"""U/B cube creatures that care about artifacts: Improvise and the
self-or-another-artifact ETB trigger (Kappa Cannoneer), Affinity for
artifacts and the graveyard cast permission (Emry, Lurker of the
Loch)."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    _apply_improvise,
    apply_action,
    can_pay_cost,
    drain_stack,
    put_into_battlefield,
)
from mtg_bot.agents import Agent
from mtg_bot.cards.base import ManaCost
from mtg_bot.cards.parser.cube_creatures_ub import (
    parse_ub_creature_line,
    parse_ub_effect,
    parse_ub_trigger_phrase,
)
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic.cube_creatures_ub import (
    MayCastTargetGraveyardCardThisTurn,
    SourceCantBeBlockedThisTurn,
)
from mtg_bot.effects.predicates import Event
from mtg_bot.game import Zone, is_cant_be_blocked
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_cleanup_step
from tests._spells_b_helpers import PRINTINGS, add, add_lands, make_state


# ---------------------------------------------------------------- Improvise


def test_improvise_and_affinity_lines():
    assert parse_ub_creature_line("Improvise", "X").fields == {"has_improvise": True}
    aff = parse_ub_creature_line("Affinity for artifacts", "X").cost_reductions[0]
    assert aff.amount == 1
    assert PRINTINGS["Kappa Cannoneer"].has_improvise
    assert PRINTINGS["Emry, Lurker of the Loch"].cost_reductions


def test_improvise_counts_untapped_artifacts_toward_generic():
    state = make_state()
    add_lands(state, 0, "Island", 2)
    for _ in range(4):
        add(state, 0, "Sol Ring", Zone.BATTLEFIELD)
    kappa = add(state, 0, "Kappa Cannoneer", Zone.HAND)
    cost = ManaCost(generic=5, colored=(("U", 1),))
    assert not can_pay_cost(state, 0, cost)
    assert can_pay_cost(state, 0, cost, improvise=True)
    assert CastSpell(kappa.id) in legal_actions(state, 0)
    apply_action(state, 0, CastSpell(kappa.id))
    drain_stack(state)
    assert any(o.printing.name == "Kappa Cannoneer" for o in state.battlefield)
    rings = [o for o in state.battlefield if o.printing.name == "Sol Ring"]
    assert all(r.tapped for r in rings)


def test_improvise_prefers_non_mana_artifacts_and_skips_without_need():
    state = make_state()
    ring = add(state, 0, "Sol Ring", Zone.BATTLEFIELD)
    rock = add(state, 0, "Aether Spellbomb", Zone.BATTLEFIELD)
    order = Agent.choose_improvise_artifacts(
        state.players[0].agent, state, 0, [ring.id, rock.id], 2,
    )
    assert order == [rock.id, ring.id]
    free = ManaCost(generic=0, colored=(("U", 1),))
    assert _apply_improvise(state, 0, free) == free
    left = _apply_improvise(state, 0, ManaCost(generic=1))
    assert left.generic == 0 and sum(o.tapped for o in (ring, rock)) == 1


# ---------------------------------------------------------------- Kappa trigger


def test_self_or_another_artifact_enters_trigger():
    event, pred = parse_ub_trigger_phrase(
        "this creature or another artifact you control enters"
    )
    assert event is Event.ENTERS
    assert parse_ub_trigger_phrase(
        "this creature or another frobnicator you control enters"
    ) is None
    eff = parse_ub_effect(
        "put a +1/+1 counter on this creature. It can't be blocked this turn"
    )
    assert isinstance(eff, Sequence)
    assert eff.effects[1] == SourceCantBeBlockedThisTurn()
    assert "can't be blocked" in SourceCantBeBlockedThisTurn().describe()


def test_kappa_grows_and_slips_past_blockers():
    state = make_state()
    kappa = state.new_object(PRINTINGS["Kappa Cannoneer"], 0, Zone.HAND)
    put_into_battlefield(state, kappa, 0)
    drain_stack(state)
    assert kappa.plus_one_counters == 1
    assert is_cant_be_blocked(state, kappa)
    ring = state.new_object(PRINTINGS["Sol Ring"], 0, Zone.HAND)
    put_into_battlefield(state, ring, 0)
    drain_stack(state)
    assert kappa.plus_one_counters == 2
    # An opponent's artifact doesn't count.
    other = state.new_object(PRINTINGS["Sol Ring"], 1, Zone.HAND)
    put_into_battlefield(state, other, 1)
    drain_stack(state)
    assert kappa.plus_one_counters == 2
    # Source gone: nothing to make unblockable.
    state.resolving_source = None
    SourceCantBeBlockedThisTurn().resolve(state, 0, ())


# ---------------------------------------------------------------- Emry


def test_emry_lets_an_artifact_be_cast_from_the_graveyard_this_turn():
    eff = parse_ub_effect(
        "choose target artifact card in your graveyard. You may cast that "
        "card this turn"
    )
    assert isinstance(eff, MayCastTargetGraveyardCardThisTurn)
    assert "you may cast it" in eff.describe()
    state = make_state()
    emry = add(state, 0, "Emry, Lurker of the Loch", Zone.BATTLEFIELD)
    ring = add(state, 0, "Sol Ring", Zone.GRAVEYARD)
    add(state, 0, "Island", Zone.GRAVEYARD)
    add_lands(state, 0, "Island", 1)
    assert CastSpell(ring.id) not in legal_actions(state, 0)
    apply_action(state, 0, ActivateAbility(source_id=emry.id, ability_index=0))
    drain_stack(state)
    assert ring.castable_from_graveyard_this_turn
    assert CastSpell(ring.id) in legal_actions(state, 0)
    apply_action(state, 0, CastSpell(ring.id))
    drain_stack(state)
    assert ring in state.battlefield and not ring.castable_from_graveyard_this_turn


def test_emry_permission_ends_at_cleanup_and_needs_the_card():
    state = make_state()
    ring = add(state, 0, "Sol Ring", Zone.GRAVEYARD)
    eff = MayCastTargetGraveyardCardThisTurn(
        card_filter=PRINTINGS["Emry, Lurker of the Loch"]
        .activated_abilities[0].effect.card_filter,
    )
    assert eff.legal_targets(state, 0) == [("graveyard_card", ring.id)]
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("graveyard_card", 999),))
    eff.resolve(state, 0, (("graveyard_card", ring.id),))
    assert ring.castable_from_graveyard_this_turn
    state.step = Step.CLEANUP
    run_cleanup_step(state)
    assert not state.players[0].graveyard[0].castable_from_graveyard_this_turn
