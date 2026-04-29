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


# ---------- ``GrantUnblockableUEOT`` attacking_only / exclude_self ----------


def test_grant_unblockable_attacking_only_filters_legal_targets():
    # With ``attacking_only=True``, ``legal_targets`` only returns
    # creatures whose ``attacking`` flag is True right now. A non-
    # attacking creature on the battlefield is excluded from the pool.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.cards.base import GrantUnblockableUEOT
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    attacker = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    attacker.attacking = True
    state.battlefield.append(attacker)
    sitter = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(sitter)
    eff = GrantUnblockableUEOT(attacking_only=True)
    legal = eff.legal_targets(state, controller_id=0)
    assert ("creature", attacker.id) in legal
    assert ("creature", sitter.id) not in legal


def test_grant_unblockable_exclude_self_filters_source():
    # With ``exclude_self=True`` and ``state.resolving_source`` set to
    # the source object, that object is filtered out of the legal-
    # target pool even if it would otherwise qualify.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.cards.base import GrantUnblockableUEOT
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    src = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    src.attacking = True
    state.battlefield.append(src)
    other = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    other.attacking = True
    state.battlefield.append(other)
    state.resolving_source = src
    try:
        eff = GrantUnblockableUEOT(attacking_only=True, exclude_self=True)
        legal = eff.legal_targets(state, controller_id=0)
    finally:
        state.resolving_source = None
    assert ("creature", src.id) not in legal
    assert ("creature", other.id) in legal


def test_grant_unblockable_describe_attacking_other():
    # The ``describe`` output reflects the attacking-only +
    # exclude-self combo as ``another target attacking creature can't
    # be blocked this turn`` — the Clammy Prowler surface form.
    from mtg_bot.cards.base import GrantUnblockableUEOT
    eff = GrantUnblockableUEOT(attacking_only=True, exclude_self=True)
    assert eff.describe() == (
        "another target attacking creature can't be blocked this turn"
    )


def test_grant_unblockable_describe_attacking_only():
    # Attacking-only without exclude-self describes as ``target
    # attacking creature can't be blocked this turn`` — forward-looking
    # surface form not used by any DSK printing today but kept
    # symmetric with the other flag combinations.
    from mtg_bot.cards.base import GrantUnblockableUEOT
    eff = GrantUnblockableUEOT(attacking_only=True)
    assert eff.describe() == (
        "target attacking creature can't be blocked this turn"
    )


def test_parse_another_target_attacking_creature_unblockable():
    # End-to-end through the effect-phrase parser. The phrase
    # ``another target attacking creature can't be blocked this turn``
    # parses to ``GrantUnblockableUEOT(attacking_only=True,
    # exclude_self=True)``.
    from mtg_bot.cards.base import GrantUnblockableUEOT
    from mtg_bot.cards.parser.effects import _parse_effect_phrase
    parsed = _parse_effect_phrase(
        "another target attacking creature can't be blocked this turn"
    )
    assert parsed == GrantUnblockableUEOT(
        attacking_only=True, exclude_self=True,
    )


def test_clammy_prowler_claimed_by_parser():
    # Clammy Prowler ``{3}{U}`` 2/5 Enchantment Creature — Horror.
    # Single oracle line: ``Whenever this creature attacks, another
    # target attacking creature can't be blocked this turn.`` Claims
    # via the existing ``this creature attacks`` predicate-trigger
    # phrase + the new ``another target attacking creature`` variant
    # of the unblockable-UEOT primitive.
    assert "Clammy Prowler" in _claimed_names()


# ---------- ``unlocked doors among Rooms`` static gate ----------


def test_static_unlocked_doors_gate_inactive_below_threshold():
    # ``StaticAbility`` with ``requires_unlocked_doors_among_rooms=2``
    # is inert until the controller's battlefield contains at least
    # two unlocked doors (per-half count) across Rooms they control.
    # With zero Rooms in play, the ability does NOT apply to its
    # source.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    src = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(src)
    static = StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=3,
        requires_unlocked_doors_among_rooms=2,
    )
    assert static.applies_to(src, src, state) is False


def test_static_unlocked_doors_gate_active_at_threshold():
    # With two unlocked doors on the controller's battlefield (one
    # Room with both halves unlocked, OR two Rooms with one half
    # each), the ability applies to its source. Models Rampaging
    # Soulrager's printed gate.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    src = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(src)
    # Find any Room printing in the parser pool to use as a fixture.
    printings = OracleParserCardSource().get_printings()
    room_p = next(
        p for p in printings.values()
        if "Room" in p.subtypes
    )
    room = state.new_object(room_p, owner_id=0, zone=Zone.BATTLEFIELD)
    room.unlocked_halves = frozenset(h.name for h in room_p.room_halves)
    state.battlefield.append(room)
    static = StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=3,
        requires_unlocked_doors_among_rooms=2,
    )
    # Exactly 2 doors unlocked on the lone Room → applies.
    assert static.applies_to(src, src, state) is True


def test_static_unlocked_doors_gate_ignores_opponent_rooms():
    # Rooms controlled by an opponent don't contribute to the source's
    # controller's door count. With both halves of an opponent's Room
    # unlocked, the source-side ability still doesn't apply.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    src = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(src)
    printings = OracleParserCardSource().get_printings()
    room_p = next(
        p for p in printings.values()
        if "Room" in p.subtypes
    )
    opp_room = state.new_object(room_p, owner_id=1, zone=Zone.BATTLEFIELD)
    opp_room.unlocked_halves = frozenset(h.name for h in room_p.room_halves)
    state.battlefield.append(opp_room)
    static = StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=3,
        requires_unlocked_doors_among_rooms=2,
    )
    assert static.applies_to(src, src, state) is False


def test_rampaging_soulrager_claimed_by_parser():
    # Rampaging Soulrager ``{2}{R}`` 1/4 Spirit. Single oracle line:
    # ``This creature gets +3/+0 as long as there are two or more
    # unlocked doors among Rooms you control.`` Claims via the
    # existing trailing ``as long as <condition>`` static-ability
    # grammar feeding the new ``requires_unlocked_doors_among_rooms``
    # gate field on ``StaticAbility``.
    assert "Rampaging Soulrager" in _claimed_names()


def test_rampaging_soulrager_carries_unlocked_doors_static():
    # The claimed printing must actually carry the new gate field on
    # its static ability — otherwise the engine wouldn't gate the +3/+0
    # bonus on the door threshold and the printing would over-pump
    # whenever it's on the battlefield.
    from mtg_bot.cards.parser.source import OracleParserCardSource
    src = OracleParserCardSource()
    soulrager = src.get_printings()["Rampaging Soulrager"]
    statics = soulrager.static_abilities
    assert len(statics) == 1
    static = statics[0]
    assert static.power_bonus == 3
    assert static.toughness_bonus == 0
    assert static.requires_unlocked_doors_among_rooms == 2


# ---------- intervening-``while`` trigger shape ----------


def test_parse_pump_self_with_it_subject_pronoun():
    # Belt-and-suspenders that the relaxed self-pump regexes accept the
    # ``it`` source-subject pronoun (``it gets +N/+M ...``) — Hand That
    # Feeds prints its trigger body with ``it`` rather than the
    # ``this creature`` form Eerie cards use, and the
    # ``_normalize_creature_effect_phrase`` normalizer strips ``it ``
    # leaving the bare ``gets +N/+M`` shape that the regexes now
    # tolerate via an optional ``(?:this creature )?`` prefix.
    from mtg_bot.cards.base import PumpSelfUntilEOT
    from mtg_bot.cards.parser.effects import _parse_effect_phrase
    parsed = _parse_effect_phrase(
        "it gets +2/+0 and gains menace until end of turn"
    )
    assert parsed == PumpSelfUntilEOT(
        power_bonus=2, toughness_bonus=0,
        granted_keywords=frozenset({"menace"}),
    )


def test_parse_pump_self_with_this_creature_subject_unchanged():
    # Belt-and-suspenders that adding the optional ``(?:this creature
    # )?`` prefix didn't break the canonical surface — the
    # ``this creature gets +N/+M`` form Eerie cards use must continue
    # to claim the same engine class.
    from mtg_bot.cards.base import PumpSelfUntilEOT
    from mtg_bot.cards.parser.effects import _parse_effect_phrase
    parsed = _parse_effect_phrase(
        "this creature gets +2/+0 and gains lifelink until end of turn"
    )
    assert parsed == PumpSelfUntilEOT(
        power_bonus=2, toughness_bonus=0,
        granted_keywords=frozenset({"lifelink"}),
    )


def test_parse_intervening_while_trigger_line():
    # End-to-end through the trigger-line parser. The intervening-
    # ``while`` shape composes the trigger condition (``this creature
    # attacks``) with the ``while`` gate predicate (``Delirium``) via
    # plain ``And``, mirroring the middle-clause intervening-if path.
    from mtg_bot.cards.base import (
        PumpSelfUntilEOT,
        TriggeredAbility,
    )
    from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line
    from mtg_bot.effects.predicates import (
        Delirium,
        Event,
        IsSelf,
    )
    line = (
        "Whenever this creature attacks while there are four or more "
        "card types among cards in your graveyard, it gets +2/+0 and "
        "gains menace until end of turn."
    )
    parsed = _parse_triggered_ability_line(line)
    assert parsed == TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsSelf() & Delirium(),
        effect=PumpSelfUntilEOT(
            power_bonus=2, toughness_bonus=0,
            granted_keywords=frozenset({"menace"}),
        ),
    )


def test_parse_intervening_while_unrecognized_gate_rejects():
    # An unrecognized ``while`` gate phrase rejects the whole line —
    # same don't-silently-drop-the-gate discipline as the
    # ``, if `` middle-clause path. The line shape regex matches
    # because the ``while`` boundary is present, but the gate phrase
    # lookup fails so the parser declines.
    from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line
    line = (
        "Whenever this creature attacks while the moon is full, "
        "it gets +1/+0 until end of turn."
    )
    assert _parse_triggered_ability_line(line) is None


def test_hand_that_feeds_claimed_by_parser():
    # Hand That Feeds ``{1}{R}`` 2/2 Mutant. Single oracle line:
    # ``Delirium — Whenever this creature attacks while there are four
    # or more card types among cards in your graveyard, it gets +2/+0
    # and gains menace until end of turn.`` Claims via the existing
    # ``Delirium —`` ability-word prefix strip + the new
    # intervening-``while`` line shape feeding the existing
    # ``Delirium()`` gate predicate, with the body parsing through the
    # relaxed ``it``-or-``this creature`` self-pump-and-grant grammar.
    assert "Hand That Feeds" in _claimed_names()


# ---------- ``GrantUnblockableUEOT`` power_at_most filter ----------


def test_grant_unblockable_power_at_most_filters_high_power_targets():
    # With ``power_at_most=2`` the legal-target pool excludes creatures
    # whose effective power exceeds the threshold. A 3-power creature
    # is omitted; a 2-power creature is included.
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.cards.base import GrantUnblockableUEOT, make_creature
    from mtg_bot.game import GameState, Player, Zone
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    small = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(small)
    big = state.new_object(
        make_creature("BigFixture", "{2}{G}", 3, 3),
        owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(big)
    eff = GrantUnblockableUEOT(power_at_most=2)
    legal = eff.legal_targets(state, controller_id=0)
    assert ("creature", small.id) in legal
    assert ("creature", big.id) not in legal


def test_grant_unblockable_power_at_most_describe():
    # The describe output spells out the power threshold so log
    # messages are readable.
    from mtg_bot.cards.base import GrantUnblockableUEOT
    eff = GrantUnblockableUEOT(power_at_most=2)
    assert eff.describe() == (
        "target creature with power 2 or less can't be blocked this turn"
    )


def test_parse_target_creature_with_power_at_most_unblockable():
    # End-to-end through the effect-phrase parser. The phrase
    # ``target creature with power 2 or less can't be blocked this
    # turn`` parses to ``GrantUnblockableUEOT(power_at_most=2)``.
    from mtg_bot.cards.base import GrantUnblockableUEOT
    from mtg_bot.cards.parser.effects import _parse_effect_phrase
    parsed = _parse_effect_phrase(
        "target creature with power 2 or less can't be blocked this turn"
    )
    assert parsed == GrantUnblockableUEOT(power_at_most=2)


def test_ragged_playmate_claimed_by_parser():
    # Ragged Playmate ``{1}{R}`` 2/2 Artifact Creature — Toy. Single
    # oracle line: ``{1}, {T}: Target creature with power 2 or less
    # can't be blocked this turn.`` Claims via the existing
    # ``{mana}, {T}`` activation-cost grammar plus the new
    # ``power_at_most`` variant of the unblockable-UEOT primitive.
    assert "Ragged Playmate" in _claimed_names()
