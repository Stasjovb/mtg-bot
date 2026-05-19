"""Genuine real-EoE cross-engine byte-equality probes for the
session's flagship features in CROSS-FEATURE INTERACTION.

**The genuinely-distinct dimension this module closes.**

This continuous-pipeline cycle added ~60 genuine real-EoE byte-equal
probes plus the sibling-owned ``test_probe_*`` modules. Every one of
them — the spell-card-bridge carrier sweep
(``test_probe_spell_card_bridge_admitted.py``), the warp lifecycle
(``test_probe_warp_admitted.py``), the warp+combat surface
(``test_probe_warp_combat_interaction.py``), the covered-but-unprobed
batches (``test_probe_covered_unprobed_{a,b,c,d}.py``), and the
isolated Tier-A real-EoE probes in ``tests/test_parity_smoke.py``
(Radiant Strike / Depressurize / Biosynthic Burst / the 5 warp
creatures) — exercises a flagship feature in a SINGLE-card /
single-feature context. None of them ever drives **two flagship
features onto the same creature in the same game**, which is exactly
where cross-engine divergences most plausibly hide:

  * a bench-admitted removal spell resolving onto a
    ``+1/+1``-counter'd-AND-``indestructible``-granted creature
    (the counters-fold × UEOT-keyword-grant × conditional-destroy
    triple-interaction inside one spell's resolve);
  * a bench-admitted removal spell DESTROYING a warp-cast creature
    BEFORE its end-step exile sweep (spell-resolution × the
    ``WarpExileSelf`` delayed-trigger ordering × the
    graveyard-not-exile destination split, CR 603.6c "permanent
    already left → no-op");
  * a bench-admitted debuff spell that does NOT kill a warp-cast
    creature, so the warp-exile sweep STILL fires (the opposite
    ordering — non-lethal spell × warp-exile destination = exile,
    not graveyard, with the UEOT modifier draining on a
    warp-exiled permanent).

**What is NOT re-asserted (verify-first disjointness — Python
``src/mtg_bot/`` is SoT).** The isolated Depressurize real-EoE probe
``test_cross_engine_real_eoe_depressurize_debuff_then_conditional_destroy_parity``
(``tests/test_parity_smoke.py``) ALREADY covers Depressurize × a
plain ``+N/+N``-counter'd creature (its load-bearing §2 COUNTERS arm:
printed 2/2 + 2 net counters → eff power 2+2−3=1>0 → survives). This
module does NOT re-probe that. The genuinely-NEW interaction here is
the *third* feature stacked on: Biosynthic Burst's ``indestructible``
UEOT grant making Depressurize's conditional ``destroy()`` **fizzle**
on a creature whose folded counter drives eff power to exactly 0 —
the ``destroy``-respects-``indestructible`` gate (``turn.py``:533)
reached *through a spell's resolve, gated by another spell's UEOT
keyword grant*. No isolated probe casts two flagship spells onto one
creature; no isolated probe removes a warp permanent with a bridged
spell before its sweep.

**Idiom.** Two established, sibling-proven idioms, used verbatim:

  1. The StackItem-injection idiom (``test_probe_covered_unprobed_*``
     / the isolated Tier-A real-EoE probes) for the controlled
     two-spell-on-one-creature interaction: empty matched states,
     ``register_and_inject_object`` + ``set_counters`` /
     ``tap_object`` to seat the precise board, the genuine parsed
     Python ``spell_effect`` on a ``StackItem`` + the bridged
     synthetic on Rust, ``resolve_top_of_stack`` + ``apply_sbas``,
     FULL ``compare_fields`` (post-``_net_counters`` ``ecc5f680``).

  2. The real-deck warp-lifecycle idiom
     (``test_cross_engine_real_eoe_warp_phase1_full_lifecycle_byte_equal``
     / ``test_probe_warp_combat_interaction.py``) for the
     spell × warp-exile-sweep interaction: the ACTUAL parsed warp
     printing through ``trajectory._printing_to_card_def``, the
     genuine Phase-1 spell-card-bridge carrier for the removal spell
     (``cast_spell`` → ``cast_spell_noncreature`` →
     ``StackItem.target_obj_id`` → resolve → graveyard), single-color
     normalised basics (the documented dual-producer-ambiguity
     avoidance — see the diagnosis note in the Scenario-3 docstring),
     ``step_both`` + the per-phase ``adv`` FULL ``compare_fields``.

**Assertion strength.** The three byte-equal interactions (the
Biosynthic-indestructible × Depressurize triple-interaction, the
Radiant × warp-exile ordering, the Depressurize × surviving-warp ×
warp-exile destination) assert FULL ``compare_fields`` == [] over the
WHOLE cross-engine field view at every step / phase boundary AND
post-resolve (the strong tier — no carve-out; the ``_net_counters``
fix makes the counter'd / debuffed / warp-exiled creature's signature
compare honestly on BOTH engines) PLUS the interaction observable
(survives/dies; graveyard-vs-exile destination; the warp sweep no-op
vs fire). The negative control surfaced a genuine RUST-SIDE
divergence (CFI-1 — see the FINDINGS NOTE above
``_negative_control_diffs``) which has since been **CLOSED**
Rust-side: the negative control now hard-asserts the byte-equal
interaction observable AND a FULL field-view byte-equality with no
carve-out, and the former strict-xfail tracker is now a normal
passing pin (``test_depressurize_kills_counter_creature_full_field_
cfi1_closed``) — a permanent regression guard for the closed
divergence.

**Verify-first.** Each probe re-resolves the live printing(s),
asserts the genuine ``spell_effect`` / warp shape, and asserts the
spell is still Phase-1 bench-admitted / the creature still
warp-admitted at HEAD BEFORE probing — FAILing loudly (never silently
skipping) on live-tree drift. **A genuine RUST-SIDE divergence WAS
surfaced — the cross-feature interaction work SUCCEEDING** (the
negative control: a +1/+1-counter'd creature killed by Depressurize).
Diagnosed (Python is SoT, read-only Rust inspection): Rust's
``Effect::DepressurizeEffect`` destroy arm had a stray
``obj.counters = 0;`` that diverged from Python AND Rust's own SBA
destroy path (the established byte-equal contract — counters retained
on the dead object — is pinned by the Orbital Plunge probe). This was
**FIXED Rust-side** in the slice that closed CFI-1 (the stray line
deleted; new-code-is-right, Python untouched) — see the RUST-SIDE
FINDINGS NOTE above ``_negative_control_diffs``.
Separately, during development a ``mana_pool_p0`` divergence was
surfaced and diagnosed as a probe-fixture artifact (a dual-color
basic letting the two engines make different mana-color choices for
an ambiguous dual-producer — NOT an engine bug); resolved
new-code-is-right by normalising to single-color basics, the
documented warp / spell-card-bridge harness idiom. No
``docs/SEARCH_LIMITATIONS.md`` entry — the byte-equal interactions
are pure evidence-strengthening; the one real divergence (CFI-1) was
a Rust-side bug since FIXED (the stray ``obj.counters = 0;`` deleted),
not a Python shortcut.

**Disjointness.** A distinct dimension (cross-feature interaction)
from every isolated single-feature probe and a disjoint card-USE from
every sibling-owned module. Does NOT touch
``tests/test_trajectory_parity.py``, ``tests/test_trajectory.py``,
the ``test_probe_covered_unprobed_*`` modules, the
``test_probe_spell_card_bridge_admitted`` module, the
``test_probe_warp_admitted`` module, the
``test_probe_warp_combat_interaction`` module, or the protected
``test_audit_safe_trigger_*`` tests. New module, own file.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


# Skip the whole module if the Rust extension isn't built — same policy
# as ``tests/test_parity_smoke.py`` / ``tests/test_trajectory_parity.py``.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


# ---------------------------------------------------------------------------
# Interaction 1 — the controlled two-spell-on-one-creature triple
# interaction (StackItem-injection idiom).
#
# Biosynthic Burst grants a +1/+1 counter + reach/trample/
# indestructible UEOT + untap on one own creature. Depressurize then
# applies -3/-0 UEOT and "if power <= 0, destroy it". On a printed 2/2
# the +1/+1 counter folds (CR 613 layer 7d) to eff power 3; the -3 UEOT
# from Depressurize drives it to 2+1-3 = 0 <= 0, so Depressurize calls
# ``destroy()`` — but Biosynthic Burst's UEOT ``indestructible`` makes
# that ``destroy()`` FIZZLE (``turn.py``:533 — the destroy-respects-
# indestructible gate). The creature SURVIVES on BOTH engines.
#
# This is the genuinely-new surface: the isolated Depressurize probe
# already covers Depressurize × a plain counter'd creature; NO isolated
# probe stacks Biosynthic Burst's indestructible-grant onto the same
# creature so that the conditional-destroy inside Depressurize's resolve
# is reached AND gated by another spell's UEOT keyword. The two control
# arms below pin the boundary precisely so a counter-fold OR an
# indestructible-fold bug on either side flips a survive/die observable.
# ---------------------------------------------------------------------------


def _seat_subject(py, rs, *, power, toughness, tapped, counters):
    """Seat one identical p0-controlled creature on BOTH engines'
    battlefields with the requested printed P/T, tap-state, and net
    +1/+1 counters. Returns ``(py_obj, rs_id)``."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    ZB = 2
    cp = CardPrinting(
        name="CFI Subject", mana_cost_str="", mana_cost=ManaCost(generic=0),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=power, toughness=toughness,
        produces=frozenset(),
    )
    py_obj = py.new_object(cp, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = tapped
    if counters >= 0:
        py_obj.plus_one_counters = counters
    else:
        py_obj.minus_one_counters = -counters
    py.battlefield.append(py_obj)

    rs_id = rs.register_and_inject_object(
        {"name": "CFI Subject", "card_types": ["Creature"],
         "power": power, "toughness": toughness}, 0, ZB)
    if tapped:
        rs.tap_object(rs_id)
    if counters != 0:
        assert rs.set_counters(rs_id, counters) is True
    return py_obj, rs_id


def _cast_genuine_then_bridged(
    py, rs, py_obj, *, real_printing, bridged_effect_dict,
):
    """Cast ``real_printing`` (the ACTUAL parsed EoE spell) on the
    Python side as a genuine ``spell_effect`` on a ``StackItem``
    targeting ``py_obj``; cast the ``bridged_effect_dict`` synthetic
    Instant on the Rust side. Resolve + SBA both. Returns the
    post-resolve FULL ``compare_fields`` diff list."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    py_spell = py.new_object(real_printing, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_obj.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    rs_spell_id = rs.register_and_inject_object(
        {"name": real_printing.name, "card_types": ["Instant"],
         "effects": [bridged_effect_dict]}, 0, 0)
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    return compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )


def test_biosynthic_indestructible_grant_fizzles_depressurize_destroy():
    """**Interaction 1 — Biosynthic Burst's UEOT ``indestructible``
    fizzles Depressurize's conditional ``destroy()`` (counter-fold ×
    UEOT-keyword-grant × conditional-destroy triple-interaction).**

    p0 controls a TAPPED 2/2. p0 casts the genuine Biosynthic Burst on
    it: +1/+1 counter (eff P/T fold → 3/3), reach/trample/
    indestructible UEOT, untapped. Then p0 casts the genuine
    Depressurize on the SAME creature: -3/-0 UEOT → eff power
    2+1-3 = 0 <= 0 → Depressurize calls ``destroy()`` — which FIZZLES
    because the creature is ``indestructible`` (UEOT, from Biosynthic
    Burst). The creature SURVIVES on BOTH engines.

    Asserts FULL ``compare_fields`` == [] after EACH spell (Biosynthic
    Burst's counter+kw+untap, then Depressurize's debuff+fizzled-
    destroy) PLUS the survive observable. A counter-fold bug, an
    indestructible-fold bug, or a destroy-gate bug on either engine
    flips this from survive→die and diverges.

    Distinct from
    ``test_cross_engine_real_eoe_depressurize_..._conditional_destroy``
    (Depressurize × a PLAIN counter'd creature, no indestructible) and
    ``test_cross_engine_real_eoe_biosynthic_burst_...`` (Biosynthic
    Burst in isolation, no follow-up removal). No isolated probe casts
    two flagship spells onto one creature.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import (
        BiosynthicBurstEffect, DepressurizeEffect,
    )
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )

    src = get_active_source().get_printings()
    bb = src.get("Biosynthic Burst")
    dp = src.get("Depressurize")
    if bb is None or dp is None:
        pytest.skip("Biosynthic Burst / Depressurize absent")
    assert "Instant" in bb.card_types and "Instant" in dp.card_types
    assert isinstance(bb.spell_effect, BiosynthicBurstEffect), (
        f"genuine Biosynthic Burst spell_effect must be "
        f"BiosynthicBurstEffect; got {type(bb.spell_effect).__name__}"
    )
    assert isinstance(dp.spell_effect, DepressurizeEffect), (
        f"genuine Depressurize spell_effect must be DepressurizeEffect;"
        f" got {type(dp.spell_effect).__name__}"
    )
    assert dp.spell_effect.power_penalty == 3

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # A TAPPED printed 2/2, no counters yet (Biosynthic Burst adds the
    # counter + untaps it as part of the first resolve).
    py_obj, rs_id = _seat_subject(
        py, rs, power=2, toughness=2, tapped=True, counters=0)

    # ---- Spell 1: genuine Biosynthic Burst on the own creature.
    diff1 = _cast_genuine_then_bridged(
        py, rs, py_obj,
        real_printing=bb,
        bridged_effect_dict={"kind": "biosynthic_burst_effect"},
    )
    assert diff1 == [], (
        f"Biosynthic Burst leg must be byte-equal across the WHOLE "
        f"field view (counter + reach/trample/indestructible UEOT + "
        f"untap on one own creature); diffs={diff1}"
    )
    # Sanity (Python observable; the zero-divergence compare already
    # proves Rust agrees): the counter folded + indestructible granted.
    from mtg_bot.game import effective_keywords, effective_power
    assert py_obj.plus_one_counters == 1
    assert "indestructible" in effective_keywords(py, py_obj)
    assert py_obj.tapped is False
    assert effective_power(py, py_obj) == 3, (
        "printed 2 + 1 counter = eff power 3 before Depressurize"
    )

    # ---- Spell 2: genuine Depressurize on the SAME creature. -3/-0
    # → eff power 2+1-3 = 0 <= 0 → destroy() — fizzles (indestructible
    # UEOT from Biosynthic Burst). The creature SURVIVES on BOTH.
    diff2 = _cast_genuine_then_bridged(
        py, rs, py_obj,
        real_printing=dp,
        bridged_effect_dict={"kind": "depressurize_effect",
                             "power_penalty": 3},
    )
    py_alive = any(o.id == py_obj.id for o in py.battlefield)
    rs_alive = any(e["id"] == rs_id for e in rs.battlefield_snapshot())
    assert py_alive is True and rs_alive is True, (
        f"the indestructible (UEOT, from Biosynthic Burst) creature "
        f"must SURVIVE Depressurize's conditional destroy (eff power "
        f"2+1-3=0<=0 → destroy() fizzles) on BOTH; "
        f"py_alive={py_alive} rs_alive={rs_alive}"
    )
    assert diff2 == [], (
        f"Depressurize-onto-indestructible-counter'd-creature leg must "
        f"be byte-equal across the WHOLE field view (the triple "
        f"interaction: counter-fold × UEOT-indestructible × "
        f"conditional-destroy fizzle); diffs={diff2}"
    )


# ---------------------------------------------------------------------------
# RUST-SIDE FINDINGS NOTE — Divergence CFI-1: **CLOSED**.
#
# **Divergence CFI-1 — Rust's ``Effect::DepressurizeEffect`` destroy
# arm spuriously zeroed ``GameObject.counters`` on the dying creature;
# Python (the SoT) and Rust's own SBA destroy path do NOT.** This was
# surfaced by the negative-control interaction below (a +1/+1-counter'd
# creature killed by Depressurize → graveyard) and has now been FIXED
# Rust-side.
#
# History: the cross-feature interaction probe's negative control
# isolated the divergence to ONE field-view slot (``graveyard_p0`` —
# the dead creature's counter component was ``+1`` on Python, ``0`` on
# Rust). Root cause: ``rust/src/state_ops_resolve.rs``
# ``Effect::DepressurizeEffect`` resolve's conditional-destroy branch
# had a stray ``obj.counters = 0;`` (≈ line 5969) when moving the
# creature to the graveyard. Python's ``move_off_battlefield``
# (``turn.py``) clears combat state (damage / tapped / attached_to) but
# never the +1/+1 counters, and Rust's SBA destroy path
# (``state_ops_sba.rs`` ~:417) follows that same observable — so a
# counter'd creature RETAINS its counters on the graveyard object on
# BOTH Python and Rust's SBA destroy path. The campaign's byte-equal
# contract is "counters retained on the dead object" and is EXPLICITLY
# pinned by the isolated Orbital Plunge probe
# ``test_cross_engine_real_eoe_orbital_plunge_excess_conditional_lander_parity``
# (the dead −4-counter creature's ``graveyard`` signature carries
# ``−4`` byte-equal on BOTH). The Depressurize-specific
# ``obj.counters = 0;`` was the outlier; it diverged from (a) Python
# (SoT) AND (b) Rust's own SBA destroy path.
#
# Fix (this slice, Rust-side, new-code-is-right): the stray
# ``obj.counters = 0;`` in the ``Effect::DepressurizeEffect`` destroy
# branch was DELETED so it matches Python + Rust's SBA destroy path.
# (Aside: CR 700.4 says counters cease on zone change, so the
# rules-correct end state is 0; but the CAMPAIGN parity contract —
# Python is SoT — is "retained", and changing Python's
# ``move_off_battlefield`` to clear them was VERIFIED to break the
# established Orbital Plunge byte-equal pin. Aligned the outlier Rust
# arm to Python + Rust's own SBA path; Python untouched.)
#
# CFI-1 is CLOSED: the negative control below now asserts FULL
# ``compare_fields`` == [] with NO carve-out (the ``graveyard_p0``
# filter + the strict-xfail tracker were removed when the fix landed —
# the gap is closed, so the scaffolding is gone and the negative
# control is a permanent full-field regression pin).
# ---------------------------------------------------------------------------


def _negative_control_diffs():
    """Run the negative-control scenario (a +1/+1-counter'd 2/2 with
    NO indestructible grant, killed by genuine Depressurize) and return
    ``(diffs, py_alive, rs_alive)``."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import DepressurizeEffect
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )

    src = get_active_source().get_printings()
    dp = src.get("Depressurize")
    if dp is None:
        pytest.skip("Depressurize absent")
    assert isinstance(dp.spell_effect, DepressurizeEffect)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # printed 2/2 + ONE +1/+1 counter, untapped, NO indestructible.
    py_obj, rs_id = _seat_subject(
        py, rs, power=2, toughness=2, tapped=False, counters=1)

    diffs = _cast_genuine_then_bridged(
        py, rs, py_obj,
        real_printing=dp,
        bridged_effect_dict={"kind": "depressurize_effect",
                             "power_penalty": 3},
    )
    py_alive = any(o.id == py_obj.id for o in py.battlefield)
    rs_alive = any(e["id"] == rs_id for e in rs.battlefield_snapshot())
    return diffs, py_alive, rs_alive


def test_depressurize_kills_counter_creature_without_the_indestructible_grant():
    """**Interaction 1 — the NEGATIVE control: WITHOUT Biosynthic
    Burst's indestructible grant, the same +1/+1-counter'd creature
    DIES to Depressurize.**

    p0 controls an UNtapped printed 2/2 carrying ONE pre-seated +1/+1
    counter (the counter is present, but NO ``indestructible`` was
    granted — Biosynthic Burst was NOT cast). p0 casts the genuine
    Depressurize: -3/-0 → eff power 2+1-3 = 0 <= 0 → ``destroy()``,
    which now SUCCEEDS (nothing granted indestructible). The creature
    DIES on BOTH engines.

    This isolates that the survival in
    ``test_biosynthic_indestructible_grant_fizzles_depressurize_destroy``
    is specifically Biosynthic Burst's indestructible grant — NOT the
    counter alone (a +1 counter only raises eff power to exactly 0,
    still <= 0, so the destroy still fires absent indestructible). The
    boundary is exactly the indestructible UEOT keyword the other spell
    granted.

    **The byte-equal interaction observable is hard-asserted** (the
    creature dies on BOTH) AND the full cross-engine field view is
    asserted byte-equal with NO carve-out. The Rust-side divergence
    CFI-1 (Rust's ``Effect::DepressurizeEffect`` destroy arm spuriously
    zeroed ``GameObject.counters`` on the dead creature) has been
    CLOSED: the stray ``obj.counters = 0;`` was deleted from
    ``rust/src/state_ops_resolve.rs`` so the Depressurize destroy arm
    now matches Python (SoT) AND Rust's own SBA destroy path (the
    established "counters retained on the dead object" byte-equal
    contract, pinned by the Orbital Plunge probe). The earlier
    ``graveyard_p0`` filter + the strict-xfail tracker were removed
    with the fix — this is now a plain full-field byte-equality
    assertion: the dead creature's counter slot must compare byte-equal
    (Python retains the +1, Rust now also retains it).

    Distinct from the isolated Depressurize §2 COUNTERS arm (printed
    2/2 + **2** net counters → eff power 1 > 0 → SURVIVES — that pins
    the counter-fold keeping power positive AND the SURVIVING creature's
    counter slot, so it never exercises a counter'd creature DYING via
    Depressurize). This negative control is the path that surfaced
    CFI-1 — exactly the cross-feature interaction work succeeding, now
    a permanent full-field regression pin for the closed divergence.
    """
    diffs, py_alive, rs_alive = _negative_control_diffs()
    assert py_alive is False and rs_alive is False, (
        f"WITHOUT the indestructible grant, the +1-counter 2/2 → eff "
        f"power 2+1-3 = 0 <= 0 → destroy() SUCCEEDS → dies on BOTH; "
        f"py_alive={py_alive} rs_alive={rs_alive}"
    )
    # CFI-1 CLOSED: the full cross-engine field view must be byte-equal
    # (no carve-out). A Depressurize-killed +1/+1-counter'd creature
    # carries its counters into the graveyard byte-equal on BOTH
    # engines now that the stray Rust ``obj.counters = 0;`` is deleted.
    assert diffs == [], (
        f"CFI-1 regression — a Depressurize-killed +1/+1-counter'd "
        f"creature must be byte-equal across the WHOLE field view "
        f"(counters retained on the dead object on BOTH engines, the "
        f"established contract); diffs={diffs}"
    )


def test_depressurize_kills_counter_creature_full_field_cfi1_closed():
    """**Interaction 1 — the permanent regression pin for the CLOSED
    Rust-side divergence CFI-1.**

    The EXACT negative-control scenario, asserting FULL
    ``compare_fields`` == [] over the WHOLE cross-engine field view.
    This was previously ``xfail(strict=True)`` while CFI-1 was open
    (Rust's ``Effect::DepressurizeEffect`` destroy arm spuriously
    zeroed ``GameObject.counters`` on the dead creature). The stray
    ``obj.counters = 0;`` has been DELETED from
    ``rust/src/state_ops_resolve.rs`` (new-code-is-right: aligned the
    outlier Rust arm to Python (SoT) + Rust's own SBA destroy path),
    so the full field view is now byte-equal. The xfail was flipped to
    this normal passing pin (and the ``graveyard_p0`` filter in the
    negative control removed) — CFI-1 is closed and this is a
    permanent byte-equality regression guard.
    """
    diffs, py_alive, rs_alive = _negative_control_diffs()
    assert py_alive is False and rs_alive is False
    assert diffs == [], (
        f"CFI-1 regression — a Depressurize-killed +1/+1-counter'd "
        f"creature must be byte-equal across the WHOLE field view "
        f"(counters retained on the dead object, the established "
        f"contract — the stray Rust obj.counters=0 is deleted): "
        f"{diffs}"
    )


# ---------------------------------------------------------------------------
# Interactions 2 & 3 — bridged removal/debuff × the warp-exile sweep
# (real-deck warp-lifecycle idiom).
#
# A warp-cast creature carries a ``WarpExileSelf`` delayed triggered
# ability (``actions.py``:1550) that fires on the controller's end step
# and "re-checks the battlefield by id at resolve time — if the warp
# permanent has already left the battlefield (countered, died, bounced,
# etc.) the resolution is a no-op per CR 603.6c". NO isolated probe ever
# removes a warp permanent with a bridged spell before that sweep, nor
# debuffs (without killing) a warp permanent and lets the sweep fire.
# These two probes pin BOTH orderings byte-equal.
# ---------------------------------------------------------------------------


_BASIC_FOR_COLOR = {
    "R": "Mountain", "G": "Forest", "W": "Plains",
    "U": "Island", "B": "Swamp",
}


def _make_adv(label, py, rs):
    from mtg_bot.parity.cross_engine import (
        advance_phase_python, compare_fields,
    )
    from test_trajectory_parity import _step_views

    def adv(n):
        for _ in range(n):
            advance_phase_python(py)
            rs.advance_phase()
            pv, rv = _step_views(py, rs)
            d = compare_fields(pv, rv)
            assert not d, (
                f"{label}: phase advance ({pv['step']}, turn "
                f"{pv['turn']}) diverged (FULL compare_fields): "
                f"{[(x.field, x.py_value, x.rust_value) for x in d]}"
            )
    return adv


def _tap_color(py, rs, ai, color, n, label):
    """Tap exactly ``n`` of p``ai``'s untapped non-sick lands that
    produce ``color``, byte-equal on BOTH engines."""
    from mtg_bot.parity.cross_engine import step_both, step_both_drained

    t = 0
    for o in list(py.battlefield):
        if (o.controller_id == ai and o.printing.is_land
                and not o.tapped and not o.summoning_sick
                and color in o.printing.produces and t < n):
            s = step_both(
                py, rs,
                {"kind": "activate_ability",
                 "source_id": int(o.id), "ability_index": 0})
            assert not s.divergences, (
                f"{label}: {color}-land tap diverged: "
                f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
            )
            t += 1
    assert t == n, f"{label}: needed {n} {color} mana; tapped {t}"


def _warp_then_bridged_spell_setup(
    *, warp_card, warp_color, warp_str, spell_card, spell_color,
):
    """Build a deterministic two-color matched game, ramp byte-equal,
    warp-cast ``warp_card``, and return everything the two probes need:
    ``(py, rs, adv, ai, warp_obj)`` with the warp creature on p``ai``'s
    battlefield (``cast_via_warp`` True) and the bridged removal/debuff
    spell still in hand, FULL byte-equal throughout.

    Single-color basics ONLY (the documented dual-producer-ambiguity
    avoidance — a dual-color basic lets the two engines pick different
    mana colors for an ambiguous producer; surfaced + diagnosed during
    development as a probe-fixture artifact, NOT an engine bug, fixed
    new-code-is-right by single-color normalisation, the established
    warp / spell-card-bridge harness idiom).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, step_both, step_both_drained,
    )
    from test_trajectory_parity import _step_views
    from tests.parity._picker_shims import _PickFirstLegalTargetAgent

    src = get_active_source().get_printings()
    wreal = src.get(warp_card)
    sreal = src.get(spell_card)
    if wreal is None or sreal is None:
        pytest.skip(f"{warp_card} / {spell_card} absent from CardSource")

    # Verify-first: the warp creature is STILL warp-admitted (warp arm,
    # not the plain simple-creature arm) and the removal/debuff spell is
    # STILL Phase-1 spell-card-bridge admitted, at THIS live HEAD.
    assert wreal.warp_cost is not None and wreal.warp_cost_str == warp_str
    assert trajectory._printing_is_bridge_pure_warp_creature(wreal), (
        f"{warp_card} is NOT warp-admitted at live HEAD — the warp "
        f"Phase-1/1.5 admit set drifted; re-derive + drop/replace this "
        f"probe honestly (do NOT relax to a skip)."
    )
    assert not trajectory._printing_is_bridge_simple_creature(wreal), (
        f"{warp_card}: the PLAIN simple-creature arm admits it — the "
        f"warp arm is then not the load-bearing admit path. Re-derive."
    )
    assert trajectory._printing_is_bridge_simple_spell(sreal), (
        f"{spell_card} is NOT Phase-1 spell-card-bridge admitted at "
        f"live HEAD — the lever's admit set drifted; re-derive + "
        f"drop/replace this probe honestly (do NOT relax to a skip)."
    )

    cd_w = trajectory._printing_to_card_def(wreal)
    cd_s = trajectory._printing_to_card_def(sreal)
    assert cd_w.has_warp is True
    assert cd_s.card_type == "Instant" and cd_s.spell_effect is not None

    wbasic = _BASIC_FOR_COLOR[warp_color]
    sbasic = _BASIC_FOR_COLOR[spell_color]
    wland = CardDef(name=wbasic, card_type="Land",
                    mana_produced=(warp_color,))
    sland = CardDef(name=sbasic, card_type="Land",
                    mana_produced=(spell_color,))

    import re as _re

    def _cost_total(cost_str):
        return sum(
            int(x) if x.isdigit() else 1
            for x in _re.findall(r"\{([^}]+)\}", cost_str)
        )

    warp_total = _cost_total(warp_str)
    spell_total = _cost_total(sreal.mana_cost_str)
    # The warp creature is warp-cast AND the removal/debuff spell is
    # cast in the SAME p0 turn, so p0 needs ``warp_total`` warp-color
    # mana + ``spell_total`` spell-color mana available at once. Seat
    # exactly that many of each colored basic up front (plus 1 spare of
    # each for the dual-producer-free single-tap discipline), then a
    # warp-color tail. Deterministic seed=None deck-list order (no RNG).
    n_w = warp_total + 1
    n_s = spell_total + 1
    prefix = (
        [warp_card, spell_card]
        + [sbasic] * n_s
        + [wbasic] * n_w
    )
    library = tuple(prefix + [wbasic] * (60 - len(prefix)))
    spec = DeckSpec(
        card_defs=(cd_w, cd_s, wland, sland),
        p0_library=library,
        p1_library=(wbasic,) * 40,
    )
    py, rs = trajectory.setup_matched_game(spec)
    for pl in py.players:
        pl.agent = _PickFirstLegalTargetAgent()

    label = f"{warp_card}+{spell_card}"
    adv = _make_adv(label, py, rs)

    adv(3)  # turn 1 → MAIN1
    # Ramp one land/turn until p0 controls enough of BOTH colors to
    # warp-cast the creature AND cast the removal/debuff in one turn
    # (adv(24) returns to p0 MAIN1 two turns later — p1's no-op turn
    # keeps the game deterministic).
    for _ in range(40):
        n_wland = sum(
            1 for o in py.battlefield
            if o.controller_id == py.active_player_idx
            and o.printing.name == wbasic)
        n_sland = sum(
            1 for o in py.battlefield
            if o.controller_id == py.active_player_idx
            and o.printing.name == sbasic)
        if (py.active_player_idx == 0
                and n_wland >= warp_total and n_sland >= spell_total):
            break
        if (py.active_player_idx == 0
                and py.players[0].lands_played_this_turn == 0):
            hand = py.players[0].hand
            hl = [o for o in hand
                  if o.printing.name in (wbasic, sbasic)]
            if hl:
                s = step_both(
                    py, rs,
                    {"kind": "play_land", "card_id": int(hl[0].id)})
                assert not s.divergences, (
                    f"{label}: play_land diverged: "
                    f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
                )
        adv(24)

    ai = py.active_player_idx
    n_wland = sum(
        1 for o in py.battlefield
        if o.controller_id == ai and o.printing.name == wbasic
        and not o.tapped and not o.summoning_sick
    )
    n_sland = sum(
        1 for o in py.battlefield
        if o.controller_id == ai and o.printing.name == sbasic
        and not o.tapped and not o.summoning_sick
    )
    if ai != 0 or n_wland < warp_total or n_sland < spell_total:
        pytest.skip(
            f"{label}: real ramp did not develop {warp_total} {wbasic} "
            f"+ {spell_total} {sbasic} on p0's turn (got w={n_wland} "
            f"s={n_sland} ai={ai}) — land-light shuffle; the byte-equal "
            f"trajectory up to here held."
        )
    _tap_color(py, rs, ai, warp_color, warp_total, label)
    wobj = next(
        o for o in py.players[ai].hand
        if o.printing.name == warp_card)
    s = step_both_drained(
        py, rs,
        {"kind": "cast_spell", "card_id": int(wobj.id),
         "use_warp": True})
    assert not s.divergences, (
        f"{label}: warp cast diverged (FULL compare_fields): "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )
    assert py.spell_warped_this_turn is True
    assert rs.spell_warped_this_turn is True
    warp_obj = next(
        o for o in py.battlefield
        if o.printing.name == warp_card)
    assert warp_obj.cast_via_warp is True, (
        f"{label}: the warp creature must carry the warp marker "
        f"(cast_via_warp) — the end-step exile sweep is keyed on it"
    )
    return py, rs, adv, ai, warp_obj


def test_radiant_strike_destroys_warp_creature_before_its_exile_sweep():
    """**Interaction 2 — a bench-admitted removal spell DESTROYS a
    warp-cast creature BEFORE its end-step exile sweep (spell-resolve ×
    ``WarpExileSelf`` ordering × graveyard-not-exile destination).**

    p0 warp-casts Bygone Colossus (9/9 **Artifact** Creature, warp
    ``{3}``; the warp marker schedules a ``WarpExileSelf`` delayed
    trigger for this turn's end step). p0 taps it (mirrored cross-engine
    so the ``IsArtifact() | (IsCreature() & IsTapped())`` OR-filter's
    tapped-creature leg unambiguously applies), then casts the genuine
    Radiant Strike through the Phase-1 carrier targeting it →
    ``DestroyTargetArtifactOrTappedCreature`` destroys it → it goes to
    the **GRAVEYARD** (a spell-destroy, NOT the warp-exile). At this
    turn's end step the scheduled ``WarpExileSelf`` fires but the
    permanent already left the battlefield → **no-op** per CR 603.6c
    (it must NOT yank the card from the graveyard into exile).

    Asserts, FULL ``compare_fields`` == [] at every step / phase
    boundary AND post-resolve: Bygone Colossus in p0's **graveyard**
    (NOT exile) on BOTH engines after Radiant Strike resolves; the
    end-step ``WarpExileSelf`` a no-op (``exile`` stays empty of Bygone
    Colossus, ``graveyard`` keeps it) on BOTH engines.

    Distinct from the warp lifecycle / warp+combat probes (the warp
    permanent is never removed by a spell there — it always reaches its
    own exile sweep) and the isolated Radiant Strike real-EoE probe
    (Grizzly Bears, no warp marker, no delayed-trigger ordering).
    """
    from mtg_bot.parity.cross_engine import compare_fields, step_both, step_both_drained
    from mtg_bot.legal import legal_actions
    from test_trajectory_parity import _step_views

    py, rs, adv, ai, bygone = _warp_then_bridged_spell_setup(
        warp_card="Bygone Colossus", warp_color="G", warp_str="{3}",
        spell_card="Radiant Strike", spell_color="W",
    )

    # Tap Bygone Colossus on BOTH engines so the OR-filter's
    # tapped-creature leg unambiguously matches (mirrored manual
    # mutation — re-confirm byte-equal before the spell or the probe's
    # premise is unsound).
    assert rs.tap_object(int(bygone.id)) is True
    bygone.tapped = True
    pv, rv = _step_views(py, rs)
    d = compare_fields(pv, rv)
    assert not d, (
        f"Bygone Colossus: mirrored tap left the views divergent "
        f"(probe-setup unsoundness): "
        f"{[(x.field, x.py_value, x.rust_value) for x in d]}"
    )

    # Cast Radiant Strike ({3}{W}) through the Phase-1 carrier on the
    # tapped warp creature.
    _tap_color(py, rs, ai, "W", 4, "Bygone+Radiant")
    rsk = next(
        o for o in py.players[ai].hand
        if o.printing.name == "Radiant Strike")
    s = step_both_drained(
        py, rs, {"kind": "cast_spell", "card_id": int(rsk.id)})
    assert not s.divergences, (
        f"Bygone+Radiant: Radiant Strike cast→resolve through the "
        f"Phase-1 carrier diverged (FULL compare_fields): "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )

    # Spell-destroy destination: GRAVEYARD, not exile, on BOTH engines.
    py_bf = [o for o in py.battlefield
             if o.printing.name == "Bygone Colossus"]
    py_gy = [o for o in py.players[ai].graveyard
             if o.printing.name == "Bygone Colossus"]
    rs_bf = [e for e in rs.battlefield_snapshot()
             if e["printing_name"] == "Bygone Colossus"]
    rs_gy = [e for e in rs.graveyard_snapshot(ai)
             if e["printing_name"] == "Bygone Colossus"]
    assert not py_bf and not rs_bf, (
        f"Bygone Colossus must have left the battlefield on BOTH "
        f"(Radiant Strike destroyed it); py_bf={len(py_bf)} "
        f"rs_bf={len(rs_bf)}"
    )
    assert len(py_gy) == 1 and len(rs_gy) == 1, (
        f"a spell-destroyed warp creature goes to the GRAVEYARD (NOT "
        f"the warp-exile) on BOTH; py_gy={len(py_gy)} rs_gy={len(rs_gy)}"
    )

    # End step: the scheduled WarpExileSelf fires but the permanent
    # already left → no-op (CR 603.6c). It must NOT pull Bygone Colossus
    # from the graveyard into exile. FULL byte-equal at the boundary.
    adv(7)
    py_ex = sorted(o.printing.name for o in py.players[ai].exile)
    rs_ex = sorted(e["printing_name"]
                   for e in rs.exile_snapshot(ai))
    py_gy2 = sorted(o.printing.name
                    for o in py.players[ai].graveyard)
    rs_gy2 = sorted(e["printing_name"]
                    for e in rs.graveyard_snapshot(ai))
    assert "Bygone Colossus" not in py_ex, (
        f"the end-step WarpExileSelf must be a NO-OP (the permanent "
        f"already left the battlefield, CR 603.6c) — it must NOT yank "
        f"Bygone Colossus from the graveyard into exile; py_ex={py_ex}"
    )
    assert py_ex == rs_ex, (
        f"warp-exile no-op exile state must be byte-equal; "
        f"py_ex={py_ex} rs_ex={rs_ex}"
    )
    assert "Bygone Colossus" in py_gy2 and py_gy2 == rs_gy2, (
        f"Bygone Colossus must STAY in the graveyard (the spell-destroy "
        f"destination) on BOTH; py_gy={py_gy2} rs_gy={rs_gy2}"
    )
    pv, rv = _step_views(py, rs)
    fd = compare_fields(pv, rv)
    assert not fd, (
        f"Bygone+Radiant: end-step (post WarpExileSelf no-op) FULL "
        f"compare_fields diverged: "
        f"{[(x.field, x.py_value, x.rust_value) for x in fd]}"
    )


def test_depressurize_debuffs_surviving_warp_creature_then_sweep_exiles_it():
    """**Interaction 3 — the OPPOSITE ordering: a bench-admitted debuff
    spell does NOT kill a warp-cast creature, so the warp-exile sweep
    STILL fires (non-lethal spell × warp-exile destination = EXILE, not
    graveyard, with the UEOT modifier draining on a warp-exiled
    permanent).**

    p0 warp-casts Germinating Wurm (5/5, warp ``{1}{G}``; ETB GainLife
    2, byte-equal). p0 casts the genuine Depressurize through the
    Phase-1 carrier on it: -3/-0 UEOT → eff power 5-3 = 2 > 0 → the
    conditional ``destroy()`` does NOT fire → the Wurm SURVIVES the
    spell. At this turn's end step the scheduled ``WarpExileSelf`` STILL
    fires (the warp marker is untouched by a non-lethal debuff) → the
    Wurm goes to **EXILE** (the warp destination, NOT the graveyard),
    and the -3/-0 UEOT modifier drains correctly on the warp-exiled
    permanent.

    Asserts FULL ``compare_fields`` == [] at every step / phase
    boundary AND post-resolve: the Wurm SURVIVES Depressurize on BOTH;
    then is in p0's **EXILE** (NOT graveyard) after the sweep on BOTH;
    Depressurize itself in the graveyard on BOTH.

    Distinct from Interaction 2 (there the spell KILLS the warp
    creature → graveyard, sweep no-ops; here the spell does NOT kill →
    the sweep fires, exile destination) and from the isolated
    Depressurize real-EoE probe (no warp marker, no exile-sweep
    ordering). Pins that a non-lethal UEOT debuff is transparent to the
    warp-exile sweep cross-engine.
    """
    from mtg_bot.parity.cross_engine import compare_fields, step_both, step_both_drained
    from test_trajectory_parity import _step_views

    py, rs, adv, ai, wurm = _warp_then_bridged_spell_setup(
        warp_card="Germinating Wurm", warp_color="G",
        warp_str="{1}{G}", spell_card="Depressurize", spell_color="B",
    )

    # Cast Depressurize ({1}{B}) through the Phase-1 carrier on the
    # 5/5 warp creature. 5-3 = 2 > 0 → SURVIVES the conditional destroy.
    _tap_color(py, rs, ai, "B", 2, "Wurm+Depressurize")
    dpc = next(
        o for o in py.players[ai].hand
        if o.printing.name == "Depressurize")
    s = step_both_drained(
        py, rs, {"kind": "cast_spell", "card_id": int(dpc.id)})
    assert not s.divergences, (
        f"Wurm+Depressurize: Depressurize cast→resolve through the "
        f"Phase-1 carrier diverged (FULL compare_fields): "
        f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
    )

    py_bf = [o for o in py.battlefield
             if o.printing.name == "Germinating Wurm"]
    rs_bf = [e for e in rs.battlefield_snapshot()
             if e["printing_name"] == "Germinating Wurm"]
    assert len(py_bf) == 1 and len(rs_bf) == 1, (
        f"Germinating Wurm (5/5) must SURVIVE Depressurize (eff power "
        f"5-3 = 2 > 0 → conditional destroy does NOT fire) on BOTH; "
        f"py_bf={len(py_bf)} rs_bf={len(rs_bf)}"
    )

    # End step: the warp marker is untouched by the non-lethal debuff,
    # so WarpExileSelf STILL fires → the Wurm goes to EXILE (the warp
    # destination), NOT the graveyard. FULL byte-equal at the boundary.
    # S7-A2: drain the stack via the explicit primitive so the
    # CR-603.7 delayed trigger resolves into exile on BOTH engines.
    from mtg_bot.parity.cross_engine import drain_stack_both
    adv(7)
    drain_stack_both(py, rs)
    py_ex = sorted(o.printing.name for o in py.players[ai].exile)
    rs_ex = sorted(e["printing_name"]
                   for e in rs.exile_snapshot(ai))
    py_gy = sorted(o.printing.name
                   for o in py.players[ai].graveyard)
    rs_gy = sorted(e["printing_name"]
                   for e in rs.graveyard_snapshot(ai))
    assert "Germinating Wurm" in py_ex, (
        f"a SURVIVING warp creature is still warp-exiled at its end "
        f"step (the non-lethal debuff is transparent to the warp "
        f"marker) → EXILE, not graveyard; py_ex={py_ex}"
    )
    assert py_ex == rs_ex, (
        f"warp-exile destination must be byte-equal; py_ex={py_ex} "
        f"rs_ex={rs_ex}"
    )
    assert "Germinating Wurm" not in py_gy, (
        f"the surviving warp creature must NOT be in the graveyard "
        f"(it was exiled by the warp sweep, not destroyed); "
        f"py_gy={py_gy}"
    )
    assert py_gy == rs_gy, (
        f"graveyard (Depressurize only) must be byte-equal; "
        f"py_gy={py_gy} rs_gy={rs_gy}"
    )
    pv, rv = _step_views(py, rs)
    fd = compare_fields(pv, rv)
    assert not fd, (
        f"Wurm+Depressurize: end-step (post warp-exile of the "
        f"survivor) FULL compare_fields diverged: "
        f"{[(x.field, x.py_value, x.rust_value) for x in fd]}"
    )


# ---------------------------------------------------------------------------
# Interaction 4 — Depressurize DESTROYING a creature that carries a
# ``DIES`` triggered ability (the round-74 post-spell-admit bench-sweep
# discovery R74-2; Rust-side, Python ``src/mtg_bot/`` is SoT).
#
# **The divergence (R74-2 — NEW, now FIXED Rust-side).** Rust's
# ``Effect::DepressurizeEffect`` conditional-destroy branch is a
# HAND-ROLLED destroy (it ``bf.remove``s the object, sets
# ``zone=GRAVEYARD``, pushes to the graveyard, calls
# ``mark_left_battlefield_if_nonland``, and pushed ONLY
# ``pending_leaves_dispatches``). It NEVER pushed
# ``pending_dies_dispatches`` — so a destroyed creature's
# ``Event.DIES`` triggered ability silently never fired. Python's
# ``DepressurizeEffect.resolve`` (``effects/bespoke.py:1589``) calls
# ``turn.destroy`` → ``move_off_battlefield`` (``turn.py:253-283``)
# which fires the DIES trigger (``_fire_dies_triggers`` + the
# predicate-path ``dispatch_event(Event.DIES)``) BEFORE the LEAVES
# trigger — so Python correctly produces the dies-trigger's token /
# effect. The generic SBA destroy path (``state_ops_sba.rs``
# :467-482) ALREADY pushes BOTH ``pending_dies_dispatches`` (creature-
# gated) and ``pending_leaves_dispatches`` and drains DIES-then-LEAVES
# (:497/:503); the hand-rolled Depressurize arm diverged from BOTH
# Python (SoT) AND Rust's own generic destroy path. Empirically
# surfaced by the round-74 sweep: Depressurize destroying **Gravpack
# Monoist** (``Event.DIES / IsSelf → CreateToken(Robot, tapped)``)
# produced the Robot token on Python but not on Rust (single-field
# ``battlefield`` divergence; no ``graveyard_pX`` component → distinct
# from CFI-1, which is the SAME arm's separate already-closed stray
# ``obj.counters = 0;``). Repro
# ``bench_trajectory_parity --archetype 216 --seed 0``; full
# diagnosis in ``docs/bench_trajectory_parity_smoke.md`` round-74.
#
# **Fix (this slice, Rust-side, new-code-is-right).** The
# DepressurizeEffect destroy branch now pushes
# ``pending_dies_dispatches`` (creature-gated, exactly mirroring the
# SBA path's ``victim_is_creature`` gate) BEFORE the existing
# ``pending_leaves_dispatches`` push, and the four spell/trigger
# resolution sites in ``state_ops_resolve.rs`` now drain
# ``pending_dies_dispatches`` immediately BEFORE
# ``pending_leaves_dispatches`` (DIES drained then LEAVES → LIFO
# resolution → LEAVES resolves first, byte-equal to the SBA path +
# Python's ``move_off_battlefield`` sequence). Outside ``apply_sbas``
# (which self-drains) the ONLY producer of ``pending_dies_dispatches``
# is this DepressurizeEffect arm, so the added drains are a verified
# no-op for every pre-R74-2 resolution. Python untouched (SoT,
# correct). A faithful parity fix aligning the Rust outlier to Python
# + Rust's own generic destroy path — NOT a shortcut, so no
# ``SEARCH_LIMITATIONS.md`` entry is warranted (the CFI-1 precedent).
#
# **Disjointness.** A distinct cross-feature dimension from every
# sibling probe: a removal spell DESTROYING a creature whose own
# ``DIES`` trigger then resolves. The isolated Depressurize probe
# (``test_parity_smoke.py``) kills only vanilla / counter'd creatures
# (no DIES trigger); CFI-1's negative control kills a counter'd
# creature (no DIES trigger). No isolated probe casts Depressurize at
# a DIES-trigger creature so the conditional-destroy reaches the
# dies-dispatch path.
# ---------------------------------------------------------------------------


def _gravpack_dies_token_trigger_dict(robot_pid):
    """The Gravpack-Monoist-shaped DIES→CreateToken trigger dict
    (the EXACT parsed shape: ``Event.DIES / IsSelf →
    CreateToken(Robot, count=1, tapped=True)``; the ``tapped`` rider
    is a Python-side-only flag with no Rust ``CreateToken`` mirror per
    the ``create_token`` bridge arm docstring, so it is OMITTED from
    the cross-engine dict — both engines mint an untapped Robot
    byte-equal, which is the R74-2 observable). Consumed identically
    by Rust ``register_and_inject_object`` and the Python bridge
    translator ``_ta_dict_to_python_triggered_ability``."""
    return {
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "create_token",
            "count": 1,
            "token_printing_id": robot_pid,
        },
    }


def _seat_dies_trigger_creature(py, rs, *, robot_pid):
    """Seat one identical p0-controlled 2/1 creature carrying the
    Gravpack-Monoist DIES→CreateToken(Robot) trigger on BOTH engines'
    battlefields. The Robot token printing is pre-registered at
    ``robot_pid`` via the ``DeckSpec.card_defs`` path (a registry
    entry with NO live object on EITHER engine — see the caller), so
    NO library/id-offset asymmetry is introduced (a registration
    DUMMY object would diverge a FULL field view). The Python bridge
    side resolves the same pid via the canonical
    ``register_token_printing`` +
    ``_ta_dict_to_python_triggered_ability`` pattern. Returns
    ``(py_obj, rs_id)``."""
    from mtg_bot.cards.base import (
        CardPrinting, ManaCost, make_token_creature,
    )
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
        clear_token_printings, register_token_printing,
    )

    ZONE_BATTLEFIELD = 2

    trig_dict = _gravpack_dies_token_trigger_dict(robot_pid)

    # ---- Rust: inject the DIES-trigger creature onto p0's bf (the
    # Robot printing is already in the registry at robot_pid via the
    # caller's card_defs). ----
    rs_creature_dict = {
        "name": "Gravpack R74-2 Probe",
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 1,
        "effects": [],
        "triggered_abilities": [trig_dict],
    }
    rs_id = rs.register_and_inject_object(
        rs_creature_dict, 0, ZONE_BATTLEFIELD)

    # ---- Python: register the matching Robot token printing against
    # Rust's pid via the bridge, then assemble the DIES-trigger
    # creature using the SAME trigger-dict shape Rust consumed (the
    # canonical cross-engine pattern). ----
    py_robot_token = make_token_creature(
        name="Robot R74-2 Probe",
        power=2,
        toughness=2,
        subtypes=("Robot",),
        artifact=True,
    )
    clear_token_printings()
    register_token_printing(robot_pid, py_robot_token)
    py_trig = _ta_dict_to_python_triggered_ability(trig_dict)
    py_printing = CardPrinting(
        name="Gravpack R74-2 Probe",
        mana_cost_str="", mana_cost=ManaCost(generic=0),
        type_line="Creature", supertypes=(),
        card_types=("Creature",), subtypes=(),
        power=2, toughness=1, produces=frozenset(),
        triggered_abilities=(py_trig,),
    )
    py_obj = py.new_object(py_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    return py_obj, rs_id


def _cast_depressurize_then_drain(py, rs, py_obj, rs_id):
    """Cast genuine Depressurize (Python: the ACTUAL parsed EoE
    ``spell_effect`` on a ``StackItem``; Rust: the bridged
    ``depressurize_effect`` synthetic Instant) targeting the seated
    creature, then FULLY drain both stacks (Depressurize resolves →
    destroys → the creature's DIES trigger lands on the stack →
    resolves → Robot token), run SBA on both. Returns the post-drain
    FULL ``compare_fields`` diff list."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import DepressurizeEffect
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    dp = get_active_source().get_printings().get("Depressurize")
    if dp is None:
        pytest.skip("Depressurize absent from CardSource")
    assert isinstance(dp.spell_effect, DepressurizeEffect), (
        f"genuine Depressurize spell_effect must be DepressurizeEffect;"
        f" got {type(dp.spell_effect).__name__}"
    )
    assert dp.spell_effect.power_penalty == 3

    # ---- Python: genuine Depressurize as a real spell_effect. ----
    py_spell = py.new_object(dp, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_obj.id),))
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bridged depressurize_effect synthetic Instant. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Depressurize", "card_types": ["Instant"],
         "effects": [{"kind": "depressurize_effect",
                      "power_penalty": 3}]}, 0, 0)
    rs.push_to_stack(rs_spell_id, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    return compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )


def test_depressurize_destroying_dies_trigger_creature_fires_token_r74_2():
    """**Interaction 4 — Depressurize destroying a ``DIES``-trigger
    creature MUST fire the dies-trigger byte-equal (R74-2 closed).**

    p0 controls a 2/1 carrying the genuine Gravpack-Monoist-shaped
    ``Event.DIES / IsSelf → CreateToken(Robot)`` triggered ability.
    p0 casts the genuine Depressurize on it: -3/-0 UEOT → eff power
    2-3 = -1 ≤ 0 → ``destroy()``. Python's destroy → the creature's
    DIES trigger fires → a Robot token enters under p0's control.
    Pre-R74-2 Rust's hand-rolled DepressurizeEffect destroy arm
    pushed only ``pending_leaves_dispatches`` and NEVER
    ``pending_dies_dispatches``, so the Robot token NEVER appeared on
    Rust — a single-field ``battlefield`` divergence (the R74-2
    bench-sweep discovery).

    Post-fix the Rust arm pushes ``pending_dies_dispatches``
    (creature-gated, mirroring the SBA path) and the resolution sites
    drain DIES-before-LEAVES, so the Robot token appears byte-equal
    on BOTH engines. Asserts:

      * the original creature is DEAD on BOTH (Depressurize's
        conditional destroy succeeded — no indestructible);
      * exactly ONE Robot token on p0's battlefield on BOTH (the
        dies-trigger fired);
      * FULL ``compare_fields`` == [] over the WHOLE cross-engine
        field view (the strongest tier — a missing dies-trigger
        token, a wrong controller, or a wrong post-destroy zone
        state on either engine flips this and FAILs loudly).

    This is the permanent regression pin for the CLOSED Rust-side
    divergence R74-2. Distinct from CFI-1's negative control (a
    counter'd creature with NO dies-trigger killed by Depressurize)
    and the isolated Depressurize §2 probes (vanilla / counter'd, no
    dies-trigger).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    # The Robot token printing is registered via card_defs (NOT in
    # any library) so BOTH engines get a registry entry at a
    # deterministic pid with NO live object and NO id consumed — a
    # registration-DUMMY live object would shift every subsequent
    # object's id slot and leave an asymmetric library entry,
    # diverging the FULL field view (the harness-artifact the first
    # draft of this pin surfaced; fixed new-code-is-right by the
    # no-dummy card_defs registration, the established
    # build_rust_state/build_python_state symmetric-id idiom).
    robot_carddef = CardDef(
        name="Robot R74-2 Probe",
        card_type="Creature",
        extra_card_types=("Artifact",),
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(robot_carddef,), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    # The Robot is the SOLE registered printing → its pid is 0
    # (deterministic: card_defs registration order, empty libraries).
    assert rs.registry_size == 1, (
        f"probe pre-condition: Robot must be the only registered "
        f"printing (pid 0); got registry_size={rs.registry_size}"
    )
    robot_pid = 0

    py_obj, rs_id = _seat_dies_trigger_creature(
        py, rs, robot_pid=robot_pid)
    diffs = _cast_depressurize_then_drain(py, rs, py_obj, rs_id)

    # The original creature is dead on BOTH (destroy succeeded).
    py_alive = any(o.id == py_obj.id for o in py.battlefield)
    rs_alive = any(e["id"] == rs_id
                   for e in rs.battlefield_snapshot())
    assert py_alive is False and rs_alive is False, (
        f"Depressurize -3/-0 on a printed 2/1 → eff power -1 ≤ 0 → "
        f"destroy() SUCCEEDS → the creature dies on BOTH; "
        f"py_alive={py_alive} rs_alive={rs_alive}"
    )

    # Exactly one Robot token on p0's bf on BOTH (the DIES trigger
    # fired). This is the R74-2 observable: pre-fix Rust had ZERO.
    py_robots = [
        o for o in py.battlefield
        if o.controller_id == 0
        and o.printing.name == "Robot R74-2 Probe"
    ]
    rs_robots = [
        e for e in rs.battlefield_snapshot()
        if e.get("printing_name") == "Robot R74-2 Probe"
    ]
    assert len(py_robots) == 1, (
        f"Python: Depressurize-destroyed Gravpack's DIES trigger must "
        f"create exactly 1 Robot token; got {len(py_robots)}"
    )
    assert len(rs_robots) == 1, (
        f"R74-2 regression — Rust: the Depressurize-destroyed "
        f"DIES-trigger creature's token MUST fire (the hand-rolled "
        f"destroy arm now pushes pending_dies_dispatches); got "
        f"{len(rs_robots)} Robot tokens (pre-fix bug = 0)"
    )

    # FULL cross-engine field view byte-equal — no carve-out.
    assert diffs == [], (
        f"R74-2 regression — a Depressurize-destroyed DIES-trigger "
        f"creature must be byte-equal across the WHOLE field view "
        f"(the dies-trigger's Robot token fires on BOTH engines); "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------------
# **Interaction 5 — Radiant Strike destroying a tapped ``DIES``-trigger
# creature MUST fire the dies-trigger byte-equal (round-76 bench-resweep
# discovery R76-2; Rust-side, Python ``src/mtg_bot/`` is SoT; SAME
# class as R74-2, a DIFFERENT Effect arm).**
#
# **The divergence (R76-2 — NEW, now FIXED Rust-side).** Rust's
# ``Effect::DestroyTargetArtifactOrTappedCreature`` (Radiant Strike's
# destroy half — ``{3}{W}`` Instant: *"Destroy target artifact or
# tapped creature. You gain 3 life."*; ``spell_effect`` =
# ``Sequence(DestroyTargetArtifactOrTappedCreature, GainLife(3))``) is
# ANOTHER HAND-ROLLED destroy structurally identical to the R74-2
# DepressurizeEffect anti-pattern: it ``bf.remove``s the object,
# graveyards it, ``mark_left_battlefield_if_nonland``, pushed ONLY
# ``pending_leaves_dispatches`` (+ ``queue_token_cease``) — and NEVER
# ``pending_dies_dispatches``. So a destroyed tapped dies-trigger
# creature (e.g. Gravpack Monoist → Robot) silently never fired its
# trigger. Python's ``DestroyTargetArtifactOrTappedCreature.resolve``
# (``effects/generic/destroy.py``) calls ``turn.destroy`` → fires the
# DIES trigger (CR 603 / 700.4). R74-2's fix (``f38df833``) added the
# DIES drain at the 4 resolution sites + the dies-push at the
# ``DepressurizeEffect`` arm ONLY — it did NOT touch this distinct
# Effect arm, so the round-74 coarse ``cast_spell::battlefield``
# bucket had CONFLATED this with R74-2; the R74-2 fix un-masked it as
# the standalone R76-2 (round-76 re-sweep). Repro
# ``bench_trajectory_parity --archetype 52021 --seed 7``; full
# diagnosis in ``docs/bench_trajectory_parity_smoke.md`` round-76.
#
# **Fix (this slice, Rust-side, new-code-is-right).** The
# ``DestroyTargetArtifactOrTappedCreature`` destroy arm now pushes
# ``pending_dies_dispatches`` (creature-gated — so the OR-filter's
# *artifact* leg does NOT fire a spurious DIES; CR 700.4) BEFORE the
# existing ``pending_leaves_dispatches`` push, exactly the R74-2
# ``f38df833`` shape transplanted to this arm. The 4 resolution sites
# already drain ``pending_dies_dispatches`` DIES-before-LEAVES (R74-2
# added those drains globally), so NO resolution-site change is
# needed. The verbatim-clone sibling — Seedship Impact's destroy-half
# (its own comment says it clones this body) — got the SAME
# creature-gated dies-push (a dual-typed Artifact Creature is
# admissible under Seedship's Artifact-OR-Enchantment filter AND is a
# creature, so Python's generic ``destroy`` would fire its DIES
# trigger). Python untouched (SoT, correct). A faithful parity fix
# aligning the Rust outliers to Python + Rust's own generic SBA
# destroy path — NOT a shortcut, so no ``SEARCH_LIMITATIONS.md``
# entry is warranted (the R74-2 / CFI-1 precedent).
#
# **Disjointness.** A distinct cross-feature dimension from Interaction
# 4: a SEQUENCE-composed removal spell (destroy-then-gain-life) whose
# FIRST sub-effect destroys a TAPPED creature whose own ``DIES``
# trigger then resolves — exercising a different hand-rolled destroy
# arm AND the Sequence combinator AND the tapped-leg of the OR-filter.
# ---------------------------------------------------------------------------


def _seat_tapped_dies_trigger_creature(py, rs, *, robot_pid):
    """Sibling of :func:`_seat_dies_trigger_creature` that seats the
    Gravpack-shaped DIES→CreateToken(Robot) creature **TAPPED** on
    BOTH engines (Radiant Strike's destroy filter is *artifact OR
    TAPPED creature* — an untapped non-artifact creature is NOT a
    legal target, so the probe creature must be tapped to be hit).
    Returns ``(py_obj, rs_id)``."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards.base import make_token_creature
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
        clear_token_printings, register_token_printing,
    )

    ZONE_BATTLEFIELD = 2
    trig_dict = _gravpack_dies_token_trigger_dict(robot_pid)

    # ---- Rust: inject the tapped DIES-trigger creature on p0's bf. ----
    rs_creature_dict = {
        "name": "Gravpack R76-2 Probe",
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 1,
        "effects": [],
        "triggered_abilities": [trig_dict],
    }
    rs_id = rs.register_and_inject_object(
        rs_creature_dict, 0, ZONE_BATTLEFIELD)
    # Tap it so Radiant Strike's "tapped creature" OR-leg admits it.
    assert rs.tap_object(rs_id) is True, (
        "probe setup: the seated R76-2 creature must tap")

    # ---- Python: matching tapped DIES-trigger creature. ----
    py_robot_token = make_token_creature(
        name="Robot R76-2 Probe",
        power=2,
        toughness=2,
        subtypes=("Robot",),
        artifact=True,
    )
    clear_token_printings()
    register_token_printing(robot_pid, py_robot_token)
    py_trig = _ta_dict_to_python_triggered_ability(trig_dict)
    py_printing = CardPrinting(
        name="Gravpack R76-2 Probe",
        mana_cost_str="", mana_cost=ManaCost(generic=0),
        type_line="Creature", supertypes=(),
        card_types=("Creature",), subtypes=(),
        power=2, toughness=1, produces=frozenset(),
        triggered_abilities=(py_trig,),
    )
    py_obj = py.new_object(
        py_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = True
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    return py_obj, rs_id


def _cast_radiant_strike_then_drain(py, rs, py_obj, rs_id):
    """Cast genuine Radiant Strike (Python: the ACTUAL parsed EoE
    ``spell_effect`` — ``Sequence(DestroyTargetArtifactOrTapped
    Creature, GainLife(3))`` — on a ``StackItem``; Rust: the bridged
    ``sequence`` synthetic Instant carrying the same two-leaf dict)
    targeting the seated tapped creature, then FULLY drain both stacks
    (Radiant Strike resolves → destroys → the creature's DIES trigger
    lands on the stack → resolves → Robot token; +3 life), run SBA on
    both. Returns the post-drain FULL ``compare_fields`` diff list."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    rsp = get_active_source().get_printings().get("Radiant Strike")
    if rsp is None:
        pytest.skip("Radiant Strike absent from CardSource")
    assert isinstance(rsp.spell_effect, Sequence), (
        f"genuine Radiant Strike spell_effect must be a Sequence; "
        f"got {type(rsp.spell_effect).__name__}"
    )

    # ---- Python: genuine Radiant Strike as a real spell_effect. ----
    py_spell = py.new_object(rsp, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_obj.id),))
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bridged Sequence synthetic Instant (the EXACT
    # reverse-serializer dict the spell-card-bridge produces for the
    # real Radiant Strike printing). ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Radiant Strike", "card_types": ["Instant"],
         "effects": [{
             "kind": "sequence",
             "effects": [
                 {"kind": "destroy_target_artifact_or_tapped_creature"},
                 {"kind": "gain_life", "amount": 3},
             ],
         }]}, 0, 0)
    rs.push_to_stack(rs_spell_id, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    return compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )


def test_radiant_strike_destroying_dies_trigger_creature_fires_token_r76_2():
    """**Interaction 5 — Radiant Strike destroying a tapped ``DIES``-
    trigger creature MUST fire the dies-trigger byte-equal (R76-2
    closed).**

    p0 controls a TAPPED 2/1 carrying the genuine Gravpack-Monoist-
    shaped ``Event.DIES / IsSelf → CreateToken(Robot)`` trigger. p0
    casts the genuine Radiant Strike (``Sequence(DestroyTarget
    ArtifactOrTappedCreature, GainLife(3))``) on it: the tapped
    creature is destroyed (OR-filter's tapped-creature leg) → Python's
    generic ``destroy`` fires the DIES trigger → a Robot token enters
    under p0's control; +3 life. Pre-R76-2 Rust's hand-rolled
    ``DestroyTargetArtifactOrTappedCreature`` destroy arm pushed only
    ``pending_leaves_dispatches`` and NEVER
    ``pending_dies_dispatches``, so the Robot token NEVER appeared on
    Rust — a single-field ``battlefield`` divergence (the round-76
    bench-resweep R76-2 discovery; same class as R74-2, different
    Effect arm).

    Post-fix the Rust arm pushes ``pending_dies_dispatches`` (creature-
    gated, so the OR-filter's artifact leg does NOT fire a spurious
    DIES) BEFORE ``pending_leaves_dispatches``; the resolution sites
    already drain DIES-before-LEAVES (R74-2 global drains). Asserts:

      * the original creature is DEAD on BOTH;
      * exactly ONE Robot token on p0's battlefield on BOTH (the
        dies-trigger fired — the R76-2 observable; pre-fix Rust = 0);
      * FULL ``compare_fields`` == [] over the WHOLE cross-engine
        field view (a missing dies-trigger token, wrong life total
        from the GainLife leg, or wrong post-destroy zone flips this
        and FAILs loudly).

    Permanent regression pin for the CLOSED Rust-side divergence
    R76-2. Distinct from Interaction 4 (R74-2 — Depressurize, an
    UNtapped creature, a single-effect spell): this is a SEQUENCE-
    composed spell destroying a TAPPED creature via a DIFFERENT
    hand-rolled destroy arm.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
    )

    robot_carddef = CardDef(
        name="Robot R76-2 Probe",
        card_type="Creature",
        extra_card_types=("Artifact",),
        power=2,
        toughness=2,
    )
    spec = DeckSpec(
        card_defs=(robot_carddef,), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    assert rs.registry_size == 1, (
        f"probe pre-condition: Robot must be the only registered "
        f"printing (pid 0); got registry_size={rs.registry_size}"
    )
    robot_pid = 0

    py_obj, rs_id = _seat_tapped_dies_trigger_creature(
        py, rs, robot_pid=robot_pid)
    diffs = _cast_radiant_strike_then_drain(py, rs, py_obj, rs_id)

    # The original creature is dead on BOTH (destroy succeeded).
    py_alive = any(o.id == py_obj.id for o in py.battlefield)
    rs_alive = any(e["id"] == rs_id
                   for e in rs.battlefield_snapshot())
    assert py_alive is False and rs_alive is False, (
        f"Radiant Strike on a tapped 2/1 → DestroyTargetArtifactOr"
        f"TappedCreature destroys it on BOTH; "
        f"py_alive={py_alive} rs_alive={rs_alive}"
    )

    # Exactly one Robot token on p0's bf on BOTH (the DIES trigger
    # fired). This is the R76-2 observable: pre-fix Rust had ZERO.
    py_robots = [
        o for o in py.battlefield
        if o.controller_id == 0
        and o.printing.name == "Robot R76-2 Probe"
    ]
    rs_robots = [
        e for e in rs.battlefield_snapshot()
        if e.get("printing_name") == "Robot R76-2 Probe"
    ]
    assert len(py_robots) == 1, (
        f"Python: Radiant-Strike-destroyed Gravpack's DIES trigger "
        f"must create exactly 1 Robot token; got {len(py_robots)}"
    )
    assert len(rs_robots) == 1, (
        f"R76-2 regression — Rust: the Radiant-Strike-destroyed "
        f"tapped DIES-trigger creature's token MUST fire (the "
        f"DestroyTargetArtifactOrTappedCreature hand-rolled destroy "
        f"arm now pushes pending_dies_dispatches); got "
        f"{len(rs_robots)} Robot tokens (pre-fix bug = 0)"
    )

    # FULL cross-engine field view byte-equal — no carve-out (the
    # GainLife(3) leg's life delta + the dies-trigger token are all
    # in-scope).
    assert diffs == [], (
        f"R76-2 regression — a Radiant-Strike-destroyed tapped "
        f"DIES-trigger creature must be byte-equal across the WHOLE "
        f"field view (the dies-trigger's Robot token fires + the "
        f"Sequence's GainLife(3) applies on BOTH engines); "
        f"diffs={diffs}"
    )
