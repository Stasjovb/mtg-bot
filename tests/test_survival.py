"""Tests for the DSK Survival ability-word trigger family.

Survival is a triggered-ability shape with a fixed condition:
``Survival — At the beginning of your second main phase, if this
creature is tapped, <effect>.`` The trigger maps to:

* Event ``BEGINNING_OF_POSTCOMBAT_MAIN`` — the active player's
  post-combat main phase. Wired in ``simulate.run_step`` (and the
  search-engine adapter equivalent) via
  ``run_beginning_of_postcombat_main_triggers``.
* Predicate ``Controlled(YOU) & IsSelf() & IsTapped()`` — fires
  only on the source's own controller's second main phase, only if
  the source is tapped at that moment, only on the source itself.

These tests cover the new event/predicate/dispatch wiring, the parser
grammar for the ``Survival — `` ability-word prefix and the
``"if this creature is tapped"`` intervening-if gate, and the
end-to-end claim of the Survival cards whose effect bodies the
existing unified effect grammar already supports (Cautious Survivor,
Shrewd Storyteller).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mtg_bot.actions import drain_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards.base import (
    GainLife,
    PutPlusOneCounterOnTargetCreature,
    TriggeredAbility,
    make_creature,
)
from mtg_bot.cards.parser.triggers import (
    _parse_at_beginning_of_phrase,
    _parse_triggered_ability_line,
)
from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.object_predicates import (
    IsTapped,
)
from mtg_bot.effects.predicates import (
    Controlled,
    EVENT_SUBJECTS,
    Event,
    IsSelf,
    Source,
    Subject,
    YOU,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import (
    Step,
    run_beginning_of_postcombat_main_triggers,
)


_PRINTINGS = get_active_source().get_printings()


# ---------- Predicate / Event data-model ----------


@dataclass
class _FakePrinting:
    card_types: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()
    is_token: bool = False


@dataclass
class _FakeObject:
    id: int = 0
    controller_id: int = 0
    tapped: bool = False
    printing: _FakePrinting = field(default_factory=_FakePrinting)


@dataclass
class _FakePlayer:
    id: int = 0


@dataclass
class _FakeState:
    pass


def test_event_postcombat_main_subject_is_player():
    # Mirrors the BEGINNING_OF_UPKEEP / _COMBAT / _END_STEP shape.
    assert EVENT_SUBJECTS[Event.BEGINNING_OF_POSTCOMBAT_MAIN] == ("player",)


def test_is_tapped_true_for_tapped_subject():
    pred = Subject("obj", IsTapped())
    obj = _FakeObject(tapped=True)
    src = _FakeObject(id=42)
    assert pred.matches(_FakeState(), {"obj": obj}, src) is True


def test_is_tapped_false_for_untapped_subject():
    pred = Subject("obj", IsTapped())
    obj = _FakeObject(tapped=False)
    src = _FakeObject(id=42)
    assert pred.matches(_FakeState(), {"obj": obj}, src) is False


def test_is_tapped_explicit_player_subject_is_false():
    # ``Subject("player", IsTapped())`` reads the named slot. Players
    # have no ``tapped`` attribute, so the predicate evaluates false
    # rather than raising.
    pred = Subject("player", IsTapped())
    player = _FakePlayer(id=1)
    src = _FakeObject(id=42)
    assert pred.matches(_FakeState(), {"player": player}, src) is False


def test_source_is_tapped_falls_back_to_source():
    # ``Source(IsTapped())`` checks the SOURCE's tapped state — the
    # surface meaning of "this creature is tapped" on the DSK Survival
    # ability-word trigger. The source is the survivor permanent; the
    # event's player subject is unrelated.
    pred = Source(IsTapped())
    player = _FakePlayer(id=1)
    src_tapped = _FakeObject(id=42, tapped=True)
    src_untapped = _FakeObject(id=42, tapped=False)
    assert pred.matches(_FakeState(), {"player": player}, src_tapped) is True
    assert pred.matches(_FakeState(), {"player": player}, src_untapped) is False


def test_is_self_default_subject_player_is_tautology():
    # ``IsSelf()`` (subject=None) on a turn-structure event whose
    # only subject is a Player evaluates true — the dispatcher already
    # iterates one source at a time, so the source-self check is
    # tautological. Pairs with ``IsTapped()``'s player-subject
    # fallback so the Survival idiom ``IsSelf() & IsTapped()`` reads
    # naturally.
    pred = IsSelf()
    player = _FakePlayer(id=1)
    src = _FakeObject(id=42)
    assert pred.matches(_FakeState(), {"player": player}, src) is True


def test_is_self_with_permanent_subject_uses_identity():
    # When the resolved subject IS a permanent (carries ``printing``),
    # ``IsSelf()`` keeps its standard object-identity behavior. The
    # Player-subject fallback above doesn't shadow the permanent-
    # subject identity check.
    pred = IsSelf()
    other_obj = _FakeObject(id=7)  # a permanent (has ``printing``)
    src = _FakeObject(id=42)
    assert pred.matches(_FakeState(), {"obj": other_obj}, src) is False
    assert pred.matches(_FakeState(), {"obj": src}, src) is True


def test_is_tapped_false_when_subject_missing():
    # ``Subject("missing", IsTapped())`` resolves to no obj — predicate
    # evaluates false rather than KeyError'ing.
    pred = Subject("missing", IsTapped())
    src = _FakeObject(id=42)
    assert pred.matches(_FakeState(), {}, src) is False


def test_is_tapped_named_subject_lookup():
    # ``Subject(slot, IsTapped())`` pulls the named slot. Matches the
    # shape used for compound predicates whose event has multiple
    # subject slots.
    pred = Subject("attacker", IsTapped())
    attacker = _FakeObject(tapped=True)
    blocker = _FakeObject(tapped=False)
    src = _FakeObject(id=42)
    assert pred.matches(
        _FakeState(),
        {"attacker": attacker, "blocker": blocker},
        src,
    ) is True


# ---------- Parser grammar: phrasebook ----------


def test_at_beginning_of_phrasebook_includes_your_second_main_phase():
    assert _parse_at_beginning_of_phrase("your second main phase") == (
        Event.BEGINNING_OF_POSTCOMBAT_MAIN, Controlled(YOU),
    )


# ---------- Parser grammar: line-level Survival ----------


def test_survival_line_parses_with_gain_life_body():
    # Cautious Survivor — the simplest Survival surface form. The
    # ``Survival — `` prefix is stripped, the ``if this creature is
    # tapped, `` middle clause is consumed and replaced by an
    # ``IsSelf() & IsTapped()`` predicate AND-ed onto the trigger's
    # base ``Controlled(YOU)`` arm.
    parsed = _parse_triggered_ability_line(
        "Survival — At the beginning of your second main phase, "
        "if this creature is tapped, you gain 2 life."
    )
    assert parsed == TriggeredAbility(
        event=Event.BEGINNING_OF_POSTCOMBAT_MAIN,
        predicate=Controlled(YOU) & IsSelf() & Source(IsTapped()),
        effect=GainLife(amount=2),
    )


def test_survival_line_parses_with_target_counter_body():
    # Shrewd Storyteller — exercises the parser through a different
    # effect primitive to confirm the prefix/gate handling is
    # body-agnostic.
    parsed = _parse_triggered_ability_line(
        "Survival — At the beginning of your second main phase, "
        "if this creature is tapped, "
        "put a +1/+1 counter on target creature."
    )
    assert parsed == TriggeredAbility(
        event=Event.BEGINNING_OF_POSTCOMBAT_MAIN,
        predicate=Controlled(YOU) & IsSelf() & Source(IsTapped()),
        effect=PutPlusOneCounterOnTargetCreature(amount=1),
    )


def test_survival_missing_gate_clause_rejected():
    # The ``Survival — `` prefix is paired with the verbatim
    # ``if this creature is tapped, `` middle clause in every printing
    # — a Survival-prefixed line whose body starts with something else
    # is rejected outright. Mirrors the Void rider's missing-gate
    # rejection.
    parsed = _parse_triggered_ability_line(
        "Survival — At the beginning of your second main phase, "
        "you gain 2 life."
    )
    assert parsed is None


def test_survival_unparseable_inner_effect_rejected():
    # Recognized Survival prefix + gate but the inner effect tail
    # isn't in the unified effect grammar — reject the whole line so
    # the wrapping card stays unclaimed rather than producing a
    # partial trigger.
    parsed = _parse_triggered_ability_line(
        "Survival — At the beginning of your second main phase, "
        "if this creature is tapped, frobnicate the widget."
    )
    assert parsed is None


def test_survival_prefix_only_strips_for_at_the_beginning_of_body():
    # The Survival-strip in the at-shape dispatch only consumes the
    # prefix when it's followed by ``At the beginning of …`` — a
    # ``Survival — Whenever …`` line wouldn't match the at-shape
    # regex anyway, but the prefix-strip guard mirrors the Void
    # equivalent so a future addition that lands a different
    # ``Survival — When/Whenever`` shape doesn't get its prefix
    # stolen by this dispatch arm.
    parsed = _parse_triggered_ability_line(
        "Survival — Whenever this creature attacks, draw a card."
    )
    # The line shape doesn't match anything claimed today — neither
    # the at-shape (the prefix-strip guard refuses non-``At …``
    # bodies) nor the standard ability-word strip (its lookahead
    # requires ``When``/``Whenever``, which DOES match here, but the
    # ``Survival —`` prefix is consumed by the generic
    # ``_strip_ability_word_prefix`` first, after which the body
    # parses as a normal attack trigger). Sanity-check the result is
    # NOT a Survival trigger.
    assert parsed is None or parsed.event != Event.BEGINNING_OF_POSTCOMBAT_MAIN


# ---------- End-to-end: parser claims expected DSK cards ----------


def test_parser_claims_cautious_survivor():
    # Cautious Survivor is a Duskmourn Survival creature whose effect
    # body (``you gain 2 life``) is in the unified effect grammar
    # today — so the new Survival prefix + gate handling is enough to
    # claim it end-to-end.
    assert "Cautious Survivor" in _PRINTINGS


def test_cautious_survivor_carries_predicate_style_trigger():
    p = _PRINTINGS["Cautious Survivor"]
    assert len(p.triggered_abilities) == 1
    ab = p.triggered_abilities[0]
    assert ab.event == Event.BEGINNING_OF_POSTCOMBAT_MAIN
    assert ab.effect == GainLife(amount=2)
    # Predicate composes Controlled(YOU) & IsSelf() & IsTapped() — the
    # exact AND-tree shape mirrors the parser's left-leaning compose:
    # ``Controlled(YOU) & IsSelf() & IsTapped()`` is
    # ``And(And(Controlled, IsSelf), IsTapped)``.
    assert ab.predicate == Controlled(YOU) & IsSelf() & Source(IsTapped())


def test_parser_claims_shrewd_storyteller():
    assert "Shrewd Storyteller" in _PRINTINGS


# ---------- Engine wiring: dispatch fires only when source is tapped ----------


def _new_state_in_postcombat_main():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.POSTCOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_postcombat_main_trigger_fires_when_tapped():
    state = _new_state_in_postcombat_main()
    survivor = _put(state, _PRINTINGS["Cautious Survivor"])
    # Tap the survivor — the ``IsTapped()`` arm of the predicate is
    # the gate: an untapped survivor's trigger should NOT fire (next
    # test). When tapped at the start of post-combat main the trigger
    # fires and resolves the GainLife(2) effect.
    survivor.tapped = True
    starting_life = state.players[0].life
    run_beginning_of_postcombat_main_triggers(state)
    drain_stack(state)
    assert state.players[0].life == starting_life + 2


def test_postcombat_main_trigger_does_not_fire_when_untapped():
    state = _new_state_in_postcombat_main()
    survivor = _put(state, _PRINTINGS["Cautious Survivor"])
    # Survivor is untapped at start of post-combat main — trigger
    # gate fails, no life gained.
    assert survivor.tapped is False
    starting_life = state.players[0].life
    run_beginning_of_postcombat_main_triggers(state)
    drain_stack(state)
    assert state.players[0].life == starting_life


def test_postcombat_main_trigger_only_fires_for_active_player():
    # Survivor under the non-active player's control — the
    # ``Controlled(YOU)`` arm gates against the active-player
    # subject, so a survivor controlled by the non-active player
    # doesn't fire its trigger on the active player's post-combat
    # main step. Even tapped, the gate fails.
    state = _new_state_in_postcombat_main()
    survivor = _put(state, _PRINTINGS["Cautious Survivor"], owner_id=1)
    survivor.tapped = True
    starting_lives = [p.life for p in state.players]
    run_beginning_of_postcombat_main_triggers(state)
    drain_stack(state)
    assert [p.life for p in state.players] == starting_lives


def test_postcombat_main_trigger_targeted_pump():
    # Shrewd Storyteller — exercises the targeted variant. Targets a
    # creature; needs an agent that picks the first legal target so
    # the trigger doesn't fizzle.
    class _PickFirstAgent(Agent):
        def choose_target(self, state, player_id, legal_targets):
            return legal_targets[0] if legal_targets else None

    state = _new_state_in_postcombat_main()
    state.players[0].agent = _PickFirstAgent()
    storyteller = _put(state, _PRINTINGS["Shrewd Storyteller"])
    storyteller.tapped = True
    bear = _put(state, make_creature("Test Bear", "{1}{G}", 2, 2))
    run_beginning_of_postcombat_main_triggers(state)
    drain_stack(state)
    # The +1/+1 counter goes on whichever creature the picker chose;
    # we just need at least one creature on the battlefield to have a
    # +1/+1 counter (the picker is deterministic against this
    # battlefield, so it will land on the first legal target — which
    # may be Storyteller itself or the bear, depending on iteration
    # order).
    counters_seen = sum(
        o.plus_one_counters for o in state.battlefield
    )
    assert counters_seen == 1
    # Sanity: at least the bear was a viable target.
    assert bear in state.battlefield


# ---------- describe coverage ----------


def test_triggered_ability_describe_covers_postcombat_main():
    # The describe() prefix table maps the new event value to a
    # human-readable phrase. Used by UI / log output — guards against
    # a future regression that drops the entry from the map.
    ab = TriggeredAbility(
        event=Event.BEGINNING_OF_POSTCOMBAT_MAIN,
        predicate=Controlled(YOU),
        effect=GainLife(amount=2),
    )
    description = ab.describe()
    assert "second main phase" in description
