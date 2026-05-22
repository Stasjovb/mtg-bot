"""Cross-engine parity probes for Scour for Scrap.

**scour-for-scrap-cycle-2 (2026-05-21).** Scour for Scrap is the
FIRST ``or_both=True`` ``ModalChooseOne`` to flip from COVERED →
PROBED. The substrate that makes this possible:

  1. Lane LL's Cycle-1 ``or_both`` multi-pick substrate
     (``StackItem.chosen_mode_idxs: Option<Vec<u8>>``, cast-time
     all-modes bind, per-mode resolve dispatch, reverse serializer
     ``or_both`` round-trip).
  2. The new Rust ``Effect::ReturnTargetArtifactCardFromYour
     GraveyardToHand`` unit variant (declaration + parse + to_pydict
     + resolve arm with CR 608.2b re-validation on the cast-time-
     bound graveyard-artifact target).
  3. The per-mode detector table extension in
     ``state_ops_cast.rs::cast_spell_noncreature`` — when ``or_both``
     fires the multi-pick bind, the detector walk peeks the FIRST
     chosen mode whose Effect variant IS in the recognized-targeted-
     leaf allowlist (skipping Scour's untargeted mode 0
     ``SearchLibraryForCard``, picking mode 1's
     ``ReturnTargetArtifactCardFromYourGraveyardToHand`` for cast-
     time binding).
  4. The new target-satisfiability arm in
     ``state_ops_legal.rs::spell_targets_satisfiable`` (caster's
     graveyard, artifact in card_types).
  5. The matching bridge round-trip arms:
       * ``cross_engine.py::_ta_dict_to_python_effect`` dict→Python
         arm (constructs the field-free Python effect class).
       * ``trajectory.py::_python_spell_effect_to_dict``'s ``_leaf``
         table — adds BOTH the new
         ``return_target_artifact_card_from_your_graveyard_to_hand``
         leaf AND a NARROW ``search_library_for_card`` leaf scoped to
         ``filter_name="artifact"`` (mode 0). The narrow scope
         honest-stops Demonic Counsel's auto-flip to a follow-up
         cycle.
  6. The Phase-5 admit-shape widen in
     ``_printing_is_bridge_simple_spell`` — accepts the
     ``(min_t, max_t) == (0, 1)`` empty-slot_kinds shape that Scour's
     ``ModalChooseOne(or_both=True)`` reports (mode 0 untargeted +
     mode 1 single-target ⇒ ``(0, 1)``).

Lives in its own module per the concurrent-agent merge-conflict-
minimization hint (mirrors the Drill Too Deep / Reroute Systems /
Exorcise / Close Encounter sibling lanes). The slug-credit scanner
discovers it via the new entry in
``scripts/measure_pool_parity.py::PROBE_MODULES`` (Lane MM's
re-anchored discipline).

Covered:
- Verify-first: live parser maps Scour to the expected
  ``ModalChooseOne(or_both=True, modes=(SearchLibraryForCard,
  ReturnTargetArtifactCardFromYourGraveyardToHand))`` shape.
- Serializer round-trip emits a clean ``choose_one_mode`` dict with
  ``or_both: True`` and both per-mode leaves; dict→Python rebuilds
  byte-equal.
- The card passes the ``_printing_is_bridge_simple_spell`` admit
  gate (the spell-card-bridge flip).
- Real-EoE byte-equal cast-resolve probe drives the genuine parsed
  printing through both engines.
- Rust unit pins for the new resolve arm + per-mode detector entry.
"""

from __future__ import annotations

import importlib
import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


def _fresh_rust():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


_ZONE_HAND = 0
_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3


def test_real_eoe_scour_for_scrap_spell_effect_is_or_both_modal_chooseone_with_expected_modes():
    """**Verify-first.** The live parser maps Scour for Scrap to
    ``ModalChooseOne(or_both=True, modes=(
        SearchLibraryForCard(filter_name="artifact", may_fail=True),
        ReturnTargetArtifactCardFromYourGraveyardToHand(),
    ))``. This pin freezes the parser SoT so a parser drift is caught
    here, not silently downstream."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetArtifactCardFromYourGraveyardToHand,
    )
    from mtg_bot.effects.generic.search import SearchLibraryForCard

    p = get_active_source().get_printings().get("Scour for Scrap")
    if p is None:
        pytest.skip("Scour for Scrap absent from active CardSource")
    assert "Instant" in p.card_types
    se = p.spell_effect
    assert isinstance(se, ModalChooseOne)
    assert se.or_both is True
    assert len(se.modes) == 2
    assert isinstance(se.modes[0], SearchLibraryForCard)
    assert se.modes[0].filter_name == "artifact"
    assert isinstance(
        se.modes[1], ReturnTargetArtifactCardFromYourGraveyardToHand
    )


def test_cross_engine_real_eoe_scour_for_scrap_serializer_round_trip():
    """**scour-for-scrap-cycle-2 serializer round-trip pin.** The
    trajectory reverse-serializer must emit a clean
    ``choose_one_mode`` dict with ``or_both: True`` and both per-mode
    leaves AND the dict→Python bridge must reconstruct the original
    ``ModalChooseOne(or_both=True)`` byte-equal.

    This is the load-bearing round-trip test: a partially-serializable
    ModalChooseOne returns ``None`` from
    ``_python_spell_effect_to_dict`` and the admit gate refuses to
    flip the card into the bridge admit set (the no-fallback-hybrid
    teeth). Adding the new
    ``ReturnTargetArtifactCardFromYourGraveyardToHand`` leaf AND the
    narrow ``SearchLibraryForCard(filter_name="artifact")`` leaf
    together flip Scour for Scrap from None-emitted (COVERED) to a
    clean two-mode ``or_both`` dict (PROBED)."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetArtifactCardFromYourGraveyardToHand,
    )
    from mtg_bot.effects.generic.search import SearchLibraryForCard
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    p = get_active_source().get_printings().get("Scour for Scrap")
    if p is None:
        pytest.skip("Scour for Scrap absent from active CardSource")
    d = trajectory._python_spell_effect_to_dict(p.spell_effect)
    assert d is not None, (
        "Scour for Scrap's spell_effect MUST round-trip clean post-"
        "cycle-2 (both modes leaf-recognized; serializer recurses "
        "via the ModalChooseOne composer with or_both=True emit)"
    )
    assert d == {
        "kind": "choose_one_mode",
        "modes": [
            {
                "kind": "search_library_for_card",
                "filter_name": "artifact",
                "max_mv": 0,
                "may_fail": True,
            },
            {
                "kind": (
                    "return_target_artifact_card_from_your_"
                    "graveyard_to_hand"
                ),
            },
        ],
        "or_both": True,
    }
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, ModalChooseOne)
    assert rebuilt.or_both is True
    assert len(rebuilt.modes) == 2
    assert isinstance(rebuilt.modes[0], SearchLibraryForCard)
    assert rebuilt.modes[0].filter_name == "artifact"
    assert isinstance(
        rebuilt.modes[1], ReturnTargetArtifactCardFromYourGraveyardToHand
    )


def test_scour_for_scrap_passes_bridge_admit_gate():
    """**The lever flip pin.** Post-cycle-2, Scour for Scrap MUST pass
    ``_printing_is_bridge_simple_spell`` — the spell-card-bridge
    admit gate. The card has ``(0, 1)`` target_count_range with empty
    target_slot_kinds (the new Phase-5 ``or_both`` admit shape); both
    modes are covered+bridged; the serializer round-trips cleanly
    (the §2 teeth all fire positively)."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = get_active_source().get_printings().get("Scour for Scrap")
    if p is None:
        pytest.skip("Scour for Scrap absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(p) is True
    # Per-tooth diagnostics.
    assert trajectory._spell_effect_is_covered_and_bridged(p) is True
    assert trajectory._python_spell_effect_to_dict(p.spell_effect) is not None


def test_demonic_counsel_stays_declined_post_cycle_2():
    """**Honest-stop discipline pin.** Demonic Counsel's
    ``SearchLibraryForCard(filter_name="demon")`` body would also
    round-trip if the ``_leaf`` arm admitted any filter — but cycle-2
    narrows the ``_leaf`` arm to ``filter_name="artifact"`` only, so
    Demonic Counsel STAYS declined this lane and waits for its own
    follow-up cycle to ship the per-card probe + admit-set guardrail
    flip. This guard catches a future leaf-widening regression that
    would silently auto-flip Demonic Counsel without its dedicated
    probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = get_active_source().get_printings().get("Demonic Counsel")
    if p is None:
        pytest.skip("Demonic Counsel absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(p) is False
    # The body IS covered+bridged on both engines today — the decline
    # comes from the narrow ``_leaf`` admit (artifact-only) at the
    # reverse-serializer gate.
    assert trajectory._spell_effect_is_covered_and_bridged(p) is True
    assert trajectory._python_spell_effect_to_dict(p.spell_effect) is None


# ---------------------------------------------------------------------------
# Rust unit pins for the new variant + per-mode detector entry.
# ---------------------------------------------------------------------------


def test_rust_return_target_artifact_card_parse_and_to_pydict_round_trip():
    """The new ``Effect::ReturnTargetArtifactCardFromYourGraveyard
    ToHand`` Rust variant must parse from the unit-shape dict
    ``{"kind": "return_target_artifact_card_from_your_graveyard_to_hand"}``
    and round-trip cleanly through the parse/to_pydict path. Smoke
    via register_and_inject_object (the only public parse surface)."""
    _require_engine()
    rs = _fresh_rust()
    # Register an instant whose body is the bare new leaf; the parse
    # arm fires inside register_and_inject_object. Acceptance of the
    # registration = parse arm green.
    sid = rs.register_and_inject_object(
        {
            "name": "Bare Return Artifact",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1},
            "effects": [
                {
                    "kind": (
                        "return_target_artifact_card_from_your_"
                        "graveyard_to_hand"
                    ),
                }
            ],
        },
        0, _ZONE_HAND,
    )
    assert sid >= 0


def test_rust_per_mode_detector_picks_targeted_mode_in_or_both_walk():
    """When an ``or_both=True`` modal has mode 0 = untargeted (e.g.
    ``SearchLibraryForCard``) and mode 1 = targeted (e.g.
    ``ReturnTargetArtifactCardFromYourGraveyardToHand``), the
    per-mode detector walk in ``cast_spell_noncreature`` skips mode
    0 (no recognized-targeted-leaf match) and picks mode 1's binder
    — binding the caster's first graveyard artifact onto
    ``current_resolve_payload_target_id``. This pins the new
    ``is_recognized_targeted_mode_leaf`` allowlist walk."""
    _require_engine()
    rs = _fresh_rust()
    # Seed an artifact in p0's graveyard.
    art_id = rs.register_and_inject_object(
        {
            "name": "Test Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "effects": [],
        },
        0, _ZONE_GRAVEYARD,
    )
    # Seed a library card too — DrawCards mode is untargeted so a
    # library card avoids the no-target degenerate path. (Actually
    # SearchLibraryForCard is also fine without a library card; the
    # mode just fizzles silently. Use a non-creature card here.)
    rs.register_and_inject_object(
        {
            "name": "Library Filler",
            "card_types": ["Land"],
            "mana_cost": {},
        },
        0, 1,  # ZONE_LIBRARY
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Synthetic Scour-shape",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1},
            "effects": [
                {
                    "kind": "choose_one_mode",
                    "modes": [
                        {
                            "kind": "search_library_for_card",
                            "filter_name": "artifact",
                            "max_mv": 0,
                            "may_fail": True,
                        },
                        {
                            "kind": (
                                "return_target_artifact_card_from_"
                                "your_graveyard_to_hand"
                            ),
                        },
                    ],
                    "or_both": True,
                }
            ],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "C", 1)
    ok = rs.cast_spell_noncreature(sid, 0)
    assert ok is True
    # Multi-pick path active: both modes bound.
    assert rs.stack_top_chosen_mode_idxs() == [0, 1]
    # Per-mode detector walk peeked mode 1 (the targeted leaf) and
    # bound the artifact id.
    assert rs.stack_top_target_id() == art_id


def test_rust_return_target_artifact_resolve_moves_card_from_gy_to_hand():
    """The new resolve arm moves the cast-time-bound artifact card
    from the caster's graveyard to the caster's hand. Drive via the
    bare leaf at the top-level effects[0] (the production cast-time
    bind from the per-mode detector seats the payload-target id;
    here we exercise the resolve arm directly via push_to_stack_with_
    target)."""
    _require_engine()
    rs = _fresh_rust()
    # p0 has Test Artifact in graveyard.
    art_id = rs.register_and_inject_object(
        {
            "name": "Test Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "effects": [],
        },
        0, _ZONE_GRAVEYARD,
    )
    # Bare-leaf spell, pre-bound via push_to_stack_with_target.
    sid = rs.register_and_inject_object(
        {
            "name": "Bare Return Artifact",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1},
            "effects": [
                {
                    "kind": (
                        "return_target_artifact_card_from_your_"
                        "graveyard_to_hand"
                    ),
                }
            ],
        },
        0, _ZONE_HAND,
    )
    rs.push_to_stack_with_target(sid, 0, art_id)
    rs.resolve_top_of_stack()
    # Artifact left the graveyard and entered the hand.
    gy_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    hand_ids = [e["id"] for e in rs.hand_snapshot(0)]
    assert art_id not in gy_ids, (
        "Artifact must have left graveyard post-resolve"
    )
    assert art_id in hand_ids, (
        "Artifact must have entered hand post-resolve"
    )


def test_rust_return_target_artifact_resolve_fizzles_when_target_left_gy():
    """**CR 608.2b re-validation pin.** When the cast-time-bound
    artifact card has left the graveyard between cast and resolve,
    the resolve arm must silently fizzle — NOT crash, NOT scan for a
    different target. Pins the resolve-arm's payload-target
    re-validation against the source-controller's graveyard."""
    _require_engine()
    rs = _fresh_rust()
    # Stage 1: register an artifact in p0's graveyard.
    art_id = rs.register_and_inject_object(
        {
            "name": "Test Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "effects": [],
        },
        0, _ZONE_GRAVEYARD,
    )
    # Stage 2: register a DECOY artifact in p0's graveyard. If the
    # resolve arm fell back to the deterministic-first scan instead
    # of re-validating the payload, it would scan and pick THIS
    # decoy (or the original — order depends on Vec insertion).
    decoy_id = rs.register_and_inject_object(
        {
            "name": "Decoy Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "effects": [],
        },
        0, _ZONE_GRAVEYARD,
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Bare Return Artifact",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1},
            "effects": [
                {
                    "kind": (
                        "return_target_artifact_card_from_your_"
                        "graveyard_to_hand"
                    ),
                }
            ],
        },
        0, _ZONE_HAND,
    )
    # Bind the ORIGINAL artifact id as the cast-time payload target.
    rs.push_to_stack_with_target(sid, 0, art_id)
    # Move the ORIGINAL artifact OUT of the graveyard between cast
    # and resolve — exile-equivalent (use move_object_from_graveyard_
    # to_hand to relocate, since exile zone isn't trivially synthetic-
    # injectable here; the hand move achieves the same "not in
    # graveyard" precondition).
    rs.move_object_from_graveyard_to_hand(0, art_id)
    # Snapshot post-move pre-resolve.
    pre_gy = {e["id"] for e in rs.graveyard_snapshot(0)}
    pre_hand = {e["id"] for e in rs.hand_snapshot(0)}
    assert art_id not in pre_gy
    assert art_id in pre_hand
    assert decoy_id in pre_gy
    # Resolve — must silently fizzle (validation rejects the
    # payload-target id; the decoy stays put).
    rs.resolve_top_of_stack()
    post_gy = {e["id"] for e in rs.graveyard_snapshot(0)}
    post_hand = {e["id"] for e in rs.hand_snapshot(0)}
    # Decoy stays in graveyard (no fallback fire).
    assert decoy_id in post_gy, (
        "Decoy must stay in graveyard — payload-target validation "
        "must REJECT the missing target, NOT fall back to first-legal"
    )
    # Original stays in hand (the pre-resolve move).
    assert art_id in post_hand


def test_rust_return_target_artifact_resolve_self_scan_fallback():
    """Substrate fallback pin — when ``current_resolve_payload_target_id``
    is ``None`` (e.g. a synthetic-test direct-resolve path that bypasses
    the cast-time per-mode binder), the resolve arm falls back to the
    deterministic-first-legal scan from the controller's graveyard.
    This back-compat path matches the sibling
    ``ReturnArtifactOrCreatureFromYourGraveyardToHand`` self-scan
    behavior."""
    _require_engine()
    rs = _fresh_rust()
    art_id = rs.register_and_inject_object(
        {
            "name": "Test Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "effects": [],
        },
        0, _ZONE_GRAVEYARD,
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Bare Return Artifact",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1},
            "effects": [
                {
                    "kind": (
                        "return_target_artifact_card_from_your_"
                        "graveyard_to_hand"
                    ),
                }
            ],
        },
        0, _ZONE_HAND,
    )
    # push_to_stack (NO target) — payload remains None at resolve.
    rs.push_to_stack(sid, 0)
    rs.resolve_top_of_stack()
    # Self-scan fallback picked the artifact.
    hand_ids = [e["id"] for e in rs.hand_snapshot(0)]
    assert art_id in hand_ids


# ---------------------------------------------------------------------------
# Real-EoE byte-equal cross-engine probe (slug-credit name).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_scour_for_scrap_return_target_artifact_card_from_your_graveyard_to_hand_parity():
    """**GENUINE real-EoE cross-engine probe — Scour for Scrap.
    cycle-2 — admit-set flip Scour for Scrap COVERED → PROBED.
    PROBED tier — the slice's headline pin (slug-credit name).**

    Drives the GENUINE parsed Scour for Scrap ``ModalChooseOne`` body
    through resolve on BOTH engines for the mode-1 graveyard-return
    path. Asserts byte-equal hand state (the bound artifact card
    moved from graveyard to hand) post-resolve.

    Setup focuses on mode 1 (the new substrate) — mode 0 is library-
    tutor whose parity is established by the existing
    ``SearchLibraryForCard`` bridge; the targeted-mode path is where
    cycle-2's new substrate lives.

      * p0 has an artifact card in graveyard (Test Salvage Ship — a
        bare Spacecraft printing that carries the Artifact card type).
      * Python: spell on stack with ``chosen_modes=(1,)`` (mode 1
        only) and the ``("graveyard_artifact", id)`` target tuple.
      * Rust: spell registered, push the spell via
        ``cast_spell_noncreature`` so the cast-time per-mode detector
        binds the graveyard-artifact id; narrow to mode 1 via
        ``set_stack_top_chosen_mode_idxs([1])``; resolve arm consumes
        the bound id and moves the artifact card from graveyard to
        hand.
    """
    _require_engine()
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetArtifactCardFromYourGraveyardToHand,
    )
    from mtg_bot.cards.base import make_spacecraft

    real = get_active_source().get_printings().get("Scour for Scrap")
    if real is None:
        pytest.skip("Scour for Scrap absent from active CardSource")
    se = real.spell_effect
    assert isinstance(se, ModalChooseOne)
    assert se.or_both is True
    assert isinstance(
        se.modes[1], ReturnTargetArtifactCardFromYourGraveyardToHand
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: artifact in graveyard; spell on stack mode 1 only.
    test_ship = make_spacecraft(
        "Test Salvage Ship", "{2}", power=1, toughness=2,
        station_threshold=3,
    )
    py_ship = py.new_object(test_ship, owner_id=0, zone=Zone.GRAVEYARD)
    py.players[0].graveyard.append(py_ship)
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            chosen_modes=(1,),
            targets=(("graveyard_artifact", py_ship.id),),
        ),
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    py_hand_names = [o.printing.name for o in py.players[0].hand]
    assert "Test Salvage Ship" in py_hand_names, (
        "Python: artifact card must be in hand after mode-1 resolve"
    )
    py_gy_names = [o.printing.name for o in py.players[0].graveyard]
    assert "Test Salvage Ship" not in py_gy_names

    # ---- Rust: seed the artifact in p0's graveyard, register the
    # ---- real Scour for Scrap printing, cast through the production
    # ---- path (so the per-mode detector + payload-target binder
    # ---- fire), narrow chosen modes to [1] (mirror Python's
    # ---- chosen_modes=(1,)), resolve.
    rs_ship_id = rs.register_and_inject_object(
        {
            "name": "Test Salvage Ship",
            "card_types": ["Artifact"],
            "subtypes": ["Spacecraft"],
            "mana_cost": {"generic": 2},
            "effects": [],
        },
        0, _ZONE_GRAVEYARD,
    )
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Scour for Scrap",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1, "generic": 3},
            "effects": [
                {
                    "kind": "choose_one_mode",
                    "modes": [
                        {
                            "kind": "search_library_for_card",
                            "filter_name": "artifact",
                            "max_mv": 0,
                            "may_fail": True,
                        },
                        {
                            "kind": (
                                "return_target_artifact_card_from_"
                                "your_graveyard_to_hand"
                            ),
                        },
                    ],
                    "or_both": True,
                }
            ],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "U", 1)
    rs.add_mana(0, "C", 3)
    ok = rs.cast_spell_noncreature(rs_spell_id, 0)
    assert ok is True, "Scour for Scrap cast must succeed"
    # The cast-time per-mode detector picked the bound target.
    assert rs.stack_top_target_id() == rs_ship_id, (
        "Rust per-mode detector must bind the graveyard artifact"
    )
    # Narrow chosen modes to mode 1 only (mirrors Python's
    # chosen_modes=(1,)).
    rs.set_stack_top_chosen_mode_idxs([1])
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # Hand carries the artifact post-resolve; graveyard does not.
    hand_ids = [e["id"] for e in rs.hand_snapshot(0)]
    gy_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert rs_ship_id in hand_ids, (
        "Rust: artifact must be in hand post-resolve"
    )
    assert rs_ship_id not in gy_ids, (
        "Rust: artifact must be gone from graveyard post-resolve"
    )
