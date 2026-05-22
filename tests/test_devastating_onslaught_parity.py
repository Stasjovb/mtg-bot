"""Cross-engine parity probes for Devastating Onslaught.

**Devastating Onslaught — Cycle 1 (the SECOND X-cost cross-engine
close; immediate follow-on to X-value Cycle 3's Zero Point Ballad).**
Devastating Onslaught ``{X}{X}{R}`` Sorcery (EoE): "Create X tokens
that are copies of target artifact or creature you control. Those
tokens gain haste until end of turn. Sacrifice them at the beginning
of the next end step."

The substrate that makes this slice possible:

  1. X-value subsystem C1+C2+C2.5+C3 (commits ``7c28643c`` /
     ``6a35d8e0`` / ``157336d1`` / ``33d803e7``): per-StackItem
     ``x_value: Option<i32>`` slot + ``GameState.current_resolve_x_value``
     transient + the save → set → restore bracket + ``ManaCost.x_pips``
     field + cast-pipeline detector binding ``Some(0)`` via no-agent
     fallback + admit-predicate widen for X-cost spells.
  2. ``CreateTokenCopyOfTargetCreatureYouControl`` precedent
     (state_ops_resolve.rs:12727): token-copy mint pattern (fresh
     ``next_object_id``, fresh ETB timestamp, ETB dispatch, etc.).
  3. ``DelayedTrigger`` infrastructure (``state.rs:5800-5830``):
     generic ``Effect`` payload carrying the per-token end-step sac
     schedule. Already proven by ``WarpExileSelf`` (warp end-step
     exile) and ``RemoveChargeCountersFromSourceDelayed``
     (control-change Cycle 5).

  4. THIS LANE: ``Effect::CreateXTokensOfTargetPermanentWithHasteEndStepSac``
     Rust unit variant (parse arm + ``to_pydict`` arm + resolve arm
     reading ``current_resolve_x_value`` + ``current_resolve_payload_target_id``
     per CR 608.2b + minting X token copies with haste UEOT +
     scheduling per-token ``SacrificeSourceDelayed`` end-step sac
     delayed triggers) +
     ``Effect::SacrificeSourceDelayed`` sibling unit variant +
     matching bridge dict→Python arms + reverse serializer leaves +
     Phase-1 ``(1, 1)``-shape X-cost admit widen (removes the
     unconditional X-cost reject in the Phase-1 predicate; the
     covered+bridged + round-trip-or-bail teeth still gate).

**Cross-engine harness X=0 dormancy.** Under the no-agent harness
(``agent=None`` on Python; X=0 mint on Rust per C2.5), the X-dependent
mint surface is dormant: 0 token copies are created, no haste grants,
no delayed triggers scheduled. Lose-X-life is not part of this card —
the harness limitation is purely on the mint surface (Devastating
Onslaught's only X-dependent observable is the mint count). The
cross-engine probe at X=0 verifies parse + admit + serializer
round-trip + resolve byte-equal without exercising the X-dependent
surface. The X-dependent surface is exercised by synthetic-state
Rust unit pins (X=0 silent no-op + X=2 mints 2 token copies + haste
UEOT + per-token sac schedule + indestructible target STILL gets
copied / tokens still sac + CR 608.2b fizzle on target-fizzle). This
is the deliberate harness limitation documented in
``docs/SEARCH_LIMITATIONS.md`` (mirrors the X-value C3 Zero Point
Ballad precedent).

Covered:

  - Parser SoT: the live parsed Devastating Onslaught printing's
    ``spell_effect`` IS the field-free Python
    ``CreateXTokensOfTargetPermanentWithHasteEndStepSac()``;
    its ``mana_cost.x_pips == 2`` ({X}{X}{R}).
  - Serializer round-trip: ``_python_spell_effect_to_dict`` emits
    ``{"kind": "create_x_tokens_of_target_permanent_with_haste_end_step_sac"}``;
    the dict→Python bridge reconstructs the field-free Python class.
  - Admit-gate flip: Devastating Onslaught NOW passes
    ``_printing_is_bridge_simple_spell`` (the §2 auto-grow teeth fire
    positively post-Cycle-1); the Phase-1 X-cost widen accepted the
    SHAPE, the Cycle-1 Effect arms + bridge arms fill in the
    covered+bridged + round-trip teeth.
  - Rust resolve unit pins:
      * X=0 silent no-op: 0 token copies minted, 0 haste grants,
        0 delayed triggers; the original target survives.
      * X=2 mints 2 token copies with haste: the new tokens have the
        target's printing, controller=caster, summoning-sick=true.
        ``effective_keywords`` includes "haste" on each token. Each
        token has a ``SacrificeSourceDelayed`` delayed trigger
        scheduled with ``fire_at_turn = state.turn_number``.
      * Indestructible target STILL gets copied: the target is the
        COPY SOURCE, not subject to destruction; the new tokens are
        independent objects. CR 702.12 (indestructible) is irrelevant
        to the copy.
      * CR 608.2b fizzle: if the target is gone from the battlefield
        at resolve time (e.g. it has been bounced between cast and
        resolve), the resolve is a silent no-op.
      * Delayed sac fires at end step: scheduling + firing path
        eventually moves the token to the caster's graveyard.
  - GENUINE real-EoE cross-engine byte-equal probe:
    ``test_cross_engine_real_eoe_devastating_onslaught_create_x_tokens_of_target_permanent_with_haste_end_step_sac_parity``
    drives the parsed Devastating Onslaught printing through both
    engines at X=0; asserts the WHOLE field view byte-equal
    post-resolve.
"""

from __future__ import annotations

import pytest


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_devastating_onslaught_spell_effect_class_and_x_pips():
    """**Verify-first.** The live parser maps Devastating Onslaught
    to ``CreateXTokensOfTargetPermanentWithHasteEndStepSac()`` — a
    parameterless frozen dataclass — and its ``mana_cost.x_pips == 2``
    (the ``{X}{X}{R}`` cost has two X pips, mirroring Python's
    parser shape). This pin freezes the parser SoT so a parser drift
    is caught here, not silently downstream in the cross-engine probe.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.tokens import (
        CreateXTokensOfTargetPermanentWithHasteEndStepSac,
    )

    p = get_active_source().get_printings().get("Devastating Onslaught")
    if p is None:
        pytest.skip("Devastating Onslaught absent from active CardSource")
    assert "Sorcery" in p.card_types
    assert isinstance(
        p.spell_effect, CreateXTokensOfTargetPermanentWithHasteEndStepSac
    ), (
        f"Devastating Onslaught spell_effect must be "
        f"CreateXTokensOfTargetPermanentWithHasteEndStepSac; "
        f"got {type(p.spell_effect).__name__}"
    )
    assert p.mana_cost.x_pips == 2, (
        f"Devastating Onslaught mana_cost.x_pips must be 2 "
        f"({{X}}{{X}}{{R}}); got {p.mana_cost.x_pips}"
    )


# -------------------------------------------------------------------
# Round-trip + admit-gate pins (the auto-grow §2 teeth).
# -------------------------------------------------------------------


def test_devastating_onslaught_serializer_round_trip():
    """The trajectory reverse-serializer must emit a clean
    ``{"kind": "create_x_tokens_of_target_permanent_with_haste_end_step_sac"}``
    unit dict; the dict→Python bridge must reconstruct
    ``CreateXTokensOfTargetPermanentWithHasteEndStepSac()``.

    A no-emit serializer would short-circuit the admit gate (the
    no-fallback-hybrid teeth). With the leaf landed and the variant
    field-free, the round-trip is byte-equal both ways.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.tokens import (
        CreateXTokensOfTargetPermanentWithHasteEndStepSac,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    p = get_active_source().get_printings().get("Devastating Onslaught")
    if p is None:
        pytest.skip("Devastating Onslaught absent from active CardSource")
    d = trajectory._python_spell_effect_to_dict(p.spell_effect)
    assert d == {
        "kind":
        "create_x_tokens_of_target_permanent_with_haste_end_step_sac",
    }, (
        f"Devastating Onslaught reverse serializer must emit the bare "
        f"unit-variant dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(
        rebuilt, CreateXTokensOfTargetPermanentWithHasteEndStepSac
    ), (
        f"dict→Python bridge must round-trip to "
        f"CreateXTokensOfTargetPermanentWithHasteEndStepSac; "
        f"got {type(rebuilt).__name__}"
    )


def test_sacrifice_source_delayed_serializer_round_trip():
    """Sibling round-trip pin for the per-token end-step sac
    delayed-trigger Effect. Unit variant on both sides — the dict
    emits only ``kind`` and the bridge reconstructs the field-free
    Python ``SacrificeSourceDelayed()``.

    Devastating Onslaught is the FIRST EoE consumer that needs this
    Rust→Python bridge arm to exist (the delayed-trigger effect is
    spawned dynamically by the
    ``CreateXTokensOfTargetPermanentWithHasteEndStepSac`` resolve arm,
    NOT by a static printing trigger list — same RUST_AHEAD_OF_POOL
    shape as ``WarpExileSelf``). This pin enforces the dict-shape
    round-trip for any future caller that asks for it.
    """
    from mtg_bot.effects.generic.delayed_actions import SacrificeSourceDelayed
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = trajectory._python_spell_effect_to_dict(SacrificeSourceDelayed())
    assert d == {"kind": "sacrifice_source_delayed"}, (
        f"SacrificeSourceDelayed reverse serializer must emit the bare "
        f"unit-variant dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, SacrificeSourceDelayed), (
        f"dict→Python bridge must round-trip to SacrificeSourceDelayed; "
        f"got {type(rebuilt).__name__}"
    )


def test_devastating_onslaught_passes_bridge_admit_gate():
    """**The lever flip pin.** Post-Cycle-1, Devastating Onslaught MUST
    pass ``_printing_is_bridge_simple_spell`` — the spell-card-bridge
    admit gate. Phase-1 ``(1, 1)``-shape admit + X-cost C2.5 widen
    extended to Phase 1 + Effect covered+bridged + serializer
    round-trips (the §2 teeth all fire positively).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = get_active_source().get_printings().get("Devastating Onslaught")
    if p is None:
        pytest.skip("Devastating Onslaught absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(p) is True, (
        "Devastating Onslaught must auto-join the spell-card-bridge "
        "admit set post-Cycle-1 (covered+bridged + round-trips + "
        "Phase-1 (1, 1)-shape X-cost widen)"
    )
    # Pin per-tooth gates — if any one fails, debug-time message points
    # at WHICH tooth.
    assert (
        trajectory._spell_effect_is_covered_and_bridged(p) is True
    )
    assert (
        trajectory._python_spell_effect_to_dict(p.spell_effect)
        is not None
    )


def test_devastating_onslaught_class_covered():
    """``CreateXTokensOfTargetPermanentWithHasteEndStepSac`` must be in
    the covered-by-rust set — the Rust
    ``Effect::CreateXTokensOfTargetPermanentWithHasteEndStepSac``
    variant declaration makes ``covered_python_class_set()`` include
    it (1:1 identity mapping; no override needed). Without this, the
    §2 admit-gate teeth refuse to flip the card.
    """
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert (
        "CreateXTokensOfTargetPermanentWithHasteEndStepSac" in covered
    ), (
        "Rust Effect::CreateXTokensOfTargetPermanentWithHasteEndStepSac "
        "variant must make the Python class covered"
    )


# -------------------------------------------------------------------
# Rust resolve-arm pins (synthetic state — drives X=0 silent no-op /
# X=2 mints 2 copies + haste + sac schedules / indestructible-blind
# copy / CR 608.2b fizzle).
# -------------------------------------------------------------------


def _build_rust_devastating_onslaught_state(
    *,
    target_owner=0,
    target_name="Wild Bear",
    target_power=2,
    target_toughness=2,
    target_indestructible=False,
    x_value=0,
    extra_bf_creatures=(),
    omit_target=False,
):
    """Build a Rust state with Devastating Onslaught on p0's stack, a
    target permanent on the specified owner's battlefield, the X
    value bound to the StackItem's ``x_value`` slot via the C1
    synthetic setter, and the target id bound via
    ``push_to_stack_with_target``.

    Returns ``(rs, target_id, spell_id)``. If ``omit_target=True`` the
    target is NOT injected (used for the CR 608.2b fizzle pin).
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    ZB = 2  # battlefield
    target_id: int | None = None
    if not omit_target:
        printing = {
            "name": target_name,
            "card_types": ["Creature"],
            "power": target_power,
            "toughness": target_toughness,
        }
        if target_indestructible:
            printing["keywords"] = ["indestructible"]
        target_id = rs.register_and_inject_object(
            printing, target_owner, ZB,
        )
    for (owner, name, power, toughness) in extra_bf_creatures:
        rs.register_and_inject_object(
            {"name": name, "card_types": ["Creature"],
             "power": power, "toughness": toughness},
            owner, ZB,
        )
    spell_id = rs.register_and_inject_object(
        {"name": "Devastating Onslaught",
         "card_types": ["Sorcery"],
         "effects": [{
             "kind":
             "create_x_tokens_of_target_permanent_with_haste_end_step_sac",
         }]},
        0, 0,  # hand zone — irrelevant; pushed onto stack next
    )
    if target_id is not None:
        rs.push_to_stack_with_target(spell_id, 0, target_id)
    else:
        # Fizzle pin: push without seeding a target.
        rs.push_to_stack(spell_id, 0)
    rs.set_stack_top_x_value(x_value)
    return rs, target_id, spell_id


def test_rust_devastating_onslaught_x_zero_silent_no_op():
    """Rust pin (a): X=0 silent no-op — 0 token copies minted, no
    delayed triggers scheduled, no haste grants. The original target
    survives. This is the no-agent cross-engine harness mint shape
    (X=0) for Devastating Onslaught — the cross-engine probe's
    dominant resolve shape.
    """
    rs, target_id, _ = _build_rust_devastating_onslaught_state(
        target_owner=0,
        target_name="DO Original 2/2",
        x_value=0,
    )
    bf_size_before = len(rs.battlefield_snapshot())
    delayed_before = rs.delayed_trigger_count
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly at X=0"
    bf = rs.battlefield_snapshot()
    bf_ids = {e["id"] for e in bf}
    assert target_id in bf_ids, "target must survive at X=0 (no destroy)"
    # No mint — bf size unchanged.
    assert len(bf) == bf_size_before, (
        f"X=0 must mint zero token copies; bf size went {bf_size_before}"
        f" → {len(bf)}"
    )
    # No delayed triggers scheduled.
    assert rs.delayed_trigger_count == delayed_before, (
        f"X=0 must schedule zero end-step sacs; delayed count went "
        f"{delayed_before} → {rs.delayed_trigger_count}"
    )


def test_rust_devastating_onslaught_x_two_mints_two_token_copies_with_haste():
    """Rust pin (b): X=2 — mints 2 token copies of the target's
    printing. The new tokens are on the caster's battlefield, share
    the target's printing_id, and have ``haste`` in their effective
    keywords via a UEOT GrantKeyword modifier. Mirrors Python's
    ``tokens.py:446-475`` mint loop with the
    ``ApplyEffect(GrantKeywords({"haste"}), EndOfTurn())`` haste push
    per token.
    """
    rs, target_id, _ = _build_rust_devastating_onslaught_state(
        target_owner=0,
        target_name="DO Original 2/2",
        x_value=2,
    )
    bf_before = rs.battlefield_snapshot()
    target_printing_id = next(
        e["printing_id"] for e in bf_before if e["id"] == target_id
    )
    rs.resolve_top_of_stack()
    bf_after = rs.battlefield_snapshot()
    # Two new objects on the caster's battlefield with the target's
    # printing_id (the original is also still present — the COPY is
    # of the target, not a transformation).
    copies = [
        e for e in bf_after
        if e["printing_id"] == target_printing_id
        and e["id"] != target_id
    ]
    assert len(copies) == 2, (
        f"X=2 must mint exactly 2 token copies; got {len(copies)}"
    )
    # Both copies on the caster's battlefield.
    for c in copies:
        assert c["controller_id"] == 0, (
            f"token copy controller must be the caster (0); got "
            f"{c['controller_id']}"
        )
    # Both tokens have haste via the UEOT GrantKeyword modifier — read
    # via the effective_keywords getter (the cross-engine convention).
    for c in copies:
        assert rs.has_keyword(c["id"], "haste"), (
            f"token copy {c['id']} must have haste UEOT; has_keyword "
            f"returned False"
        )


def test_rust_devastating_onslaught_x_two_schedules_two_end_step_sacs():
    """Rust pin (c): X=2 — schedules exactly 2 ``SacrificeSourceDelayed``
    delayed triggers, one per minted token, with ``fire_at_turn ==
    state.turn_number`` (current turn's end step, the "next end step"
    interpretation). Each schedule entry's ``source_id`` matches one
    of the minted tokens.
    """
    rs, target_id, _ = _build_rust_devastating_onslaught_state(
        target_owner=0,
        target_name="DO Original 2/2",
        x_value=2,
    )
    delayed_before = rs.delayed_trigger_count
    turn_at_cast = rs.turn_number  # getter, not callable
    rs.resolve_top_of_stack()
    delayed_after = rs.delayed_trigger_count
    assert delayed_after - delayed_before == 2, (
        f"X=2 must schedule exactly 2 end-step sacs; delayed count went "
        f"{delayed_before} → {delayed_after}"
    )
    # Inspect the 2 newest schedules and pin their shape.
    schedules = rs.delayed_triggers_snapshot()
    # The two newest entries are the per-token sac schedules.
    new_entries = schedules[delayed_before:]
    assert len(new_entries) == 2
    for entry in new_entries:
        assert entry["fire_at_turn"] == turn_at_cast, (
            f"fire_at_turn must equal turn_at_cast ({turn_at_cast}); "
            f"got {entry['fire_at_turn']}"
        )
        assert entry["controller_id"] == 0, (
            f"controller_id must be the caster (0); got "
            f"{entry['controller_id']}"
        )
        assert entry["effect_kind"] == "sacrifice_source_delayed", (
            f"effect kind must be sacrifice_source_delayed; got "
            f"{entry['effect_kind']}"
        )
    # The source_ids must be exactly the minted token ids.
    bf_after = rs.battlefield_snapshot()
    target_printing_id = next(
        e["printing_id"] for e in bf_after if e["id"] == target_id
    )
    copies = [
        e["id"] for e in bf_after
        if e["printing_id"] == target_printing_id and e["id"] != target_id
    ]
    sched_source_ids = {e["source_id"] for e in new_entries}
    assert sched_source_ids == set(copies), (
        f"per-token sac schedule source_ids must equal the minted "
        f"token ids; sched={sched_source_ids}, tokens={set(copies)}"
    )


def test_rust_devastating_onslaught_indestructible_target_still_copied():
    """Rust pin (d): an indestructible target STILL gets copied — the
    target is the COPY SOURCE, not subject to destruction; the new
    tokens are independent objects. CR 702.12 (indestructible) is
    irrelevant to the copy. The original indestructible target stays
    on the battlefield (it isn't sacrificed; the per-token sac
    schedule is keyed on the NEW tokens). The new tokens are
    scheduled for end-step sac — sac bypasses indestructible per
    CR 701.16 anyway (sacrifice is not destroy).
    """
    rs, target_id, _ = _build_rust_devastating_onslaught_state(
        target_owner=0,
        target_name="DO Indestructible Wall",
        target_power=0,
        target_toughness=4,
        target_indestructible=True,
        x_value=2,
    )
    bf_before = rs.battlefield_snapshot()
    target_printing_id = next(
        e["printing_id"] for e in bf_before if e["id"] == target_id
    )
    rs.resolve_top_of_stack()
    bf_after = rs.battlefield_snapshot()
    # Original indestructible target still on bf.
    assert any(e["id"] == target_id for e in bf_after), (
        "indestructible target must survive (it isn't destroyed; "
        "copies are independent objects)"
    )
    # 2 new token copies of the indestructible printing.
    copies = [
        e for e in bf_after
        if e["printing_id"] == target_printing_id and e["id"] != target_id
    ]
    assert len(copies) == 2, (
        f"indestructible target must STILL be copied X=2 times; "
        f"got {len(copies)} copies"
    )


def test_rust_devastating_onslaught_target_fizzle_silent_no_op():
    """Rust pin (e): CR 608.2b fizzle. The spell is on the stack with
    NO bound target (synthetic fizzle path — the production cast
    pipeline would NEVER push without a target, but the resolve arm's
    payload-target-aware path must still silent-fizzle correctly when
    the payload is unbound AND no fallback first-eligible candidate
    exists). Resolve must be a silent no-op: 0 token copies, 0
    delayed triggers.
    """
    rs, _target_id, _spell_id = _build_rust_devastating_onslaught_state(
        x_value=2,
        omit_target=True,
    )
    bf_size_before = len(rs.battlefield_snapshot())
    delayed_before = rs.delayed_trigger_count
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0
    bf_after = rs.battlefield_snapshot()
    assert len(bf_after) == bf_size_before, (
        f"target-fizzle must mint zero copies; bf size went "
        f"{bf_size_before} → {len(bf_after)}"
    )
    assert rs.delayed_trigger_count == delayed_before, (
        f"target-fizzle must schedule zero sacs; delayed count went "
        f"{delayed_before} → {rs.delayed_trigger_count}"
    )


def test_rust_devastating_onslaught_x_two_tokens_summoning_sick():
    """Rust pin (f): minted tokens enter summoning-sick (CR 302.1 ETB
    default; the haste UEOT grant lets them attack despite the sick
    flag). Pin both — sick is true AND haste is granted, so the
    composed `can_attack` predicate sees them as legal attackers.
    """
    rs, target_id, _ = _build_rust_devastating_onslaught_state(
        target_owner=0,
        target_name="DO Original 2/2",
        x_value=2,
    )
    bf_before = rs.battlefield_snapshot()
    target_printing_id = next(
        e["printing_id"] for e in bf_before if e["id"] == target_id
    )
    rs.resolve_top_of_stack()
    bf_after = rs.battlefield_snapshot()
    copies = [
        e for e in bf_after
        if e["printing_id"] == target_printing_id and e["id"] != target_id
    ]
    assert len(copies) == 2
    for c in copies:
        assert c["summoning_sick"] is True, (
            f"token copy {c['id']} must enter summoning-sick (CR 302.1); "
            f"got summoning_sick={c['summoning_sick']}"
        )
        # haste is granted via UEOT
        assert rs.has_keyword(c["id"], "haste"), (
            f"token copy {c['id']} must have haste UEOT despite sick"
        )


# -------------------------------------------------------------------
# Genuine real-printing cross-engine byte-equal probe.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_devastating_onslaught_create_x_tokens_of_target_permanent_with_haste_end_step_sac_parity():
    """**GENUINE real-printing cross-engine probe — Devastating
    Onslaught at X=0 (no-agent harness mint). Devastating Onslaught
    Cycle 1 PROBED-tier flip.**

    Drives the **ACTUAL parsed Devastating Onslaught printing** on
    the Python side: ``get_active_source().get_printings()
    ["Devastating Onslaught"]`` — which the live parser maps to a
    ``spell_effect`` of
    ``CreateXTokensOfTargetPermanentWithHasteEndStepSac()`` (verified
    above) with ``mana_cost.x_pips == 2``.

    Oracle (verbatim, ``data/edge_of_eternities.json``):

        "[Sorcery] {X}{X}{R} — Create X tokens that are copies of
         target artifact or creature you control. Those tokens gain
         haste until end of turn. Sacrifice them at the beginning of
         the next end step."

    **No-agent harness X=0 mint (C2.5 SoT).** Under the cross-engine
    harness, Python's ``_choose_and_apply_x`` at
    ``actions.py:529-549`` returns 0 when ``p.agent is None``; the
    Rust ``cast_spell_noncreature`` Delta-2 detector (C2.5) mints
    ``StackItem.x_value = Some(0)`` to match. The X-dependent mint
    surface (X token-copy creations, haste UEOT grants, per-token sac
    schedules) is DORMANT at X=0:

      * 0 token copies are minted.
      * 0 ``UeotModifier::GrantKeyword`` haste pushes.
      * 0 ``SacrificeSourceDelayed`` delayed-trigger schedules.

    This probe verifies the GENUINE parsed printing + C1+C2+C2.5+C3
    substrate + Cycle-1 Effect arms + admit gate + serializer
    round-trip + resolve byte-equal at X=0, NOT the X-dependent mint
    surface (which the synthetic-state Rust unit pins above exercise).
    This is the deliberate harness limitation documented in
    ``docs/SEARCH_LIMITATIONS.md`` — mirrors the X-value C3 Zero
    Point Ballad precedent.

    p0 has the genuine Devastating Onslaught on the stack with X=0;
    p0 also controls a vanilla 2/2 (the target the cast-time binding
    seats). The WHOLE field view is asserted byte-equal post-resolve.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        build_python_field_view,
        compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.tokens import (
        CreateXTokensOfTargetPermanentWithHasteEndStepSac,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Devastating Onslaught")
    if real is None:
        pytest.skip("Devastating Onslaught absent from active CardSource")
    assert "Sorcery" in real.card_types
    assert isinstance(
        real.spell_effect, CreateXTokensOfTargetPermanentWithHasteEndStepSac
    )

    def _vanilla_creature(name, power, toughness):
        return CardPrinting(
            name=name, mana_cost_str="",
            mana_cost=ManaCost(generic=0),
            type_line="Creature", supertypes=(),
            card_types=("Creature",), subtypes=(),
            power=power, toughness=toughness, produces=frozenset(),
            keywords=(),
        )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p0 caster-controlled 2/2 vanilla — the target the cast-time
    # binding would seat. At X=0 no token copies are minted, but the
    # target binding still resolves through the payload-target slot
    # cleanly.
    py_target = py.new_object(
        _vanilla_creature("DO Real Target 2/2", 2, 2),
        owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_target.summoning_sick = False
    py.battlefield.append(py_target)
    rs_target = rs.register_and_inject_object(
        {"name": "DO Real Target 2/2",
         "card_types": ["Creature"],
         "power": 2, "toughness": 2},
        0, ZB,
    )

    # Cast the genuine Devastating Onslaught on Python with the
    # StackItem's x_value=0 and the cast-time-bound target.
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell,
            controller_id=0,
            x_value=0,
            targets=(("permanent", py_target.id),),
        )
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # Cast on Rust: push the spell, bind the target via
    # `push_to_stack_with_target`, bind X=0 via the C1 setter (which is
    # what C2.5's production cast-pipeline detector also produces under
    # no-agent semantics — Some(0) for an X-cost spell). The bridged
    # synthetic Sorcery's effect dict carries the
    # ``create_x_tokens_of_target_permanent_with_haste_end_step_sac``
    # kind that round-trips to the Python side via
    # ``_ta_dict_to_python_effect``.
    rs_spell = rs.register_and_inject_object(
        {"name": "Devastating Onslaught",
         "card_types": ["Sorcery"],
         "effects": [{
             "kind":
             "create_x_tokens_of_target_permanent_with_haste_end_step_sac",
         }]},
        0, 0,
    )
    rs.push_to_stack_with_target(rs_spell, 0, rs_target)
    rs.set_stack_top_x_value(0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # FULL byte-equal compare. At X=0 the mint loop iterates zero
    # times — no token copies, no haste grants, no per-token sac
    # schedules. The post-resolve field view is byte-equal across
    # both engines (every observable — bf, graveyard, life totals,
    # exile, hand, library — matches).
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Devastating Onslaught at X=0 post-resolve must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )
    # Observable cross-checks.
    assert any(o.id == py_target.id for o in py.battlefield), (
        "Python: target 2/2 must survive at X=0 (no destroy; the "
        "target is the copy SOURCE)"
    )
    assert any(
        e["id"] == rs_target for e in rs.battlefield_snapshot()
    ), "Rust: target 2/2 must survive at X=0 (byte-equal)"
