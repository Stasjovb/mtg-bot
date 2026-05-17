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
    from mtg_bot.parity.cross_engine import step_both

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
        CardDef, DeckSpec, step_both,
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
    s = step_both(
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
    from mtg_bot.parity.cross_engine import compare_fields, step_both
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
    s = step_both(
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
    from mtg_bot.parity.cross_engine import compare_fields, step_both
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
    s = step_both(
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
    adv(7)
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
