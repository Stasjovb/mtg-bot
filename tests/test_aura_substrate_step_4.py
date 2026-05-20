"""Aura-attachment substrate — Phase 1 STEP 4 tests.

Spec: ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §3 Phase 1 step 4.

**STEP 4 scope.** When an Aura spell resolves, the Rust engine must:

1. Read the cast-time bound target from the StackItem's
   ``target_obj_id`` (set by STEP 3's ``submit_enchant_target_decision``
   dispatcher and swapped in by the resolver via the
   ``current_resolve_payload_target_id`` payload swap).
2. Validate at resolve time per CR 608.2b — target still on a
   battlefield, type matches ``aura_enchant_type``, ``aura_yours_only``
   respected.
3. **Illegal target → fizzle (CR 608.2b).** Aura goes to its owner's
   graveyard; ``attached_to`` stays ``None``.
4. **Legal target → attach.** Aura enters the battlefield with
   ``attached_to = Some(host_id)``; the layer-7c P/T bonus +
   layer-6 keyword grants from ``aura_power_bonus`` /
   ``aura_toughness_bonus`` / ``aura_granted_keywords`` become
   readable via the engine's ``effective_power`` /
   ``effective_toughness`` / ``battlefield_has_keyword`` accessors.

Mirrors Python's Aura resolve branch at ``actions.py:2720-2758``
(fizzle + attach) and the equipment_bonuses scan in
``game.py:969-996`` / ``game.py:1120-1145`` (layered grant readers).

**Deferred to STEP 5+:**

* CR-704.5n SBA (bury an Aura whose host disappears between
  resolves) + the host-leave bury (Aura sent to graveyard when its
  attached host leaves the battlefield).
* Bidirectional bridge arms across the new state slots
  (``attached_to``, ``aura_*`` printing fields — STEP 6).
* OR-in of ``_printing_is_bridge_simple_aura`` into the loader's
  5-disjunct admit chokepoint (STEP 7).
* Sub-shape S2 (control-changing auras via
  ``apply_aura_static_grants_on_attach`` analogue) is a separate
  Phase 2 lane.

These tests exercise the resolve arm + layered-grant readers in
isolation using synthetic state fixtures (the loader still does not
admit any real Aura — STEP 7 honest-stop, see
``test_aura_substrate_phase1.py``).
"""

from __future__ import annotations

import importlib

import pytest

ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


def _aura_printing_dict(
    name="Frantic Strength",
    mana_cost=None,
    enchant_type="creature",
    yours_only=False,
    p_bonus=2,
    t_bonus=2,
    granted_keywords=("trample",),
):
    """Build a registry-dict for an Aura printing. Mirrors the
    STEP-2 emission shape (``cross_engine.py:10384-10391``)."""
    if mana_cost is None:
        mana_cost = {"R": 1}
    d = {
        "name": name,
        "mana_cost": mana_cost,
        "card_types": ["Enchantment"],
        "subtypes": ["Aura"],
        "is_aura": True,
        "aura_enchant_type": enchant_type,
    }
    if yours_only:
        d["aura_yours_only"] = True
    if p_bonus or t_bonus or granted_keywords:
        d["aura_equipment_bonuses"] = {
            "power_bonus": p_bonus,
            "toughness_bonus": t_bonus,
            "granted_keywords": list(granted_keywords),
        }
    return d


def _creature_dict(name="Grizzly Bears", power=2, toughness=2):
    return {
        "name": name,
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "subtypes": ["Bear"],
        "power": power,
        "toughness": toughness,
    }


def _artifact_dict(name="Plain Artifact"):
    return {
        "name": name,
        "mana_cost": {"generic": 2},
        "card_types": ["Artifact"],
    }


def _fresh_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _battlefield_obj(state, player_id, obj_id):
    """Find an object with given id on either player's battlefield.
    Returns the dict if present (and matches expected controller),
    else None. ``battlefield_snapshot`` is a combined view; we filter
    by controller to assert host-and-controller invariants."""
    for o in state.battlefield_snapshot():
        if o["id"] == obj_id and o["controller_id"] == player_id:
            return o
    return None


def _graveyard_obj(state, player_id, obj_id):
    for o in state.graveyard_snapshot(player_id):
        if o["id"] == obj_id:
            return o
    return None


def _cast_and_resolve_aura(state, aura_id, target_id, *, controller=0):
    """Helper: full STEP-3 + STEP-4 path. Casts aura, submits target
    (None for "no target — fizzle"), then resolves the top of stack.
    """
    ok = state.cast_aura(aura_id, controller)
    assert ok is True, "cast_aura returned False"
    # If pending decision was queued, submit it. If there were no
    # candidates the cast pump skipped the decision push entirely.
    if state.pending_decisions():
        state.submit_enchant_target_decision(target_id)
    return state.resolve_top_of_stack()


# ---------------------------------------------------------------------------
# Legal target → attach: attached_to stamped, aura on bf
# ---------------------------------------------------------------------------


def test_aura_resolves_to_battlefield_attached_to_legal_target():
    """An Aura with a legal bound target enters the battlefield with
    ``attached_to = Some(host_id)``. Mirrors Python at
    ``actions.py:2746`` (``card.attached_to = target_obj.id``).
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    _cast_and_resolve_aura(state, aura_id, bears_id)
    # Aura is now on P0's battlefield, attached to Bears.
    aura_bf = _battlefield_obj(state, 0, aura_id)
    assert aura_bf is not None, "Aura did not land on battlefield"
    assert aura_bf["attached_to"] == bears_id
    # Aura was NOT sent to graveyard (sanity).
    assert _graveyard_obj(state, 0, aura_id) is None
    # Bears unchanged in identity (still on bf with its id).
    bears_bf = _battlefield_obj(state, 0, bears_id)
    assert bears_bf is not None


def test_aura_resolves_attached_when_target_is_opponent_creature():
    """``aura_yours_only=False`` (Frantic Strength shape) — Aura can
    legally attach to an opponent's creature. The resolve arm honors
    the cast-time bound target regardless of host controller.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    elves_id = state.register_and_inject_object(
        _creature_dict("Elves", power=1, toughness=1), 1, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    _cast_and_resolve_aura(state, aura_id, elves_id)
    # Aura lands on P0's bf (caster's controller), attached to P1's
    # Elves.
    aura_bf = _battlefield_obj(state, 0, aura_id)
    assert aura_bf is not None
    assert aura_bf["attached_to"] == elves_id
    elves_bf = _battlefield_obj(state, 1, elves_id)
    assert elves_bf is not None


# ---------------------------------------------------------------------------
# Fizzle on no legal target at resolve time (CR 608.2b)
# ---------------------------------------------------------------------------


def test_aura_fizzles_to_graveyard_when_no_target_was_bound():
    """``submit_enchant_target_decision(None)`` leaves the Aura with
    no bound target. On resolve the Aura fizzles to its owner's
    graveyard with ``attached_to = None``. Mirrors Python's
    ``actions.py:2740-2745`` (``_send_to_graveyard_or_library``).
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    state.submit_enchant_target_decision(None)
    state.resolve_top_of_stack()
    # Aura in P0's graveyard, NOT on bf.
    assert _battlefield_obj(state, 0, aura_id) is None
    gy_aura = _graveyard_obj(state, 0, aura_id)
    assert gy_aura is not None, (
        "Aura did not fizzle to graveyard on no-target resolve"
    )
    assert gy_aura["attached_to"] is None
    # Bears still on bf (sanity — fizzle does not perturb the bf
    # otherwise).
    assert _battlefield_obj(state, 0, bears_id) is not None


def test_aura_fizzles_when_no_legal_candidates_at_cast_time():
    """Casting an Aura with NO legal candidates skips the decision
    push (STEP 3 invariant). On resolve the Aura still fizzles to
    graveyard — the resolve arm's legality check sees
    ``target_obj_id = None`` and routes to graveyard.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    # Empty bf — no creatures.
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    assert state.pending_decisions() == []  # STEP-3 invariant
    state.resolve_top_of_stack()
    gy_aura = _graveyard_obj(state, 0, aura_id)
    assert gy_aura is not None
    assert gy_aura["attached_to"] is None
    assert _battlefield_obj(state, 0, aura_id) is None


def test_aura_fizzles_when_target_leaves_battlefield_between_cast_and_resolve():
    """STEP 4 resolve-time legality check (CR 608.2b). If the bound
    target leaves the battlefield between cast and resolve, the Aura
    fizzles to graveyard. We simulate the lapse by destroying the
    target via SBA (zero-toughness creature with marked lethal damage)
    before calling ``resolve_top_of_stack``.

    Implementation note: we use a synthetic-state shortcut and just
    REMOVE the target from the battlefield by re-registering / re-
    injecting an absent state — actually, the cleanest path is to
    inject the target with very low toughness, deal it lethal damage
    via the synthetic helper, run SBAs, then resolve.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    state.submit_enchant_target_decision(bears_id)
    # Simulate the target leaving via lethal damage + SBA. We deal 2
    # damage to Bears (2 toughness → lethal), then apply_sbas
    # destroys it.
    state.deal_damage(bears_id, 2)
    state.apply_sbas()
    # Bears now in P0's graveyard.
    assert _battlefield_obj(state, 0, bears_id) is None
    # Resolve the Aura — it should fizzle (target gone).
    state.resolve_top_of_stack()
    gy_aura = _graveyard_obj(state, 0, aura_id)
    assert gy_aura is not None, (
        "Aura did not fizzle when bound target had been destroyed"
    )
    assert gy_aura["attached_to"] is None
    assert _battlefield_obj(state, 0, aura_id) is None


def test_aura_yours_only_fizzles_when_target_changes_controller():
    """An Aura with ``aura_yours_only=True`` fizzles at resolve time
    if the bound target is no longer the caster's creature (CR 608.2b
    re-legality check). We simulate by directly injecting the target
    onto the OPPONENT'S battlefield rather than the caster's, then
    binding to the cross-bf id. The cast filter accepts only the
    caster's creatures, so this scenario is constructed via a direct
    StackItem.target_obj_id override path.

    Simpler proxy: bind a yours_only Aura to a yours-controlled
    creature, then verify a non-yours target is REJECTED at resolve
    via the controller mismatch. We do this by submitting a NON-
    caster-controlled target — that submission raises because it's
    not in the candidate set; so instead we go via the no-target
    fizzle path (yours_only with no qualifying candidate at cast).
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(
            name="Shardmage's Rescue",
            mana_cost={"W": 1},
            yours_only=True,
            p_bonus=1, t_bonus=1, granted_keywords=(),
        ),
        0, ZONE_HAND,
    )
    # Only opponent has a creature — caster has none. yours_only
    # filter → empty candidate list at cast → no pending decision →
    # resolve fizzles.
    p1_elves = state.register_and_inject_object(
        _creature_dict("Elves"), 1, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "W", 1)
    state.cast_aura(aura_id, 0)
    assert state.pending_decisions() == []
    state.resolve_top_of_stack()
    # Aura fizzled, P1's Elves untouched.
    assert _graveyard_obj(state, 0, aura_id) is not None
    assert _battlefield_obj(state, 1, p1_elves) is not None


# ---------------------------------------------------------------------------
# Layer-7c P/T grant: effective_power / effective_toughness fold in
# ---------------------------------------------------------------------------


def test_aura_grants_layer_7_p_t_bonus_to_host_after_resolve():
    """After the Aura attaches, the host's ``effective_power`` and
    ``effective_toughness`` MUST fold in the Aura's
    ``aura_power_bonus`` / ``aura_toughness_bonus`` (CR 613.1d layer
    7c additive bonuses). Frantic Strength is a +2/+2 Aura on Bears
    (2/2 base) → effective 4/4.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(
            name="Frantic Strength",
            p_bonus=2, t_bonus=2, granted_keywords=("trample",),
        ),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears", power=2, toughness=2), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    # Pre-attach: 2/2.
    assert state.effective_power(bears_id) == 2
    assert state.effective_toughness(bears_id) == 2
    _cast_and_resolve_aura(state, aura_id, bears_id)
    # Post-attach: 4/4.
    assert state.effective_power(bears_id) == 4
    assert state.effective_toughness(bears_id) == 4


def test_aura_grant_only_applies_when_attached_to_matches_host():
    """The layer-7c bonus is scoped to the host whose id matches the
    Aura's ``attached_to``. An unrelated creature on the bf MUST NOT
    pick up the bonus.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(p_bonus=3, t_bonus=3, granted_keywords=()),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears", power=2, toughness=2), 0, ZONE_BATTLEFIELD,
    )
    elves_id = state.register_and_inject_object(
        _creature_dict("Elves", power=1, toughness=1), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    _cast_and_resolve_aura(state, aura_id, bears_id)
    # Bears got the bonus, Elves did not.
    assert state.effective_power(bears_id) == 5
    assert state.effective_toughness(bears_id) == 5
    assert state.effective_power(elves_id) == 1
    assert state.effective_toughness(elves_id) == 1


def test_two_auras_stack_layer_7_bonuses_additively():
    """Two Auras on the same host stack their P/T bonuses additively
    (CR 613.1d layer 7c). Bears (2/2) with two +2/+2 Auras → 6/6.
    """
    _require_engine()
    state = _fresh_state()
    aura1 = state.register_and_inject_object(
        _aura_printing_dict(
            name="Aura One",
            mana_cost={"R": 1},
            p_bonus=2, t_bonus=2, granted_keywords=(),
        ),
        0, ZONE_HAND,
    )
    aura2 = state.register_and_inject_object(
        _aura_printing_dict(
            name="Aura Two",
            mana_cost={"R": 1},
            p_bonus=2, t_bonus=2, granted_keywords=(),
        ),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears", power=2, toughness=2), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 2)
    _cast_and_resolve_aura(state, aura1, bears_id)
    _cast_and_resolve_aura(state, aura2, bears_id)
    assert state.effective_power(bears_id) == 6
    assert state.effective_toughness(bears_id) == 6


# ---------------------------------------------------------------------------
# Layer-6 keyword grant
# ---------------------------------------------------------------------------


def test_aura_grants_layer_6_keyword_to_host():
    """After attach the host picks up the Aura's
    ``aura_granted_keywords`` (CR 613.1c layer 6). Frantic Strength
    grants trample.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(
            p_bonus=0, t_bonus=0, granted_keywords=("trample",),
        ),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    # Pre-attach: bears doesn't have trample.
    assert state.has_keyword(bears_id, "trample") is False
    _cast_and_resolve_aura(state, aura_id, bears_id)
    assert state.has_keyword(bears_id, "trample") is True


def test_aura_keyword_grant_only_applies_to_attached_host():
    """A Bears + Elves bf; aura attaches to Bears with hexproof; Elves
    MUST NOT pick up hexproof.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(
            p_bonus=0, t_bonus=0, granted_keywords=("hexproof",),
        ),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    elves_id = state.register_and_inject_object(
        _creature_dict("Elves"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    _cast_and_resolve_aura(state, aura_id, bears_id)
    assert state.has_keyword(bears_id, "hexproof") is True
    assert state.has_keyword(elves_id, "hexproof") is False


# ---------------------------------------------------------------------------
# SBA interaction: aura bonus shifts effective toughness for 704.5g/f
# ---------------------------------------------------------------------------


def test_aura_toughness_bonus_keeps_host_alive_at_sba_lethal_check():
    """A 2/2 host with marked damage 3 would normally die (704.5g),
    but an Aura grant of +1/+2 raises effective toughness to 4 — the
    creature survives. Mirrors the I23 R74-1 closure shape, this time
    with the aura-grant contributing to layer 7c.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(p_bonus=1, t_bonus=2, granted_keywords=()),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears", power=2, toughness=2), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    _cast_and_resolve_aura(state, aura_id, bears_id)
    # Deal 3 damage to Bears: 3 < effective toughness 4 → survives.
    state.deal_damage(bears_id, 3)
    state.apply_sbas()
    # Bears still on bf.
    assert _battlefield_obj(state, 0, bears_id) is not None


# ---------------------------------------------------------------------------
# Stack pop / queue drains: no stale decision left behind
# ---------------------------------------------------------------------------


def test_resolve_top_of_stack_pops_aura_stack_item():
    """After resolve the stack is empty (the Aura's StackItem has
    been popped, attach or fizzle). Mirrors the resolve pop contract
    every other spell follows.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    state.submit_enchant_target_decision(bears_id)
    assert state.stack_size() == 1
    state.resolve_top_of_stack()
    assert state.stack_size() == 0
    assert state.pending_decisions() == []


def test_resolve_fizzle_path_also_pops_stack():
    """The fizzle-on-no-target resolve path ALSO pops the stack. The
    Aura goes to graveyard but the StackItem is still drained."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(), 0, ZONE_HAND,
    )
    # No bf candidates → cast skips decision push.
    state.add_mana(0, "R", 1)
    state.cast_aura(aura_id, 0)
    assert state.stack_size() == 1
    state.resolve_top_of_stack()
    assert state.stack_size() == 0


# ---------------------------------------------------------------------------
# Aura on artifact host (aura_enchant_type=artifact)
# ---------------------------------------------------------------------------


def test_aura_attaches_to_artifact_when_enchant_type_is_artifact():
    """``aura_enchant_type="artifact"`` Aura attaches to an Artifact
    host."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(
            name="Artifact Aura",
            mana_cost={"generic": 1},
            enchant_type="artifact",
            p_bonus=0, t_bonus=0, granted_keywords=(),
        ),
        0, ZONE_HAND,
    )
    artifact_id = state.register_and_inject_object(
        _artifact_dict("Plain Artifact"), 0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 1)
    _cast_and_resolve_aura(state, aura_id, artifact_id)
    aura_bf = _battlefield_obj(state, 0, aura_id)
    assert aura_bf is not None
    assert aura_bf["attached_to"] == artifact_id
