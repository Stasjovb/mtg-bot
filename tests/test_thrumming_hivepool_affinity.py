"""Thrumming Hivepool's Affinity-for-Slivers cost reduction.

Audit-found bug: pre-fix the Affinity rider was silently dropped with a
comment claiming the cost reduction was unmodeled. Now wired via a
``CostReduction(amount=1, condition=PerControlled(HasSubtype
("Sliver")))`` on the printing — the structural ``Condition`` grammar
evaluates ``PerControlled``'s ``multiplier`` (the count of Slivers the
caster controls) and the engine's ``_evaluate_cost_reduction``
multiplies the unit amount by it.

Per CR 702.41 (Affinity), the spell on the stack does not count
toward its own discount — it isn't on the battlefield yet.
"""

from mtg_bot.actions import apply_cost_reductions
from mtg_bot.cards import TOKEN_PRINTINGS, CostReduction
from mtg_bot.effects.conditions import PerControlled
from mtg_bot.effects.object_predicates import HasSubtype
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _put_sliver_token(state, owner_id=0):
    return _put(state, TOKEN_PRINTINGS["Sliver"], owner_id=owner_id)


# -----------------------
# Printing shape
# -----------------------


def test_thrumming_hivepool_has_affinity_cost_reduction():
    p = _PRINTINGS["Thrumming Hivepool"]
    assert p.is_artifact is True
    assert p.cost_reductions == (
        CostReduction(
            amount=1,
            condition=PerControlled(HasSubtype("Sliver")),
        ),
    )
    # Other oracle clauses still wired.
    assert len(p.static_abilities) == 1
    assert len(p.triggered_abilities) == 1


# -----------------------
# Cost reduction integration
# -----------------------


def test_no_slivers_means_no_discount():
    state = _new_state()
    p = _PRINTINGS["Thrumming Hivepool"]
    reduced = apply_cost_reductions(p, state, 0, p.mana_cost)
    assert reduced.generic == p.mana_cost.generic  # base {6}


def test_one_sliver_discounts_by_one():
    state = _new_state()
    _put_sliver_token(state)
    p = _PRINTINGS["Thrumming Hivepool"]
    reduced = apply_cost_reductions(p, state, 0, p.mana_cost)
    assert reduced.generic == p.mana_cost.generic - 1  # {5}


def test_three_slivers_discounts_by_three():
    state = _new_state()
    for _ in range(3):
        _put_sliver_token(state)
    p = _PRINTINGS["Thrumming Hivepool"]
    reduced = apply_cost_reductions(p, state, 0, p.mana_cost)
    assert reduced.generic == p.mana_cost.generic - 3  # {3}


def test_max_discount_clamps_at_base_generic():
    """The base cost is {6}; with 10 Slivers in play the discount is
    capped at 6 (you can't go negative)."""
    state = _new_state()
    for _ in range(10):
        _put_sliver_token(state)
    p = _PRINTINGS["Thrumming Hivepool"]
    reduced = apply_cost_reductions(p, state, 0, p.mana_cost)
    assert reduced.generic == 0


def test_opponent_slivers_do_not_count():
    state = _new_state()
    _put_sliver_token(state, owner_id=1)
    _put_sliver_token(state, owner_id=1)
    p = _PRINTINGS["Thrumming Hivepool"]
    reduced = apply_cost_reductions(p, state, 0, p.mana_cost)
    # Opponent's Slivers are irrelevant.
    assert reduced.generic == p.mana_cost.generic


def test_non_sliver_creatures_do_not_count():
    """Sliver subtype check is strict: a Wild Bear in play is still
    just a Bear, no discount."""
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = _new_state()
    _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    p = _PRINTINGS["Thrumming Hivepool"]
    reduced = apply_cost_reductions(p, state, 0, p.mana_cost)
    assert reduced.generic == p.mana_cost.generic


def test_describe_text():
    """Sanity check the printing's affinity reduction is exposed in
    the cost_reductions tuple. (No textual describe() currently, but
    pin the shape.)"""
    p = _PRINTINGS["Thrumming Hivepool"]
    rule = p.cost_reductions[0]
    assert rule.condition == PerControlled(HasSubtype("Sliver"))
    assert rule.amount == 1


# -----------------------
# End-to-end cost gating via legal_actions
# -----------------------


def test_legal_actions_exposes_hivepool_at_reduced_cost():
    """With two Slivers in play and only {4} of mana available, the
    full {6} would be unaffordable but Affinity reduces to {4} →
    legal_actions should expose the cast."""
    from mtg_bot.actions import CastSpell
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.legal import legal_actions

    state = _new_state()
    state.players[0].agent = None  # legal_actions must work without one
    p = state.players[0]
    hivepool = state.new_object(_PRINTINGS["Thrumming Hivepool"], 0, Zone.HAND)
    p.hand.append(hivepool)
    # 4 untapped Mountains → {4} available.
    for _ in range(4):
        _put(state, BASIC_LANDS["Mountain"], owner_id=0)
    # Two Slivers reduce {6} to {4} — affordable.
    _put_sliver_token(state)
    _put_sliver_token(state)
    actions = legal_actions(state, 0)
    casts = [
        a for a in actions
        if isinstance(a, CastSpell) and a.card_id == hivepool.id
    ]
    assert casts, "Affinity-reduced cast must be legal"


def test_legal_actions_blocks_hivepool_without_enough_slivers():
    """Same setup but with zero Slivers — full {6} unaffordable
    against {4}, so cast must NOT be exposed."""
    from mtg_bot.actions import CastSpell
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.legal import legal_actions

    state = _new_state()
    state.players[0].agent = None
    p = state.players[0]
    hivepool = state.new_object(_PRINTINGS["Thrumming Hivepool"], 0, Zone.HAND)
    p.hand.append(hivepool)
    for _ in range(4):
        _put(state, BASIC_LANDS["Mountain"], owner_id=0)
    actions = legal_actions(state, 0)
    casts = [
        a for a in actions
        if isinstance(a, CastSpell) and a.card_id == hivepool.id
    ]
    assert casts == []
