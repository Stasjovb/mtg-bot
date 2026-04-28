"""Tests for the DSK ``This creature must be blocked if able.`` clause.

Adds a printing-level static block-requirement (CR 509.1c). The
oracle text is verbatim ``This creature must be blocked if able.`` and
surfaces on Fear of Being Hunted alongside Haste. Engine enforcement
lives in ``actions._declare_blockers``: for each attacker carrying the
flag, if the defending player didn't assign a blocker to it, the
engine scans the eligible-blockers pool deterministically (lowest id
first) for an unused defender that ``combat.can_block`` accepts and
forces the assignment.
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser.printing_keywords import _parse_must_be_blocked_line
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.combat import declare_attackers
from mtg_bot.game import GameState, Player, Zone


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- line recognizer ----------


def test_parse_must_be_blocked_line_recognizes_canonical_form():
    # Verbatim Scryfall surface form. Whitespace tolerant via the
    # recognizer's own ``.strip()``.
    assert _parse_must_be_blocked_line(
        "This creature must be blocked if able."
    ) is True


def test_parse_must_be_blocked_line_rejects_other_forms():
    # Variants we DON'T match: missing period, broader "permanent"
    # wording, or an unrelated must-attack rider. Each would land its
    # own recognizer rather than parameterizing this one.
    assert _parse_must_be_blocked_line(
        "This creature must be blocked if able"
    ) is False
    assert _parse_must_be_blocked_line(
        "This permanent must be blocked if able."
    ) is False
    assert _parse_must_be_blocked_line(
        "This creature must attack if able."
    ) is False
    assert _parse_must_be_blocked_line("") is False


# ---------- make_creature kwarg threading ----------


def test_make_creature_threads_must_be_blocked_flag():
    # Direct sanity check that the kwarg reaches the produced
    # ``CardPrinting`` field. The default stays ``False`` for every
    # creature that doesn't pass the kwarg.
    p = make_creature(
        "Test Must Block", "{1}{R}", 4, 2, must_be_blocked_if_able=True,
    )
    assert p.must_be_blocked_if_able is True
    p_default = make_creature("Test Default", "{1}{R}", 4, 2)
    assert p_default.must_be_blocked_if_able is False


# ---------- end-to-end claim ----------


def test_fear_of_being_hunted_claimed_by_parser():
    # Fear of Being Hunted ``{1}{R}{R}`` 4/2 Enchantment Creature —
    # Nightmare. Two oracle lines: ``Haste`` (existing keyword) and
    # ``This creature must be blocked if able.`` (new printing
    # keyword). Claims via the existing haste keyword grammar plus
    # the new ``_parse_must_be_blocked_line`` recognizer flipping
    # the new ``must_be_blocked_if_able=True`` kwarg on
    # ``make_creature``.
    assert "Fear of Being Hunted" in _claimed_names()


def test_fear_of_being_hunted_carries_must_be_blocked_flag():
    # The claimed printing must actually carry the field — without
    # the threading from the builder to ``make_creature`` to the
    # printing's ``must_be_blocked_if_able`` field, the engine's
    # ``_declare_blockers`` enforcement wouldn't have anything to
    # gate on.
    src = OracleParserCardSource()
    printings = {p.name: p for p in src.get_printings().values()}
    p = printings["Fear of Being Hunted"]
    assert p.must_be_blocked_if_able is True
    assert "haste" in p.keywords


# ---------- engine enforcement (CR 509.1c) ----------


def _setup_two_players_with_creatures(*, attacker_printing, blocker_printing):
    """Stage a defender-side creature against a must-be-blocked attacker.

    Returns ``(state, attacker_obj, blocker_obj)``. The attacker
    belongs to P0 (the active/attacking player by convention), the
    blocker to P1 (the defending player). Summoning sickness is
    cleared on the blocker so it's eligible.
    """
    from mtg_bot.agents import RandomAgent
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    attacker_obj = state.new_object(
        attacker_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(attacker_obj)
    blocker_obj = state.new_object(
        blocker_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    blocker_obj.summoning_sick = False
    state.battlefield.append(blocker_obj)
    return state, attacker_obj, blocker_obj


def test_must_be_blocked_forces_block_when_defender_skipped():
    # Defender skips the block (passes empty assignments) but has an
    # eligible+legal blocker. The engine forces the assignment per
    # CR 509.1c. Assertion: the blocker ends up assigned to the
    # must-be-blocked attacker.
    from mtg_bot.actions import _declare_blockers
    fear = make_creature(
        "FearLikeFixture", "{1}{R}{R}", 4, 2,
        keywords={"haste"}, must_be_blocked_if_able=True,
    )
    state, attacker, blocker = _setup_two_players_with_creatures(
        attacker_printing=fear,
        blocker_printing=SYNTHETIC_CREATURES["Wild Bear"],
    )
    declare_attackers(state, [attacker.id])
    _declare_blockers(state, player_id=1, assignments=())
    assert blocker.blocking == attacker.id


def test_must_be_blocked_does_not_force_when_no_eligible_blocker():
    # No eligible blockers (the only defender-side creature is
    # tapped). The forced-assignment path should bail gracefully —
    # no block is added, the attacker goes through unblocked.
    # Tapped creatures are excluded by ``eligible_blockers`` per
    # CR 509.1a.
    from mtg_bot.actions import _declare_blockers
    fear = make_creature(
        "FearLikeFixture", "{1}{R}{R}", 4, 2,
        keywords={"haste"}, must_be_blocked_if_able=True,
    )
    state, attacker, blocker = _setup_two_players_with_creatures(
        attacker_printing=fear,
        blocker_printing=SYNTHETIC_CREATURES["Wild Bear"],
    )
    blocker.tapped = True
    declare_attackers(state, [attacker.id])
    _declare_blockers(state, player_id=1, assignments=())
    assert blocker.blocking is None


def test_must_be_blocked_does_not_force_when_block_illegal():
    # Eligible defender exists but ``can_block`` rejects it because
    # the attacker has flying and the defender doesn't have flying
    # or reach. Per CR 509.1c "if able" requires the block to be
    # legal — the requirement applies only when the defender has at
    # least one creature that COULD block. Here it doesn't, so the
    # attacker goes through unblocked.
    from mtg_bot.actions import _declare_blockers
    flier_fear = make_creature(
        "FlyingFearFixture", "{1}{U}", 2, 2,
        keywords={"flying"}, must_be_blocked_if_able=True,
    )
    state, attacker, blocker = _setup_two_players_with_creatures(
        attacker_printing=flier_fear,
        blocker_printing=SYNTHETIC_CREATURES["Wild Bear"],
    )
    declare_attackers(state, [attacker.id])
    _declare_blockers(state, player_id=1, assignments=())
    assert blocker.blocking is None


def test_must_be_blocked_skipped_when_defender_already_assigned():
    # Defender DID assign a blocker — the enforcement path is a no-op.
    # Belt-and-suspenders that the forced-assignment scan only runs
    # when the requirement is unfulfilled.
    from mtg_bot.actions import _declare_blockers
    fear = make_creature(
        "FearLikeFixture", "{1}{R}{R}", 4, 2,
        keywords={"haste"}, must_be_blocked_if_able=True,
    )
    state, attacker, blocker = _setup_two_players_with_creatures(
        attacker_printing=fear,
        blocker_printing=SYNTHETIC_CREATURES["Wild Bear"],
    )
    declare_attackers(state, [attacker.id])
    _declare_blockers(
        state, player_id=1,
        assignments=((blocker.id, attacker.id),),
    )
    # The defender's own assignment stuck — no double-assignment.
    assert blocker.blocking == attacker.id


def test_no_forcing_for_creature_without_must_be_blocked_flag():
    # Pure regression check: a synthetic vanilla attacker without the
    # flag never triggers the forced-assignment path. Asserts the
    # defender's empty-assignment intent is honored.
    from mtg_bot.actions import _declare_blockers
    state, attacker, blocker = _setup_two_players_with_creatures(
        attacker_printing=SYNTHETIC_CREATURES["Wild Bear"],
        blocker_printing=SYNTHETIC_CREATURES["Wild Bear"],
    )
    declare_attackers(state, [attacker.id])
    _declare_blockers(state, player_id=1, assignments=())
    assert blocker.blocking is None
