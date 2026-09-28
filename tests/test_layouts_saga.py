"""Cube layouts bucket: Sagas (CR 714) -- Urza's Saga and Fable of the
Mirror-Breaker // Reflection of Kiki-Jiki.

Parse shape (chapter abilities as ``chapter_<N>`` triggers) and engine
behavior: a lore counter on entry and after the draw step, chapter
triggers, the final-chapter sacrifice held while a chapter ability is on
the stack, granted abilities, Fable's return transformed.
"""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    PlayLand,
    apply_action,
    can_pay_cost,
    drain_stack,
    resolve_top_of_stack,
)
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.base import ManaCost
from mtg_bot.cards.parser.saga_builder import _build_saga_printing
from mtg_bot.effects.generic.card_flow import CardFilter
from mtg_bot.effects.generic.layout_effects import (
    CreateTokenCopyOfTargetWithKeywordsSacAtEndStep,
    ExileSourceThenReturnTransformed,
)
from mtg_bot.game import (
    Zone,
    add_counters,
    effective_activated_abilities,
    effective_keywords,
    effective_land_produces,
    effective_power,
)
from mtg_bot.layouts import chapter_ability_on_stack, chapter_number
from mtg_bot.legal import legal_actions
from mtg_bot.turn import (
    run_delayed_end_step_triggers,
    run_draw_step,
    state_based_actions,
)
from tests._spells_b_helpers import ScriptedAgent, add, add_lands, make_state, printing

URZA = "Urza's Saga"
FABLE = "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki"


def _creature(state, pid, name="Stalwart Knight"):
    obj = state.new_object(SYNTHETIC_CREATURES[name], pid, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


# ---------------------------------------------------------------------------
# Parse shape
# ---------------------------------------------------------------------------


def test_urza_saga_shape():
    p = printing(URZA)
    assert p.is_saga and p.chapter_count == 3 and p.is_land and p.is_enchantment
    assert p.mana_only_from_produces and p.produces == frozenset()
    assert [chapter_number(t) for t in p.triggered_abilities] == [1, 2, 3]
    search = p.triggered_abilities[2].effect
    assert search.card_filter == CardFilter(
        any_types=("Artifact",), mana_costs=("{0}", "{1}"),
    )
    assert "mana cost {0} or {1}" in search.card_filter.describe()


def test_fable_shape():
    p = printing(FABLE)
    assert p.is_saga and p.chapter_count == 3 and p.mana_cost_str == "{2}{R}"
    assert p.triggered_abilities[2].effect == ExileSourceThenReturnTransformed(
        under_owners_control=False,
    )
    back = p.transform_back_face
    assert back.name == "Reflection of Kiki-Jiki" and not back.is_saga
    (ab,) = back.activated_abilities
    assert isinstance(ab.effect, CreateTokenCopyOfTargetWithKeywordsSacAtEndStep)
    assert ab.effect.keywords == frozenset({"haste"})


def test_saga_builder_rejects():
    base = {"name": "S", "mana_cost": "{1}", "type_line": "Enchantment — Saga"}
    assert _build_saga_printing(dict(base, type_line="Enchantment")) is None
    assert _build_saga_printing(dict(base, oracle_text="Read ahead")) is None
    assert _build_saga_printing(dict(base, oracle_text="I — Frobnicate.")) is None
    assert _build_saga_printing(dict(base, oracle_text="IX — Draw a card.")) is None
    assert _build_saga_printing(dict(base, oracle_text="(Reminder only.)")) is None
    two = _build_saga_printing(dict(base, oracle_text="I, II — Draw a card."))
    assert [chapter_number(t) for t in two.triggered_abilities] == [1, 2]
    assert two.chapter_count == 2


def test_chapter_number_of_other_abilities_is_zero():
    assert chapter_number(object()) == 0


# ---------------------------------------------------------------------------
# Urza's Saga
# ---------------------------------------------------------------------------


def test_urza_saga_full_cycle():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    saga = add(state, 0, URZA, Zone.HAND)
    add(state, 0, "Island", Zone.LIBRARY)
    add(state, 0, "Island", Zone.LIBRARY)
    pearl = add(state, 0, "Mox Pearl", Zone.LIBRARY)
    add(state, 0, "Sol Ring", Zone.LIBRARY)
    assert PlayLand(saga.id) in legal_actions(state, 0)
    # No mana ability yet: it pays for nothing.
    apply_action(state, 0, PlayLand(saga.id))
    assert saga.lore_counters == 1
    assert chapter_ability_on_stack(state, saga)
    assert effective_land_produces(state, saga) == frozenset()
    drain_stack(state)
    # Chapter I: "{T}: Add {C}." -- now an automatic mana source.
    assert effective_land_produces(state, saga) == frozenset({"C"})
    assert can_pay_cost(state, 0, ManaCost(generic=1))
    # Chapter II after the next draw step.
    state.turn_number = 3
    run_draw_step(state)
    assert saga.lore_counters == 2
    drain_stack(state)
    abilities = effective_activated_abilities(state, saga)
    assert len(abilities) == 2
    add_lands(state, 0, "Island", 2)
    apply_action(state, 0, ActivateAbility(source_id=saga.id, ability_index=1))
    drain_stack(state)
    construct = next(o for o in state.battlefield if o.printing.name == "Construct")
    assert effective_power(state, construct) == 1  # itself
    # Chapter III: search for a {0}/{1} artifact; the Saga isn't
    # sacrificed while the chapter ability is on the stack.
    agent.scripts["library"] = [pearl.id]
    run_draw_step(state)
    assert saga.lore_counters == 3
    state_based_actions(state)
    assert saga in state.battlefield
    drain_stack(state)
    assert pearl in state.battlefield
    assert effective_power(state, construct) == 2
    state_based_actions(state)
    assert saga in state.players[0].graveyard and saga.lore_counters == 3


def test_urza_saga_search_skips_other_costs():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    saga = add(state, 0, URZA, Zone.BATTLEFIELD)
    ballista = add(state, 0, "Walking Ballista", Zone.LIBRARY)
    saga.lore_counters = 2
    add_counters(state, saga, "lore", 1)
    assert chapter_ability_on_stack(state, saga)
    drain_stack(state)
    assert ballista in state.players[0].library


def test_lore_counter_only_on_active_players_sagas():
    state = make_state()
    mine = add(state, 0, URZA, Zone.BATTLEFIELD)
    theirs = add(state, 1, URZA, Zone.BATTLEFIELD)
    mine.lore_counters = theirs.lore_counters = 1
    add(state, 0, "Island", Zone.LIBRARY)
    run_draw_step(state)
    assert mine.lore_counters == 2 and theirs.lore_counters == 1


# ---------------------------------------------------------------------------
# Fable of the Mirror-Breaker
# ---------------------------------------------------------------------------


def test_fable_chapters_and_reflection():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    fable = add(state, 0, FABLE, Zone.HAND)
    add_lands(state, 0, "Mountain", 3)
    apply_action(state, 0, CastSpell(fable.id))
    drain_stack(state)
    assert fable.lore_counters == 1
    goblin = next(o for o in state.battlefield if o.printing.name == "Goblin Shaman")
    assert effective_power(state, goblin) == 2
    # Chapter II: discard up to two, draw that many.
    a = add(state, 0, "Lightning Bolt", Zone.HAND)
    add(state, 0, "Island", Zone.LIBRARY)
    add(state, 0, "Island", Zone.LIBRARY)
    add(state, 0, "Island", Zone.LIBRARY)
    agent.scripts["x"] = [1]
    state.turn_number = 3
    run_draw_step(state)
    drain_stack(state)
    assert a in state.players[0].graveyard
    # Chapter III: exile, return transformed as Reflection of Kiki-Jiki.
    run_draw_step(state)
    state_based_actions(state)
    assert fable in state.battlefield
    drain_stack(state)
    state_based_actions(state)
    assert fable in state.battlefield
    assert fable.printing.name == "Reflection of Kiki-Jiki"
    assert fable.lore_counters == 0 and fable.summoning_sick


def test_reflection_copies_nonlegendary_creature_with_haste():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    fable = add(state, 0, FABLE, Zone.BATTLEFIELD)
    from mtg_bot.layouts import transform_permanent

    transform_permanent(state, fable)
    knight = _creature(state, 0)
    add_lands(state, 0, "Mountain", 1)
    ab = fable.printing.activated_abilities[0]
    state.resolving_source = fable
    legal = ab.effect.legal_targets(state, 0)
    state.resolving_source = None
    assert ("creature", fable.id) not in legal and ("creature", knight.id) in legal
    agent.scripts["target"] = [("creature", knight.id)]
    apply_action(state, 0, ActivateAbility(source_id=fable.id, ability_index=0))
    drain_stack(state)
    token = next(
        o for o in state.battlefield
        if o.printing.is_token and o.printing.name == knight.printing.name
    )
    assert "haste" in effective_keywords(state, token)
    run_delayed_end_step_triggers(state)
    drain_stack(state)
    assert token not in state.battlefield
    assert "haste" in ab.effect.describe()


def test_reflection_copy_fizzles_without_target():
    state = make_state()
    eff = CreateTokenCopyOfTargetWithKeywordsSacAtEndStep()
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("creature", 99),))
    assert not state.battlefield


def test_goblin_shaman_token_attack_makes_treasure():
    from mtg_bot.actions import DeclareAttackers

    state = make_state()
    fable = add(state, 0, FABLE, Zone.HAND)
    add_lands(state, 0, "Mountain", 3)
    apply_action(state, 0, CastSpell(fable.id))
    drain_stack(state)
    goblin = next(o for o in state.battlefield if o.printing.name == "Goblin Shaman")
    goblin.summoning_sick = False
    from mtg_bot.turn import Step

    state.step = Step.DECLARE_ATTACKERS
    apply_action(state, 0, DeclareAttackers(attacker_ids=frozenset({goblin.id})))
    drain_stack(state)
    assert any(o.printing.name == "Treasure" for o in state.battlefield)


def test_chapter_triggers_via_resolve_one_at_a_time():
    state = make_state()
    saga = add(state, 0, URZA, Zone.BATTLEFIELD)
    add_counters(state, saga, "lore", 2)
    assert len(state.stack) == 2
    resolve_top_of_stack(state)
    assert chapter_ability_on_stack(state, saga)
