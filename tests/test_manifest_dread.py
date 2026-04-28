"""Tests for the Manifest Dread mechanic (Duskmourn).

Coverage:

* ``GameObject.face_down`` virtualization — when set True, the
  ``effective_*`` helpers report the face-down 2/2 vanilla view (CR
  701.34 / 707.2): no name / no subtypes / no keywords / no abilities,
  always a creature, base 2/2.
* ``ManifestDread`` effect — looks at the top two cards, manifests
  one face-down (2/2 creature), the other goes to the graveyard.
  Repeats ``count`` times. Edge cases: empty library, single-card
  library, X-times surface (count=None).
* ``TurnFaceUp`` action — pays the underlying card's mana cost and
  flips ``face_down`` off; offered by ``legal_actions`` only when the
  underlying printing is a creature card whose mana cost is payable.
* Parser grammar primitive — ``manifest dread`` (count=1) and the
  ``twice`` / ``N times`` / ``X times`` variants on
  ``_parse_effect``; end-to-end parser-claim coverage for the bare
  Manifest Dread sorcery.
"""

from __future__ import annotations

import random

from mtg_bot.actions import (
    PassPriority,
    TurnFaceUp,
    apply_action,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.cards.parser.effects import (
    _parse_effect,
    _parse_spell_effect_phrase,
)
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects import ManifestDread
from mtg_bot.game import (
    GameState,
    Player,
    Zone,
    effective_keywords,
    effective_power,
    effective_subtypes,
    effective_toughness,
    is_creature_now,
)
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step


# ----------------------------------------------------------------------
# Test scaffolding
# ----------------------------------------------------------------------


def _arena() -> GameState:
    """Two-player arena with empty libraries — tests stock the library
    explicitly so the manifest-dread flow has something to look at."""
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _stock_library(state: GameState, player_id: int, printings) -> list:
    """Put ``printings`` into the top of ``player_id``'s library in
    list order; the first item ends up as the top card. Returns the
    list of GameObjects in library order (top → bottom)."""
    cards = []
    for printing in printings:
        card = state.new_object(
            printing, owner_id=player_id, zone=Zone.LIBRARY,
        )
        state.players[player_id].library.append(card)
        cards.append(card)
    return cards


# ----------------------------------------------------------------------
# Face-down virtualization (GameObject.face_down)
# ----------------------------------------------------------------------


def test_face_down_creature_has_no_name_subtypes_or_keywords():
    state = _arena()
    obj = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    obj.face_down = True
    state.battlefield.append(obj)
    # Subtypes / keywords are wiped while face-down.
    assert effective_subtypes(state, obj) == ()
    assert effective_keywords(state, obj) == frozenset()


def test_face_down_object_is_a_creature_regardless_of_underlying_type():
    """A face-down permanent is ALWAYS a creature (CR 701.34), even
    when the underlying card isn't — e.g. a face-down land or
    enchantment is still a 2/2 creature on the battlefield."""
    state = _arena()
    # An island (a land card) manifested face-down should still count
    # as a creature.
    obj = state.new_object(
        BASIC_LANDS["Island"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    obj.face_down = True
    state.battlefield.append(obj)
    assert is_creature_now(obj) is True
    # And it's a 2/2.
    assert effective_power(state, obj) == 2
    assert effective_toughness(state, obj) == 2


def test_face_down_pt_is_2_2_plus_counters():
    """+1/+1 counters still apply to a face-down creature — they're
    state-based modifiers (layer 7d), not abilities."""
    state = _arena()
    obj = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    obj.face_down = True
    obj.plus_one_counters = 3
    state.battlefield.append(obj)
    assert effective_power(state, obj) == 5
    assert effective_toughness(state, obj) == 5


def test_face_down_minus_one_counters_apply_too():
    """-1/-1 counters lower the 2/2 base (layer 7d)."""
    state = _arena()
    obj = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    obj.face_down = True
    obj.minus_one_counters = 1
    state.battlefield.append(obj)
    assert effective_power(state, obj) == 1
    assert effective_toughness(state, obj) == 1


def test_face_up_flag_off_returns_printed_view():
    """Belt-and-suspenders: with face_down=False the engine sees the
    printed P/T as before."""
    state = _arena()
    obj = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(obj)
    assert obj.face_down is False
    assert effective_power(state, obj) == obj.printing.power
    assert effective_toughness(state, obj) == obj.printing.toughness


# ----------------------------------------------------------------------
# ManifestDread effect resolve
# ----------------------------------------------------------------------


def test_manifest_dread_default_picks_top_card():
    """With no agent (``p.agent is None``), the top card is manifested
    face-down and the second card goes to graveyard."""
    state = _arena()
    state.players[0].agent = None
    cards = _stock_library(
        state, 0, [
            SYNTHETIC_CREATURES["Wild Bear"],
            SYNTHETIC_CREATURES["Wild Bear"],
        ],
    )
    top, second = cards
    ManifestDread().resolve(state, 0)
    assert top in state.battlefield
    assert top.face_down is True
    assert top.zone == Zone.BATTLEFIELD
    assert second in state.players[0].graveyard
    assert second.zone == Zone.GRAVEYARD


def test_manifest_dread_agent_picks_second_card():
    """An agent that picks the second card to manifest sends the top
    card to the graveyard."""

    class PickSecond(RandomAgent):
        def choose_card_from_library(self, state, player_id, option_ids):
            return option_ids[1]

    state = _arena()
    state.players[0].agent = PickSecond(rng=random.Random(0))
    cards = _stock_library(
        state, 0, [
            SYNTHETIC_CREATURES["Wild Bear"],
            SYNTHETIC_CREATURES["Wild Bear"],
        ],
    )
    top, second = cards
    ManifestDread().resolve(state, 0)
    assert second in state.battlefield
    assert second.face_down is True
    assert top in state.players[0].graveyard


def test_manifest_dread_empty_library_noop():
    state = _arena()
    state.players[0].agent = None
    ManifestDread().resolve(state, 0)
    # No crash; library still empty.
    assert state.players[0].library == []
    assert state.battlefield == []


def test_manifest_dread_single_card_library_manifests_only_card():
    """When the library has exactly one card left, that card is
    manifested and the graveyard step is skipped."""
    state = _arena()
    state.players[0].agent = None
    cards = _stock_library(
        state, 0, [SYNTHETIC_CREATURES["Wild Bear"]]
    )
    only = cards[0]
    ManifestDread().resolve(state, 0)
    assert only in state.battlefield
    assert only.face_down is True
    assert state.players[0].graveyard == []
    assert state.players[0].library == []


def test_manifest_dread_twice_resolves_twice():
    """count=2 manifests two face-down creatures and mills two cards."""
    state = _arena()
    state.players[0].agent = None
    _stock_library(
        state, 0, [SYNTHETIC_CREATURES["Wild Bear"]] * 4,
    )
    ManifestDread(count=2).resolve(state, 0)
    face_down_count = sum(
        1 for o in state.battlefield if o.face_down
    )
    assert face_down_count == 2
    assert len(state.players[0].graveyard) == 2
    assert state.players[0].library == []


def test_manifest_dread_x_times_reads_resolving_x_value():
    """count=None reads ``state.resolving_x_value`` at resolve time —
    the X-times surface for cards like Valgavoth's Onslaught."""
    state = _arena()
    state.players[0].agent = None
    _stock_library(
        state, 0, [SYNTHETIC_CREATURES["Wild Bear"]] * 6,
    )
    state.resolving_x_value = 3
    ManifestDread(count=None).resolve(state, 0)
    face_down_count = sum(
        1 for o in state.battlefield if o.face_down
    )
    assert face_down_count == 3
    assert len(state.players[0].graveyard) == 3


def test_manifest_dread_describe():
    assert ManifestDread().describe() == "manifest dread"
    assert ManifestDread(count=2).describe() == "manifest dread twice"
    assert ManifestDread(count=3).describe() == "manifest dread three times"
    assert ManifestDread(count=4).describe() == "manifest dread 4 times"
    assert ManifestDread(count=None).describe() == "manifest dread X times"


# ----------------------------------------------------------------------
# TurnFaceUp action
# ----------------------------------------------------------------------


def test_turn_face_up_pays_cost_and_flips_face_down_off():
    state = _arena()
    # Stock a Wild Bear ({1}{G} 2/2) and 2 Forests so the cost can be
    # paid via ``can_pay_cost``.
    obj = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    obj.face_down = True
    state.battlefield.append(obj)
    for _ in range(2):
        land = state.new_object(
            BASIC_LANDS["Forest"], owner_id=0, zone=Zone.BATTLEFIELD,
        )
        state.battlefield.append(land)
    apply_action(state, 0, TurnFaceUp(card_id=obj.id))
    assert obj.face_down is False
    # Lands tapped to pay the {1}{G} cost.
    tapped = sum(
        1 for o in state.battlefield
        if o.printing.is_land and o.tapped
    )
    assert tapped == 2


def test_legal_actions_offers_turn_face_up_when_payable():
    state = _arena()
    obj = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    obj.face_down = True
    state.battlefield.append(obj)
    for _ in range(2):
        land = state.new_object(
            BASIC_LANDS["Forest"], owner_id=0, zone=Zone.BATTLEFIELD,
        )
        state.battlefield.append(land)
    actions = legal_actions(state, 0)
    assert any(
        isinstance(a, TurnFaceUp) and a.card_id == obj.id
        for a in actions
    )


def test_legal_actions_omits_turn_face_up_when_unpayable():
    """No mana sources → the special action isn't offered."""
    state = _arena()
    obj = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    obj.face_down = True
    state.battlefield.append(obj)
    actions = legal_actions(state, 0)
    assert not any(isinstance(a, TurnFaceUp) for a in actions)


def test_legal_actions_omits_turn_face_up_for_non_creature_card():
    """A face-down land card can't be turned face up by the manifest-
    dread rule (it's not a creature card)."""
    state = _arena()
    obj = state.new_object(
        BASIC_LANDS["Island"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    obj.face_down = True
    state.battlefield.append(obj)
    # Drop a land to satisfy "any payable cost" without rule-of-thumb
    # cost (Island has cost {0} so trivial).
    actions = legal_actions(state, 0)
    assert not any(isinstance(a, TurnFaceUp) for a in actions)


def test_turn_face_up_is_a_noop_for_unknown_card_id():
    """Defensive: a TurnFaceUp action for a card that isn't on the
    battlefield (or isn't face-down) silently no-ops."""
    state = _arena()
    # No object with id 999 exists.
    apply_action(state, 0, TurnFaceUp(card_id=999))
    # No crash — that's the assertion.


def test_turn_face_up_noop_when_underlying_is_not_a_creature():
    """If the manifested card is a non-creature card, the turn-face-up
    flow refuses (CR 701.34)."""
    state = _arena()
    obj = state.new_object(
        BASIC_LANDS["Island"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    obj.face_down = True
    state.battlefield.append(obj)
    apply_action(state, 0, TurnFaceUp(card_id=obj.id))
    assert obj.face_down is True


def test_turn_face_up_noop_when_cost_unpayable():
    """If ``can_pay_cost`` would fail, the special action does nothing
    (defensive — legal_actions already gates this)."""
    state = _arena()
    obj = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    obj.face_down = True
    state.battlefield.append(obj)
    # No lands → can't pay {1}{G}.
    apply_action(state, 0, TurnFaceUp(card_id=obj.id))
    assert obj.face_down is True


# ----------------------------------------------------------------------
# Parser grammar primitive
# ----------------------------------------------------------------------


def test_parse_manifest_dread_bare():
    assert _parse_effect("manifest dread") == ManifestDread(count=1)


def test_parse_manifest_dread_twice():
    assert _parse_effect("manifest dread twice") == ManifestDread(count=2)


def test_parse_manifest_dread_three_times():
    assert _parse_effect("manifest dread three times") == ManifestDread(
        count=3,
    )


def test_parse_manifest_dread_x_times():
    assert _parse_effect("manifest dread X times") == ManifestDread(
        count=None,
    )


def test_parse_manifest_dread_digit_times():
    assert _parse_effect("manifest dread 5 times") == ManifestDread(
        count=5,
    )


def test_parse_manifest_dread_unrecognized_returns_none():
    """Stray phrases that look superficially similar don't match."""
    assert _parse_effect("manifest dreadful") is None
    assert _parse_effect("not a manifest dread") is None
    assert _parse_effect("manifest dread the cards") is None


def test_parse_spell_form_manifest_dread():
    """The spell-form normalization (strip name prefix + period +
    lowercase first letter) feeds the bare parser. Manifest Dread the
    sorcery's body is exactly ``Manifest dread.`` → ``ManifestDread(
    count=1)``."""
    assert _parse_spell_effect_phrase(
        "Manifest dread.", "Manifest Dread"
    ) == ManifestDread(count=1)


# ----------------------------------------------------------------------
# End-to-end parser-claim coverage (DSK)
# ----------------------------------------------------------------------


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


def test_manifest_dread_sorcery_claimed_by_parser():
    """Manifest Dread ``{1}{G}`` Sorcery — the bare body
    ``Manifest dread.`` claims via the new grammar primitive."""
    assert "Manifest Dread" in _claimed_names()


def test_manifest_dread_sorcery_engine_class():
    """Belt-and-suspenders: the produced ``CardPrinting`` carries the
    expected ``ManifestDread(count=1)`` engine class."""
    parser = OracleParserCardSource()
    p = parser.get_printings()["Manifest Dread"]
    assert p.spell_effect == ManifestDread(count=1)


def test_unsettling_twins_etb_carries_manifest_dread():
    """Unsettling Twins ``{3}{W}`` 2/2 Human — its ETB body parses to
    a single triggered ability whose effect is ``ManifestDread(
    count=1)``."""
    parser = OracleParserCardSource()
    p = parser.get_printings()["Unsettling Twins"]
    assert len(p.triggered_abilities) == 1
    assert p.triggered_abilities[0].effect == ManifestDread(count=1)


def test_innocuous_rat_dies_carries_manifest_dread():
    """Innocuous Rat ``{1}{B}`` 1/1 Rat — dies trigger fires manifest
    dread."""
    parser = OracleParserCardSource()
    p = parser.get_printings()["Innocuous Rat"]
    assert len(p.triggered_abilities) == 1
    assert p.triggered_abilities[0].effect == ManifestDread(count=1)


def test_twist_reality_modal_includes_manifest_dread():
    """Twist Reality ``{1}{U}{U}`` Instant — modal ``Choose one —``
    with ``Counter target spell.`` and ``Manifest dread.`` modes. Both
    modes parse so the modal claims end-to-end."""
    parser = OracleParserCardSource()
    p = parser.get_printings()["Twist Reality"]
    # The spell_effect is a ModalChooseOne with two modes; the second
    # mode is ManifestDread.
    from mtg_bot.effects import ModalChooseOne
    assert isinstance(p.spell_effect, ModalChooseOne)
    assert ManifestDread(count=1) in p.spell_effect.modes
