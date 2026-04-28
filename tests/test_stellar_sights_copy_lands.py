"""Tests for Stellar Sights copy-land batch: Thespian's Stage, Mirrorpool.

Covers the new copy primitives:
- BecomesCopyOfTargetLand (mutates source.printing in place)
- CreateTokenCopyOfTargetCreatureYouControl (token via existing
  CreateToken machinery)
- CopyTargetInstantOrSorceryYouControl (short-circuit re-resolve)
"""

from mtg_bot.actions import ActivateAbility, apply_action, resolve_top_of_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.game import GameState, Player, StackItem, Zone
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


class _PickLastAgent(Agent):
    """Used when the first legal target is the source itself (e.g. a
    copy-land ability where self-targeting would be a no-op)."""

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[-1] if legal_targets else None


def _new_state(agent_cls=_PickFirstAgent):
    state = GameState()
    state.players.append(Player(id=0, agent=agent_cls()))
    state.players.append(Player(id=1, agent=agent_cls()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# Thespian's Stage
# -----------------------


def test_thespians_stage_copies_basic_forest_to_produce_green():
    # PickLast so the agent chooses the Forest (last land added),
    # not the Stage itself (first).
    state = _new_state(agent_cls=_PickLastAgent)
    stage = _put(state, _PRINTINGS["Thespian's Stage"])
    # Pay {2} from two basic lands, plus a Forest as the target.
    for _ in range(2):
        _put(state, BASIC_LANDS["Mountain"])
    forest = _put(state, BASIC_LANDS["Forest"], owner_id=1)
    apply_action(
        state, 0, ActivateAbility(source_id=stage.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    # Stage's printing now reflects Forest's produces.
    assert "G" in stage.printing.produces
    # Its name was replaced (per oracle — copies the printing).
    assert stage.printing.name == "Forest"
    # original_printing snapshot captured the pre-copy identity.
    assert stage.original_printing is not None
    assert stage.original_printing.name == "Thespian's Stage"


def test_thespians_stage_retains_own_activated_ability_after_copy():
    """The 'except it has this ability' clause — Thespian's own
    {2},{T}: become-a-copy ability survives the copy."""
    state = _new_state(agent_cls=_PickLastAgent)
    stage = _put(state, _PRINTINGS["Thespian's Stage"])
    for _ in range(2):
        _put(state, BASIC_LANDS["Mountain"])
    _put(state, BASIC_LANDS["Forest"], owner_id=1)
    apply_action(
        state, 0, ActivateAbility(source_id=stage.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    # Forest has zero activated abilities; after copy, Stage's printing
    # has exactly Thespian's original copy ability.
    assert len(stage.printing.activated_abilities) == 1


def test_thespians_stage_recopy_does_not_accumulate_abilities():
    """A second copy activation should still leave the Stage with the
    target's abilities + its own copy ability — not double-stacked."""
    state = _new_state(agent_cls=_PickLastAgent)
    stage = _put(state, _PRINTINGS["Thespian's Stage"])
    for _ in range(4):
        _put(state, BASIC_LANDS["Mountain"])
    # First target: Ancient Tomb (1 activated ability).
    ancient_tomb = _put(state, _PRINTINGS["Ancient Tomb"])
    apply_action(
        state, 0, ActivateAbility(source_id=stage.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    # Stage now has Ancient Tomb's ability + its own copy ability = 2.
    assert len(stage.printing.activated_abilities) == 2
    # Activate again, target a Forest this time.
    _put(state, BASIC_LANDS["Forest"], owner_id=1)
    # Find the copy ability on the re-copied stage (it's the second,
    # since the target printing's abilities come first).
    copy_ability_idx = len(stage.printing.activated_abilities) - 1
    apply_action(
        state, 0, ActivateAbility(
            source_id=stage.id, ability_index=copy_ability_idx,
        ),
    )
    while state.stack:
        resolve_top_of_stack(state)
    # Now Stage should have Forest's abilities (0) + its own (1) = 1.
    assert len(stage.printing.activated_abilities) == 1


# -----------------------
# Mirrorpool: basic metadata
# -----------------------


def test_mirrorpool_is_legendary_and_enters_tapped():
    p = _PRINTINGS["Mirrorpool"]
    assert "Legendary" in p.supertypes
    assert p.enters_tapped is True
    assert len(p.activated_abilities) == 2
    # Both sac abilities.
    assert all(a.cost.sacrifice_self for a in p.activated_abilities)


# -----------------------
# Mirrorpool mode 2: token-copy a creature
# -----------------------


def test_mirrorpool_token_copy_creature_creates_a_copy_token():
    state = _new_state()
    pool = _put(state, _PRINTINGS["Mirrorpool"])
    # Mana for {4}{C} = 5 generic; we need 5 coins. Colorless mana
    # via activating basic lands is auto-tapped; seed directly.
    from mtg_bot.game import ManaCoin
    state.players[0].mana_pool.extend(
        [ManaCoin(color="C")] * 5
    )
    bear = _put(
        state, make_creature("Test Bear", "{1}{G}", 2, 2), owner_id=0,
    )
    bear.summoning_sick = False
    # Ability 1 (index 1) is the token-copy one ({4}{C}).
    apply_action(
        state, 0, ActivateAbility(source_id=pool.id, ability_index=1),
    )
    while state.stack:
        resolve_top_of_stack(state)
    # Mirrorpool is gone (sacrificed).
    assert pool not in state.battlefield
    # Two copies of Test Bear should now exist — the original plus the
    # freshly-created token.
    bears = [o for o in state.battlefield if o.printing.name == "Test Bear"]
    assert len(bears) == 2
    # The token has the Token supertype on its printing; the original
    # doesn't.
    tokens = [o for o in bears if o.printing.is_token]
    assert len(tokens) == 1


# -----------------------
# Mirrorpool mode 1: copy an instant on the stack
# -----------------------


def test_mirrorpool_copy_spell_reresolves_target_effect():
    """Activate Mirrorpool's copy-spell ability with a Plasma Bolt on
    the stack — the copy should deal 2 damage to an additional target.
    """
    class _TargetOpponentAgent(Agent):
        def choose_target(self, state, player_id, legal_targets):
            for t in legal_targets:
                if t[0] == "player" and t[1] != player_id:
                    return t
                if t[0] == "stack_spell":
                    return t
            return legal_targets[0] if legal_targets else None

    state = _new_state(agent_cls=_TargetOpponentAgent)
    pool = _put(state, _PRINTINGS["Mirrorpool"])
    # Skip Mirrorpool's own mana cost via direct mana pool.
    from mtg_bot.game import ManaCoin
    state.players[0].mana_pool.extend([ManaCoin(color="C")] * 3)
    # Cast a Plasma Bolt at opponent. Short-circuit: put the bolt
    # StackItem directly onto the stack.
    bolt_printing = _PRINTINGS["Plasma Bolt"]
    bolt_obj = state.new_object(bolt_printing, 0, Zone.STACK)
    state.stack.append(
        StackItem(
            source=bolt_obj, controller_id=0, ability=None,
            targets=(("player", 1),),
        )
    )
    # Activate Mirrorpool copy-spell (index 0).
    apply_action(
        state, 0, ActivateAbility(source_id=pool.id, ability_index=0),
    )
    # Resolve the Mirrorpool ability (the copy effect). Don't resolve
    # the bolt itself yet.
    while state.stack and state.stack[-1].ability is not None:
        resolve_top_of_stack(state)
    # The copy has re-resolved, dealing 2 damage to an opponent
    # already. Life should be 20 - 2 = 18.
    assert state.players[1].life == 18
    # The original Plasma Bolt is still on the stack, pending.
    assert len(state.stack) == 1


# -----------------------
# Progress marker
# -----------------------


# -----------------------
# Defensive coverage for the new effects — describe() + noop paths
# -----------------------


def test_copy_effects_describe():
    from mtg_bot.effects import (
        BecomesCopyOfTargetLand,
        CopyTargetInstantOrSorceryYouControl,
        CreateTokenCopyOfTargetCreatureYouControl,
    )

    assert "copy" in BecomesCopyOfTargetLand().describe().lower()
    assert "copy" in CopyTargetInstantOrSorceryYouControl().describe().lower()
    assert (
        "copy"
        in CreateTokenCopyOfTargetCreatureYouControl().describe().lower()
    )


def test_becomes_copy_noop_without_source_or_target():
    from mtg_bot.effects import BecomesCopyOfTargetLand

    state = _new_state()
    # No resolving_source → noop.
    BecomesCopyOfTargetLand().resolve(state, 0, ())
    # resolving_source but empty targets → noop.
    stage = _put(state, _PRINTINGS["Thespian's Stage"])
    state.resolving_source = stage
    try:
        BecomesCopyOfTargetLand().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    # resolving_source but nonexistent target id → noop.
    state.resolving_source = stage
    try:
        BecomesCopyOfTargetLand().resolve(state, 0, (("permanent", 9999),))
    finally:
        state.resolving_source = None
    assert stage.printing.name == "Thespian's Stage"


def test_create_token_copy_noop_without_target():
    from mtg_bot.effects import CreateTokenCopyOfTargetCreatureYouControl

    state = _new_state()
    CreateTokenCopyOfTargetCreatureYouControl().resolve(state, 0, ())
    # Nonexistent target id → noop.
    CreateTokenCopyOfTargetCreatureYouControl().resolve(
        state, 0, (("creature", 9999),),
    )
    assert state.battlefield == []


def test_copy_spell_noop_paths():
    from mtg_bot.effects import CopyTargetInstantOrSorceryYouControl

    state = _new_state()
    # No targets → noop.
    CopyTargetInstantOrSorceryYouControl().resolve(state, 0, ())
    # Wrong kind → noop.
    CopyTargetInstantOrSorceryYouControl().resolve(
        state, 0, (("permanent", 0),),
    )
    # Unknown src_id → noop.
    CopyTargetInstantOrSorceryYouControl().resolve(
        state, 0, (("stack_spell", 9999),),
    )


def test_copy_spell_legal_targets_filters_correctly():
    """Only instants/sorceries controlled by the effect's controller
    appear in legal_targets."""
    from mtg_bot.effects import CopyTargetInstantOrSorceryYouControl

    state = _new_state()
    # Opponent's sorcery — should be filtered out.
    opp_bolt = state.new_object(_PRINTINGS["Plasma Bolt"], 1, Zone.STACK)
    state.stack.append(
        StackItem(
            source=opp_bolt, controller_id=1, ability=None, targets=(),
        ),
    )
    # Our creature spell (not an instant/sorcery) — should be filtered out.
    creature_printing = None
    for p in _PRINTINGS.values():
        if p.is_creature and not p.is_instant and not p.is_sorcery:
            creature_printing = p
            break
    assert creature_printing is not None
    our_creature = state.new_object(creature_printing, 0, Zone.STACK)
    state.stack.append(
        StackItem(
            source=our_creature, controller_id=0, ability=None, targets=(),
        ),
    )
    # Our sorcery — included.
    our_bolt = state.new_object(_PRINTINGS["Plasma Bolt"], 0, Zone.STACK)
    state.stack.append(
        StackItem(
            source=our_bolt, controller_id=0, ability=None, targets=(),
        ),
    )
    legal = CopyTargetInstantOrSorceryYouControl().legal_targets(state, 0)
    # Only the controller's sorcery should be legal.
    assert legal == [("stack_spell", our_bolt.id)]


