"""Aura-attachment substrate — Phase 2 S2.5 (layer-7b set-base-PT
reader fold).

Spec: ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §3 Phase 2 (S2.5
Lignify-shape slice — the reader fold that lights up the
``aura_set_base_pt`` field plumbed by Phase 2 S2).

**Scope shipped in this slice (round-79+, 2026-05-20).**

Phase 2 S2 plumbed the ``aura_set_base_pt`` (Option<(i16, i16)>)
field through CardDef + bridge + Rust storage + bidir round-trip,
but the Rust reader fold for layer-7b set-base-PT was honest-stopped
("no admitted carrier today uses it"). This slice lights up the
reader fold so a host enchanted by a Lignify-shape Aura ("Enchanted
creature is a 0/4 Treefolk") observes the set-base values as its
effective base power / toughness — with UEOT additive +/- bonuses
(CR 613 layer 7c) and aura ±P/±T grants stacking on top.

**Reader sites lit.**

* ``battlefield_creature_power`` / ``battlefield_creature_toughness``
  in ``state_ops_combat.rs`` (the combat-side effective-P/T
  computation surfaced through ``state.effective_power(id)`` /
  ``state.effective_toughness(id)``).
* ``collect_sba_victims`` + ``is_lethal`` in ``state_ops_sba.rs``
  (the SBA-side base-toughness recipe — load-bearing for the
  704.5f zero-toughness and 704.5g lethal-damage state-based
  actions; a Lignified 4/4 → 0/4 must NOT be destroyed by 704.5f
  even though the printed P/T was 4/4).

**Layer ordering** (mirroring CR 613.3b → 613.3c and Python's
``_compute_effective_pt``):

1. ``UeotModifier::SetBasePT`` (layer 7b, last-applied wins).
2. ``UeotModifier::BecomesLandCreature`` (layer 7b, manland-shape
   override).
3. **``aura_set_base_pt`` (layer 7b, this slice).**
4. ``dynamic_base_pt_pub`` (layer 7b CDA — Harmonious Grovestrider).
5. Printed base P/T.
Then layer 7c additive bonuses (UEOT pump + aura ±P/±T grants)
stack on top, then layer 7d counters fold.

**Honest-stops carried.**

* **Multi-Aura set-base interleaving.** When two set-base-PT Auras
  are attached to the same host CR 613.3b requires the latest by
  timestamp to win. The Rust GameObject does not carry an attach
  timestamp; the reader returns the FIRST attached set-base-PT Aura
  it encounters in the deterministic bf walk. No live admit set
  exercises the interleave today (Lignify isn't in the EoE pool;
  Phase 2 S2's bridge admit predicate still declines
  ``attached_sets_base_pt is not None`` carriers).
* **Lignify not bridge-admitted.** The reader fold is exercised
  here via synthetic registry-dict injection ONLY. The bridge
  admit predicate
  (``trajectory.py::_printing_is_bridge_simple_aura``) still
  declines Lignify-shape Auras — no live EoE deck stresses this
  slice. The substrate value is the readiness for a future
  cross-engine pool member, not the current admit count.
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


def _aura_set_base_pt_dict(
    name="Lignify",
    mana_cost=None,
    set_base_power=0,
    set_base_toughness=4,
    grants_lose_abilities=True,
    p_bonus=0,
    t_bonus=0,
    granted_keywords=(),
):
    """Build a registry-dict for a Lignify-shape Aura printing.

    Defaults match Lignify: 0/4 set-base + lose-all-abilities; no
    +P/+T rider. Callers pass overrides to vary the shape.
    """
    if mana_cost is None:
        mana_cost = {"generic": 1, "G": 1}
    d = {
        "name": name,
        "mana_cost": mana_cost,
        "card_types": ["Enchantment"],
        "subtypes": ["Aura"],
        "is_aura": True,
        "aura_enchant_type": "creature",
        "aura_set_base_pt": {
            "power": set_base_power,
            "toughness": set_base_toughness,
        },
    }
    if grants_lose_abilities:
        d["aura_grants_lose_abilities"] = True
    if p_bonus or t_bonus or granted_keywords:
        d["aura_equipment_bonuses"] = {
            "power_bonus": p_bonus,
            "toughness_bonus": t_bonus,
            "granted_keywords": list(granted_keywords),
        }
    return d


def _plain_aura_dict(
    name="Brawn",
    mana_cost=None,
    p_bonus=0,
    t_bonus=1,
    granted_keywords=(),
):
    """Build a registry-dict for an Aura that grants layer-7c +/- P/T
    only (no set-base, no lose-abilities) — composable with the
    set-base Aura in the multi-aura test."""
    if mana_cost is None:
        mana_cost = {"G": 1}
    d = {
        "name": name,
        "mana_cost": mana_cost,
        "card_types": ["Enchantment"],
        "subtypes": ["Aura"],
        "is_aura": True,
        "aura_enchant_type": "creature",
        "aura_equipment_bonuses": {
            "power_bonus": p_bonus,
            "toughness_bonus": t_bonus,
            "granted_keywords": list(granted_keywords),
        },
    }
    return d


def _creature_dict(name="Big Bear", power=4, toughness=4):
    return {
        "name": name,
        "mana_cost": {"generic": 2, "G": 1},
        "card_types": ["Creature"],
        "subtypes": ["Bear"],
        "power": power,
        "toughness": toughness,
    }


def _fresh_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _battlefield_obj(state, obj_id):
    for o in state.battlefield_snapshot():
        if o["id"] == obj_id:
            return o
    return None


def _cast_and_resolve_aura(state, aura_id, target_id, controller=0):
    """Helper: cast + submit-target + resolve."""
    ok = state.cast_aura(aura_id, controller)
    assert ok is True
    if state.pending_decisions():
        state.submit_enchant_target_decision(target_id)
    state.resolve_top_of_stack()


# ---------------------------------------------------------------------------
# Single set-base Aura: printed 4/4 + Lignify 0/4 → effective 0/4
# ---------------------------------------------------------------------------


def test_set_base_aura_overrides_host_printed_pt():
    """A 4/4 host enchanted by Lignify (set-base 0/4) reads as 0/4
    for effective P/T. The printed base 4/4 is REPLACED by the
    Aura's set-base 0/4 (CR 613.3b layer 7b)."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(), 0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    # Pre-attach: host reads its printed 4/4.
    assert state.effective_power(host_id) == 4
    assert state.effective_toughness(host_id) == 4
    state.add_mana(0, "C", 1)
    state.add_mana(0, "G", 1)
    _cast_and_resolve_aura(state, aura_id, host_id)
    # Post-attach: host reads the Aura's set-base 0/4.
    assert state.effective_power(host_id) == 0
    assert state.effective_toughness(host_id) == 4


def test_set_base_aura_scoped_to_attached_host_only():
    """The set-base-PT override applies only to the attached host.
    Another creature on the same battlefield reads its printed base."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(), 0, ZONE_HAND,
    )
    target_id = state.register_and_inject_object(
        _creature_dict("Target Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    bystander_id = state.register_and_inject_object(
        _creature_dict("Bystander Bear", power=3, toughness=3),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 1)
    state.add_mana(0, "G", 1)
    _cast_and_resolve_aura(state, aura_id, target_id)
    # Target: 0/4 (Lignified).
    assert state.effective_power(target_id) == 0
    assert state.effective_toughness(target_id) == 4
    # Bystander: untouched 3/3.
    assert state.effective_power(bystander_id) == 3
    assert state.effective_toughness(bystander_id) == 3


# ---------------------------------------------------------------------------
# Set-base + counters (layer 7d stacks on top of set-base)
# ---------------------------------------------------------------------------


def test_set_base_aura_composes_with_counters():
    """A Lignified host with a +1/+1 counter is 1/5 effective:
    set-base 0/4 (layer 7b) + +1/+1 counter (layer 7d). CR 613.3b
    → 613.3d ordering."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(), 0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    # Place a +1/+1 counter on the host BEFORE attaching the Aura
    # (the order doesn't matter — counters are layer 7d and apply
    # AFTER set-base regardless of attach timing).
    state.add_counters(host_id, 1)
    state.add_mana(0, "C", 1)
    state.add_mana(0, "G", 1)
    _cast_and_resolve_aura(state, aura_id, host_id)
    # set-base 0/4 + counter +1/+1 → 1/5.
    assert state.effective_power(host_id) == 1
    assert state.effective_toughness(host_id) == 5


# ---------------------------------------------------------------------------
# Set-base composes with a SECOND Aura's +/- P/T grant (layer 7c)
# ---------------------------------------------------------------------------


def test_set_base_aura_composes_with_own_pt_rider():
    """A single Aura that BOTH set-base-PTs AND grants layer-7c +/- P/T
    (a synthetic shape) composes: the set-base replaces the printed
    base, the same Aura's layer-7c rider adds on top. printed 4/4 +
    set-base 0/4 + +1/+1 rider → effective 1/5.

    This proves the within-Aura layer 7b → 7c ordering on the same
    source — matching Python's `_compute_effective_pt` which applies
    set-base (registry 7b) BEFORE folding in the per-permanent layer
    7c bonus."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            set_base_power=0, set_base_toughness=4,
            p_bonus=1, t_bonus=1,
        ),
        0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 1)
    state.add_mana(0, "G", 1)
    _cast_and_resolve_aura(state, aura_id, host_id)
    # set-base 0/4 + +1/+1 (same Aura's layer-7c) → 1/5.
    assert state.effective_power(host_id) == 1
    assert state.effective_toughness(host_id) == 5


def test_set_base_aura_composes_with_second_aura_pt_grant():
    """A Lignified host (set-base 0/4) ALSO enchanted by a +0/+1
    Aura is 0/5 effective: set-base 0/4 (layer 7b) + +0/+1 layer-7c
    aura grant. The two Auras compose without interfering."""
    _require_engine()
    state = _fresh_state()
    lignify_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(), 0, ZONE_HAND,
    )
    brawn_id = state.register_and_inject_object(
        _plain_aura_dict(
            name="Brawn", p_bonus=0, t_bonus=1,
        ),
        0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 1)
    state.add_mana(0, "G", 2)
    _cast_and_resolve_aura(state, lignify_id, host_id)
    # After Lignify only: 0/4.
    assert state.effective_power(host_id) == 0
    assert state.effective_toughness(host_id) == 4
    _cast_and_resolve_aura(state, brawn_id, host_id)
    # set-base 0/4 + +0/+1 → 0/5.
    assert state.effective_power(host_id) == 0
    assert state.effective_toughness(host_id) == 5


# ---------------------------------------------------------------------------
# Aura unattach restores host to its printed base
# ---------------------------------------------------------------------------


def test_set_base_aura_revert_when_aura_leaves_play():
    """After the set-base-PT Aura leaves play (host destroyed →
    Aura SBA-buried → host reborn), the host's effective P/T
    reverts to its printed base. Pin: the reader fold is purely
    state-derived (it walks the bf each call), so the moment no
    set-base-PT Aura is attached the override drops."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(), 0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 1)
    state.add_mana(0, "G", 1)
    _cast_and_resolve_aura(state, aura_id, host_id)
    assert state.effective_power(host_id) == 0
    assert state.effective_toughness(host_id) == 4
    # Bounce the host — the Aura SBA-buries with attached_to cleared.
    state.move_object(host_id, ZONE_HAND, 0)
    state.apply_sbas()
    # Bring the host back to bf — no Aura attached, printed P/T
    # returns.
    state.move_object(host_id, ZONE_BATTLEFIELD, 0)
    assert state.effective_power(host_id) == 4
    assert state.effective_toughness(host_id) == 4


# ---------------------------------------------------------------------------
# SBA lock-step: Lignified host survives lethal-against-printed damage
# ---------------------------------------------------------------------------


def test_set_base_aura_sba_lethal_check_uses_set_base():
    """A printed 4/4 Lignified to 0/4 with 3 marked damage survives
    apply_sbas (3 < effective toughness 4). The SBA's lethal-damage
    predicate must lock-step with the combat reader and read the
    set-base toughness, NOT the printed toughness."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(), 0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 1)
    state.add_mana(0, "G", 1)
    _cast_and_resolve_aura(state, aura_id, host_id)
    # Mark 3 damage on the host. Set-base toughness is 4 → not lethal.
    state.deal_damage(host_id, 3)
    state.apply_sbas()
    # Host still on the battlefield.
    assert _battlefield_obj(state, host_id) is not None, (
        "Lignified host (eff toughness 4) wrongly destroyed by 3 "
        "damage — SBA must use set-base toughness, not printed"
    )


def test_set_base_aura_sba_lethal_check_destroys_at_set_base_toughness():
    """A printed 4/4 Lignified to 0/4 with 4 marked damage IS
    destroyed (4 >= 4). Confirms the SBA's lock-step is bidirectional
    — the reduced set-base toughness 4 IS the lethal threshold, not
    the printed 4 (coincidentally same here; the next test pins the
    smaller-than-printed case)."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(), 0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 1)
    state.add_mana(0, "G", 1)
    _cast_and_resolve_aura(state, aura_id, host_id)
    state.deal_damage(host_id, 4)
    state.apply_sbas()
    # Host destroyed.
    assert _battlefield_obj(state, host_id) is None


def test_set_base_aura_sba_lethal_smaller_than_printed():
    """A printed 5/5 Lignified to 0/2 with 2 marked damage IS
    destroyed — set-base toughness 2 < printed 5 makes the SBA
    fire at lower damage than the printed value would. Pins the
    "set-base shrinks the lethal threshold" direction of the SBA
    lock-step."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            set_base_power=0, set_base_toughness=2,
        ),
        0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Bigger Bear", power=5, toughness=5),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 1)
    state.add_mana(0, "G", 1)
    _cast_and_resolve_aura(state, aura_id, host_id)
    # Pre-SBA: 0/2.
    assert state.effective_toughness(host_id) == 2
    state.deal_damage(host_id, 2)
    state.apply_sbas()
    assert _battlefield_obj(state, host_id) is None, (
        "Lignified host (eff toughness 2 < printed 5) wrongly "
        "survived 2 damage — SBA must use set-base, not printed"
    )


def test_set_base_aura_sba_zero_toughness_set_base_destroys():
    """A printed 4/4 hit with a 0/0 set-base Aura is destroyed by
    704.5f (0 effective toughness) on the next SBA pass, even
    without marked damage. Confirms the SBA's 704.5f check also
    locks onto set-base."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            set_base_power=0, set_base_toughness=0,
        ),
        0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 1)
    state.add_mana(0, "G", 1)
    _cast_and_resolve_aura(state, aura_id, host_id)
    state.apply_sbas()
    # The Aura itself buries with the host (Phase-1-STEP-5 bury path).
    assert _battlefield_obj(state, host_id) is None, (
        "Set-base 0/0 Aura did not destroy host via 704.5f"
    )


# ---------------------------------------------------------------------------
# Helper-level pin: aura_set_base_pt_on returns None when nothing attached
# ---------------------------------------------------------------------------


def test_set_base_reader_returns_printed_when_no_aura_attached():
    """A creature with no Aura attached reads its printed base — the
    set-base override fires ONLY while an Aura with the field is
    attached (back-compat invariant for every pre-S2.5 creature)."""
    _require_engine()
    state = _fresh_state()
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    # No Aura at all: printed 4/4.
    assert state.effective_power(host_id) == 4
    assert state.effective_toughness(host_id) == 4
    # A non-set-base Aura attached (a +0/+1 buff) leaves the
    # set-base reader returning None internally so the printed base
    # still wins: effective is 4 / (4 + 1) = 4/5, NOT some
    # set-base shape.
    buff_id = state.register_and_inject_object(
        _plain_aura_dict(name="Brawn", p_bonus=0, t_bonus=1),
        0, ZONE_HAND,
    )
    state.add_mana(0, "G", 1)
    _cast_and_resolve_aura(state, buff_id, host_id)
    assert state.effective_power(host_id) == 4
    assert state.effective_toughness(host_id) == 5


def test_set_base_aura_negative_power_supported():
    """The set-base override accepts a negative power (defensive — no
    printed Lignify-shape uses negative set-base today, but the
    field type is signed i16 and the reader passes it through)."""
    _require_engine()
    state = _fresh_state()
    aura_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            set_base_power=-1, set_base_toughness=1,
        ),
        0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 1)
    state.add_mana(0, "G", 1)
    _cast_and_resolve_aura(state, aura_id, host_id)
    # Power can read negative — Rust clamps to i16, displays via the
    # effective_power getter which preserves the sign.
    assert state.effective_power(host_id) == -1
    assert state.effective_toughness(host_id) == 1
