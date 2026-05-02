"""Engine-resolve tests for ``ManifestDreadThenPutPlusOneCountersOnIt``.

The existing single test in ``tests/test_rooms.py``
(``test_manifest_dread_then_counters_no_op_on_empty_library``) only
exercises the empty-library no-op branch — the success path that
manifests a face-down 2/2 and then puts ``counter_amount`` +1/+1
counters on it was uncovered. The Slimy Aquarium / Surgical Suite
unlocks fire this effect.

These tests pin:

- the +1/+1-counter deposit on the just-manifested face-down creature
  (``counter_amount=1`` and a multi-counter variant);
- preservation of the face-down 2/2 view (effective P/T after counters);
- the ``describe()`` text shape for both singular and plural counter
  amounts.
"""

from __future__ import annotations

from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects import ManifestDreadThenPutPlusOneCountersOnIt
from mtg_bot.game import (
    GameState,
    Player,
    Zone,
    effective_power,
    effective_toughness,
)
from mtg_bot.turn import Step


def _arena() -> GameState:
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _stock_library(state: GameState, player_id: int, printings) -> list:
    cards = []
    for printing in printings:
        card = state.new_object(
            printing, owner_id=player_id, zone=Zone.LIBRARY,
        )
        state.players[player_id].library.append(card)
        cards.append(card)
    return cards


def test_resolve_manifests_and_puts_one_counter():
    state = _arena()
    # Top two cards: a creature and a non-creature land. ManifestDread
    # picks one face-down 2/2; the other heads to the graveyard.
    _stock_library(
        state, 0,
        [SYNTHETIC_CREATURES["Wild Bear"], BASIC_LANDS["Plains"]],
    )

    pre_bf = list(state.battlefield)
    eff = ManifestDreadThenPutPlusOneCountersOnIt(counter_amount=1)
    eff.resolve(state, controller_id=0, targets=())

    new_perms = [o for o in state.battlefield if o not in pre_bf]
    assert len(new_perms) == 1
    manifested = new_perms[0]
    assert manifested.face_down is True
    assert manifested.plus_one_counters == 1
    # Face-down 2/2 + 1/+1 = 3/3 effective.
    assert effective_power(state, manifested) == 3
    assert effective_toughness(state, manifested) == 3


def test_resolve_manifests_and_puts_multiple_counters():
    state = _arena()
    _stock_library(
        state, 0,
        [SYNTHETIC_CREATURES["Wild Bear"], BASIC_LANDS["Plains"]],
    )

    eff = ManifestDreadThenPutPlusOneCountersOnIt(counter_amount=3)
    eff.resolve(state, 0, ())

    manifested = [
        o for o in state.battlefield if o.face_down
    ][-1]
    assert manifested.plus_one_counters == 3
    assert effective_power(state, manifested) == 5
    assert effective_toughness(state, manifested) == 5


def test_resolve_logs_counter_deposit():
    state = _arena()
    _stock_library(
        state, 0,
        [SYNTHETIC_CREATURES["Wild Bear"], BASIC_LANDS["Plains"]],
    )
    ManifestDreadThenPutPlusOneCountersOnIt(counter_amount=2).resolve(
        state, 0, (),
    )
    assert any("+1/+1 counter" in line for line in state.log)


def test_describe_singular_counter():
    text = ManifestDreadThenPutPlusOneCountersOnIt(
        counter_amount=1,
    ).describe()
    assert "manifest dread" in text.lower()
    assert "a +1/+1 counter" in text


def test_describe_multiple_counters():
    text = ManifestDreadThenPutPlusOneCountersOnIt(
        counter_amount=3,
    ).describe()
    assert "manifest dread" in text.lower()
    assert "3 +1/+1" in text


def test_resolve_only_one_card_in_library_still_manifests():
    """ManifestDread with a single-card library still picks that one
    card: top-of-library face-down, no second card to dump."""
    state = _arena()
    _stock_library(state, 0, [SYNTHETIC_CREATURES["Wild Bear"]])

    pre_bf = list(state.battlefield)
    ManifestDreadThenPutPlusOneCountersOnIt(counter_amount=1).resolve(
        state, 0, (),
    )
    new_perms = [o for o in state.battlefield if o not in pre_bf]
    assert len(new_perms) == 1
    assert new_perms[0].plus_one_counters == 1
