"""Tests for the Duskmourn Impending alt-cost mechanic.

Covers:
- Parser claims the Overlord cycle's Impending cost via
  ``_parse_impending_line`` and the grammar path (not the bespoke
  table). The Overlords were removed from ``_BESPOKE_CREATURES``
  in the bespoke: migrate Overlord cycle commit.
- ``CastSpell(use_impending=True)`` uses ``impending_cost`` and
  enters the permanent with N time counters,
  ``impending_active=True``, suppressing the printed creature type.
- The end-step turn-based action
  ``run_impending_decrement_turn_based_action`` removes one time
  counter per active player's end step; when the last counter is
  removed, ``impending_active`` clears and the permanent becomes a
  creature.
- ``legal_actions`` surfaces both the printed-cost and impending-
  cost cast variants at sorcery speed.
- Casting for the printed cost enters as a creature with no time
  counters.
"""

import json
import os

import pytest

from mtg_bot import legal_moves
from mtg_bot.actions import (
    CastSpell, apply_action, drain_stack, put_into_battlefield,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.parser.creature_builder import (
    _BESPOKE_CREATURES,
    _build_creature_printing,
)
from mtg_bot.cards.parser.printing_keywords import _parse_impending_line
from mtg_bot.cards.parser.triggers import _parse_compound_predicate_trigger_phrase
from mtg_bot.effects.predicates import Event, IsSelf
from mtg_bot.game import GameState, Player, Zone, is_creature_now
from mtg_bot.turn import (
    Step, run_impending_decrement_turn_based_action,
)

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _load_dsk_card(name: str) -> "dict | None":
    """Return the Scryfall record for ``name`` from duskmourn.json."""
    data_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "duskmourn.json"
    )
    with open(data_path) as f:
        data = json.load(f)
    for card in data:
        if card.get("name") == name:
            return card
    return None


class _PickFirstAgent(Agent):
    """Picks the first legal target / first discard for any prompt."""

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[0] if hand_card_ids else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0, tapped=False):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    obj.tapped = tapped
    state.battlefield.append(obj)
    return obj


# -----------------------
# Parser: _parse_impending_line
# -----------------------


def test_parse_impending_line_basic():
    # Reminder text is stripped before this lookup runs.
    assert _parse_impending_line("Impending 4—{2}{W}{W}") == (4, "{2}{W}{W}")


def test_parse_impending_line_single_color():
    assert _parse_impending_line("Impending 5—{1}{B}") == (5, "{1}{B}")


def test_parse_impending_line_no_match_for_plain_text():
    assert _parse_impending_line("Flying") is None


def test_parse_impending_line_no_match_for_warp():
    assert _parse_impending_line("Warp {1}{R}") is None


def test_parse_impending_line_no_match_when_count_missing():
    assert _parse_impending_line("Impending—{1}{B}") is None


# -----------------------
# Printing fields
# -----------------------


def test_overlord_mistmoors_has_impending_fields():
    p = _PRINTINGS["Overlord of the Mistmoors"]
    assert p.impending_cost_str == "{2}{W}{W}"
    assert p.impending_count == 4
    assert p.impending_cost is not None
    assert p.impending_cost.generic == 2
    # The printing is a creature; impending state is per-instance.
    assert p.is_creature
    assert "Enchantment" in p.card_types


def test_overlord_boilerbilges_has_impending_fields():
    p = _PRINTINGS["Overlord of the Boilerbilges"]
    assert p.impending_cost_str == "{2}{R}{R}"
    assert p.impending_count == 4


def test_non_impending_card_has_default_impending_fields():
    p = _PRINTINGS["Cosmogoyf"]
    assert p.impending_cost is None
    assert p.impending_cost_str == ""
    assert p.impending_count == 0


# -----------------------
# Cast path: impending vs printed cost
# -----------------------


def test_impending_cast_marks_card_via_cast_via_impending():
    """``_cast_spell`` with ``use_impending=True`` flags the card so
    ``put_into_battlefield`` initializes time counters and
    ``impending_active``."""
    state = _new_state()
    # 4 Plains (impending cost is {2}{W}{W} = 2 generic + 2 W).
    for _ in range(4):
        _put(state, BASIC_LANDS["Plains"])
    overlord = state.new_object(
        _PRINTINGS["Overlord of the Mistmoors"], 0, Zone.HAND,
    )
    state.players[0].hand.append(overlord)
    apply_action(state, 0, CastSpell(overlord.id, use_impending=True))
    # Cast: card is on the stack (not yet on battlefield).
    assert overlord.zone == Zone.STACK
    assert overlord.cast_via_impending is True
    # The printed-cost path didn't set warp.
    assert overlord.cast_via_warp is False
    # Resolve.
    drain_stack(state)
    assert overlord.zone == Zone.BATTLEFIELD
    assert overlord.time_counters == 4
    assert overlord.impending_active is True
    # ``cast_via_impending`` is consumed at ETB so a future blink-
    # and-recast under the printed cost doesn't reactivate suppression.
    assert overlord.cast_via_impending is False
    # Suppressed-as-non-creature.
    assert is_creature_now(overlord) is False
    # Printed creature card type is still in the printing.
    assert overlord.printing.is_creature is True


def test_printed_cost_cast_skips_impending_state():
    """Casting via the printed cost doesn't initialize time counters
    or set ``impending_active``."""
    state = _new_state()
    # 7 Plains for {5}{W}{W}.
    for _ in range(7):
        _put(state, BASIC_LANDS["Plains"])
    overlord = state.new_object(
        _PRINTINGS["Overlord of the Mistmoors"], 0, Zone.HAND,
    )
    state.players[0].hand.append(overlord)
    apply_action(state, 0, CastSpell(overlord.id))
    drain_stack(state)
    assert overlord.zone == Zone.BATTLEFIELD
    assert overlord.time_counters == 0
    assert overlord.impending_active is False
    # Enters as a creature (printed creature type not suppressed).
    assert is_creature_now(overlord) is True


# -----------------------
# End-step turn-based action: counter decrement + flip
# -----------------------


def test_impending_decrement_removes_one_counter_per_call():
    state = _new_state()
    overlord = _put(state, _PRINTINGS["Overlord of the Mistmoors"])
    overlord.time_counters = 4
    overlord.impending_active = True
    overlord.controller_id = 0
    run_impending_decrement_turn_based_action(state)
    assert overlord.time_counters == 3
    assert overlord.impending_active is True
    run_impending_decrement_turn_based_action(state)
    assert overlord.time_counters == 2


def test_impending_last_counter_removal_flips_to_creature():
    state = _new_state()
    overlord = _put(state, _PRINTINGS["Overlord of the Mistmoors"])
    overlord.time_counters = 1
    overlord.impending_active = True
    overlord.controller_id = 0
    # Suppressed before decrement.
    assert is_creature_now(overlord) is False
    run_impending_decrement_turn_based_action(state)
    assert overlord.time_counters == 0
    assert overlord.impending_active is False
    # Now a creature.
    assert is_creature_now(overlord) is True


def test_impending_decrement_only_active_player():
    """Only the active player's permanents tick — mirrors "At the
    beginning of your end step"."""
    state = _new_state()
    overlord = _put(state, _PRINTINGS["Overlord of the Mistmoors"])
    overlord.time_counters = 4
    overlord.impending_active = True
    overlord.controller_id = 1  # opponent
    state.active_player_idx = 0
    run_impending_decrement_turn_based_action(state)
    # No change — opponent's permanent doesn't tick on P0's end step.
    assert overlord.time_counters == 4
    assert overlord.impending_active is True


def test_impending_decrement_skips_inactive_permanents():
    """A printing with impending_count > 0 but
    ``impending_active=False`` (cast for printed cost) doesn't tick."""
    state = _new_state()
    overlord = _put(state, _PRINTINGS["Overlord of the Mistmoors"])
    overlord.time_counters = 0
    overlord.impending_active = False
    overlord.controller_id = 0
    run_impending_decrement_turn_based_action(state)
    assert overlord.time_counters == 0
    assert overlord.impending_active is False


# -----------------------
# legal_actions surfacing
# -----------------------


def test_legal_actions_offers_both_printed_and_impending_cast():
    state = _new_state()
    # Lots of Plains so both costs are payable.
    for _ in range(8):
        _put(state, BASIC_LANDS["Plains"])
    overlord = state.new_object(
        _PRINTINGS["Overlord of the Mistmoors"], 0, Zone.HAND,
    )
    state.players[0].hand.append(overlord)
    actions = [
        a for a in legal_moves(state)
        if isinstance(a, CastSpell) and a.card_id == overlord.id
    ]
    # Printed cost (no flags) AND impending variant.
    assert any(
        not a.use_impending and not a.use_warp and not a.kicked
        and not a.cast_for_free
        for a in actions
    )
    assert any(a.use_impending for a in actions)


def test_legal_actions_drops_impending_when_unaffordable():
    state = _new_state()
    # Not enough mana for the impending cost {2}{W}{W}.
    _put(state, BASIC_LANDS["Plains"])
    overlord = state.new_object(
        _PRINTINGS["Overlord of the Mistmoors"], 0, Zone.HAND,
    )
    state.players[0].hand.append(overlord)
    actions = [
        a for a in legal_moves(state)
        if isinstance(a, CastSpell) and a.card_id == overlord.id
    ]
    assert not any(a.use_impending for a in actions)


def test_legal_actions_no_impending_at_instant_speed():
    """Sorcery-speed gate — no Impending cast on opponent's turn or
    with a non-empty stack."""
    state = _new_state()
    state.active_player_idx = 1  # opponent's turn
    state.priority_player_idx = 0
    for _ in range(8):
        _put(state, BASIC_LANDS["Plains"])
    overlord = state.new_object(
        _PRINTINGS["Overlord of the Mistmoors"], 0, Zone.HAND,
    )
    state.players[0].hand.append(overlord)
    actions = [
        a for a in legal_moves(state)
        if isinstance(a, CastSpell) and a.card_id == overlord.id
    ]
    assert not any(a.use_impending for a in actions)


# -----------------------
# Suppression interaction with attacking
# -----------------------


def test_impending_suppression_blocks_combat_eligibility():
    """An impending-active Overlord can't be declared as an attacker
    because ``is_creature_now`` returns False."""
    from mtg_bot.combat import eligible_attackers

    state = _new_state()
    overlord = _put(state, _PRINTINGS["Overlord of the Mistmoors"])
    overlord.controller_id = 0
    overlord.impending_active = True
    overlord.time_counters = 1
    overlord.summoning_sick = False
    eligible = eligible_attackers(state, 0)
    assert overlord not in eligible


def test_impending_flip_makes_creature_combat_eligible():
    from mtg_bot.combat import eligible_attackers

    state = _new_state()
    overlord = _put(state, _PRINTINGS["Overlord of the Mistmoors"])
    overlord.controller_id = 0
    overlord.impending_active = False
    overlord.time_counters = 0
    overlord.summoning_sick = False
    eligible = eligible_attackers(state, 0)
    assert overlord in eligible


# -----------------------
# End-to-end: cast for impending, three end steps, flip on fourth
# -----------------------


def test_impending_etb_trigger_fires_when_cast_for_impending():
    """The Mistmoors Overlord's "Whenever this permanent enters or
    attacks" trigger fires on the ENTERS event regardless of whether
    the printed creature type is suppressed (``IsSelf()`` matches
    the entering object). Two 2/1 Insect tokens should appear."""
    state = _new_state()
    for _ in range(4):
        _put(state, BASIC_LANDS["Plains"])
    overlord = state.new_object(
        _PRINTINGS["Overlord of the Mistmoors"], 0, Zone.HAND,
    )
    state.players[0].hand.append(overlord)
    apply_action(state, 0, CastSpell(overlord.id, use_impending=True))
    drain_stack(state)
    insects = [
        o for o in state.battlefield
        if o.printing.name == "Insect" and o.controller_id == 0
    ]
    assert len(insects) == 2


def test_boilerbilges_etb_damage_fires_on_impending_cast():
    """Boilerbilges' "deals 4 damage to any target" ETB trigger
    targets a legal target and deals 4 damage. The first legal
    target in ``DealDamageAnyTarget.legal_targets`` (with no
    creatures around) is the controller themselves; verify the
    trigger fired and total damage in the system is 4."""
    state = _new_state()
    # 4 Mountains for {2}{R}{R}.
    mountain = BASIC_LANDS["Mountain"]
    for _ in range(4):
        _put(state, mountain)
    overlord = state.new_object(
        _PRINTINGS["Overlord of the Boilerbilges"], 0, Zone.HAND,
    )
    state.players[0].hand.append(overlord)
    state.players[0].life = 20
    state.players[1].life = 20
    apply_action(state, 0, CastSpell(overlord.id, use_impending=True))
    drain_stack(state)
    # Some target took 4 damage — the first legal target in the
    # players list (P0 self) under _PickFirstAgent.
    total_damage_dealt = 40 - (state.players[0].life + state.players[1].life)
    assert total_damage_dealt == 4


def test_floodpits_etb_draws_two_then_discards_one():
    """Overlord of the Floodpits' ETB sequences DrawCards(2) then
    DiscardSelf(1). Net hand growth = +1 (drew two, discarded one).
    Library decreases by 2."""
    state = _new_state()
    p = state.players[0]
    # 5 Islands for {1}{U}{U} = 1 generic + 2 U.
    for _ in range(5):
        _put(state, BASIC_LANDS["Island"])
    # Library has 5 cards so the 2-card draw can be satisfied.
    for _ in range(5):
        c = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
        p.library.append(c)
    overlord = state.new_object(
        _PRINTINGS["Overlord of the Floodpits"], 0, Zone.HAND,
    )
    p.hand.append(overlord)
    hand_before = len(p.hand)  # includes the Overlord
    apply_action(state, 0, CastSpell(overlord.id, use_impending=True))
    drain_stack(state)
    # Hand: started with [Overlord], cast removed it, drew 2,
    # discarded 1 → net change vs (hand_before - 1) is +1.
    assert len(p.hand) == (hand_before - 1) + 1


def test_floodpits_keywords_include_flying():
    p = _PRINTINGS["Overlord of the Floodpits"]
    assert "flying" in p.keywords
    assert p.impending_count == 4


def test_impending_full_lifecycle_via_end_step_action():
    """Simulate: cast Overlord for impending; tick the end-step
    decrement N=4 times; the 4th tick flips it to a creature."""
    state = _new_state()
    for _ in range(4):
        _put(state, BASIC_LANDS["Plains"])
    overlord = state.new_object(
        _PRINTINGS["Overlord of the Mistmoors"], 0, Zone.HAND,
    )
    state.players[0].hand.append(overlord)
    apply_action(state, 0, CastSpell(overlord.id, use_impending=True))
    drain_stack(state)
    assert overlord.time_counters == 4
    assert overlord.impending_active is True
    # Tick four end steps.
    for expected_remaining in (3, 2, 1, 0):
        run_impending_decrement_turn_based_action(state)
        assert overlord.time_counters == expected_remaining
    assert overlord.impending_active is False
    # Last tick flipped it to a creature.
    assert is_creature_now(overlord) is True


# -----------------------
# Trigger-phrase: "this permanent enters or attacks"
# -----------------------


def test_compound_trigger_phrase_this_permanent_enters_or_attacks():
    """``_parse_compound_predicate_trigger_phrase`` recognizes the
    ``"this permanent enters or attacks"`` surface and returns two
    ``(Event, Predicate)`` pairs — one ENTERS+IsSelf and one
    ATTACKS+IsSelf.

    This covers the Duskmourn Overlord cycle oracle text
    ``"Whenever this permanent enters or attacks, …"`` where the
    permanent isn't always a creature (impending-suppressed state).
    """
    result = _parse_compound_predicate_trigger_phrase(
        "this permanent enters or attacks"
    )
    assert result is not None
    assert len(result) == 2
    events = {event for event, _ in result}
    assert Event.ENTERS in events
    assert Event.ATTACKS in events
    # Both arms use IsSelf() — predicate identity check.
    for _, pred in result:
        assert isinstance(pred, IsSelf)


# -----------------------
# Grammar-path migration: Overlords NOT in _BESPOKE_CREATURES
# -----------------------


def test_overlord_mistmoors_not_in_bespoke_table():
    """Overlord of the Mistmoors was removed from ``_BESPOKE_CREATURES``
    after engine-impending migration; the grammar claims it directly."""
    assert "Overlord of the Mistmoors" not in _BESPOKE_CREATURES


def test_overlord_floodpits_not_in_bespoke_table():
    assert "Overlord of the Floodpits" not in _BESPOKE_CREATURES


def test_overlord_boilerbilges_not_in_bespoke_table():
    assert "Overlord of the Boilerbilges" not in _BESPOKE_CREATURES


@pytest.mark.parametrize("name", [
    "Overlord of the Mistmoors",
    "Overlord of the Floodpits",
    "Overlord of the Boilerbilges",
])
def test_overlord_grammar_claims_card(name):
    """``_build_creature_printing`` produces the card from oracle text.

    Verifies that the grammar path (trigger-phrase + impending line +
    enchantment type-line handling) successfully claims each Overlord
    and produces the expected impending fields, enchantment card type,
    and two triggered abilities.
    """
    card = _load_dsk_card(name)
    assert card is not None, f"Card {name!r} not found in duskmourn.json"
    result = _build_creature_printing(card)
    assert result is not None, f"Grammar returned None for {name!r}"
    assert result.impending_count == 4
    assert result.impending_cost is not None
    assert "Enchantment" in result.card_types
    # Two triggers: one ENTERS+IsSelf, one ATTACKS+IsSelf.
    assert len(result.triggered_abilities) == 2
    events = {ta.event for ta in result.triggered_abilities}
    assert Event.ENTERS in events
    assert Event.ATTACKS in events
