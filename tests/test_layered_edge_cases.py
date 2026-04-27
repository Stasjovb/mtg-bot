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
    CLONE, LIGNIFY, MAGICAL_HACK, SCUTTLEMUTT, WHITE_KNIGHT,
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
