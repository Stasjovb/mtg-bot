"""Tests for Meltstrider's Resolve — Aura ETB "fight" rider.

Oracle text:
    Enchant creature you control
    When this Aura enters, enchanted creature fights up to one target
    creature an opponent controls. (Each deals damage equal to its
    power to the other.)
    Enchanted creature gets +0/+2 and can't be blocked by more than
    one creature.

The +0/+2 + menace pump is exercised in test_rules_cards_misc.py;
this module focuses on the previously-dropped ETB fight rider.
"""

from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects import EnchantedCreatureFightsTargetEffect
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import state_based_actions
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    return state


def _put(state, printing, owner_id=0, attached_to=None):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    if attached_to is not None:
        obj.attached_to = attached_to
    state.battlefield.append(obj)
    return obj


# -----------------------
# Effect-shape sanity
# -----------------------


def test_effect_is_optional_target():
    """'Up to one' → min=0, max=1; requires_target() is False so the
    spell still resolves with no chosen target."""
    e = EnchantedCreatureFightsTargetEffect()
    assert e.requires_target() is False
    assert e.target_count_range() == (0, 1)


def test_effect_describe_mentions_fight():
    d = EnchantedCreatureFightsTargetEffect().describe()
    assert "fight" in d
    assert "opponent" in d


def test_legal_targets_are_opponent_creatures_only():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)  # ally
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    aura = _put(state, _PRINTINGS["Meltstrider's Resolve"], attached_to=bear.id)
    state.resolving_source = aura
    try:
        legal = EnchantedCreatureFightsTargetEffect().legal_targets(state, 0)
    finally:
        state.resolving_source = None
    creature_ids = {tid for kind, tid in legal if kind == "creature"}
    assert enemy.id in creature_ids
    assert bear.id not in creature_ids


# -----------------------
# Resolution paths
# -----------------------


def test_etb_no_opponent_creature_is_noop_but_aura_attaches():
    """With no opponent creatures available, the "up to one" target is
    skipped — fight does nothing, the Aura still resolves and stays
    attached. Verifies the previously-dropped rider doesn't break the
    no-target case."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)  # 2/2
    aura = _put(state, _PRINTINGS["Meltstrider's Resolve"], attached_to=bear.id)
    state.resolving_source = aura
    try:
        EnchantedCreatureFightsTargetEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    # No damage anywhere; aura still attached.
    assert bear.damage == 0
    assert aura.attached_to == bear.id
    state_based_actions(state)
    assert bear in state.battlefield
    assert aura in state.battlefield


def test_etb_both_fighters_survive_take_each_others_power():
    """Bear (2/2) enchanted by Resolve fights an opposing Forest Giant
    (3/3). Each deals damage equal to its power to the other:
      - Bear takes 3 damage on a 4-toughness body (2 + Resolve's +0/+2
        → 2/4); survives.
      - Forest Giant takes 2 damage on a 3-toughness body; survives.
    """
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)  # 2/2
    aura = _put(state, _PRINTINGS["Meltstrider's Resolve"], attached_to=bear.id)
    enemy = _put(state, SYNTHETIC_CREATURES["Forest Giant"], owner_id=1)  # 3/3
    state.resolving_source = aura
    try:
        EnchantedCreatureFightsTargetEffect().resolve(
            state, 0, (("creature", enemy.id),),
        )
    finally:
        state.resolving_source = None
    # Bear dealt 2 to Forest Giant; Forest Giant dealt 3 to Bear.
    assert bear.damage == 3
    assert enemy.damage == 2
    state_based_actions(state)
    # Both alive (Resolve buffs Bear to 2/4).
    assert bear in state.battlefield
    assert enemy in state.battlefield


def test_etb_enchanted_creature_dies_in_fight():
    """Bear (2/2 → 2/4 with Resolve) fights an opposing Great Wurm
    (6/6). Wurm deals 6 → lethal on the bear's 4 toughness; Bear
    deals 2 → wurm survives. State-based actions move both the bear
    and the (now unattached) Aura to the graveyard.
    """
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)  # 2/2
    aura = _put(state, _PRINTINGS["Meltstrider's Resolve"], attached_to=bear.id)
    big = _put(state, SYNTHETIC_CREATURES["Great Wurm"], owner_id=1)  # 6/6
    state.resolving_source = aura
    try:
        EnchantedCreatureFightsTargetEffect().resolve(
            state, 0, (("creature", big.id),),
        )
    finally:
        state.resolving_source = None
    # Bear takes 6 (lethal on 4 toughness with Resolve's +0/+2).
    # Wurm takes 2.
    assert bear.damage == 6
    assert big.damage == 2
    state_based_actions(state)
    # Bear died; the Aura goes with it (aura-on-creature SBA).
    assert bear not in state.battlefield
    assert aura not in state.battlefield
    assert bear in state.players[0].graveyard
    assert aura in state.players[0].graveyard
    # The big creature survives (2 damage on 6 toughness).
    assert big in state.battlefield


def test_etb_resolve_without_resolving_source_is_noop():
    """Defensive: if resolving_source isn't set (shouldn't happen in
    the engine, but covered for safety), resolve early-returns
    without raising."""
    state = _new_state()
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    EnchantedCreatureFightsTargetEffect().resolve(
        state, 0, (("creature", enemy.id),),
    )
    assert enemy.damage == 0


def test_etb_resolve_with_unknown_creature_target_is_noop():
    """If the chosen target ID isn't on the battlefield (e.g. it left
    between targeting and resolution), nothing happens."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    aura = _put(state, _PRINTINGS["Meltstrider's Resolve"], attached_to=bear.id)
    state.resolving_source = aura
    try:
        EnchantedCreatureFightsTargetEffect().resolve(
            state, 0, (("creature", 999_999),),
        )
    finally:
        state.resolving_source = None
    assert bear.damage == 0


def test_etb_resolve_with_non_creature_target_kind_is_noop():
    """Engine-shape guard: a non-'creature' target kind is a no-op."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    aura = _put(state, _PRINTINGS["Meltstrider's Resolve"], attached_to=bear.id)
    state.resolving_source = aura
    try:
        EnchantedCreatureFightsTargetEffect().resolve(
            state, 0, (("player", 1),),
        )
    finally:
        state.resolving_source = None
    assert bear.damage == 0
    assert state.players[1].life == 20


def test_etb_resolve_with_detached_aura_is_noop():
    """If the aura somehow has no attached_to (shouldn't happen post-
    resolve for a normal Aura, but covered defensively), nothing
    happens — no enchanted creature to wield the fight."""
    state = _new_state()
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    aura = _put(state, _PRINTINGS["Meltstrider's Resolve"])
    aura.attached_to = None
    state.resolving_source = aura
    try:
        EnchantedCreatureFightsTargetEffect().resolve(
            state, 0, (("creature", enemy.id),),
        )
    finally:
        state.resolving_source = None
    assert enemy.damage == 0


def test_etb_resolve_with_missing_enchanted_creature_is_noop():
    """If the attached_to ID points to no permanent on the battlefield
    (bear left between attach and fight), the fight resolves to
    nothing rather than crashing."""
    state = _new_state()
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    aura = _put(state, _PRINTINGS["Meltstrider's Resolve"])
    aura.attached_to = 999_999  # nonexistent
    state.resolving_source = aura
    try:
        EnchantedCreatureFightsTargetEffect().resolve(
            state, 0, (("creature", enemy.id),),
        )
    finally:
        state.resolving_source = None
    assert enemy.damage == 0


# -----------------------
# Printing wiring
# -----------------------


def test_printing_has_etb_trigger_and_buffs():
    p = _PRINTINGS["Meltstrider's Resolve"]
    triggers = {_legacy_or_inferred_key(ab) for ab in p.triggered_abilities}
    assert "etb" in triggers
    # The +0/+2 + menace continuous bonus is preserved.
    assert p.equipment_bonuses[0] == 0
    assert p.equipment_bonuses[1] == 2
    assert "menace" in p.equipment_bonuses[2]
    # The ETB effect is the fight rider, not some other Effect.
    etb = next(
        ab for ab in p.triggered_abilities if _matches_legacy_key(ab, "etb")
    )
    assert isinstance(etb.effect, EnchantedCreatureFightsTargetEffect)
