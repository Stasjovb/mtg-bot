"""Tests for the third Duskmourn creature parser batch.

This batch grows the parser to claim a small cluster of Duskmourn
creatures whose oracle text needs new trigger / effect / static-gate
primitives layered on top of the existing engine surface — no new
events or core data fields are required.

* **``HasPowerAtMost`` predicate** + **``another creature you control
  with power 2 or less enters`` trigger phrase** — Vicious Clown
  (``{2}{R}`` 2/3) prints this trigger condition with the existing
  ``this creature gets +N/+0 until end of turn`` self-pump body
  (``PumpSelfUntilEOT``). The same condition phrase is also used by
  Irreverent Gremlin and is forward-looking grammar coverage today
  (Gremlin's effect body needs a separate optional-discard-then-draw
  primitive that's out of scope for this batch).
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    PumpSelfUntilEOT,
    TriggeredAbility,
)
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    HasPowerAtMost,
    IsCreature,
    IsSelf,
)


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- ``HasPowerAtMost`` predicate ----------


def test_has_power_at_most_matches_low_power_creature():
    # Direct sanity check that a creature with effective power 2
    # satisfies ``HasPowerAtMost(n=2)``. The predicate reads through
    # ``effective_power`` so a creature whose base power is 2 with no
    # pump or counters tests positive.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    obj = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(obj)
    p = HasPowerAtMost(n=2)
    # ``Wild Bear`` is a 2/2 — power == 2, threshold == 2, predicate true.
    assert p.matches(state, {"obj": obj}, source=obj) is True


def test_has_power_at_most_rejects_higher_power_creature():
    # Belt-and-suspenders that a 3-power creature does NOT satisfy
    # ``HasPowerAtMost(n=2)``. The predicate's bound is inclusive on
    # the threshold, exclusive above it.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards.base import make_creature
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    big = make_creature("BigFixture", "{2}{G}", 3, 3)
    obj = state.new_object(big, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    p = HasPowerAtMost(n=2)
    assert p.matches(state, {"obj": obj}, source=obj) is False


def test_has_power_at_most_rejects_player_subject():
    # A Player subject has no measurable power; the predicate evaluates
    # false rather than raising, mirroring how ``HasKeyword`` /
    # ``HasCounter`` handle player-only subject slots.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    p0 = Player(id=0, agent=RandomAgent())
    state.players.append(p0)
    src = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(src)
    p = HasPowerAtMost(n=2)
    assert p.matches(state, {"obj": p0}, source=src) is False


def test_has_power_at_most_handles_missing_subject():
    # When the named subject slot isn't present in the dispatch
    # mapping, the predicate evaluates false — same convention every
    # subject-scoped predicate uses.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    src = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(src)
    p = HasPowerAtMost(n=2, subject="missing")
    assert p.matches(state, {"obj": src}, source=src) is False


# ---------- trigger-phrase entry ----------


def test_parse_another_creature_with_power_2_or_less_enters_trigger():
    # End-to-end through the trigger-line parser. The condition phrase
    # claims via the predicate-trigger phrasebook with an
    # ``IsCreature() & Controlled(YOU) & HasPowerAtMost(n=2) & ~IsSelf()``
    # composite predicate; the body parses via the existing
    # ``_PUMP_SELF_UEOT`` primitive.
    line = (
        "Whenever another creature you control with power 2 or less "
        "enters, this creature gets +2/+0 until end of turn."
    )
    parsed = _parse_triggered_ability_line(line)
    assert parsed == TriggeredAbility(
        event=Event.ENTERS,
        predicate=(
            IsCreature() & Controlled(YOU) & HasPowerAtMost(n=2) & ~IsSelf()
        ),
        effect=PumpSelfUntilEOT(power_bonus=2, toughness_bonus=0),
    )


# ---------- end-to-end claim ----------


def test_vicious_clown_claimed_by_parser():
    # Vicious Clown ``{2}{R}`` 2/3 Human Clown. Single oracle line:
    # ``Whenever another creature you control with power 2 or less
    # enters, this creature gets +2/+0 until end of turn.`` Claims
    # via the new trigger-phrase entry feeding the existing
    # ``PumpSelfUntilEOT`` self-pump primitive.
    assert "Vicious Clown" in _claimed_names()
