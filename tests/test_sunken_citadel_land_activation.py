"""Sunken Citadel's second mana ability: ``{T}: Add two mana of the
chosen color. Spend this mana only to activate abilities of land
sources.``

Audit-found bug: prior to this fix, only the first mana ability was
wired — the comment in stellar_sights.py admitted "the second 'add
two mana, spend only for land abilities' ability is dropped — its
spend restriction would need new cost-payment plumbing tagged for
land-activations." This file exercises the new ``"land_activation"``
spend-restriction tag end-to-end.

Also exercises a drive-by regression fix for the existing
``"artifact_activation"`` tag: ``_coin_satisfies_context`` was
checking the legacy string ``spell_kind == "artifact_activation"``
rather than tag-set membership, which silently broke Steelswarm
Operator's second mana ability after Plaza of Heroes converted
``_activate_ability`` to always pass a frozenset of tags.
"""

from mtg_bot.actions import (
    ActivateAbility, _coin_satisfies_context, apply_action,
    can_pay_cost,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import (
    BASIC_LANDS, EOE_CREATURES, STELLAR_SIGHTS_LANDS, parse_mana_cost,
)
from mtg_bot.game import GameState, ManaCoin, Player, Zone
from mtg_bot.turn import Step


class _Agent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_Agent()))
    state.players.append(Player(id=1, agent=_Agent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# Printing shape
# -----------------------


def test_sunken_citadel_now_has_two_mana_abilities():
    p = STELLAR_SIGHTS_LANDS["Sunken Citadel"]
    assert len(p.activated_abilities) == 2
    # Ability 0: tap for one any-color (unrestricted).
    a0 = p.activated_abilities[0]
    assert a0.is_mana_ability is True
    assert a0.effect.spend_restriction is None
    # Ability 1: tap for two any-color, restricted to land activations.
    a1 = p.activated_abilities[1]
    assert a1.is_mana_ability is True
    assert a1.effect.spend_restriction == "land_activation"
    assert a1.effect.produces == (("any", 2),)


# -----------------------
# Second ability mints restricted coins
# -----------------------


def test_second_ability_mints_two_land_activation_coins():
    state = _new_state()
    citadel = _put(state, STELLAR_SIGHTS_LANDS["Sunken Citadel"])
    # Bypass enters-tapped for the test fixture.
    citadel.tapped = False
    apply_action(
        state, 0, ActivateAbility(source_id=citadel.id, ability_index=1),
    )
    pool = state.players[0].mana_pool
    assert len(pool) == 2
    assert all(c.color == "any" for c in pool)
    assert all(
        c.spend_restriction == "land_activation" for c in pool
    )
    assert citadel.tapped is True


# -----------------------
# Coin spend rules — _coin_satisfies_context
# -----------------------


def test_land_activation_coin_satisfies_land_activation_context():
    coin = ManaCoin(color="U", spend_restriction="land_activation")
    assert _coin_satisfies_context(
        coin, frozenset({"spell", "land_activation"})
    )


def test_land_activation_coin_rejects_default_spell_context():
    coin = ManaCoin(color="U", spend_restriction="land_activation")
    assert not _coin_satisfies_context(coin, "spell")
    assert not _coin_satisfies_context(coin, frozenset({"spell"}))


def test_land_activation_coin_rejects_artifact_activation():
    """Strict scoping: a land-activation coin can't pay for an
    artifact ability activation."""
    coin = ManaCoin(color="U", spend_restriction="land_activation")
    assert not _coin_satisfies_context(
        coin, frozenset({"spell", "artifact_activation"})
    )


def test_artifact_activation_coin_rejects_land_activation_context():
    """Reverse scoping: an artifact-activation coin can't pay for a
    land ability activation either."""
    coin = ManaCoin(color="U", spend_restriction="artifact_activation")
    assert not _coin_satisfies_context(
        coin, frozenset({"spell", "land_activation"})
    )


# -----------------------
# can_pay_cost integration
# -----------------------


def test_can_pay_cost_accepts_land_activation_coins_for_land_ability():
    state = _new_state()
    state.players[0].mana_pool.append(
        ManaCoin(color="any", spend_restriction="land_activation")
    )
    state.players[0].mana_pool.append(
        ManaCoin(color="any", spend_restriction="land_activation")
    )
    cost = parse_mana_cost("{1}{U}")
    assert can_pay_cost(
        state, 0, cost, spell_kind=frozenset({"spell", "land_activation"})
    )
    # Same coins can't pay for a normal spell.
    assert not can_pay_cost(state, 0, cost, spell_kind="spell")


# -----------------------
# Regression: artifact_activation tag-set bug introduced by Plaza
# -----------------------


def test_artifact_activation_coin_satisfies_tag_set_context():
    """Pre-fix bug: ``_coin_satisfies_context`` only matched the
    ``"artifact_activation"`` spend restriction when ``spell_kind``
    was the literal string. Plaza of Heroes converted activations to
    always pass a frozenset of tags, silently breaking Steelswarm
    Operator's second mana ability for actual gameplay."""
    coin = ManaCoin(color="U", spend_restriction="artifact_activation")
    # The tag-set form (post-Plaza activation path) must accept it.
    assert _coin_satisfies_context(
        coin, frozenset({"spell", "artifact_activation"})
    )
    # Legacy string form keeps working.
    assert _coin_satisfies_context(coin, "artifact_activation")


def test_steelswarm_artifact_activation_coin_pays_for_artifact_ability():
    """End-to-end: a Steelswarm-tagged coin in pool satisfies
    ``can_pay_cost`` when the activation context tags include
    ``"artifact_activation"`` (the frozenset shape produced by
    ``_activate_ability`` and ``legal_actions`` post-Plaza)."""
    state = _new_state()
    # Drop a colorless artifact source on the battlefield to confirm
    # the printing-side conditions used by legal/actions still apply.
    op = EOE_CREATURES["Steelswarm Operator"]
    assert op.is_artifact is True
    state.players[0].mana_pool.append(
        ManaCoin(color="U", spend_restriction="artifact_activation")
    )
    cost = parse_mana_cost("{U}")
    assert can_pay_cost(
        state, 0, cost,
        spell_kind=frozenset({"spell", "artifact_activation"}),
    )


# -----------------------
# legal_actions integration: a land-activation coin makes a costed
# land ability legal; the same coin does NOT unlock a non-land
# costed activation
# -----------------------


def test_land_activation_coin_unlocks_costed_land_ability():
    """Bonders' Enclave's `{3}, {T}: Draw a card` is a costed
    activation on a land source. With three land-activation coins in
    pool (and the power-4 prereq satisfied by a token creature),
    legal_actions must list the activation."""
    from mtg_bot.legal import legal_actions
    from mtg_bot.cards.base import make_creature

    state = _new_state()
    for _ in range(3):
        state.players[0].mana_pool.append(
            ManaCoin(color="any", spend_restriction="land_activation")
        )
    enclave = _put(state, STELLAR_SIGHTS_LANDS["Bonders' Enclave"])
    enclave.tapped = False
    # Bonders' Enclave's activation requires a creature with power ≥ 4.
    big = _put(
        state, make_creature("BigBeast", "{4}", power=4, toughness=4),
    )
    big.summoning_sick = False
    actions = legal_actions(state, 0)
    activates = [
        a for a in actions
        if isinstance(a, ActivateAbility) and a.source_id == enclave.id
    ]
    assert activates, "land_activation coins should pay {3} on a land"


def test_land_activation_coin_does_not_unlock_creature_activation():
    """Restriction enforced both ways: the same land_activation coins
    must NOT pay for an activation on a non-land source."""
    from mtg_bot.legal import legal_actions

    state = _new_state()
    for _ in range(3):
        state.players[0].mana_pool.append(
            ManaCoin(color="any", spend_restriction="land_activation")
        )
    # Stellar Sights' Crucias, Titan of the Waves has a costed
    # activated ability, but to keep this test self-contained we
    # use a synthetic creature with a {3}: do-nothing ability via
    # the same printing helpers as the broader test base.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import ActivatedAbility, ActivationCost, DrawCards

    creature = make_creature(
        "ProbeBeast", "{2}", power=2, toughness=2,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{3}"), mana_str="{3}",
                ),
                effect=DrawCards(amount=1),
            ),
        ),
    )
    obj = _put(state, creature)
    obj.summoning_sick = False
    actions = legal_actions(state, 0)
    activates = [
        a for a in actions
        if isinstance(a, ActivateAbility) and a.source_id == obj.id
    ]
    assert activates == [], (
        "land_activation coins must not pay for a creature activation"
    )


# -----------------------
# First ability still works (sanity)
# -----------------------


def test_first_ability_unchanged():
    state = _new_state()
    citadel = _put(state, STELLAR_SIGHTS_LANDS["Sunken Citadel"])
    citadel.tapped = False
    apply_action(
        state, 0, ActivateAbility(source_id=citadel.id, ability_index=0),
    )
    pool = state.players[0].mana_pool
    assert len(pool) == 1
    assert pool[0].color == "any"
    assert pool[0].spend_restriction is None
