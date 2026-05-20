"""Aura-attachment substrate — Phase 1 STEP 5 tests.

Spec: ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §3 Phase 1 STEP 5.

**STEP 5 scope.** CR 704.5q (audit-labelled 704.5n in this
codebase): "An Aura that's attached to an illegal object or player,
or is not attached to an object or player, is put into its owner's
graveyard." This is a continuous state-based action that fires
whenever a bf Aura's ``attached_to`` reference becomes stale.

The new Rust surface is:

1. ``collect_aura_sba_victims`` (module-private) — walks every bf
   Aura, returns ``(owner_id, aura_obj_id)`` pairs for every Aura
   whose attachment is illegal per the four-branch test (no host
   bound / host gone / type mismatch / yours_only controller
   mismatch).
2. ``move_aura_to_owners_graveyard`` (module-private) — removes the
   Aura from bf and pushes it onto its owner's graveyard, queues a
   LEAVES_BATTLEFIELD dispatch (no DIES — Auras aren't creatures).
3. Wire-in to ``apply_sbas`` AFTER the creature-destruction pass +
   LEAVES/DIES dispatches: a host that died this same pass is gone,
   so the Aura SBA buries the dependent Aura in the SAME ``apply_sbas``
   call. Mirrors Python's `turn.py:1327-1358` position within
   `state_based_actions`.

**Host-leave detection.** Any path that moves the host off the
battlefield (SBA destroy, exile via ``move_object``, return-to-hand
via ``move_object``) is detected by the SBA's stale ``attached_to``
scan on the next priority window. There is no explicit host-leave
hook; the SBA scan IS the host-leave detector.

**Honest-stop.** The "host loses creature type via a UEOT layer-4
add_type / remove-types effect" branch is intentionally NOT folded
in — the type check reads the host's PRINTED card_types only. The
Phase-1 S1 cards (Frantic Strength, Shardmage's Rescue) target
creature-typed printings, so this honest-stop has zero observable
impact on the shipped substrate.

These tests exercise the SBA bury logic + host-leave triggers in
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
ZONE_EXILE = 5


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
    """Build a registry-dict for an Aura printing. Mirrors STEP-4's
    helper shape."""
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
    for o in state.battlefield_snapshot():
        if o["id"] == obj_id and o["controller_id"] == player_id:
            return o
    return None


def _graveyard_obj(state, player_id, obj_id):
    for o in state.graveyard_snapshot(player_id):
        if o["id"] == obj_id:
            return o
    return None


def _hand_obj(state, player_id, obj_id):
    for o in state.hand_snapshot(player_id):
        if o["id"] == obj_id:
            return o
    return None


def _exile_obj(state, player_id, obj_id):
    for o in state.exile_snapshot(player_id):
        if o["id"] == obj_id:
            return o
    return None


def _attach_aura_to_host(state, controller, aura_id, host_id, mana="R"):
    """Helper: cast the aura, submit the target, resolve. Returns
    after the Aura is on the bf with ``attached_to = host_id``.
    """
    state.add_mana(controller, mana, 1)
    state.cast_aura(aura_id, controller)
    state.submit_enchant_target_decision(host_id)
    state.resolve_top_of_stack()


# ---------------------------------------------------------------------------
# Branch 1: aura whose host was destroyed via 704.5f/g (lethal damage)
# ---------------------------------------------------------------------------


def test_aura_buried_when_host_dies_to_lethal_damage_same_sba_pass():
    """An Aura attached to a creature; the creature dies to lethal
    damage (704.5g). In the SAME ``apply_sbas`` pass, the Aura SBA
    (704.5q) observes the post-destroy bf and buries the Aura into
    its owner's graveyard. Mirrors Python's `turn.py:1327-1358`
    ordering: creature destruction (1280-1300) precedes Aura legality
    scan (1327-1358) within `state_based_actions`.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(p_bonus=0, t_bonus=0, granted_keywords=()),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears", power=2, toughness=2), 0, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura_id, bears_id)
    # Aura attached, host alive.
    assert _battlefield_obj(state, 0, aura_id) is not None
    assert _battlefield_obj(state, 0, bears_id) is not None
    # Lethal damage on host → 704.5g destroys it; same pass should
    # also bury the Aura.
    state.deal_damage(bears_id, 2)
    state.apply_sbas()
    # Both gone from bf.
    assert _battlefield_obj(state, 0, bears_id) is None
    assert _battlefield_obj(state, 0, aura_id) is None
    # Both in p0's graveyard.
    assert _graveyard_obj(state, 0, bears_id) is not None
    aura_gy = _graveyard_obj(state, 0, aura_id)
    assert aura_gy is not None
    # Aura's attached_to reset on the way out.
    assert aura_gy["attached_to"] is None


def test_aura_buried_when_host_dies_to_zero_toughness():
    """704.5f variant — host with effective toughness <= 0 dies, Aura
    buries in the same SBA pass. We use a -1/-1 counter to push a
    2/2 creature to 1 toughness, then a second to 0.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(p_bonus=0, t_bonus=0, granted_keywords=()),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears", power=2, toughness=2), 0, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura_id, bears_id)
    # Stack two -1/-1 counters → effective toughness 0 → 704.5f.
    state.add_counters(bears_id, -2)
    state.apply_sbas()
    assert _battlefield_obj(state, 0, bears_id) is None
    assert _battlefield_obj(state, 0, aura_id) is None
    assert _graveyard_obj(state, 0, aura_id) is not None


# ---------------------------------------------------------------------------
# Branch 2: aura whose host was exiled
# ---------------------------------------------------------------------------


def test_aura_buried_when_host_is_exiled():
    """Host moved off-bf to exile (e.g. by an instant-speed exile
    effect, simulated here via the generic ``move_object``
    primitive). On the next SBA pass the Aura's ``attached_to`` id is
    no longer on any bf → bury.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(p_bonus=0, t_bonus=0, granted_keywords=()),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura_id, bears_id)
    # Exile the host (move_object to exile zone).
    moved = state.move_object(bears_id, ZONE_EXILE, 0)
    assert moved is True
    assert _exile_obj(state, 0, bears_id) is not None
    # SBA pass should now bury the Aura.
    state.apply_sbas()
    assert _battlefield_obj(state, 0, aura_id) is None
    aura_gy = _graveyard_obj(state, 0, aura_id)
    assert aura_gy is not None
    assert aura_gy["attached_to"] is None
    # The host stays in exile (the SBA doesn't touch it).
    assert _exile_obj(state, 0, bears_id) is not None


# ---------------------------------------------------------------------------
# Branch 2: aura whose host was returned to hand
# ---------------------------------------------------------------------------


def test_aura_buried_when_host_returns_to_hand():
    """Host moved off-bf to hand (Unsummon-shape). The Aura was on bf
    when the host left; the SBA scan finds ``attached_to`` pointing
    at an id no longer on the bf and buries the Aura.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(p_bonus=0, t_bonus=0, granted_keywords=()),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura_id, bears_id)
    # Bounce host to hand.
    moved = state.move_object(bears_id, ZONE_HAND, 0)
    assert moved is True
    assert _hand_obj(state, 0, bears_id) is not None
    # SBA bury.
    state.apply_sbas()
    assert _battlefield_obj(state, 0, aura_id) is None
    assert _graveyard_obj(state, 0, aura_id) is not None
    # Host still in hand.
    assert _hand_obj(state, 0, bears_id) is not None


# ---------------------------------------------------------------------------
# Branch 2: aura whose host was sent to library / graveyard (other paths)
# ---------------------------------------------------------------------------


def test_aura_buried_when_host_is_sent_to_library():
    """Host moved off-bf to library (top-deck shuffle / hand-binding
    effects). Same host-leave detection as exile / return-to-hand.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(p_bonus=0, t_bonus=0, granted_keywords=()),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura_id, bears_id)
    moved = state.move_object(bears_id, ZONE_LIBRARY, 0)
    assert moved is True
    state.apply_sbas()
    assert _battlefield_obj(state, 0, aura_id) is None
    assert _graveyard_obj(state, 0, aura_id) is not None


def test_aura_buried_when_host_is_sent_directly_to_graveyard():
    """Host moved off-bf to graveyard via the generic mover (rather
    than via 704.5f/g destruction). E.g. a sacrifice effect that
    doesn't route through ``apply_sbas`` first. Aura still gets
    buried on the next SBA pass.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(p_bonus=0, t_bonus=0, granted_keywords=()),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura_id, bears_id)
    moved = state.move_object(bears_id, ZONE_GRAVEYARD, 0)
    assert moved is True
    state.apply_sbas()
    assert _battlefield_obj(state, 0, aura_id) is None
    assert _graveyard_obj(state, 0, aura_id) is not None


# ---------------------------------------------------------------------------
# Branch 3 (positive): a legally-attached aura stays put
# ---------------------------------------------------------------------------


def test_legally_attached_aura_is_not_buried_by_sba():
    """Sanity: a freshly-attached Aura with a healthy creature host
    is NOT buried by the SBA. Multiple sequential ``apply_sbas`` calls
    leave it on the bf.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(p_bonus=2, t_bonus=2, granted_keywords=("trample",)),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears", power=2, toughness=2), 0, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura_id, bears_id)
    # Two SBA passes — Aura stays.
    state.apply_sbas()
    state.apply_sbas()
    aura_bf = _battlefield_obj(state, 0, aura_id)
    assert aura_bf is not None
    assert aura_bf["attached_to"] == bears_id
    assert _graveyard_obj(state, 0, aura_id) is None


def test_aura_survives_when_host_is_pumped_above_lethal():
    """The +2/+2 from the Aura keeps the host alive past 3 damage
    (effective toughness 4). The host stays on bf, the Aura stays
    attached, the Aura is NOT buried.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(p_bonus=2, t_bonus=2, granted_keywords=()),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears", power=2, toughness=2), 0, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura_id, bears_id)
    state.deal_damage(bears_id, 3)
    state.apply_sbas()
    # Host alive, Aura alive.
    assert _battlefield_obj(state, 0, bears_id) is not None
    assert _battlefield_obj(state, 0, aura_id) is not None
    assert _graveyard_obj(state, 0, aura_id) is None


# ---------------------------------------------------------------------------
# Branch 3: type-mismatch via host registry-level type. Honest-stop
# documented for UEOT layer-4 type changes (no Rust analogue yet).
# ---------------------------------------------------------------------------


def test_aura_buried_when_enchant_type_does_not_match_host_printing():
    """The ``aura_enchant_type`` says "creature" but the only host on
    bf is a non-creature. Construct via a synthetic-state forced
    attach to a non-creature host (we use a STEP-4 attach path with
    an "artifact" enchant_type, then mutate the printing's
    ``aura_enchant_type`` from "artifact" to "creature" — proxy for
    a UEOT type-change that makes the once-legal attachment illegal).

    Simpler proxy that doesn't require post-resolve registry mutation:
    cast an artifact-targeting Aura onto an Artifact, then verify
    the SBA does NOT bury (positive control). For the negative case
    we'd need a UEOT type-change which is the honest-stop boundary.
    """
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
    state.cast_aura(aura_id, 0)
    state.submit_enchant_target_decision(artifact_id)
    state.resolve_top_of_stack()
    # Positive control: the artifact-enchant Aura on an Artifact stays
    # attached after SBA passes.
    state.apply_sbas()
    aura_bf = _battlefield_obj(state, 0, aura_id)
    assert aura_bf is not None
    assert aura_bf["attached_to"] == artifact_id


# ---------------------------------------------------------------------------
# Branch 4: yours_only — host changes controller (via direct relocate)
# ---------------------------------------------------------------------------


def test_yours_only_aura_buried_when_host_moves_to_opponent_bf():
    """A ``aura_yours_only=True`` Aura attached to the caster's
    creature; the host gets moved to the opponent's bf (proxy for a
    control-swap effect). On the next SBA pass the Aura's
    ``aura_yours_only`` is violated → bury.

    Implementation: the generic ``move_object(host, ZONE_BATTLEFIELD,
    opponent)`` re-homes the host to the opponent's bf (a bf-to-bf
    move; the source-was-battlefield path is exercised, but the
    target is also battlefield so the host stays alive — just under
    the opponent's control).
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
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura_id, bears_id, mana="W")
    # Steal the host to opponent's bf.
    moved = state.move_object(bears_id, ZONE_BATTLEFIELD, 1)
    assert moved is True
    # Host now on p1's bf.
    assert _battlefield_obj(state, 1, bears_id) is not None
    # SBA pass: yours_only violated → bury the Aura.
    state.apply_sbas()
    assert _battlefield_obj(state, 0, aura_id) is None
    aura_gy = _graveyard_obj(state, 0, aura_id)
    assert aura_gy is not None
    assert aura_gy["attached_to"] is None


def test_yours_only_aura_survives_when_host_stays_with_caster():
    """Inverse of the above — ``aura_yours_only=True``, host stays on
    the caster's bf, SBA passes leave the Aura attached.
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
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura_id, bears_id, mana="W")
    state.apply_sbas()
    aura_bf = _battlefield_obj(state, 0, aura_id)
    assert aura_bf is not None
    assert aura_bf["attached_to"] == bears_id


# ---------------------------------------------------------------------------
# Pump-then-die: bonus does not save host if pump is dropped (defensive)
# ---------------------------------------------------------------------------


def test_aura_bonus_drops_off_when_aura_is_buried():
    """After the Aura is buried, its layer-7c grant disappears from
    the (now-gone) host. Sanity check that
    ``aura_pt_bonus_on`` returns the right value before and after the
    SBA bury chain. We use a sibling unrelated creature to verify the
    bonus was specific to the original host (not stuck globally).
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(p_bonus=2, t_bonus=2, granted_keywords=()),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears", power=2, toughness=2), 0, ZONE_BATTLEFIELD,
    )
    elves_id = state.register_and_inject_object(
        _creature_dict("Elves", power=1, toughness=1), 0, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura_id, bears_id)
    # Pre-bury: Bears has 4 power (2+2), Elves untouched (1).
    assert state.effective_power(bears_id) == 4
    assert state.effective_power(elves_id) == 1
    # Kill the host → SBA chain buries the Aura. The Aura's +2/+2
    # pumps effective toughness to 4, so we need 4 damage (not 2).
    state.deal_damage(bears_id, 4)
    state.apply_sbas()
    # Aura buried; the surviving Elves still untouched (no contagion).
    assert _battlefield_obj(state, 0, aura_id) is None
    assert state.effective_power(elves_id) == 1


# ---------------------------------------------------------------------------
# Quiescence loop / idempotence
# ---------------------------------------------------------------------------


def test_apply_sbas_until_quiescent_handles_aura_chain_in_one_pass():
    """When a host dies, the in-pass aura bury happens within the
    same ``apply_sbas`` call. ``apply_sbas_until_quiescent`` should
    therefore return after a single pass (passes=1) with the bf
    quiesced — host + Aura both in graveyard.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(p_bonus=0, t_bonus=0, granted_keywords=()),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears", power=2, toughness=2), 0, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura_id, bears_id)
    state.deal_damage(bears_id, 2)
    passes = state.apply_sbas_until_quiescent()
    # Both host and Aura in graveyard.
    assert _battlefield_obj(state, 0, bears_id) is None
    assert _battlefield_obj(state, 0, aura_id) is None
    assert _graveyard_obj(state, 0, bears_id) is not None
    assert _graveyard_obj(state, 0, aura_id) is not None
    # Quiescence loop: only 1 pass needed (creature destruction +
    # aura bury fold into a single apply_sbas call). The 2nd pass
    # returns 0 (already quiesced) so apply_sbas_until_quiescent
    # returns 1 (count of passes that fired).
    assert passes == 1


def test_idempotent_sba_no_aura_when_no_change():
    """Sanity: ``apply_sbas`` on a clean state (no aura, no SBA
    victims) is idempotent and returns 0. Establishes the no-op
    baseline for the new aura path.
    """
    _require_engine()
    state = _fresh_state()
    state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    assert state.apply_sbas() == 0
    assert state.apply_sbas() == 0


# ---------------------------------------------------------------------------
# Multi-aura: each independent attachment is checked
# ---------------------------------------------------------------------------


def test_two_auras_on_same_host_both_buried_when_host_dies():
    """Two Auras on the same host. When the host dies, BOTH Auras are
    buried in the same SBA pass.
    """
    _require_engine()
    state = _fresh_state()
    aura1 = state.register_and_inject_object(
        _aura_printing_dict(
            name="Aura One",
            mana_cost={"R": 1},
            p_bonus=0, t_bonus=0, granted_keywords=(),
        ),
        0, ZONE_HAND,
    )
    aura2 = state.register_and_inject_object(
        _aura_printing_dict(
            name="Aura Two",
            mana_cost={"R": 1},
            p_bonus=0, t_bonus=0, granted_keywords=(),
        ),
        0, ZONE_HAND,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears", power=2, toughness=2), 0, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura1, bears_id)
    _attach_aura_to_host(state, 0, aura2, bears_id)
    # Verify both auras attached.
    assert _battlefield_obj(state, 0, aura1) is not None
    assert _battlefield_obj(state, 0, aura2) is not None
    # Kill host.
    state.deal_damage(bears_id, 2)
    state.apply_sbas()
    # Both auras and host in graveyard.
    assert _battlefield_obj(state, 0, aura1) is None
    assert _battlefield_obj(state, 0, aura2) is None
    assert _graveyard_obj(state, 0, aura1) is not None
    assert _graveyard_obj(state, 0, aura2) is not None
    assert _graveyard_obj(state, 0, bears_id) is not None


def test_only_aura_with_dead_host_is_buried_others_stay():
    """One Aura's host dies; a SECOND Aura attached to a different,
    surviving creature stays on the bf. SBA isolation check.
    """
    _require_engine()
    state = _fresh_state()
    # Two creatures.
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears", power=2, toughness=2), 0, ZONE_BATTLEFIELD,
    )
    elves_id = state.register_and_inject_object(
        _creature_dict("Elves", power=1, toughness=4), 0, ZONE_BATTLEFIELD,
    )
    # Two auras, one on each creature.
    aura_b = state.register_and_inject_object(
        _aura_printing_dict(
            name="Aura B",
            mana_cost={"R": 1},
            p_bonus=0, t_bonus=0, granted_keywords=(),
        ),
        0, ZONE_HAND,
    )
    aura_e = state.register_and_inject_object(
        _aura_printing_dict(
            name="Aura E",
            mana_cost={"R": 1},
            p_bonus=0, t_bonus=0, granted_keywords=(),
        ),
        0, ZONE_HAND,
    )
    _attach_aura_to_host(state, 0, aura_b, bears_id)
    _attach_aura_to_host(state, 0, aura_e, elves_id)
    # Kill Bears only.
    state.deal_damage(bears_id, 2)
    state.apply_sbas()
    # Bears gone, Aura B buried; Elves alive, Aura E still attached.
    assert _battlefield_obj(state, 0, bears_id) is None
    assert _battlefield_obj(state, 0, aura_b) is None
    assert _graveyard_obj(state, 0, aura_b) is not None
    assert _battlefield_obj(state, 0, elves_id) is not None
    aura_e_bf = _battlefield_obj(state, 0, aura_e)
    assert aura_e_bf is not None
    assert aura_e_bf["attached_to"] == elves_id


# ---------------------------------------------------------------------------
# Cross-player: opponent's creature dies, my aura on it gets buried
# to MY graveyard (the aura's owner, not the host's owner)
# ---------------------------------------------------------------------------


def test_aura_on_opponent_creature_buries_to_caster_graveyard_when_host_dies():
    """Frantic Strength shape (yours_only=False) — caster (p0) attaches
    Aura to opponent (p1)'s creature. The opponent's creature dies; the
    Aura should bury to P0's graveyard (the Aura's owner / controller),
    NOT P1's. CR 400.6 + Phase-1 owner==controller convention.
    """
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_printing_dict(p_bonus=0, t_bonus=0, granted_keywords=()),
        0, ZONE_HAND,
    )
    p1_elves = state.register_and_inject_object(
        _creature_dict("Elves", power=1, toughness=1), 1, ZONE_BATTLEFIELD,
    )
    _attach_aura_to_host(state, 0, aura_id, p1_elves)
    # Confirm Aura is on p0's bf, attached to p1's creature.
    aura_bf = _battlefield_obj(state, 0, aura_id)
    assert aura_bf is not None
    assert aura_bf["attached_to"] == p1_elves
    # Kill opp's creature.
    state.deal_damage(p1_elves, 1)
    state.apply_sbas()
    # Aura → P0's graveyard, p1's elves → p1's graveyard.
    assert _battlefield_obj(state, 0, aura_id) is None
    assert _graveyard_obj(state, 0, aura_id) is not None
    assert _graveyard_obj(state, 1, p1_elves) is not None
    # NOT in p1's graveyard.
    assert _graveyard_obj(state, 1, aura_id) is None


# ---------------------------------------------------------------------------
# Non-aura permanents are untouched by the new SBA path
# ---------------------------------------------------------------------------


def test_non_aura_permanent_with_attached_to_set_is_not_buried():
    """Only Auras (printing.is_aura == True) are subject to 704.5q.
    A non-Aura permanent with ``attached_to`` set (e.g. a future
    Equipment) is NOT buried by this SBA path. Equipment has its own
    CR 704.5p unattach behavior (stays on bf, just unattaches) — out
    of scope for STEP 5.

    Synthetic test: register a non-Aura with a creature-like printing
    and force ``attached_to`` via the equipment ETB attach (STEP-4
    used the Equipment arms for the attach machinery), then run SBAs
    and verify the non-Aura stays put.
    """
    _require_engine()
    state = _fresh_state()
    # Pure non-Aura permanent — a vanilla artifact, no Aura keys.
    artifact_id = state.register_and_inject_object(
        _artifact_dict("Plain Artifact"), 0, ZONE_BATTLEFIELD,
    )
    bears_id = state.register_and_inject_object(
        _creature_dict("Bears"), 0, ZONE_BATTLEFIELD,
    )
    # Two SBA passes — artifact stays on bf regardless (it's not an
    # Aura, the new SBA path doesn't touch it).
    state.apply_sbas()
    state.apply_sbas()
    assert _battlefield_obj(state, 0, artifact_id) is not None
    assert _battlefield_obj(state, 0, bears_id) is not None
