"""Tests for Warping Wail ({1}{C}) — Special Guests modal instant.

Oracle (Scryfall-updated): Choose one —
  • Exile target creature with power or toughness 1 or less.
  • Counter target sorcery spell.
  • Create a 1/1 colorless Eldrazi Scion creature token with
    "Sacrifice this token: Add {C}."
"""

from dataclasses import replace

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES, TOKEN_PRINTINGS
from mtg_bot.effects import (
    ActivationCost,
    CounterTargetSpell,
    CreateToken,
    ExileTargetCreatureWithPowerOrToughnessAtMost,
    ModalChooseOne,
)
from mtg_bot.game import GameState, ManaCoin, Player, StackItem, Zone

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickMode(Agent):
    def __init__(self, idx: int):
        self.idx = idx

    def choose_mode(self, state, player_id, mode_descriptions):
        return self.idx


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_warping_wail_is_wired_up():
    ww = _PRINTINGS["Warping Wail"]
    assert ww.is_instant
    assert ww.mana_cost_str == "{1}{C}"
    # Effect shape: three modes.
    assert isinstance(ww.spell_effect, ModalChooseOne)
    assert len(ww.spell_effect.modes) == 3


def test_mode0_legal_targets_only_includes_small_creatures():
    state = _new_state()
    # 1/1 Human Soldier — legal. Wild Bear (2/2) — not legal. 1/3 Hill
    # Giant-size — toughness 1 or less? Let's use a 3/1 instead for the
    # "toughness 1" branch.
    scion = state.new_object(
        TOKEN_PRINTINGS["Eldrazi Scion"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(scion)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,  # 2/2
    )
    state.battlefield.append(bear)
    # Synthesize a "3/1" by mutating a 2/2's toughness_bonus.
    bear2 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    bear2.temp_toughness_bonus = -1  # 2/2 → 2/1
    state.battlefield.append(bear2)

    effect = ExileTargetCreatureWithPowerOrToughnessAtMost(max_value=1)
    legal = effect.legal_targets(state, 0)
    legal_ids = {t[1] for t in legal}
    assert scion.id in legal_ids, "1/1 Scion is a legal target"
    assert bear2.id in legal_ids, "2/1 bear is legal via toughness 1"
    assert bear.id not in legal_ids, "plain 2/2 is NOT legal"


def test_mode0_exiles_targeted_creature():
    state = _new_state(_PickMode(0))
    scion = state.new_object(
        TOKEN_PRINTINGS["Eldrazi Scion"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(scion)
    modal = _PRINTINGS["Warping Wail"].spell_effect
    modal.resolve(state, 0, (("creature", scion.id),))
    assert scion not in state.battlefield


def test_mode0_fizzles_when_target_no_longer_small():
    """If the target gets pumped between cast and resolve, the exile
    clause is re-checked and fizzles silently."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,  # 2/2
    )
    bear.temp_toughness_bonus = -1  # 2/1 at cast-time
    state.battlefield.append(bear)

    effect = ExileTargetCreatureWithPowerOrToughnessAtMost(max_value=1)
    # Pump it back to 2/2 between cast and resolve.
    bear.temp_toughness_bonus = 0
    effect.resolve(state, 0, (("creature", bear.id),))
    assert bear in state.battlefield
    assert any("fizzle" in line or "no longer" in line for line in state.log)


def test_mode1_counters_target_sorcery():
    """Mode 1 counters a sorcery on the stack; a non-sorcery target is
    not even in the legal set."""
    state = _new_state(_PickMode(1))
    # Put a sorcery on the stack.
    sorcery = _PRINTINGS["Atomic Starburst"] if (
        "Atomic Starburst" in _PRINTINGS
    ) else None
    # Fall back to anything that's a sorcery.
    if sorcery is None:
        sorcery = next(
            p for p in _PRINTINGS.values() if p.is_sorcery
        )
    src = state.new_object(sorcery, 1, Zone.STACK)
    state.stack.append(
        StackItem(source=src, controller_id=1, targets=(), countered=False)
    )
    effect = CounterTargetSpell(filter_types=frozenset({"Sorcery"}))
    legal = effect.legal_targets(state, 0)
    assert ("stack", 0) in legal
    effect.resolve(state, 0, (("stack", 0),))
    assert state.stack[0].countered


def test_mode1_does_not_target_instants():
    """Counter-target-sorcery filters out instants entirely."""
    state = _new_state()
    inst = next(p for p in _PRINTINGS.values() if p.is_instant)
    src = state.new_object(inst, 1, Zone.STACK)
    state.stack.append(
        StackItem(source=src, controller_id=1, targets=(), countered=False)
    )
    effect = CounterTargetSpell(filter_types=frozenset({"Sorcery"}))
    assert effect.legal_targets(state, 0) == []


def test_mode2_creates_eldrazi_scion_token():
    state = _new_state(_PickMode(2))
    modal = _PRINTINGS["Warping Wail"].spell_effect
    modal.resolve(state, 0, ())
    scions = [
        o for o in state.battlefield
        if o.printing.name == "Eldrazi Scion" and o.controller_id == 0
    ]
    assert len(scions) == 1
    scion = scions[0]
    assert scion.printing.is_creature
    assert "Eldrazi" in scion.printing.subtypes
    assert "Scion" in scion.printing.subtypes
    assert scion.printing.power == 1 and scion.printing.toughness == 1


def test_scion_token_sac_for_colorless_mana_ability():
    """The Eldrazi Scion token has 'Sacrifice this token: Add {C}.' as a
    mana ability. Activation sacs the scion and mints one {C} coin."""
    state = _new_state()
    scion = state.new_object(
        TOKEN_PRINTINGS["Eldrazi Scion"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(scion)
    abilities = scion.printing.activated_abilities
    assert len(abilities) == 1
    ability = abilities[0]
    assert ability.is_mana_ability
    assert ability.cost == ActivationCost(sacrifice_self=True)

    p = state.player_by_id(0)
    before = len(p.mana_pool)
    # Resolve the mana ability directly (bypasses the stack just like
    # other mana abilities).
    ability.effect.resolve(state, 0, ())
    assert len(p.mana_pool) == before + 1
    assert any(
        isinstance(c, ManaCoin) and c.color == "C" for c in p.mana_pool
    )


def test_token_creation_mode_is_untargeted_in_modal_unit():
    """Mode 2 doesn't show up when computing mixed-modal targets:
    unioned legal targets should be drawn only from modes 0 and 1."""
    state = _new_state()
    scion = state.new_object(
        TOKEN_PRINTINGS["Eldrazi Scion"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(scion)
    modal = _PRINTINGS["Warping Wail"].spell_effect
    legal = modal.legal_targets(state, 0)
    # Scion id is eligible (mode 0). Stack is empty so mode 1 has none.
    assert any(t == ("creature", scion.id) for t in legal)
    # Since at least one mode is untargeted, requires_target is False.
    assert modal.requires_target() is False
    assert modal.target_count_range() == (0, 1)


def test_mode0_defensive_paths_are_safe():
    """Empty targets / wrong target kind / creature already gone all
    return silently without raising."""
    state = _new_state()
    # Include a land so legal_targets skips past the "not a creature"
    # branch at least once.
    from mtg_bot.cards import BASIC_LANDS
    land = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)

    effect = ExileTargetCreatureWithPowerOrToughnessAtMost(max_value=1)
    # Empty: legal_targets skips the land; resolve returns cleanly.
    assert effect.legal_targets(state, 0) == []
    effect.resolve(state, 0, ())  # empty targets branch
    effect.resolve(state, 0, (("player", 0),))  # wrong kind branch
    # Creature that left the battlefield between cast and resolve.
    effect.resolve(state, 0, (("creature", 99999),))
    assert land in state.battlefield  # land unaffected


def test_modal_describe_lists_all_three_modes():
    modal = _PRINTINGS["Warping Wail"].spell_effect
    desc = modal.describe()
    assert "power or toughness 1 or less" in desc
    assert "sorcery" in desc.lower()
    assert "Eldrazi Scion" in desc
