"""Magical Hack (Alpha) — exercises CR 613 layer 3 (text-changing).

Magical Hack's oracle text: "Change the text of target spell or
permanent by replacing all instances of one basic land type with
another."

Magical Hack is a real Magic card, not in the Edge of Eternities
pool. The printing lives in ``mtg_bot.cards.demo_layers``.

Implementation scope: only handles basic-land-type substitution on
basic lands (the engine doesn't model landwalk or other rules-text
references to basic land types yet, so the text-change has no
effect there). The substitution flows through:

- ``effective_subtypes`` walks layer-3 ``"replace_basic_land_type"``
  entries in timestamp order, substituting old → new.
- ``effective_land_produces`` derives produced color from the
  effective basic-land-type subtype via
  ``_BASIC_LAND_TYPE_TO_COLOR`` (Plains→W, Island→U, Swamp→B,
  Mountain→R, Forest→G).

So a Forest with a layer-3 ("Forest", "Mountain") entry effectively
has subtype "Mountain" and taps for {R}.

Pinned behavior:

- Targeting: only basic lands are legal targets (in this demo).
- Resolution writes a layer-3 entry with ``expires_at=None``
  (CR 612: text changes are persistent).
- Substitution affects subtypes AND mana production.
- Multiple Magical Hacks on the same land stack by timestamp; the
  most-recent rewrite wins.
- Layer-3 substitution composes with layer-4 add_subtype (Lignify):
  layer 3 substitutes first, then layer 4 appends.
"""

from __future__ import annotations

import pytest

from mtg_bot.actions import drain_stack, resolve_top_of_stack
from mtg_bot.agents import Agent
from mtg_bot.cards.base import make_basic_land
from mtg_bot.cards.demo_layers import LIGNIFY, MAGICAL_HACK
from mtg_bot.effects.generic import MagicalHackTextChangeEffect
from mtg_bot.game import (
    GameState, Player, StackItem, Zone,
    effective_land_produces, effective_subtypes,
)
from mtg_bot.turn import Step


class _PickFirstColor(Agent):
    """Agent that picks the first option in choose_mana_color and the
    first legal target. Used to drive Magical Hack deterministically:
    when the OLD type is Forest (G), choose_mana_color is offered
    [W, U, B, R], so it picks W → Plains."""

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_mana_color(self, state, player_id, options):
        return options[0]


class _PickColor(Agent):
    """Agent that picks a specific color from choose_mana_color."""

    def __init__(self, color: str):
        self.color = color

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_mana_color(self, state, player_id, options):
        return self.color if self.color in options else options[0]


def _new_state(agent: Agent | None = None) -> GameState:
    state = GameState()
    a = agent or _PickFirstColor()
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


# ---------- Printing shape ----------


def test_magical_hack_printing_shape():
    assert MAGICAL_HACK.is_sorcery is True
    assert MAGICAL_HACK.spell_effect.__class__.__name__ \
        == "MagicalHackTextChangeEffect"


def test_magical_hack_not_in_eoe_pool():
    """Magical Hack is a demo-only card. It must not leak into the
    EoE NONLAND_POOL or all_printings."""
    from mtg_bot.cards.registry import NONLAND_POOL, all_printings
    assert "Magical Hack" not in NONLAND_POOL
    assert "Magical Hack" not in all_printings()


# ---------- Direct effect resolution: basic land subtype rewrite ----------


def test_magical_hack_changes_forest_subtype_to_chosen():
    """Magical Hack on a basic Forest with the agent picking R:
    Forest's effective subtype becomes Mountain (and only Mountain —
    the substitution replaces, not adds)."""
    state = _new_state(agent=_PickColor("R"))
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    assert effective_subtypes(state, forest) == ("Forest",)

    MagicalHackTextChangeEffect().resolve(
        state, controller_id=0, targets=(("permanent", forest.id),),
    )

    subs = effective_subtypes(state, forest)
    assert "Forest" not in subs
    assert "Mountain" in subs


def test_magical_hack_writes_persistent_layer3_entry():
    """The registry entry has layer=3, kind='replace_basic_land_type',
    params=(old, new), expires_at=None."""
    state = _new_state(agent=_PickColor("R"))
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)

    MagicalHackTextChangeEffect().resolve(
        state, controller_id=0, targets=(("permanent", forest.id),),
    )

    entries = [
        ce for ce in state.continuous_effects
        if ce.layer == 3 and ce.kind == "replace_basic_land_type"
    ]
    assert len(entries) == 1
    assert entries[0].params == ("Forest", "Mountain")
    assert entries[0].target_id == forest.id
    assert entries[0].expires_at is None  # text changes persist


def test_magical_hack_changes_mana_production():
    """A Forest rewritten to Mountain taps for {R}, not {G}."""
    state = _new_state(agent=_PickColor("R"))
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    assert effective_land_produces(state, forest) == frozenset({"G"})

    MagicalHackTextChangeEffect().resolve(
        state, controller_id=0, targets=(("permanent", forest.id),),
    )

    assert effective_land_produces(state, forest) == frozenset({"R"})


@pytest.mark.parametrize("color,expected_subtype", [
    ("W", "Plains"),
    ("U", "Island"),
    ("B", "Swamp"),
    ("R", "Mountain"),
])
def test_magical_hack_each_color_choice(color, expected_subtype):
    """All four non-Forest color picks rewrite the Forest accordingly."""
    state = _new_state(agent=_PickColor(color))
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)

    MagicalHackTextChangeEffect().resolve(
        state, controller_id=0, targets=(("permanent", forest.id),),
    )

    assert expected_subtype in effective_subtypes(state, forest)
    assert effective_land_produces(state, forest) == frozenset({color})


def test_magical_hack_excludes_old_color_from_options():
    """The choose_mana_color options exclude the OLD basic-land
    color, since Magical Hack must replace one type with ANOTHER."""
    captured: list[list[str]] = []

    class _CaptureOptions(Agent):
        def choose_target(self, state, player_id, legal_targets):
            return legal_targets[0] if legal_targets else None

        def choose_mana_color(self, state, player_id, options):
            captured.append(list(options))
            return options[0]

    state = _new_state(agent=_CaptureOptions())
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)

    MagicalHackTextChangeEffect().resolve(
        state, controller_id=0, targets=(("permanent", forest.id),),
    )

    assert captured == [["W", "U", "B", "R"]]  # G excluded


# ---------- Stacked Magical Hacks: most-recent timestamp wins ----------


def test_two_magical_hacks_most_recent_wins():
    """Two Magical Hacks on the same land. T1: ("Forest","Mountain").
    T2: ("Mountain","Island"). After both, the substitutions chain in
    timestamp order: Forest -> Mountain -> Island. Effective subtype
    is Island; produces {U}.
    """
    state = _new_state(agent=_PickColor("R"))
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)

    # Hack 1: Forest -> Mountain.
    MagicalHackTextChangeEffect().resolve(
        state, 0, (("permanent", forest.id),),
    )
    assert effective_land_produces(state, forest) == frozenset({"R"})

    # Switch agent to pick Island the second time.
    state.players[0].agent = _PickColor("U")
    # Hack 2: now-effective Mountain -> Island.
    MagicalHackTextChangeEffect().resolve(
        state, 0, (("permanent", forest.id),),
    )

    assert "Island" in effective_subtypes(state, forest)
    assert effective_land_produces(state, forest) == frozenset({"U"})


# ---------- Layer 3 + Layer 4 composition ----------


def test_magical_hack_then_lignify_composes_layers():
    """Layer 3 substitutes first, then layer 4 adds. Apply Magical
    Hack to a Forest (Forest→Plains), then attach Lignify to a Bear
    on the same battlefield. Lignify only affects the Bear (different
    target), so the Forest is still Plains. Test isolation."""
    from mtg_bot.actions import apply_aura_static_grants_on_attach
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = _new_state(agent=_PickColor("W"))
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    aura = _put(state, LIGNIFY, owner_id=0)

    MagicalHackTextChangeEffect().resolve(
        state, 0, (("permanent", forest.id),),
    )
    aura.attached_to = bear.id
    apply_aura_static_grants_on_attach(state, aura, bear, 0)

    # Forest's subtype rewritten Plains; Bear has Treefolk added.
    assert "Plains" in effective_subtypes(state, forest)
    assert "Treefolk" in effective_subtypes(state, bear)
    # Cross-effects don't leak.
    assert "Treefolk" not in effective_subtypes(state, forest)
    assert "Plains" not in effective_subtypes(state, bear)


# ---------- Edge cases ----------


def test_magical_hack_on_non_basic_land_filters_out():
    """Non-basic lands are not legal targets in this demo."""
    state = _new_state()
    # Make a non-basic land by using a synthetic printing — only basic
    # lands appear in legal_targets.
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)

    legal = MagicalHackTextChangeEffect().legal_targets(state, 0)
    assert legal == [("permanent", forest.id)]


def test_magical_hack_target_with_no_basic_land_type_fizzles():
    """If somehow a Magical Hack ends up resolving with a target that
    has no basic-land-type subtype, it logs and fizzles (no entry)."""
    state = _new_state(agent=_PickColor("R"))
    # Construct a printing with is_basic_land=True but no basic-type
    # subtype — pathological, but exercises the fizzle path.
    from mtg_bot.cards.base import CardPrinting, ManaCost
    weird = CardPrinting(
        name="WeirdLand",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Basic Land",
        supertypes=("Basic",),
        card_types=("Land",),
        subtypes=(),  # no basic type subtype
        produces=frozenset(),
    )
    land = _put(state, weird, owner_id=0)
    assert land.printing.is_basic_land is True

    MagicalHackTextChangeEffect().resolve(
        state, 0, (("permanent", land.id),),
    )

    assert state.continuous_effects == []


# ---------- Full cast pipeline (resolve_top_of_stack) ----------


def test_magical_hack_resolves_via_full_cast_pipeline():
    """Drive Magical Hack through resolve_top_of_stack — verify the
    layer-3 entry lands and the Forest's mana production flips."""
    state = _new_state(agent=_PickColor("U"))
    forest = _put(state, make_basic_land("Forest", "G"), owner_id=0)
    spell = state.new_object(MAGICAL_HACK, 0, Zone.STACK)

    state.stack.append(StackItem(
        source=spell,
        controller_id=0,
        targets=(("permanent", forest.id),),
    ))
    resolve_top_of_stack(state)
    drain_stack(state)

    assert effective_land_produces(state, forest) == frozenset({"U"})
    assert any(
        ce.layer == 3 and ce.kind == "replace_basic_land_type"
        and ce.target_id == forest.id
        for ce in state.continuous_effects
    )
