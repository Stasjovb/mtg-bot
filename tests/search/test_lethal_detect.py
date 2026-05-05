"""Tests for the alpha-strike lethal-detect heuristic.

Coverage:
- The pure ``detect_lethal_attack`` function across happy paths,
  conservative-abort gates (opp's hand, abilities, blocker keywords,
  lifelink), and edge cases (just-not-lethal, partial blocks).
- Integration with ``ISMCTS.choose_with_visits``: when the heuristic
  fires, search is short-circuited; when it doesn't fire (out of
  combat, or any abort gate triggered), search runs as normal.
"""

from __future__ import annotations

from unittest import mock

import pytest

from mtg_bot.actions import PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.game import Zone
from mtg_bot.search import (
    AttackerDecision, MtgGameStateAdapter, RandomRolloutEvaluator,
)
from mtg_bot.search._lethal_detect import detect_lethal_attack
from mtg_bot.search.budget import Budget
from mtg_bot.search.ismcts import ISMCTS
from mtg_bot.simulate import setup_game
from mtg_bot.turn import Step
from tests._test_decks import simple_test_decklists  # noqa: E402


# ---------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------


def _setup_state(seed: int = 42):
    """Two-player setup with stripped zones for both players so the
    test has full control over what's on the battlefield / in hand."""
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=seed,
    )
    for idx in range(len(state.players)):
        p = state.players[idx]
        state.battlefield = [
            o for o in state.battlefield
            if o.controller_id != p.id and o.owner_id != p.id
        ]
        p.hand = []
        p.graveyard = []
        p.exile = []
        p.mana_pool = []
        p.library = []
    return state


def _give_creature(
    state, player_idx: int, name: str,
    *, summoning_sick: bool = False, tapped: bool = False,
) -> int:
    p = state.players[player_idx]
    obj = state.new_object(
        SYNTHETIC_CREATURES[name], owner_id=p.id,
        zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = p.id
    obj.summoning_sick = summoning_sick
    obj.tapped = tapped
    state.battlefield.append(obj)
    return obj.id


def _give_land_in_hand(state, player_idx: int, name: str) -> int:
    p = state.players[player_idx]
    obj = state.new_object(
        BASIC_LANDS[name], owner_id=p.id, zone=Zone.HAND,
    )
    p.hand.append(obj)
    return obj.id


# ---------------------------------------------------------------------
# Pure heuristic — happy path / lethal cases
# ---------------------------------------------------------------------


def test_lethal_detect_simple_alpha_strike():
    """Opp at 2 life, no blockers, attacker is 2/2 — lethal."""
    state = _setup_state()
    state.players[1].life = 2
    state.players[0].life = 20
    atk_id = _give_creature(state, 0, "Wild Bear")  # 2/2
    result = detect_lethal_attack(state, player_id=0)
    assert result == {atk_id}


def test_lethal_detect_with_some_blockers():
    """N attackers, M blockers (M < N). Opp blocks the biggest M;
    smallest N-M reach face. Pick stats so unblocked sum >= life."""
    state = _setup_state()
    state.players[1].life = 4
    # P0 attackers: 6/6 (Great Wurm), 3/3 (Forest Giant), 2/2 (Wild
    # Bear), 2/2 (Wild Bear). Sorted desc: 6,3,2,2; opp has 2 blockers
    # so they block 6 and 3, unblocked sum = 2+2 = 4. >= life 4 = lethal.
    atk_ids = [
        _give_creature(state, 0, "Great Wurm"),
        _give_creature(state, 0, "Forest Giant"),
        _give_creature(state, 0, "Wild Bear"),
        _give_creature(state, 0, "Wild Bear"),
    ]
    # P1 blockers: two 2/2s.
    _give_creature(state, 1, "Wild Bear")
    _give_creature(state, 1, "Wild Bear")
    result = detect_lethal_attack(state, player_id=0)
    assert result == set(atk_ids)


# ---------------------------------------------------------------------
# Pure heuristic — abort gates
# ---------------------------------------------------------------------


def test_lethal_detect_skipped_when_opp_has_mana():
    """Opp has untapped land but ALSO empty hand and no abilities — the
    heuristic must still fire (untapped lands by themselves don't
    disrupt — they're mana sources but with empty hand the mana goes
    nowhere). This is a regression check against being too
    conservative."""
    state = _setup_state()
    state.players[1].life = 2
    atk_id = _give_creature(state, 0, "Wild Bear")
    # Opp has an untapped Forest. No hand, no abilities.
    forest = state.new_object(
        BASIC_LANDS["Forest"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    forest.controller_id = 1
    forest.tapped = False
    state.battlefield.append(forest)
    result = detect_lethal_attack(state, player_id=0)
    # Lands' mana ability is mana-only — fires.
    assert result == {atk_id}


def test_lethal_detect_skipped_when_opp_has_cards_in_hand():
    """Cards in opp hand → potential disruption; abort."""
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    # Opp has a card in hand — any card. The heuristic doesn't try
    # to inspect what kind.
    _give_land_in_hand(state, 1, "Mountain")
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_skipped_when_opp_has_activated_ability():
    """Opp controls a creature with a non-mana activated ability —
    abort. Spider Sentinel is just vanilla so we use a real-pool
    card with an activated ability via Stone Ogre... actually
    SYNTHETIC_CREATURES is mostly vanilla. Use ``Memorial Vault`` or
    inject a synthetic activator. For this test, we use a creature
    we know has an activated ability — none in synthetic; instead,
    we reach into the real card source for a creature with an
    activated ability."""
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    # Inject a creature with a non-mana activated ability. Use the
    # active source for a card that has one. Simplest: synthetic
    # creatures don't have any, so we monkey-patch a fake activated
    # ability onto an opp creature.
    # Approach: give opp a Wild Bear, then mutate its printing's
    # activated_abilities to include a fake non-mana effect.
    from dataclasses import replace
    from mtg_bot.effects.base import (
        ActivatedAbility, ActivationCost,
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    bear_id = _give_creature(state, 1, "Wild Bear")
    bear = next(o for o in state.battlefield if o.id == bear_id)
    fake_ability = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=DrawCards(amount=1),
    )
    new_printing = replace(
        bear.printing,
        activated_abilities=(fake_ability,),
    )
    bear.printing = new_printing
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_skipped_when_blocker_has_first_strike():
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")  # 2/2
    blk_id = _give_creature(state, 1, "Wild Bear")
    blk = next(o for o in state.battlefield if o.id == blk_id)
    # Mutate the printing keywords to include first_strike.
    from dataclasses import replace
    blk.printing = replace(
        blk.printing,
        keywords=frozenset({"first_strike"}),
    )
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_skipped_when_blocker_has_indestructible():
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    blk_id = _give_creature(state, 1, "Wild Bear")
    blk = next(o for o in state.battlefield if o.id == blk_id)
    from dataclasses import replace
    blk.printing = replace(
        blk.printing,
        keywords=frozenset({"indestructible"}),
    )
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_skipped_when_blocker_has_double_strike():
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    blk_id = _give_creature(state, 1, "Wild Bear")
    blk = next(o for o in state.battlefield if o.id == blk_id)
    from dataclasses import replace
    blk.printing = replace(
        blk.printing,
        keywords=frozenset({"double_strike"}),
    )
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_skipped_when_blocker_has_hexproof():
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    blk_id = _give_creature(state, 1, "Wild Bear")
    blk = next(o for o in state.battlefield if o.id == blk_id)
    from dataclasses import replace
    blk.printing = replace(
        blk.printing,
        keywords=frozenset({"hexproof"}),
    )
    assert detect_lethal_attack(state, player_id=0) is None


# ---------------------------------------------------------------------
# Pure heuristic — lifelink math
# ---------------------------------------------------------------------


def test_lethal_detect_lifelink_blocker_increases_opp_life():
    """Opp has a 2-power lifelink blocker — even if the math is
    "exactly lethal" by attacker power, the lifelink lifegain pushes
    opp out of kill range. Heuristic should NOT fire."""
    state = _setup_state()
    # Three attackers of power 2 each (Wild Bear). One blocker with
    # lifelink (power 2). Opp at 4 life.
    # Without lifelink: powers = [2,2,2], blockers=1, unblocked sum
    #   = 2+2 = 4 >= 4 = lethal.
    # With lifelink: threshold = 4 + 2 = 6, unblocked = 4 — not lethal.
    state.players[1].life = 4
    for _ in range(3):
        _give_creature(state, 0, "Wild Bear")
    blk_id = _give_creature(state, 1, "Cleric of Dawn")  # 2/2 lifelink
    # Cleric of Dawn already has lifelink keyword in synthetic.
    assert detect_lethal_attack(state, player_id=0) is None
    # Sanity: drop opp life to 2 — now lethal even with lifelink.
    state.players[1].life = 2
    result = detect_lethal_attack(state, player_id=0)
    assert result is not None
    assert blk_id not in result  # blocker is opp's, not in our set


# ---------------------------------------------------------------------
# Pure heuristic — partial-lethal / not-lethal cases
# ---------------------------------------------------------------------


def test_lethal_detect_picks_lowest_power_subset():
    """When opp greedily blocks the biggest, the smallest reach face.
    Confirm the math accounts for the smallest unblocked correctly:
    [6, 1] vs 1 blocker → opp blocks 6, only 1 power reaches face.
    Opp at 2 life: NOT lethal."""
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Great Wurm")  # 6/6
    _give_creature(state, 0, "Sapling")  # 1/2
    _give_creature(state, 1, "Wild Bear")  # 2/2 blocker
    assert detect_lethal_attack(state, player_id=0) is None
    # Drop life to 1 — now the unblocked Sapling kills.
    state.players[1].life = 1
    result = detect_lethal_attack(state, player_id=0)
    assert result is not None
    # All eligible attackers are returned (lethal-set = full eligible
    # set today; the lowest-power "unblocked" emerges from opp's
    # greedy blocking).
    assert len(result) == 2


def test_lethal_detect_not_quite_lethal_returns_none():
    """Sum is opp_life - 1 → not lethal."""
    state = _setup_state()
    state.players[1].life = 5
    # Two Wild Bears (2/2 each) with no blockers — sum = 4, opp life = 5.
    _give_creature(state, 0, "Wild Bear")
    _give_creature(state, 0, "Wild Bear")
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_exactly_lethal_kills():
    """Sum exactly opp_life → kills (life goes to 0 → SBA loss)."""
    state = _setup_state()
    state.players[1].life = 4
    _give_creature(state, 0, "Wild Bear")
    _give_creature(state, 0, "Wild Bear")
    result = detect_lethal_attack(state, player_id=0)
    assert result is not None


def test_lethal_detect_no_attackers_returns_none():
    state = _setup_state()
    state.players[1].life = 1
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_summoning_sick_excluded_from_attackers():
    """Summoning-sick creatures aren't eligible attackers — they don't
    count toward the lethal threshold."""
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear", summoning_sick=True)
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_tapped_creature_not_an_attacker():
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear", tapped=True)
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_blockers_match_count_aborts_unblocked_zero():
    """N attackers == M blockers → all blocked, unblocked = 0, NOT
    lethal (we don't reason about damage assignment)."""
    state = _setup_state()
    state.players[1].life = 1
    _give_creature(state, 0, "Wild Bear")
    _give_creature(state, 1, "Wild Bear")
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_more_blockers_than_attackers_returns_none():
    state = _setup_state()
    state.players[1].life = 1
    _give_creature(state, 0, "Wild Bear")
    _give_creature(state, 1, "Wild Bear")
    _give_creature(state, 1, "Wild Bear")
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_opp_already_dead_returns_none():
    state = _setup_state()
    state.players[1].life = 0
    _give_creature(state, 0, "Wild Bear")
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_skipped_when_opp_has_combat_trigger_predicate():
    """Opp permanent has a triggered ability with the ATTACKS event
    (predicate-style) — heuristic aborts to avoid reasoning about
    the trigger's effect."""
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    blk_id = _give_creature(state, 1, "Wild Bear")
    blk = next(o for o in state.battlefield if o.id == blk_id)
    from dataclasses import replace
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.generic.draw_mill import DrawCards
    fake_trig = TriggeredAbility(
        event=Event.ATTACKS, effect=DrawCards(amount=1),
    )
    blk.printing = replace(
        blk.printing, triggered_abilities=(fake_trig,),
    )
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_skipped_when_opp_has_combat_trigger_string_key():
    """Opp permanent has a triggered ability with a string-key
    matching one of the combat-event names — abort."""
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    blk_id = _give_creature(state, 1, "Wild Bear")
    blk = next(o for o in state.battlefield if o.id == blk_id)
    from dataclasses import replace
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.draw_mill import DrawCards
    fake_trig = TriggeredAbility(
        trigger="attacks", effect=DrawCards(amount=1),
    )
    blk.printing = replace(
        blk.printing, triggered_abilities=(fake_trig,),
    )
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_skipped_when_opp_has_combat_trigger_alt_string():
    """A string-key trigger using the alternate combat-trigger naming
    convention (e.g. "combat_damage") still aborts."""
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    blk_id = _give_creature(state, 1, "Wild Bear")
    blk = next(o for o in state.battlefield if o.id == blk_id)
    from dataclasses import replace
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.draw_mill import DrawCards
    fake_trig = TriggeredAbility(
        trigger="combat_damage", effect=DrawCards(amount=1),
    )
    blk.printing = replace(
        blk.printing, triggered_abilities=(fake_trig,),
    )
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_skipped_when_opp_has_self_animator_land():
    """Opp controls a noncreature permanent (a basic land here, mutated
    to carry a manland-style activated ability) whose effect animates
    the land into a 2/2 creature UEOT. Even with empty hand, no combat
    triggers, and no problematic blocker keywords, the heuristic must
    abort — opp can animate a fresh blocker mid-combat and soak the
    smallest unblocked attacker."""
    from dataclasses import replace
    from mtg_bot.effects.base import (
        ActivatedAbility, ActivationCost,
    )
    from mtg_bot.effects.generic.become_type import BecomeLandCreatureUEOT
    state = _setup_state()
    state.players[1].life = 2
    atk_id = _give_creature(state, 0, "Wild Bear")  # 2/2
    # Put a Forest on opp's battlefield, then mutate its printing to
    # carry a manland-style activated ability (Mishra's Factory shape:
    # a non-tap mana cost activates "this land becomes a 2/2 creature").
    forest = state.new_object(
        BASIC_LANDS["Forest"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    forest.controller_id = 1
    forest.tapped = False
    state.battlefield.append(forest)
    animator_ability = ActivatedAbility(
        cost=ActivationCost(),
        effect=BecomeLandCreatureUEOT(power=2, toughness=2),
    )
    forest.printing = replace(
        forest.printing,
        activated_abilities=(animator_ability,),
    )
    # Sanity: the forest is still a noncreature permanent.
    from mtg_bot.game import is_creature_now
    assert is_creature_now(forest) is False
    # Heuristic aborts even though life=2 and our Wild Bear is 2/2.
    assert detect_lethal_attack(state, player_id=0) is None
    # Without the animator ability mutation it would fire (control —
    # the regular-Forest case is already covered by
    # test_lethal_detect_skipped_when_opp_has_mana, but re-asserting
    # here ties this test's premise back to a known-firing baseline).
    forest.printing = replace(forest.printing, activated_abilities=())
    assert detect_lethal_attack(state, player_id=0) == {atk_id}


def test_lethal_detect_fires_with_regular_basic_land_only():
    """Control: opp controls a regular basic land (no animation
    ability, just the implicit tap-for-mana). Heuristic still fires."""
    state = _setup_state()
    state.players[1].life = 2
    atk_id = _give_creature(state, 0, "Wild Bear")
    forest = state.new_object(
        BASIC_LANDS["Forest"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    forest.controller_id = 1
    forest.tapped = False
    state.battlefield.append(forest)
    # No mutation — basic Forest has no printed activated abilities.
    assert detect_lethal_attack(state, player_id=0) == {atk_id}


def test_lethal_detect_animator_gate_skips_already_animated_creatures():
    """The animator gate only checks NONcreature permanents — already-
    animated (or natively-creature) opp permanents are handled by the
    existing blocker-keyword / blocker-count gates. Verify the new
    gate doesn't re-abort on a creature that happens to also have the
    animation ability on its printing (defensive — a manland that's
    already a creature this turn is just a regular blocker)."""
    from dataclasses import replace
    from mtg_bot.effects.base import (
        ActivatedAbility, ActivationCost,
    )
    from mtg_bot.effects.generic.become_type import BecomeLandCreatureUEOT
    from mtg_bot.search._lethal_detect import (
        _opp_has_self_animator_permanent,
    )
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    # Opp Wild Bear with a manland-style ability bolted on. It's
    # already a creature, so the new animator gate should NOT count it
    # (the existing creature-blocker gates handle it).
    bear_id = _give_creature(state, 1, "Wild Bear")
    bear = next(o for o in state.battlefield if o.id == bear_id)
    animator_ability = ActivatedAbility(
        cost=ActivationCost(),
        effect=BecomeLandCreatureUEOT(power=2, toughness=2),
    )
    bear.printing = replace(
        bear.printing,
        activated_abilities=(animator_ability,),
    )
    # The animator gate (in isolation) does not flag an already-creature
    # permanent.
    assert _opp_has_self_animator_permanent(state, opp_id=1) is False


def test_lethal_detect_animator_gate_skips_mana_abilities():
    """Mana abilities (``is_mana_ability=True``) are skipped by the
    animator gate even if their effect class were to coincidentally
    match — we shouldn't be flagging mana sources as animators.
    (Defensive: today no real card combines mana-ability=True with a
    BecomeLandCreatureUEOT effect, but the skip keeps the gate honest
    if a future synthetic card does.)"""
    from dataclasses import replace
    from mtg_bot.effects.base import (
        ActivatedAbility, ActivationCost,
    )
    from mtg_bot.effects.generic.become_type import BecomeLandCreatureUEOT
    from mtg_bot.search._lethal_detect import (
        _opp_has_self_animator_permanent,
    )
    state = _setup_state()
    forest = state.new_object(
        BASIC_LANDS["Forest"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    forest.controller_id = 1
    state.battlefield.append(forest)
    weird_ability = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=BecomeLandCreatureUEOT(power=2, toughness=2),
        is_mana_ability=True,
    )
    forest.printing = replace(
        forest.printing,
        activated_abilities=(weird_ability,),
    )
    # Mana-ability skip: the animator gate alone does NOT flag this.
    assert _opp_has_self_animator_permanent(state, opp_id=1) is False


def test_lethal_detect_returns_none_with_no_opp():
    """3+ player game (or all opps lost) — single-opp gate fails."""
    state = _setup_state()
    # Mark opp as having lost.
    state.players[1].has_lost = True
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    assert detect_lethal_attack(state, player_id=0) is None


def test_lethal_detect_does_not_abort_on_mana_ability_only():
    """Opp has a creature with an explicit mana-only activated ability
    (AddMana) — should NOT trigger the abort."""
    state = _setup_state()
    state.players[1].life = 2
    atk_id = _give_creature(state, 0, "Wild Bear")
    # Add a creature on opp side that has only a mana ability.
    # Easiest: use a Forest (basic land has tap-for-mana). But a creature
    # specifically with a mana ability via Llanowar Elves... synthetic
    # doesn't have one. Inject via mutation.
    # Skip the creature path — the existing test_lethal_detect_skipped_
    # when_opp_has_mana already verifies opp Forest doesn't trigger
    # an abort. This test specifically verifies the AddMana effect
    # class name is recognized.
    from dataclasses import replace
    from mtg_bot.effects.base import (
        ActivatedAbility, ActivationCost,
    )
    # Create a fake mana ability class instance — use the real AddMana
    # if importable; otherwise synthesize a duck-typed object.
    try:
        from mtg_bot.effects.generic.add_mana import AddMana
        mana_effect = AddMana(amount=1, color="G")
    except Exception:
        # Fallback: define a class with the right __name__.
        class AddMana:
            pass
        mana_effect = AddMana()
    mana_ability = ActivatedAbility(
        cost=ActivationCost(tap_self=True), effect=mana_effect,
    )
    blk_id = _give_creature(state, 1, "Wild Bear")
    blk = next(o for o in state.battlefield if o.id == blk_id)
    blk.printing = replace(
        blk.printing, activated_abilities=(mana_ability,),
    )
    # Opp has 1 creature blocker. We have 1 attacker. Unblocked = 0.
    # So lethal should NOT be detected — but for a different reason
    # than "mana ability disrupts." Add another attacker.
    _give_creature(state, 0, "Wild Bear")
    _give_creature(state, 0, "Wild Bear")
    # Now we have 3 attackers vs 1 blocker; opp blocks biggest 2/2,
    # 2 unblocked Wild Bears reach face = 4 damage > opp life 2 = lethal.
    result = detect_lethal_attack(state, player_id=0)
    # The mana-only ability did NOT cause an abort; lethal detected.
    assert result is not None
    assert atk_id in result


# ---------------------------------------------------------------------
# Integration: ISMCTS short-circuit
# ---------------------------------------------------------------------


def _drive_to_attacker_phase(adapter):
    """Pass priority until the adapter is at an attacker sub-decision."""
    MAX = 100
    for _ in range(MAX):
        if adapter.is_terminal():
            return
        if adapter.combat_phase == "attackers":
            return
        legal = adapter.legal_decisions()
        if not legal:
            return
        # Find a PassPriority and apply it.
        for d in legal:
            if isinstance(d, PassPriority):
                adapter.apply(d)
                break
        else:
            return
    raise AssertionError(
        f"failed to reach attacker phase within {MAX} iterations"
    )


def _make_search(enable_lethal_detect: bool = True) -> ISMCTS:
    """Plain UCB1 ISMCTS (no PUCT) — RandomRolloutEvaluator is
    sufficient and avoids needing a policy-capable evaluator."""
    return ISMCTS(
        evaluator=RandomRolloutEvaluator(),
        budget_factory=lambda: Budget(max_nodes=20),
        puct=False,
        enable_lethal_detect=enable_lethal_detect,
    )


def test_lethal_detect_short_circuits_choose_with_visits():
    """When the heuristic fires, the search loop is NOT entered."""
    state = _setup_state()
    state.players[1].life = 2
    state.players[0].life = 20
    _give_creature(state, 0, "Wild Bear")  # 2/2 attacker
    adapter = MtgGameStateAdapter(state, expose_combat_decisions=True)
    _drive_to_attacker_phase(adapter)
    assert adapter.combat_phase == "attackers"

    search = _make_search(enable_lethal_detect=True)
    # Spy on _search_serial so we can verify it's NOT called.
    with mock.patch.object(
        search, "_search_serial", wraps=search._search_serial,
    ) as serial_spy:
        visits = search.choose_with_visits(adapter, player_id=0)
    # Search bypassed entirely.
    serial_spy.assert_not_called()
    # One decision returned with a single visit.
    assert len(visits) == 1
    decision, count = next(iter(visits.items()))
    assert isinstance(decision, AttackerDecision)
    assert decision.attack is True
    assert count == 1
    # Counter incremented.
    assert search._lethal_detect_fires == 1


def test_lethal_detect_falls_through_when_heuristic_disabled():
    """With ``enable_lethal_detect=False`` search runs normally even
    in a known-lethal position."""
    state = _setup_state()
    state.players[1].life = 2
    state.players[0].life = 20
    _give_creature(state, 0, "Wild Bear")
    adapter = MtgGameStateAdapter(state, expose_combat_decisions=True)
    _drive_to_attacker_phase(adapter)
    assert adapter.combat_phase == "attackers"

    search = _make_search(enable_lethal_detect=False)
    with mock.patch.object(
        search, "_search_serial", wraps=search._search_serial,
    ) as serial_spy:
        search.choose_with_visits(adapter, player_id=0)
    serial_spy.assert_called_once()
    assert search._lethal_detect_fires == 0


def test_lethal_detect_falls_through_when_not_in_combat_phase():
    """Outside of attacker-decision phase, the heuristic doesn't fire.
    We verify by checking the heuristic firing counter stays at 0.
    (The number of legal decisions and whether search is invoked
    depends on capability auto-pass; we only care that the lethal-
    detect path didn't trigger.)"""
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    adapter = MtgGameStateAdapter(state, expose_combat_decisions=True)
    # Don't drive to attacker phase — stay at the main-phase priority.
    assert adapter.combat_phase is None

    search = _make_search(enable_lethal_detect=True)
    search.choose_with_visits(adapter, player_id=0)
    # Heuristic does NOT fire from a non-attacker-phase moment.
    assert search._lethal_detect_fires == 0


def test_lethal_detect_falls_through_when_heuristic_aborts():
    """Heuristic aborts (opp has cards in hand) — search proceeds."""
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    # Opp has a card in hand → abort.
    _give_land_in_hand(state, 1, "Mountain")
    adapter = MtgGameStateAdapter(state, expose_combat_decisions=True)
    _drive_to_attacker_phase(adapter)
    search = _make_search(enable_lethal_detect=True)
    with mock.patch.object(
        search, "_search_serial", wraps=search._search_serial,
    ) as serial_spy:
        search.choose_with_visits(adapter, player_id=0)
    serial_spy.assert_called_once()
    assert search._lethal_detect_fires == 0


def test_lethal_detect_returns_attack_subset_correctly():
    """When lethal subset is detected, the head pending attacker's
    AttackerDecision routed through the heuristic is attack=True.
    Multi-attacker case: each attacker's choose_with_visits call gets
    short-circuited individually."""
    state = _setup_state()
    state.players[1].life = 4
    # 2 attackers of power 2 each; no blockers — both unblocked, sum
    # 4 = lethal at life 4.
    atk_ids = [
        _give_creature(state, 0, "Wild Bear"),
        _give_creature(state, 0, "Wild Bear"),
    ]
    adapter = MtgGameStateAdapter(state, expose_combat_decisions=True)
    _drive_to_attacker_phase(adapter)
    search = _make_search(enable_lethal_detect=True)
    # Drive both attacker sub-decisions through the search.
    seen_ids: list[int] = []
    for _ in range(2):
        assert adapter.combat_phase == "attackers"
        visits = search.choose_with_visits(adapter, player_id=0)
        assert len(visits) == 1
        decision = next(iter(visits.keys()))
        assert isinstance(decision, AttackerDecision)
        assert decision.attack is True
        seen_ids.append(decision.attacker_id)
        adapter.apply(decision)
    # Combat phase finalized.
    assert adapter.combat_phase is None
    # Both creatures committed to attack.
    attacking = [o for o in adapter.engine_state.battlefield if o.attacking]
    assert {o.id for o in attacking} == set(atk_ids)
    # Heuristic fired twice (once per sub-decision).
    assert search._lethal_detect_fires == 2


def test_reset_lethal_detect_count_zeroes_counter():
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    adapter = MtgGameStateAdapter(state, expose_combat_decisions=True)
    _drive_to_attacker_phase(adapter)
    search = _make_search(enable_lethal_detect=True)
    search.choose_with_visits(adapter, player_id=0)
    assert search._lethal_detect_fires == 1
    search.reset_lethal_detect_count()
    assert search._lethal_detect_fires == 0


def test_lethal_detect_falls_through_when_viewer_isnt_active():
    """If the search is being driven from a non-active-player POV
    during attacker phase (defensive — shouldn't normally happen),
    the heuristic aborts."""
    state = _setup_state()
    state.players[1].life = 2
    _give_creature(state, 0, "Wild Bear")
    adapter = MtgGameStateAdapter(state, expose_combat_decisions=True)
    _drive_to_attacker_phase(adapter)
    search = _make_search(enable_lethal_detect=True)
    # Active player is 0 (turn holder); pass viewer=1 (the wrong POV).
    # This tests the active_player()==player_id sanity gate. Since
    # the adapter isn't terminal and there are 2 legal decisions,
    # a search will be needed. We don't actually need to verify
    # search runs to completion — just that the heuristic short-
    # circuit doesn't fire from the wrong POV. We CAN still call
    # choose_with_visits with viewer=1 because legal is non-empty.
    # However, the determinizer / evaluator will operate from
    # viewer 1's POV and may error if state is inconsistent —
    # use a try/except so any internal exception is fine, we only
    # care that the heuristic counter stays at 0.
    try:
        search.choose_with_visits(adapter, player_id=1)
    except Exception:
        pass
    assert search._lethal_detect_fires == 0
