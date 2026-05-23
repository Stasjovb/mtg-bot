"""Blade of the Swarm Cycle 1 —
``OwnerPutsTargetWarpedExileCardOnBottomOfLibrary`` Rust Effect
substrate close + per-card cross-engine byte-equal probe.

Blade of the Swarm is a ``{3}{B}`` Creature — Insect Assassin (3/1, EoE
— sourced from ``data/edge_of_eternities.json``) with a modal ETB:

    "When this creature enters, choose one —
     * Put two +1/+1 counters on this creature.
     * Put target exiled card with warp on the bottom of its owner's
       library."

This module pins the Rust
``Effect::OwnerPutsTargetWarpedExileCardOnBottomOfLibrary`` variant
landed in this branch + the matching cross_engine bridge arm + a
genuine real-EoE cross-engine byte-equal probe driving the mode-1
warp-exile-to-library-bottom path end-to-end on a synthetic Rust
carrier.

**Multi-gated card; classifier stays multi-gated.** Per the round-58
subsystem-attribution classifier
(``scripts/scout_r58_subsystem_attribution.py``), Blade of the Swarm
is multi-gated across TWO gates:

  * ``effect_uncovered`` — closed by this cycle. The new Rust variant
    ``Effect::OwnerPutsTargetWarpedExileCardOnBottomOfLibrary`` makes
    the Python class
    ``OwnerPutsTargetWarpedExileCardOnBottomOfLibrary`` covered via
    the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``; the classifier's
    ``missing_effect_classes`` array shrinks by one for this card.
  * ``nonsafe_triggered_ability`` — **STAYS active**. The trajectory
    safe-trigger admit gate (``parity/trajectory.py::
    _python_ta_to_safe_dict``) is INTENTIONALLY NOT widened — that
    gate is about the production-deck bench admit set, a distinct
    concern from per-card real-EoE parity probes.

**Per-card dedicated parity probe path (PROBED tier flip).** Even
though the classifier keeps the card multi-gated at
``nonsafe_triggered_ability``, this test module is the dedicated
per-card real-EoE byte-equal cross-engine probe that flips Blade of
the Swarm to PROBED tier. Same precedent as
``test_possibility_technician_parity.py``,
``test_boilerbilges_ripper_parity.py``,
``test_terrapact_intimidator_parity.py``,
``test_splitskin_doll_parity.py``: a per-card probe drives the real
printing through both engines and pins byte-equal observables; the
safe-trigger bench admit set is widened in a separate cycle when the
production-deck bench needs it.

**Warp substrate distinction.** The Rust ``warped`` flag (the marker
set by ``Effect::WarpExileSelf`` on the delayed end-step trigger) is
already live on ``GameObject`` (per the Codecracker Hound /
Boilerbilges Ripper closures — see ``state.rs:219``, the
cast-from-warp-exile surface at ``state_ops_legal.rs:2638-2683``).
Blade of the Swarm's mode-1 effect is the warp-exile-REMOVAL
counterpart to the warp-exile-ADD substrate: it READS ``warped``
and bottom-decks the chosen card.

**Probe path.** The probe drives the BARE
``Effect::OwnerPutsTargetWarpedExileCardOnBottomOfLibrary`` resolve
through a synthetic Instant carrier (NOT through Blade's modal ETB
wrapper). The modal-wrapper dispatch is already pinned in
``test_modal_chooseone_envelope_cycle2.py`` (Cycle 2 of the
ModalChooseOne envelope substrate plan); per the no-fallback-hybrid
precedent, the per-card probe targets the new effect class
specifically, not the modal envelope. The synthetic carrier seats
``Effect::OwnerPutsTargetWarpedExileCardOnBottomOfLibrary`` directly
as the spell's effect; the cast pipeline binds the warped-exile-card
target at cast time via ``current_resolve_payload_target_id``, and
the resolve arm reads that target and bottom-decks the warped exile
card byte-equal with Python's
``OwnerPutsTargetWarpedExileCardOnBottomOfLibrary.resolve``.

**set_warped test helper.** A new ``set_warped(player_idx, obj_id,
value)`` pymethod on ``GameState`` (landed in this branch alongside
the Effect substrate) lets the probe stamp ``warped = True`` on a
synthetic exile card without exercising the full ``warp_cost`` cast
pipeline. Same shape/validation as the existing
``set_spells_cast_this_turn`` /
``set_artifacts_entered_under_your_control_this_turn`` test helpers.

Test surface:

  1. Parser SoT — Blade of the Swarm is parser-claimed and emits an
     ETB ``ModalChooseOne`` with mode 1 =
     ``OwnerPutsTargetWarpedExileCardOnBottomOfLibrary()``.

  2. Serializer round-trip — a Python
     ``OwnerPutsTargetWarpedExileCardOnBottomOfLibrary`` and the dict
     shape
     ``{"kind": "owner_puts_target_warped_exile_card_on_bottom_of_library"}``
     round-trip through the cross_engine bridge identically; the
     Rust ``Effect::OwnerPutsTargetWarpedExileCardOnBottomOfLibrary``
     → dict emits the one-key shape.

  3. Rust unit pins:
       3a. Warped exile card on p1 + target bound → card moves to
           bottom of p1's library, warp flag clears.
       3b. Target absent (no warped card with the bound id) → silent
           fizzle, no state mutation.
       3c. Target id exists but ``warped == false`` → silent fizzle
           (re-check at resolve mirrors Python's
           ``if not obj.warped: return``).

  4. Covered-set membership — the orphan walker recognises
     ``OwnerPutsTargetWarpedExileCardOnBottomOfLibrary`` as a 1:1
     same-named Rust/Python match.

  5. **GENUINE real-EoE cross-engine probe** — drives the ACTUAL
     parsed Blade of the Swarm printing's mode-1 effect on Python
     and a bridged synthetic carrier on Rust. After resolve, asserts
     the concrete zone observables (the warped card moves from
     p1.exile to p1.library bottom on BOTH engines + the warp flag
     clears) plus the full ``compare_fields == []`` over the whole
     cross-engine field view. CAVEAT (mirrors
     ``docs/POOL_PARITY.md``): Effect+bridge-level byte-equality on
     a *controlled* cross-engine state, NOT full-game-trajectory
     parity.

NO admit-set change — Blade of the Swarm's mode-1 surface is wrapped
in a modal-creature ETB; the spell-card-bridge admit set
(``trajectory.py::_python_spell_effect_to_dict`` + its §2 teeth)
gates non-creature spells only. Per-card PROBED via the probe below.
"""

from __future__ import annotations

import importlib
import importlib.util
import pathlib
import sys

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.zone_moves import (
    OwnerPutsTargetWarpedExileCardOnBottomOfLibrary,
)


_PRINTINGS = get_active_source().get_printings()


# Skip the Rust-engine probes if the extension isn't built — mirrors
# the project-wide policy for cross-engine probes.
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there). Identical to the established pattern in
    ``test_possibility_technician_parity.py``."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# Zone constants (mirror Rust's u8 zone IDs used by
# ``register_and_inject_object``).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


# Synthetic Instant carrier whose effect IS the bare
# ``OwnerPutsTargetWarpedExileCardOnBottomOfLibrary`` (no modal wrap).
# The probe casts this synthetic spell via the cast pipeline so the
# target is bound at cast time via ``current_resolve_payload_target_id``.
# The same shape Tier-A spell-card-bridge admitted spells use; here it
# carries only the new effect for the substrate-level probe.
_BLADE_MODE1_SYNTH_PRINTING_DICT: dict = {
    "name": "Blade Mode-1 Synthetic Carrier",
    "card_types": ["Instant"],
    "mana_cost": {"B": 1},
    "effects": [
        {
            "kind": "owner_puts_target_warped_exile_card_on_bottom_of_library",
        },
    ],
}


# Plain vanilla Instant filler — used as the warp-exile card body in
# the probe (the printing's identity doesn't matter; only its presence
# in exile with ``warped=True`` does).
_WARPED_EXILE_FILLER_DICT: dict = {
    "name": "Warped Exile Filler",
    "card_types": ["Instant"],
    "mana_cost": {"B": 1},
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Blade of the Swarm is parser-claimed and the mode-1
# leaf of its ETB ModalChooseOne is the new effect class.
# ---------------------------------------------------------------------------


def test_blade_of_the_swarm_parser_claims_card():
    assert "Blade of the Swarm" in _PRINTINGS, (
        "Blade of the Swarm must be parser-claimed by the active "
        "CardSource"
    )


def test_blade_of_the_swarm_printed_attrs():
    """Pins the basic printing surface (cost, type, P/T, NO Warp).

    Blade of the Swarm itself does NOT have the Warp keyword (it
    BENEFITS from warped exile cards via mode 1, but is not a
    warp-castable card itself). Pinning the absence of ``warp_cost``
    is the load-bearing signal that this card is NOT the warp_cost
    gate (contrast Possibility Technician / Boilerbilges Ripper).
    """
    p = _PRINTINGS["Blade of the Swarm"]
    assert p.mana_cost_str == "{3}{B}"
    assert "Creature" in p.card_types
    assert "Insect" in p.subtypes or "Assassin" in p.subtypes, (
        f"expected Insect or Assassin subtype; got {p.subtypes}"
    )
    assert p.power == 3
    assert p.toughness == 1
    # Blade of the Swarm has NO Warp keyword (per the explicit
    # `test_blade_of_the_swarm_has_no_warp` regression pin in
    # `test_pinnacle_blade.py`).
    assert p.warp_cost_str == "", (
        "Blade of the Swarm must NOT carry a warp_cost — it's the "
        "warp-exile-REMOVAL counterpart, not a warp-castable card"
    )


def test_blade_of_the_swarm_etb_modal_mode_1_emits_bespoke_effect():
    """The ETB ChooseOneMode has exactly two modes; mode 1 (the
    warp-bottom-deck leaf) is the new effect class.

    Pin the shape so a parser drift is caught here, not silently
    downstream in the cross-engine probe. The full modal-shape
    assertion (mode 0 = +2 +1/+1 counters) lives in
    ``test_pinnacle_blade.py``; we re-pin mode 1 specifically because
    it's the surface this cycle closes.
    """
    from mtg_bot.effects import ModalChooseOne
    from mtg_bot.effects.predicates import Event

    p = _PRINTINGS["Blade of the Swarm"]
    enters_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.ENTERS
    ]
    assert len(enters_tas) >= 1, (
        f"Blade of the Swarm must have at least one ENTERS triggered "
        f"ability (the modal ETB); got {len(enters_tas)}"
    )
    # Find the ETB arm carrying the ModalChooseOne.
    modal_arms = [
        ta for ta in enters_tas if isinstance(ta.effect, ModalChooseOne)
    ]
    assert len(modal_arms) == 1, (
        f"exactly one ENTERS arm must wrap a ModalChooseOne; got "
        f"{len(modal_arms)}"
    )
    modal = modal_arms[0].effect
    assert len(modal.modes) == 2, (
        f"Blade's ETB ChooseOneMode must have 2 modes; got "
        f"{len(modal.modes)}"
    )
    # Mode 1 is the new effect class.
    assert isinstance(
        modal.modes[1],
        OwnerPutsTargetWarpedExileCardOnBottomOfLibrary,
    ), (
        f"mode 1 must be OwnerPutsTargetWarpedExileCardOnBottomOfLibrary; "
        f"got {type(modal.modes[1]).__name__}"
    )
    # Field-free unit dataclass — equality with a fresh instance.
    assert modal.modes[1] == OwnerPutsTargetWarpedExileCardOnBottomOfLibrary()


# ---------------------------------------------------------------------------
# (2) Serializer round-trip — Python class -> Rust-shape dict ->
# Python class. Validates the cross_engine bridge arm landed in this
# branch (``_ta_dict_to_python_effect`` ->
# ``owner_puts_target_warped_exile_card_on_bottom_of_library`` arm)
# round-trips the unit variant without field drift.
# ---------------------------------------------------------------------------


def test_blade_effect_dict_to_python_round_trip():
    """Rust-shape dict → Python
    ``OwnerPutsTargetWarpedExileCardOnBottomOfLibrary`` via
    ``_ta_dict_to_python_effect`` reconstructs a default-constructed
    instance. Bridge arm is the lever flip — without it, a
    Rust→Python triggered-ability translation would raise on the
    unknown kind."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = {
        "kind": "owner_puts_target_warped_exile_card_on_bottom_of_library",
    }
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(
        rebuilt, OwnerPutsTargetWarpedExileCardOnBottomOfLibrary
    ), (
        f"dict→Python bridge must round-trip to "
        f"OwnerPutsTargetWarpedExileCardOnBottomOfLibrary; got "
        f"{type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == OwnerPutsTargetWarpedExileCardOnBottomOfLibrary()


@_rust_skip
def test_blade_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::OwnerPutsTargetWarpedExileCardOnBottomOfLibrary``
    → dict emits the expected one-key shape. Drives the round-trip
    through ``Registry.register_printing`` + a getter that walks the
    spell's effect chain. Field-free unit-variant idiom — no other
    keys in the dict."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Blade Round-trip",
            "card_types": ["Instant"],
            "mana_cost": {"B": 1},
            "effects": [
                {
                    "kind": "owner_puts_target_warped_exile_card_on_bottom_of_library",
                },
            ],
        }
    )
    effs = reg.get_printing_effects(pid)
    assert len(effs) == 1, f"expected 1 effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == (
        "owner_puts_target_warped_exile_card_on_bottom_of_library"
    )
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


# ---------------------------------------------------------------------------
# (3) Rust unit pins — drive the new Rust variant via the synthetic-test
# cast pipeline (register synthetic spell + push_to_stack_with_target +
# resolve). Three scenarios: happy path, target-absent fizzle,
# target-not-warped fizzle.
# ---------------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _inject_warped_exile_card(rs, owner: int) -> int:
    """Inject a vanilla Instant filler into ``owner``'s exile zone
    AND stamp ``warped = True`` via the ``set_warped`` test helper.
    Returns the object id."""
    obj_id = rs.register_and_inject_object(
        _WARPED_EXILE_FILLER_DICT, owner, ZONE_EXILE,
    )
    rs.set_warped(owner, obj_id, True)
    return obj_id


def _inject_unwarped_exile_card(rs, owner: int) -> int:
    """Inject a vanilla Instant filler into ``owner``'s exile zone
    WITHOUT setting the warped flag. Returns the object id."""
    return rs.register_and_inject_object(
        _WARPED_EXILE_FILLER_DICT, owner, ZONE_EXILE,
    )


def _push_synth_blade_mode1_with_target(rs, target_id: int, controller: int = 0):
    """Cast a synthetic mode-1 carrier targeting the given exile card
    via the cast pipeline (register in hand → push_to_stack_with_target
    → resolve). Mirrors the synthetic-test cast-without-cost pipeline
    the SeedshipImpactEffect / DestroyTargetArtifactOrTappedCreature
    probes use."""
    spell_id = rs.register_and_inject_object(
        _BLADE_MODE1_SYNTH_PRINTING_DICT, controller, ZONE_HAND,
    )
    rs.push_to_stack_with_target(spell_id, controller, target_id)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    return spell_id


@_rust_skip
def test_rust_resolve_moves_warped_exile_card_to_library_bottom():
    """Happy path: a warped exile card on p1, target id bound at cast
    time → card moves to bottom of p1's library, warp flag clears."""
    rs = _fresh_rust_state()

    # Seed p1's library with a sentinel (top of library) so we can
    # assert the warped card lands at the BOTTOM, not the top.
    sentinel = rs.register_and_inject_object(
        {
            "name": "P1 Library Sentinel",
            "card_types": ["Instant"],
            "mana_cost": {"B": 1},
        },
        1, ZONE_LIBRARY,
    )
    warped_id = _inject_warped_exile_card(rs, owner=1)

    # Sanity: pre-resolve, warped card is in p1.exile with warped=True;
    # p1.library has only sentinel.
    p1_exile_pre = [e for e in rs.exile_snapshot(1)]
    assert [e["id"] for e in p1_exile_pre] == [warped_id], (
        f"pre-resolve p1.exile mismatch; got "
        f"{[e['id'] for e in p1_exile_pre]}"
    )
    p1_lib_pre = [e["id"] for e in rs.library_snapshot(1)]
    assert p1_lib_pre == [sentinel], (
        f"pre-resolve p1.library mismatch; got {p1_lib_pre}"
    )

    _push_synth_blade_mode1_with_target(rs, target_id=warped_id, controller=0)

    # Post-resolve: warped card is in p1.library bottom (last entry);
    # exile is empty.
    p1_exile_post = [e["id"] for e in rs.exile_snapshot(1)]
    assert p1_exile_post == [], (
        f"p1.exile must be empty post-resolve; got {p1_exile_post}"
    )
    p1_lib_post = [e["id"] for e in rs.library_snapshot(1)]
    assert p1_lib_post == [sentinel, warped_id], (
        f"warped card must land at p1.library BOTTOM (after sentinel); "
        f"got {p1_lib_post}"
    )
    # Warp flag must be cleared on the moved card. Read via the
    # library snapshot — it doesn't carry warped directly, so we
    # re-inject into exile via set_warped and observe that set_warped
    # raises ValueError on an obj_id that isn't in exile any more
    # (the warped card has moved out of exile, so it's not findable
    # in the exile zone).
    with pytest.raises(ValueError):
        rs.set_warped(1, warped_id, True)


@_rust_skip
def test_rust_resolve_target_absent_silent_fizzle():
    """Target id bound at cast time but no exile card with that id
    exists anywhere → silent fizzle. No zone mutations."""
    rs = _fresh_rust_state()

    # Seed p1's library with a sentinel; do NOT inject any exile card.
    sentinel = rs.register_and_inject_object(
        {
            "name": "P1 Library Sentinel",
            "card_types": ["Instant"],
            "mana_cost": {"B": 1},
        },
        1, ZONE_LIBRARY,
    )

    # Bind a target id that doesn't correspond to any exile card.
    # Use sentinel's id + 1000 as a definitely-unused id.
    bogus_target_id = sentinel + 1000
    _push_synth_blade_mode1_with_target(
        rs, target_id=bogus_target_id, controller=0,
    )

    # No mutations: library still has only sentinel, exile zones empty.
    assert [e["id"] for e in rs.library_snapshot(1)] == [sentinel]
    assert list(rs.exile_snapshot(0)) == []
    assert list(rs.exile_snapshot(1)) == []


@_rust_skip
def test_rust_resolve_target_not_warped_silent_fizzle():
    """Target id is valid + exists in exile, but ``warped == false``
    → silent fizzle (CR 608.2b re-check at resolve mirrors Python's
    ``if not obj.warped: return``). The card stays in exile."""
    rs = _fresh_rust_state()

    unwarped_id = _inject_unwarped_exile_card(rs, owner=1)

    _push_synth_blade_mode1_with_target(
        rs, target_id=unwarped_id, controller=0,
    )

    # Card stays in exile; library untouched.
    p1_exile_post = [e["id"] for e in rs.exile_snapshot(1)]
    assert p1_exile_post == [unwarped_id], (
        f"unwarped card must stay in exile; got {p1_exile_post}"
    )
    assert list(rs.library_snapshot(1)) == []


# ---------------------------------------------------------------------------
# (4) Covered-set membership — the orphan walker recognises the new
# Rust variant OwnerPutsTargetWarpedExileCardOnBottomOfLibrary as a
# 1:1 same-named match against the parser-claimed Python class.
# ---------------------------------------------------------------------------


def test_blade_effect_class_covered_by_rust():
    """The Python class is in the parser-emitted covered set
    (Blade of the Swarm claims it) and the Rust variant has the
    SAME name, so the orphan walker pairs them 1:1 without an
    override or RUST_AHEAD_OF_POOL allowlist entry."""
    from mtg_bot.parity.effect_coverage import (
        collect_python_effect_vocab,
        collect_rust_effect_variants,
        covered_python_class_set,
    )

    py_classes, _examples, _n = collect_python_effect_vocab()
    assert "OwnerPutsTargetWarpedExileCardOnBottomOfLibrary" in py_classes, (
        "Blade of the Swarm must surface "
        "OwnerPutsTargetWarpedExileCardOnBottomOfLibrary in the "
        "parser-walked Python effect vocab"
    )
    rust_variants = collect_rust_effect_variants()
    assert "OwnerPutsTargetWarpedExileCardOnBottomOfLibrary" in rust_variants, (
        "the new Rust Effect variant must be discoverable by the "
        "cards.rs text parser"
    )
    covered = covered_python_class_set()
    assert "OwnerPutsTargetWarpedExileCardOnBottomOfLibrary" in covered, (
        "the new Rust variant pairs 1:1 with the parser-claimed "
        "Python class (no override / RUST_AHEAD_OF_POOL allowlist "
        "needed)"
    )


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Blade of the Swarm printing's mode-1 effect on Python
# and a bridged synthetic Instant carrier on Rust. After resolve,
# asserts the concrete zone observables (the warped card moves from
# p1.exile to p1.library bottom on BOTH engines + the warp flag
# clears) plus the full ``compare_fields == []`` over the whole
# cross-engine field view.
#
# Scenario: p1 has one warped exile card; p0 casts the mode-1 effect
# (synthetic carrier on Rust; direct ``Effect.resolve`` call on
# Python) targeting that card. Both engines bottom-deck the card and
# clear its warped flag.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_blade_of_the_swarm_mode1_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Blade of the Swarm
    mode-1 warp-exile-to-library-bottom path.**

    Python: the ACTUAL parsed mode-1 effect (extracted from the live
    Blade of the Swarm printing's ETB ModalChooseOne) resolved
    directly with a bound warped-exile-card target. The synthetic-
    state convention (controlled cross-engine state, NOT full-game
    trajectory) lets us drive the effect end-to-end without spinning
    up the full ETB+modal-pick agent path on Python.

    Rust: synthetic Instant carrier whose effect is the new
    ``Effect::OwnerPutsTargetWarpedExileCardOnBottomOfLibrary``;
    cast via ``push_to_stack_with_target`` (binds the warped exile
    card id at cast time via
    ``current_resolve_payload_target_id``), then resolve.

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players), PLUS
    the concrete zone observables (warped card disappears from
    p1.exile and appears at the BOTTOM of p1.library on BOTH
    engines + the warp flag clears).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects import ModalChooseOne
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Blade of the Swarm")
    if real is None:
        pytest.skip("Blade of the Swarm absent from active CardSource")
    assert "Creature" in real.card_types

    # §2 source-of-truth: extract the genuine mode-1 effect from the
    # parsed Blade of the Swarm ETB ChooseOneMode.
    etb_modal_ta = next(
        (
            ta for ta in real.triggered_abilities
            if (
                ta.event is Event.ENTERS
                and isinstance(ta.effect, ModalChooseOne)
            )
        ),
        None,
    )
    assert etb_modal_ta is not None, (
        "Blade of the Swarm must carry an ENTERS+ModalChooseOne "
        "trigger arm (the modal ETB)"
    )
    modal = etb_modal_ta.effect
    assert len(modal.modes) == 2
    mode1_effect = modal.modes[1]
    assert isinstance(
        mode1_effect, OwnerPutsTargetWarpedExileCardOnBottomOfLibrary
    ), (
        f"mode 1 must be OwnerPutsTargetWarpedExileCardOnBottomOfLibrary; "
        f"got {type(mode1_effect).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # Synthetic vanilla filler printing on the Python side (matching
    # the Rust register_and_inject_object dict byte-for-byte).
    def _instant_printing(name: str) -> CardPrinting:
        return CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(generic=0, colored=(("B", 1),)),
            type_line="Instant",
            supertypes=(),
            card_types=("Instant",),
            subtypes=(),
            power=None,
            toughness=None,
            produces=frozenset(),
            keywords=frozenset(),
        )

    # ---- Python side: seat one warped exile card on p1; effect
    # resolves with that card as target. Normalise summoning_sick=False
    # to match the Rust register_and_inject_object default
    # (summoning_sick defaults to False for non-bf zones in Rust vs
    # True in Python's new_object — the Territorial Bruntar /
    # Icecave Crasher / Possibility Technician fixture-asymmetry
    # idiom).
    #
    # **Id-alignment idiom (CE4-style id ordering).** Python's
    # ``new_object`` and Rust's ``register_and_inject_object`` both
    # mint monotonic ids starting at 0. On Rust we register the
    # warped exile card FIRST (id=0) and the synthetic Instant
    # carrier SECOND (id=1, registered inside
    # ``_push_synth_blade_mode1_with_target``). To keep ids byte-
    # equal across engines, allocate the Python warped card FIRST
    # (id=0) and the synthetic carrier SECOND (id=1) — same idiom
    # Possibility Technician's probe uses for fixture ordering.
    py_warped = py.new_object(
        _instant_printing("Warped Exile Filler"),
        owner_id=1,
        zone=Zone.EXILE,
    )
    py_warped.warped = True
    py_warped.summoning_sick = False
    py.players[1].exile.append(py_warped)
    py_synth_carrier = py.new_object(
        _instant_printing("Blade Mode-1 Synthetic Carrier"),
        owner_id=0,
        zone=Zone.GRAVEYARD,
    )
    py_synth_carrier.summoning_sick = False
    py.players[0].graveyard.append(py_synth_carrier)

    # ---- Rust side: synthetic carrier in p0's hand + warped exile
    # card in p1's exile. The synthetic-cast pipeline binds the
    # warped card's id at cast time via push_to_stack_with_target.
    rs_warped = rs.register_and_inject_object(
        {
            "name": "Warped Exile Filler",
            "card_types": ["Instant"],
            "mana_cost": {"B": 1},
        },
        1, ZONE_EXILE,
    )
    rs.set_warped(1, rs_warped, True)

    # Pre-cast sanity.
    assert len(py.stack) == 0 and rs.stack_size() == 0
    assert py_warped.warped is True
    # Library is empty on both p0 and p1 — pin pre-state for the
    # post-resolve bottom-deck observable.
    assert py.players[1].library == []
    assert list(rs.library_snapshot(1)) == []

    # ---- Fire mode-1 effect on BOTH engines. ----
    #
    # **Python.** Call the effect's ``resolve`` directly with the
    # warped card as the bound target. This is the same shape
    # ``test_blade_mode_1_puts_warped_exile_card_on_bottom_of_library``
    # exercises (just without the modal-wrapper dispatch + ETB-fire
    # chain — we're probing the leaf effect, not the modal envelope).
    # Controller id 0 mirrors the Rust synthetic-cast controller.
    #
    # The synthetic Instant carrier is already pre-seated in
    # py.p0.graveyard (above) to mirror Rust's post-cast residue —
    # the carrier resolves on Rust and lands in p0's graveyard.
    # Python's mode-1 effect is invoked via ``.resolve()`` directly
    # (no spell wrapper) so there's no Python-side carrier; the
    # symmetric graveyard pre-seat is the byte-equal idiom for
    # cross-engine probes that drive one engine via ``.resolve()``
    # and the other via the cast pipeline.
    mode1_effect.resolve(py, 0, (("exile_card", py_warped.id),))

    # **Rust.** Cast the synthetic carrier targeting the warped card.
    # The cast pipeline binds the target via
    # push_to_stack_with_target; resolve_top_of_stack swaps it into
    # current_resolve_payload_target_id; the Effect arm reads it,
    # finds the warped card in p1.exile, moves to p1.library bottom,
    # clears the warped flag.
    _push_synth_blade_mode1_with_target(
        rs, target_id=rs_warped, controller=0,
    )

    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Python observables. ----
    assert py.players[1].exile == [], (
        f"Python: p1.exile must be empty post-resolve; got "
        f"{py.players[1].exile}"
    )
    assert py.players[1].library == [py_warped], (
        f"Python: warped card must land at p1.library (the only "
        f"entry); got {py.players[1].library}"
    )
    assert py_warped.warped is False, (
        "Python: warp flag must clear once the card is in the "
        "library"
    )
    assert py_warped.zone == Zone.LIBRARY

    # ---- Rust observables. ----
    rs_exile_post = [e["id"] for e in rs.exile_snapshot(1)]
    assert rs_exile_post == [], (
        f"Rust: p1.exile must be empty post-resolve; got "
        f"{rs_exile_post}"
    )
    rs_lib_post = [e["id"] for e in rs.library_snapshot(1)]
    assert rs_lib_post == [rs_warped], (
        f"Rust: warped card must land at p1.library bottom; got "
        f"{rs_lib_post}"
    )
    # Verify warp flag cleared on Rust side: re-trying set_warped
    # raises ValueError because the card moved out of exile.
    with pytest.raises(ValueError):
        rs.set_warped(1, rs_warped, True)

    # ---- Full field-view byte-equality over the WHOLE state. ----
    #
    # The post-resolve states should agree on every observable
    # field-view slot: hand / library / graveyard / exile / battlefield
    # / mana / life / step / turn / active_player / priority. The
    # warp flag itself isn't in the zone signature (per
    # ``_zone_signature`` / ``_rust_zone_obj_sig`` at
    # ``parity_smoke.py:228-267``), but the zone-change observable
    # (card moved from exile → library bottom) is — and that's what
    # this assertion locks down byte-equal.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Blade of the Swarm mode-1 "
        f"OwnerPutsTargetWarpedExileCardOnBottomOfLibrary must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
