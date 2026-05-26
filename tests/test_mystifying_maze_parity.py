"""Mystifying Maze — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip; Carrier-AA Phase 3A
admit-set landing).

Mystifying Maze is a ``{0}`` Land in the EoE pool with a leading mana
ability ``{T}: Add {C}.`` plus a single non-mana activated ability:

    "{4}, {T}: Exile target attacking creature an opponent controls.
    At the beginning of the next end step, that player returns it to
    the battlefield under its owner's control tapped."

The Carrier-AA substrate Phase 3A (2026-05-25 — see
``docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md`` §7.1) closes in
THREE cycles: (C1) Rust substrate landing the two new ``Effect``
variants ``ExileTargetAttackingCreatureUntilEndStep`` +
``ReturnExiledPermanentToOwnerTapped`` plus the delayed-trigger
producer + the attacking-creature target fan-out + the 4 bridge arms
(``cross_engine.py`` ``_python_aa_to_safe_dict`` x2 forward emits +
``_ta_dict_to_python_effect`` x2 reverse parses) — landed at commit
``3de469a3``; (C2) Python admit widen — the
``_carrier_aa_phase_1_effect_classes`` lazy frozenset accessor at
``src/mtg_bot/parity/trajectory.py:8514`` extended to include
``ExileTargetAttackingCreatureUntilEndStep`` — landed at commit
``d1fd2037`` (Mystifying Maze's live AA shape is ``{4}, {T}``, the
Phase-1.5a ``{N}, {T}`` cost-gate is already wired, so the admit-gate
FLIPs DECLINED → ADMITTED on this widen alone); (C3) THIS PROBE —
real-EoE per-card byte-equal observable on both engines, covering
the GENUINE end-to-end exile-attacker-then-return-tapped-on-EoT
chain through the Python delayed-trigger machinery
(``state.delayed_triggers`` Vec + ``run_delayed_end_step_triggers``
dispatch + ``ReturnExiledPermanentToOwnerTapped`` resolve →
``put_into_battlefield`` + tapped). The Rust mirror lives in the C1
substrate's ``Effect::ExileTargetAttackingCreatureUntilEndStep``
resolve arm (schedules the same delayed trigger payload onto
``state.delayed_triggers``) plus the ``Effect::ReturnExiledPermanent
ToOwnerTapped`` arm (returns the exact card_id from the payload
to its owner's battlefield tapped).

Parser-emitted Effect shape:

    ``ExileTargetAttackingCreatureUntilEndStep()``  (unit-variant
    zero-arg frozen dataclass; no ``__post_init__`` stamps — the
    class is bare; ``requires_target=True`` + ``legal_targets``
    walks ``state.battlefield`` for opponent-controlled attacking
    creatures)

attached to an ``ActivatedAbility`` whose ``cost`` carries
``mana=ManaCost(generic=4)`` + ``tap_self=True`` (no sacrifice). The
bridge arm ``exile_target_attacking_creature_until_end_step``
(``cross_engine.py`` reverse arm at line 12493;
``cross_engine.py:14378`` ``_python_aa_to_safe_dict`` forward emit
arm) round-trips ``{"kind":
"exile_target_attacking_creature_until_end_step"}`` byte-equal to
Python's ``ExileTargetAttackingCreatureUntilEndStep()``.

**EEEE-idiom for the ActivatedAbility carrier.** Same lane discipline
as the sibling Carrier-AA AA probes (parse + bridge round-trip +
Python-side resolve): the probe drives the parsed Effect through its
actual ``resolve`` path on the Python state, with observables that
mirror what Rust's ``Effect::ExileTargetAttackingCreatureUntilEnd
Step`` resolve arm + the paired ``Effect::ReturnExiledPermanent
ToOwnerTapped`` arm produce on the same input shape. The cross-
engine byte-equal mirror is established by the Phase-3A admit gate
routing the genuine parsed Mystifying Maze printing through the
Carrier-AA substrate end-to-end (loader admits post-C2 — see the
C2 admit-set walk pin
``test_carrier_aa_30_no_silent_auto_grow_admit_set_swarmyard_plus_
deserted_temple_plus_petrified_field_plus_terrain_generator_plus_
mystifying_maze`` in ``test_carrier_aa_phase_1_substrate_cycle_2.py``).

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe binding
the Mystifying Maze slug to the AA +
``ExileTargetAttackingCreatureUntilEndStep`` Effect+bridge round-trip
on the REAL parsed EoE printing — and the FIRST PROBED-tier slot for
BOTH the ``ExileTargetAttackingCreatureUntilEndStep`` AND the paired
``ReturnExiledPermanentToOwnerTapped`` Effect classes via the
Carrier-AA substrate's ``{N}, {T}`` cost-shape disjunct. The two
Effect classes form one printed-text "exile then return at EoT"
oracle line; the cross-engine observable for the combined oracle
line is the load-bearing end-to-end exile-and-then-return-tapped
chain pinned in the load-bearing test below.

**AA-cost-substrate scope.** The mana-payment (``{4}``) /
tap-payment cost trajectory of the AA is exercised at the loader-
end-to-end disjunct (Mystifying Maze passes
``_printing_is_bridge_simple_carrier_aa_land`` post-C2 widen + the
cross-engine bridge round-trip pin below); per-slug PROBED
attribution credits Mystifying Maze based on the Effect + bridge
byte-equality + parsed-printing resolve smoke alone — the canonical
EEEE-idiom precedent (Petrified Field's Phase-2a probe at
``tests/test_petrified_field_parity.py`` / Terrain Generator's
Phase-2b probe at ``tests/test_terrain_generator_parity.py`` /
Deserted Temple's Phase-1.5a probe at
``tests/test_deserted_temple_parity.py``).

**Delayed-trigger contract (load-bearing).** Python's
``ExileTargetAttackingCreatureUntilEndStep.resolve`` (exile.py:210)
appends a dict to ``state.delayed_triggers`` with shape
``{"fire_at_turn": <current turn>, "controller_id": <active player>,
"effect": ReturnExiledPermanentToOwnerTapped(exile_card_id=<id>),
"source_id": <maze id>}``. At the active player's next end step,
``run_delayed_end_step_triggers`` (turn.py:773) sees the
``fire_at_turn == turn_number`` AND ``controller_id == active_player``
match, synthesizes a TriggeredAbility wrapping the
ReturnExiledPermanentToOwnerTapped effect, pushes it onto the stack
via ``push_triggered_ability``, and the standard
``resolve_top_of_stack`` path drains the stack. The
ReturnExiledPermanentToOwnerTapped resolve (exile.py:98) walks every
player's exile zone for ``card.id == exile_card_id``, removes from
exile, routes the card through ``put_into_battlefield`` (ETB triggers
fire normally), then sets ``card.tapped = True``. The Rust mirror at
``state_ops_resolve.rs`` walks the same payload shape byte-equal.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.exile import (
    ExileTargetAttackingCreatureUntilEndStep,
    ReturnExiledPermanentToOwnerTapped,
)


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


def _pick_simple_creature_printing():
    """Return the FIRST parser-claimed creature printing that is a
    plain non-token Creature with a printed power/toughness. Used as
    the opponent's attacker in the load-bearing end-to-end probe;
    the exact identity is unimportant — the cross-engine observable
    is the zone-move and tapped-state of the attacker, not its body."""
    for name, pr in _PRINTINGS.items():
        if "Creature" not in pr.card_types:
            continue
        if pr.power is None or pr.toughness is None:
            continue
        # Skip token printings (token_printings would not be in
        # _PRINTINGS anyway, but defensive).
        if getattr(pr, "is_token", False):
            continue
        return name, pr
    raise RuntimeError(
        "No plain creature printing found in active CardSource — "
        "every EoE deck pool carries at least one"
    )


# ---------------------------------------------------------------------------
# (1) Parser SoT — Mystifying Maze is parser-claimed and carries the
# exact AA shape the design doc (§7.1) pins.
# ---------------------------------------------------------------------------


def test_mystifying_maze_parser_claims_card():
    assert "Mystifying Maze" in _PRINTINGS, (
        "Mystifying Maze must be parser-claimed by the active "
        "CardSource"
    )


def test_mystifying_maze_printed_attrs():
    """Pins the basic printing surface: single-typed Land, no mana
    cost, no power/toughness, no triggered / static / keyword riders.
    The leading ``{T}: Add {C}`` mana ability lives in the parser-
    synthesized mana-ability slot, NOT on the carrier surface; the
    carrier AA (the exile-attacker AA) is the SECOND activated_
    abilities entry."""
    p = _PRINTINGS["Mystifying Maze"]
    assert p.card_types == ("Land",)
    assert p.subtypes == ()
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert p.power is None and p.toughness is None
    assert p.keywords == frozenset()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


def test_mystifying_maze_activated_ability_exile_attacker_shape():
    """Mystifying Maze has the single carrier ``ActivatedAbility``
    whose effect is ``ExileTargetAttackingCreatureUntilEndStep()``
    (unit variant, no fields). Cost is ``{4}, {T}`` — the Phase-1.5a
    widened cost-gate shape."""
    p = _PRINTINGS["Mystifying Maze"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) == 1, (
        f"Mystifying Maze must have exactly one non-mana "
        f"ActivatedAbility; got {len(non_mana_aas)}"
    )
    aa = non_mana_aas[0]
    # Effect shape.
    assert isinstance(aa.effect, ExileTargetAttackingCreatureUntilEndStep), (
        f"Mystifying Maze AA effect must be "
        f"ExileTargetAttackingCreatureUntilEndStep; got "
        f"{type(aa.effect).__name__}"
    )
    # Cost shape — the Phase-3A load-bearing axis.
    assert aa.cost.tap_self is True
    assert aa.cost.sacrifice_self is False, (
        "Mystifying Maze's AA carries NO sacrifice_self (cost is "
        "just ``{4}, {T}``)"
    )
    assert aa.cost.mana is not None, (
        "Mystifying Maze's AA cost carries ``{4}`` mana component"
    )
    assert aa.cost.mana.generic == 4
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
    # The Effect declares itself targeted (CR 608.2b — re-validate at
    # resolve), and its targeting filter is "attacking creature an
    # opponent controls" via legal_targets at runtime.
    assert aa.effect.requires_target() is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the exile_target_attacking_creature_until_
# end_step dict shape round-trips byte-equal to the parsed printing's
# emitted Effect.
# ---------------------------------------------------------------------------


def test_mystifying_maze_bridge_arm_round_trip():
    """The bridge arm ``exile_target_attacking_creature_until_end_step``
    (cross_engine.py:12493) round-trips
    ``{"kind": "exile_target_attacking_creature_until_end_step"}`` to
    the matching Python ``ExileTargetAttackingCreatureUntilEndStep()``
    instance — unit variant, no fields.

    Effect-level byte-equality between the parsed real-EoE printing's
    emitted ``ExileTargetAttackingCreatureUntilEndStep`` Effect and
    the bridged Effect: the structural contract for the PROBED tier."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "exile_target_attacking_creature_until_end_step"}
    )
    assert isinstance(bridged, ExileTargetAttackingCreatureUntilEndStep)

    p = _PRINTINGS["Mystifying Maze"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert aa.effect == bridged, (
        f"Mystifying Maze AA Effect must be byte-equal to the "
        f"bridged Effect "
        f"(ExileTargetAttackingCreatureUntilEndStep() unit-variant "
        f"structural contract); got parsed={aa.effect!r}, "
        f"bridged={bridged!r}"
    )


def test_mystifying_maze_paired_return_arm_round_trip():
    """**Phase 3A paired-arm pin.** The bridge arm
    ``return_exiled_permanent_to_owner_tapped`` (cross_engine.py:12522)
    round-trips ``{"kind": "return_exiled_permanent_to_owner_tapped",
    "exile_card_id": <int>}`` byte-equal to Python's
    ``ReturnExiledPermanentToOwnerTapped(exile_card_id=<int>)``.

    Unlike the bare exile-attacker Effect (unit variant), this paired
    arm carries the ``exile_card_id`` integer payload — the exact
    card id captured at exile-resolve time by
    ``ExileTargetAttackingCreatureUntilEndStep.resolve`` and stored
    on the ``state.delayed_triggers`` dict entry. The Rust mirror
    serializes the same field via the C1 substrate's paired-arm
    parse + emit + to_pydict arms.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "return_exiled_permanent_to_owner_tapped",
            "exile_card_id": 17,
        }
    )
    assert isinstance(bridged, ReturnExiledPermanentToOwnerTapped)
    assert bridged.exile_card_id == 17, (
        "ReturnExiledPermanentToOwnerTapped.exile_card_id must "
        "round-trip byte-equal from the bridged dict"
    )
    # Equal via dataclass __eq__.
    assert bridged == ReturnExiledPermanentToOwnerTapped(exile_card_id=17)


def test_mystifying_maze_aa_round_trip_through_safe_dict():
    """The bridge's ``_python_aa_to_safe_dict`` ↔
    ``_aa_dict_to_python_activated_ability`` round-trip applied to the
    genuine parsed Mystifying Maze AA emits the canonical
    ``{"cost": {"mana": {"generic": 4}, "tap_self": True}, "effect":
    {"kind": "exile_target_attacking_creature_until_end_step"}}``
    dict and rebuilds a byte-equal Python ActivatedAbility on the
    load-bearing fields (cost atoms + Effect + AA-rider fields). The
    cost-side ``mana_str`` display-string field is parser-only and is
    NOT round-tripped through the bridge (UI-side annotation; both
    engines ignore it for activation semantics — same convention as
    the Deserted Temple / Petrified Field / Terrain Generator
    probes)."""
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    p = _PRINTINGS["Mystifying Maze"]
    non_mana_aas = [
        aa for aa in (p.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    safe = _python_aa_to_safe_dict(aa)
    assert safe is not None, (
        "_python_aa_to_safe_dict must accept Mystifying Maze's "
        "parsed AA post-Phase-3A — the C2 Effect-class widen + "
        "Phase-1.5a cost-gate gate admit this shape"
    )
    assert safe == {
        "cost": {"mana": {"generic": 4}, "tap_self": True},
        "effect": {
            "kind": "exile_target_attacking_creature_until_end_step",
        },
    }
    back = _aa_dict_to_python_activated_ability(safe)
    assert back.effect == aa.effect
    assert back.cost.mana == aa.cost.mana
    assert back.cost.tap_self == aa.cost.tap_self
    assert back.cost.sacrifice_self == aa.cost.sacrifice_self
    assert back.is_mana_ability == aa.is_mana_ability
    assert back.sorcery_speed == aa.sorcery_speed
    assert back.cost_reductions == aa.cost_reductions
    assert back.room_half == aa.room_half
    assert back.tier_threshold == aa.tier_threshold
    assert back.activate_only_once == aa.activate_only_once


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts a
# Mystifying-Maze-shape dict (carrier AA with ``{4}, {T}`` cost +
# ``ExileTargetAttackingCreatureUntilEndStep`` effect). Exercises the
# Rust ``parse_effect`` arm for the
# ``exile_target_attacking_creature_until_end_step`` kind landed in
# the Phase-3A C1 substrate.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_mystifying_maze_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` +
    ``parse_activated_ability`` arms accept a Mystifying-Maze-shape
    dict (single AA with
    ``{"cost": {"mana": {"generic": 4}, "tap_self": True}, "effect":
    {"kind": "exile_target_attacking_creature_until_end_step"}}``) on
    a Land carrier. The Phase-3A C1 substrate (commit ``3de469a3``)
    shipped the variant + parse arms + resolve arm (delayed-trigger
    producer) + cross-engine bridge arms in lockstep; this pin
    confirms the end-to-end Rust acceptance under the Phase-3A C2
    Effect-class widen."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Mystifying Maze (synthetic carrier)",
            "card_types": ["Land"],
            "mana_cost": {"generic": 0},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {
                        "tap_self": True,
                        "mana": {"generic": 4},
                    },
                    "effect": {
                        "kind": "exile_target_attacking_creature_until_end_step",
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) Carrier-AA loader admit pin — the Phase-3A admit-set end-to-end:
# ``_filter_deck_to_bridge_supported`` admits Mystifying Maze through
# the Carrier-AA disjunct, the resulting CardDef carries the canonical
# AA dict shape ready for ``build_rust_state`` to emit into the Rust
# registry.
# ---------------------------------------------------------------------------


def test_mystifying_maze_carrier_aa_loader_end_to_end_admit():
    """**Phase 3A end-to-end pin.** The production-deck loader
    (``_filter_deck_to_bridge_supported``) admits Mystifying Maze
    through the Carrier-AA Phase 3A disjunct. The returned CardDef
    carries the single non-token AA dict with the canonical Phase-1.5a
    cost shape + Phase-3A ``ExileTargetAttackingCreatureUntilEndStep``
    effect — Rust-side ``build_rust_state`` consumes it via the
    Phase-3A C1 substrate emit arm (no other code path needed)."""
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Mystifying Maze"], _PRINTINGS,
    )
    assert filtered == ["Mystifying Maze"]
    assert len(card_defs) == 1
    card_def = card_defs[0]
    assert card_def.name == "Mystifying Maze"
    assert card_def.card_type == "Land"
    assert card_def.mana_produced == ()
    assert card_def.triggered_abilities == ()
    assert card_def.keywords == ()
    assert card_def.token_activated_abilities == ()
    aas = card_def.activated_abilities
    assert len(aas) == 1
    aa_dict = aas[0]
    assert aa_dict["cost"] == {
        "tap_self": True,
        "mana": {"generic": 4},
    }
    assert aa_dict["effect"] == {
        "kind": "exile_target_attacking_creature_until_end_step",
    }


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Mystifying Maze printing's AA through its
# ``ExileTargetAttackingCreatureUntilEndStep`` Effect resolve path on
# the Python side, mirroring Rust's
# ``Effect::ExileTargetAttackingCreatureUntilEndStep`` resolve arm
# (the C1 substrate landing at commit ``3de469a3``). The probe asserts
# the two observables the design doc §7.1 pins:
#   (a) baseline silent fizzle when no eligible target exists
#       (legal_targets is empty; resolve with empty targets is a no-op
#       with NO delayed-trigger scheduled and NO state mutation);
#   (b) load-bearing exile-now-then-return-tapped-on-EoT line — the
#       full end-to-end chain through state.delayed_triggers +
#       run_delayed_end_step_triggers + ReturnExiledPermanentToOwner
#       Tapped resolve.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_mystifying_maze_baseline_no_eligible_target_fizzle_parity():
    """**GENUINE real-EoE probe — baseline silent-fizzle line.**

    Drives the parsed Mystifying Maze AA's
    ``ExileTargetAttackingCreatureUntilEndStep`` Effect via
    ``resolve(state, controller_id, targets=())`` on a battlefield with
    ZERO attacking creatures (the source — Maze itself — is on the
    battlefield, but no opponent attacker exists, and Maze is not a
    creature). Python's
    ``ExileTargetAttackingCreatureUntilEndStep.resolve`` (exile.py:210)
    early-returns on empty ``targets`` (``if not targets: return`` at
    exile.py:216). Rust's
    ``Effect::ExileTargetAttackingCreatureUntilEndStep`` resolve arm
    silently fizzles in the same shape — no panic, no state mutation,
    no delayed-trigger scheduled, no exile move. Byte-equal mirror.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Mystifying Maze")
    if real is None:
        pytest.skip("Mystifying Maze absent from active CardSource")

    non_mana_aas = [
        aa for aa in (real.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert isinstance(aa.effect, ExileTargetAttackingCreatureUntilEndStep)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the genuine parsed Mystifying Maze on p0's bf (the AA
    # source). Untapped. Empty battlefield otherwise — no attackers.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Pre-resolve sanity — the legal-targets walk yields the empty
    # list (no attacking creature an opponent controls).
    assert (
        aa.effect.legal_targets(py_state, py_source.controller_id) == []
    )

    # Pre-resolve state snapshot.
    bf_before = len(py_state.battlefield)
    delayed_before = len(py_state.delayed_triggers)
    p0_exile_before = len(py_state.players[0].exile)
    p1_exile_before = len(py_state.players[1].exile)
    log_before = len(py_state.log)

    # Resolve with empty targets — silent fizzle on no attacker.
    # Set resolving_source the same way the stack resolver would.
    py_state.resolving_source = py_source
    try:
        aa.effect.resolve(py_state, py_source.controller_id, targets=())
    finally:
        py_state.resolving_source = None

    # State invariants — no zone moves, no delayed-trigger scheduled,
    # no log entry added (Python's resolve appends the "is exiled
    # until end of turn" log line ONLY after a target is found).
    assert len(py_state.battlefield) == bf_before
    assert len(py_state.delayed_triggers) == delayed_before, (
        "No delayed trigger must be scheduled on fizzle"
    )
    assert len(py_state.players[0].exile) == p0_exile_before
    assert len(py_state.players[1].exile) == p1_exile_before
    assert len(py_state.log) == log_before, (
        "No log entry on fizzle (resolve never reached the "
        "'is exiled until end of turn' append)"
    )


def test_cross_engine_real_eoe_mystifying_maze_exile_then_return_at_end_step_line_parity():
    """**GENUINE real-EoE probe — load-bearing exile-attacker-then-
    return-tapped-on-EoT line. PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the FULL end-to-end Mystifying Maze chain through the
    Python delayed-trigger machinery, asserting every observable
    Rust's paired ``Effect::ExileTargetAttackingCreatureUntilEndStep``
    + ``Effect::ReturnExiledPermanentToOwnerTapped`` arms produce
    byte-equal on the same input.

    Setup:
      * Mystifying Maze on p0's battlefield (the AA source);
      * an opponent (p1) creature in attacking=True state on p0's
        bf (the AA target — Maze's
        ``legal_targets`` filter is "attacking creature an opponent
        controls").

    Phase 1 — exile resolve. Python's
    ``ExileTargetAttackingCreatureUntilEndStep.resolve``:

      * matches the target by id on state.battlefield;
      * appends ``"<attacker> is exiled until end of turn"`` to
        state.log;
      * routes the attacker through ``move_off_battlefield(...,
        destination='exile')`` — zone -> EXILE, removed from bf,
        appended to owner (p1)'s exile;
      * captures the attacker's id + Maze's id into a delayed-trigger
        dict
        ``{"fire_at_turn": <turn>, "controller_id": <active player>,
        "effect": ReturnExiledPermanentToOwnerTapped(exile_card_id=
        <attacker.id>), "source_id": <maze.id>}`` appended to
        ``state.delayed_triggers``.

    Phase 2 — delayed trigger fires at next end step.
    ``run_delayed_end_step_triggers`` (turn.py:773):

      * sees the entry's ``fire_at_turn == state.turn_number`` AND
        ``controller_id == active_player.id`` match (Maze is
        activated at instant speed, scheduling for the active player
        — same turn);
      * looks up Maze on the live battlefield by source_id (still
        there);
      * synthesizes a ``TriggeredAbility`` wrapping the
        ``ReturnExiledPermanentToOwnerTapped(exile_card_id=...)``
        effect with ``event=Event.BEGINNING_OF_END_STEP`` +
        ``predicate=Always()``;
      * pushes onto the stack via ``push_triggered_ability`` (logged
        as "Mystifying Maze's delayed trigger goes on the stack").

    Phase 3 — resolve top of stack.
    ``ReturnExiledPermanentToOwnerTapped.resolve`` (exile.py:98):

      * walks every player's exile zone for ``card.id ==
        exile_card_id`` — finds the attacker in p1's exile;
      * removes from exile, routes through ``put_into_battlefield(
        state, card, owner.id)`` — owner is p1, so the attacker
        returns to p1's bf under p1's control (the printed text
        explicitly says "under its owner's control");
      * sets ``card.tapped = True`` (per the printed text "tapped");
      * appends ``"<attacker> returns from exile to P1's battlefield
        tapped"`` to state.log.

    Rust's paired arms walk the same chain byte-equal: the C1
    substrate at commit ``3de469a3`` schedules the same payload onto
    ``state.delayed_triggers`` Vec and the end-step dispatch at
    ``run_delayed_end_step_triggers`` (state_ops_steps.rs:434) pushes
    the ReturnExiledPermanentToOwnerTapped arm onto the stack.

    The cross-engine mirror is established by:

      1. Parse SoT (test #3 above) — same AA shape on both engines.
      2. Bridge round-trip (test #4 above) — byte-equal Effect dict.
      3. Paired-arm bridge round-trip (test #5 above) — byte-equal
         ``ReturnExiledPermanentToOwnerTapped`` dict with exile_card_id
         field carried byte-equal.
      4. Rust synthetic-carrier acceptance (test #6 above) — Rust
         parses the same dict shape.
      5. End-to-end loader admit (test #7 above) — the
         ``_filter_deck_to_bridge_supported`` admit path threads the
         genuine printing into the Rust registry.
      6. This pin's Python-side resolve smoke — drives the Effect
         through the same resolve contract Rust's arm mirrors.

    The post-chain observables (the attacker moves bf → exile →
    bf-tapped over two phases; Maze stays untouched; Maze's tap +
    mana costs are out-of-band of these resolve arms — paid by the
    activation machinery before the exile resolve fires) are
    byte-equal on both engines.
    """
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone
    from mtg_bot.turn import run_delayed_end_step_triggers

    real = _PRINTINGS.get("Mystifying Maze")
    if real is None:
        pytest.skip("Mystifying Maze absent from active CardSource")

    _creature_name, creature_pr = _pick_simple_creature_printing()

    non_mana_aas = [
        aa for aa in (real.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    aa = non_mana_aas[0]
    assert isinstance(aa.effect, ExileTargetAttackingCreatureUntilEndStep)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat genuine Mystifying Maze on p0's bf — untapped (the AA
    # source). p0 is the active player by default in build_python_state.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Seat an opponent creature on p1's bf, in attacking=True state
    # (the AA's target — Maze's legal_targets filter is "attacking
    # creature an opponent controls").
    py_attacker = py_state.new_object(
        creature_pr, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_attacker.attacking = True
    py_attacker.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_attacker)

    # Pre-chain sanity — legal_targets yields exactly the attacker.
    legals = aa.effect.legal_targets(py_state, py_source.controller_id)
    assert legals == [("creature", py_attacker.id)], (
        f"legal_targets must yield exactly the opponent's attacker; "
        f"got {legals}"
    )

    # Pre-chain state snapshot.
    bf_before = len(py_state.battlefield)
    p1_exile_before = len(py_state.players[1].exile)
    p1_bf_count_before = sum(
        1 for o in py_state.battlefield if o.controller_id == 1
    )
    active_player_id = py_state.active_player().id
    turn_before = py_state.turn_number

    # ===========================================================
    # Phase 1 — exile resolve. Byte-equal mirror to Rust's
    # ``Effect::ExileTargetAttackingCreatureUntilEndStep`` resolve
    # arm. The Effect resolves with the targeted attacker; Maze is
    # set as the resolving_source per the standard stack-resolution
    # plumbing.
    # ===========================================================
    py_state.resolving_source = py_source
    try:
        aa.effect.resolve(
            py_state, py_source.controller_id,
            targets=(("creature", py_attacker.id),),
        )
    finally:
        py_state.resolving_source = None

    # Post-exile observables.
    assert py_attacker.zone == Zone.EXILE, (
        "The attacker must transition battlefield → exile"
    )
    assert py_attacker in py_state.players[1].exile, (
        "The attacker must be in its owner (p1)'s exile zone"
    )
    assert py_attacker not in py_state.battlefield, (
        "The attacker must be removed from the centralized bf"
    )
    assert len(py_state.players[1].exile) == p1_exile_before + 1
    assert len(py_state.battlefield) == bf_before - 1
    # Delayed trigger scheduled with the canonical payload.
    assert len(py_state.delayed_triggers) == 1, (
        f"Exactly one delayed trigger must be scheduled; got "
        f"{len(py_state.delayed_triggers)}"
    )
    entry = py_state.delayed_triggers[0]
    assert entry["fire_at_turn"] == turn_before, (
        "fire_at_turn must be the current turn (Maze is activated "
        "at instant speed on the same turn the end-step return "
        "trigger fires)"
    )
    assert entry["controller_id"] == active_player_id, (
        "controller_id on the delayed trigger must be the active "
        "player (Maze's controller). The active player owns the EoT "
        "trigger per CR 603.7c"
    )
    assert isinstance(entry["effect"], ReturnExiledPermanentToOwnerTapped)
    assert entry["effect"].exile_card_id == py_attacker.id, (
        "The delayed trigger's effect must carry the exiled "
        "attacker's id"
    )
    assert entry["source_id"] == py_source.id, (
        "The delayed trigger's source_id must point at Mystifying "
        "Maze (for the stack-time source resolution)"
    )
    assert any(
        "is exiled until end of turn" in entry_log
        for entry_log in py_state.log
    ), "Python resolve must append the 'is exiled until end of turn' log"

    # ===========================================================
    # Phase 2 — delayed trigger fires at next end step (same turn,
    # active-player p0). ``run_delayed_end_step_triggers`` pushes the
    # synthesized TriggeredAbility onto the stack. Byte-equal mirror
    # to Rust's end-step dispatch arm.
    # ===========================================================
    stack_before = len(py_state.stack)
    run_delayed_end_step_triggers(py_state)
    # The delayed-triggers list is drained; the trigger now lives on
    # the stack as a real TriggeredAbility.
    assert py_state.delayed_triggers == [], (
        "The delayed-triggers queue must be drained after the "
        "fire-now scan"
    )
    assert len(py_state.stack) == stack_before + 1, (
        "Exactly one TriggeredAbility must be pushed onto the stack"
    )

    # ===========================================================
    # Phase 3 — resolve top of stack. Byte-equal mirror to Rust's
    # ``Effect::ReturnExiledPermanentToOwnerTapped`` resolve arm.
    # ===========================================================
    resolve_top_of_stack(py_state)

    # Post-chain observables.
    assert py_attacker.zone == Zone.BATTLEFIELD, (
        "The attacker must transition exile → battlefield"
    )
    assert py_attacker in py_state.battlefield, (
        "The attacker must be back on the centralized bf"
    )
    assert py_attacker not in py_state.players[1].exile, (
        "The attacker must be removed from its owner's exile"
    )
    assert py_attacker.tapped is True, (
        "The attacker must be tapped (the printed text 'tapped')"
    )
    assert py_attacker.owner_id == 1, (
        "The attacker's owner_id must remain p1 (zone moves do NOT "
        "change ownership)"
    )
    assert py_attacker.controller_id == 1, (
        "The attacker must come back under its OWNER's control "
        "(the printed text: 'under its owner's control'); "
        "p1 is both owner and controller post-return"
    )
    # Mystifying Maze itself unchanged on bf — the resolve arms
    # do NOT touch the source.
    assert py_source in py_state.battlefield
    assert py_source.zone == Zone.BATTLEFIELD
    # Battlefield population net-zero (attacker left + came back).
    p1_bf_count_after = sum(
        1 for o in py_state.battlefield if o.controller_id == 1
    )
    assert p1_bf_count_after == p1_bf_count_before, (
        "Net p1 battlefield count must be unchanged across the full "
        "exile-then-return chain"
    )
    # Log entry — Python's ReturnExiledPermanentToOwnerTapped resolve
    # appends "<name> returns from exile to P1's battlefield tapped";
    # an honest mirror to Rust's silent-state-mutation arm.
    assert any(
        "returns from exile" in entry_log
        and "P1's battlefield tapped" in entry_log
        for entry_log in py_state.log
    ), (
        f"Python resolve must append the '<name> returns from exile "
        f"to P1's battlefield tapped' log entry; "
        f"got log tail={py_state.log[-10:]}"
    )
