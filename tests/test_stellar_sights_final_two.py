"""Tests for Eldrazi Temple (colorless-Eldrazi spend restriction) and
Swarmyard (regenerate mechanic).

Eldrazi Temple is gameplay-moot in our EoE pool (no Eldrazi cards),
so its tests synthesize targets via dataclasses.replace.

Swarmyard does have an in-pool target — Skystinger (Insect Warrior).
These tests still use synthetic creatures to exercise the machinery
exhaustively (Rat subtype, no-subtype baseline, second-strike, zero-
toughness, cleanup); a Skystinger-specific end-to-end test lives in
``test_swarmyard_regenerate.py``.
"""

import dataclasses

from mtg_bot.actions import (
    ActivateAbility, PlayLand, apply_action, resolve_top_of_stack,
    _cast_spell,
)
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.effects import RegenerateTargetCreature
from mtg_bot.game import (
    GameObject, GameState, ManaCoin, Player, Zone, StackItem,
)
from mtg_bot.turn import Step, run_cleanup_step, state_based_actions

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


# =======================
# Eldrazi Temple
# =======================


def test_eldrazi_temple_has_two_mana_abilities():
    p = _PRINTINGS["Eldrazi Temple"]
    assert len(p.activated_abilities) == 2
    assert all(a.is_mana_ability for a in p.activated_abilities)


def test_eldrazi_temple_ability_one_produces_normal_colorless():
    state = _new_state()
    temple = _put(state, _PRINTINGS["Eldrazi Temple"])
    apply_action(
        state, 0, ActivateAbility(source_id=temple.id, ability_index=0),
    )
    pool = state.players[0].mana_pool
    assert len(pool) == 1
    assert pool[0].color == "C"
    assert pool[0].spend_restriction is None


def test_eldrazi_temple_ability_two_produces_eldrazi_restricted():
    state = _new_state()
    temple = _put(state, _PRINTINGS["Eldrazi Temple"])
    apply_action(
        state, 0, ActivateAbility(source_id=temple.id, ability_index=1),
    )
    pool = state.players[0].mana_pool
    assert len(pool) == 2
    for c in pool:
        assert c.color == "C"
        assert c.spend_restriction == "colorless_eldrazi"


def test_eldrazi_coin_satisfies_colorless_eldrazi_spell_kind():
    """A coin tagged colorless_eldrazi pays for a synthetic Eldrazi
    spell's cost (verified via _coin_satisfies_context directly)."""
    from mtg_bot.actions import _coin_satisfies_context

    coin = ManaCoin(color="C", spend_restriction="colorless_eldrazi")
    assert _coin_satisfies_context(coin, "colorless_eldrazi_spell")
    assert _coin_satisfies_context(coin, "colorless_eldrazi_ability")
    # Same coin doesn't satisfy a plain "spell".
    assert not _coin_satisfies_context(coin, "spell")
    # And doesn't satisfy an "artifact_spell" unrelated context.
    assert not _coin_satisfies_context(coin, "artifact_spell")


def test_eldrazi_temple_mana_pays_for_synthetic_eldrazi_cast():
    """End-to-end: pay for a colorless-Eldrazi spell's cast with the
    restricted mana from Eldrazi Temple's second ability."""
    state = _new_state()
    temple = _put(state, _PRINTINGS["Eldrazi Temple"])
    # Activate the second mana ability to fill the pool with 2
    # Eldrazi-restricted colorless.
    apply_action(
        state, 0, ActivateAbility(source_id=temple.id, ability_index=1),
    )
    assert len(state.players[0].mana_pool) == 2

    # Synthesize a colorless 2-cost Eldrazi in hand.
    base = make_creature("Eldrazi Grunt", "{2}", 2, 2)
    eldrazi_printing = dataclasses.replace(
        base, subtypes=tuple(list(base.subtypes) + ["Eldrazi"]),
    )
    card = state.new_object(eldrazi_printing, 0, Zone.HAND)
    state.players[0].hand.append(card)

    _cast_spell(state, 0, card.id)
    # After cast: pool emptied (both coins consumed), stack has the
    # creature spell.
    assert len(state.players[0].mana_pool) == 0
    assert len(state.stack) == 1


# =======================
# Swarmyard + RegenerateTargetCreature
# =======================


def test_swarmyard_has_regenerate_ability():
    p = _PRINTINGS["Swarmyard"]
    assert len(p.activated_abilities) == 1


def test_regenerate_legal_targets_filter_by_subtype():
    state = _new_state()
    # A Rat — qualifies.
    rat_p = dataclasses.replace(
        make_creature("Test Rat", "{B}", 1, 1),
        subtypes=("Rat",),
    )
    rat = _put(state, rat_p)
    # A plain Bear — does NOT qualify.
    bear = _put(state, make_creature("Plain Bear", "{1}{G}", 2, 2))
    eff = RegenerateTargetCreature(
        allowed_subtypes=frozenset({"Rat", "Spider", "Squirrel", "Insect", "Snake"}),
    )
    legal = eff.legal_targets(state, 0)
    ids = {t[1] for t in legal}
    assert rat.id in ids
    assert bear.id not in ids


def test_regenerate_sets_shield_on_resolve():
    state = _new_state()
    rat = _put(state, dataclasses.replace(
        make_creature("Rat", "{B}", 1, 1), subtypes=("Rat",),
    ))
    eff = RegenerateTargetCreature(
        allowed_subtypes=frozenset({"Rat"}),
    )
    eff.resolve(state, 0, (("creature", rat.id),))
    assert rat.regeneration_shield is True


def test_regenerate_shield_replaces_lethal_destruction():
    """A shielded creature with lethal damage survives state-based
    actions — the shield is consumed, the creature is tapped, damage
    cleared."""
    state = _new_state()
    rat = _put(state, dataclasses.replace(
        make_creature("Rat", "{B}", 1, 1), subtypes=("Rat",),
    ))
    rat.damage = 5  # lethal
    rat.regeneration_shield = True
    rat.attacking = True
    state_based_actions(state)
    # Rat survives.
    assert rat in state.battlefield
    assert rat.damage == 0
    assert rat.tapped is True
    assert rat.attacking is False
    # Shield consumed.
    assert rat.regeneration_shield is False


def test_regenerate_shield_only_covers_one_destruction():
    """After the shield triggers, a second lethal-damage event
    destroys the creature normally."""
    state = _new_state()
    rat = _put(state, dataclasses.replace(
        make_creature("Rat", "{B}", 1, 1), subtypes=("Rat",),
    ))
    rat.damage = 5
    rat.regeneration_shield = True
    state_based_actions(state)
    assert rat in state.battlefield
    # Second lethal hit: no shield left.
    rat.damage = 5
    state_based_actions(state)
    assert rat not in state.battlefield


def test_regenerate_does_not_save_from_zero_toughness():
    """Rule 701.15: regenerate doesn't replace toughness-<=-0
    destruction. The Rat here dies despite the shield."""
    state = _new_state()
    rat = _put(state, dataclasses.replace(
        make_creature("Rat", "{B}", 1, 1), subtypes=("Rat",),
    ))
    # Drop toughness to 0 via a temp debuff.
    rat.temp_toughness_bonus = -1
    rat.regeneration_shield = True
    state_based_actions(state)
    assert rat not in state.battlefield


def test_regenerate_shield_clears_at_cleanup_if_unused():
    state = _new_state()
    rat = _put(state, dataclasses.replace(
        make_creature("Rat", "{B}", 1, 1), subtypes=("Rat",),
    ))
    rat.regeneration_shield = True
    run_cleanup_step(state)
    assert rat.regeneration_shield is False


def test_swarmyard_activation_on_synthetic_rat_regenerates_it():
    """End-to-end: play Swarmyard, summon a synthetic Rat, take
    lethal damage, activate Swarmyard, confirm the Rat survives.
    Oracle text: "{T}: Regenerate target Insect, Rat, Spider, or
    Squirrel." — cost is tap only, no mana needed."""
    state = _new_state()
    swarm = _put(state, _PRINTINGS["Swarmyard"])
    rat = _put(state, dataclasses.replace(
        make_creature("Rat", "{B}", 1, 1), subtypes=("Rat",),
    ))
    rat.damage = 5
    # Activate Swarmyard targeting the Rat.
    apply_action(
        state, 0, ActivateAbility(source_id=swarm.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    # Now SBAs check — shield activates.
    state_based_actions(state)
    assert rat in state.battlefield
    assert rat.damage == 0


def test_regenerate_describe_lists_allowed_subtypes():
    eff = RegenerateTargetCreature(
        allowed_subtypes=frozenset({"Rat", "Spider"}),
    )
    d = eff.describe()
    assert "Rat" in d
    assert "Spider" in d


def test_regenerate_describe_falls_back_when_no_filter():
    assert (
        RegenerateTargetCreature().describe()
        == "regenerate target creature"
    )


def test_regenerate_noop_when_no_targets():
    state = _new_state()
    RegenerateTargetCreature().resolve(state, 0, ())
    # No-op.


def test_regenerate_noop_when_target_id_missing():
    state = _new_state()
    RegenerateTargetCreature().resolve(
        state, 0, (("creature", 9999),),
    )
    # No-op.


def test_move_counter_noop_when_donor_missing():
    """Regression: donor id not in state.battlefield → effect no-ops
    cleanly without raising."""
    from mtg_bot.effects import MovePlusOneCounterBetweenPermanentsYouControl

    state = _new_state()
    recipient = _put(state, make_creature("Recip", "{G}", 1, 1))
    MovePlusOneCounterBetweenPermanentsYouControl().resolve(
        state, 0,
        (("permanent", 9999), ("permanent", recipient.id)),
    )
    assert recipient.plus_one_counters == 0


# =======================
# Progress marker — final two
# =======================




