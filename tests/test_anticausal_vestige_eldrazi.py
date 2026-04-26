"""Anticausal Vestige carries the Eldrazi subtype.

Audit-found bug: the printing in eoe_creatures.py was missing the
Eldrazi subtype that the oracle type line ("Creature — Eldrazi")
specifies. With the subtype absent, the "Eldrazi" in subtypes check
in actions._cast_spell never fired and Eldrazi Temple's
colorless-Eldrazi-restricted mana could not pay for casting
Anticausal Vestige.

Anticausal Vestige is the ONLY Eldrazi card in the EoE pool, so its
fix is what activates Eldrazi Temple's previously-pool-moot machinery.

Anticausal Vestige has no activated abilities with a mana cost
(only a leaves-battlefield triggered ability and Warp), so this
file tests only the cast-side end-to-end. The activation path is
covered for the same machinery in test_stellar_sights_final_two.py.
"""

from mtg_bot.actions import (
    ActivateAbility, _cast_spell, apply_action,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import EOE_CREATURES, STELLAR_SIGHTS_LANDS
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_anticausal_vestige_subtypes_include_eldrazi():
    """The oracle type line is `Creature — Eldrazi`; the printing
    must reflect that."""
    p = EOE_CREATURES["Anticausal Vestige"]
    assert "Eldrazi" in p.subtypes


def test_anticausal_vestige_is_colorless():
    """The colorless-Eldrazi spell_kind gate also requires no colored
    pips in the printed mana cost. {6} has none."""
    p = EOE_CREATURES["Anticausal Vestige"]
    assert p.mana_cost.colored == ()
    assert p.mana_cost.total == 6


def test_eldrazi_temple_mana_pays_for_anticausal_vestige_cast():
    """End-to-end: three Eldrazi Temples each supply {2} of colorless
    Eldrazi mana. Together that's 6 colorless-Eldrazi-restricted coins,
    exactly Anticausal Vestige's cost. Casting it consumes them all,
    proving the colorless_eldrazi_spell tag is set on the cast."""
    state = _new_state()
    temples = [
        _put(state, STELLAR_SIGHTS_LANDS["Eldrazi Temple"])
        for _ in range(3)
    ]
    for temple in temples:
        apply_action(
            state, 0,
            ActivateAbility(source_id=temple.id, ability_index=1),
        )
    pool = state.players[0].mana_pool
    assert len(pool) == 6
    assert all(c.spend_restriction == "colorless_eldrazi" for c in pool)

    # Drop a real Anticausal Vestige into hand and cast it.
    card = state.new_object(
        EOE_CREATURES["Anticausal Vestige"], 0, Zone.HAND,
    )
    state.players[0].hand.append(card)

    _cast_spell(state, 0, card.id)
    # Pool drained; spell on the stack.
    assert len(state.players[0].mana_pool) == 0
    assert len(state.stack) == 1


def test_unrestricted_eldrazi_temple_mana_alone_cannot_pay_plain_spell():
    """Sanity check that the spend restriction really is what's
    enabling the cast above: with the same coins in pool but a
    non-Eldrazi 6-mana spell, the cast must NOT succeed (the coins
    would be filtered out of the usable pool by
    _coin_satisfies_context for spell_kind="spell")."""
    from mtg_bot.actions import can_pay_cost

    state = _new_state()
    temples = [
        _put(state, STELLAR_SIGHTS_LANDS["Eldrazi Temple"])
        for _ in range(3)
    ]
    for temple in temples:
        apply_action(
            state, 0,
            ActivateAbility(source_id=temple.id, ability_index=1),
        )
    # Six colorless-Eldrazi-tagged coins, no other mana sources.
    cost = EOE_CREATURES["Anticausal Vestige"].mana_cost
    # With the colorless_eldrazi_spell context (what _cast_spell
    # picks for an Eldrazi colorless cast), coins are usable.
    assert can_pay_cost(
        state, 0, cost, spell_kind="colorless_eldrazi_spell",
    )
    # With a plain "spell" context, coins are filtered out and the
    # cost cannot be paid (no untapped lands either).
    assert not can_pay_cost(state, 0, cost, spell_kind="spell")
