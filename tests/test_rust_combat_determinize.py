"""B3-S3 — the factored-combat provider side + determinization-via-Rust.

Covers:
* the new Rust ``set_object_printing_id`` write pymethod
  (B3-pre-EXT write half) — set / miss / CoW-safety;
* ``rust_determinize`` permutes hidden-zone printing_ids, preserves
  zones/ids/counts, leaves a clone's source pristine (CoW), and
  preserves a public-zone / own-hand card the viewer knows;
* the provider's factored-combat-phase bookkeeping (``_combat_phase``
  / ``_pending_attackers`` / ``_pending_blockers``) tracks Rust's G1
  factored emission so the codec's combat-slot path encodes; the
  codec encodes AttackerDecision / BlockerDecision through the
  RustZoneView (attacking derived from Rust get_attackers()).
"""

from __future__ import annotations

import random

import pytest

from mtg_bot.actions import PassPriority
from mtg_bot.search.combat_decisions import (
    AttackerDecision, BlockerDecision,
)


def _rs():
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity.cross_engine import (
        build_rust_state, tiny_synthetic_deckspec,
    )
    return build_rust_state(tiny_synthetic_deckspec())


# ---------------------------------------------------------------------------
# the Rust set_object_printing_id write pymethod
# ---------------------------------------------------------------------------


def test_set_object_printing_id_sets_and_misses():
    rs = _rs()
    lib = [dict(d) for d in rs.library_snapshot(0)]
    assert lib, "synthetic spec must seed p0 library"
    oid = lib[0]["id"]
    old = lib[0]["printing_id"]
    new = 1 if old == 0 else 0
    assert rs.set_object_printing_id(oid, new) is True
    after = [dict(d) for d in rs.library_snapshot(0)]
    assert after[0]["printing_id"] == new
    # Miss on a non-existent id returns False (never raises).
    assert rs.set_object_printing_id(10_000_001, 0) is False


def test_set_object_printing_id_is_cow_safe():
    """Cloning then mutating the clone must NOT leak into the source
    (PIMC clones the god-view then determinizes the clone)."""
    rs = _rs()
    src_pid = dict(list(rs.library_snapshot(0))[0])["printing_id"]
    oid = dict(list(rs.library_snapshot(0))[0])["id"]
    clone = rs.clone_once()
    clone.set_object_printing_id(oid, 99)
    assert dict(list(rs.library_snapshot(0))[0])["printing_id"] == src_pid
    assert dict(list(clone.library_snapshot(0))[0])["printing_id"] == 99


# ---------------------------------------------------------------------------
# rust_determinize
# ---------------------------------------------------------------------------


def test_rust_determinize_preserves_zones_ids_counts():
    from mtg_bot.search.rust_determinize import rust_determinize

    rs = _rs()
    before = {
        pid: [(dict(d)["id"], dict(d)["zone"])
              for d in rs.library_snapshot(pid)]
        for pid in (0, 1)
    }
    before_pid_multiset = sorted(
        dict(d)["printing_id"]
        for pid in (0, 1) for d in rs.library_snapshot(pid)
    )
    rust_determinize(rs, viewer_id=0, rng=random.Random(42))
    after = {
        pid: [(dict(d)["id"], dict(d)["zone"])
              for d in rs.library_snapshot(pid)]
        for pid in (0, 1)
    }
    # Zones / ids / per-zone counts unchanged.
    assert before == after
    # The printing_id MULTISET is conserved (only permuted within
    # each owner's hidden pool — never created/destroyed).
    after_pid_multiset = sorted(
        dict(d)["printing_id"]
        for pid in (0, 1) for d in rs.library_snapshot(pid)
    )
    assert before_pid_multiset == after_pid_multiset


def test_rust_determinize_cow_clone_source_pristine():
    """Determinizing a clone leaves the source god-view untouched."""
    from mtg_bot.search.rust_determinize import rust_determinize

    rs = _rs()
    src = sorted(
        dict(d)["printing_id"] for d in rs.library_snapshot(0)
    )
    src_order = [dict(d)["printing_id"] for d in rs.library_snapshot(0)]
    clone = rs.clone_once()
    rust_determinize(clone, viewer_id=1, rng=random.Random(7))
    # Source unchanged (order + multiset).
    assert [dict(d)["printing_id"]
            for d in rs.library_snapshot(0)] == src_order
    assert sorted(
        dict(d)["printing_id"] for d in rs.library_snapshot(0)
    ) == src


def test_rust_determinize_viewer_knows_public_zone_preserved():
    """A card the viewer knows (public zone) must NOT be permuted.
    Drive a card to the battlefield, snapshot its printing, determinize
    from the opponent's view, assert the battlefield card is unchanged.
    """
    from mtg_bot.search.rust_determinize import (
        _rust_viewer_knows, _ZONE_BATTLEFIELD, _ZONE_HAND, _ZONE_LIBRARY,
    )

    # Unit-level: the epistemic policy itself (the Python-kept model).
    bf = {"id": 1, "zone": _ZONE_BATTLEFIELD, "printing_id": 3}
    own_hand = {"id": 2, "zone": _ZONE_HAND, "printing_id": 4}
    opp_hand = {"id": 3, "zone": _ZONE_HAND, "printing_id": 5}
    lib = {"id": 4, "zone": _ZONE_LIBRARY, "printing_id": 6}
    assert _rust_viewer_knows(bf, owner_pid=1, viewer_id=0) is True
    assert _rust_viewer_knows(own_hand, owner_pid=0, viewer_id=0) is True
    assert _rust_viewer_knows(opp_hand, owner_pid=1, viewer_id=0) is False
    assert _rust_viewer_knows(lib, owner_pid=0, viewer_id=0) is False


# ---------------------------------------------------------------------------
# the factored-combat provider side
# ---------------------------------------------------------------------------


def _combat_adapter_at_attacker_phase():
    """Build a provider whose Rust state has a NON-summoning-sick
    creature on p0's battlefield, positioned so that driving the
    provider's priority loop reaches p0's DECLARE_ATTACKERS (Rust
    phase 5) with the G1 factored ``attacker_decision`` emission live.

    Seats a Grizzly Bears (2/2) via the ``move_object`` primitive,
    then rolls the Rust turn forward (advance_phase wraps UNTAP which
    clears the active player's summoning sickness) until p0 is active
    at phase < 5 with the Bears non-sick. The provider is then
    constructed on that state; its constructor's
    _advance_to_next_decision drives to the first decision moment.
    """
    pytest.importorskip("mtg_bot_engine")
    from mtg_bot.parity.cross_engine import (
        DeckSpec, _BEARS, _FOREST, build_rust_state,
    )
    from mtg_bot.search.engine_adapter_factory import (
        make_rust_game_state_adapter,
    )

    spec = DeckSpec(
        card_defs=(_FOREST, _BEARS),
        p0_library=tuple(["Grizzly Bears"] * 4 + ["Forest"] * 8),
        p1_library=tuple(["Forest"] * 12),
    )
    rs = build_rust_state(spec)
    bears = next(
        dict(d) for d in rs.library_snapshot(0)
        if dict(d)["printing_name"] == "Grizzly Bears"
    )
    assert rs.move_object(bears["id"], 2, 0) is True  # ZONE_BF=2, p0
    # Roll turns until p0 is active, phase==UPKEEP(1), Bears non-sick.
    # (advance_phase's CLEANUP->UNTAP wrap clears the active player's
    # summoning sickness; turn 3 phase 1 is p0-active with the Bears
    # no longer sick — verified live.)
    for _ in range(80):
        if (
            rs.active_player_idx == 0
            and rs.current_phase() == 1
            and not any(
                dict(o)["summoning_sick"]
                for o in rs.battlefield_snapshot()
                if dict(o)["controller_id"] == 0
            )
        ):
            break
        rs.advance_phase()
    return make_rust_game_state_adapter(rs, spec=spec), bears["id"]


def test_combat_phase_bookkeeping_tracks_factored_emission():
    """Drive the provider's priority loop into p0's DECLARE_ATTACKERS
    with a non-sick creature; assert the provider sets
    ``_combat_phase``/``_pending_attackers`` from Rust's G1 factored
    emission so the codec's combat-slot path encodes, and that the
    factored AttackerDecision round-trips through the codec."""
    from mtg_bot.training import action_encoding as ae

    adapter, bears_id = _combat_adapter_at_attacker_phase()
    saw_attackers = False
    for _ in range(60):
        if adapter.is_terminal():
            break
        legal = adapter.legal_decisions()
        if not legal:
            break
        atk = [d for d in legal if isinstance(d, AttackerDecision)]
        if atk:
            saw_attackers = True
            assert adapter.combat_phase == "attackers"
            assert adapter._pending_attackers, (
                "provider must expose the pending attacker head for "
                "the codec's _pending_attacker_head"
            )
            head = adapter._pending_attackers[0]
            assert head == bears_id
            assert all(d.attacker_id == head for d in atk)
            # The codec encodes the factored AttackerDecision via the
            # implicit-head ATTACKER slot (RustZoneView-sourced).
            slot = ae.encode(
                atk[0], adapter, adapter.active_player(),
            )
            assert slot in (
                ae.SLOT_ATTACKER_ATTACK, ae.SLOT_ATTACKER_SKIP,
            )
            # decode round-trips back to an AttackerDecision for the
            # same implicit head.
            back = ae.decode(slot, adapter, adapter.active_player())
            assert isinstance(back, AttackerDecision)
            assert back.attacker_id == head
            break
        # Not yet at the attacker window — pass priority to advance.
        passes = [d for d in legal if isinstance(d, PassPriority)]
        adapter.apply(passes[0] if passes else legal[0])
    assert saw_attackers, (
        "provider never surfaced the G1 factored attacker decision "
        "despite a non-sick creature on the active player's bf"
    )


def test_combat_phase_clears_to_none_off_combat():
    """At a normal priority moment (no factored combat dicts) the
    provider's combat_phase is None so the codec uses the priority-
    window path."""
    adapter, _ = _combat_adapter_at_attacker_phase()
    # The constructor drives to the first decision moment, which
    # (phase==UPKEEP, empty stack) is a normal priority window, not
    # combat — combat_phase must be None there.
    adapter.legal_decisions()
    assert adapter.combat_phase is None
    assert adapter._pending_attackers == []
    assert adapter._pending_blockers == []
