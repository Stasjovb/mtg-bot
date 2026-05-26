"""Scavenger Grounds — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip; Carrier-AA Phase 3B
admit-set landing).

Scavenger Grounds is a ``{0}`` ``Land — Desert`` in the EoE pool with
a single non-mana activated ability:

    "{2}, {T}, Sacrifice a Desert: Exile all graveyards."

The Carrier-AA substrate Phase 3B (2026-05-25 — see
``docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md`` §7.2) closes in
THREE cycles: (C1) Rust substrate landing the new ``Effect`` variant
``ExileAllGraveyards`` plus parse / resolve / to_pydict arms +
cross-engine bridge arms + the 5 Rust unit pins — landed at commit
``51abfd78``; (C2) Python admit widen + Scavenger Grounds FLIP — the
``_carrier_aa_phase_1_effect_classes`` lazy frozenset accessor at
``src/mtg_bot/parity/trajectory.py`` extended to include
``ExileAllGraveyards`` AND the ``_aa_is_phase1_sub_shape_a`` cost-gate
widened on the ``sacrifice_a_desert`` axis (defense-in-depth: the
gate continues to decline ``sacrifice_self=True AND sacrifice_a_desert
=True`` together — no carrier in EoE has both) — landed at commit
``a0f21384`` (Scavenger Grounds's live AA shape is ``{2}, {T},
sacrifice_a_desert``: the Phase-1.5a ``{N}, {T}`` cost-gate is already
wired, so the combined Effect-class + cost-axis widen FLIPs the
admit-gate DECLINED → ADMITTED in one slice); (C3) THIS PROBE —
real-EoE per-card byte-equal observable on both engines, covering
the GENUINE end-to-end "exile every card from every player's
graveyard" mass-zone-move chain. Closes Phase 3B.

Parser-emitted Effect shape:

    ``ExileAllGraveyards()``  (unit-variant zero-arg frozen dataclass;
    no ``__post_init__`` stamps — the class is bare;
    ``requires_target() == False`` — zero-target mass effect; resolve
    walks ``state.players[0..2]`` graveyards into the matching
    player's exile, preserving owner attribution)

attached to an ``ActivatedAbility`` whose ``cost`` carries
``mana=ManaCost(generic=2)`` + ``tap_self=True`` +
``sacrifice_a_desert=True`` (NOT ``sacrifice_self``: Scavenger Grounds
itself is a valid Desert target via the Lander-precedent SELF-
eligibility rule, but the cost-bool axis the parser stamps is the
zero-target ``sacrifice_a_desert`` axis — the per-Desert target
fan-out is handled by the activation machinery in
``state_ops_actions.rs:1179`` + the Python ``actions.py`` mirror, not
by ``sacrifice_self``). The bridge arm ``exile_all_graveyards``
(``cross_engine.py:12615`` reverse arm; ``cross_engine.py:14500``
forward emit arm) round-trips ``{"kind": "exile_all_graveyards"}``
byte-equal to Python's ``ExileAllGraveyards()``.

**EEEE-idiom for the ActivatedAbility carrier.** Same lane discipline
as the sibling Carrier-AA AA probes (parse + bridge round-trip +
Python-side resolve): the probe drives the parsed Effect through its
actual ``resolve`` path on the Python state, with observables that
mirror what Rust's ``Effect::ExileAllGraveyards`` resolve arm
(``rust/src/state_ops_resolve.rs:23553``) produces on the same input
shape. The cross-engine byte-equal mirror is established by the
Phase-3B admit gate routing the genuine parsed Scavenger Grounds
printing through the Carrier-AA substrate end-to-end (loader admits
post-C2 — see the C2-flipped admit pin in
``test_carrier_aa_phase_3b_substrate_cycle_1.py``).

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe binding
the Scavenger Grounds slug to the AA + ``ExileAllGraveyards``
Effect+bridge round-trip on the REAL parsed EoE printing — and the
FIRST PROBED-tier slot for the ``ExileAllGraveyards`` Effect class
via the Carrier-AA substrate's ``{N}, {T}, sacrifice_a_desert``
cost-shape disjunct.

**AA-cost-substrate scope.** The mana-payment (``{2}``) /
tap-payment / sacrifice-a-Desert cost trajectory of the AA is
exercised at the loader-end-to-end disjunct (Scavenger Grounds passes
``_printing_is_bridge_simple_carrier_aa_land`` post-C2 widen + the
cross-engine bridge round-trip pin below); per-slug PROBED attribution
credits Scavenger Grounds based on the Effect + bridge byte-equality
+ parsed-printing resolve smoke alone — the canonical EEEE-idiom
precedent (Petrified Field's Phase-2a probe at
``tests/test_petrified_field_parity.py`` / Terrain Generator's
Phase-2b probe at ``tests/test_terrain_generator_parity.py`` /
Mystifying Maze's Phase-3A probe at
``tests/test_mystifying_maze_parity.py``).

**Per-owner routing invariant (load-bearing).** Python's
``ExileAllGraveyards.resolve`` (``effects/generic/exile.py:667-680``)
iterates ``for p in state.players`` and ``for c in list(p.graveyard)``:
each card is removed from THAT player's graveyard, has its
``zone`` stamped ``Zone.EXILE``, and is appended to THAT SAME
player's exile. Cards stay with their owner; no cross-routing. The
Rust mirror at ``state_ops_resolve.rs:23553`` walks the same
``state.players`` Vec by index, draining each ``player_gy`` into
``player_exile`` for the same ``pidx`` — byte-equal per-owner routing.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.exile import ExileAllGraveyards


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 4


# ---------------------------------------------------------------------------
# (1) Parser SoT — Scavenger Grounds is parser-claimed and carries the
# exact AA shape the design doc (§7.2) pins.
# ---------------------------------------------------------------------------


def test_scavenger_grounds_parser_claims_card():
    assert "Scavenger Grounds" in _PRINTINGS, (
        "Scavenger Grounds must be parser-claimed by the active "
        "CardSource"
    )


def test_scavenger_grounds_printed_attrs():
    """Pins the basic printing surface: single-typed ``Land — Desert``,
    no mana cost, no power/toughness, no triggered / static / keyword
    riders. Scavenger Grounds carries NO leading ``{T}: Add {C}`` mana
    ability (the synthesized mana-ability slot is empty — unlike
    Mystifying Maze / Petrified Field / Terrain Generator); the
    carrier AA (the exile-all-graveyards AA) is the SOLE
    ``activated_abilities`` entry."""
    p = _PRINTINGS["Scavenger Grounds"]
    assert p.card_types == ("Land",)
    assert p.subtypes == ("Desert",), (
        "Scavenger Grounds must carry the Desert subtype — the "
        "Phase-3B admit predicate does not gate on subtypes, but "
        "the live ``sacrifice_a_desert`` cost-pay machinery in "
        "``state_ops_legal.rs:3522`` requires the Desert subtype on "
        "the eligible sacrifice victims (SELF-eligibility per the "
        "Lander precedent: Scavenger Grounds itself is a valid Desert "
        "sacrifice target for its own activation)"
    )
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert p.power is None and p.toughness is None
    assert p.keywords == frozenset()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


def test_scavenger_grounds_activated_ability_exile_all_graveyards_shape():
    """Scavenger Grounds has the single carrier ``ActivatedAbility``
    whose effect is ``ExileAllGraveyards()`` (unit variant, no fields).
    Cost is ``{2}, {T}, sacrifice_a_desert`` — the Phase-3B widened
    cost-gate's load-bearing shape. The Lander-precedent SELF-
    eligibility rule applies (Scavenger Grounds itself is a valid
    Desert sacrifice target for this activation), but the cost-bool
    axis the parser stamps is ``sacrifice_a_desert``, not
    ``sacrifice_self``."""
    p = _PRINTINGS["Scavenger Grounds"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) == 1, (
        f"Scavenger Grounds must have exactly one non-mana "
        f"ActivatedAbility; got {len(non_mana_aas)}"
    )
    aa = non_mana_aas[0]
    # Effect shape.
    assert isinstance(aa.effect, ExileAllGraveyards), (
        f"Scavenger Grounds AA effect must be ExileAllGraveyards; got "
        f"{type(aa.effect).__name__}"
    )
    # Cost shape — the Phase-3B load-bearing axis.
    assert aa.cost.tap_self is True
    assert aa.cost.sacrifice_self is False, (
        "Scavenger Grounds's AA carries NO sacrifice_self (the "
        "cost-bool axis is ``sacrifice_a_desert``, NOT "
        "``sacrifice_self`` — the parser distinguishes the typed "
        "Desert-cost from the bare self-sac cost; both-at-once stays "
        "DECLINED at the Phase-3B admit gate per the C2 defense-in-"
        "depth guard)"
    )
    assert aa.cost.sacrifice_a_desert is True, (
        "Scavenger Grounds's AA must carry ``sacrifice_a_desert=True`` "
        "— the Phase-3B C2 cost-gate widen's load-bearing axis"
    )
    assert aa.cost.mana is not None, (
        "Scavenger Grounds's AA cost carries ``{2}`` mana component"
    )
    assert aa.cost.mana.generic == 2
    assert aa.cost.mana.colored == ()
    assert aa.cost.mana.hybrid == ()
    assert aa.cost.mana.x_pips == 0
    # No riders.
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is False
    assert aa.cost_reductions == ()
    assert aa.room_half is None
    assert aa.tier_threshold == 0
    assert aa.activate_only_once is False
    # The Effect is a zero-target mass effect — requires_target is
    # False; no legal_targets fan-out at activation time (the per-
    # Desert target-pick is handled by the cost-pay machinery via the
    # ``sacrifice_a_desert`` axis at activation, NOT by the Effect
    # itself).
    assert aa.effect.requires_target() is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the exile_all_graveyards dict shape round-
# trips byte-equal to the parsed printing's emitted Effect.
# ---------------------------------------------------------------------------


def test_scavenger_grounds_bridge_arm_round_trip():
    """The bridge arm ``exile_all_graveyards`` (cross_engine.py:12615)
    round-trips ``{"kind": "exile_all_graveyards"}`` to the matching
    Python ``ExileAllGraveyards()`` instance — unit variant, no fields.

    Effect-level byte-equality between the parsed real-EoE printing's
    emitted ``ExileAllGraveyards`` Effect and the bridged Effect: the
    structural contract for the PROBED tier."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "exile_all_graveyards"}
    )
    assert isinstance(bridged, ExileAllGraveyards)

    p = _PRINTINGS["Scavenger Grounds"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert aa.effect == bridged, (
        f"Scavenger Grounds AA Effect must be byte-equal to the "
        f"bridged Effect (ExileAllGraveyards() unit-variant structural "
        f"contract); got parsed={aa.effect!r}, bridged={bridged!r}"
    )


def test_scavenger_grounds_aa_round_trip_through_safe_dict():
    """The bridge's ``_python_aa_to_safe_dict`` ↔
    ``_aa_dict_to_python_activated_ability`` round-trip applied to the
    genuine parsed Scavenger Grounds AA emits the canonical
    ``{"cost": {"mana": {"generic": 2}, "tap_self": True,
    "sacrifice_a_desert": True}, "effect":
    {"kind": "exile_all_graveyards"}}`` dict and rebuilds a byte-equal
    Python ActivatedAbility on the load-bearing fields (cost atoms +
    Effect + AA-rider fields). The cost-side ``mana_str`` display-
    string field is parser-only and is NOT round-tripped through the
    bridge (UI-side annotation; both engines ignore it for activation
    semantics — same convention as the Deserted Temple / Petrified
    Field / Terrain Generator / Mystifying Maze probes)."""
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    p = _PRINTINGS["Scavenger Grounds"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    safe = _python_aa_to_safe_dict(aa)
    assert safe is not None, (
        "_python_aa_to_safe_dict must accept Scavenger Grounds's "
        "parsed AA post-Phase-3B — the C2 Effect-class widen + "
        "Phase-3B cost-gate widen admit this shape"
    )
    assert safe == {
        "cost": {
            "mana": {"generic": 2},
            "tap_self": True,
            "sacrifice_a_desert": True,
        },
        "effect": {"kind": "exile_all_graveyards"},
    }
    back = _aa_dict_to_python_activated_ability(safe)
    assert back.effect == aa.effect
    assert back.cost.mana == aa.cost.mana
    assert back.cost.tap_self == aa.cost.tap_self
    assert back.cost.sacrifice_self == aa.cost.sacrifice_self
    assert back.cost.sacrifice_a_desert == aa.cost.sacrifice_a_desert
    assert back.is_mana_ability == aa.is_mana_ability
    assert back.sorcery_speed == aa.sorcery_speed
    assert back.cost_reductions == aa.cost_reductions
    assert back.room_half == aa.room_half
    assert back.tier_threshold == aa.tier_threshold
    assert back.activate_only_once == aa.activate_only_once


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts a
# Scavenger-Grounds-shape dict (carrier AA with ``{2}, {T},
# sacrifice_a_desert`` cost + ``ExileAllGraveyards`` effect).
# Exercises the Rust ``parse_effect`` arm for the
# ``exile_all_graveyards`` kind landed in the Phase-3B C1 substrate.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_scavenger_grounds_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` +
    ``parse_activated_ability`` arms accept a Scavenger-Grounds-shape
    dict (single AA with
    ``{"cost": {"mana": {"generic": 2}, "tap_self": True,
    "sacrifice_a_desert": True}, "effect":
    {"kind": "exile_all_graveyards"}}``) on a Land carrier. The
    Phase-3B C1 substrate (commit ``51abfd78``) shipped the variant +
    parse arms + resolve arm (zero-target mass-zone-move) + cross-
    engine bridge arms in lockstep; this pin confirms the end-to-end
    Rust acceptance under the Phase-3B C2 Effect-class widen + cost-
    gate widen."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Scavenger Grounds (synthetic carrier)",
            "card_types": ["Land"],
            "subtypes": ["Desert"],
            "mana_cost": {"generic": 0},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 2},
                        "tap_self": True,
                        "sacrifice_a_desert": True,
                    },
                    "effect": {
                        "kind": "exile_all_graveyards",
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) Carrier-AA loader admit pin — the Phase-3B admit-set end-to-end:
# ``_filter_deck_to_bridge_supported`` admits Scavenger Grounds through
# the Carrier-AA disjunct, the resulting CardDef carries the canonical
# AA dict shape ready for ``build_rust_state`` to emit into the Rust
# registry.
# ---------------------------------------------------------------------------


def test_scavenger_grounds_carrier_aa_loader_end_to_end_admit():
    """**Phase 3B end-to-end pin.** The production-deck loader
    (``_filter_deck_to_bridge_supported``) admits Scavenger Grounds
    through the Carrier-AA Phase 3B disjunct. The returned CardDef
    carries the single non-token AA dict with the canonical Phase-3B
    cost shape + ``ExileAllGraveyards`` effect — Rust-side
    ``build_rust_state`` consumes it via the Phase-3B C1 substrate
    emit arm (no other code path needed)."""
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Scavenger Grounds"], _PRINTINGS,
    )
    assert filtered == ["Scavenger Grounds"]
    assert len(card_defs) == 1
    card_def = card_defs[0]
    assert card_def.name == "Scavenger Grounds"
    assert card_def.card_type == "Land"
    assert card_def.mana_produced == ()
    assert card_def.triggered_abilities == ()
    assert card_def.keywords == ()
    assert card_def.token_activated_abilities == ()
    aas = card_def.activated_abilities
    assert len(aas) == 1
    aa_dict = aas[0]
    assert aa_dict["cost"] == {
        "mana": {"generic": 2},
        "tap_self": True,
        "sacrifice_a_desert": True,
    }
    assert aa_dict["effect"] == {"kind": "exile_all_graveyards"}


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Scavenger Grounds printing's AA through its
# ``ExileAllGraveyards`` Effect resolve path on the Python side,
# mirroring Rust's ``Effect::ExileAllGraveyards`` resolve arm (the C1
# substrate landing at commit ``51abfd78``). The probe asserts the
# two observables the design doc §7.2 pins:
#   (a) baseline empty-graveyards no-op (activate on both empty
#       graveyards → no exile happens, byte-equal silent no-op modulo
#       the log entry stamping the 0-card count);
#   (b) load-bearing both-graveyards-populated mass-exile line — every
#       card in every player's graveyard moves to that SAME player's
#       exile (per-owner routing).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_scavenger_grounds_baseline_empty_graveyards_no_op_parity():
    """**GENUINE real-EoE probe — baseline empty-graveyards no-op line.**

    Drives the parsed Scavenger Grounds AA's ``ExileAllGraveyards``
    Effect via ``resolve(state, controller_id, targets=())`` on a
    state with BOTH players' graveyards empty. Python's
    ``ExileAllGraveyards.resolve`` (``effects/generic/exile.py:667-
    680``) iterates ``for p in state.players`` and ``for c in
    list(p.graveyard)``: with empty graveyards every inner loop is a
    no-op; ``total`` stays 0; the log entry ``"all graveyards exiled
    (0 cards)"`` is stamped (the resolve always logs, regardless of
    count — Rust's mirror also stamps a 0-count tombstone).

    Rust's ``Effect::ExileAllGraveyards`` resolve arm
    (``state_ops_resolve.rs:23553``) walks the same
    ``0..state.players.len()`` index range; each per-player graveyard
    drain produces an empty Vec; the per-player exile is unchanged.
    Byte-equal silent no-op modulo the log tombstone — no panic, no
    zone moves, no state mutation beyond the count-0 log entry.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Scavenger Grounds")
    if real is None:
        pytest.skip("Scavenger Grounds absent from active CardSource")

    non_mana_aas = [
        aa for aa in (real.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert isinstance(aa.effect, ExileAllGraveyards)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the genuine parsed Scavenger Grounds on p0's bf (the AA
    # source). Untapped. Both graveyards empty.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve sanity — both graveyards empty (the load-bearing
    # baseline for the no-op observable).
    assert py_state.players[0].graveyard == []
    assert py_state.players[1].graveyard == []

    # Pre-resolve state snapshot.
    bf_before = len(py_state.battlefield)
    p0_exile_before = list(py_state.players[0].exile)
    p1_exile_before = list(py_state.players[1].exile)
    log_before_len = len(py_state.log)

    # Resolve with empty targets — zero-target mass effect; the resolve
    # walks every player's graveyard regardless of targets.
    aa.effect.resolve(py_state, py_source.controller_id, targets=())

    # State invariants — no zone moves on either side, source
    # untouched, both exiles unchanged, both graveyards still empty.
    assert len(py_state.battlefield) == bf_before
    assert py_source in py_state.battlefield
    assert py_source.zone == Zone.BATTLEFIELD
    assert py_state.players[0].graveyard == []
    assert py_state.players[1].graveyard == []
    assert list(py_state.players[0].exile) == p0_exile_before
    assert list(py_state.players[1].exile) == p1_exile_before
    # Log tombstone — the resolve unconditionally logs
    # ``"all graveyards exiled (<N> cards)"`` with N=0.
    assert len(py_state.log) == log_before_len + 1
    assert "all graveyards exiled (0 cards)" in py_state.log[-1]


def test_cross_engine_real_eoe_scavenger_grounds_both_graveyards_populated_mass_exile_line_parity():
    """**GENUINE real-EoE probe — load-bearing both-graveyards-
    populated mass-exile line. PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the FULL parsed Scavenger Grounds AA's ``ExileAllGraveyards``
    Effect resolve on a state where BOTH players' graveyards carry
    cards. The probe asserts every observable Rust's
    ``Effect::ExileAllGraveyards`` resolve arm produces byte-equal on
    the same input.

    Setup:
      * Scavenger Grounds on p0's battlefield (the AA source);
      * 2 cards in p0's graveyard (Forest, Forest);
      * 3 cards in p1's graveyard (Mountain, Island, Plains).

    Phase 1 — resolve. Python's ``ExileAllGraveyards.resolve``
    (``effects/generic/exile.py:667-680``):

      * iterates ``for p in state.players`` (p0, then p1);
      * for each player, snapshots the graveyard via ``list(p.graveyard)``
        (so concurrent mutation during the inner loop is safe);
      * for each card: removes from p.graveyard, stamps ``c.zone =
        Zone.EXILE``, appends to p.exile;
      * stamps ``"all graveyards exiled (<total> cards)"`` to
        state.log (total = sum across both players).

    Rust's ``Effect::ExileAllGraveyards`` resolve arm
    (``state_ops_resolve.rs:23553``) walks the same ``0..state
    .players.len()`` index range, drains each ``player_gy`` via
    ``Arc::make_mut`` snapshot, stamps ``obj.zone = ZONE_EXILE``, and
    appends to ``player_exile`` for the SAME pidx — byte-equal per-
    owner routing.

    The cross-engine mirror is established by:

      1. Parse SoT (test #3 above) — same AA shape on both engines.
      2. Bridge round-trip (test #4 above) — byte-equal Effect dict.
      3. Rust synthetic-carrier acceptance (test #6 above) — Rust
         parses the same dict shape.
      4. End-to-end loader admit (test #7 above) — the
         ``_filter_deck_to_bridge_supported`` admit path threads the
         genuine printing into the Rust registry.
      5. This pin's Python-side resolve smoke — drives the Effect
         through the same resolve contract Rust's arm mirrors.

    **Per-owner routing invariant pinned in-line.** Every card
    leaving p0's graveyard MUST land in p0's exile (and only p0's);
    every card leaving p1's graveyard MUST land in p1's exile (and
    only p1's). Cross-routing — e.g. a p0-graveyard card ending up
    in p1's exile — is a violation; both engines must preserve
    owner attribution. The Rust resolve walks the same per-pidx
    loop body, so any cross-routing would show as a Rust-side
    byte-divergence at the snapshot bridge.

    The post-resolve observables (every graveyard card moves
    graveyard → exile, owner-preserved; Scavenger Grounds stays
    untouched on bf because its tap-self + sacrifice-a-Desert costs
    are paid OUT-OF-BAND by the activation machinery before this
    resolve fires — Rust's ``sacrifice_a_desert`` cost-pay commits at
    ``state_ops_actions.rs:1179`` BEFORE this resolve arm fires) are
    byte-equal on both engines.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Scavenger Grounds")
    if real is None:
        pytest.skip("Scavenger Grounds absent from active CardSource")

    forest = _PRINTINGS.get("Forest")
    mountain = _PRINTINGS.get("Mountain")
    island = _PRINTINGS.get("Island")
    plains = _PRINTINGS.get("Plains")
    if forest is None or mountain is None or island is None or plains is None:
        pytest.skip(
            "Basic land printings absent from active CardSource — "
            "every EoE deck pool carries the 5 basics"
        )

    non_mana_aas = [
        aa for aa in (real.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert isinstance(aa.effect, ExileAllGraveyards)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat genuine Scavenger Grounds on p0's bf — untapped (the AA
    # source). p0 is the active player by default in
    # build_python_state.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Populate p0's graveyard with 2 cards (Forest, Forest).
    p0_gy_objs = []
    for _ in range(2):
        obj = py_state.new_object(
            forest, owner_id=0, zone=Zone.GRAVEYARD,
        )
        py_state.players[0].graveyard.append(obj)
        p0_gy_objs.append(obj)

    # Populate p1's graveyard with 3 cards (Mountain, Island, Plains).
    p1_gy_objs = []
    for pr in (mountain, island, plains):
        obj = py_state.new_object(
            pr, owner_id=1, zone=Zone.GRAVEYARD,
        )
        py_state.players[1].graveyard.append(obj)
        p1_gy_objs.append(obj)

    # Pre-resolve state snapshot.
    bf_before = len(py_state.battlefield)
    p0_exile_before_ids = {c.id for c in py_state.players[0].exile}
    p1_exile_before_ids = {c.id for c in py_state.players[1].exile}
    p0_gy_ids = {c.id for c in p0_gy_objs}
    p1_gy_ids = {c.id for c in p1_gy_objs}
    log_before_len = len(py_state.log)

    # Pre-resolve sanity — graveyards populated as set up.
    assert len(py_state.players[0].graveyard) == 2
    assert len(py_state.players[1].graveyard) == 3
    # Every staged card carries the OWNER's id matching the graveyard
    # it sits in (the per-owner routing invariant's setup precondition).
    for obj in p0_gy_objs:
        assert obj.owner_id == 0
        assert obj.zone == Zone.GRAVEYARD
    for obj in p1_gy_objs:
        assert obj.owner_id == 1
        assert obj.zone == Zone.GRAVEYARD

    # ===========================================================
    # Resolve — byte-equal mirror to Rust's
    # ``Effect::ExileAllGraveyards`` resolve arm. The Effect resolves
    # with empty targets (zero-target mass effect).
    # ===========================================================
    aa.effect.resolve(py_state, py_source.controller_id, targets=())

    # Post-resolve observables.
    # (1) Both graveyards drained.
    assert py_state.players[0].graveyard == [], (
        "p0's graveyard must be empty post-resolve"
    )
    assert py_state.players[1].graveyard == [], (
        "p1's graveyard must be empty post-resolve"
    )
    # (2) Per-owner routing invariant — cards stay with their owner.
    p0_exile_after_ids = {c.id for c in py_state.players[0].exile}
    p1_exile_after_ids = {c.id for c in py_state.players[1].exile}
    p0_new_exile_ids = p0_exile_after_ids - p0_exile_before_ids
    p1_new_exile_ids = p1_exile_after_ids - p1_exile_before_ids
    assert p0_new_exile_ids == p0_gy_ids, (
        f"p0's exile must gain exactly the p0-graveyard ids "
        f"(per-owner routing); got new p0 exile ids = "
        f"{p0_new_exile_ids}, expected = {p0_gy_ids}"
    )
    assert p1_new_exile_ids == p1_gy_ids, (
        f"p1's exile must gain exactly the p1-graveyard ids "
        f"(per-owner routing); got new p1 exile ids = "
        f"{p1_new_exile_ids}, expected = {p1_gy_ids}"
    )
    # (3) Cross-routing guard — no p0-gy card lands in p1's exile (and
    # vice versa). This is the load-bearing per-owner routing
    # invariant the Rust mirror also preserves.
    assert p0_gy_ids.isdisjoint(p1_new_exile_ids), (
        f"p0-graveyard cards must NOT appear in p1's exile (cards "
        f"stay with their owner during ExileAllGraveyards); got "
        f"p0_gy_ids ∩ p1_new_exile = {p0_gy_ids & p1_new_exile_ids}"
    )
    assert p1_gy_ids.isdisjoint(p0_new_exile_ids), (
        f"p1-graveyard cards must NOT appear in p0's exile (cards "
        f"stay with their owner during ExileAllGraveyards); got "
        f"p1_gy_ids ∩ p0_new_exile = {p1_gy_ids & p0_new_exile_ids}"
    )
    # (4) Every exiled card carries Zone.EXILE + the owner_id matching
    # the player whose exile it sits in (zone stamp + owner-routing
    # double-check).
    for obj in p0_gy_objs:
        assert obj.zone == Zone.EXILE
        assert obj.owner_id == 0
        assert obj in py_state.players[0].exile
        assert obj not in py_state.players[1].exile
        assert obj not in py_state.players[0].graveyard
    for obj in p1_gy_objs:
        assert obj.zone == Zone.EXILE
        assert obj.owner_id == 1
        assert obj in py_state.players[1].exile
        assert obj not in py_state.players[0].exile
        assert obj not in py_state.players[1].graveyard
    # (5) Scavenger Grounds itself unchanged on bf — the resolve arm
    # does NOT touch the source. The tap-self + sacrifice-a-Desert
    # costs are out-of-band (paid by the activation machinery before
    # the resolve fires).
    assert py_source in py_state.battlefield
    assert py_source.zone == Zone.BATTLEFIELD
    assert len(py_state.battlefield) == bf_before
    # (6) Log entry — Python's resolve appends the canonical
    # ``"all graveyards exiled (5 cards)"`` count-stamp; an honest
    # mirror to Rust's silent-state-mutation arm (Rust also stamps
    # the same count via the per-player drain loop).
    assert len(py_state.log) == log_before_len + 1
    assert "all graveyards exiled (5 cards)" in py_state.log[-1], (
        f"Python resolve must append the 'all graveyards exiled "
        f"(<total> cards)' tombstone with total = 5 (2 + 3); got "
        f"log tail = {py_state.log[-3:]}"
    )


# ---------------------------------------------------------------------------
# (6) Per-owner-routing invariant — load-bearing one-sided pin.
# Beyond the both-populated mass line above, codify the cross-routing
# guard on the simpler one-sided case (ONLY p1's graveyard populated).
# Mirrors the C1 substrate's ``test_resolve_exile_all_graveyards_one_
# sided_graveyard`` pin on the Python side via the GENUINE parsed
# Scavenger Grounds Effect — same invariant lives on both engines.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_scavenger_grounds_per_owner_routing_one_sided_invariant_parity():
    """**GENUINE real-EoE probe — per-owner-routing one-sided pin.**

    With ONLY p1's graveyard populated (and p0's empty), Scavenger
    Grounds's ``ExileAllGraveyards`` resolve must move p1's cards
    INTO p1's exile only — NEVER into p0's exile. Codifies the
    load-bearing per-owner routing invariant on the asymmetric case
    that surfaces routing bugs the symmetric both-populated case can
    accidentally pass (e.g. if Python's resolve mistakenly used the
    activator's exile instead of the per-player exile).

    Python's ``ExileAllGraveyards.resolve`` iterates ``for p in
    state.players`` and appends to ``p.exile`` — owner-preserved by
    construction. Rust's mirror walks the same per-pidx loop. This
    pin makes the cross-routing bug structurally testable: if either
    engine's resolve ever mis-routed, the assertion that p0's exile
    gains ZERO new cards would fail.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Scavenger Grounds")
    if real is None:
        pytest.skip("Scavenger Grounds absent from active CardSource")

    forest = _PRINTINGS.get("Forest")
    if forest is None:
        pytest.skip("Forest absent from active CardSource")

    non_mana_aas = [
        aa for aa in (real.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert isinstance(aa.effect, ExileAllGraveyards)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat genuine Scavenger Grounds on p0's bf.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Populate ONLY p1's graveyard.
    p1_gy_objs = []
    for _ in range(2):
        obj = py_state.new_object(
            forest, owner_id=1, zone=Zone.GRAVEYARD,
        )
        py_state.players[1].graveyard.append(obj)
        p1_gy_objs.append(obj)

    # Pre-resolve snapshot.
    p0_exile_before_ids = {c.id for c in py_state.players[0].exile}
    p1_exile_before_ids = {c.id for c in py_state.players[1].exile}

    # Resolve.
    aa.effect.resolve(py_state, py_source.controller_id, targets=())

    # Post-resolve — p0's exile gained NOTHING (p0 had no graveyard
    # cards); p1's exile gained exactly the staged cards. This is
    # the load-bearing cross-routing guard.
    p0_new_exile_ids = (
        {c.id for c in py_state.players[0].exile} - p0_exile_before_ids
    )
    p1_new_exile_ids = (
        {c.id for c in py_state.players[1].exile} - p1_exile_before_ids
    )
    assert p0_new_exile_ids == set(), (
        f"p0's exile must gain ZERO cards (p0 had no graveyard cards "
        f"to exile); got new p0 exile ids = {p0_new_exile_ids}. "
        f"Any non-empty diff is a per-owner routing violation — the "
        f"Rust mirror must show the same empty diff."
    )
    expected_p1_new = {c.id for c in p1_gy_objs}
    assert p1_new_exile_ids == expected_p1_new, (
        f"p1's exile must gain exactly the p1-graveyard ids; got "
        f"new p1 exile ids = {p1_new_exile_ids}, expected = "
        f"{expected_p1_new}"
    )
    # All staged cards carry Zone.EXILE + owner_id == 1.
    for obj in p1_gy_objs:
        assert obj.zone == Zone.EXILE
        assert obj.owner_id == 1
        assert obj in py_state.players[1].exile
        assert obj not in py_state.players[0].exile
    # p0's graveyard stays empty; p1's graveyard is now empty.
    assert py_state.players[0].graveyard == []
    assert py_state.players[1].graveyard == []
