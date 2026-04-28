"""Tests for the DSK ``Whenever you attack`` trigger family.

Three Duskmourn creatures print the once-per-declare-attackers
``Whenever you attack, …`` trigger phrase: Razorkin Hordecaller, Most
Valuable Slayer, and Lionheart Glimmer. The shape is distinct from the
pre-existing ``Whenever this creature attacks`` per-attacker trigger
because it fires exactly ONCE per declare-attackers pass when the
controller has attacked with at least one creature, regardless of how
many attackers were declared.

This batch lands:

* **``Event.YOU_ATTACK``** — a new event with a single Player subject
  (``"player"``) dispatched by ``combat.declare_attackers`` after every
  attacker has been processed (and after Exalted's once-per-pass
  fixup), but only if at least one creature actually entered the
  attacking state. The Player-subject + ``Controlled(YOU)`` predicate
  shape mirrors the turn-structure events
  (``BEGINNING_OF_UPKEEP``, etc.) — same matching rule, different
  fire site.

* **``"you attack"`` trigger phrase** mapping to
  ``(Event.YOU_ATTACK, Controlled(YOU))``. Tied to the new event.

* **``Gremlin`` token printing** in ``cards/tokens.py`` — vanilla 1/1
  Gremlin creature token (Razorkin Hordecaller's create-token body
  resolves against the existing stat-bearing creature-token grammar
  once the registry entry exists).

* **``target attacking creature`` qualifier** on the existing
  ``_PUMP_AND_GAIN_KEYWORDS_UEOT`` regex, surfacing as the new
  ``attacking_only=True`` flag on ``PumpTargetCreatureUntilEOT``.
  Most Valuable Slayer's pump+grant body lands via this primitive —
  the engine class's ``legal_targets`` filters the creature pool to
  those currently flagged ``attacking=True`` regardless of controller.

The shared parametrized parity test in ``tests/test_parser_parity.py``
enforces full ``CardPrinting`` parity, so this file focuses on the new
event / dispatch / grammar in isolation plus the claim assertions.
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.base import (
    CreateToken,
    PumpCreaturesYouControlUntilEOT,
    PumpTargetCreatureUntilEOT,
    TriggeredAbility,
)
from mtg_bot.cards.parser.effects import _parse_effect_phrase
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.triggers import (
    _parse_predicate_trigger_phrase,
    _parse_triggered_ability_line,
)
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.combat import declare_attackers
from mtg_bot.effects.predicates import (
    EVENT_SUBJECTS,
    Controlled,
    Event,
    YOU,
)
from mtg_bot.game import GameState, Player, Zone


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- ``Event.YOU_ATTACK`` registration ----------


def test_you_attack_event_carries_player_subject():
    # Like the turn-structure events the subject is the active Player,
    # not a permanent — so ``Controlled(YOU)`` matches by
    # ``player.id == source.controller_id`` per the existing player-
    # subject branch in the ``Controlled`` predicate.
    assert EVENT_SUBJECTS[Event.YOU_ATTACK] == ("player",)


# ---------- trigger phrase ----------


def test_parse_you_attack_trigger_phrase():
    # The bare ``you attack`` condition resolves to YOU_ATTACK with
    # the controller-of-source player gate. ``Controlled(YOU)`` here
    # reads as "the attacking player is the source's controller" —
    # the same shape used by every other player-subject event.
    assert _parse_predicate_trigger_phrase("you attack") == (
        Event.YOU_ATTACK, Controlled(YOU),
    )


# ---------- ``target attacking creature`` pump+grant ----------


def test_parse_target_attacking_creature_pump_and_grant():
    # Most Valuable Slayer's printed body. The ``attacking`` qualifier
    # narrows the legal-target pool to creatures currently flagged
    # ``attacking=True``; encoded by the engine class's
    # ``attacking_only=True`` flag. Independent of the
    # ``you_control_only`` / ``exclude_self`` flags — neither is set
    # here because the surface text doesn't carry ``another`` /
    # ``you control`` qualifiers.
    parsed = _parse_effect_phrase(
        "target attacking creature gets +1/+0 and gains first strike "
        "until end of turn"
    )
    assert parsed == PumpTargetCreatureUntilEOT(
        power_bonus=1,
        toughness_bonus=0,
        granted_keywords=frozenset({"first strike"}),
        attacking_only=True,
    )


def test_pump_and_grant_bare_form_unchanged_after_attacking_capture():
    # Belt-and-suspenders that adding the optional ``attacking ``
    # capture group didn't widen or narrow the bare ``target creature
    # gets ...`` shape. The bare form must continue to produce
    # ``attacking_only=False, exclude_self=False, you_control_only=
    # False``.
    parsed = _parse_effect_phrase(
        "target creature gets +2/+2 and gains trample until end of turn"
    )
    assert parsed == PumpTargetCreatureUntilEOT(
        power_bonus=2,
        toughness_bonus=2,
        granted_keywords=frozenset({"trample"}),
        attacking_only=False,
        exclude_self=False,
        you_control_only=False,
    )


def test_pump_and_grant_another_you_control_unchanged_after_attacking_capture():
    # Belt-and-suspenders that the ``another target creature you
    # control gets ...`` shape (Hardened Escort) still parses with
    # the original two flags flipped and the new ``attacking_only``
    # flag staying False.
    parsed = _parse_effect_phrase(
        "another target creature you control gets +1/+0 and gains "
        "indestructible until end of turn"
    )
    assert parsed == PumpTargetCreatureUntilEOT(
        power_bonus=1,
        toughness_bonus=0,
        granted_keywords=frozenset({"indestructible"}),
        you_control_only=True,
        exclude_self=True,
        attacking_only=False,
    )


# ---------- ``Gremlin`` token registry entry ----------


def test_gremlin_token_registered():
    # ``Gremlin`` must be present in the token registry so the
    # stat-bearing creature-token grammar can claim Razorkin
    # Hordecaller's "create a 1/1 red Gremlin creature token" body.
    assert "Gremlin" in TOKEN_PRINTINGS


def test_gremlin_token_is_vanilla_one_one_creature():
    # A Gremlin token is a 1/1 with no abilities — same shape as
    # other simple color-bearing tokens (Insect, Sliver). Color
    # isn't tracked through tokens; the registered printing surfaces
    # as a colorless 1/1 creature.
    g = TOKEN_PRINTINGS["Gremlin"]
    assert g.power == 1
    assert g.toughness == 1
    assert "Creature" in g.card_types
    assert "Gremlin" in g.subtypes
    assert g.keywords == frozenset()
    assert g.triggered_abilities == ()
    assert g.activated_abilities == ()
    assert g.static_abilities == ()


def test_parse_create_a_red_gremlin_creature_token():
    # End-to-end through the stat-bearing creature-token grammar.
    # Razorkin Hordecaller's body is exactly this phrase — the regex
    # collapses the token to the ``Gremlin`` registry entry while
    # consuming the color word as part of the surface match.
    eff = _parse_effect_phrase("create a 1/1 red Gremlin creature token")
    assert eff == CreateToken(
        token_printing=TOKEN_PRINTINGS["Gremlin"], count=1,
    )


# ---------- triggered-ability line lookup ----------


def test_triggered_ability_line_recognizes_you_attack():
    # The full surface form parses through ``_parse_triggered_ability
    # _line`` and produces a single ``TriggeredAbility`` whose event
    # is YOU_ATTACK and whose effect is the parsed body.
    parsed = _parse_triggered_ability_line(
        "Whenever you attack, creatures you control get +1/+1 "
        "until end of turn."
    )
    assert parsed == TriggeredAbility(
        event=Event.YOU_ATTACK,
        predicate=Controlled(YOU),
        effect=PumpCreaturesYouControlUntilEOT(
            power_bonus=1,
            toughness_bonus=1,
        ),
    )


# ---------- end-to-end claim assertions ----------


def test_razorkin_hordecaller_claimed_by_parser():
    # Razorkin Hordecaller ``{4}{R}`` 4/4 Human Clown Berserker. Two
    # oracle lines: ``Haste`` (existing keyword) and ``Whenever you
    # attack, create a 1/1 red Gremlin creature token.`` Claims via
    # the new ``you attack`` trigger phrase, the new Gremlin token
    # registry entry, and the existing stat-bearing creature-token
    # grammar.
    assert "Razorkin Hordecaller" in _claimed_names()


def test_most_valuable_slayer_claimed_by_parser():
    # Most Valuable Slayer ``{3}{R}`` 2/4 Human Warrior. Single oracle
    # line: ``Whenever you attack, target attacking creature gets
    # +1/+0 and gains first strike until end of turn.`` Claims via
    # the new ``you attack`` trigger phrase and the extended pump+
    # grant primitive's new ``attacking_only=True`` flag.
    assert "Most Valuable Slayer" in _claimed_names()


def test_lionheart_glimmer_claimed_by_parser():
    # Lionheart Glimmer ``{3}{W}{W}`` 2/5 Cat Glimmer. Two oracle
    # lines: ``Ward {2}`` (existing parametric keyword) and
    # ``Whenever you attack, creatures you control get +1/+1 until
    # end of turn.`` Claims via the new ``you attack`` trigger
    # phrase and the existing mass-pump primitive
    # (``PumpCreaturesYouControlUntilEOT``).
    assert "Lionheart Glimmer" in _claimed_names()


# ---------- combat dispatch — once per declare-attackers pass ----------


def _make_you_attack_counter_creature(name: str):
    """Build a synthetic vanilla 1/1 with a single ``Event.YOU_ATTACK``
    triggered ability. Counting fires is done via the existing
    ``"<source>'s <event> trigger goes on the stack"`` log line that
    ``push_triggered_ability`` emits — one line per push, so counting
    those lines in ``state.log`` tells us how many times YOU_ATTACK
    matched on this source.

    The effect is ``DrawCards(amount=1)`` — innocuous and never resolves
    (we don't drain the stack), so the test's assertion surface stays
    narrow: only the dispatch-and-push side is exercised.
    """
    from mtg_bot.cards.base import DrawCards, make_creature
    return make_creature(
        name, "{R}", 1, 1,
        triggered_abilities=(
            TriggeredAbility(
                event=Event.YOU_ATTACK,
                predicate=Controlled(YOU),
                effect=DrawCards(amount=1),
            ),
        ),
    )


def _setup_two_players_with_synthetic_observer():
    from mtg_bot.agents import RandomAgent
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_you_attack_fires_once_per_pass_with_one_attacker():
    # One attacker → exactly one YOU_ATTACK fire. Counted via the
    # ``trigger pushed`` log line — the centralized dispatcher
    # ``actions.dispatch_event`` calls ``push_triggered_ability`` once
    # per matching ability per source. Our synthetic observer carries
    # exactly one matching ability, so one push means one fire.
    state = _setup_two_players_with_synthetic_observer()
    obs = _make_you_attack_counter_creature("YouAttackObs")
    obs_obj = state.new_object(obs, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(obs_obj)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    declare_attackers(state, [bear.id])
    you_attack_pushes = [
        line for line in state.log
        if "you_attack trigger goes on the stack" in line
    ]
    assert len(you_attack_pushes) == 1


def test_you_attack_fires_once_per_pass_with_multiple_attackers():
    # Multiple attackers → still exactly one YOU_ATTACK fire. The
    # event is dispatched once after every attacker has been
    # processed — distinct from ``Event.ATTACKS`` which fires
    # per-attacker.
    state = _setup_two_players_with_synthetic_observer()
    obs = _make_you_attack_counter_creature("YouAttackObs")
    obs_obj = state.new_object(obs, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(obs_obj)
    bear1 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear1)
    bear2 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear2)
    declare_attackers(state, [bear1.id, bear2.id])
    you_attack_pushes = [
        line for line in state.log
        if "you_attack trigger goes on the stack" in line
    ]
    assert len(you_attack_pushes) == 1


def test_you_attack_does_not_fire_when_no_creatures_attack():
    # Empty attacker list → no YOU_ATTACK dispatch at all. The check
    # at the top of ``_fire_you_attack_triggers`` skips the dispatch
    # entirely; the printed phrasing "Whenever you attack" requires
    # at least one creature to actually attack per CR 506.2 (declaring
    # zero attackers isn't an attack).
    state = _setup_two_players_with_synthetic_observer()
    obs = _make_you_attack_counter_creature("YouAttackObs")
    obs_obj = state.new_object(obs, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(obs_obj)
    declare_attackers(state, [])
    you_attack_pushes = [
        line for line in state.log
        if "you_attack trigger goes on the stack" in line
    ]
    assert len(you_attack_pushes) == 0


def test_you_attack_gates_on_controller_via_predicate():
    # The ``Controlled(YOU)`` predicate on the trigger means an
    # observer controlled by P1 doesn't fire on P0's attack. Same
    # rule the turn-structure events use against player subjects.
    state = _setup_two_players_with_synthetic_observer()
    obs = _make_you_attack_counter_creature("YouAttackObs")
    # Observer is controlled by P1; the attacker belongs to P0.
    obs_obj = state.new_object(obs, owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.append(obs_obj)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    declare_attackers(state, [bear.id])
    you_attack_pushes = [
        line for line in state.log
        if "you_attack trigger goes on the stack" in line
    ]
    assert len(you_attack_pushes) == 0
