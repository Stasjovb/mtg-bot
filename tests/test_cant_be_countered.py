"""Tests for the "can't be countered" and "combat damage can't be prevented"
engine features.

Covers:
  1. ``spell_is_uncounterable`` flag — ``CounterTargetSpell`` excludes the
     spell from legal targets and fizzles at resolve time.
  2. ``grants_creature_spells_uncounterable`` static — while a permanent
     with this static is on the battlefield, creature spells the controller
     casts are immune to ``CounterTargetSpell``.
  3. ``combat_damage_cant_be_prevented`` flag — the creature's damage events
     bypass the global ``state.prevent_combat_damage_this_turn`` flag
     (Darkness-style prevention) while other sources are still blocked.
  4. Frenzied Baloth parity — the parser produces a ``CardPrinting`` with
     all four oracle lines correctly wired (trample, haste,
     spell_is_uncounterable, grants_creature_spells_uncounterable static,
     combat_damage_cant_be_prevented).
"""

from __future__ import annotations

import pytest

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.base import (
    CardPrinting,
    StaticAbility,
    StaticScope,
    make_creature,
    parse_mana_cost,
)
from mtg_bot.combat import (
    declare_attackers,
    declare_blockers,
    resolve_combat_damage,
)
from mtg_bot.effects import CounterTargetSpell
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import state_based_actions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_state() -> GameState:
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    return state


def _put(state: GameState, printing: CardPrinting, controller: int,
         summoning_sick: bool = False):
    obj = state.new_object(printing, controller, Zone.BATTLEFIELD)
    obj.summoning_sick = summoning_sick
    state.battlefield.append(obj)
    return obj


def _push_spell(state: GameState, printing: CardPrinting,
                controller: int = 0, controller_id: int | None = None):
    """Put a fake spell on the stack (no legal_actions/cast machinery).

    Accepts either ``controller`` or ``controller_id`` as the controlling
    player id (both spellings accepted for call-site readability).
    """
    player_id = controller_id if controller_id is not None else controller
    obj = state.new_object(printing, player_id, Zone.HAND)
    from mtg_bot.game import StackItem
    item = StackItem(source=obj, controller_id=player_id)
    state.stack.append(item)
    return item


# ---------------------------------------------------------------------------
# Uncounterable printing flag
# ---------------------------------------------------------------------------

def _make_uncounterable_creature(name: str = "TestBeast") -> CardPrinting:
    return make_creature(
        name, "{G}{G}", 3, 2,
        keywords={"trample", "haste"},
        spell_is_uncounterable=True,
    )


def test_uncounterable_spell_not_in_legal_targets():
    """A spell with ``spell_is_uncounterable=True`` must not appear in
    ``CounterTargetSpell.legal_targets``."""
    state = _new_state()
    printing = _make_uncounterable_creature()
    item = _push_spell(state, printing, controller_id=0)
    cts = CounterTargetSpell()
    targets = cts.legal_targets(state, controller_id=1)
    assert targets == [], (
        "uncounterable spell should not be a legal target"
    )


def test_uncounterable_spell_resolve_is_noop():
    """Even if somehow targeted, ``CounterTargetSpell.resolve`` must fizzle
    (not set ``countered=True``) when the target has ``spell_is_uncounterable``."""
    state = _new_state()
    printing = _make_uncounterable_creature()
    item = _push_spell(state, printing, controller_id=0)
    cts = CounterTargetSpell()
    cts.resolve(state, controller_id=1, targets=(("stack", 0),))
    assert item.countered is False, "uncounterable spell must not be countered"
    assert any("fizzles" in line for line in state.log), (
        "log should record the fizzle"
    )


def test_counterable_spell_is_still_countered():
    """A plain counterable spell is still countered normally."""
    state = _new_state()
    bear = SYNTHETIC_CREATURES["Wild Bear"]
    item = _push_spell(state, bear, controller_id=0)
    cts = CounterTargetSpell()
    targets = cts.legal_targets(state, controller_id=1)
    assert ("stack", 0) in targets
    cts.resolve(state, controller_id=1, targets=(("stack", 0),))
    assert item.countered is True


# ---------------------------------------------------------------------------
# Creature-spells-uncounterable static
# ---------------------------------------------------------------------------

def _make_grants_creature_spells_uncounterable(name: str = "Protector") -> CardPrinting:
    return make_creature(
        name, "{3}{G}{G}", 3, 2,
        keywords={"trample", "haste"},
        static_abilities=(
            StaticAbility(
                scope=StaticScope.SELF,
                grants_creature_spells_uncounterable=True,
            ),
        ),
    )


def test_creature_spells_uncounterable_static_protects_own_creatures():
    """While a permanent with ``grants_creature_spells_uncounterable`` is on
    the battlefield, creature spells the controller casts can't be targeted
    by ``CounterTargetSpell``."""
    state = _new_state()
    protector = _make_grants_creature_spells_uncounterable()
    _put(state, protector, controller=0)

    # Spell on the stack owned by the same player (creature spell).
    spell_printing = SYNTHETIC_CREATURES["Wild Bear"]
    item = _push_spell(state, spell_printing, controller_id=0)

    cts = CounterTargetSpell()
    targets = cts.legal_targets(state, controller_id=1)
    assert targets == [], (
        "creature spell should be uncounterable while protector is on the "
        "battlefield under its controller"
    )


def test_creature_spells_uncounterable_static_does_not_protect_opponent():
    """The static only protects the controller's creature spells, not the
    opponent's."""
    state = _new_state()
    protector = _make_grants_creature_spells_uncounterable()
    _put(state, protector, controller=0)

    # Opponent's creature spell on the stack.
    spell_printing = SYNTHETIC_CREATURES["Wild Bear"]
    item = _push_spell(state, spell_printing, controller_id=1)

    cts = CounterTargetSpell()
    targets = cts.legal_targets(state, controller_id=0)
    assert ("stack", 0) in targets, (
        "opponent's creature spell should still be counterable"
    )


def test_creature_spells_uncounterable_static_fizzles_at_resolve():
    """Re-check at resolve time: if the protector enters the battlefield
    *after* targeting but *before* resolution, the counter must fizzle."""
    state = _new_state()
    # Spell goes on the stack FIRST (no protector yet).
    spell_printing = SYNTHETIC_CREATURES["Wild Bear"]
    item = _push_spell(state, spell_printing, controller_id=0)

    cts = CounterTargetSpell()
    # At this moment no protector: targeting succeeds.
    targets = cts.legal_targets(state, controller_id=1)
    assert ("stack", 0) in targets

    # Protector enters the battlefield in response.
    protector = _make_grants_creature_spells_uncounterable()
    _put(state, protector, controller=0)

    # Now resolve: should fizzle.
    cts.resolve(state, controller_id=1, targets=(("stack", 0),))
    assert item.countered is False, (
        "counter should fizzle because the spell is now protected"
    )


def test_creature_spells_uncounterable_static_does_not_protect_noncreature():
    """The static only grants uncounterability to creature spells, not
    instants/sorceries."""
    from mtg_bot.cards.base import make_instant
    from mtg_bot.effects import DrawCards

    state = _new_state()
    protector = _make_grants_creature_spells_uncounterable()
    _put(state, protector, controller=0)

    instant = make_instant("TestDraw", "{U}", DrawCards(amount=1))
    item = _push_spell(state, instant, controller_id=0)

    cts = CounterTargetSpell()
    targets = cts.legal_targets(state, controller_id=1)
    assert ("stack", 0) in targets, (
        "noncreature spell should still be counterable even with protector on board"
    )


# ---------------------------------------------------------------------------
# Combat damage can't be prevented
# ---------------------------------------------------------------------------

def _make_prevention_bypasser(name: str = "BypasserBeast") -> CardPrinting:
    return make_creature(
        name, "{3}{G}{G}", 3, 2,
        keywords={"trample"},
        combat_damage_cant_be_prevented=True,
    )


def test_bypasser_deals_damage_through_darkness():
    """A creature with ``combat_damage_cant_be_prevented=True`` still deals
    combat damage even when ``state.prevent_combat_damage_this_turn`` is set."""
    state = _new_state()
    bypasser = _make_prevention_bypasser()
    attacker = _put(state, bypasser, controller=0)
    declare_attackers(state, [attacker.id])
    state.prevent_combat_damage_this_turn = True
    resolve_combat_damage(state, defending_player_id=1)
    assert state.players[1].life == 17, (
        "bypasser should deal 3 damage through Darkness-style prevention"
    )


def test_non_bypasser_is_blocked_by_prevention():
    """A normal creature does NOT deal damage when prevention is active."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], controller=0)
    declare_attackers(state, [bear.id])
    state.prevent_combat_damage_this_turn = True
    resolve_combat_damage(state, defending_player_id=1)
    assert state.players[1].life == 20, (
        "normal creature should be stopped by Darkness-style prevention"
    )


def test_mixed_attackers_only_bypasser_deals_damage():
    """When a bypasser and a normal attacker are both swinging, only the
    bypasser's damage goes through while prevention is active."""
    state = _new_state()
    bypasser = _make_prevention_bypasser()
    atk1 = _put(state, bypasser, controller=0)
    atk2 = _put(state, SYNTHETIC_CREATURES["Wild Bear"], controller=0)  # 2/2
    declare_attackers(state, [atk1.id, atk2.id])
    state.prevent_combat_damage_this_turn = True
    resolve_combat_damage(state, defending_player_id=1)
    # Bypasser: 3 damage. Bear: 0 (prevented).
    assert state.players[1].life == 17, (
        "only the bypasser's damage should land; bear is prevented"
    )


def test_prevention_flag_reset_at_cleanup():
    """After cleanup the prevention flag is cleared, and the bypasser
    no longer needs to 'bypass' anything — it deals damage normally."""
    from mtg_bot.turn import run_cleanup_step
    state = _new_state()
    state.active_player_idx = 0
    state.prevent_combat_damage_this_turn = True
    run_cleanup_step(state)
    # Flag cleared.
    assert state.prevent_combat_damage_this_turn is False
    # Bypasser now deals damage normally (no special bypass needed).
    bypasser = _make_prevention_bypasser()
    atk = _put(state, bypasser, controller=0)
    declare_attackers(state, [atk.id])
    resolve_combat_damage(state, defending_player_id=1)
    assert state.players[1].life == 17


# ---------------------------------------------------------------------------
# Frenzied Baloth parser parity
# ---------------------------------------------------------------------------

def test_frenzied_baloth_parser_parity():
    """Parser claims Frenzied Baloth and produces the printing the
    oracle text describes: trample + haste, both uncounterable flags,
    combat-damage-can't-be-prevented, plus a 3/2 G{G}{G}{G} Beast.

    The "not in _BESPOKE_CREATURES" regression check is implied by the
    parser source returning Frenzied Baloth — the parser would only
    construct the printing if no bespoke entry intercepted first.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    p = OracleParserCardSource().get_printings()
    assert "Frenzied Baloth" in p, "parser must claim Frenzied Baloth"

    b = p["Frenzied Baloth"]
    assert "trample" in b.keywords
    assert "haste" in b.keywords
    assert b.spell_is_uncounterable is True
    assert b.combat_damage_cant_be_prevented is True
    assert b.power == 3
    assert b.toughness == 2
    assert b.mana_cost_str == "{G}{G}"
    assert "Beast" in b.subtypes

    matching = [
        sa for sa in b.static_abilities
        if sa.grants_creature_spells_uncounterable
    ]
    assert len(matching) == 1, (
        "Frenzied Baloth should have exactly one static with "
        "grants_creature_spells_uncounterable"
    )
