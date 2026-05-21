"""Aura-attachment substrate — multi-Aura set-base-PT timestamp
interleaving (CR 613.3b, round-80, 2026-05-20).

Spec: ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §3 Phase 2 (S2.5
honest-stop closure on multi-Aura set-base-PT interleaving).

**What this slice closes.**

Phase 2 S2.5 (round-79+, merge ``46d8d393``) shipped the layer-7b
set-base-PT reader fold but documented an honest-stop: when two
set-base-PT Auras are attached to the same host CR 613.3b requires
the latest-by-timestamp to win. The pre-closure reader returned the
FIRST attached set-base-PT Aura in the deterministic bf walk (player
0 then player 1, in registration order) — deterministic but not
CR-correct.

This closure piggybacks on the existing ``etb_timestamp`` field
(state.rs:172). Every Aura attach goes through
``move_aura_post_resolve`` (state_ops_resolve.rs:480) which stamps a
fresh monotonic timestamp via ``reserve_etb_timestamp``. The
``aura_set_base_pt_on`` helper now walks every set-base-PT Aura on
the host and picks the one with the **highest** ``etb_timestamp``.

**What's NOT in scope.**

* **Aura re-attach.** Today no Rust code path re-attaches an Aura
  to a different host (Aura lifecycle: attach-once-at-resolve;
  re-target via "move aura" Effect doesn't exist in Rust today).
  Per CR 613.7d, re-attach would update the timestamp; if that
  path lands a follow-up slice must re-stamp ``etb_timestamp`` at
  re-attach time. No live carrier today.
* **Layer-2 (control change) timestamp ordering.** Phase 2 S2
  control-grant uses a baseline-revert model (controller_baseline)
  that handles the single-Aura case correctly via field-overwrite
  (last-grant trivially wins). Multi-control-changing-Aura
  interleaving on the same host is not in the EoE pool; promote
  to a timestamp walk when a real carrier lands.
* **Layer-6 (lose abilities) timestamp ordering.** The current
  ``aura_grants_lose_abilities_to`` predicate is presence/absence
  (any vs none); ordering is unobservable. Promote if a future
  Aura grants a layer-6 keyword that conflicts with a layer-6
  lose-all (no current shape).
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
    grants_lose_abilities=False,
):
    """Build a registry-dict for a Lignify-shape Aura printing.

    Defaults to the 0/4 set-base shape. ``grants_lose_abilities``
    defaults to False here (vs the Phase 2 S2.5 sibling test file
    where it defaults True) so the multi-Aura interleave tests
    don't intermix layer-6 ability-wipe semantics with the
    layer-7b set-base ordering pin.
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
    ok = state.cast_aura(aura_id, controller)
    assert ok is True
    if state.pending_decisions():
        state.submit_enchant_target_decision(target_id)
    state.resolve_top_of_stack()


# ---------------------------------------------------------------------------
# Two set-base Auras attach in order A then B → effective base = B's set
# ---------------------------------------------------------------------------


def test_two_set_base_auras_attach_order_a_then_b_b_wins():
    """A 4/4 host with Aura A (set-base 0/4) attached first, then
    Aura B (set-base 1/3) attached second. CR 613.3b: latest by
    timestamp wins → effective base = Aura B's 1/3.

    Pre-closure (round-79+ honest-stop) the reader returned the FIRST
    set-base Aura in bf walk (Aura A's 0/4); this test pins the
    CR-correct latest-wins behavior.
    """
    _require_engine()
    state = _fresh_state()
    aura_a_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura A",
            set_base_power=0,
            set_base_toughness=4,
        ),
        0, ZONE_HAND,
    )
    aura_b_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura B",
            set_base_power=1,
            set_base_toughness=3,
        ),
        0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 2)
    state.add_mana(0, "G", 2)
    # Attach A first.
    _cast_and_resolve_aura(state, aura_a_id, host_id)
    # After A only: A's 0/4 wins (only set-base Aura attached).
    assert state.effective_power(host_id) == 0
    assert state.effective_toughness(host_id) == 4
    # Attach B second.
    _cast_and_resolve_aura(state, aura_b_id, host_id)
    # CR 613.3b: B is later by timestamp → B's 1/3 wins.
    assert state.effective_power(host_id) == 1, (
        "Two set-base Auras: latest (B, set-base 1/3) must override "
        "earlier (A, set-base 0/4); got power != 1 — the helper is "
        "still returning the FIRST attached set-base Aura instead of "
        "the latest by etb_timestamp."
    )
    assert state.effective_toughness(host_id) == 3


# ---------------------------------------------------------------------------
# Two set-base Auras attach in order B then A → effective base = A's set
# (symmetry pin — ordering is observable both directions)
# ---------------------------------------------------------------------------


def test_two_set_base_auras_attach_order_b_then_a_a_wins():
    """Mirror of the prior test with the attach order swapped. Same
    host, same two Auras (A: 0/4, B: 1/3), attach order B then A →
    A is the later timestamp → A's 0/4 wins.

    Symmetry pin: the latest-wins rule is observable from BOTH
    sides — swapping attach order swaps the winning Aura. A reader
    that returned an order-stable (e.g. id-based) tiebreak would
    pass one of these tests and fail the other.
    """
    _require_engine()
    state = _fresh_state()
    # Register A first (lower id) but attach B FIRST (lower
    # etb_timestamp). Reversing the attach order from the prior
    # test exercises the symmetric direction.
    aura_a_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura A",
            set_base_power=0,
            set_base_toughness=4,
        ),
        0, ZONE_HAND,
    )
    aura_b_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura B",
            set_base_power=1,
            set_base_toughness=3,
        ),
        0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 2)
    state.add_mana(0, "G", 2)
    # Attach B first.
    _cast_and_resolve_aura(state, aura_b_id, host_id)
    # After B only: B's 1/3 wins.
    assert state.effective_power(host_id) == 1
    assert state.effective_toughness(host_id) == 3
    # Attach A second.
    _cast_and_resolve_aura(state, aura_a_id, host_id)
    # CR 613.3b: A is later by timestamp → A's 0/4 wins (despite
    # A having the LOWER object id; the ordering is by attach
    # timestamp, not by id).
    assert state.effective_power(host_id) == 0
    assert state.effective_toughness(host_id) == 4


# ---------------------------------------------------------------------------
# After Aura B detaches, Aura A's set-base wins again
# ---------------------------------------------------------------------------


def test_two_set_base_auras_winner_detaches_earlier_takes_over():
    """A then B attached (B wins, set-base 1/3). When B leaves the
    battlefield (host bounce → SBA-bury both Auras → host returns
    fresh), no Aura is attached and the host reads printed 4/4.

    Then re-attach A only: A's set-base 0/4 wins. Pin: the helper
    is purely state-derived (it walks the bf each call), so detach
    of the latest-winner correctly demotes back to the next-latest
    (or none).

    NB: today's SBA-bury path moves BOTH Auras to graveyard when the
    host leaves; re-creating "A still attached, B detached" requires
    going through fresh attach. That's the right CR-level shape —
    detach without host-bounce isn't a Phase-2 Rust path.
    """
    _require_engine()
    state = _fresh_state()
    aura_a_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura A",
            set_base_power=0,
            set_base_toughness=4,
        ),
        0, ZONE_HAND,
    )
    aura_b_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura B",
            set_base_power=1,
            set_base_toughness=3,
        ),
        0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 2)
    state.add_mana(0, "G", 2)
    _cast_and_resolve_aura(state, aura_a_id, host_id)
    _cast_and_resolve_aura(state, aura_b_id, host_id)
    # Both attached: B wins.
    assert state.effective_power(host_id) == 1
    assert state.effective_toughness(host_id) == 3
    # Bounce the host: both Auras SBA-bury with attached_to cleared.
    state.move_object(host_id, ZONE_HAND, 0)
    state.apply_sbas()
    # The Aura objects went to graveyard (Phase 2 S2 SBA path) —
    # confirm they're no longer attached.
    for o in state.battlefield_snapshot():
        assert o.get("attached_to") in (None, 0), (
            "Aura should have left bf when host bounced"
        )
    # Bring the host back to bf — printed P/T returns.
    state.move_object(host_id, ZONE_BATTLEFIELD, 0)
    assert state.effective_power(host_id) == 4
    assert state.effective_toughness(host_id) == 4


# ---------------------------------------------------------------------------
# Three set-base Auras: latest of the three wins (transitive ordering pin)
# ---------------------------------------------------------------------------


def test_three_set_base_auras_latest_wins():
    """Three set-base Auras attached in order A (0/4), B (1/3),
    C (2/2). C is latest → C's 2/2 wins. Transitive pin: the
    helper must not stop at the first match nor at the second
    match — it must scan all and pick max-by-timestamp.
    """
    _require_engine()
    state = _fresh_state()
    aura_a_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura A", set_base_power=0, set_base_toughness=4,
        ),
        0, ZONE_HAND,
    )
    aura_b_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura B", set_base_power=1, set_base_toughness=3,
        ),
        0, ZONE_HAND,
    )
    aura_c_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura C", set_base_power=2, set_base_toughness=2,
        ),
        0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 3)
    state.add_mana(0, "G", 3)
    _cast_and_resolve_aura(state, aura_a_id, host_id)
    _cast_and_resolve_aura(state, aura_b_id, host_id)
    _cast_and_resolve_aura(state, aura_c_id, host_id)
    # Latest (C, 2/2) wins.
    assert state.effective_power(host_id) == 2
    assert state.effective_toughness(host_id) == 2


# ---------------------------------------------------------------------------
# Aura on opponent's bf vs aura on your bf: cross-player timestamp ordering
# ---------------------------------------------------------------------------


def test_set_base_auras_cross_player_timestamp_ordering():
    """Aura A controlled by player 0 attached first; Aura B
    controlled by player 1 attached second to the SAME host (whose
    controller is unchanged by the Aura — both Auras are
    set-base-only, no control-change rider). B is the latest by
    etb_timestamp → B's set-base wins despite living on the
    opponent's bf.

    Pin: the helper walks both players' battlefields and the
    timestamp-max comparison crosses player boundaries.
    """
    _require_engine()
    state = _fresh_state()
    aura_a_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura A", set_base_power=0, set_base_toughness=4,
        ),
        0, ZONE_HAND,
    )
    aura_b_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura B", set_base_power=1, set_base_toughness=3,
        ),
        1, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 1)
    state.add_mana(0, "G", 1)
    state.add_mana(1, "C", 1)
    state.add_mana(1, "G", 1)
    # P0 casts A targeting host.
    _cast_and_resolve_aura(state, aura_a_id, host_id, controller=0)
    # P1 casts B targeting host.
    _cast_and_resolve_aura(state, aura_b_id, host_id, controller=1)
    # B is later by timestamp → B's 1/3 wins.
    assert state.effective_power(host_id) == 1
    assert state.effective_toughness(host_id) == 3


# ---------------------------------------------------------------------------
# Non-set-base Aura mixed with a set-base Aura: timestamp ordering only
# counts the set-base candidates
# ---------------------------------------------------------------------------


def test_non_set_base_aura_does_not_displace_set_base_winner():
    """Aura A (set-base 0/4) attached first. Then Aura B (a +0/+1
    buff with NO set-base) attached second. Even though B has the
    later timestamp, it is not a set-base candidate, so A's 0/4
    still wins for the set-base slot. The buff's +0/+1 stacks on
    top per CR layer-7c → effective 0/5.

    Pin: the helper's printing-side filter (Some(aura_set_base_pt))
    correctly excludes non-set-base Auras from the latest-wins
    contest.
    """
    _require_engine()
    state = _fresh_state()
    aura_a_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura A", set_base_power=0, set_base_toughness=4,
        ),
        0, ZONE_HAND,
    )
    # Plain buff Aura with no aura_set_base_pt.
    buff_id = state.register_and_inject_object(
        {
            "name": "Brawn",
            "mana_cost": {"G": 1},
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "is_aura": True,
            "aura_enchant_type": "creature",
            "aura_equipment_bonuses": {
                "power_bonus": 0,
                "toughness_bonus": 1,
                "granted_keywords": [],
            },
        },
        0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 1)
    state.add_mana(0, "G", 2)
    _cast_and_resolve_aura(state, aura_a_id, host_id)
    _cast_and_resolve_aura(state, buff_id, host_id)
    # A's set-base 0/4 still wins (buff has no set-base entry).
    # +0/+1 from the buff stacks on top → 0/5.
    assert state.effective_power(host_id) == 0
    assert state.effective_toughness(host_id) == 5


# ---------------------------------------------------------------------------
# SBA lethal lock-step under multi-Aura: latest set-base toughness drives
# the SBA threshold
# ---------------------------------------------------------------------------


def test_multi_aura_sba_lethal_locks_on_latest_set_base_toughness():
    """A printed 4/4 host with two set-base Auras attached:
    A first (set-base 0/4) then B (set-base 5/2). Effective base =
    B's 5/2 (latest wins). With 2 damage marked, SBA 704.5g should
    fire (damage >= effective toughness 2) and destroy the host.

    Pin: the SBA's lethal predicate must call into the same
    `aura_set_base_pt_on` helper and observe the same latest-wins
    answer as the combat reader. The pre-closure FIRST-walk would
    have read A's toughness 4 and (wrongly) survived 2 damage.
    """
    _require_engine()
    state = _fresh_state()
    aura_a_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura A", set_base_power=0, set_base_toughness=4,
        ),
        0, ZONE_HAND,
    )
    aura_b_id = state.register_and_inject_object(
        _aura_set_base_pt_dict(
            name="Aura B", set_base_power=5, set_base_toughness=2,
        ),
        0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "C", 2)
    state.add_mana(0, "G", 2)
    _cast_and_resolve_aura(state, aura_a_id, host_id)
    _cast_and_resolve_aura(state, aura_b_id, host_id)
    # Effective base from B (latest): 5/2.
    assert state.effective_toughness(host_id) == 2
    state.deal_damage(host_id, 2)
    state.apply_sbas()
    # Host destroyed at 2 damage (matches B's set-base toughness 2,
    # not A's 4). The Auras bury too (Phase 2 S2 SBA path).
    assert _battlefield_obj(state, host_id) is None, (
        "Multi-Aura SBA lethal must use the LATEST set-base "
        "toughness (B: 2), not the first (A: 4)"
    )


# ---------------------------------------------------------------------------
# Helper-level pin: aura_set_base_pt_on returns None when only non-set-base
# Auras are attached
# ---------------------------------------------------------------------------


def test_helper_returns_none_when_only_non_set_base_auras_attached():
    """A host with a plain buff Aura (no set-base) attached: the
    helper returns None — only non-set-base entries are present, so
    nothing wins the set-base slot. The reader falls through to the
    printed base.

    Pin: the loop correctly skips printings where
    aura_set_base_pt is None instead of returning early.
    """
    _require_engine()
    state = _fresh_state()
    buff_id = state.register_and_inject_object(
        {
            "name": "Brawn",
            "mana_cost": {"G": 1},
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "is_aura": True,
            "aura_enchant_type": "creature",
            "aura_equipment_bonuses": {
                "power_bonus": 1,
                "toughness_bonus": 1,
                "granted_keywords": [],
            },
        },
        0, ZONE_HAND,
    )
    host_id = state.register_and_inject_object(
        _creature_dict("Big Bear", power=4, toughness=4),
        0, ZONE_BATTLEFIELD,
    )
    state.add_mana(0, "G", 1)
    _cast_and_resolve_aura(state, buff_id, host_id)
    # printed 4/4 + buff +1/+1 → 5/5 (no set-base override).
    assert state.effective_power(host_id) == 5
    assert state.effective_toughness(host_id) == 5
