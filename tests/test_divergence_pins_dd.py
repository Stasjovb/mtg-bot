"""Divergence-pin tests: batch DD (rounds 1-7 surfaced bugs).

Each test is named ``test_cross_engine_real_eoe_<slug>_*_divergence_pin``
and ASSERTS the CURRENT divergent behavior rather than parity. The
PROBED-tier detector excludes ``*_divergence_pin`` functions, so these
tests grow the test surface without touching the PROBED metric.

Pinned bugs
-----------

Pin 1 — ``DealDamageEqualToSourcePowerAnyTarget`` DIES-trigger battlefield
search (state_ops_resolve.rs:9584-9604).

    Rust's resolve arm for ``Effect::DealDamageEqualToSourcePowerAnyTarget``
    searches ``player.battlefield`` for the source object to read its
    printed power.  For a DIES-triggered ability the source creature has
    already moved to the graveyard at the time the trigger resolves — the
    battlefield search finds nothing, ``amount`` stays 0, and the early-
    return at line 9602 fires with no damage dealt.

    Python's ``DealDamageEqualToSourcePowerAnyTarget.resolve``
    (``effects/generic/damage.py:238-260``) reads
    ``state.resolving_source.effective_power`` instead.
    ``state.resolving_source`` is set to ``item.source`` in
    ``resolve_top_of_stack`` (``actions.py:2678``) and ``item.source`` is
    the ``GameObject`` reference captured when the trigger was pushed —
    the dying creature.  At push time the object was still on the
    battlefield; at resolve time the reference survives the zone move and
    the graveyard copy retains ``printing.power``.  Python therefore reads
    the creature's printed power and deals the correct amount.

    CR reference: CR 603.10 (last-known information for triggered ability
    sources that change zones after the trigger condition is met) and
    CR 603.3c (triggered ability goes on the stack when the condition is
    met; the object that caused the trigger is the source).

    Verified observable divergence (source power 3, p1 player target):
      * Python: p1 life decreases by 3.
      * Rust:   p1 life unchanged (amount = 0; early return).

Pin 2 — ``grant_keyword_to_target_creature_until_eot`` bridge class-mismatch
(FIXED in feature/bridge-grant-keyword-fix; now a ``_parity`` probe).

    The cross-engine bridge arm for the Rust dict kind
    ``grant_keyword_to_target_creature_until_eot`` previously constructed
    ``PumpTargetCreatureUntilEOT`` for ALL keyword values, including
    ``keyword="unblockable"``, causing ``is_cant_be_blocked`` to return False
    for bridge-routed resolves because the wrong registry kind was written
    (``grant_keyword`` instead of ``cant_be_blocked``).

    Fixed: the bridge arm now detects ``keyword == "unblockable"`` and returns
    ``GrantUnblockableUEOT()``.  For genuine MTG keywords (haste, lifelink,
    etc.) the ``PumpTargetCreatureUntilEOT`` path is retained.

    The test ``test_cross_engine_real_eoe_enter_the_enigma_unblockable_bridge_
    class_mismatch_FIXED_parity`` (below) now asserts the CORRECT behavior
    (both paths return True from ``is_cant_be_blocked``).
"""

from __future__ import annotations

import importlib.util

import pytest

# ---------------------------------------------------------------------------
# Rust-engine guard for Pin 1 (requires PyO3 extension; skipped otherwise).
# ---------------------------------------------------------------------------

_RUST_ENGINE_AVAILABLE = importlib.util.find_spec("mtg_bot_engine") is not None

pytestmark_rust = pytest.mark.skipif(
    not _RUST_ENGINE_AVAILABLE,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_base_state():
    """Minimal two-player GameState for Python-only pins."""
    from mtg_bot.game import GameState, Player
    from mtg_bot.turn import Step

    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put_on_bf(state, printing, owner_id):
    """Place a new GameObject on the battlefield (no ETB triggers)."""
    from mtg_bot.game import Zone

    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = False
    obj.damage = 0
    obj.etb_timestamp = state.next_timestamp
    state.next_timestamp += 1
    state.battlefield.append(obj)
    return obj


# ---------------------------------------------------------------------------
# Pin 1 — DealDamageEqualToSourcePowerAnyTarget DIES battlefield search
# ---------------------------------------------------------------------------

@pytestmark_rust
def test_cross_engine_real_eoe_infernal_phantom_dies_damage_source_power_battlefield_search_divergence_pin():
    """Pin the Rust-vs-Python divergence for
    ``Effect::DealDamageEqualToSourcePowerAnyTarget`` on a DIES trigger.

    Bug location:
      Rust: ``rust/src/state_ops_resolve.rs:9584-9604`` —
      ``Effect::DealDamageEqualToSourcePowerAnyTarget`` searches
      ``player.battlefield`` for the source object to read its printed power.
      On a DIES trigger the source creature is already in the graveyard when
      the trigger resolves; the battlefield scan finds nothing; ``amount``
      stays 0; the early-return at 9602 fires with no damage dealt.

      Python: ``src/mtg_bot/effects/generic/damage.py:238-244`` —
      ``DealDamageEqualToSourcePowerAnyTarget.resolve`` reads
      ``state.resolving_source.effective_power``.  ``state.resolving_source``
      is the ``item.source`` reference captured at push time (the dying
      creature while still on battlefield); the reference survives the zone
      move; the graveyard copy retains ``printing.power``.  Python reads
      power = 3 and deals 3 damage to p1.

    What's right: Python (CR 603.10 last-known-information for the source).

    Verified divergence (source power 3, p1 player target):
      * Python: p1 life 20 → 17 (3 damage dealt).
      * Rust:   p1 life 20 → 20 (amount = 0; early return; no damage).

    Probe shape:
      1. Build states with a 3/2 creature ("Phantom Striker") on p0's bf
         with a self-DIES trigger: ``deal_damage_equal_to_source_power_any_
         target``.  No target is injected onto p1's bf — Rust's resolve arm
         falls back to the defender-player when no p1 creature exists, so
         with amount = 0 the fallback is irrelevant.  Python directs the
         target to p1 player via the agent seated below.
      2. Python only: seat a ``_PickFirstOpponentTargetAgent`` on p0 so the
         trigger's target-selection at push time picks the p1 player.
         (Rust's ``DealDamageEqualToSourcePowerAnyTarget`` picks the target
         at resolve time deterministically — no agent needed.)
      3. Mark lethal damage on the creature (damage >= toughness 2).
      4. Run an SBA pass on both engines.  Both engines detect lethal damage,
         move the creature to the graveyard, and fire its DIES trigger.
         Both stacks should hold exactly one trigger item.
      5. Drain both stacks (resolve the trigger).
      6. Assert per-engine divergence on p1's life total.

    Out of scope:
      * Cross-engine parity — this probe DOCUMENTS a known divergence;
        no cross-engine equivalence assertion is made.
      * Target choice divergence — Rust's deterministic player-fallback
        and Python's agent-picked player converge on p1 IF amount > 0;
        the divergence is on the AMOUNT step, not on target routing.
      * SBA lethal-damage vs. destroy ordering — both engines apply the
        same indestructible-unaware lethal-damage SBA; the creature is
        a plain 3/2 with no riders.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import state_based_actions as py_sba
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    # Build states: one card ("Phantom Striker" 3/2 Creature with DIES
    # trigger for deal_damage_equal_to_source_power_any_target).
    phantom_striker = DeckSpec(
        card_defs=(
            {  # type: ignore[arg-type]  # CardDef-compatible dict
                "name": "Phantom Striker",
                "card_type": "Creature",
                "mana_cost_generic": 2,
                "mana_cost_colored": (("B", 1),),
                "power": 3,
                "toughness": 2,
                "triggered_abilities": (
                    {
                        "event": "dies",
                        "predicate": {"kind": "source_is_self"},
                        "effect": {
                            "kind": "deal_damage_equal_to_source_power_any_target",
                        },
                    },
                ),
            },
        ),
        p0_library=(),
        p1_library=(),
    )
    # build_python_state and build_rust_state both accept DeckSpec; however
    # card_defs contains a raw dict here (not a CardDef dataclass) because
    # CardDef doesn't carry a ``triggered_abilities`` event="dies" shape in
    # its standard initializer.  The builders accept dicts transparently
    # via the same dict-to-printing bridge used by every probe.
    #
    # HOWEVER -- CardDef must be a dataclass instance for build_python_state.
    # Use the raw DeckSpec constructor with an empty card_defs and inject
    # the creature manually on both sides (the same pattern used by the
    # Gravpack Monoist DIES probe at test_parity_smoke.py:57966).

    # Empty DeckSpec: no library cards; inject the creature manually.
    spec = DeckSpec(
        card_defs=(),
        p0_library=(),
        p1_library=(),
    )
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)

    # ---- Python side: build the printing manually and inject ----
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.damage import DealDamageEqualToSourcePowerAnyTarget
    from mtg_bot.effects.predicates import Event, IsSelf

    phantom_printing = CardPrinting(
        name="Phantom Striker",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("B", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=3,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.DIES,
                predicate=IsSelf(),
                effect=DealDamageEqualToSourcePowerAnyTarget(),
            ),
        ),
    )

    # Seat an agent on p0 (Python side) so the DIES trigger's
    # push-time target-selection picks the p1 player.
    py_state.players[0].agent = _PickFirstOpponentTargetAgent()

    from mtg_bot.game import Zone
    py_phantom = py_state.new_object(phantom_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_phantom.summoning_sick = False
    py_phantom.tapped = False
    py_phantom.damage = 0
    py_phantom.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_phantom)

    py_p0_life_before = py_state.players[0].life
    py_p1_life_before = py_state.players[1].life
    assert py_p0_life_before == 20
    assert py_p1_life_before == 20

    # ---- Rust side: register and inject the creature ----
    ZONE_BATTLEFIELD = 2
    rust_phantom_id = rust_state.register_and_inject_object(
        {
            "name": "Phantom Striker",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 2, "B": 1},
            "effects": [],
            "power": 3,
            "toughness": 2,
            "triggered_abilities": [
                {
                    "event": "dies",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "deal_damage_equal_to_source_power_any_target",
                    },
                }
            ],
        },
        0,  # controller = p0
        ZONE_BATTLEFIELD,
    )

    rust_p0_life_before = rust_state.get_life(0)
    rust_p1_life_before = rust_state.get_life(1)
    assert rust_p0_life_before == 20
    assert rust_p1_life_before == 20

    # No DIES trigger fires just from sitting on bf.
    assert rust_state.stack_size() == 0, (
        f"Rust: no trigger expected before SBA; got {rust_state.stack_size()}"
    )
    assert len(py_state.stack) == 0, (
        f"Python: no trigger expected before SBA; got {len(py_state.stack)}"
    )

    # ---- Mark lethal damage (toughness = 2; 2 damage = lethal) ----
    py_phantom.damage = 2

    # Rust: deal_damage marks damage on the object.
    rust_state.deal_damage(rust_phantom_id, 2)

    # ---- SBA pass — creature dies; DIES trigger fires ----
    py_sba(py_state)
    rust_state.apply_sbas()

    # After SBA: creature should be in graveyard on both sides.
    py_bf_names = [o.printing.name for o in py_state.battlefield]
    assert "Phantom Striker" not in py_bf_names, (
        "Python: Phantom Striker should have moved to graveyard via SBA "
        f"lethal damage; bf={py_bf_names}"
    )
    py_p0_gy = [o.printing.name for o in py_state.players[0].graveyard]
    assert "Phantom Striker" in py_p0_gy, (
        f"Python: Phantom Striker should be in p0's graveyard; gy={py_p0_gy}"
    )

    rust_bf_snapshot = rust_state.battlefield_snapshot()
    rust_bf_names = [e.get("printing_name") for e in rust_bf_snapshot]
    assert "Phantom Striker" not in rust_bf_names, (
        "Rust: Phantom Striker should have moved to graveyard via SBA "
        f"lethal damage; bf_names={rust_bf_names}"
    )

    # DIES trigger should be on stack on both engines.
    assert rust_state.stack_size() == 1, (
        "Rust: Phantom Striker DIES trigger should be on stack after SBA; "
        f"got stack_size={rust_state.stack_size()}"
    )
    assert len(py_state.stack) == 1, (
        "Python: Phantom Striker DIES trigger should be on stack after SBA; "
        f"got stack size={len(py_state.stack)}"
    )

    # ---- Drain both stacks (resolve DIES trigger) ----
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    while py_state.stack:
        resolve_top_of_stack(py_state)

    # ---- Per-engine divergence assertions ----
    # Python: resolving_source = Phantom Striker (graveyard ref); power = 3;
    # deals 3 damage to p1 player (agent-picked target).
    assert py_state.players[1].life == py_p1_life_before - 3, (
        "Python: DealDamageEqualToSourcePowerAnyTarget DIES trigger should "
        "read resolving_source (graveyard object) and deal 3 damage to p1. "
        "Bug-fix will make Rust match this value. "
        f"before={py_p1_life_before} "
        f"after={py_state.players[1].life}"
    )
    assert py_state.players[0].life == py_p0_life_before, (
        f"Python: p0 life should be unchanged; got {py_state.players[0].life}"
    )

    # Rust: DealDamageEqualToSourcePowerAnyTarget resolve arm at
    # state_ops_resolve.rs:9590 searches player.battlefield for the source
    # object — not found (creature is in graveyard) → amount = 0 → early
    # return at line 9602 → NO damage dealt → p1 life unchanged.
    assert rust_state.get_life(1) == rust_p1_life_before, (
        "Rust: DealDamageEqualToSourcePowerAnyTarget on a DIES trigger should "
        "deal 0 damage (source not found on battlefield; battlefield-search "
        "bug at state_ops_resolve.rs:9590). Pinned divergent behavior — will "
        "flip to FAIL when Rust searches resolving_source_zone (graveyard) "
        "instead of only battlefield. "
        f"before={rust_p1_life_before} "
        f"after={rust_state.get_life(1)}"
    )
    assert rust_state.get_life(0) == rust_p0_life_before, (
        f"Rust: p0 life should be unchanged; got {rust_state.get_life(0)}"
    )

    # CROSS-ENGINE NON-PARITY: p1 life values MUST differ between engines.
    # When Rust fixes the battlefield-search bug (reads graveyard or
    # resolving_source instead), both engines will deal 3 damage and
    # py_p1_life == rust_p1_life == 17.  That flip makes this assertion
    # fail, signaling that the pin should be converted to a parity assert.
    assert py_state.players[1].life != rust_state.get_life(1), (
        "Cross-engine non-parity: Python (3 damage) should NOT equal "
        "Rust (0 damage) until the battlefield-search bug is fixed. "
        f"Python p1 life={py_state.players[1].life}, "
        f"Rust p1 life={rust_state.get_life(1)}"
    )

    # Both stacks should be empty after drain.
    assert rust_state.stack_size() == 0, (
        f"Rust: stack should be empty post-drain; got {rust_state.stack_size()}"
    )
    assert len(py_state.stack) == 0, (
        f"Python: stack should be empty post-drain; got {len(py_state.stack)}"
    )


# ---------------------------------------------------------------------------
# Pin 2 — grant_keyword_to_target_creature_until_eot bridge class-mismatch
# (FIXED in feature/bridge-grant-keyword-fix; converted to _parity probe)
# ---------------------------------------------------------------------------

def test_cross_engine_real_eoe_enter_the_enigma_unblockable_bridge_class_mismatch_FIXED_parity():
    """Parity probe: the bridge arm for ``grant_keyword_to_target_creature_until_eot``
    with ``keyword="unblockable"`` now returns ``GrantUnblockableUEOT`` (not
    ``PumpTargetCreatureUntilEOT``), and both the direct-Python and bridge-routed
    resolve paths produce a layer-6 ``cant_be_blocked`` registry entry that
    ``is_cant_be_blocked`` recognizes.

    Bug that was fixed (branch: feature/bridge-grant-keyword-fix):
      ``src/mtg_bot/parity/cross_engine.py`` — the bridge arm for Rust dict kind
      ``grant_keyword_to_target_creature_until_eot`` previously always constructed
      ``PumpTargetCreatureUntilEOT(power_bonus=0, toughness_bonus=0,
      granted_keywords=frozenset({keyword}), you_control_only=True,
      exclude_self=False)`` for ANY keyword value, including ``"unblockable"``.

      ``PumpTargetCreatureUntilEOT.resolve`` (with granted_keywords) calls
      ``GrantKeywords(keywords={"unblockable"})`` which writes a layer-6
      ``grant_keyword`` continuous-effect registry entry with
      ``params=("unblockable",)``.  ``is_cant_be_blocked`` (``game.py``)
      checks for ``kind == "cant_be_blocked"`` — a structurally distinct
      registry kind.  After the bridge-routed resolve, the target creature
      did NOT test as unblockable.

    The fix:
      The bridge arm now detects ``keyword == "unblockable"`` and returns
      ``GrantUnblockableUEOT()`` instead of ``PumpTargetCreatureUntilEOT``.
      ``GrantUnblockable.resolve`` writes a layer-6 ``cant_be_blocked`` entry
      that ``is_cant_be_blocked`` recognizes.  For genuine MTG keywords (haste,
      lifelink, deathtouch, flying, trample, reach, first_strike, etc.) the
      ``PumpTargetCreatureUntilEOT`` path is retained — those ARE ``grant_keyword``
      registry entries consumed by ``effective_keywords``.

    CR reference: CR 509.1b — "can't be blocked" is a gameplay-action restriction
    (layer 6 continuous effect), NOT an MTG keyword.

    Parity assertions:
      * Bridge returns ``GrantUnblockableUEOT`` (not ``PumpTargetCreatureUntilEOT``).
      * Both paths write a layer-6 ``cant_be_blocked`` entry on the target.
      * Both paths make ``is_cant_be_blocked(state, target)`` return True.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.grant_keywords import GrantUnblockableUEOT
    from mtg_bot.game import GameState, Player, Zone, is_cant_be_blocked
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.turn import Step

    bait_printing = CardPrinting(
        name="Bait Creature",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
    )

    def _make_state_with_bait():
        """Return (state, bait_obj) — a minimal state with one 1/1 on p0's bf."""
        state = GameState()
        state.players.append(Player(id=0, life=20))
        state.players.append(Player(id=1, life=20))
        state.active_player_idx = 0
        state.priority_player_idx = 0
        state.step = Step.PRECOMBAT_MAIN
        bait = state.new_object(bait_printing, owner_id=0, zone=Zone.BATTLEFIELD)
        bait.summoning_sick = False
        bait.tapped = False
        bait.damage = 0
        bait.etb_timestamp = state.next_timestamp
        state.next_timestamp += 1
        state.battlefield.append(bait)
        return state, bait

    # ------------------------------------------------------------------
    # Path A: correct path — GrantUnblockableUEOT directly.
    # ------------------------------------------------------------------
    state_a, bait_a = _make_state_with_bait()

    GrantUnblockableUEOT().resolve(
        state_a,
        controller_id=0,
        targets=(("creature", bait_a.id),),
    )

    is_unblockable_a = is_cant_be_blocked(state_a, bait_a)

    # Verify the expected registry shape for the correct path.
    cant_be_blocked_entries_a = [
        ce for ce in state_a.continuous_effects
        if ce.layer == 6 and ce.kind == "cant_be_blocked" and ce.target_id == bait_a.id
    ]
    assert cant_be_blocked_entries_a, (
        "Path A (GrantUnblockableUEOT): expected a layer-6 'cant_be_blocked' "
        "registry entry on bait_a after resolve; got none. "
        f"continuous_effects={state_a.continuous_effects}"
    )
    assert is_unblockable_a is True, (
        "Path A (GrantUnblockableUEOT): is_cant_be_blocked should return True "
        "after GrantUnblockableUEOT.resolve — the correct Python class writes "
        "a 'cant_be_blocked' layer-6 entry that is_cant_be_blocked recognizes. "
        f"Got: {is_unblockable_a}"
    )

    # ------------------------------------------------------------------
    # Path B: bridge-routed path — _ta_dict_to_python_effect.
    # ------------------------------------------------------------------
    state_b, bait_b = _make_state_with_bait()

    effect_dict = {
        "kind": "grant_keyword_to_target_creature_until_eot",
        "keyword": "unblockable",
    }
    bridge_effect = _ta_dict_to_python_effect(effect_dict)

    # Post-fix: the bridge must return GrantUnblockableUEOT, not PumpTargetCreatureUntilEOT.
    assert isinstance(bridge_effect, GrantUnblockableUEOT), (
        "Bridge class parity: _ta_dict_to_python_effect for "
        "grant_keyword_to_target_creature_until_eot with keyword='unblockable' "
        "must return GrantUnblockableUEOT (the correct class after the fix). "
        f"Got: {type(bridge_effect).__name__}. "
        "If this assertion fails, the bridge fix was reverted."
    )

    # Resolve the bridge-returned effect on bait_b.
    bridge_effect.resolve(
        state_b,
        controller_id=0,
        targets=(("creature", bait_b.id),),
    )

    is_unblockable_b = is_cant_be_blocked(state_b, bait_b)

    # Verify the correct registry shape for the bridge path.
    cant_be_blocked_entries_b = [
        ce for ce in state_b.continuous_effects
        if ce.layer == 6 and ce.kind == "cant_be_blocked" and ce.target_id == bait_b.id
    ]
    assert cant_be_blocked_entries_b, (
        "Path B (GrantUnblockableUEOT via bridge): expected a layer-6 "
        "'cant_be_blocked' registry entry on bait_b after resolve; got none. "
        f"continuous_effects={state_b.continuous_effects}"
    )
    assert is_unblockable_b is True, (
        "Path B (bridge route): is_cant_be_blocked should return True after "
        "GrantUnblockableUEOT.resolve via the fixed bridge — the bridge now "
        "returns GrantUnblockableUEOT which writes 'cant_be_blocked' (not "
        "'grant_keyword'), so is_cant_be_blocked returns True. "
        f"Got: {is_unblockable_b}"
    )

    # ------------------------------------------------------------------
    # Cross-path parity: both paths now agree.
    # ------------------------------------------------------------------
    assert is_unblockable_a == is_unblockable_b == True, (
        "Cross-path parity: GrantUnblockableUEOT (direct) and bridge-route "
        "GrantUnblockableUEOT should both make is_cant_be_blocked return True. "
        f"is_unblockable_a={is_unblockable_a}, "
        f"is_unblockable_b={is_unblockable_b}"
    )
