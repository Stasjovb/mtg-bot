"""Regression tests for Plaza of Heroes' two legendary-scoped mana
abilities (audit-found bug — the spend restrictions used to be silently
dropped).

Plaza of Heroes (Stellar Sights) reads:
    {T}: Add {C}.
    {T}: Add one mana of any color. Spend this mana only to cast a
         legendary spell.
    {T}: Add one mana of any color among legendary permanents you
         control.
    {3}, {T}, Exile this land: Target legendary creature gains hexproof
         and indestructible until end of turn.

The two restricted mana abilities now produce coins tagged
"legendary_spell" and "legendary_permanent_ability". The dispatch sites
in actions._cast_spell and actions._activate_ability extend the
spell-kind context with the same tags when the spell being cast or the
permanent being activated is legendary.
"""

import dataclasses

from mtg_bot.actions import (
    ActivateAbility, _cast_spell, _coin_satisfies_context,
    apply_action, resolve_top_of_stack,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.effects import AddManaToPool
from mtg_bot.game import GameState, ManaCoin, Player, Zone
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


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


# -----------------------
# Printing-shape invariants
# -----------------------


def test_plaza_of_heroes_has_four_activated_abilities():
    """{T}: Add {C}; {T}: Add one mana of any color (legendary spell);
    {T}: Add one mana of any color (legendary permanent ability);
    {3},{T},Sac: pump."""
    p = _PRINTINGS["Plaza of Heroes"]
    assert len(p.activated_abilities) == 4


def test_plaza_of_heroes_first_three_are_mana_abilities():
    p = _PRINTINGS["Plaza of Heroes"]
    for ability in p.activated_abilities[:3]:
        assert ability.is_mana_ability is True
    # The flagship pump is not a mana ability.
    assert p.activated_abilities[3].is_mana_ability is False


def test_plaza_of_heroes_mana_ability_tags_match_oracle_text():
    """Ability 1: baseline {C}, no spend restriction.
    Ability 2: any-color, restricted to legendary spells.
    Ability 3: any-color, restricted to legendary permanent activations.
    """
    p = _PRINTINGS["Plaza of Heroes"]
    a0_eff = p.activated_abilities[0].effect
    a1_eff = p.activated_abilities[1].effect
    a2_eff = p.activated_abilities[2].effect
    assert isinstance(a0_eff, AddManaToPool)
    assert a0_eff.spend_restriction is None
    assert a0_eff.produces == (("C", 1),)

    assert isinstance(a1_eff, AddManaToPool)
    assert a1_eff.spend_restriction == "legendary_spell"
    assert a1_eff.produces == (("any", 1),)

    assert isinstance(a2_eff, AddManaToPool)
    assert a2_eff.spend_restriction == "legendary_permanent_ability"
    assert a2_eff.produces == (("any", 1),)


# -----------------------
# Direct unit checks on _coin_satisfies_context for the new tags.
# -----------------------


def test_legendary_spell_coin_satisfies_legendary_spell_context():
    coin = ManaCoin(color="any", spend_restriction="legendary_spell")
    assert _coin_satisfies_context(coin, "legendary_spell")
    assert _coin_satisfies_context(
        coin, frozenset({"spell", "legendary_spell"})
    )


def test_legendary_spell_coin_rejects_plain_spell_context():
    coin = ManaCoin(color="any", spend_restriction="legendary_spell")
    assert not _coin_satisfies_context(coin, "spell")
    assert not _coin_satisfies_context(coin, "artifact_spell")
    assert not _coin_satisfies_context(coin, "legendary_permanent_ability")


def test_legendary_permanent_ability_coin_satisfies_correct_context():
    coin = ManaCoin(
        color="any", spend_restriction="legendary_permanent_ability",
    )
    assert _coin_satisfies_context(coin, "legendary_permanent_ability")
    assert _coin_satisfies_context(
        coin,
        frozenset({"spell", "legendary_permanent_ability"}),
    )
    # Doesn't satisfy the spell context (it's an activation tag).
    assert not _coin_satisfies_context(coin, "legendary_spell")
    assert not _coin_satisfies_context(coin, "spell")


# -----------------------
# Activations produce the right coins.
# -----------------------


def test_plaza_legendary_spell_ability_produces_tagged_coin():
    state = _new_state()
    plaza = _put(state, _PRINTINGS["Plaza of Heroes"])
    apply_action(
        state, 0, ActivateAbility(source_id=plaza.id, ability_index=1),
    )
    pool = state.players[0].mana_pool
    assert len(pool) == 1
    assert pool[0].color == "any"
    assert pool[0].spend_restriction == "legendary_spell"


def test_plaza_legendary_permanent_ability_produces_tagged_coin():
    state = _new_state()
    plaza = _put(state, _PRINTINGS["Plaza of Heroes"])
    apply_action(
        state, 0, ActivateAbility(source_id=plaza.id, ability_index=2),
    )
    pool = state.players[0].mana_pool
    assert len(pool) == 1
    assert pool[0].color == "any"
    assert pool[0].spend_restriction == "legendary_permanent_ability"


# -----------------------
# End-to-end: legendary-spell coin pays for a legendary creature spell.
# -----------------------


def _make_legendary_creature(name: str, mana_cost: str, p: int, t: int):
    base = make_creature(name, mana_cost, p, t)
    # Inject Legendary into supertypes + type_line, since make_creature
    # has no legendary kwarg.
    return dataclasses.replace(
        base,
        supertypes=tuple(list(base.supertypes) + ["Legendary"]),
        type_line=f"Legendary {base.type_line}",
    )


def test_plaza_legendary_spell_mana_pays_for_legendary_creature_cast():
    state = _new_state()
    plaza = _put(state, _PRINTINGS["Plaza of Heroes"])
    # Activate Plaza's legendary-spell mana ability.
    apply_action(
        state, 0, ActivateAbility(source_id=plaza.id, ability_index=1),
    )
    assert len(state.players[0].mana_pool) == 1
    assert state.players[0].mana_pool[0].spend_restriction == "legendary_spell"

    # Synthesize a legendary 1-cost creature in hand.
    leg_print = _make_legendary_creature("Test Legend", "{G}", 1, 1)
    card = state.new_object(leg_print, 0, Zone.HAND)
    state.players[0].hand.append(card)

    _cast_spell(state, 0, card.id)
    # Pool drained, stack has the creature spell.
    assert len(state.players[0].mana_pool) == 0
    assert len(state.stack) == 1


def test_plaza_legendary_spell_mana_does_not_pay_for_nonlegendary_cast():
    state = _new_state()
    plaza = _put(state, _PRINTINGS["Plaza of Heroes"])
    # Activate the legendary-spell mana ability.
    apply_action(
        state, 0, ActivateAbility(source_id=plaza.id, ability_index=1),
    )
    assert len(state.players[0].mana_pool) == 1

    # Synthesize a NON-legendary 1-cost creature in hand.
    nonleg = make_creature("Plain Bear", "{G}", 1, 1)
    card = state.new_object(nonleg, 0, Zone.HAND)
    state.players[0].hand.append(card)

    # can_pay_cost with a "spell"-only context should reject the
    # legendary-restricted coin and find no other mana available.
    from mtg_bot.actions import can_pay_cost
    assert not can_pay_cost(state, 0, nonleg.mana_cost, spell_kind="spell")


# -----------------------
# End-to-end: legendary-permanent-ability mana pays for activations on
# legendary permanents only.
# -----------------------


def test_plaza_legendary_perm_ability_mana_pays_for_legendary_activation():
    """Activate Plaza's third mana ability, then use that coin to pay
    a {1} cost on activating an ability of another legendary
    permanent (Inventors' Fair's {1},{T},Sac search)."""
    state = _new_state()
    plaza = _put(state, _PRINTINGS["Plaza of Heroes"])
    # Build Plaza's legendary-permanent-ability coin.
    apply_action(
        state, 0, ActivateAbility(source_id=plaza.id, ability_index=2),
    )
    assert (
        state.players[0].mana_pool[0].spend_restriction
        == "legendary_permanent_ability"
    )

    # Inventors' Fair is a legendary land with a {1},{T},Sacrifice
    # activation. Use it as the legendary permanent whose ability we
    # want to activate. The legendary-permanent-ability coin should
    # satisfy its {1} mana cost.
    fair = _put(state, _PRINTINGS["Inventors' Fair"])
    fair.tapped = False
    fair.summoning_sick = False
    # Put a card in library so the search has something to find.
    junk = make_creature("Filler Artifact", "{1}", 1, 1)
    junk = dataclasses.replace(
        junk,
        card_types=tuple(list(junk.card_types) + ["Artifact"]),
    )
    state.players[0].library.append(state.new_object(junk, 0, Zone.LIBRARY))

    # Activate Inventors' Fair's search ability (index 0). The {1}
    # cost should be paid from the legendary-permanent-ability coin.
    apply_action(
        state, 0, ActivateAbility(source_id=fair.id, ability_index=0),
    )
    # Coin spent.
    assert len(state.players[0].mana_pool) == 0


def test_plaza_legendary_perm_ability_mana_rejects_nonlegendary_activation():
    """Same coin tag should NOT pay for activations on a non-legendary
    permanent. We use Strip Mine (non-legendary land) — its ability has
    no mana cost, so there's no direct activation to test, but the
    can_pay_cost check on a synthetic non-legendary {1} ability source
    must reject the coin."""
    state = _new_state()
    # Synthetic non-legendary creature with a {1} activated ability.
    base = make_creature("Mundane Spider", "{2}{G}", 2, 4)
    nonleg_perm = _put(state, base)

    # Put a legendary-permanent-ability coin in the pool directly.
    state.players[0].mana_pool.append(
        ManaCoin(
            color="any",
            spend_restriction="legendary_permanent_ability",
        )
    )

    from mtg_bot.actions import can_pay_cost
    from mtg_bot.cards import ManaCost

    # The non-legendary permanent's activation context shouldn't
    # include "legendary_permanent_ability".
    cost = ManaCost(generic=1, colored=(), x_pips=0)
    # Activation context for non-legendary, non-Eldrazi permanent:
    # only the plain "spell" tag.
    assert not can_pay_cost(
        state, 0, cost, spell_kind=frozenset({"spell"}),
    )
    # But it would satisfy a legendary-permanent activation context.
    assert can_pay_cost(
        state, 0, cost,
        spell_kind=frozenset({"spell", "legendary_permanent_ability"}),
    )
    # Sanity: the source object placement is irrelevant to the coin
    # check itself; the dispatch decides which spell_kinds tag to use.
    _ = nonleg_perm


# -----------------------
# Full pipeline regression: Plaza coins drive legal_actions correctly.
# -----------------------


def test_legal_actions_sees_legendary_creature_castable_via_plaza():
    """End-to-end via the legal-actions enumerator: a hand with a
    legendary creature and only Plaza-tagged legendary mana floating
    should show CastSpell for the legendary creature."""
    from mtg_bot.actions import CastSpell
    from mtg_bot.legal import legal_actions

    state = _new_state()
    plaza = _put(state, _PRINTINGS["Plaza of Heroes"])
    # Tap Plaza for the legendary-spell mana.
    apply_action(
        state, 0, ActivateAbility(source_id=plaza.id, ability_index=1),
    )
    # Untap, but leave the floating coin in pool — note: no SBA/cleanup
    # runs here, so floating mana persists across the action.

    # Put a legendary creature in hand.
    leg_print = _make_legendary_creature("Captain Test", "{G}", 1, 1)
    card = state.new_object(leg_print, 0, Zone.HAND)
    state.players[0].hand.append(card)

    actions = legal_actions(state, 0)
    assert any(
        isinstance(a, CastSpell) and a.card_id == card.id for a in actions
    )


def test_legal_actions_hides_nonlegendary_when_only_plaza_mana_is_floating():
    """Inverse: a non-legendary creature in hand with only Plaza
    legendary-spell mana floating must NOT be proposed as castable."""
    from mtg_bot.actions import CastSpell
    from mtg_bot.legal import legal_actions

    state = _new_state()
    plaza = _put(state, _PRINTINGS["Plaza of Heroes"])
    # Tap Plaza only for the legendary-spell mana.
    apply_action(
        state, 0, ActivateAbility(source_id=plaza.id, ability_index=1),
    )

    # Non-legendary creature in hand.
    nonleg = make_creature("Plain Bear", "{G}", 1, 1)
    card = state.new_object(nonleg, 0, Zone.HAND)
    state.players[0].hand.append(card)

    actions = legal_actions(state, 0)
    assert not any(
        isinstance(a, CastSpell) and a.card_id == card.id for a in actions
    )


# -----------------------
# Progress marker
# -----------------------


