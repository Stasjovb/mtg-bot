"""Tests for Pinnacle Emissary (cast-artifact-spell trigger) and
Blade of the Swarm (ETB +2/+2 self-counters)."""

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    drain_stack,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_CREATURES,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
    TOKEN_PRINTINGS,
)
from mtg_bot.game import GameState, Player, Zone, effective_keywords
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key


def _make_fixed_mode_agent(mode_idx: int = 0) -> RandomAgent:
    """Build a RandomAgent that always picks ``mode_idx`` when
    ``choose_mode`` is called. Mutating ``choose_mode`` on an instance
    is enough — the dataclass init stays untouched."""
    a = RandomAgent()
    a.choose_mode = lambda state, player_id, mode_descriptions: mode_idx  # type: ignore[assignment]
    return a


def _new_state(agent_factory=RandomAgent):
    state = GameState()
    state.players.append(Player(id=0, agent=agent_factory()))
    state.players.append(Player(id=1, agent=agent_factory()))
    return state


# -----------------------
# Drone token is flying 1/1 artifact creature
# -----------------------


def test_drone_token_is_flying_one_one_artifact_creature():
    d = TOKEN_PRINTINGS["Drone"]
    assert d.is_creature
    assert d.is_artifact
    assert d.is_token
    assert d.power == 1
    assert d.toughness == 1
    assert "flying" in d.keywords


def test_drone_token_printing_has_block_restriction_flag():
    """The Drone token's printing carries the block-restriction flag
    so combat.can_block can enforce 'can block only creatures with
    flying' without needing to special-case the token name."""
    d = TOKEN_PRINTINGS["Drone"]
    assert d.can_only_block_creatures_with_flying is True


def test_drone_token_cannot_block_nonflying_attacker():
    """A Drone declared as a blocker against a vanilla ground
    attacker is rejected by can_block."""
    from mtg_bot.combat import can_block

    state = _new_state()
    drone = state.new_object(
        TOKEN_PRINTINGS["Drone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(drone)
    # Wild Bear: vanilla 2/2, no flying.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    assert can_block(state, drone, bear) is False


def test_drone_token_can_block_flying_attacker():
    """A Drone (flying + 'can block only creatures with flying') is
    allowed to block another flying attacker."""
    from mtg_bot.combat import can_block

    state = _new_state()
    drone = state.new_object(
        TOKEN_PRINTINGS["Drone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(drone)
    # Use another Drone as the flying attacker — printed flying keyword.
    flyer = state.new_object(
        TOKEN_PRINTINGS["Drone"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(flyer)
    assert can_block(state, drone, flyer) is True


# -----------------------
# Pinnacle Emissary cast-artifact-spell trigger
# -----------------------


def test_pinnacle_emissary_creates_drone_when_casting_artifact():
    state = _new_state()
    p = state.players[0]
    emissary = state.new_object(
        EOE_CREATURES["Pinnacle Emissary"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(emissary)
    # Add mana for a cheap artifact spell — Memorial Vault is {3}{R}.
    for _ in range(4):
        l = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(l)
    vault = state.new_object(
        EOE_SPELLS["Memorial Vault"], 0, Zone.HAND,
    )
    p.hand.append(vault)
    apply_action(state, 0, CastSpell(vault.id))
    drain_stack(state)
    # Trigger fires as the vault hits the stack → Drone token created.
    drones = [
        o for o in state.battlefield
        if o.printing.name == "Drone" and o.controller_id == 0
    ]
    assert len(drones) == 1
    # Drone is flying.
    assert "flying" in effective_keywords(state, drones[0])


def test_pinnacle_emissary_does_not_trigger_for_non_artifact_spell():
    state = _new_state()
    p = state.players[0]
    emissary = state.new_object(
        EOE_CREATURES["Pinnacle Emissary"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(emissary)
    # Mountain + Forest for Wild Bear {1}{G}.
    for _ in range(2):
        f = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(f)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND,
    )
    p.hand.append(bear)
    apply_action(state, 0, CastSpell(bear.id))
    drones = [
        o for o in state.battlefield if o.printing.name == "Drone"
    ]
    assert drones == []


def test_pinnacle_emissary_printing_has_trigger():
    p = EOE_CREATURES["Pinnacle Emissary"]
    triggers = {_legacy_or_inferred_key(ab) for ab in p.triggered_abilities}
    assert "cast_artifact_spell" in triggers


# -----------------------
# Blade of the Swarm ETB
# -----------------------


def test_blade_of_the_swarm_enters_with_two_plus_one_counters():
    # Pin mode 0 (the +1/+1-counters mode); without an explicit pick,
    # RandomAgent could roll mode 1 (warp-bottom) and fizzle.
    state = _new_state(lambda: _make_fixed_mode_agent(mode_idx=0))
    blade = state.new_object(
        EOE_CREATURES["Blade of the Swarm"], 0, Zone.HAND,
    )
    put_into_battlefield(state, blade, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    assert blade.plus_one_counters == 2


def test_blade_of_the_swarm_has_warp():
    b = EOE_CREATURES["Blade of the Swarm"]
    assert b.warp_cost_str == "{1}{B}"


# -----------------------
# Blade of the Swarm modal ETB — both oracle modes
# (Audit-found bug regression: the warp-bottom mode was previously
# silently dropped.)
# -----------------------


def test_blade_of_the_swarm_etb_is_modal_with_two_modes():
    """Printing-level shape check: the ETB trigger now wraps a
    ModalChooseOne with exactly two modes."""
    from mtg_bot.effects import (
        ModalChooseOne,
        OwnerPutsTargetWarpedExileCardOnBottomOfLibrary,
        PutPlusOneCounterOnSelf,
    )
    blade = EOE_CREATURES["Blade of the Swarm"]
    etb = next(a for a in blade.triggered_abilities if _matches_legacy_key(a, "etb"))
    assert isinstance(etb.effect, ModalChooseOne)
    assert len(etb.effect.modes) == 2
    assert isinstance(etb.effect.modes[0], PutPlusOneCounterOnSelf)
    assert etb.effect.modes[0].amount == 2
    assert isinstance(
        etb.effect.modes[1],
        OwnerPutsTargetWarpedExileCardOnBottomOfLibrary,
    )


def test_blade_mode_1_puts_warped_exile_card_on_bottom_of_library():
    """Mode 1: the targeted warped-exile card moves to the bottom of
    its owner's library and its warp flag clears."""
    state = _new_state(lambda: _make_fixed_mode_agent(mode_idx=1))
    # Seed P1's exile with a warped creature card (e.g. Hullcarver).
    warped = state.new_object(
        EOE_CREATURES["Hullcarver"], 1, Zone.EXILE,
    )
    warped.warped = True
    state.players[1].exile.append(warped)
    # Give P1 a known library bottom for bottom-of-library assertion.
    sentinel = state.new_object(
        EOE_CREATURES["Hullcarver"], 1, Zone.LIBRARY,
    )
    state.players[1].library.append(sentinel)

    blade = state.new_object(
        EOE_CREATURES["Blade of the Swarm"], 0, Zone.HAND,
    )
    put_into_battlefield(state, blade, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)

    assert warped not in state.players[1].exile
    assert state.players[1].library[-1] is warped, (
        "warped card should sit at the bottom of its owner's library"
    )
    assert warped.warped is False, "warp flag clears once it's a library card"
    assert warped.zone == Zone.LIBRARY
    # Mode 0's effect (counters on Blade) was NOT taken.
    assert blade.plus_one_counters == 0


def test_blade_mode_1_fizzles_when_no_warped_exile_card_exists():
    """No warped card anywhere means mode 1 has no legal target, so
    the modal fizzles silently — Blade still entered, no counters,
    no library shuffle, no crash."""
    state = _new_state(lambda: _make_fixed_mode_agent(mode_idx=1))
    blade = state.new_object(
        EOE_CREATURES["Blade of the Swarm"], 0, Zone.HAND,
    )
    put_into_battlefield(state, blade, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)

    assert blade in state.battlefield
    assert blade.plus_one_counters == 0
    # Both players' libraries should be empty (no card was bottom-decked).
    assert state.players[0].library == []
    assert state.players[1].library == []


def test_blade_mode_1_legal_targets_excludes_non_warped_exile_cards():
    """The new effect's legal_targets filter accepts only exile cards
    whose ``warped`` flag is True."""
    from mtg_bot.effects import (
        OwnerPutsTargetWarpedExileCardOnBottomOfLibrary,
    )
    state = _new_state()
    # Plain (non-warped) exile card.
    plain = state.new_object(
        EOE_CREATURES["Hullcarver"], 0, Zone.EXILE,
    )
    state.players[0].exile.append(plain)
    # Warped card on the opponent's side (still legal — "any owner").
    warped_opp = state.new_object(
        EOE_CREATURES["Hullcarver"], 1, Zone.EXILE,
    )
    warped_opp.warped = True
    state.players[1].exile.append(warped_opp)

    legal = OwnerPutsTargetWarpedExileCardOnBottomOfLibrary().legal_targets(
        state, controller_id=0,
    )
    legal_ids = {tid for kind, tid in legal if kind == "exile_card"}
    assert warped_opp.id in legal_ids
    assert plain.id not in legal_ids
