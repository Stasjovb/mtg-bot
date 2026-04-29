"""Tests for the sixth Duskmourn creature parser batch.

This batch claims a pair of common-rarity Duskmourn (set code ``dsk``)
creatures whose oracle lines need only printing-level ETB-replacement
fields plus the line recognizers that flip them:

* **Cackling Slasher** ``{3}{B}`` 3/3 Common Human Assassin —
  ``Deathtouch`` plus
  ``This creature enters with a +1/+1 counter on it if a creature died
  this turn.`` The new
  ``CardPrinting.enters_with_plus_one_counter_if_creature_died_this_turn``
  field fires from ``actions.put_into_battlefield`` when the global
  ``GameState.creatures_died_this_turn`` tracker is positive. The
  tracker is incremented in ``turn.move_off_battlefield`` for every
  creature dies event the engine fires (regardless of controller —
  Cackling Slasher's printed clause doesn't qualify "you control") and
  reset by ``run_cleanup_step``.

* **Patched Plaything** ``{2}{W}`` 4/3 Uncommon Artifact Creature — Toy
  — ``Double strike`` plus
  ``This creature enters with two -1/-1 counters on it if you cast it
  from your hand.`` The new
  ``CardPrinting.enters_with_minus_one_counters_from_hand_cast``
  field fires from ``actions.put_into_battlefield`` only when the
  GameObject's ``cast_via_hand`` flag is set. ``cast_via_hand`` is
  flipped in ``actions._cast_spell``'s cast-from-hand branch and
  cleared on every other cast path (warp-from-graveyard, cast-from-
  exile, cast-from-top-of-library), so the rider stays inert on
  non-hand-origin resolutions exactly as the printed text gates.

The shared parametrized parity test in the existing parser test
corpus enforces full ``CardPrinting`` parity, so this file focuses on
the new printing-level fields, the line recognizers, the engine
hooks, and the end-to-end claim assertions.
"""

from __future__ import annotations

from mtg_bot.cards.parser.printing_keywords import (
    _parse_enters_with_minus_one_counters_from_hand_cast_line,
    _parse_enters_with_plus_one_counter_if_creature_died_line,
)
from mtg_bot.cards.parser.source import OracleParserCardSource


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- ``enters with +1/+1 counter if a creature died`` recognizer ----------


def test_parse_enters_with_plus_one_counter_if_creature_died_match():
    # Cackling Slasher's verbatim surface form. The recognizer is a
    # literal-string match — no card today varies the wording — so a
    # forward-looking surface variant ("if any creature died" / "if a
    # creature has died") would intentionally not match and would land
    # its own recognizer rather than parameterize this one.
    assert _parse_enters_with_plus_one_counter_if_creature_died_line(
        "This creature enters with a +1/+1 counter on it if a "
        "creature died this turn."
    ) is True


def test_parse_enters_with_plus_one_counter_if_creature_died_unrelated():
    # A near-miss surface that drops the death-condition tail must NOT
    # match — the bare ``This creature enters with a +1/+1 counter on
    # it.`` body is a different printed mechanic (no DSK card today,
    # but the recognizer must stay narrow). Belt-and-suspenders against
    # accidentally widening the literal-string recognizer.
    assert _parse_enters_with_plus_one_counter_if_creature_died_line(
        "This creature enters with a +1/+1 counter on it."
    ) is False


# ---------- ``enters with N -1/-1 counters from hand cast`` recognizer ----------


def test_parse_enters_with_minus_one_counters_from_hand_cast_two():
    # Patched Plaything's verbatim surface form. The cardinal ``two``
    # round-trips to ``int(2)`` via the spelled-out cardinal table so
    # the engine field stores a plain integer count.
    assert _parse_enters_with_minus_one_counters_from_hand_cast_line(
        "This creature enters with two -1/-1 counters on it if you "
        "cast it from your hand."
    ) == 2


def test_parse_enters_with_minus_one_counters_from_hand_cast_digit():
    # Forward-looking digit form. Same engine field; the recognizer's
    # ``\d+`` arm picks it up so a future printing that prints the
    # numeric ``2`` (or any other count) doesn't need a grammar
    # change. No DSK printing today uses this surface.
    assert _parse_enters_with_minus_one_counters_from_hand_cast_line(
        "This creature enters with 3 -1/-1 counters on it if you cast "
        "it from your hand."
    ) == 3


def test_parse_enters_with_minus_one_counters_from_hand_cast_singular():
    # Forward-looking ``one`` singular variant — the regex's
    # alternation includes the spelled-out cardinal and the ``counters?``
    # arm tolerates the singular "counter" tail. The engine accepts any
    # positive integer for the field; a 1-counter rider would resolve
    # the same way as the 2-counter one (Patched Plaything) at ETB.
    assert _parse_enters_with_minus_one_counters_from_hand_cast_line(
        "This creature enters with one -1/-1 counter on it if you cast "
        "it from your hand."
    ) == 1


def test_parse_enters_with_minus_one_counters_from_hand_cast_unrelated():
    # A near-miss line that swaps the cast-zone gate for an unrelated
    # phrase must NOT match — the recognizer is anchored on the
    # ``if you cast it from your hand`` tail. Belt-and-suspenders
    # against accidentally widening the regex to a generic ETB-counter
    # rider.
    assert _parse_enters_with_minus_one_counters_from_hand_cast_line(
        "This creature enters with two -1/-1 counters on it if it's "
        "your turn."
    ) is None


# ---------- engine hook: creatures_died_this_turn tracker ----------


def test_creatures_died_this_turn_tracker_increments_on_death():
    # The tracker on ``GameState`` is bumped from 0 → 1 when any
    # creature transitions from battlefield to graveyard via
    # ``move_off_battlefield``. The increment runs BEFORE
    # ``_fire_dies_triggers`` so an in-trigger ETB replacement that
    # reads the tracker (Cackling Slasher) sees this very death too.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import move_off_battlefield

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    assert state.creatures_died_this_turn == 0
    move_off_battlefield(state, bear, destination="graveyard")
    assert state.creatures_died_this_turn == 1


def test_creatures_died_this_turn_tracker_no_increment_on_exile():
    # Exile is not death; the tracker stays at 0 when a creature is
    # moved to exile. Mirrors the engine-side ``was_creature`` gate
    # which already restricts the dies-trigger fire to the graveyard
    # destination — extending the same gate to the death-counter is
    # the natural reading of CR 700.4 (a creature only "dies" when it
    # goes from battlefield to graveyard).
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import move_off_battlefield

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    move_off_battlefield(state, bear, destination="exile")
    assert state.creatures_died_this_turn == 0


def test_creatures_died_this_turn_tracker_no_increment_on_noncreature():
    # A non-creature permanent (a vanilla artifact) leaving the
    # battlefield doesn't bump the tracker — the gate keys on
    # ``is_creature_now`` at the moment of departure. Belt-and-
    # suspenders that the tracker isn't accidentally generalized to
    # every permanent type.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import move_off_battlefield

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    treasure = state.new_object(
        TOKEN_PRINTINGS["Treasure"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(treasure)
    move_off_battlefield(state, treasure, destination="graveyard")
    assert state.creatures_died_this_turn == 0


def test_creatures_died_this_turn_tracker_resets_at_cleanup():
    # The tracker is per-turn; ``run_cleanup_step`` resets it to 0
    # alongside the other turn-scoped trackers (Void flags, life-
    # gained, lands-entered, etc.). Without the reset the rider
    # would leak counters across turns, which Cackling Slasher's
    # printed text doesn't authorize.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.game import GameState, Player
    from mtg_bot.turn import run_cleanup_step

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.creatures_died_this_turn = 5
    run_cleanup_step(state)
    assert state.creatures_died_this_turn == 0


def test_creatures_died_this_turn_tracker_clones_via_state_clone():
    # The clone path mirrors every per-turn flag onto the new state so
    # search rollouts see the same tracker value. Without this carry-
    # through, a rollout would lose the Cackling Slasher rider's
    # input-state mid-search.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.game import GameState, Player

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.creatures_died_this_turn = 3
    cloned = state.clone()
    assert cloned.creatures_died_this_turn == 3


# ---------- engine hook: cast_via_hand provenance flag ----------


def test_cast_via_hand_default_false_on_new_object():
    # A freshly-minted ``GameObject`` defaults ``cast_via_hand`` to
    # False. The flag is set only by the cast-from-hand branch in
    # ``_cast_spell``; an object that never went through that path
    # (a deck-creation card, a token, a card moved into hand by a
    # search-and-put effect that hasn't been cast yet) reads False.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.HAND,
    )
    assert bear.cast_via_hand is False


# ---------- engine hook: ETB replacements ----------


def test_etb_replacement_plus_one_counter_active_when_creature_died():
    # The +1/+1 counter rider applies at ETB when the death tracker
    # is positive. We pre-seed ``creatures_died_this_turn`` to 1 to
    # simulate a prior death this turn, then put a Cackling Slasher
    # printing onto the battlefield via the engine path. The counter
    # lands as part of the ETB sequence — same place the existing
    # ``enters_with_counters_from_x`` riders fire — so the post-ETB
    # creature reads with one +1/+1 counter on it.
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.agents import RandomAgent
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    src = OracleParserCardSource()
    cs_p = src.get_printings()["Cackling Slasher"]
    cs = state.new_object(cs_p, owner_id=0, zone=Zone.STACK)
    state.creatures_died_this_turn = 1
    put_into_battlefield(state, cs, controller_id=0)
    assert cs in state.battlefield
    assert cs.plus_one_counters == 1


def test_etb_replacement_plus_one_counter_inactive_with_no_deaths():
    # The +1/+1 counter rider does NOT apply at ETB when no creature
    # has died this turn (tracker still at 0). Belt-and-suspenders
    # against the rider being silently always-on rather than gated.
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.agents import RandomAgent
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    src = OracleParserCardSource()
    cs_p = src.get_printings()["Cackling Slasher"]
    cs = state.new_object(cs_p, owner_id=0, zone=Zone.STACK)
    assert state.creatures_died_this_turn == 0
    put_into_battlefield(state, cs, controller_id=0)
    assert cs in state.battlefield
    assert cs.plus_one_counters == 0


def test_etb_replacement_minus_one_counters_from_hand_cast_only():
    # Patched Plaything's two -1/-1 counters fire at ETB only when
    # ``cast_via_hand`` is True. We mark the GameObject ourselves to
    # simulate the cast-from-hand provenance and confirm the two
    # counters land. The ``cast_via_hand`` flag is cleared at ETB so
    # a future blink-and-recast under the printed cost doesn't
    # double-apply the rider.
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.agents import RandomAgent
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    src = OracleParserCardSource()
    pp_p = src.get_printings()["Patched Plaything"]
    pp = state.new_object(pp_p, owner_id=0, zone=Zone.STACK)
    pp.cast_via_hand = True
    put_into_battlefield(state, pp, controller_id=0)
    assert pp in state.battlefield
    assert pp.minus_one_counters == 2
    # ``cast_via_hand`` cleared post-ETB so a re-trigger via blink
    # under the printed cost stays inert.
    assert pp.cast_via_hand is False


def test_etb_replacement_minus_one_counters_inactive_when_not_from_hand():
    # If the card resolved without ``cast_via_hand`` set (cast from
    # exile, top of library, graveyard, or put into play directly),
    # the -1/-1 rider does NOT fire. Patched Plaything reads its
    # printed P/T (4/3) without any -1/-1 counters.
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.agents import RandomAgent
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    src = OracleParserCardSource()
    pp_p = src.get_printings()["Patched Plaything"]
    pp = state.new_object(pp_p, owner_id=0, zone=Zone.STACK)
    assert pp.cast_via_hand is False
    put_into_battlefield(state, pp, controller_id=0)
    assert pp in state.battlefield
    assert pp.minus_one_counters == 0


# ---------- end-to-end claim assertions ----------


def test_cackling_slasher_claimed_by_parser():
    # Cackling Slasher ``{3}{B}`` 3/3 Common Human Assassin. Two oracle
    # lines: ``Deathtouch`` and ``This creature enters with a +1/+1
    # counter on it if a creature died this turn.`` Claims via the
    # existing keyword-line grammar for the first line plus the new
    # printing-level ETB-replacement field for the second.
    assert "Cackling Slasher" in _claimed_names()


def test_cackling_slasher_carries_etb_replacement_field():
    # Belt-and-suspenders that the claimed printing actually carries
    # ``enters_with_plus_one_counter_if_creature_died_this_turn=True``
    # — a regression that dropped the field would silently always-on
    # the rider (or never fire it), which Cackling Slasher's printed
    # text doesn't authorize.
    src = OracleParserCardSource()
    cs = src.get_printings()["Cackling Slasher"]
    assert "deathtouch" in cs.keywords
    assert (
        cs.enters_with_plus_one_counter_if_creature_died_this_turn is True
    )


def test_patched_plaything_claimed_by_parser():
    # Patched Plaything ``{2}{W}`` 4/3 Uncommon Artifact Creature — Toy.
    # Two oracle lines: ``Double strike`` and ``This creature enters
    # with two -1/-1 counters on it if you cast it from your hand.``
    # Claims via the existing keyword-line grammar for the first line
    # plus the new printing-level ETB-replacement field for the
    # second.
    assert "Patched Plaything" in _claimed_names()


def test_patched_plaything_carries_etb_replacement_field():
    # Belt-and-suspenders that the claimed printing actually carries
    # ``enters_with_minus_one_counters_from_hand_cast=2`` — the
    # printed two-counter count round-trips through the spelled-
    # cardinal table. A regression that dropped or zeroed the field
    # would silently leave Patched Plaything as a 4/3 with no -1/-1
    # rider regardless of cast zone.
    src = OracleParserCardSource()
    pp = src.get_printings()["Patched Plaything"]
    assert "double strike" in pp.keywords
    assert pp.enters_with_minus_one_counters_from_hand_cast == 2


# ---------- defensive: cast-paths clear cast_via_hand ----------


def test_cast_via_hand_cleared_when_returning_via_blink():
    # A blink-and-recast scenario: the card is exiled, returns to the
    # battlefield via a put-into-play path that doesn't re-cast it
    # from hand. The ``cast_via_hand`` flag was cleared at the prior
    # ETB so the second resolution doesn't re-apply the -1/-1 rider.
    # We simulate by putting the card into the battlefield twice,
    # only the first time with ``cast_via_hand=True``.
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.agents import RandomAgent
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    src = OracleParserCardSource()
    pp_p = src.get_printings()["Patched Plaything"]
    pp = state.new_object(pp_p, owner_id=0, zone=Zone.STACK)
    pp.cast_via_hand = True
    put_into_battlefield(state, pp, controller_id=0)
    assert pp.minus_one_counters == 2
    # Simulate a blink: pull off the battlefield, put it back without
    # re-flipping ``cast_via_hand``. The rider stays inert.
    state.battlefield.remove(pp)
    pp.zone = Zone.STACK
    pp.minus_one_counters = 0  # Counters reset by blink replacement.
    put_into_battlefield(state, pp, controller_id=0)
    assert pp.minus_one_counters == 0
