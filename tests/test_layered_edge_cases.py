"""Edge-case sweep for the CR 613 layered-effects machinery.

Each test pins a specific layer interaction the engine must get right,
with the named historical Magic card(s) that motivated the test in the
docstring. Tests that pin gaps in the current implementation are
marked ``xfail`` with a precise reason — fixing those is the next
chunk of work.

Index of cases:

A. Same-layer timestamp ordering
B. Lose-all-abilities timestamp ordering (Humility shape)
C. Layer 1 (copy) absorbing source's history
D. Layer 4 (type) flowing into other layers
E. Layer 7 sublayer composition
F. Lifetime / expiration corners
"""

from __future__ import annotations

import pytest

from mtg_bot.actions import (
    apply_aura_static_grants_on_attach,
    apply_clone_enters_as_copy_replacement,
    drain_stack,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.base import CardPrinting, ManaCost, make_basic_land
from mtg_bot.cards.demo_layers import (
    CLONE, DRYAD_OF_THE_ILYSIAN_GROVE, LIGNIFY, MAGICAL_HACK,
    SCUTTLEMUTT, WHITE_KNIGHT,
)
from mtg_bot.effects.generic import (
    MagicalHackTextChangeEffect, ScuttlemuttColorChangeUEOT,
)
from mtg_bot.game import (
    GameState, Player, StackItem, Zone,
    effective_activated_abilities, effective_colors, effective_keywords,
    effective_land_produces, effective_power, effective_subtypes,
    effective_toughness, effective_triggered_abilities,
    is_creature_now,
)
from mtg_bot.turn import Step, destroy


class _PickFirst(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_mana_color(self, state, player_id, options):
        return options[0]


class _PickColor(Agent):
    def __init__(self, color: str):
        self.color = color

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_mana_color(self, state, player_id, options):
        return self.color if self.color in options else options[0]


def _new_state(agent: Agent | None = None) -> GameState:
    state = GameState()
    a = agent or _PickFirst()
    state.players.append(Player(id=0, agent=a))
    state.players.append(Player(id=1, agent=a))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _attach(state, aura, target):
    aura.attached_to = target.id
    apply_aura_static_grants_on_attach(state, aura, target, aura.controller_id)


# =====================================================================
# A. Same-layer timestamp ordering
# =====================================================================


def test_two_lignifies_same_target_latest_wins():
    """Two Lignifies on the same creature: layer-7a entries stack;
    latest timestamp's set_base_pt wins. Both are 0/4 so the result
    is the same numerically, but it pins the timestamp-walking
    logic."""
    state = _new_state()
    a1 = _put(state, LIGNIFY, owner_id=0)
    a2 = _put(state, LIGNIFY, owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    _attach(state, a1, bear)
    _attach(state, a2, bear)

    pt_entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 7 and ce.kind == "set_base_pt"
        and ce.target_id == bear.id
    ]
    assert len(pt_entries) == 2
    assert pt_entries[0].timestamp < pt_entries[1].timestamp
    assert effective_power(state, bear) == 0
    assert effective_toughness(state, bear) == 4


def test_painter_then_scuttlemutt_set_overrides_add():
    """Layer 5 mixed: a synthetic add_colors entry written first
    (Painter's Servant shape), then Scuttlemutt's set_colors. Within
    layer 5, set_colors at a NEWER timestamp REPLACES the entire
    color set — not unions onto the add result.
    """
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    # Step 1: a Painter's-Servant-style add_colors entry (synthetic).
    state.add_continuous_effect(
        source_id=bear.id, layer=5, kind="add_colors",
        target_id=bear.id, params=(frozenset({"B"}),),
        description="(synthetic) add black",
    )
    # Now bear is G+B.
    assert effective_colors(state, bear) == frozenset({"G", "B"})

    # Step 2: Scuttlemutt sets color to {R}.
    scuttle = _put(state, SCUTTLEMUTT, owner_id=0)
    state.players[0].agent = _PickColor("R")
    state.resolving_source = scuttle
    ScuttlemuttColorChangeUEOT().resolve(
        state, 0, (("creature", bear.id),),
    )

    # Newer set replaces — bear is just R, not R+B.
    assert effective_colors(state, bear) == frozenset({"R"})


def test_set_then_add_unions_correctly():
    """Layer 5: set_colors first, add_colors later. The newer add
    walks AFTER the set, so the result is set-union-add."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    # Step 1: Scuttlemutt sets to {R}.
    scuttle = _put(state, SCUTTLEMUTT, owner_id=0)
    state.players[0].agent = _PickColor("R")
    state.resolving_source = scuttle
    ScuttlemuttColorChangeUEOT().resolve(
        state, 0, (("creature", bear.id),),
    )
    assert effective_colors(state, bear) == frozenset({"R"})
    # Step 2: synthetic Painter's-Servant-style add_colors entry.
    state.add_continuous_effect(
        source_id=bear.id, layer=5, kind="add_colors",
        target_id=bear.id, params=(frozenset({"B"}),),
        description="(synthetic) add black",
    )
    # Newer add unions onto set — bear is R+B.
    assert effective_colors(state, bear) == frozenset({"R", "B"})


# =====================================================================
# B. Lose-all-abilities timestamp ordering (Humility shape)
# =====================================================================


def test_lignify_then_anthem_keyword_grant_anthem_wins_if_newer():
    """CR 613.4: within layer 6, effects apply in timestamp order. A
    'lose all abilities' applied first, followed by a NEWER 'gains
    flying' grant, should result in a creature with flying (the
    later grant takes effect after the wipe). Humility + Lord of
    Atlantis shape.

    Pin the correct CR-613 outcome. Today our `_has_lose_all_abilities`
    short-circuits regardless of timestamp; this test is expected to
    fail and motivates the fix.
    """
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    _attach(state, aura, bear)
    # After Lignify: no keywords.
    assert effective_keywords(state, bear) == frozenset()

    # Synthetic anthem-style layer-6 keyword grant at a NEWER timestamp.
    # grant_keyword's contract is params=(keyword_string,) — one entry
    # per keyword (matches GameState.grant_keywords_ueot).
    state.add_continuous_effect(
        source_id=bear.id, layer=6, kind="grant_keyword",
        target_id=bear.id, params=("flying",),
        description="(synthetic) anthem grants flying",
    )

    # Per CR, the newer grant should re-add flying after the older
    # lose_all_abilities applies.
    assert "flying" in effective_keywords(state, bear)


def test_anthem_then_lignify_lignify_wins_if_newer():
    """Reverse: anthem at older timestamp, Lignify newer. Lignify's
    wipe applies AFTER the anthem grant, so the creature has no
    keywords."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)
    # Sky Sentinel has flying printed — but pin the test on a granted
    # keyword (more representative of the Humility-anthem case).
    state.add_continuous_effect(
        source_id=bear.id, layer=6, kind="grant_keyword",
        target_id=bear.id, params=("trample",),
        description="(synthetic) anthem grants trample",
    )
    assert "trample" in effective_keywords(state, bear)
    # Now Lignify, newer.
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, bear)

    assert effective_keywords(state, bear) == frozenset()


# =====================================================================
# C. Layer 1 (copy) absorbing source's history
# =====================================================================


def test_clone_of_lignified_creature_ignores_lignify():
    """Already covered in test_clone but pinned here too: copy-effect
    copies the printing, not the layer-2..7 history of the source."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, bear)
    clone = state.new_object(CLONE, 0, Zone.STACK)
    apply_clone_enters_as_copy_replacement(state, clone, controller_id=0)
    state.battlefield.append(clone)
    assert effective_power(state, clone) == 2
    assert effective_toughness(state, clone) == 2


def test_lignify_attached_to_clone_after_copy_works():
    """Clone enters as a copy of Bear. Lignify then attaches to the
    Clone. The Clone (now a Bear printing) becomes 0/4 Treefolk no
    abilities. Layer 1 → Layer 4/6/7 composition.
    """
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    clone = state.new_object(CLONE, 0, Zone.STACK)
    apply_clone_enters_as_copy_replacement(state, clone, controller_id=0)
    state.battlefield.append(clone)
    # Clone is now a 2/2 Wild Bear.
    assert effective_power(state, clone) == 2

    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, clone)

    assert effective_power(state, clone) == 0
    assert effective_toughness(state, clone) == 4
    assert "Treefolk" in effective_subtypes(state, clone)
    assert effective_keywords(state, clone) == frozenset()


# =====================================================================
# D. Layer 4 (type) flowing into other layers
# =====================================================================


def test_magus_alone_makes_nonbasic_land_a_mountain():
    """Magus of the Moon: a nonbasic land's effective subtypes are
    set to ``("Mountain",)`` and it produces {R}."""
    from mtg_bot.cards.special_guests import SPECIAL_GUESTS_EOE

    state = _new_state()
    # Build a synthetic nonbasic land — a Forest+Mountain dual.
    from mtg_bot.cards.base import CardPrinting, ManaCost
    dual = CardPrinting(
        name="Stomping Dual",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Land — Forest Mountain",
        supertypes=(),  # NOT basic
        card_types=("Land",),
        subtypes=("Forest", "Mountain"),
        produces=frozenset({"R", "G"}),
    )
    land = state.new_object(dual, 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    land.etb_timestamp = 1
    # Magus of the Moon enters at a later timestamp.
    magus = state.new_object(
        SPECIAL_GUESTS_EOE["Magus of the Moon"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(magus)
    magus.etb_timestamp = 10

    subs = effective_subtypes(state, land)
    # Magus replaces the basic-land-type subtypes with Mountain.
    assert "Mountain" in subs
    assert "Forest" not in subs
    assert effective_land_produces(state, land) == frozenset({"R"})


def test_dryad_alone_lands_become_every_basic_type():
    """Dryad of the Ilysian Grove: each land you control gains all
    five basic land types, so it taps for any color."""
    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    forest.etb_timestamp = 1
    dryad = _put(state, DRYAD_OF_THE_ILYSIAN_GROVE, owner_id=0)
    dryad.etb_timestamp = 10

    subs = effective_subtypes(state, forest)
    assert "Forest" in subs  # printed type still present
    assert "Plains" in subs
    assert "Island" in subs
    assert "Swamp" in subs
    assert "Mountain" in subs
    assert effective_land_produces(state, forest) == frozenset(
        {"W", "U", "B", "R", "G"}
    )


def test_magus_older_then_dryad_newer_lands_have_all_basic_types():
    """The famous interaction. Magus enters first (older timestamp),
    Dryad enters second (newer timestamp). Per CR 613.4 layer-4
    timestamp ordering:

      T1 (Magus): set basic-land-type subtypes to ("Mountain",) on
        every nonbasic land.
      T2 (Dryad): add all five basic land types to every land its
        controller controls — appends to whatever the post-Magus
        subtype list is.

    Result: nonbasic lands have Mountain (from Magus, surviving as
    one of the basics) plus Plains, Island, Swamp, Forest (added
    by Dryad). All five colors producible.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards.special_guests import SPECIAL_GUESTS_EOE

    state = _new_state()
    # Nonbasic Forest+Mountain dual on the battlefield.
    dual = CardPrinting(
        name="Stomping Dual",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Land — Forest Mountain",
        supertypes=(),
        card_types=("Land",),
        subtypes=("Forest", "Mountain"),
        produces=frozenset({"R", "G"}),
    )
    land = state.new_object(dual, 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    land.etb_timestamp = 1
    # T2: Magus of the Moon (older effect on the battlefield).
    magus = state.new_object(
        SPECIAL_GUESTS_EOE["Magus of the Moon"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(magus)
    magus.etb_timestamp = 5
    # T3: Dryad (newer effect).
    dryad = _put(state, DRYAD_OF_THE_ILYSIAN_GROVE, owner_id=0)
    dryad.etb_timestamp = 20

    subs = effective_subtypes(state, land)
    # Mountain survives (Magus set, Dryad re-adds it as one of five).
    assert "Mountain" in subs
    # Forest is gone after Magus, but ADDED back by Dryad.
    assert "Forest" in subs
    assert "Plains" in subs
    assert "Island" in subs
    assert "Swamp" in subs
    assert effective_land_produces(state, land) == frozenset(
        {"W", "U", "B", "R", "G"}
    )


def test_dryad_older_then_magus_newer_lands_become_just_mountains():
    """Reverse timestamps: Dryad enters first, Magus enters later.

      T1 (Dryad): add all five basic land types to every land you
        control — Forest dual gets Plains/Island/Swamp/Forest (Mountain
        already there).
      T2 (Magus): set basic-land-type subtypes to ("Mountain",) on
        every nonbasic land — drops the four other basics.

    Result: nonbasic land has just Mountain. Tap for {R} only.
    This is the famous "Blood Moon beats Dryad" outcome when the
    Magus/Blood Moon comes down second.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards.special_guests import SPECIAL_GUESTS_EOE

    state = _new_state()
    dual = CardPrinting(
        name="Stomping Dual",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Land — Forest Mountain",
        supertypes=(),
        card_types=("Land",),
        subtypes=("Forest", "Mountain"),
        produces=frozenset({"R", "G"}),
    )
    land = state.new_object(dual, 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    land.etb_timestamp = 1
    # T2: Dryad first.
    dryad = _put(state, DRYAD_OF_THE_ILYSIAN_GROVE, owner_id=0)
    dryad.etb_timestamp = 5
    # T3: Magus later (newer).
    magus = state.new_object(
        SPECIAL_GUESTS_EOE["Magus of the Moon"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(magus)
    magus.etb_timestamp = 20

    subs = effective_subtypes(state, land)
    # Magus's set replaces all basic-land-type subtypes with just
    # Mountain — Dryad's earlier adds are wiped because layer 4
    # timestamps run T2 (Dryad add) -> T3 (Magus set).
    assert "Mountain" in subs
    assert "Forest" not in subs
    assert "Plains" not in subs
    assert "Island" not in subs
    assert "Swamp" not in subs
    assert effective_land_produces(state, land) == frozenset({"R"})


def test_tractor_beam_on_dryad_layer2_then_layer4_dependency():
    """Tractor Beam swaps Dryad's controller (layer 2). Dryad's
    "lands YOU CONTROL" static (synthesized at layer 4) then keys
    off the NEW controller — its layer-4 effect now applies to the
    new controller's lands, not the old controller's. Tests the
    layer-2 → layer-4 dependency: layer 2 must be resolved before
    layer 4 reads it.
    """
    from mtg_bot.cards import EOE_SPELLS

    state = _new_state()
    # P0 has a Forest. P1 has a Forest. Dryad starts under P1's control.
    p0_forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    p0_forest.etb_timestamp = 1
    p1_forest = _put(state, make_basic_land("Forest", "G"), owner_id=1)
    p1_forest.controller_id = 1
    p1_forest.etb_timestamp = 2
    dryad = _put(state, DRYAD_OF_THE_ILYSIAN_GROVE, owner_id=1)
    dryad.controller_id = 1
    dryad.etb_timestamp = 5

    # Pre-swap: Dryad's effect applies to P1's Forest, not P0's.
    assert "Plains" in effective_subtypes(state, p1_forest)
    assert "Plains" not in effective_subtypes(state, p0_forest)

    # P0 attaches a Tractor Beam to Dryad — P0 now controls Dryad.
    aura = _put(state, EOE_SPELLS["Tractor Beam"], owner_id=0)
    _attach(state, aura, dryad)
    assert dryad.controller_id == 0

    # Now Dryad's "lands you control" follows the new controller.
    assert "Plains" in effective_subtypes(state, p0_forest)
    assert "Plains" not in effective_subtypes(state, p1_forest)


def test_lignified_tractor_beam_keeps_control_grant():
    """A Tractor Beam that gets Humility'd / Lignified AFTER
    attaching keeps its layer-2 control grant on the enchanted
    permanent. Per CR 613.1 strict layer order, layer 2 runs before
    layer 6 — the control grant is already applied by the time the
    layer-6 wipe happens, and the wipe does not retroactively undo
    layers below it.
    """
    from mtg_bot.cards import EOE_SPELLS
    from mtg_bot.game import effective_controller

    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    aura = _put(state, EOE_SPELLS["Tractor Beam"], owner_id=0)
    _attach(state, aura, bear)
    assert effective_controller(state, bear) == 0

    state.add_continuous_effect(
        source_id=aura.id, layer=6, kind="lose_all_abilities",
        target_id=aura.id, params=(),
        description="(test) Tractor Beam loses all abilities",
    )

    # Layer 2 already applied; layer 6 wipe doesn't undo it.
    assert effective_controller(state, bear) == 0


def test_two_lignified_magi_still_collapse_lands():
    """Two Magus-like sources on the battlefield, both Lignified.
    Per CR strict layer order, their layer-4 type-changing effects
    still apply — nonbasic lands are STILL Mountains. The layer-6
    wipes only target the Magi themselves; the lands are not
    Lignified.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards.special_guests import SPECIAL_GUESTS_EOE

    state = _new_state()
    dual = CardPrinting(
        name="Stomping Dual", mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Land — Forest Mountain",
        supertypes=(), card_types=("Land",),
        subtypes=("Forest", "Mountain"),
        produces=frozenset({"R", "G"}),
    )
    land = state.new_object(dual, 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    land.etb_timestamp = 1
    magus_a = state.new_object(
        SPECIAL_GUESTS_EOE["Magus of the Moon"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(magus_a)
    magus_a.etb_timestamp = 5
    magus_b = state.new_object(
        SPECIAL_GUESTS_EOE["Magus of the Moon"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(magus_b)
    magus_b.etb_timestamp = 6
    assert effective_land_produces(state, land) == frozenset({"R"})

    # Lignify both Magi.
    state.add_continuous_effect(
        source_id=99, layer=6, kind="lose_all_abilities",
        target_id=magus_a.id, params=(),
        description="(test) Lignify on magus_a",
    )
    state.add_continuous_effect(
        source_id=98, layer=6, kind="lose_all_abilities",
        target_id=magus_b.id, params=(),
        description="(test) Lignify on magus_b",
    )

    # Layer 4 still applies — dual is still Mountain.
    assert effective_land_produces(state, land) == frozenset({"R"})


def test_two_dryads_idempotent_subtype_add():
    """Two Dryads on the battlefield don't double-add subtypes.
    Lands have each basic type once — not five copies."""
    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    forest.etb_timestamp = 1
    d1 = _put(state, DRYAD_OF_THE_ILYSIAN_GROVE, owner_id=0)
    d1.etb_timestamp = 5
    d2 = _put(state, DRYAD_OF_THE_ILYSIAN_GROVE, owner_id=0)
    d2.etb_timestamp = 6

    subs = effective_subtypes(state, forest)
    assert subs.count("Plains") == 1
    assert subs.count("Island") == 1
    # Forest appears once (printed) — Dryad's add_subtype suppresses
    # duplicates.
    assert subs.count("Forest") == 1


def test_magus_leaves_play_lands_revert_to_printed():
    """When Magus leaves the battlefield, the synthesized layer-4
    set_basic_land_subtype effect stops contributing, and lands
    revert to their printed subtypes / produces.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards.special_guests import SPECIAL_GUESTS_EOE

    state = _new_state()
    dual = CardPrinting(
        name="Stomping Dual", mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Land — Forest Mountain",
        supertypes=(), card_types=("Land",),
        subtypes=("Forest", "Mountain"),
        produces=frozenset({"R", "G"}),
    )
    land = state.new_object(dual, 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    land.etb_timestamp = 1
    magus = state.new_object(
        SPECIAL_GUESTS_EOE["Magus of the Moon"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(magus)
    magus.etb_timestamp = 5
    assert effective_land_produces(state, land) == frozenset({"R"})

    destroy(state, magus)

    # Land's effective subtypes derive purely from the printing.
    subs = effective_subtypes(state, land)
    assert subs == ("Forest", "Mountain")
    assert effective_land_produces(state, land) == frozenset({"R", "G"})


def test_lignified_dryad_still_grants_basic_land_types_per_cr():
    """The famous Dryad of the Ilysian Grove + Humility ruling:
    "Under Humility, Dryad becomes a 1/1 creature with no
    abilities. However, because the Dryad's ability to make lands
    all basic land types applies in Layer 4 (type-changing) and
    Humility applies in Layer 6 (ability-removing), lands STILL
    retain all basic land types and the ability to tap for any
    color." (Layer 4 runs before layer 6 in CR 613.1, so Dryad's
    layer-4 contribution is already in effect by the time the
    layer-6 wipe of Dryad's abilities happens.)
    """
    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    forest.etb_timestamp = 1
    dryad = _put(state, DRYAD_OF_THE_ILYSIAN_GROVE, owner_id=0)
    dryad.etb_timestamp = 5
    assert effective_land_produces(state, forest) == frozenset(
        {"W", "U", "B", "R", "G"}
    )

    # Lignify the Dryad — wipes its abilities at layer 6.
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, dryad)

    # Dryad's layer-4 effect still applies. Lands keep all 5 types.
    subs = effective_subtypes(state, forest)
    assert "Plains" in subs
    assert "Island" in subs
    assert "Swamp" in subs
    assert "Mountain" in subs
    assert "Forest" in subs
    assert effective_land_produces(state, forest) == frozenset(
        {"W", "U", "B", "R", "G"}
    )


def test_lignified_magus_still_collapses_nonbasic_lands_per_cr():
    """Magus of the Moon's "nonbasic lands are Mountains" is layer 4.
    A Lignified Magus still applies its layer-4 type-changing
    effect — strict layer order says layer 4 runs before layer 6.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards.special_guests import SPECIAL_GUESTS_EOE

    state = _new_state()
    dual = CardPrinting(
        name="Stomping Dual",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Land — Forest Mountain",
        supertypes=(),
        card_types=("Land",),
        subtypes=("Forest", "Mountain"),
        produces=frozenset({"R", "G"}),
    )
    land = state.new_object(dual, 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    land.etb_timestamp = 1
    magus = state.new_object(
        SPECIAL_GUESTS_EOE["Magus of the Moon"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(magus)
    magus.etb_timestamp = 5
    assert effective_land_produces(state, land) == frozenset({"R"})

    # Lignify the Magus.
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, magus)

    # Layer-4 type-change still applies — dual is still Mountain.
    subs = effective_subtypes(state, land)
    assert "Mountain" in subs
    assert "Forest" not in subs
    assert effective_land_produces(state, land) == frozenset({"R"})


def test_lignified_sliver_lord_still_grants_anthem_keywords_per_dependency():
    """Thrumming Hivepool's anthem ("Slivers you control have
    double strike and haste") is a layer-6 keyword grant. Per CR
    613.7 within-layer dependency, the lord's anthem still applies
    to Slivers even when the lord itself is Lignified — the wipe
    targets the LORD, not the Slivers, and the dependency rule
    orders the lord's anthem before the wipe.
    """
    from mtg_bot.cards.eoe_spells import EOE_SPELLS

    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    state.add_continuous_effect(
        source_id=bear.id, layer=4, kind="add_subtype",
        target_id=bear.id, params=("Sliver",),
        description="(test) Bear is a Sliver",
    )
    hivepool = _put(state, EOE_SPELLS["Thrumming Hivepool"], owner_id=0)
    kws = effective_keywords(state, bear)
    assert "haste" in kws
    assert "double strike" in kws

    # Lignify the Hivepool synthetically (Thrumming Hivepool is an
    # Artifact and Lignify only enchants creatures, so we write the
    # lose_all_abilities registry entry directly to exercise the
    # post-wipe behavior without arguing about target legality).
    state.add_continuous_effect(
        source_id=999, layer=6, kind="lose_all_abilities",
        target_id=hivepool.id, params=(),
        description="(test) Hivepool loses all abilities",
    )

    # Hivepool wiped, but its anthem keywords still apply to Slivers
    # via the dependency rule. The wipe targets the lord; the
    # granted keywords on the Slivers are unaffected.
    kws = effective_keywords(state, bear)
    assert "haste" in kws
    assert "double strike" in kws


def test_magus_and_dryad_both_lignified_lands_keep_all_basic_types():
    """Both Magus and Dryad on the battlefield, both Lignified.
    Per CR 613.1 strict layer order, layer 4 runs before layer 6 —
    Magus's set-to-Mountain and Dryad's add-all-five basic types
    BOTH apply at layer 4 regardless of any layer-6 wipe on either
    source. Lands have all five basic land types and tap for any
    color (Magus older + Dryad newer ordering: Magus sets to
    Mountain, Dryad adds the other four).
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards.special_guests import SPECIAL_GUESTS_EOE

    state = _new_state()
    dual = CardPrinting(
        name="Stomping Dual", mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Land — Forest Mountain",
        supertypes=(), card_types=("Land",),
        subtypes=("Forest", "Mountain"),
        produces=frozenset({"R", "G"}),
    )
    land = state.new_object(dual, 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    land.etb_timestamp = 1
    magus = state.new_object(
        SPECIAL_GUESTS_EOE["Magus of the Moon"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(magus)
    magus.etb_timestamp = 5
    dryad = _put(state, DRYAD_OF_THE_ILYSIAN_GROVE, owner_id=0)
    dryad.etb_timestamp = 10

    # Lignify both.
    aura1 = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura1, magus)
    aura2 = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura2, dryad)

    # Both layer-4 statics still contribute — lands have all 5
    # basic types and produce all 5 colors.
    assert effective_land_produces(state, land) == frozenset(
        {"W", "U", "B", "R", "G"}
    )


def test_lignified_anthem_lord_keeps_keyword_grant_drops_pt_bonus():
    """The Lord-of-Atlantis-vs-Humility shape, using cards in our
    pool. Memorial Team Leader's static "Other creatures you
    control get +1/+0" mixes a layer-6 effect (none here — no
    keyword grant) and a layer-7c P/T bonus.

    Synthesize a creature anthem with BOTH a +1/+0 P/T bonus AND a
    haste keyword grant on the same static ability so both layer
    sides are exercised. Lignify the anthem source. Per CR strict
    layer order:
      - Layer 6 keyword grant (haste): still applies via dependency
        rule (the wipe targets the lord, not the recipients).
      - Layer 7c P/T bonus (+1/+0): does NOT apply (layer 6 has
        run by the time layer 7c reads — the lord's static doesn't
        exist anymore).
    """
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.base import StaticAbility, StaticScope

    anthem_lord = make_creature(
        "Test Anthem Lord", "{2}{R}", 3, 3,
        static_abilities=(
            StaticAbility(
                scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
                power_bonus=1,
                toughness_bonus=0,
                granted_keywords=frozenset({"haste"}),
            ),
        ),
    )

    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    lord = _put(state, anthem_lord, owner_id=0)
    # Pre-Lignify: Bear is 3/2 with haste (+1/+0 + haste from lord).
    assert effective_power(state, bear) == 3
    assert effective_toughness(state, bear) == 2
    assert "haste" in effective_keywords(state, bear)

    # Lignify the lord (synthetic registry write, since the test
    # creature isn't in the EoE pool and we want to exercise the
    # post-wipe split cleanly).
    state.add_continuous_effect(
        source_id=999, layer=6, kind="lose_all_abilities",
        target_id=lord.id, params=(),
        description="(test) Lord loses all abilities",
    )

    # Layer 6 keyword grant survives: Bear still has haste.
    assert "haste" in effective_keywords(state, bear)
    # Layer 7c P/T bonus drops: Bear is back to 2/2.
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2


def test_lignified_equipment_drops_pt_rider_keeps_keyword_rider():
    """An Equipment with both a P/T rider and a keyword rider
    follows the same layer split as static-ability anthems. A
    Lignified Equipment keeps granting its keyword rider but drops
    the P/T rider — the rider lives in ``equipment_bonuses`` on
    the printing, but the layer attribution is the same.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost

    eq = CardPrinting(
        name="Test Equipment",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Artifact — Equipment",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Equipment",),
        # +1/+1 P/T rider (layer 7c) + first strike (layer 6).
        equipment_bonuses=(1, 1, frozenset({"first strike"})),
    )

    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    equipment = _put(state, eq, owner_id=0)
    equipment.attached_to = bear.id
    # Pre-Lignify.
    assert effective_power(state, bear) == 3
    assert effective_toughness(state, bear) == 3
    assert "first strike" in effective_keywords(state, bear)

    state.add_continuous_effect(
        source_id=999, layer=6, kind="lose_all_abilities",
        target_id=equipment.id, params=(),
        description="(test) Equipment loses all abilities",
    )

    # Keyword rider survives the wipe.
    assert "first strike" in effective_keywords(state, bear)
    # P/T rider drops at layer 7c.
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2


def test_lignified_dominion_bracelet_keeps_granted_activated_ability():
    """The Dominion Bracelet's "equipped creature has [activated
    ability]" is a layer-6 keyword/ability grant. Per CR 613.7
    within-layer dependency, a Lignified Bracelet still grants the
    ability — the wipe targets the Bracelet, not the equipped
    creature.
    """
    from mtg_bot.cards import EOE_SPELLS

    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    bracelet = _put(
        state, EOE_SPELLS["The Dominion Bracelet"], owner_id=0,
    )
    bracelet.attached_to = bear.id
    abilities = effective_activated_abilities(state, bear)
    assert len(abilities) == 1

    state.add_continuous_effect(
        source_id=bracelet.id, layer=6, kind="lose_all_abilities",
        target_id=bracelet.id, params=(),
        description="(test) Bracelet loses all abilities",
    )

    # Per CR dependency, the granted ability still applies on the
    # equipped creature.
    abilities = effective_activated_abilities(state, bear)
    assert len(abilities) == 1


def test_lignify_on_tarmogoyf_style_cda_overrides_with_0_4():
    """Tarmogoyf-vs-Diminish / Turn-to-Frog ruling. Cosmogoyf has a
    characteristic-defining ability (CDA) at layer 7a that sets
    P/T = N / N+1 where N is cards in exile. Lignify's
    ``set_base_pt`` is at layer 7b. Per CR strict layer order,
    7b runs after 7a, so Lignify's 0/4 overrides Cosmogoyf's CDA.

    Even if Lignify also wipes Cosmogoyf's CDA at layer 6 (so 7a
    is empty), the layer-7b set still gives 0/4. Both reasonings
    converge on 0/4.
    """
    from mtg_bot.cards.eoe_spells import EOE_SPELLS

    state = _new_state()
    cosmogoyf = _put(state, EOE_SPELLS["Cosmogoyf"], owner_id=0)
    # No exile yet → Cosmogoyf is 0/1.
    assert effective_power(state, cosmogoyf) == 0
    assert effective_toughness(state, cosmogoyf) == 1

    # Add cards to exile so Cosmogoyf grows to 3/4.
    state.players[0].exile.extend([cosmogoyf.printing] * 3)
    assert effective_power(state, cosmogoyf) == 3
    assert effective_toughness(state, cosmogoyf) == 4

    # Lignify Cosmogoyf — layer-7b set should override the CDA.
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, cosmogoyf)

    assert effective_power(state, cosmogoyf) == 0
    assert effective_toughness(state, cosmogoyf) == 4
    # Even if exile grows further, the 7b override holds.
    state.players[0].exile.extend([cosmogoyf.printing] * 5)
    assert effective_power(state, cosmogoyf) == 0
    assert effective_toughness(state, cosmogoyf) == 4


def test_lignified_animated_manland_keeps_animation_at_1_1():
    """A manland animation grants the land a layer-7b set_base_pt
    entry with ``expires_at="cleanup"``. Lignify writes a NEWER
    layer-7b set_base_pt entry (0/4) and a layer-6 lose_all_abilities
    entry. Per CR strict layer order:
      - Layer 4: animation makes the land a creature.
      - Layer 6: Lignify wipes any abilities the land would have
        — but the animation is a granted UEOT continuous effect
        already in the registry, not a printed static, so it's
        unaffected.
      - Layer 7b: Lignify's 0/4 (newer) wins over animation's 4/4.
    Result: the manland is a 0/4 Treefolk creature with no
    abilities.
    """
    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    forest.etb_timestamp = 1
    state.grant_become_creature_ueot(
        source_id=forest.id, target_id=forest.id,
        power=4, toughness=4,
        subtype="Elemental",
        description="manland animation",
    )
    assert effective_power(state, forest) == 4
    assert effective_toughness(state, forest) == 4
    assert is_creature_now(forest)

    # Lignify the animated manland.
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, forest)

    # Lignify's 7b set is newer → 0/4. Layer-4 effects (animation
    # add_type, animation add_subtype + Lignify add_subtype) all
    # apply — the manland is still a creature with all its
    # Elemental + Treefolk subtypes.
    assert effective_power(state, forest) == 0
    assert effective_toughness(state, forest) == 4
    assert is_creature_now(forest)
    subs = effective_subtypes(state, forest)
    assert "Elemental" in subs
    assert "Treefolk" in subs


def test_blood_moon_urborg_dependency_GAP():
    """KNOWN GAP: CR 613.7 same-layer dependency rule isn't
    implemented in our engine. Blood Moon (synthesized as a
    layer-4 set_basic_land_subtype Mountain) and Urborg-style
    "all lands are Swamps" (synthesized as layer-4 add_subtype
    Swamp on every land) both apply at layer 4.

    Per CR dependency, Urborg's effect DEPENDS on Blood Moon's
    effect (Blood Moon makes Urborg a Mountain, which removes
    Urborg's ability — the dependency rule says Urborg waits
    until after Blood Moon applies, then doesn't apply because
    its ability was wiped). Result: Blood Moon ALWAYS wins
    regardless of timestamps.

    Our engine uses simple timestamp order within a layer. With
    Blood Moon older + Urborg newer, our engine CORRECTLY puts
    the Mountain (Blood Moon) on the land, then ADDS Swamp on top
    (Urborg). The CR-correct result is Mountain only.

    This test pins the current (incorrect-by-CR) behavior so a
    future dependency-rule implementation has a target to flip.
    Not labeled xfail since it documents observable engine
    behavior, not aspirational behavior.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost

    state = _new_state()
    # Synthesize a nonbasic land with no printed basic land subtypes.
    nonbasic = CardPrinting(
        name="Strip Mine",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Land",
        supertypes=(),
        card_types=("Land",),
        subtypes=(),
        produces=frozenset(),
    )
    land = state.new_object(nonbasic, 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    land.etb_timestamp = 1

    # Blood Moon (older, T=10): set basic land subtype to Mountain.
    state.add_continuous_effect(
        source_id=999, layer=4, kind="set_basic_land_subtype",
        target_id=land.id, params=("Mountain",),
        description="(synthetic) Blood Moon",
    )
    # Urborg-style (newer, T=11): add Swamp to every land.
    state.add_continuous_effect(
        source_id=998, layer=4, kind="add_subtype",
        target_id=land.id, params=("Swamp",),
        description="(synthetic) Urborg adds Swamp",
    )

    subs = effective_subtypes(state, land)
    # Engine result (timestamp order): Mountain (set) then add Swamp →
    # land is Mountain + Swamp, taps for {R, B}.
    assert "Mountain" in subs
    assert "Swamp" in subs
    assert effective_land_produces(state, land) == frozenset({"R", "B"})

    # CR-correct result would be Mountain only via dependency, but
    # we don't implement that yet.


def test_clone_of_dryad_grants_basic_land_types_too():
    """Clone copies Dryad's printing including the
    ``grants_all_basic_land_types_to_lands_you_control`` flag, so
    the Clone (now a Dryad) ALSO contributes the layer-4 add_subtype
    effect to lands its controller controls.
    """
    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    forest.etb_timestamp = 1
    real_dryad = _put(state, DRYAD_OF_THE_ILYSIAN_GROVE, owner_id=0)
    real_dryad.etb_timestamp = 5
    clone = state.new_object(CLONE, 0, Zone.STACK)
    apply_clone_enters_as_copy_replacement(state, clone, controller_id=0)
    state.battlefield.append(clone)
    clone.etb_timestamp = 10

    # Both Dryad and Clone-of-Dryad contribute. Forest still has all
    # five basic land types.
    subs = effective_subtypes(state, forest)
    assert "Plains" in subs
    assert "Island" in subs
    assert effective_land_produces(state, forest) == frozenset(
        {"W", "U", "B", "R", "G"}
    )

    # Removing the original Dryad: the Clone keeps the static going.
    destroy(state, real_dryad)
    subs = effective_subtypes(state, forest)
    assert "Plains" in subs
    assert effective_land_produces(state, forest) == frozenset(
        {"W", "U", "B", "R", "G"}
    )


def test_dryad_does_not_affect_opponents_lands():
    """Dryad's "lands you control" filter keeps it scoped to its
    controller. An opponent's basic Forest is unaffected."""
    state = _new_state()
    p0_forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    p0_forest.etb_timestamp = 1
    p1_forest = _put(state, make_basic_land("Forest", "G"), owner_id=1)
    p1_forest.controller_id = 1
    p1_forest.etb_timestamp = 2
    dryad = _put(state, DRYAD_OF_THE_ILYSIAN_GROVE, owner_id=0)
    dryad.etb_timestamp = 10

    p0_subs = effective_subtypes(state, p0_forest)
    p1_subs = effective_subtypes(state, p1_forest)
    assert "Plains" in p0_subs  # Dryad applies to your land
    assert "Plains" not in p1_subs  # not to opponent's


def test_synthetic_added_subtype_picked_up_by_subtype_keyed_anthem():
    """A Conspiracy-style layer-4 ``add_subtype`` entry adds "Sliver"
    to a non-Sliver creature. Thrumming Hivepool's anthem ("Slivers
    you control have double strike and haste") should pick up the
    granted Sliver subtype via ``effective_subtypes``, not just
    printed subtypes."""
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.cards.eoe_spells import EOE_SPELLS

    state = _new_state()
    hivepool = _put(state, EOE_SPELLS["Thrumming Hivepool"], owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    # No layered effect → bear is no Sliver, no haste/double strike.
    assert "haste" not in effective_keywords(state, bear)
    assert "double strike" not in effective_keywords(state, bear)
    # Synthetic Conspiracy-style add: Bear is also a Sliver.
    state.add_continuous_effect(
        source_id=bear.id, layer=4, kind="add_subtype",
        target_id=bear.id, params=("Sliver",),
        description="(synthetic) Conspiracy-style adds Sliver",
    )
    # Effective subtypes now include Sliver — anthem should grant.
    assert "Sliver" in effective_subtypes(state, bear)
    assert "haste" in effective_keywords(state, bear)
    assert "double strike" in effective_keywords(state, bear)


def test_subtype_keyed_read_uses_effective_subtypes():
    """A subtype-keyed query (e.g., 'Slivers count their lords' — but
    we don't have a real one in scope here) should read
    ``effective_subtypes``, not ``printing.subtypes``. Pin via Lignify
    + a subtype-filtered effect target lookup.

    Specifically: Lignify makes a Bear into a Treefolk. A
    ScuttlemuttColorChangeUEOT.legal_targets currently uses
    ``printing.is_creature``. ``effective_subtypes`` adds Treefolk
    to the bear; legal_targets isn't subtype-filtered here, so this
    test pins the subtype IS visible (which any subtype-keyed
    consumer will need)."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, bear)

    # The effective subtype IS readable via the right helper.
    assert "Treefolk" in effective_subtypes(state, bear)


def test_magical_hack_then_synthetic_dryad_lands_get_all_basic_types():
    """Blood Moon + Dryad of the Ilysian Grove shape (with Magical
    Hack standing in for Blood Moon's "set type Mountain" since both
    are layer 4-ish). Sequence:

    T1: Magical Hack rewrites Forest -> Mountain (layer 3 substitute).
    T2: Synthetic Dryad-style add_subtype entries add Forest, Plains,
        Island, Swamp to the same land.

    Per our reader's order (layer 3 first, then layer 4), the Forest's
    "Forest" subtype is substituted to "Mountain" first, then layer 4
    appends the four basics. Final effective subtypes:
        {Mountain, Forest, Plains, Island, Swamp}
    Layer-3 substitution is one-shot per entry (matches against the
    *current* subtype list at substitution time), so the appended
    "Forest" by layer 4 is NOT itself substituted — that's correct
    per CR ordering (layer 3 fully resolves before layer 4 is
    consulted)."""
    state = _new_state(agent=_PickColor("R"))
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)

    # T1: Magical Hack Forest -> Mountain.
    MagicalHackTextChangeEffect().resolve(
        state, 0, (("permanent", forest.id),),
    )
    # T2: synthetic Dryad-style add_subtype entries.
    for sub in ("Forest", "Plains", "Island", "Swamp"):
        state.add_continuous_effect(
            source_id=forest.id, layer=4, kind="add_subtype",
            target_id=forest.id, params=(sub,),
            description=f"(synthetic) Dryad adds {sub}",
        )

    subs = effective_subtypes(state, forest)
    assert "Mountain" in subs
    assert "Forest" in subs
    assert "Plains" in subs
    assert "Island" in subs
    assert "Swamp" in subs
    # All five colors producible.
    assert effective_land_produces(state, forest) == frozenset(
        {"R", "G", "W", "U", "B"}
    )


def test_dryad_then_magical_hack_substitutes_added_subtype():
    """Reverse order: Dryad first, then Magical Hack. Per CR layer
    ordering, layer 3 still applies *before* layer 4 in
    ``effective_subtypes`` regardless of timestamps — layer-by-layer
    is the outer loop, timestamps are within-layer.

    So even if Dryad's add was newer than Hack's substitution, the
    final order applied here is: substitute first, then add. Forest
    -> Mountain -> add (Forest, Plains, Island, Swamp). Same result
    as the previous test.
    """
    state = _new_state(agent=_PickColor("R"))
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)

    # T1: Dryad-style adds.
    for sub in ("Forest", "Plains", "Island", "Swamp"):
        state.add_continuous_effect(
            source_id=forest.id, layer=4, kind="add_subtype",
            target_id=forest.id, params=(sub,),
            description=f"(synthetic) Dryad adds {sub}",
        )
    # T2: Magical Hack Forest -> Mountain.
    MagicalHackTextChangeEffect().resolve(
        state, 0, (("permanent", forest.id),),
    )

    subs = effective_subtypes(state, forest)
    # Layer 3 substituted "Forest" in printed subtypes ONLY; the
    # layer-4 added "Forest" remains unaffected (since substitution
    # happens before the add walk).
    assert "Mountain" in subs
    assert "Forest" in subs  # added by Dryad after substitution
    assert effective_land_produces(state, forest) == frozenset(
        {"R", "G", "W", "U", "B"}
    )


# =====================================================================
# E. Layer 7 sublayer composition
# =====================================================================


def test_lignify_plus_counters_plus_pump_compose():
    """Lignify (7b set 0/4) + 2x +1/+1 counters (7d) + +3/+3 UEOT
    pump (7c) = 0+2+3 / 4+2+3 = 5/9. Pin the composition order."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    bear.plus_one_counters = 2
    bear.temp_power_bonus = 3
    bear.temp_toughness_bonus = 3
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, bear)

    assert effective_power(state, bear) == 0 + 2 + 3
    assert effective_toughness(state, bear) == 4 + 2 + 3


def test_wandering_fumarole_switch_after_lignify():
    """Wandering Fumarole's "{0}: Switch P/T UEOT" is a layer 7e
    effect — it operates on whatever the post-7b/c/d effective P/T
    is. So a Lignified manland at 0/4 should switch to 4/0."""
    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    # Animate Forest into a 1/4 creature (manland-style) UEOT.
    state.grant_become_creature_ueot(
        source_id=forest.id, target_id=forest.id,
        power=1, toughness=4,
        description="manland animation",
    )
    # Lignify the animated land.
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, forest)
    assert effective_power(state, forest) == 0  # Lignify wins over animation
    assert effective_toughness(state, forest) == 4

    from mtg_bot.effects.generic import SwitchSourcePowerToughnessUEOT
    state.resolving_source = forest
    SwitchSourcePowerToughnessUEOT().resolve(state, 0)

    assert effective_power(state, forest) == 4
    assert effective_toughness(state, forest) == 0


def test_switch_pt_swaps_after_counters_not_just_base():
    """Layer 7e switch operates AFTER 7d counters. A Lignified bear
    (0/4 base) with a +1/+1 counter is effectively 1/5 before the
    switch — switching gives 5/1, NOT 4/0 (which would be the
    pre-counter base swap). Pins the sublayer ordering.
    """
    from mtg_bot.effects.generic import SwitchSourcePowerToughnessUEOT

    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, bear)
    bear.plus_one_counters = 1
    assert effective_power(state, bear) == 1
    assert effective_toughness(state, bear) == 5

    state.resolving_source = bear
    SwitchSourcePowerToughnessUEOT().resolve(state, 0)

    assert effective_power(state, bear) == 5
    assert effective_toughness(state, bear) == 1


def test_asymmetric_pump_before_switch_pump_applies_to_unswapped_base():
    """Titan's-Strength-style asymmetric pump (+3/+1) applied to a
    Wandering Fumarole BEFORE the switch activates. Per CR sublayer
    order, 7c (modify P/T) applies before 7e (switch):

      7b base: 1/4 (animated manland)
      7c pump: 1+3 / 4+1 = 4/5
      7e switch: 5/4

    Pinning that pump bonuses are added to BASE P/T, then the swap
    happens to the post-pump pair.
    """
    from mtg_bot.effects.generic import SwitchSourcePowerToughnessUEOT

    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    state.grant_become_creature_ueot(
        source_id=forest.id, target_id=forest.id,
        power=1, toughness=4,
        description="manland animation",
    )
    # Pump first: +3/+1 (Titan's Strength shape).
    forest.temp_power_bonus = 3
    forest.temp_toughness_bonus = 1
    assert effective_power(state, forest) == 4
    assert effective_toughness(state, forest) == 5

    state.resolving_source = forest
    SwitchSourcePowerToughnessUEOT().resolve(state, 0)

    assert effective_power(state, forest) == 5
    assert effective_toughness(state, forest) == 4


def test_asymmetric_pump_after_switch_same_result():
    """Reverse timestamp order: switch FIRST, pump LATER. Per CR
    613 the layer of the effect dominates the timestamp — 7c always
    runs before 7e regardless of when each was applied. So the
    final P/T is the same as the pump-before-switch ordering: 5/4.

    This is the key MTG-correctness guarantee the user called out:
    the asymmetric pump's bonus must be applied to the unswapped
    base, with the swap happening LAST regardless of casting order.
    """
    from mtg_bot.effects.generic import SwitchSourcePowerToughnessUEOT

    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    state.grant_become_creature_ueot(
        source_id=forest.id, target_id=forest.id,
        power=1, toughness=4,
        description="manland animation",
    )
    # Switch first.
    state.resolving_source = forest
    SwitchSourcePowerToughnessUEOT().resolve(state, 0)
    assert effective_power(state, forest) == 4
    assert effective_toughness(state, forest) == 1
    # Now apply the pump — temporally AFTER the switch, but per CR
    # layered effects 7c still applies before 7e in computation.
    forest.temp_power_bonus = 3
    forest.temp_toughness_bonus = 1

    # Same final result as the pump-then-switch test: 5/4.
    assert effective_power(state, forest) == 5
    assert effective_toughness(state, forest) == 4


def test_two_switches_cancel():
    """Two layer-7e switch_pt entries cancel — P/T returns to the
    pre-switch effective values."""
    from mtg_bot.effects.generic import SwitchSourcePowerToughnessUEOT

    state = _new_state()
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    state.grant_become_creature_ueot(
        source_id=forest.id, target_id=forest.id,
        power=1, toughness=4,
        description="manland animation",
    )
    assert (effective_power(state, forest), effective_toughness(state, forest)) \
        == (1, 4)

    state.resolving_source = forest
    SwitchSourcePowerToughnessUEOT().resolve(state, 0)
    assert (effective_power(state, forest), effective_toughness(state, forest)) \
        == (4, 1)

    SwitchSourcePowerToughnessUEOT().resolve(state, 0)
    assert (effective_power(state, forest), effective_toughness(state, forest)) \
        == (1, 4)


def test_older_set_base_pt_then_lignify_lignify_wins_if_newer():
    """Two layer-7a ``set_base_pt`` entries on the same target.
    First an older "becomes 1/1" entry (Atomic-Microsizer-style,
    UEOT), then Lignify (newer, ``expires_at=None``). Both target
    the same id at the same sublayer; the newer Lignify wins.
    """
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    state.add_continuous_effect(
        source_id=bear.id, layer=7, sublayer=1, kind="set_base_pt",
        target_id=bear.id, params=(1, 1), expires_at="cleanup",
        description="(synthetic) becomes 1/1 UEOT",
    )
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, bear)

    assert effective_power(state, bear) == 0
    assert effective_toughness(state, bear) == 4


def test_lignify_then_newer_set_base_pt_newer_wins():
    """Reverse order: Lignify first (7a, expires_at=None), then a
    NEWER "becomes 1/1" 7a entry (UEOT). The newer entry wins per
    CR within-layer timestamp ordering, regardless of which one
    has a longer lifetime."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, bear)
    state.add_continuous_effect(
        source_id=bear.id, layer=7, sublayer=1, kind="set_base_pt",
        target_id=bear.id, params=(1, 1), expires_at="cleanup",
        description="(synthetic) becomes 1/1 UEOT",
    )

    assert effective_power(state, bear) == 1
    assert effective_toughness(state, bear) == 1


def test_lignify_then_atomic_microsizer_real_card_newer_wins():
    """End-to-end with a real card: Lignify attaches first, then
    Atomic Microsizer's 'becomes 1/1 UEOT' resolves. Verify the
    newer Microsizer effect wins via registry timestamp ordering."""
    from mtg_bot.effects.bespoke import AtomicMicrosizerAttackEffect

    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, bear)
    assert effective_power(state, bear) == 0
    assert effective_toughness(state, bear) == 4

    # Atomic Microsizer's effect resolves on the bear, AFTER Lignify.
    state.resolving_source = aura  # any source for source_id
    AtomicMicrosizerAttackEffect().resolve(
        state, controller_id=0, targets=(("creature", bear.id),),
    )

    assert effective_power(state, bear) == 1
    assert effective_toughness(state, bear) == 1


# =====================================================================
# F. Lifetime / expiration corners
# =====================================================================


def test_ueot_pump_on_lignified_creature_aura_leaves_before_cleanup():
    """A UEOT pump (`expires_at='cleanup'`) on a Lignified bear.
    Lignify is destroyed (its `expires_at=None` entries drop) but the
    pump's cleanup-marked entry persists. Bear becomes 2+pump /
    2+pump after Lignify falls off but before cleanup."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    aura = _put(state, LIGNIFY, owner_id=0)
    _attach(state, aura, bear)
    # UEOT pump.
    bear.temp_power_bonus = 3
    bear.temp_toughness_bonus = 3
    assert effective_power(state, bear) == 0 + 3
    assert effective_toughness(state, bear) == 4 + 3

    destroy(state, aura)

    # Lignify gone, pump remains.
    assert effective_power(state, bear) == 2 + 3
    assert effective_toughness(state, bear) == 2 + 3

    state.expire_continuous_effects("cleanup")
    bear.temp_power_bonus = 0  # cleanup zeros legacy fields
    bear.temp_toughness_bonus = 0

    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2
