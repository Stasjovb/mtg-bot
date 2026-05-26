"""Measured, regenerable POOL-LEVEL cross-engine parity metric.

The campaign has long answered "how far from parity?" with PROXIES:

  * per-*emission* Rust Effect coverage (``docs/RUST_EFFECT_COVERAGE.md``,
    ``scripts/measure_effect_coverage.py``) — weighted by how many
    cards each Effect class appears on, NOT a per-card classification;
  * the honest residue count (``docs/residue_worklist.json``) — the
    distinct genuinely-Rust-blocked cards, but only the blocked tail;
  * "0 FAIL_DIVERGENCE over the bridge-admitted bench subset"
    (``docs/bench_trajectory_parity_smoke.md``) — an empirical signal
    over whatever the loader admits, not a tracked pool fraction.

None of those is a single authoritative, tracked, *measured* number
for "what fraction of the EoE card pool is byte-equal cross-engine".
This script is that metric. It classifies **every** card in the EoE
pool (the same pool ``measure_effect_coverage`` walks) into honest,
precisely-defined tiers and reports the counts + percentages, then
writes ``docs/POOL_PARITY.md`` (auto-overwritten on each run) and
prints the same markdown to stdout — the same idiom as
``measure_effect_coverage.py``.

WHAT THIS MEASURES (and what it does NOT)
-----------------------------------------
This metric measures **Effect+bridge-level byte-equality evidence**,
NOT full-game-trajectory parity. The strongest tier (PROBED) has a
genuine real-EoE cross-engine probe asserting byte-equality on a
controlled state; the next tier (covered-by-construction) only proves
every Effect the card emits has a live Rust variant + bridge arm — it
does NOT prove the card is byte-equal in a real multi-turn game. The
bench tier is the empirical full-trajectory signal but is capped at
~22-25 turns and only over the loader-admitted subset. **No tier here
claims "byte-equal in real full-game trajectories for the whole
pool"** — that is explicitly out of scope and stated as a caveat in
the generated doc. Honest discipline: the headline reports the
modest, defensible number, not a flattering one.

Run with::

    PYTHONPATH=src \\
    ../../mtg-bot/.venv-py313/Scripts/python.exe \\
    scripts/measure_pool_parity.py

This script does not depend on the Rust extension being built — it
reuses ``measure_effect_coverage``'s pure-text ``cards.rs`` parser and
its EoE-pool walker (``collect_python_effect_vocab`` /
``collect_rust_effect_variants`` — the parse rule is NOT duplicated
here) plus the pure-Python ``parity.trajectory`` admit predicates and
a text scan of ``tests/test_parity_smoke.py``. The companion test
``tests/test_measure_pool_parity.py`` exercises the classifier.

TIER DEFINITIONS (precise)
--------------------------
Each EoE printing lands in EXACTLY ONE tier, evaluated in this
strict precedence order (strongest evidence wins):

1. **PROBED byte-equal** — a genuine real-EoE cross-engine probe in
   ``tests/test_parity_smoke.py`` (a ``test_cross_engine_real_eoe_
   <slug>_parity`` function whose name-prefix is the snake_case slug
   of this card's printed name — split cards keyed on the left face)
   asserts byte-equality for THIS card. Strongest evidence: a real
   pool printing pinned end-to-end on both engines on a controlled
   state. (Still a controlled-state probe, NOT a full random game —
   see the caveat above.)

2. **Effect+bridge covered (not individually probed)** — every
   distinct Python ``Effect`` class this card emits (walked with
   ``measure_effect_coverage``'s exact walker) has a live Rust
   ``Effect::`` variant + a wired bridge arm (i.e. is in the coverage
   script's covered-class set), AND the card is NOT a BLOCKED entry
   in ``docs/residue_worklist.json``. Covered-by-construction: the
   primitives all exist + bridge, but no genuine probe pins THIS
   card, so it is weaker evidence than PROBED. A card with zero
   Effects (pure vanilla / keyword-only) counts here only if it is
   also loader-admitted (otherwise it cannot be cross-engine
   exercised at all and falls to the relevant lower tier).

3. **bridge-admitted & bench-exercised** — the production-deck
   loader admits this printing (it passes
   ``trajectory._printing_is_bridge_basic_land`` or
   ``trajectory._printing_is_bridge_simple_creature`` — the exact
   admit gate the bench corpus runs through) and the bench has run
   it 0-divergence at scale. CAVEAT: the bench caps at ~22-25 turns
   (``docs/bench_trajectory_parity_smoke.md``), so this is a
   bounded-depth empirical signal, not a game-end guarantee.

4. **BLOCKED** — not byte-equal-covered today. Broken out into:
   * ``blocked_genuinely_missing`` — a residue worklist
     ``genuinely_missing`` entry: a TRUE new-Rust-Effect ask (the
     load-bearing "how far from parity" gap).
   * ``blocked_non_effect`` — a residue worklist
     ``blocked_non_effect`` entry: the card's Effects ARE shipped;
     it is gated by a non-Effect path (unbridged event / declined
     cost-mechanic / unmodeled subsystem / token-registration
     substrate).
   * ``blocked_subsystem_gated`` — NOT in the residue worklist as
     blocked, NOT probed, NOT covered-by-construction, NOT
     loader-admitted: the card emits at least one Effect with no
     covered Rust counterpart, OR is loader-rejected by a subsystem
     gate (Station / Ward / Devour / warp / Aura / Rooms /
     BECOMES_TAPPED / dynamic-P/T / activated+static abilities /
     planeswalker / …). The long, un-itemised blocked tail.

INTERNAL-CONSISTENCY CROSS-CHECK
--------------------------------
A card listed BLOCKED (``genuinely_missing`` or
``blocked_non_effect``) in ``docs/residue_worklist.json`` must NOT be
counted in PROBED or covered-by-construction. The script asserts this
and emits a ``WARNING`` line into the doc + a non-zero structural
flag (the companion test pins it) if a residue-blocked card ever
sneaks into a covered tier — exactly the residue-vs-headline drift
class the round-54/55/56 cron guards, applied to THIS metric.
"""

from __future__ import annotations

import ast
import io
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
OUTPUT_DOC = REPO_ROOT / "docs" / "POOL_PARITY.md"
SMOKE_TEST = REPO_ROOT / "tests" / "test_parity_smoke.py"
RESIDUE_WORKLIST = REPO_ROOT / "docs" / "residue_worklist.json"

# --- The DEDICATED genuine-real-EoE probe modules (cycles 3-4) ----------
#
# HONEST-MEASUREMENT-TOOLING fix (resolves the orchestrator's standing
# cycle-4 flag). The original PROBED detector scanned ONLY
# ``tests/test_parity_smoke.py`` for ``test_cross_engine_real_eoe_
# <slug>_parity`` functions. Cycles 3-4 added FOUR new dedicated probe
# modules (the ``test_probe_covered_unprobed_{a,b,c,d}.py`` batch
# stream) carrying ~27 genuine real-EoE cross-engine byte-equality
# probes that use the EXACT same idiom + the EXACT same
# ``test_cross_engine_real_eoe_<...>_parity`` naming convention as the
# 60 cards already credited from the smoke file — but live in a
# different file, so the metric did not see them and ``PROBED``
# understated real probe coverage. This list is the closed set of
# modules whose ``*_parity`` functions are scanned with the SAME
# inclusion bar (see ``genuine_probed_cards``).
#
# DELIBERATELY EXCLUDED (a defensible zero-undercount integrity
# choice, NOT an oversight):
#
#   * ``tests/test_probe_warp_admitted.py`` and
#     ``tests/test_probe_spell_card_bridge_admitted.py`` — these ARE
#     genuine real-EoE byte-equal probes, but (a) their functions do
#     NOT use the established ``_parity`` slug-keyed naming convention
#     (they are ``test_warp_admitted_*`` /
#     ``test_spell_card_bridge_phase1_carrier_*`` parametrized sweeps),
#     so crediting them would require a SECOND, looser inclusion rule —
#     a weaker bar than the established one; and (b) every card they
#     pin (Radiant Strike, Depressurize, Seedship Impact, Orbital
#     Plunge, the five warp creatures) is ALREADY individually PROBED
#     via its canonical ``test_cross_engine_real_eoe_<slug>_parity``
#     function in ``tests/test_parity_smoke.py``. Excluding the
#     differently-named modules therefore costs ZERO undercount while
#     keeping exactly ONE inclusion predicate at exactly the
#     established bar — the "match the established bar; if unsure,
#     undercount rather than inflate" discipline.
#
# CYCLE-10 HONEST-ATTRIBUTION RECONCILIATION (the recurring
# measurement-attribution gap the cycle-10 fold flagged: ``PROBED=104``
# understated real probe coverage by the Tier-C target-seating cards).
# The Tier-C lever-a slices (Sunset Saboteur ``5e05cbaa`` / Exosuit
# Savior ``fa3d17b4``) each landed a GENUINE real-EoE cross-engine
# byte-equal firing-parity probe — drives the live parsed printing
# (``get_active_source().get_printings().get("Sunset Saboteur" /
# "Exosuit Savior")``) end-to-end through the production ATTACKS / ETB
# path on BOTH engines and asserts byte-equal state (the SAME idiom +
# the SAME strength bar as the 60+ cards already credited). The probes
# were authored IN ``tests/test_parity_smoke.py`` (already scanned) but
# their function names ended ``_attacks_seats_first_opponent_creature``
# / ``_etb_seats_first_own_permanent`` instead of the established
# ``..._parity`` convention, so the unchanged single inclusion
# predicate (``_smoke_probed_cards`` / ``_probe_module_probed_cards``
# both require the ``_parity`` suffix) silently UNDERCOUNTED them — the
# SAME class of bug the cycle-4 batch-module flag tracked, surfacing
# again. RESOLUTION (the established discipline — conform the deviating
# probes to the convention, do NOT loosen the bar / add a second
# looser predicate): the two functions were renamed to append
# ``_parity`` (``feature/probe-modules-tierc-registration``), so the
# UNCHANGED smoke detector now credits them at EXACTLY the established
# bar. PROBED 104 → 106 (+Sunset Saboteur, +Exosuit Savior; both move
# covered-by-construction → the stronger PROBED tier — the byte-equal
# headline total is unchanged, only the evidence tier strengthens).
#
# HONESTLY EXCLUDED (the bar cuts both ways — NOT an oversight):
#
#   * **Diplomatic Relations** — historical carve-out CLOSED by the
#     round-26 YYY batch (``tests/test_probe_remaining_yyy.py``:
#     ``test_cross_engine_real_eoe_diplomatic_relations_parity``).  The
#     YYY probe meets the same parse + bridge round-trip + Python-side
#     resolve idiom DDD slice 17's Honored Knight-Captain probe
#     established as a PROBE_MODULES-credited shape -- the live printing
#     is bound via ``get_active_source().get_printings().get("Diplomatic
#     Relations")``, the ``diplomatic_relations_effect`` bridge round-
#     trip is verified, and the Python-side 2-slot resolve drives pump+
#     vigilance+power-equal damage on a controlled state.  The
#     ``tests/test_cross_engine_etb_triggers.py`` ``test_bridge_*_bidirectional_round_trip`` and
#     ``test_bridge_spell_card_lever_phase2_diplomatic_relations_real_eoe_cast_resolve_parity``
#     pre-existing tests remain as the trajectory-harness-driven
#     cross-engine full-cast-resolve pin (a stronger but
#     non-PROBE_MODULES-credited shape); the YYY probe closes the
#     attribution gap at the established bar.
#
# MEASUREMENT-ATTRIBUTION SWEEP P1 (2026-05-21,
# ``feature/measurement-attribution-sweep-p1``) — exhaustive scanner-vs-
# source audit, sibling to the same-day
# ``feature/probe-modules-scanner-fix`` (registered 3 dedicated probe
# modules) / ``feature/loader-admits-attribution-sweep`` (folded missing
# loader-admits disjuncts) / ``feature/scout-survivors-slug`` (added a
# slug delegator for Scout for Survivors) lanes.  The sweep enumerated
# every ``def test_cross_engine_real_eoe_<...>_parity`` function in the
# test surface (324 across 94 files) and cross-checked each enclosing
# module against this PROBE_MODULES list + ``SMOKE_TEST``.  Findings:
#
#   * **0 missing canonical probes.** 10 unregistered modules surfaced
#     -- ALL 10 are ``tests/test_divergence_pins_*.py`` post-closure
#     markers whose ``*_parity`` functions ALL use the ``_FIXED_parity``
#     convention (e.g.
#     ``test_cross_engine_real_eoe_lightless_evangel_is_sacrificed_ordering_FIXED_parity``).
#     The ``_FIXED_parity`` convention pins a previously-divergent shape
#     post-closure, NOT a canonical real-EoE byte-equal probe; the
#     ``feature/probe-modules-scanner-fix`` precedent honest-stopped
#     these by design.  Registering them would CHANGE the inclusion
#     semantic (post-closure markers are a different shape, different
#     intent), not close an attribution gap.  HONEST-STOP: do NOT
#     register the 10 ``test_divergence_pins_*.py`` modules.
#
#   * **0 misnamed canonical probes.** A search for ``test_*`` functions
#     that bind an unprobed pool card via ``get_printings().get("X")``
#     AND carry a cross-engine byte-equal signature
#     (``compare_fields`` / ``byte_equal`` / ``FAIL_DIVERGENCE`` + a
#     ``rust`` / ``cross_engine`` reference) returned 0 candidates.  The
#     scanner's ``get_printings()``-binding match (introduced when
#     PROBE_MODULES was widened beyond SMOKE_TEST) sidesteps the
#     apostrophe-elision class of bug entirely; no slug-mismatch class
#     remains.
#
#   * **0 loader_admits disjunct gaps.**  ``loader_admits`` currently
#     mirrors all 10 disjuncts of
#     ``trajectory._filter_deck_to_bridge_supported``'s admit gate
#     (verified line-by-line against ``trajectory.py:7738-7853``); no
#     11th disjunct has landed since the round-85 N1
#     ``_printing_is_bridge_simple_tapped_mana_land`` widening that the
#     ``feature/loader-admits-attribution-sweep`` lane already folded
#     in.
#
# Audit shape: 324 ``_parity`` functions enumerated across 94 modules,
# 88 PROBE_MODULES + 1 SMOKE_TEST = 89 registered carriers, 10
# ``_FIXED_parity`` honest-stop excludes, 0 missing attributions.
# PROBED 279 unchanged (the metric is tight at this point in the
# campaign — every canonical real-EoE byte-equal probe in the test
# surface is credited).  This is a doc-only audit commit; no
# attribution counts move.
PROBE_MODULES: tuple[Path, ...] = (
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_a.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_b.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_c.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_d.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_e.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_f.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_g.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_h.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_i.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_j.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_k.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_l.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_m.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_n.py",
    REPO_ROOT / "tests" / "test_probe_activated_abilities_o2.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_p.py",
    REPO_ROOT / "tests" / "test_probe_activated_abilities_q.py",
    REPO_ROOT / "tests" / "test_probe_may_do_r.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_s.py",
    REPO_ROOT / "tests" / "test_probe_activated_abilities_t.py",
    REPO_ROOT / "tests" / "test_probe_modal_counterspell_u.py",
    REPO_ROOT / "tests" / "test_probe_covered_unprobed_v.py",
    REPO_ROOT / "tests" / "test_probe_activated_abilities_w.py",
    REPO_ROOT / "tests" / "test_probe_attacks_leaves_battlefield_x.py",
    REPO_ROOT / "tests" / "test_probe_activated_abilities_y.py",
    REPO_ROOT / "tests" / "test_probe_attacks_round2_z.py",
    REPO_ROOT / "tests" / "test_probe_cast_spell_aa.py",
    REPO_ROOT / "tests" / "test_probe_activated_abilities_bb.py",
    REPO_ROOT / "tests" / "test_probe_activated_abilities_ee.py",
    REPO_ROOT / "tests" / "test_probe_activated_abilities_hh.py",
    REPO_ROOT / "tests" / "test_probe_subject_is_enchantment_unlock.py",
    REPO_ROOT / "tests" / "test_probe_activated_abilities_kk.py",
    REPO_ROOT / "tests" / "test_probe_has_power_at_most_unlock.py",
    REPO_ROOT / "tests" / "test_probe_eerie_cards_nn.py",
    REPO_ROOT / "tests" / "test_divergence_pins_dd.py",
    REPO_ROOT / "tests" / "test_probe_remaining_qq.py",
    REPO_ROOT / "tests" / "test_probe_deals_combat_damage_unlock.py",
    REPO_ROOT / "tests" / "test_probe_remaining_tt.py",
    REPO_ROOT / "tests" / "test_probe_phase_step_unlock.py",
    REPO_ROOT / "tests" / "test_probe_remaining_ww.py",
    REPO_ROOT / "tests" / "test_probe_you_attack_unlock.py",
    REPO_ROOT / "tests" / "test_probe_remaining_zz.py",
    REPO_ROOT / "tests" / "test_divergence_pins_xx.py",
    REPO_ROOT / "tests" / "test_probe_remaining_ccc.py",
    REPO_ROOT / "tests" / "test_divergence_pins_aaa.py",
    REPO_ROOT / "tests" / "test_divergence_pins_uu.py",
    REPO_ROOT / "tests" / "test_probe_remaining_fff.py",
    REPO_ROOT / "tests" / "test_probe_rr_events_trio.py",
    REPO_ROOT / "tests" / "test_probe_remaining_iii.py",
    REPO_ROOT / "tests" / "test_divergence_pins_rr.py",
    REPO_ROOT / "tests" / "test_probe_bbb_downstream.py",
    REPO_ROOT / "tests" / "test_probe_remaining_lll.py",
    REPO_ROOT / "tests" / "test_probe_eee_downstream_unlock.py",
    REPO_ROOT / "tests" / "test_divergence_pins_jjj.py",
    REPO_ROOT
    / "tests"
    / "test_probe_idiom_unlocked_optional_cost_mirror.py",
    REPO_ROOT
    / "tests"
    / "test_probe_idiom_unlocked_multi_target_picker.py",
    REPO_ROOT / "tests" / "test_probe_remaining_ooo.py",
    REPO_ROOT / "tests" / "test_probe_remaining_qqq.py",
    REPO_ROOT / "tests" / "test_divergence_pins_oo.py",
    # 12th Rust slice (slot-aware Controlled bridge form + RRR Pin 1):
    REPO_ROOT / "tests" / "test_probe_mmm_downstream.py",
    REPO_ROOT / "tests" / "test_probe_rrr_downstream.py",
    # Probe batch SSS (round 23 covered-but-unprobed):
    REPO_ROOT / "tests" / "test_probe_remaining_sss.py",
    # Probe batch UUU (round 24 covered-but-unprobed):
    REPO_ROOT / "tests" / "test_probe_remaining_uuu.py",
    # Probe batch WWW (round 25 covered-but-unprobed):
    REPO_ROOT / "tests" / "test_probe_remaining_www.py",
    # 14th Rust slice (TTT Pins 1+2 closures):
    REPO_ROOT / "tests" / "test_probe_ttt_downstream.py",
    # 15th Rust slice (VVV Pin 1 — Predicate::SourceIsSelf
    # player-subject tautology arm for Survivor postcombat-main):
    REPO_ROOT / "tests" / "test_probe_vvv_downstream.py",
    # 17th Rust slice (DDD Pins 1+2+3 — pure-Python bridge arms for
    # SurveyMechanActivationEffect + ExileTopXOfLibraryMayPlayThisTurn
    # + SearchLibraryForEquipmentToBattlefield; first Formula
    # dispatcher _ta_dict_to_python_formula in cross_engine.py):
    REPO_ROOT / "tests" / "test_probe_ddd_downstream.py",
    # Probe batch YYY (round 26 covered-but-unprobed) — the two
    # remaining bespoke-Effect covered-by-construction cards
    # (Diplomatic Relations + Astelli Reclaimer) closed via the same
    # parse + bridge round-trip + Python-side resolve idiom DDD
    # slice 17's Honored Knight-Captain probe established:
    REPO_ROOT / "tests" / "test_probe_remaining_yyy.py",
    # 18th Rust slice (XXX Pin 2 — Roving Actuator Void ETB; new
    # Effect::RovingActuatorETBEffect { max_mv: u8 } variant +
    # parse + resolve + bridge; cast-from-exile-copy-for-free
    # substrate via recursive apply_effect on the exiled card's
    # printing.effects with the source-controller transient pinned):
    REPO_ROOT / "tests" / "test_probe_xxx_downstream.py",
    # Probe batch ZZZ (round 26 covered-but-unprobed) — the LAST
    # alphabetic-named probe batch.  Reinstates two YYY drop-list
    # entries that the YYY-idiom (parse + bridge round-trip +
    # Python-side resolve, NO cross-engine compare_fields) DOES
    # unblock -- Stay Hidden, Stay Silent (Aura ETB +
    # TapEnchantedPermanent unit-variant) and Sheltered by Ghosts
    # (Aura ETB + ExileOpponentsNonlandPermanentUntilLeaves; FIRST
    # Aura-carrier shape on that effect class, distinct from the
    # PROBED Banishing Light bare-Enchantment carrier).  Future
    # probe batches (round 27+) must use a 4-letter or numeric
    # naming convention -- the alphabetic 3-letter naming is
    # exhausted by this batch.
    REPO_ROOT / "tests" / "test_probe_remaining_zzz.py",
    # Probe batch AAAA (round 27 covered-but-unprobed) — the FIRST
    # 4-letter probe batch, established post-ZZZ alphabetic exhaustion
    # per the ZZZ docstring naming-convention note.  Two cards from
    # the covered tier upgraded to PROBED via the same parse + bridge
    # round-trip + Python-side resolve idiom DDD slice 17 / YYY / ZZZ
    # established:
    #   * Cryoshatter (Aura with BECOMES_TAPPED + DEALT_DAMAGE host-
    #     event triggers -> DestroyEnchantedPermanent; FIRST Aura-
    #     carrier with the DestroyEnchantedPermanent unit-variant
    #     to land a credited _parity probe -- complements ZZZ's
    #     Stay Hidden / Stay Silent Aura ETB + TapEnchantedPermanent
    #     by pinning DESTROY-mutation + host-event-triggered firing).
    #   * Meltstrider's Gear (Equipment ENTERS + IsSelf ->
    #     AttachToTargetCreatureYouControl bare, no UEOT keyword
    #     rider; FIRST Equipment-carrier ETB with the bare attach
    #     to land a credited _parity probe -- the bridge docstring
    #     at cross_engine.py:3367-3372 explicitly cited Meltstrider's
    #     Gear as the cleanest real-EoE consumer of the bare shape).
    # Subsequent 4-letter batches follow BBBB / CCCC / ... per the
    # established alphabetic cadence, now widened by one letter to
    # give the campaign another 26 batches of room.
    REPO_ROOT / "tests" / "test_probe_remaining_aaaa.py",
    # Probe batch BBBB (round 28 covered-but-unprobed) — second
    # 4-letter probe batch.  One probe lands via the QQQ cross-engine
    # spell-effect idiom: Withering Torment (Instant
    # Sequence(DestroyTargetCreature, LoseLife(2)) — FIRST Sequence-
    # of-destroy+lose_life spell-effect probe; ``lose_life``
    # previously pinned only at synthetic-ETB-trigger level (round
    # 24)).  Vanish from Sight DROPPED on verify for a bounce-to-
    # library summoning-sick divergence — parallel to the ZZZ-flagged
    # exile-summoning-sick gap (Trapped in the Screen drop); a
    # sibling-lane divergence pin should pin the bounce path.  See
    # module docstring for the full honest-exhaustion drop list.
    REPO_ROOT / "tests" / "test_probe_remaining_bbbb.py",
    # Probe batch CCCC (round 29 covered-but-unprobed) — third
    # 4-letter probe batch (after AAAA and BBBB).  Two cards from
    # the covered tier upgraded to PROBED via the same parse +
    # bridge round-trip + Python-side resolve idiom DDD slice 17 /
    # YYY / ZZZ / AAAA established:
    #   * Lightless Evangel (Creature IS_SACRIFICED ->
    #     PutPlusOneCounterOnSelf(amount=1); FIRST IS_SACRIFICED-
    #     event carrier of the effect class to land a credited
    #     probe -- complements the existing ENTERS / IS_CAST event
    #     consumers covered by construction).
    #   * Skystinger (Creature BLOCKS -> PumpSelfUntilEOT(
    #     power_bonus=5, toughness_bonus=0, granted_keywords=
    #     frozenset()); FIRST BLOCKS-event carrier of the BARE-shape
    #     variant -- the empty granted_keywords is what makes the
    #     bare bridge byte-equal, distinguishing it from the
    #     covered-but-not-probed Hand That Feeds / Cult Healer
    #     rider-bearing variants).
    # Trapped in the Screen was considered but DROPPED on verify
    # (bit-identical shape to the already-PROBED Banishing Light;
    # the same ZZZ + YYY drop-list precedent that already pins this
    # as honest-exhaustion).
    REPO_ROOT / "tests" / "test_probe_remaining_cccc.py",
    # Probe batch DDDD (round 30 reclaim covered-but-unprobed) —
    # fourth 4-letter probe batch (after AAAA, BBBB, CCCC; sibling
    # to EEEE which merged first and shipped DDDD's originally-
    # drafted cards Starwinder + Broodguard Elite).  This reclaim
    # re-picks two DIFFERENT covered-but-unprobed cards to avoid
    # duplicate credit (the PROBED-credit predicate is name+_parity
    # function match; re-probing the EEEE cards would not move the
    # classifier needle).  Two cards from the covered tier upgraded
    # to PROBED via the same parse + bridge round-trip + Python-side
    # resolve idiom DDD slice 17 / YYY / ZZZ / AAAA / CCCC / EEEE
    # established:
    #   * Meltstrider Eulogist (Creature DIES -> DrawCards(amount=1);
    #     FIRST PROBE_MODULES-credited probe of the DIES + bare
    #     DrawCards event + effect-class combination -- the only EoE
    #     consumer of this combination, with the HasCounter
    #     predicate drop-recovered under the YYY-idiom per the
    #     CCCC Lightless Evangel predicate-is-metadata precedent;
    #     the i-batch's prior drop used the full-compare_fields
    #     idiom requiring Rust-bridge predicate parity, which the
    #     YYY-idiom does not).
    #   * Balemurk Leech (Creature ENTERS ->
    #     EachOpponentLosesLife(amount=1); FIRST PROBE_MODULES-
    #     credited probe of the EachOpponentLosesLife effect class
    #     -- the only EoE consumer of this effect class per the
    #     bridge-arm docstring at cross_engine.py:4872-4874; the CR
    #     118.4 direct life loss primitive distinct from sibling
    #     TargetOpponentLosesLife and DamageEachOpponent; the
    #     non-credited test_probe_subject_is_enchantment_unlock.py
    #     function predates the _parity naming convention and uses
    #     full compare_fields requiring the Rust-bridge subject_is_
    #     enchantment arm, while DDDD lands the credited _parity
    #     variant under the YYY-idiom).
    # Honest-exhaustion drops: Sami, Ship's Engineer (Conditional
    # OnTappedCreatures wrapper substrate), Meltstrider's Resolve
    # (Aura subsystem -- in flight on feature/aura-substrate-step-7),
    # Dawnsire (no bare DealDamageToTargetCreature bridge arm; only
    # the rider-bearing variant ships), Fear of Failed Tests (bit-
    # identical to EEEE Starwinder), Cackling Slasher / Daggermaw /
    # vanilla creatures (no Effects to probe), activated-ability
    # cards (subsystem-gated, separate probe surface).  See module
    # docstring for the full honest-exhaustion drop list.
    REPO_ROOT / "tests" / "test_probe_remaining_dddd.py",
    # Probe batch EEEE (round 31 reclaim covered-but-unprobed) — fifth
    # 4-letter probe batch (this slot was previously claimed by an
    # agent that hit the API limit; that branch is gone, slot
    # reclaimed fresh).  Two cards from the covered tier upgraded to
    # PROBED via the same parse + bridge round-trip + Python-side
    # resolve idiom DDD slice 17 / YYY / ZZZ / AAAA / CCCC
    # established:
    #   * Starwinder (Creature DEALS_COMBAT_DAMAGE ->
    #     DrawCardsEqualToResolvingCombatDamage(); FIRST credited
    #     probe of this bare unit-variant effect class -- the
    #     WWW/YYY batches explicitly deferred this card citing
    #     combat-damage harness substrate, but the bare effect+
    #     bridge+resolve idiom unblocks it: the resolve reads
    #     state.resolving_combat_damage_amount, which the probe
    #     sets directly per the effect's resolve contract at
    #     draw_mill.py:106; the harness-driven trajectory firing
    #     is a stronger but distinct test shape that stays
    #     deferred).
    #   * Broodguard Elite (Creature LEAVES_BATTLEFIELD ->
    #     MoveSelfCountersToTargetCreatureYouControl(); FIRST
    #     LEAVES_BATTLEFIELD-event carrier of this effect class to
    #     land a credited probe -- complements the existing
    #     PROBED Dockworker Drone ENTERS-event carrier).
    # Fear of Failed Tests was considered but DROPPED on verify
    # (bit-identical effect-class shape to Starwinder; the predicate
    # distinction is metadata and does not move the PROBED-tier
    # classifier).  See module docstring for the full honest-
    # exhaustion drop list.
    REPO_ROOT / "tests" / "test_probe_remaining_eeee.py",
    # Probe batch FFFF (round 32 relaunch covered-but-unprobed) — sixth
    # 4-letter probe batch (this slot was previously claimed by an
    # agent that timed out at worktree creation; that branch is gone,
    # slot reclaimed fresh).  ONE card from the covered tier upgraded
    # to PROBED via the same parse + bridge round-trip + Python-side
    # resolve idiom DDD slice 17 / YYY / ZZZ / AAAA / CCCC / EEEE /
    # DDDD established:
    #   * Illvoi Operative (Creature IS_CAST ->
    #     PutPlusOneCounterOnSelf(amount=1); FIRST IS_CAST-event
    #     carrier of the PutPlusOneCounterOnSelf effect class to land
    #     a credited probe -- the only EoE consumer of this
    #     (event, effect-class) tuple.  Earlier YYY / SSS / UUU drops
    #     deferred this card on cross-engine compare_fields grounds
    #     (slice-12 IS_CAST stack-resolution-order divergence), but
    #     the EEEE-idiom (parse + bridge round-trip + Python-side
    #     resolve, NO cross-engine compare_fields) sidesteps that
    #     gap entirely -- same drop-recovery precedent DDDD used for
    #     Meltstrider Eulogist (HasCounter predicate gap) and EEEE
    #     used for Starwinder (combat-damage harness gap).
    # Honest-exhaustion is the dominant signal for the remainder of
    # the covered_by_construction tier -- the magecraft-family
    # siblings Cosmogrand Zenith / Station Monitor / Sunstar
    # Lightsmith are blocked by their EFFECT-class wrappers (modal /
    # token-registration / Sequence), not the IS_CAST event itself;
    # the long tail of activated-ability cards, Equipment / Aura /
    # Room subsystem cards, pump-rider cards, vanilla creatures,
    # ManifestDread substrate, and non-basic lands carry their own
    # subsystem / bridge-arm blockers (see module docstring for the
    # full honest-exhaustion drop list).
    REPO_ROOT / "tests" / "test_probe_remaining_ffff.py",
    # Probe batch GGGG (round 33 covered-but-unprobed) — seventh
    # 4-letter probe batch (after AAAA, BBBB, CCCC, DDDD, EEEE, FFFF).
    # ONE card from the covered tier upgraded to PROBED via the same
    # parse + bridge round-trip + Python-side resolve idiom DDD slice
    # 17 / YYY / ZZZ / AAAA / CCCC / DDDD / EEEE / FFFF established:
    #   * Roving Actuator (Artifact Creature ENTERS ->
    #     RovingActuatorETBEffect(max_mv=2); FIRST credited _parity
    #     probe of this dedicated bespoke effect class on the REAL
    #     parsed Roving Actuator EoE printing.  The
    #     test_probe_xxx_downstream.py test_xxx_probe_roving_actuator
    #     _* function family exercises the bridge round-trip + cross-
    #     engine resolve trajectory on a SYNTHETIC carrier (built
    #     via register_and_inject_object) but is NOT credited
    #     because the function names predate the _parity convention;
    #     GGGG binds the REAL parsed printing via
    #     get_printings().get("Roving Actuator") and asserts the
    #     empty-target short-circuit at bespoke.py:667-668).
    # Honest-exhaustion drops include Illvoi Operative (ALREADY
    # PROBED via FFFF round 32 relaunch, main HEAD 25c0d410 -- the
    # original GGGG draft included Illvoi Operative as a second
    # probe but it was dropped on origin/main merge since FFFF
    # landed first and credited it), Optimistic Scavenger (Drix
    # Fatemaker already PROBED on same effect+event combo), Unwanted
    # Remake / Come Back Wrong (Murder already PROBED bare),
    # Weapons Manufacturing / Station Monitor (token-registration
    # substrate), Clammy Prowler / Dawnsire (no bridge arm), Hand
    # That Feeds (granted_keywords rider dropped by bridge), Room
    # cards (Rooms subsystem), ManifestDread carriers (picker
    # substrate deferred), Sequence / Modal wrappers (no container-
    # level bridge), Pain for All / Tractor Beam (Aura phase 2 in
    # flight), vanilla / lands / activated-ability cards (separate
    # probe surface).  See module docstring for the full honest-
    # exhaustion drop list.
    REPO_ROOT / "tests" / "test_probe_remaining_gggg.py",
    # Probe batch HHHH (round 34 covered-but-unprobed) -- eighth
    # 4-letter probe batch (after AAAA, BBBB, CCCC, DDDD, EEEE, FFFF,
    # GGGG).  THREE Aura ENTERS bespoke-Effect cards from the covered
    # tier upgraded to PROBED via the same parse + bridge round-trip
    # + Python-side resolve idiom DDD slice 17 / YYY / ZZZ / AAAA /
    # CCCC / DDDD / EEEE / FFFF / GGGG established (the substrate-
    # shipped-but-no-_parity-probe measurement-attribution gap --
    # same shape as the warp_cost Phase 3 precedent at merge
    # 33188239):
    #   * Pain for All (Aura ENTERS -> PainForAllETBEffect();
    #     FIRST credited _parity probe of the Aura Phase 3 / S4
    #     triggered-shape bespoke effect class.  The
    #     test_probe_pain_for_all_downstream.py
    #     test_pain_for_all_etb_* family covers the bridge round-trip
    #     + Rust-side fizzle but predates the _parity naming
    #     convention; HHHH binds the REAL parsed Pain for All EoE
    #     printing and asserts the no-attached_to silent-fizzle at
    #     bespoke.py:389-391).
    #   * Tractor Beam (Aura ENTERS -> TapEnchantedPermanent();
    #     FIRST credited _parity probe of the Aura Phase 2 S2 /
    #     cast-time auto-resolve bespoke effect class.  The
    #     test_tractor_beam.py / test_tractor_beam_control.py /
    #     test_aura_substrate_phase_2_s2_extension.py test functions
    #     cover the resolve mechanics on synthetic carriers but
    #     predate the _parity naming convention; HHHH binds the REAL
    #     parsed Tractor Beam EoE printing and asserts the no-
    #     attached_to silent-fizzle at tap.py:516-517).
    #   * Meltstrider's Resolve (Aura ENTERS ->
    #     EnchantedCreatureFightsTargetEffect(); FIRST credited
    #     _parity probe of the slice-19 bespoke effect class.  The
    #     test_meltstriders_resolve.py /
    #     test_aura_substrate_phase_4.py test functions cover the
    #     resolve mechanics on synthetic carriers but predate the
    #     _parity naming convention; HHHH binds the REAL parsed
    #     Meltstrider's Resolve EoE printing and asserts the empty-
    #     target silent-fizzle at bespoke.py:544-545).
    # Honest-exhaustion drops include The Seriema (SearchLibrary
    # already PROBED via siblings), Lightstall Inquisitor (cast-
    # permission flag round-trip pending verification), Dawnsire /
    # Clammy Prowler / Temporal Intervention (no bridge arm), pump
    # carriers with granted_keywords riders (Hand That Feeds / Flesh
    # Burrower / Cult Healer / Give In to Violence / Dual-Sun
    # Technique / Horrid Vigor / Rig for War / Violent Urge -- bridge
    # drops the rider), token-registration cards (Sami / Station
    # Monitor / Weapons Manufacturing / Grand Entryway), Sequence /
    # Modal wrappers (Sunstar Lightsmith / Cosmogrand Zenith / Rust
    # Harvester / Requiem Monolith / Let's Play a Game / Split Up /
    # Lithobraking / Vanish from Sight / Unnerving Grasp), Equipment
    # carriers / ManifestDread carriers (substrate deferral), bit-
    # identical-to-PROBED-siblings (Trapped in the Screen / Unwanted
    # Remake / Come Back Wrong / Optimistic Scavenger), Room
    # subsystem cards, vanilla creatures, lands (separate activated-
    # ability surface).  See module docstring for the full honest-
    # exhaustion drop list.
    REPO_ROOT / "tests" / "test_probe_remaining_hhhh.py",
    # Probe batch IIII (round 35 covered-but-unprobed) -- ninth
    # 4-letter probe batch (after AAAA, BBBB, CCCC, DDDD, EEEE, FFFF,
    # GGGG, HHHH).  FOUR cards from the covered tier upgraded to
    # PROBED via the same parse + bridge round-trip + Python-side
    # resolve idiom DDD slice 17 / YYY / ZZZ / AAAA / CCCC / DDDD /
    # EEEE / FFFF / GGGG / HHHH established (the substrate-shipped-
    # but-no-_parity-probe measurement-attribution gap -- same shape
    # as the warp_cost Phase 3 precedent at merge 33188239):
    #   * Lightstall Inquisitor (Creature ENTERS ->
    #     EachOpponentExilesCardFromHandWithCastPermission(); FIRST
    #     credited _parity probe of the bespoke effect class shipped
    #     in the 20th Rust slice (XXX Pin 3 closure).  The
    #     test_probe_xxx_pin3_downstream.py test_xxx_pin3_* family
    #     exercises the bridge round-trip + Rust-side empty-hand no-op
    #     on a SYNTHETIC carrier; an existing _parity-suffixed
    #     function (test_xxx_pin3_real_eoe_lightstall_inquisitor_
    #     cast_from_exile_substrate_parity) does NOT match the slug
    #     scanner regex (which anchors on the full
    #     ``test_cross_engine_real_eoe_<slug>_parity`` prefix), so
    #     Lightstall remained uncredited.  IIII binds the REAL parsed
    #     Lightstall Inquisitor EoE printing and asserts the
    #     per-opponent empty-hand skip at discard.py:196-197).
    #   * The Seriema (Artifact (Spacecraft) ENTERS ->
    #     SearchLibraryForCard(filter_name='legendary_creature',
    #     max_mv=0, may_fail=False); FIRST credited _parity probe of
    #     the bare SearchLibraryForCard shape with the
    #     (legendary_creature, may_fail=False) parameterization on an
    #     ENTERS carrier.  Sibling PROBED consumers pin different
    #     parameterization quadruples: Spineseeker Centipede pins
    #     (ENTERS, bare, basic_land, may_fail=True); Starfield
    #     Shepherd pins (ENTERS, ModalChooseOne wrapper, basic_plains
    #     + creature_small); Demonic Counsel pins (SPELL, bare, demon,
    #     may_fail=False).  HHHH dropped The Seriema citing
    #     "SearchLibrary already PROBED via siblings" but the
    #     (legendary_creature, may_fail=False) bare-ENTERS quadruple
    #     was not covered by any of the three siblings -- the
    #     attribution-gap closure here is the credited delta).
    #   * Optimistic Scavenger (Creature ENTERS ->
    #     PutPlusOneCounterOnTargetCreature(amount=1); FIRST credited
    #     _parity probe binding the Optimistic Scavenger slug to the
    #     Effect+bridge round-trip on the REAL parsed EoE printing.
    #     The PROBED-tier classifier credits per-slug; sibling PROBED
    #     consumers (Drix Fatemaker / Mm'menon Uthros Exile / Honor /
    #     Selfcraft Mechan / Shrewd Storyteller) cover other (event,
    #     predicate) combos but no slug-keyed probe pinned Optimistic
    #     Scavenger.  HHHH dropped Optimistic Scavenger citing "bit-
    #     identical to PROBED Drix Fatemaker" but the predicate
    #     distinction (Subject(IsEnchantment) & Controlled(YOU) vs
    #     IsSelf) + the ROOM_FULLY_UNLOCKED second trigger DO produce
    #     a different per-slug attribution -- the classifier credits
    #     per-slug, not per-effect-class).
    #   * Command Bridge (Land ENTERS ->
    #     SacrificeSelfUnlessTapPermanent(); FIRST credited _parity
    #     probe of the bespoke effect class shipped in the 20th Rust
    #     slice (VVV Pin 2 closure).  Command Bridge is the ONLY EoE
    #     consumer of this effect class -- the HIGHEST-deck-count
    #     BLOCKED-genuinely_missing closure on the
    #     ``docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md`` list at the
    #     time of the VVV Pin 2 substrate landing (24,522 17lands
    #     decks).  HHHH's drop list cited "Lands (activated-ability
    #     surface)" generically as a skip reason for ALL lands, but
    #     Command Bridge is a LAND with a TRIGGERED ability surface
    #     distinct from its activated mana ability -- IIII pins the
    #     triggered shape via the no-source short-circuit at
    #     combinators.py:121-123).
    # Honest-exhaustion drops include Dawnsire / Clammy Prowler /
    # Temporal Intervention (no bridge arm), pump carriers with
    # granted_keywords riders (Hand That Feeds / Flesh Burrower / Cult
    # Healer / Give In to Violence / Dual-Sun Technique / Horrid Vigor
    # / Rig for War / Violent Urge -- bridge drops the rider), token-
    # registration cards (Sami / Station Monitor / Weapons
    # Manufacturing / Grand Entryway), Sequence / Modal wrappers with
    # substrate-deferred inner effects (Sunstar Lightsmith /
    # Cosmogrand Zenith / Rust Harvester / Requiem Monolith / Let's
    # Play a Game / Split Up / Lithobraking / Vanish from Sight /
    # Unnerving Grasp), Equipment carriers / ManifestDread carriers
    # (substrate deferral), bit-identical-to-PROBED-siblings (Trapped
    # in the Screen / Unwanted Remake / Come Back Wrong / Innocuous
    # Rat / Break Down the Door / Under the Skin / Fear of Failed
    # Tests / Irreverent Gremlin), Room subsystem cards, vanilla
    # creatures, lands (separate activated-ability surface), Lane K's
    # Tannuk + Frenzied Baloth (deferred per concurrent-agent note).
    # See module docstring for the full honest-exhaustion drop list.
    REPO_ROOT / "tests" / "test_probe_remaining_iiii.py",
    # Probe batch JJJJ (round 36 covered-but-unprobed) -- tenth
    # 4-letter probe batch (after AAAA, BBBB, CCCC, DDDD, EEEE, FFFF,
    # GGGG, HHHH, IIII).  THREE Room ENTERS / YOU_ATTACK triggered-
    # ability cards from the covered tier upgraded to PROBED via the
    # same parse + bridge round-trip + Python-side resolve idiom DDD
    # slice 17 / YYY / ZZZ / AAAA / CCCC / DDDD / EEEE / FFFF / GGGG /
    # HHHH / IIII established (the substrate-shipped-but-no-_parity-
    # probe measurement-attribution gap -- same shape as the warp_cost
    # Phase 3 precedent at merge 33188239, and IIII's Command Bridge
    # precedent that pinned a LAND triggered-ability surface distinct
    # from the activated mana ability surface):
    #   * Funeral Room // Awakening Hall (Enchantment (Room) ENTERS ->
    #     ReturnAllCreaturesFromYourGraveyardToBattlefield(); FIRST
    #     credited _parity probe of the bare untargeted-mass-
    #     reanimation effect class on the REAL parsed printing.
    #     The bridge docstring at cross_engine.py:6545-6546 stated
    #     "No EoE oracle hits today (Awakening Hall, the canonical
    #     consumer, is not in EoE)" incorrectly -- Awakening Hall IS
    #     in EoE as the back-half of the split card; JJJJ closes the
    #     corrective gap).
    #   * Moldering Gym // Weight Room (Enchantment (Room) ENTERS ->
    #     SearchLibraryForBasicLandTapped(count=1); FIRST credited
    #     _parity probe of the bare unwrapped shape on a triggered-
    #     ability carrier.  Larval Scoutlander is the known consumer
    #     of the OptionalSac-WRAPPED shape with count=2 -- a different
    #     carrier shape and parameterization.  Moldering Gym is the
    #     front-half door body; the Weight Room back-half emits
    #     ManifestDreadThenPutPlusOneCountersOnIt(counter_amount=3)
    #     which stays the dropped surface per the ManifestDread
    #     harness substrate deferral).
    #   * Surgical Suite // Hospital Room (Enchantment (Room)
    #     YOU_ATTACK -> PutPlusOneCounterOnTargetCreature(amount=1,
    #     attacking_only=True); FIRST credited _parity probe of the
    #     attacking_only=True parameterization.  IIII's Optimistic
    #     Scavenger probe explicitly named the attacking_only=True
    #     parameterization as a distinct axis ("the Hospital Room
    #     half shape" at tests/test_probe_remaining_iiii.py:972) and
    #     used Hospital Room as the contrast carrier for that
    #     distinctness assertion -- JJJJ now pins Hospital Room
    #     directly).
    # Honest-exhaustion drops include Bottomless Pool // Locker Room
    # (DEALS_COMBAT_DAMAGE -> DrawCards(amount=1) bit-identical to
    # PROBED Haliya / Illvoi Infiltrator), Innocuous Rat (DIES ->
    # ManifestDread(count=1) bit-identical to PROBED Bashful Beastie),
    # Ticket Booth // Tunnel of Hate (ENTERS -> ManifestDread bit-
    # identical to PROBED Unsettling Twins), Trapped in the Screen
    # (bit-identical to PROBED Banishing Light), Underwater Tunnel //
    # Slimy Aquarium / Break Down the Door / Under the Skin (Manifest
    # Dread substrate deferral), Grand Entryway (token-registration
    # substrate), Dawnsire / Clammy Prowler / Temporal Intervention
    # (no bridge arm), pump carriers with granted_keywords riders
    # (Hand That Feeds / Flesh Burrower / Cult Healer / Give In to
    # Violence / Dual-Sun Technique / Horrid Vigor / Rig for War /
    # Violent Urge / Derelict Attic // Widow's Walk YOU_ATTACK half),
    # Equipment ETB cards (Conductive Machete / Cursed Windbreaker /
    # Killer's Mask / Squire's Lightblade / Illvoi Light Jammer / The
    # Dominion Bracelet), Sequence / Modal wrappers with substrate-
    # deferred inner effects (Sunstar Lightsmith / Cosmogrand Zenith
    # / Rust Harvester / Requiem Monolith / Let's Play a Game / Split
    # Up / Lithobraking / Vanish from Sight / Unnerving Grasp /
    # Restricted Office // Lecture Hall / Mirror Room // Fractured
    # Realm), Fear of Failed Tests (bit-identical to PROBED Starwinder),
    # vanilla creatures + lands + activated-ability-only cards.  See
    # module docstring for the full honest-exhaustion drop list.
    REPO_ROOT / "tests" / "test_probe_remaining_jjjj.py",
    # Wrath-admit-widening lane (round-87, 2026-05-21) — the Phase-3
    # (0, 0)-shape wrath admit arm + three wrath-shape serializer
    # leaves (DealNDamageToEachCreature [Pyroclasm-shape] / bare
    # DestroyAllCreatures / ManifestDread) on
    # `_printing_is_bridge_simple_spell` + `_python_spell_effect_to_dict`.
    # Two ManifestDread carriers (Break Down the Door — Instant
    # {2}{G}; Under the Skin — Sorcery {2}{G}) flip COVERED -> PROBED
    # via the empty-library no-op probe idiom established by the
    # SSS-batch Manifest Dread probe. Pyroclasm AUTO-JOINS the admit
    # set but was already PROBED via the batch-G Pyroclasm probe.
    # Beyond the Quiet stays BLOCKED (substrate work — its
    # ExileAllCreaturesAndSpacecraft Effect is uncovered in Rust;
    # out of lane scope). See the module docstring for the full
    # honest-stop drop list (Singularity Rupture, Mutinous Massacre,
    # Zero Point Ballad, Zealous Display, etc.).
    REPO_ROOT / "tests" / "test_probe_wrath_admit_widening.py",
    # Reroute Systems closure (2026-05-21). Adds two
    # ``test_cross_engine_real_eoe_reroute_systems_<mode>_parity``
    # functions — the mode-0 (PumpTargetArtifactOrCreatureUntilEOT
    # widened with ``granted_keywords`` + at-cast per-mode detector
    # entry) and mode-1 (DealDamageToTargetTappedCreature new variant
    # + at-resolve filter recheck) probes for Reroute Systems
    # (6,132 17lands decks). The card AUTO-JOINS the spell-card-bridge
    # admit set via the same Cycle 4 widen + the new Cycle 5/6
    # per-mode detector entries + the new per-leaf reverse serializer
    # arms. PROBED tier count +1.
    REPO_ROOT / "tests" / "test_reroute_systems.py",
    # **drill-too-deep-slice (2026-05-21):** ModalChooseOne envelope
    # Cycle 6 — first per-mode-target ModalChooseOne closure. The
    # ``test_cross_engine_real_eoe_drill_too_deep_put_charge_counters
    # _on_target_spacecraft_or_planet_you_control_parity`` probe drives
    # the genuine Drill Too Deep printing through the new
    # ``PutChargeCountersOnTargetSpacecraftOrPlanetYouControl`` Effect
    # arm + the per-mode target binding detector table extension.
    # Flips Drill Too Deep COVERED → PROBED (admit set 17 → 18, plus
    # the Untimely Malfunction co-admit via the new
    # ``destroy_target_artifact`` serializer leaf — see the slice's
    # admit-set test note).
    REPO_ROOT / "tests" / "test_drill_too_deep_parity.py",
    # **scour-for-scrap-cycle-2 (2026-05-21):** ModalChooseOne envelope
    # — FIRST ``or_both=True`` flip. The
    # ``test_cross_engine_real_eoe_scour_for_scrap_return_target_artifact
    # _card_from_your_graveyard_to_hand_parity`` probe drives the
    # genuine Scour for Scrap printing through the new
    # ``Effect::ReturnTargetArtifactCardFromYourGraveyardToHand`` Rust
    # unit variant + the per-mode detector table extension (the
    # or_both walk peeks the targeted mode-1 leaf) + the matching
    # bridge round-trip arms + the Phase-5 ``(0, 1)`` ``or_both``
    # admit-shape widen. Flips Scour for Scrap COVERED → PROBED
    # (admit set 23 → 24; ~6,434 17lands decks). The narrow
    # ``SearchLibraryForCard(filter_name="artifact")`` ``_leaf`` admit
    # honest-stops Demonic Counsel's auto-flip to a follow-up cycle.
    REPO_ROOT / "tests" / "test_scour_for_scrap_parity.py",
    # **darkness-cycle-3-p1 (2026-05-22):** Darkness combat-damage
    # prevention closure (Cycle 3 of a 3-cycle subsystem lane; ~43
    # 17lands decks — DSK special-guests reprint in the EoE pool). The
    # ``test_cross_engine_real_eoe_darkness_prevent_all_combat_damage_
    # this_turn_parity`` probe drives the genuine parsed Darkness
    # printing ({B} Instant: "Prevent all combat damage that would be
    # dealt this turn.") through the new
    # ``Effect::PreventAllCombatDamageThisTurn`` Rust field-free unit
    # variant + the matching parse + to_pydict + resolve arm (the
    # production MINT SITE flipping the Cycle 1 substrate's
    # ``state.prevent_all_combat_damage_this_turn`` flag, after which
    # the Cycle 2 routing guard at
    # ``state_ops_combat.rs::deal_combat_damage:1656`` zeros out every
    # combat damage event for the rest of the turn). Bridge round-trips
    # via ``cross_engine.py::prevent_all_combat_damage_this_turn``
    # (constructs the field-free Python class) and the
    # ``trajectory.py::_python_spell_effect_to_dict`` ``_leaf`` arm
    # (emits the bare ``{"kind": "prevent_all_combat_damage_this_
    # turn"}`` dict). Darkness AUTO-JOINS the spell-card-bridge admit
    # set via the existing Phase-3 ``(0, 0)``-shape wrath admit arm
    # (no admit-predicate widen needed). Flips Darkness COVERED →
    # PROBED (admit set 24 → 25 — the §2 auto-grow teeth).
    REPO_ROOT / "tests" / "test_darkness_parity.py",
    # **non-state-rs-tractable-slice (2026-05-21):** Effect-uncovered
    # single-gated tier closure — Exorcise (Duskmourn {1}{W} Sorcery).
    # The ``test_cross_engine_real_eoe_exorcise_parity`` probe drives
    # the genuine parsed Exorcise printing through the new
    # ``Effect::ExorciseEffect`` Rust unit variant + the file-local
    # ``read_doubling_power`` effective-power reader + bridge arm +
    # reverse-serializer leaf. The 3-way OR target filter (Artifact OR
    # Enchantment OR Creature-with-effective-power-4+) is the
    # structural sibling of Shattered Wings's destroy-half filter,
    # with two swaps — exile-not-destroy (no indestructible-skip, per
    # CR 702.12) and power-4-not-flying (reads effective power, folds
    # counters + UEOT bonuses, matches Python's
    # ``effective_power`` byte-equal). Flips Exorcise COVERED →
    # PROBED (admit set 20 → 21 — the §2 auto-grow teeth).
    REPO_ROOT / "tests" / "test_exorcise_parity.py",
    # **close-encounter-substrate (2026-05-21):** Close Encounter
    # additional-cost-choice closure (~16,098 17lands decks — highest-
    # deck-count BLOCKED card in the substrate-gated tier as of the
    # close-encounter merge 2406068c). The
    # ``test_cross_engine_real_eoe_close_encounter_damage_parity`` probe
    # drives the genuine parsed Close Encounter EoE printing through
    # the new ``Effect::CloseEncounterEffect`` Rust unit variant + the
    # additional-cost-choice transient + bridge arm. The dedicated
    # ``test_close_encounter_parity.py`` module was authored alongside
    # the substrate but its scanner registration was missed at merge —
    # this entry closes the measurement-attribution gap. Flips Close
    # Encounter COVERED → PROBED (the highest-deck-count BLOCKED card
    # in the prior cycle's substrate-gated tier finally banks the
    # PROBED-tier credit it earned).
    REPO_ROOT / "tests" / "test_close_encounter_parity.py",
    # **multi-target-admit-phase4 (round-pre-launcher, merged
    # 2026-05-20 via ``feature/multi-target-admit-phase4``):** Scout
    # for Survivors via the Phase-4 multi-target admit-gate widen.
    # The dedicated probe module
    # ``test_multi_target_phase4.py`` carries the canonical
    # ``test_cross_engine_real_eoe_scout_for_survivors_return_up_to_n
    # _creatures_with_counters_parity`` function which binds the
    # genuine parsed "Scout for Survivors" printing via
    # ``get_active_source().get_printings().get("Scout for Survivors")``.
    # Lane JJ subsequently added a smoke-file delegator (so the slug-
    # scanner credits via the smoke path), but the canonical probe
    # module remained unregistered — this entry plugs the
    # measurement-attribution gap at the canonical source. No PROBED
    # delta (the smoke delegator already covers it); pure metric
    # truthfulness — same precedent as the cycle-10 reconciliation.
    REPO_ROOT / "tests" / "test_multi_target_phase4.py",
    # **pull-through-the-weft-cycle-1 (2026-05-22):** Pull Through the
    # Weft ({3}{G}{G} Sorcery) via the new ``Effect::ReturnUpToN
    # NonlandPermanentCardsFromGraveyardToHand`` Rust variant + bridge
    # arm + reverse-serializer leaf. The Phase-4 multi-target admit
    # predicate AUTO-JOINS the card the moment its Effect class enters
    # the covered+bridged set (no admit-predicate widen needed — the
    # ``(0, 2)`` / empty-slot_kinds shape was already accepted). The
    # dedicated probe module ``test_pull_through_the_weft_parity.py``
    # carries the canonical
    # ``test_cross_engine_real_eoe_pull_through_the_weft_return_up_to
    # _n_nonland_permanents_parity`` function which binds the genuine
    # parsed "Pull Through the Weft" printing. PROBED 279 → 280.
    REPO_ROOT / "tests" / "test_pull_through_the_weft_parity.py",
    # **Singularity Rupture Cycle 1 (2026-05-24):** Singularity Rupture
    # ({3}{U}{B}{B} Sorcery) — full closure landing. The Rust
    # ``Effect::SingularityRuptureEffect`` unit variant + bridge arm +
    # reverse-serializer leaf land the resolve-time self-scan substrate
    # (wrath phase + per-living-player floor(library/2) mill). The Phase
    # 4 admit predicate AUTO-GROWS under the ``not slot_kinds``
    # permissive disjunct the moment ``SingularityRuptureEffect``
    # enters the covered+bridged set (no admit-predicate widen needed —
    # the ``(0, 8)`` / empty-slot_kinds shape was already accepted).
    # The dedicated probe module
    # ``test_singularity_rupture_parity.py`` carries the canonical
    # ``test_cross_engine_real_eoe_singularity_rupture_wrath_and_mill_
    # parity`` function which binds the genuine parsed "Singularity
    # Rupture" printing. Admit set 39 → 40 (admits ~5,046 17lands
    # decks BLOCKED → PROBED).
    REPO_ROOT / "tests" / "test_singularity_rupture_parity.py",
    # **PPP Pins 1+2+3 (10th Rust slice, ``41c57251``):** the
    # ``test_probe_ppp_downstream.py`` module carries three canonical
    # probes naming the ``_parity`` convention (Drix Fatemaker,
    # Cautious Survivor, Savior of the Small) but was never registered
    # alongside its sibling ``test_probe_<letters>_downstream.py``
    # modules already in PROBE_MODULES (bbb / eee / mmm / rrr / ttt /
    # vvv / ddd / xxx). The cards each probe pins are already PROBED
    # via redundant routes (Drix Fatemaker has a smoke-file probe;
    # Cautious Survivor + Savior of the Small are credited via
    # vvv_downstream), so registration is metric-truthfulness only
    # (no PROBED delta) — closes the per-slice-canonical-probe
    # attribution gap and makes the metric robust against future
    # rearrangement of the redundant routes.
    REPO_ROOT / "tests" / "test_probe_ppp_downstream.py",
    # **x-value-subsystem-cycle-3 (2026-05-22):** Zero Point Ballad
    # `{X}{B}` — FIRST X-cost cross-engine probe. The
    # ``test_cross_engine_real_eoe_zero_point_ballad_x_value_parity``
    # probe drives the genuine parsed Zero Point Ballad EoE printing
    # through the new ``Effect::ZeroPointBalladEffect`` Rust unit
    # variant + the C1+C2.5 X-value substrate (StackItem.x_value mint,
    # current_resolve_x_value bracket) + bridge arm + reverse-
    # serializer leaf. Under the no-agent cross-engine harness X=0
    # (per C2.5's no-agent fallback mint); the X-dependent destroy +
    # lose-X-life + X>=6 reanimation surface stays dormant, but the
    # printing parses + admits + serializer round-trips + resolves
    # byte-equal. Flips Zero Point Ballad COVERED → PROBED (admit set
    # 24 → 25; ~6,041 17lands decks).
    REPO_ROOT / "tests" / "test_zero_point_ballad_parity.py",
    # **control-change-ueot-cycle-4-p1 (2026-05-22):** Cycle 4 of the
    # control-change-UEOT subsystem — Mutinous Massacre closure
    # (~4,671 17lands decks). The dedicated probe module
    # ``test_mutinous_massacre_parity.py`` carries the canonical
    # ``test_cross_engine_real_eoe_mutinous_massacre_control_change
    # _parity`` function which drives the genuine parsed Mutinous
    # Massacre printing through both engines. The C1-C3 substrate
    # (controller_override field + helper + cleanup drain + bridge
    # round-trip — landed across cycles 1-3 of the same triad lane)
    # + this lane's ``Effect::MutinousMassacreEffect`` field-free unit
    # variant + resolve arm (the FIRST Rust call site that mints a
    # non-None override) + bridge arms + reverse-serializer leaf
    # flips Mutinous Massacre COVERED → PROBED.
    REPO_ROOT / "tests" / "test_mutinous_massacre_parity.py",
    # **control-change-ueot-cycle-5-p1 (2026-05-22):** Cycle 5 of the
    # control-change-UEOT subsystem — Systems Override closure
    # (~4,775 17lands decks). The dedicated probe module
    # ``test_systems_override_parity.py`` carries the canonical
    # ``test_cross_engine_real_eoe_systems_override_control_change_
    # spacecraft_rider_parity`` function which drives the genuine
    # parsed Systems Override printing through both engines against
    # an opponent-controlled Spacecraft. Cycle 5 lands
    # ``Effect::SystemsOverrideEffect`` + resolve arm (control-grant
    # + untap + haste + Spacecraft-conditional +10 charge counters
    # + delayed-trigger schedule) + the new
    # ``Effect::RemoveChargeCountersFromSourceDelayed { amount }``
    # delayed-trigger effect + bridge arms + reverse-serializer
    # leaves. Composes the existing G7 Class-C end-step drain
    # machinery (second non-WarpExileSelf consumer). Systems
    # Override COVERED → PROBED.
    REPO_ROOT / "tests" / "test_systems_override_parity.py",
    # **devastating-onslaught-cycle-1 (2026-05-22):** Devastating
    # Onslaught `{X}{X}{R}` — SECOND X-cost cross-engine probe.
    # The
    # ``test_cross_engine_real_eoe_devastating_onslaught_create_x_tokens_of_target_permanent_with_haste_end_step_sac_parity``
    # probe drives the genuine parsed Devastating Onslaught EoE
    # printing through the new
    # ``Effect::CreateXTokensOfTargetPermanentWithHasteEndStepSac``
    # Rust unit variant + the C1+C2.5 X-value substrate
    # (StackItem.x_value mint, current_resolve_x_value bracket) +
    # ``Effect::SacrificeSourceDelayed`` per-token end-step sac
    # delayed-trigger sibling + bridge arms + reverse-serializer
    # leaves. Under the no-agent cross-engine harness X=0 (per
    # C2.5's no-agent fallback mint); the X-dependent token-mint
    # surface stays dormant under the cross-engine probe but the
    # printing parses + admits + serializer round-trips + resolves
    # byte-equal. The X>=2 mint + haste-grant + end-step-sac surface
    # is pinned via dedicated Rust unit pins (synthetic-state path).
    # Flips Devastating Onslaught COVERED → PROBED (admit set
    # 28 → 29).
    REPO_ROOT / "tests" / "test_devastating_onslaught_parity.py",
    # **vengeful-possession-cycle-1-p1 (2026-05-22):** Closes
    # Vengeful Possession (~0 17lands decks — uncommon Effect-uncovered
    # closure). The dedicated probe module
    # ``test_vengeful_possession_parity.py`` carries the canonical
    # ``test_cross_engine_real_eoe_vengeful_possession_control_change_
    # parity`` function which drives the genuine parsed Vengeful
    # Possession printing through the Rust resolve arm. The control-
    # change-UEOT C1-C5 substrate (controller_override field + helper
    # + cleanup drain + bridge round-trip + Mutinous Massacre / Systems
    # Override resolve precedents) + this lane's
    # ``Effect::ThreatenTargetCreatureUEOT`` field-free unit variant +
    # resolve arm (control-grant + untap + haste UEOT, creature-only
    # target filter — distinct from Systems Override's artifact-OR-
    # creature filter) + bridge arms + reverse-serializer leaves
    # (including the previously-missing ``_leaf`` arms for the
    # surrounding composite Effects ``IfYouDo`` / ``MayDo`` /
    # ``DiscardSelf`` / ``DrawCards`` — all four were Rust-covered and
    # ``cross_engine.py``-bridged at this cycle's HEAD; the trajectory.py
    # ``_leaf`` table was the only missing piece) flips Vengeful
    # Possession COVERED → PROBED.
    REPO_ROOT / "tests" / "test_vengeful_possession_parity.py",
    # **post-flip-reclassification-scout-2026-05-24 (this sweep):**
    # 12 dedicated probe modules each carry a canonical
    # ``test_cross_engine_real_eoe_<...>_parity`` function with a live
    # EoE ``get_active_source().get_printings().get("<Card>")`` binding,
    # but were never registered in ``PROBE_MODULES`` when they landed,
    # leaving each carrier silently classified COVERED rather than the
    # stronger PROBED tier. Pure measurement-attribution gap — identical
    # shape to the 2026-05-21 ``feature/loader-admits-attribution-sweep``
    # precedent (5 missing disjuncts in the loader_admits helper → 9
    # BLOCKED→PROBED flips). The probes are LIVE and PASSING at this
    # HEAD; registration alone flips each card COVERED → PROBED in the
    # metric (no engine changes, no new tests). The two NEW (2026-05-24)
    # carriers (Coordinated Clobbering Cycle 2b + Warping Wail Cycle 4)
    # were surfaced directly by today's flips; the other 10 are
    # accumulated backlog from the 2026-05-22 / 2026-05-23 Effect-
    # uncovered closure wave that shipped its probe modules without
    # adding the registration line:
    #
    #   * ``test_arabella_abandoned_doll_parity.py`` — Arabella, Abandoned Doll
    #   * ``test_boilerbilges_ripper_parity.py`` — Boilerbilges Ripper
    #   * ``test_burgeoning_parity.py`` — Burgeoning
    #   * ``test_comet_crawler_parity.py`` — Comet Crawler
    #   * ``test_coordinated_clobbering_parity.py`` — Coordinated Clobbering (today)
    #   * ``test_fanatic_of_the_harrowing_parity.py`` — Fanatic of the Harrowing
    #   * ``test_osseous_sticktwister_parity.py`` — Osseous Sticktwister
    #   * ``test_terminal_velocity_parity.py`` — Terminal Velocity
    #   * ``test_terrapact_intimidator_parity.py`` — Terrapact Intimidator
    #   * ``test_endstone_parity.py`` — The Endstone
    #   * ``test_vaultguard_trooper_parity.py`` — Vaultguard Trooper
    #   * ``test_warping_wail_cycle_4_cross_engine.py`` — Warping Wail (today)
    #
    # Net delta: PROBED 287 → 299 (+12); covered_by_construction
    # 123 → 111 (-12); BLOCKED-subsystem-gated unchanged at 65; pool
    # total 475 unchanged.
    REPO_ROOT / "tests" / "test_arabella_abandoned_doll_parity.py",
    REPO_ROOT / "tests" / "test_boilerbilges_ripper_parity.py",
    REPO_ROOT / "tests" / "test_burgeoning_parity.py",
    REPO_ROOT / "tests" / "test_comet_crawler_parity.py",
    REPO_ROOT / "tests" / "test_coordinated_clobbering_parity.py",
    REPO_ROOT / "tests" / "test_fanatic_of_the_harrowing_parity.py",
    REPO_ROOT / "tests" / "test_osseous_sticktwister_parity.py",
    REPO_ROOT / "tests" / "test_terminal_velocity_parity.py",
    REPO_ROOT / "tests" / "test_terrapact_intimidator_parity.py",
    REPO_ROOT / "tests" / "test_endstone_parity.py",
    REPO_ROOT / "tests" / "test_vaultguard_trooper_parity.py",
    REPO_ROOT / "tests" / "test_warping_wail_cycle_4_cross_engine.py",
    # **post-ac-flip-attribution-sweep-2026-05-24:** the
    # Archenemy's Charm BLOCKED → PROBED flip (merge ``7088c9bd``)
    # landed ``tests/test_archenemys_charm_parity.py`` with three
    # canonical ``test_cross_engine_real_eoe_archenemys_charm_mode_
    # {0,1,2}_..._parity`` functions, each binding the live EoE
    # printing via the in-body ``get_active_source().get_printings()
    # .get("Archenemy's Charm")`` idiom — i.e. the
    # ``_probe_module_probed_cards`` predicate matches — but the
    # AC merge did not also touch this registry. Pure measurement-
    # attribution gap (identical shape to the 2026-05-24
    # ``feature/post-flip-reclassification-scout`` 12-card sweep
    # immediately prior). Registration alone flips Archenemy's Charm
    # COVERED → PROBED in the metric; no engine changes.
    REPO_ROOT / "tests" / "test_archenemys_charm_parity.py",
    # **probe-module-predicate-widen-2026-05-24:** four per-card
    # parity modules that hoist the printings dict to module scope —
    # ``_PRINTINGS = get_active_source().get_printings()`` at the top
    # of the file — and call ``_PRINTINGS.get("<Card>")`` inside the
    # canonical ``test_cross_engine_real_eoe_<...>_parity`` function
    # body. The body-scoped scan above never saw the ``get_printings()``
    # call (it lives outside the bounded function body), so these
    # probes were silently undercounted. The companion widen in
    # ``_probe_module_probed_cards`` now AST-walks the module to
    # detect the module-level binding and credit the in-body
    # ``_PRINTINGS.get("<Card>")`` references — the integrity guard
    # in ``test_probe_module_synthetic_nonprobe_is_not_counted`` is
    # preserved because the widen only recognizes the BARE
    # printings-dict shape (``= get_active_source().get_printings()``
    # / ``= get_printings()``); a module-level
    # ``_X = get_printings().get("Card")`` is NOT a dict binding,
    # so the case-(4) negative-control still passes. Pure
    # measurement-attribution gap (identical shape to the immediately-
    # prior 12-card + Archenemy's Charm sweeps): the probes EXIST and
    # PASS at this HEAD, only the predicate + registry needed to
    # learn the new idiom.
    REPO_ROOT / "tests" / "test_blade_of_the_swarm_parity.py",
    REPO_ROOT / "tests" / "test_genemorph_imago_parity.py",
    REPO_ROOT / "tests" / "test_possibility_technician_parity.py",
    REPO_ROOT / "tests" / "test_territorial_bruntar_parity.py",
    # **codecracker-hound-cycle-3-probe-p1 (2026-05-24):** the per-card
    # real-EoE cross-engine byte-equality probe for Codecracker Hound.
    # Cycle 1 (commit ``bd37cca0``) folded the bespoke
    # ``LookAtTopTwoSplitHandGraveyard`` engine class into
    # ``LookTopNPutOneInHandRestToGraveyard(n=2, reveal_chosen=False)``.
    # Cycle 2 (commit ``278992d7``) widened the safe-trigger admit gate
    # (warp-arm admit set 6 → 7) so CH is now ADMITTED at
    # ``_printing_is_bridge_pure_warp_creature``. Cycle 3 (this slice)
    # ships the dedicated per-card probe — the load-bearing PROBED-tier
    # flip evidence: ``test_cross_engine_real_eoe_codecracker_hound_etb_
    # parity`` binds the live EoE printing via the module-scope
    # ``_PRINTINGS = get_active_source().get_printings()`` idiom (the
    # ``_probe_module_probed_cards_via_module_scope_binding`` widen
    # accepts it). Registration alone flips Codecracker Hound
    # ``covered_by_construction`` → PROBED in the pool-parity metric.
    REPO_ROOT / "tests" / "test_codecracker_hound_parity.py",
    # **anticausal-vestige-cycle-3-probe-p1 (2026-05-24):** the per-
    # card real-EoE cross-engine byte-equality probe for Anticausal
    # Vestige ({6} colorless Creature - Eldrazi 7/5 with warp {4} and
    # a LEAVES_BATTLEFIELD draw + may-put-permanent-from-hand-tapped
    # trigger). Cycle 1 (commit ``e148450a``) wired the new Rust
    # ``Effect::AnticausalVestigeLeavesEffect`` unit variant + parse +
    # to_pydict + resolve + bridge arms (AV STAYED DECLINED).
    # Cycle 2 (commit ``c32f07f9``) widened ``_python_ta_to_safe_dict``
    # to admit ``LEAVES_BATTLEFIELD`` as the FIFTH safe event +
    # registered the ``("leaves_battlefield", "source_is_self",
    # "anticausal_vestige_leaves_effect")`` _SAFE_TRIGGERS triple +
    # the matching _SAFE_EFFECT_KEYS whitelist; warp-arm admit set
    # 7 -> 8 (AV inserted alphabetically as the FIRST entry).
    # Cycle 3 (this slice) ships the dedicated per-card probe — the
    # load-bearing PROBED-tier flip evidence:
    # ``test_cross_engine_real_eoe_anticausal_vestige_ltb_parity``
    # drives the genuine warp-cast -> end-step exile sweep ->
    # LEAVES_BATTLEFIELD dispatch -> LTB resolve path through both
    # engines byte-equal under the deterministic-first contract
    # (seated ``_PickFirstSacrificeAgent`` on Python p0 to mirror
    # Rust's first-legal hand-iteration pick at
    # ``rust/src/state_ops_resolve.rs:15219-15392``; resolves the C2
    # deferral that "deterministic-first is the deferred default" —
    # held byte-equal here, no PendingDecision pivot needed this
    # cycle). The probe binds the live EoE printing via the module-
    # scope ``_PRINTINGS = get_active_source().get_printings()``
    # idiom (the ``_probe_module_probed_cards_via_module_scope_binding``
    # widen accepts it). Registration alone flips Anticausal Vestige
    # ``covered_by_construction`` -> PROBED in the pool-parity metric.
    # The sibling ``tests/test_probe_warp_admitted.py`` _WARP_CARDS
    # parametrize also gains an AV entry (warp-cast + normal-cast
    # lifecycle real-EoE probes) — uses the same seated-agent shim
    # in ``_build_real_deck_context`` as a card_name == "Anticausal
    # Vestige" special-case.
    REPO_ROOT / "tests" / "test_anticausal_vestige_parity.py",
    # **memorial-team-leader-cycle-2-flip (2026-05-24):** Memorial
    # Team Leader ({3}{R} 4/3 with warp {1}{R}; "During your turn,
    # other creatures you control get +1/+0.") closes the Phase-4
    # static-anthem-PT-conditional + warp composition. The C1
    # substrate (commit ``1d6f5cd3``) wired the Rust ``StaticAnthem``
    # P/T + ``during_your_turn`` dispatcher + the 6-tuple bridge
    # shape; C2 (this lane) ships the
    # ``_printing_is_bridge_static_anthem_pt_conditional_warp_creature``
    # admit predicate + the matching
    # ``_printing_to_card_def`` arm + the matching ``loader_admits``
    # disjunct + the per-card real-EoE parity probe in
    # ``tests/test_memorial_team_leader_parity.py``. The probe's
    # canonical ``test_cross_engine_real_eoe_memorial_team_leader_
    # anthem_byte_equal_parity`` function drives the genuine parsed
    # printing through both engines byte-equal across the
    # DuringYourTurn-gated anthem fold (active-player flip, cross-
    # controller scope exclusion, source-self exclusion). ~6,229
    # 17lands decks BLOCKED → PROBED; admit set delta +1 for the
    # creature-side admit predicates (single-card single-cycle FLIP,
    # no silent auto-grows).
    REPO_ROOT / "tests" / "test_memorial_team_leader_parity.py",
    # **weftwalking-cycle-3-probe-p1 (2026-05-24):** Weftwalking
    # ({4}{U}{U} Enchantment with ETB+IsSelf+ConditionalIfCastFromHand(
    # Sequence(ShuffleZonesIntoLibrary(hand+graveyard), DrawCards(7))))
    # closes the multi-cycle Enchantment-side admit pipeline. The C1
    # substrate (commits ``61f04bef`` + ``d18bb3a4``) wired two new
    # Rust Effect variants -- ``Effect::ConditionalIfCastFromHand``
    # (recursive Box<Effect>) + ``Effect::ShuffleZonesIntoLibrary``
    # (Vec<String>) -- with parse/to_pydict/resolve + cross-engine
    # bridge arms + reverse-serializer leaves (incl. nested-Sequence-
    # as-leaf). C2 (commit ``0017d9c1``) widened
    # ``_python_ta_to_safe_dict`` to admit the 10th ENTERS+IsSelf
    # safe-trigger leaf (conditional_if_cast_from_hand with the EXACT
    # canonical Weftwalking inner gate -- surgical §2 teeth) + landed
    # the ``_SAFE_TRIGGERS`` triple + the ``_SAFE_EFFECT_KEYS``
    # whitelist + a NEW ``_printing_is_bridge_simple_enchantment``
    # admit arm (the Enchantment-side sibling of
    # ``_printing_is_bridge_simple_creature`` -- a fresh arm rather
    # than extending the Creature arm because the latter cascades
    # through Creature-specific downstream assumptions). C3 (this
    # lane) ships the per-card real-EoE parity probe in
    # ``tests/test_weftwalking_parity.py``. The probe's canonical
    # ``test_cross_engine_real_eoe_weftwalking_etb_parity`` function
    # drives the genuine parsed printing through both engines (direct
    # injection bypass -- Rust has no cast_enchantment primitive, see
    # state_ops_actions.rs cast dispatch cascade), exercising the
    # documented ConditionalIfCastFromHand always-run-inner resolve
    # degradation (combinators.py:1518-1536 -- the cast_via_hand flag
    # is ephemeral, cleared before ETB triggers fire on both engines)
    # + the Sequence(Shuffle, Draw(7)) body under a shared external
    # Python RNG (round-54 set_external_rng cross-engine shuffle-
    # parity pattern). Full ``compare_fields == []`` over the WHOLE
    # field view post-resolve. NORMAL-CAST LIFECYCLE ONLY -- the
    # warp-cast lifecycle is structurally inapplicable (Weftwalking
    # has ``warp_cost_str == ""``, verify-first pinned by the C1
    # substrate module). ~3,680 17lands decks BLOCKED -> PROBED;
    # admit set delta +1 for the new Enchantment-side admit predicate
    # (single-card single-cycle FLIP, no silent auto-grows --
    # Weftwalking is the SOLE ConditionalIfCastFromHand carrier
    # system-wide).
    REPO_ROOT / "tests" / "test_weftwalking_parity.py",
    # **probe-module-rename-sweep-p1 (2026-05-24):** the eight per-card
    # real-EoE cross-engine byte-equal probe modules whose cross-engine
    # function name previously used a non-canonical ``_round_trip`` /
    # ``_byte_equal`` suffix (or missed the ``_eoe_`` infix, in
    # Friendly Teddy's case) — the predicate's
    # ``_PROBE_FN_HEADER_RE`` requires a ``..._parity`` suffix, so each
    # module's genuine probe was uncredited even though it bound the
    # live printing via ``get_active_source().get_printings().get(<n>)``
    # in the function body. This lane renamed each cross-engine probe
    # to the canonical ``..._parity`` suffix (append-only edit, lower
    # diff churn than dropping the descriptive ``_round_trip`` /
    # ``_byte_equal`` half) and now registers the eight modules so the
    # widened-coverage credit lands. Each flip is COVERED-by-
    # construction → PROBED in the pool-parity classifier (PROBED 306
    # → 314, covered_by_construction 107 → 99; BLOCKED-SG unchanged).
    # Same precedent shape as the prior
    # ``feature/post-flip-reclassification-scout`` 12-card sweep that
    # registered the existing ``..._parity``-named probes; this lane
    # is the rename-then-register companion for the eight
    # non-canonically-named cross-engine probes.
    REPO_ROOT / "tests" / "test_attack_in_the_box_parity.py",
    REPO_ROOT / "tests" / "test_enduring_curiosity_parity.py",
    REPO_ROOT / "tests" / "test_friendly_teddy_parity.py",
    REPO_ROOT / "tests" / "test_hemosymbic_mite_parity.py",
    REPO_ROOT / "tests" / "test_ouroboroid_parity.py",
    REPO_ROOT / "tests" / "test_splitskin_doll_parity.py",
    REPO_ROOT / "tests" / "test_swarm_culler_parity.py",
    REPO_ROOT / "tests" / "test_terrasymbiosis_parity.py",
    # **cathedral-of-war-probe-rename-p1 (2026-05-24):** Cathedral of
    # War was the residual 4th-shape EoE bench-probe gap surfaced by
    # ``54a17836`` and explicitly deferred from the 8-probe rename
    # sweep (``726e9116``) because its function name carried a
    # ``_through_bench`` semantic infix beyond the three naming
    # variants that sweep closed (``_round_trip`` / ``_byte_equal`` /
    # missing ``_eoe_``). This lane completes the same per-probe
    # rename pattern: ``test_cathedral_genuine_real_eoe_byte_equal_
    # through_bench`` -> ``test_cross_engine_real_eoe_cathedral_of_
    # war_through_bench_parity`` (the ``..._through_bench_parity``
    # suffix keeps the bench-probe semantic visible while satisfying
    # the ``_PROBE_FN_HEADER_RE`` predicate's strict ``..._parity``
    # tail), then registers the module here. The in-file shockland
    # bench-probe sibling
    # (``test_r60_genuine_real_eoe_shockland_byte_equal_through_bench``
    # in ``tests/test_parity_smoke.py``) was renamed in parallel for
    # consistency, but adds 0 PROBED flips -- the 5 shocklands
    # (Breeding Pool / Watery Grave / Stomping Ground / Godless Shrine
    # / Sacred Foundry) are already PROBED via the 5 ``_parity``
    # delegators added by the 2026-05-21 loader_admits-attribution-
    # sweep (``1c2e62f6``). PROBED 314 -> 315 (+1, Cathedral of War);
    # covered_by_construction 100 -> 99 (-1); BLOCKED-SG unchanged at
    # 61. Closes the 4th-shape gap entirely (no further EoE
    # ``_through_bench`` bench-probe shapes remain).
    REPO_ROOT / "tests" / "test_cathedral_of_war_parity.py",
    # NOT registered (deliberate, documented):
    #   * ``test_deafening_silence_parity.py`` — the
    #     ``test_cross_engine_real_eoe_deafening_silence_noncreature_
    #     block_parity`` function drives a SYNTHETIC ``CardDef(name=
    #     "Deafening Silence", restricts_noncreature_spells_to_one_
    #     per_turn=True, ...)`` carrier through the bridge, not the
    #     live parsed printing via ``get_printings()``. The
    #     ``_PRINTINGS.get(...)`` widen above does not match because
    #     there is no module-level ``_PRINTINGS`` binding (the three
    #     ``get_active_source().get_printings().get("Deafening Silence")``
    #     bindings in the file live in non-``*_parity`` setup tests —
    #     they are outside any credited body). The prior post-AC-flip
    #     sweep audit (``2a8919d2``) misclassified this module into
    #     the ``_PRINTINGS`` bucket — it is actually a CardDef-
    #     driven synthetic-carrier probe, a third shape this widen
    #     deliberately does not address. Flipping Deafening Silence
    #     COVERED → PROBED honestly would require either a separate
    #     widen recognizing the synthetic-CardDef-by-name pattern
    #     (riskier — opens credit to any module that mentions a real
    #     pool card name inside a CardDef constructor) or a per-
    #     probe rewrite to bind the real printing via
    #     ``get_printings()`` first; deferred to a separate lane.
    #   * ``test_atomic_microsizer_parity.py`` — explicit
    #     ``@pytest.mark.skip`` + ``raise NotImplementedError`` multi-
    #     cycle scaffold per ``docs/SEARCH_LIMITATIONS.md``; correctly
    #     stays BLOCKED-subsystem-gated.
    # **covered-by-construction-probe-writing-p1 (2026-05-24):** Four
    # per-card real-EoE cross-engine byte-equal probes for cards
    # previously honest-stopped on "bit-identical to PROBED sibling"
    # grounds (CCCC / HHHH / IIII / JJJJ drop lists). The
    # 2026-05-24 ``post-flip-reclassification-scout`` 12-card sweep +
    # the IIII Optimistic Scavenger / Command Bridge precedent
    # together established that per-slug attribution credits a PROBED
    # slot per-printing — the classifier credits per-slug, not per-
    # effect-class. Each module carries a canonical
    # ``test_cross_engine_real_eoe_<slug>_..._parity`` function that
    # binds the live EoE printing via the module-scope
    # ``_PRINTINGS = get_active_source().get_printings()`` idiom (the
    # ``_probe_module_probed_cards_via_module_scope_binding`` widen
    # accepts it) + drives the GENUINE parsed printing through both
    # engines byte-equal end-to-end via the substrate the sibling
    # PROBED carrier already pinned:
    #
    #   * ``test_trapped_in_the_screen_parity.py`` — Trapped in the
    #     Screen ({2}{W} Enchantment, EoE special guest); mirrors the
    #     PROBED Banishing Light I80 probe (ENTERS+IsSelf →
    #     ExileOpponentsNonlandPermanentUntilLeaves(max_mv=0)).
    #   * ``test_innocuous_rat_parity.py`` — Innocuous Rat ({1}{B}
    #     Creature); mirrors the PROBED Bashful Beastie probe
    #     (DIES+IsSelf → ManifestDread(count=1)).
    #   * ``test_unwanted_remake_parity.py`` — Unwanted Remake ({W}
    #     Instant); mirrors the PROBED Murder probe
    #     (DestroyTargetCreature bare).
    #   * ``test_fear_of_failed_tests_parity.py`` — Fear of Failed
    #     Tests ({4}{U} Enchantment Creature); mirrors the PROBED
    #     Starwinder probe (DEALS_COMBAT_DAMAGE →
    #     DrawCardsEqualToResolvingCombatDamage()) with the distinct
    #     IsSelf+target-IsPlayer predicate (vs Starwinder's broader
    #     "any creature you control" predicate).
    #
    # Pure measurement-attribution: no engine changes, no Rust
    # changes, no substrate widens. Per-slug credit only.
    REPO_ROOT / "tests" / "test_trapped_in_the_screen_parity.py",
    REPO_ROOT / "tests" / "test_innocuous_rat_parity.py",
    REPO_ROOT / "tests" / "test_unwanted_remake_parity.py",
    REPO_ROOT / "tests" / "test_fear_of_failed_tests_parity.py",
    # **covered-by-construction-probe-writing-p2 (2026-05-24):** Four
    # additional per-card real-EoE cross-engine byte-equal probes for
    # cards previously honest-stopped on "bit-identical to PROBED
    # sibling" / "rename-needed" grounds.  Same lane discipline as p1
    # (the immediately-prior 4-card batch): per-slug attribution
    # credits a PROBED slot per-printing, no engine changes, no
    # substrate widens, no Rust changes.  Each module carries a
    # canonical ``test_cross_engine_real_eoe_<slug>_..._parity``
    # function that binds the live EoE printing via the module-scope
    # ``_PRINTINGS = get_active_source().get_printings()`` idiom (the
    # ``_probe_module_probed_cards_via_module_scope_binding`` widen
    # accepts it) + drives the GENUINE parsed printing through the
    # parse + bridge round-trip + Python-side resolve idiom DDD slice
    # 17 / YYY / ZZZ / AAAA / CCCC / DDDD / EEEE / FFFF / GGGG / HHHH
    # / IIII / JJJJ / batch-1 established:
    #
    #   * ``test_sunstar_lightsmith_parity.py`` — Sunstar Lightsmith
    #     ({3}{W} Creature — Human Artificer, ~11,954 17lands decks);
    #     IS_CAST+And(Controlled, StateBound(SpellsCastThisTurn(n=2)))
    #     → Sequence(PutPlusOneCounterOnSelf(1), DrawCards(1)).
    #     Templates on FFFF Illvoi Operative (IS_CAST event +
    #     PutPlusOneCounterOnSelf) + BBBB Withering Torment (Sequence
    #     composer wrapper); the EEEE-idiom sidesteps the slice-12
    #     IS_CAST stack-resolution divergence per FFFF's
    #     drop-recovery precedent.  Pins parser SoT + Sequence-arm
    #     recursive bridge round-trip (both inner arms exercised) +
    #     Python-side resolve mutation (source +1/+1 counter, p0 hand
    #     +1, library -1).
    #   * ``test_bottomless_pool_locker_room_parity.py`` — Bottomless
    #     Pool // Locker Room (Enchantment — Room, EoE pool);
    #     DEALS_COMBAT_DAMAGE+And(Subject(source, IsCreature),
    #     Controlled, Subject(target, IsPlayer)) → DrawCards(1) on the
    #     Locker Room back-half.  Templates on PROBED Illvoi
    #     Infiltrator (slice-13 deals_combat_damage_unlock probe).
    #     Front-half (Bottomless Pool ENTERS+IsSelf →
    #     ReturnTargetCreatureToOwnersHand) is deliberately scoped out
    #     per the JJJJ Moldering Gym / Weight Room half-coverage
    #     precedent — the front-half's optional/create_drone riders
    #     don't round-trip via the bridge's bare Bounce arm.
    #   * ``test_ticket_booth_tunnel_of_hate_parity.py`` — Ticket
    #     Booth // Tunnel of Hate (Enchantment — Room, EoE pool);
    #     ENTERS+IsSelf → ManifestDread(1) on the Ticket Booth front-
    #     half.  Templates on PROBED Innocuous Rat / Bashful Beastie
    #     (DIES+ManifestDread(1) — same effect class, different event)
    #     + JJJJ Funeral Room // Awakening Hall (Room ENTERS carrier
    #     pattern).  Empty-library silent no-op resolve smoke per the
    #     JJJJ Funeral Room empty-graveyard precedent.  Back-half
    #     (Tunnel of Hate YOU_ATTACK → PumpTargetCreatureUntilEOT with
    #     granted_keywords={'double strike'}) deferred per the IIII /
    #     HHHH "pump carriers with granted_keywords riders" drop.
    #   * ``test_wickerfolk_thresher_parity.py`` — Wickerfolk Thresher
    #     (Artifact Creature — Scarecrow, EoE Duskmourn special-guest
    #     reprint); ATTACKS+And(IsSelf, StateBound(Delirium())) →
    #     PeekTopMayBattlefieldIfLandElseHand().  The module ALREADY
    #     carries a load-bearing full-cross-engine probe under the
    #     ``test_cross_engine_real_dsk_wickerfolk_thresher_..._parity``
    #     name (the original was authored when DSK was the only set-
    #     provenance context).  Per the
    #     ``feature/probe-module-rename-sweep`` + Cathedral of War
    #     rename precedent (both 2026-05-24, attribution-only flips
    #     via canonical-name addition), this lane appends a thin
    #     canonical-named EoE delegator (``test_cross_engine_real_eoe_
    #     wickerfolk_thresher_attack_nonland_top_parity``) that
    #     references ``_PRINTINGS.get("Wickerfolk Thresher")`` for
    #     slug-scanner credit then delegates to the load-bearing
    #     sibling.  Pure measurement-attribution (no engine changes,
    #     no behavior changes; the original ``_dsk_``-named probe is
    #     preserved intact as the load-bearing sibling).
    REPO_ROOT / "tests" / "test_sunstar_lightsmith_parity.py",
    REPO_ROOT / "tests" / "test_bottomless_pool_locker_room_parity.py",
    REPO_ROOT / "tests" / "test_ticket_booth_tunnel_of_hate_parity.py",
    REPO_ROOT / "tests" / "test_wickerfolk_thresher_parity.py",
    # **covered-by-construction-probe-writing-p3 (2026-05-24):** Four
    # additional per-card real-EoE cross-engine byte-equal probes for
    # cards previously honest-stopped (the ``test_probe_cast_spell_aa
    # .py`` LANE RECON dropped Cosmogrand Zenith + Station Monitor on
    # StateBound grounds; the JJJJ + batch-2 half-coverage precedents
    # left the Room front-halves Derelict Attic + Underwater Tunnel
    # uncovered).  Same lane discipline as p1 + p2: per-slug
    # attribution credits a PROBED slot per-printing, no engine
    # changes, no substrate widens, no Rust changes.  Each module
    # carries a canonical ``test_cross_engine_real_eoe_<slug>_...
    # _parity`` function that binds the live EoE printing via the
    # module-scope ``_PRINTINGS = get_active_source().get_printings()``
    # idiom (the ``_probe_module_probed_cards_via_module_scope_binding``
    # widen accepts it) + drives the GENUINE parsed printing through
    # the parse + bridge round-trip + Python-side resolve idiom DDD
    # slice 17 / YYY / ZZZ / AAAA / CCCC / DDDD / EEEE / FFFF / GGGG /
    # HHHH / IIII / JJJJ / batch-1 / batch-2 established:
    #
    #   * ``test_cosmogrand_zenith_parity.py`` — Cosmogrand Zenith
    #     ({2}{W} Creature — Human Soldier, ~3,046 17lands decks);
    #     IS_CAST + And(Controlled, StateBound(SpellsCastThisTurn(2)))
    #     → ModalChooseOne(CreateToken(Human Soldier, 2),
    #     PutPlusOneCounterOnEachCreatureYouControl(1)).  Templates on
    #     batch-2 Sunstar Lightsmith (IS_CAST EEEE-idiom) + Archenemy's
    #     Charm (ModalChooseOne composer); mode-1 (each-creature-pump)
    #     pinned for byte-equality, mode-0 (CreateToken) scoped out
    #     per the Bottomless Pool / Locker Room half-coverage
    #     precedent.  The EEEE-idiom sidesteps the StateBound +
    #     slot='controller' bridge gap (the ``test_probe_cast_spell
    #     _aa.py`` LANE RECON honest-stop) per Sunstar Lightsmith
    #     batch-2 precedent.
    #   * ``test_station_monitor_parity.py`` — Station Monitor ({W}{U}
    #     Creature — Lizard Artificer, ~13,216 17lands decks); IS_CAST
    #     + And(Controlled, StateBound(SpellsCastThisTurn(2))) →
    #     CreateToken(Drone, count=1).  Templates on Pinnacle Emissary
    #     (PROBED via ``test_probe_cast_spell_aa.py``, CreateToken +
    #     Drone but non-StateBound predicate) + batch-2 Sunstar
    #     Lightsmith (IS_CAST EEEE-idiom).  Reuses Pinnacle Emissary's
    #     ``register_token_printing`` + ``TOKEN_PRINTINGS["Drone"]``
    #     canonical-printing pattern; the EEEE-idiom sidesteps the
    #     StateBound + slot='controller' bridge gap.
    #   * ``test_derelict_attic_widows_walk_parity.py`` — Derelict
    #     Attic // Widow's Walk (Enchantment — Room, EoE pool);
    #     ENTERS + IsSelf → Sequence(DrawCards(2), LoseLife(2)) on the
    #     Derelict Attic front-half.  Templates on Withering Torment
    #     (BBBB Sequence composer + LoseLife leaf) + batch-2
    #     Bottomless Pool / Locker Room (Room-subsystem half-coverage)
    #     + Sunstar Lightsmith batch-2 (Sequence composer with two
    #     bridged leaves).  Back-half (Widow's Walk YOU_ATTACK
    #     StateBound LoneAttackerForYou + PumpTargetCreatureUntilEOT
    #     granted_keywords=deathtouch) deferred per the IIII / HHHH
    #     "pump carriers with granted_keywords riders" drop list.
    #   * ``test_underwater_tunnel_slimy_aquarium_parity.py`` —
    #     Underwater Tunnel // Slimy Aquarium (Enchantment — Room,
    #     EoE pool); ENTERS + IsSelf → Surveil(amount=2) on the
    #     Underwater Tunnel front-half.  Templates on JJJJ Funeral
    #     Room // Awakening Hall (Room ENTERS empty-library no-op
    #     precedent) + batch-E Lost in Space (Surveil leaf inside a
    #     Sequence wrapper, different carrier shape).  Empty-library
    #     silent no-op resolve sidesteps the ``choose_surveil`` agent-
    #     decision surface entirely.  Back-half (Slimy Aquarium ENTERS
    #     ManifestDreadThenPutPlusOneCountersOnIt) deferred per the
    #     JJJJ Funeral Room / Ticket Booth // Tunnel of Hate batch-2
    #     ManifestDread-family deferral.
    #
    # Pure measurement-attribution + per-slug credit: no engine
    # changes, no Rust changes, no substrate widens.  Net delta: +4
    # PROBED / -4 covered_by_construction: PROBED 325 → 329; covered_
    # by_construction 90 → 86; BLOCKED unchanged at 60; pool total 475
    # unchanged.
    REPO_ROOT / "tests" / "test_cosmogrand_zenith_parity.py",
    REPO_ROOT / "tests" / "test_station_monitor_parity.py",
    REPO_ROOT / "tests" / "test_derelict_attic_widows_walk_parity.py",
    REPO_ROOT / "tests" / "test_underwater_tunnel_slimy_aquarium_parity.py",
    # **covered-by-construction-probe-writing-p4 (2026-05-25):** Five
    # additional per-card real-EoE cross-engine byte-equal probes
    # opening a new shape family: **activated-ability + AddManaToPool /
    # GainLife on real-EoE Land carriers.**  The prior batch-1/2/3
    # lane focused on triggered-ability events (ENTERS / IS_CAST /
    # YOU_ATTACK / DEALS_COMBAT_DAMAGE / DIES) + spell-effect carriers;
    # batch-4 opens the AA-on-Land carrier lane (the
    # ``test_probe_activated_abilities_o2.py`` lane covered the
    # full-cross-engine ``compare_fields`` AA pivot for creature
    # carriers; THIS batch pins the per-slug attribution for the
    # closely-related real-EoE Land AAs that the o2 lane DROPPED on
    # cost-substrate grounds, via the lighter EEEE-idiom on the
    # EFFECT half).  Same lane discipline as batches 1-3: per-slug
    # attribution credits a PROBED slot per-printing, no engine
    # changes, no Rust changes, no substrate widens.  Each module
    # carries a canonical ``test_cross_engine_real_eoe_<slug>_...
    # _parity`` function that binds the live EoE printing via the
    # module-scope ``_PRINTINGS = get_active_source().get_printings()``
    # idiom (the ``_probe_module_probed_cards_via_module_scope_binding``
    # widen accepts it) + drives the GENUINE parsed printing through
    # the parse + bridge round-trip + Python-side resolve idiom:
    #
    #   * ``test_high_market_parity.py`` — High Market ({0} Land,
    #     ~457 17lands decks); non-mana AA ({T}, Sacrifice a
    #     creature: You gain 1 life) → GainLife(amount=1).  The
    #     FIRST PROBE_MODULES-credited probe of GainLife on a real-
    #     EoE Land + AA carrier; the sacrifice-creature cost atom
    #     (``sacrifice_another_creature_or_artifact``) is the cost-
    #     substrate scope and stays substrate-deferred for this lane
    #     (the EFFECT-half bridge round-trip is what credits PROBED
    #     per-slug per the round-1 PROBED-tier definition).
    #   * ``test_mana_confluence_parity.py`` — Mana Confluence ({0}
    #     Land, ~319 17lands decks); mana AA ({T}, Pay 1 life: Add
    #     one mana of any color) → AddManaToPool(produces=(('any',
    #     1),), spend_restriction=None).  The FIRST PROBE_MODULES-
    #     credited consumer of the round-27 ``add_mana_to_pool``
    #     bridge arm on a real-EoE Land carrier; the pay_life=1 cost
    #     atom stays cost-substrate-deferred.
    #   * ``test_cascading_cataracts_parity.py`` — Cascading Cataracts
    #     ({0} Land, ~237 17lands decks); mana AA ({5},{T}: Add five
    #     mana of any one color) → AddManaToPool(produces=(('any',
    #     5),), spend_restriction=None).  Templates on the immediately-
    #     prior batch-4 sibling Mana Confluence (amount=1) — the
    #     distinguishing dispatch is the **amount=5** batch-mint
    #     (the inner ``for _ in range(count)`` loop in
    #     AddManaToPool.resolve fires count times).
    #   * ``test_gemstone_caverns_parity.py`` — Gemstone Caverns ({0}
    #     Legendary Land, ~183 17lands decks); mana AA ({T}: Add one
    #     mana of any color) → AddManaToPool(produces=(('any', 1),),
    #     spend_restriction=None).  Bit-identical bridge round-trip
    #     to Mana Confluence at the Effect level; the per-slug
    #     attribution distinction is the **Legendary** supertype
    #     (Gemstone Caverns is Legendary; Mana Confluence is non-
    #     Legendary).  Per the cathedral-of-war-style same-Effect-
    #     class-different-printing-slug precedent, both probes credit
    #     their respective slugs independently.
    #   * ``test_eldrazi_temple_parity.py`` — Eldrazi Temple ({0}
    #     Land, ~44 17lands decks); AA[0] ({T}: Add {C}) →
    #     AddManaToPool(produces=(('C', 1),), spend_restriction=
    #     None).  Distinct from the sibling batch-4 'any'-color Land
    #     probes — the FIRST PROBED-tier slot for the **'C'
    #     (colorless)** color via the add_mana_to_pool bridge arm.
    #     The synthetic Rust carrier exercises Rust's native
    #     ``validate_mana_symbol`` directly (no 'any' → 'C' coercion
    #     needed, distinct from sibling probes).  AA[1] (the
    #     spend_restriction='colorless_eldrazi' rider on the {C}{C}
    #     variant) is deferred per the IIII / HHHH "covered carrier
    #     with spend-restriction rider" implicit drop + the batch-2
    #     Wickerfolk Thresher narrow-pin half-coverage precedent —
    #     AA[0] alone carries the load-bearing slug-attribution
    #     flip.
    #
    # Pure measurement-attribution + per-slug credit: no engine
    # changes, no Rust changes, no substrate widens.  Net delta:
    # +5 PROBED / -5 covered_by_construction: PROBED 329 → 334;
    # covered_by_construction 86 → 81; BLOCKED unchanged at 60;
    # pool total 475 unchanged.
    REPO_ROOT / "tests" / "test_high_market_parity.py",
    REPO_ROOT / "tests" / "test_mana_confluence_parity.py",
    REPO_ROOT / "tests" / "test_cascading_cataracts_parity.py",
    REPO_ROOT / "tests" / "test_gemstone_caverns_parity.py",
    REPO_ROOT / "tests" / "test_eldrazi_temple_parity.py",
    # **covered-by-construction-probe-writing-p5 (2026-05-25):** Five
    # additional per-card real-EoE cross-engine byte-equal probes
    # extending the lane established by batches 1-4.  This batch
    # opens **TWO new shape families** for the per-slug attribution
    # lane:
    #
    #   * **activated-ability + DrawCards on artifact-creature
    #     carrier with {generic}+{T} cost shape** (Slagdrill Scrapper)
    #   * **activated-ability + EquipToTargetCreatureYouControl on
    #     artifact-equipment carrier with paid-Equip {generic} cost
    #     shape** (Squire's Lightblade + The Dominion Bracelet)
    #
    # plus continuing the batch-4 AddManaToPool(any, 1) shape family
    # onto **artifact-creature** + **non-Legendary Land** carriers
    # (Gene Pollinator + Sunken Citadel), templating directly off the
    # batch-4 Mana Confluence / Gemstone Caverns siblings.  Same lane
    # discipline as batches 1-4: per-slug attribution credits a
    # PROBED slot per-printing, no engine changes, no Rust changes,
    # no substrate widens.  Each module carries a canonical
    # ``test_cross_engine_real_eoe_<slug>_..._parity`` function that
    # binds the live EoE printing via the module-scope ``_PRINTINGS
    # = get_active_source().get_printings()`` idiom + drives the
    # GENUINE parsed printing through the parse + bridge round-trip +
    # Python-side resolve idiom:
    #
    #   * ``test_gene_pollinator_parity.py`` — Gene Pollinator ({G}
    #     Artifact Creature, ~31,824 17lands decks); mana AA ({T}:
    #     Add one mana of any color) → AddManaToPool(produces=
    #     (('any', 1),), spend_restriction=None).  Bit-identical
    #     bridge round-trip to the batch-4 Mana Confluence /
    #     Gemstone Caverns siblings at the Effect level; the per-
    #     slug attribution distinction is the **Artifact Creature
    #     carrier** (not a Land) — per the cathedral-of-war-style
    #     same-Effect-class-different-printing-slug precedent, each
    #     carrier-typed printing-slug gets its own PROBED-tier slot.
    #     The highest-deck-count flip in this batch (~31.8k decks).
    #   * ``test_slagdrill_scrapper_parity.py`` — Slagdrill Scrapper
    #     ({R} Artifact Creature, ~12,879 17lands decks); activated
    #     ability ({2},{T}: Draw a card) → DrawCards(amount=1).
    #     **NEW shape family** for the per-slug attribution lane:
    #     **activated-ability + DrawCards on artifact-creature
    #     carrier with {generic}+{T} cost shape**.  The FIRST
    #     PROBE_MODULES-credited probe of the DrawCards Effect class
    #     on an activated-ability artifact-creature carrier (DrawCards
    #     is widely covered across spell-effect carriers but the AA-
    #     on-creature variant is the new slot).  Exercises the
    #     ``draw_cards`` bridge arm field-name narrowing (Rust's
    #     ``count`` → Python's ``amount``).  The {2} generic mana
    #     cost atom stays cost-substrate-deferred.
    #   * ``test_squires_lightblade_parity.py`` — Squire's Lightblade
    #     ({W} Artifact — Equipment, ~3,927 17lands decks); Equip
    #     activated ability ({3}: attach this Equipment to target
    #     creature you control) → EquipToTargetCreatureYouControl(
    #     granted_keywords_ueot=frozenset()).  **NEW shape family**
    #     for the per-slug attribution lane: **activated-ability +
    #     EquipToTargetCreatureYouControl on artifact-equipment
    #     carrier with paid-Equip {generic} cost shape**.  The FIRST
    #     PROBE_MODULES-credited probe of the
    #     EquipToTargetCreatureYouControl Effect class (the round-19
    #     audit-refresh bridge arm landed end-to-end without a slug-
    #     attribution probe — sister to the
    #     ``attach_to_target_creature_you_control`` ETB-shape arm).
    #     The ETB-attach TriggeredAbility variant (with the
    #     granted_keywords_ueot={'first strike'} rider) is implicit-
    #     drop per the IIII / HHHH "covered carrier with non-bridge-
    #     clean rider" precedent.
    #   * ``test_the_dominion_bracelet_parity.py`` — The Dominion
    #     Bracelet ({2} Artifact — Equipment, ~830 17lands decks);
    #     Equip activated ability ({1}: attach) →
    #     EquipToTargetCreatureYouControl(granted_keywords_ueot=
    #     frozenset()).  Templates on the immediately-prior batch-5
    #     sibling Squire's Lightblade (the FIRST PROBE_MODULES-
    #     credited consumer of equip_to_target_creature_you_control);
    #     bit-identical Effect-level bridge round-trip — the per-slug
    #     attribution distinction is the printing identity (mana cost
    #     {2} generic-only vs {W} colored; Equip {1} vs {3}).
    #   * ``test_sunken_citadel_parity.py`` — Sunken Citadel ({0}
    #     Land, ~1,235 17lands decks); AA[0] ({T}: Add one mana of
    #     any color) → AddManaToPool(produces=(('any', 1),),
    #     spend_restriction=None).  Bit-identical bridge round-trip
    #     to the batch-4 Mana Confluence / Gemstone Caverns siblings
    #     + the batch-5 Gene Pollinator sibling at the Effect level.
    #     AA[1] (the spend_restriction='land_activation' rider on
    #     the {T}: Add {2} variant) is deferred per the IIII / HHHH
    #     "covered carrier with spend-restriction rider" implicit
    #     drop + the batch-4 Eldrazi Temple AA[1] colorless_eldrazi
    #     precedent — AA[0] alone carries the load-bearing slug-
    #     attribution flip.
    #
    # Pure measurement-attribution + per-slug credit: no engine
    # changes, no Rust changes, no substrate widens.  Net delta:
    # +5 PROBED / -5 covered_by_construction: PROBED 334 → 339;
    # covered_by_construction 81 → 76; BLOCKED unchanged at 60; pool
    # total 475 unchanged.
    REPO_ROOT / "tests" / "test_gene_pollinator_parity.py",
    REPO_ROOT / "tests" / "test_slagdrill_scrapper_parity.py",
    REPO_ROOT / "tests" / "test_squires_lightblade_parity.py",
    REPO_ROOT / "tests" / "test_the_dominion_bracelet_parity.py",
    REPO_ROOT / "tests" / "test_sunken_citadel_parity.py",
    # **covered-by-construction-probe-writing-p6 (2026-05-25):** Five
    # additional per-card real-EoE cross-engine byte-equal probes
    # extending the lane established by batches 1-5.  This batch opens
    # **ONE new shape family** for the per-slug attribution lane:
    #
    #   * **basic-land carrier via the parser-flattened-vanilla
    #     profile + the basic-land CardDef bridge auto-wire** — the
    #     parser ships basic lands as ZERO-Effect vanilla printings
    #     with the ``{T}: Add {color}`` primitive folded into the
    #     ``produces`` field; the loader-admit-gated converter
    #     ``trajectory._printing_to_card_def`` recognizes the printing
    #     via ``_printing_is_bridge_basic_land`` and emits a CardDef
    #     with ``mana_produced=(<color>,)`` which
    #     ``cross_engine._card_def_to_python_printing`` materializes
    #     back into a Python ``CardPrinting`` that **auto-wires the
    #     {T}: Add {color} mana ability** as a structured
    #     ``ActivatedAbility(AddManaToPool(produces=((<color>, 1),)))``.
    #     The bridge auto-wire (NOT the parser-shipped AA) is the
    #     load-bearing observable; the auto-wired Effect is byte-equal
    #     to the round-27 ``add_mana_to_pool`` bridge arm's emission.
    #
    # plus continuing the batch-5 EquipToTargetCreatureYouControl
    # shape family onto **another artifact-equipment carrier** (Illvoi
    # Light Jammer), templating directly off the batch-5 sibling
    # Squire's Lightblade / The Dominion Bracelet probes.  Same lane
    # discipline as batches 1-5: per-slug attribution credits a PROBED
    # slot per-printing, no engine changes, no Rust changes, no
    # substrate widens.
    #
    #   * ``test_forest_parity.py`` — Forest (Basic Land — Forest,
    #     ~466,226 17lands decks); basic-land bridge auto-wire →
    #     AddManaToPool(produces=(('G', 1),), spend_restriction=None).
    #     **NEW shape family** for the per-slug attribution lane: the
    #     FIRST PROBE_MODULES-credited probe binding a basic-land slug
    #     to its bridge-auto-wired AA shape via the
    #     ``_printing_to_card_def`` → ``_card_def_to_python_printing``
    #     basic-land path.  The highest-deck-count covered_by_
    #     construction holdout — every G-touching deck plays Forest.
    #   * ``test_island_parity.py`` — Island (Basic Land — Island,
    #     ~465,009 17lands decks); basic-land bridge auto-wire →
    #     AddManaToPool(produces=(('U', 1),)).  Sibling to the Forest
    #     probe — bit-identical bridge auto-wire mechanism, distinct
    #     color slot 'U' (per the cathedral-of-war-style same-Effect-
    #     class-different-printing-slug precedent, each basic-land
    #     color slot gets its own PROBED-tier slot).
    #   * ``test_swamp_parity.py`` — Swamp (Basic Land — Swamp,
    #     ~434,410 17lands decks); basic-land bridge auto-wire →
    #     AddManaToPool(produces=(('B', 1),)).  Sibling to the Forest
    #     / Island probes — distinct color slot 'B'.
    #   * ``test_mountain_parity.py`` — Mountain (Basic Land —
    #     Mountain, ~365,413 17lands decks); basic-land bridge auto-
    #     wire → AddManaToPool(produces=(('R', 1),)).  Sibling to the
    #     Forest / Island / Swamp probes — distinct color slot 'R'.
    #   * ``test_illvoi_light_jammer_parity.py`` — Illvoi Light Jammer
    #     ({1}{U} Artifact — Equipment, ~10,767 17lands decks); Equip
    #     activated ability ({3}: attach this Equipment to target
    #     creature you control) → EquipToTargetCreatureYouControl(
    #     granted_keywords_ueot=frozenset()).  Templates directly off
    #     the batch-5 sibling Squire's Lightblade / The Dominion
    #     Bracelet probes — bit-identical Effect-level bridge round-
    #     trip, distinct printing identity (mana cost {1}{U} U-color
    #     vs {W} Squire's; Equip {3} matches Squire's).  The ETB-
    #     attach TriggeredAbility variant (with the
    #     granted_keywords_ueot={'hexproof'} rider) is implicit-drop
    #     per the IIII / HHHH "covered carrier with non-bridge-clean
    #     rider" precedent + the batch-5 Squire's Lightblade narrow-
    #     pin half-coverage precedent.
    #
    # Pure measurement-attribution + per-slug credit: no engine
    # changes, no Rust changes, no substrate widens.  Net delta:
    # +5 PROBED / -5 covered_by_construction: PROBED 339 → 344;
    # covered_by_construction 76 → 71; BLOCKED unchanged at 60; pool
    # total 475 unchanged.
    REPO_ROOT / "tests" / "test_forest_parity.py",
    REPO_ROOT / "tests" / "test_island_parity.py",
    REPO_ROOT / "tests" / "test_swamp_parity.py",
    REPO_ROOT / "tests" / "test_mountain_parity.py",
    REPO_ROOT / "tests" / "test_illvoi_light_jammer_parity.py",
    # Cost-reduction substrate Phase 1 Cycle 3 (cost-reduction-
    # phase-1-cycle-3-gigastorm-probe-p3 lane, 2026-05-25):
    # per-card real-EoE cross-engine byte-equality probe for
    # **Gigastorm Titan** flips ``covered_by_construction`` ->
    # PROBED in the pool-parity metric.  Companion Cycle 4 lane
    # will land ``test_probe_lashwhip_predator_real_eoe_cost_
    # reduction.py`` next.  Drives BOTH lifecycles of the Phase-1
    # AnotherSpellCastThisTurn cost-reduction substrate that
    # commits ``8593b0fb`` (Cycle 2 FLIP) shipped: (a) full-cost
    # cast as first spell of turn — pays base {4}{U}, reduction
    # condition False; (b) reduced-cost cast as second spell —
    # pays {1}{U} after the {3} reduction applies, the load-bearing
    # case the C2 substrate FLIP rides on.  Pool-primed mana on
    # both engines so the cost-payment arithmetic is the entire
    # load-bearing signal (no land-tap noise).  Full
    # ``compare_fields == []`` over the 22-field cross-engine
    # field view post-cast.  Per-slug attribution = "Gigastorm
    # Titan" (24,908 17lands decks, the larger of the two C2
    # carriers).  This commit is concurrent with the batch-6
    # covered-by-construction probe-writing lane above; both
    # append to PROBE_MODULES (no semantic conflict — different
    # per-slug attributions).
    REPO_ROOT
    / "tests"
    / "test_probe_gigastorm_titan_real_eoe_cost_reduction.py",
    # Cost-reduction substrate Phase 1 Cycle 4 (cost-reduction-
    # phase-1-cycle-4-lashwhip-probe-p1 lane, 2026-05-25):
    # per-card real-EoE cross-engine byte-equality probe for
    # **Lashwhip Predator** flips ``covered_by_construction`` ->
    # PROBED in the pool-parity metric.  THE FINAL probe of
    # cost-reduction Phase 1; with this commit BLOCKED drops
    # 59 -> 58 and Phase 1 closure is complete.  Sibling to the
    # Cycle 3 Gigastorm Titan probe (same shape; exercises the
    # OpponentsControlAtLeast(IsCreature(), 3) Condition variant
    # — the SECOND and LAST Phase-1 Condition shape — on
    # Lashwhip's {4}{G}{G} 5/7 reach Plant Beast).  Drives BOTH
    # lifecycles of the Phase-1 OpponentsControlAtLeast cost-
    # reduction substrate that commit ``8593b0fb`` (Cycle 2 FLIP)
    # shipped: (a) full-cost lifecycle with 0 opp creatures on bf
    # — pays {4}{G}{G}, and (b) reduced-cost lifecycle with 3
    # opp creatures pre-seated on opp's bf via the design doc
    # §7.3 scripted picker — pays {2}{G}{G} after the {2}
    # reduction applies, the load-bearing case the C2 substrate
    # FLIP rides on for the battlefield-scanning condition
    # variant.  Pool-primed mana on both engines so the cost-
    # payment arithmetic is the entire load-bearing signal (no
    # land-tap noise).  Full ``compare_fields == []`` over the
    # 22-field cross-engine field view post-cast.  Per-slug
    # attribution = "Lashwhip Predator" (10,064 17lands decks,
    # the second of the two C2 carriers; ~24,908 decks total
    # unblocked across the Phase-1 admit lane).
    REPO_ROOT
    / "tests"
    / "test_probe_lashwhip_predator_real_eoe_cost_reduction.py",
    # Cost-reduction substrate Phase 2 Cycle 3 (cost-reduction-
    # phase-2-cycle-3-uthros-probe-p1 lane, 2026-05-25): per-card
    # real-EoE cross-engine byte-equality probe for **Uthros
    # Psionicist** flips ``covered_by_construction`` -> PROBED in
    # the pool-parity metric. Companion Cycle 4 lane will land
    # ``test_probe_sami_wildcat_captain_real_eoe_cost_reduction.py``
    # next (the ``PerControlled(IsArtifact())`` variable-multiplier
    # carrier; second of the two Phase-2 carriers). Drives BOTH
    # lifecycles of the Phase-2 NthSpellThisTurn external
    # cost-reduction substrate that commit ``c370cee4`` (Cycle 2
    # FLIP) shipped via the widened
    # ``_printing_is_bridge_pure_cost_reduction_creature`` admit
    # predicate + the ``apply_external_cost_reductions_rust``
    # helper at ``state_ops_legal.rs:897`` (externals-first
    # ordering): (a) full-cost lifecycle with one Uthros-shape
    # carrier on caster's bf + cast as the FIRST spell of the turn
    # (``spells_cast_this_turn == 0``); NthSpellThisTurn(n=2)
    # checks ``spells_cast_this_turn == n - 1 == 1`` → False, no
    # reduction applies, pays base ``{2}{U}``; (b) reduced-cost
    # lifecycle with one Uthros-shape carrier on bf + cast as the
    # SECOND spell (``spells_cast_this_turn == 1`` via the C1
    # substrate setter); condition True, the {2} external
    # reduction applies and pays the reduced ``{U}`` cost — the
    # load-bearing case the Phase-2 C2 substrate FLIP rides on for
    # the externals-axis condition variant. Pool-primed mana on
    # both engines so the cost-payment arithmetic is the entire
    # load-bearing signal (no land-tap noise). Full
    # ``compare_fields == []`` over the 22-field cross-engine
    # field view post-cast on BOTH lifecycles + the pre-cast
    # scripted-picker sanity check on lifecycle B. Per-slug
    # attribution = "Uthros Psionicist" (~14,767 17lands decks,
    # the larger of the two Phase-2 carriers; first half of the
    # +15,575-deck Phase-2 admit lane).
    REPO_ROOT
    / "tests"
    / "test_probe_uthros_psionicist_real_eoe_cost_reduction.py",
    # Cost-reduction substrate Phase 2 Cycle 4 (cost-reduction-
    # phase-2-cycle-4-sami-probe-p1 lane, 2026-05-25): per-card
    # real-EoE cross-engine byte-equality probe for **Sami, Wildcat
    # Captain** flips ``covered_by_construction`` -> PROBED in the
    # pool-parity metric. **THE FINAL probe of Phase 2** — with
    # this entry, both Phase-2 cost-reduction carriers (Uthros C3 +
    # Sami C4) are PROBED-tier and the covered_by_construction
    # cost-reduction lane drops to ONE remaining carrier (Fungal
    # Colossus on PerDifferentlyNamedLand, Phase-3 territory).
    # Drives BOTH lifecycles of the Phase-2 PerControlled(IsArtifact())
    # external cost-reduction substrate — the FIRST variable-
    # multiplier ExternalCondition path Phase 2 ships — that
    # commit ``c370cee4`` (Cycle 2 FLIP) landed via the widened
    # ``_printing_is_bridge_pure_cost_reduction_creature`` admit
    # predicate + the ``apply_external_cost_reductions_rust``
    # helper's PerControlled arm at ``state_ops_legal.rs:924-957``
    # (the multiplier IS the count — affinity-style scaling):
    # (a) full-cost lifecycle with one Sami-shape carrier on
    # caster's bf + ZERO controlled artifacts; PerControlled
    # (IsArtifact()) checks count >= 1 — False on 0 artifacts —
    # no reduction applies, pays base ``{4}{R}{W}``; (b)
    # reduced-cost lifecycle with one Sami-shape carrier on bf +
    # TWO vanilla Artifact-shape carriers pre-seated on caster's
    # bf via the scripted picker; condition True with multiplier=2,
    # the {1}-per-artifact reduction applies as ``amount *
    # multiplier == 1 * 2 == 2`` generic dropped, pays the reduced
    # ``{2}{R}{W}`` cost — the load-bearing case the Phase-2 C2
    # substrate FLIP rides on for the variable-multiplier external
    # condition variant. Pool-primed mana on both engines so the
    # cost-payment arithmetic is the entire load-bearing signal (no
    # land-tap noise). Full ``compare_fields == []`` over the
    # 22-field cross-engine field view post-cast on BOTH lifecycles
    # + the pre-cast scripted-picker sanity check on lifecycle B.
    # Per-slug attribution = "Sami, Wildcat Captain" (~808 17lands
    # decks attributable specifically to Sami, the smaller of the
    # two Phase-2 carriers; second half of the +15,575-deck Phase-2
    # admit lane). **With this entry, Phase 2 closure is complete.**
    REPO_ROOT
    / "tests"
    / "test_probe_sami_wildcat_captain_real_eoe_cost_reduction.py",
    # Cost-reduction substrate Phase 3 Cycle 3 (cost-reduction-
    # phase-3-cycle-3-fungal-probe-p1 lane, 2026-05-25): per-card
    # real-EoE cross-engine byte-equality probe for **Fungal
    # Colossus** flips ``covered_by_construction`` -> PROBED in the
    # pool-parity metric. **THE FINAL probe of Phase 3 -- AND THE
    # FINAL probe of the entire cost-reduction substrate single-
    # gated lane.** With this entry, Fungal Colossus (the sole
    # Phase-3 cost-reduction carrier) is PROBED-tier and the
    # cost-reduction substrate retires from
    # ``covered_by_construction`` entirely. Drives THREE scenarios
    # across the variable-X land-count multiplier axis of the
    # Phase-3 PerDifferentlyNamedLand spell-local cost-reduction
    # substrate that commit ``8525d18e`` (Cycle 1 substrate) +
    # ``7036c191`` (Cycle 2 FLIP) shipped via the widened
    # ``_cost_reduction_rule_is_phase1_or_3`` admit helper + the
    # ``apply_cost_reductions_rust`` spell-local match arm extension
    # + ``unique_land_names_count`` HashSet<&str> over
    # ``printing.name`` walk at ``state_ops_legal.rs:936-954``:
    # (a) 0 lands controlled -- the distinct-name set is empty,
    # count == 0 < 1, condition False, no reduction applies, pays
    # base ``{6}{G}``; (b) 4 distinctly-named EoE-pool lands
    # (Breeding Pool / Godless Shrine / Command Bridge / Adagia,
    # Windswept Bastion) pre-seated on caster's bf via the design
    # doc §7.3 scripted picker -- the HashSet collects 4 distinct
    # keys, multiplier=4, the {1} amount * 4 = {4} reduction
    # applies and pays the reduced ``{2}{G}`` cost -- the load-
    # bearing variable-multiplier case the Phase-3 substrate FLIP
    # rides on for the spell-local axis; (c) 4 SAME-named lands
    # (Breeding Pool x4) pre-seated -- the HashSet collapses to a
    # single key, multiplier=1 (NOT 4!), the {1} amount * 1 = {1}
    # reduction applies and pays the reduced ``{5}{G}`` cost --
    # the SET-SEMANTIC TEETH proving both engines key the
    # multiplier on the DISTINCT-NAME set, not the raw caster's-
    # land count. Pool-primed mana on both engines so the cost-
    # payment arithmetic is the entire load-bearing signal (no
    # land-tap noise). Full ``compare_fields == []`` over the
    # 22-field cross-engine field view post-cast on ALL THREE
    # scenarios + the pre-cast scripted-picker sanity check on
    # scenarios (b) + (c). Per-slug attribution = "Fungal Colossus"
    # (~13,165 17lands decks; the sole Phase-3 carrier; 100% of
    # the cost-reduction REMAINING single-gated deck count post-
    # Phase-2 closure). **With this entry, Phase 3 closure is
    # complete AND the entire cost-reduction substrate campaign is
    # closed -- BLOCKED 55 -> 55 (the substrate retires from the
    # covered_by_construction tier; the single-gated row stays at
    # 0 from the C2 FLIP).**
    REPO_ROOT
    / "tests"
    / "test_probe_fungal_colossus_real_eoe_cost_reduction.py",
    # **covered-by-construction-probe-writing-p7 (2026-05-25):** Six
    # additional per-card real-EoE cross-engine byte-equal probes
    # extending the lane established by batches 1-6.  This batch opens
    # **TWO new shape families** for the per-slug attribution lane:
    #
    #   * **manland carrier via the bare BecomeLandCreatureUEOT bridge
    #     arm shape on a Land carrier** — the parser ships the manland
    #     animation ability as a structured ``ActivatedAbility(
    #     BecomeLandCreatureUEOT(power, toughness, granted_keywords,
    #     unblockable, granted_subtype, granted_activated_abilities,
    #     granted_triggered_abilities))``; the bare bridge arm
    #     ``become_land_creature_ueot`` carries only the
    #     ``power`` / ``toughness`` scalars, dropping the rider fields
    #     per the documented arm signature.  Mutavault is the ONLY
    #     manland in the covered_by_construction tier whose all-bare-
    #     riders Effect shape (2/2 + ZERO granted_keywords + no
    #     unblockable + no granted_subtype + no granted abilities)
    #     round-trips byte-equal through the bare arm; the other
    #     manlands (Celestial Colonnade / Creeping Tar Pit / Hissing
    #     Quagmire / Lumbering Falls / Needle Spires / Raging Ravine /
    #     Shambling Vent / Stirring Wildwood / Inkmoth Nexus) all
    #     carry granted_keywords / unblockable / granted_triggered_
    #     abilities riders that DO NOT round-trip clean through the
    #     bare arm and stay covered_by_construction under the IIII /
    #     HHHH "covered carrier with non-bridge-clean rider" precedent.
    #
    #   * **bridge-simple vanilla-creature carrier via the
    #     ``_printing_is_bridge_simple_creature`` admit + CardDef
    #     round-trip + seated-permanent observation** — vanilla
    #     creatures (no AAs / no TAs / no spell_effect, keywords ⊆
    #     _SAFE_KEYWORDS) round-trip through the CardDef bridge
    #     carrying the (card_types, power, toughness, mana_cost,
    #     _SAFE_KEYWORDS-subset keywords) tuple byte-equal.  The
    #     parser-side subtypes are documented-drop on round-trip.
    #     The "resolve smoke" piece of the EEEE-idiom is replaced
    #     with the **seated-permanent observation** — there is no
    #     structured Effect on a vanilla creature to resolve, so the
    #     load-bearing observable is Python's combat readers
    #     (``effective_power`` / ``effective_toughness`` /
    #     ``is_creature_now``) read against the seated bridge round-
    #     tripped permanent.
    #
    # Same lane discipline as batches 1-6: per-slug attribution
    # credits a PROBED slot per-printing, no engine changes, no Rust
    # changes, no substrate widens.
    #
    #   * ``test_mutavault_parity.py`` — Mutavault ({0} Land, 679
    #     17lands decks); animation ActivatedAbility →
    #     BecomeLandCreatureUEOT(power=2, toughness=2, all-bare
    #     riders).  **NEW shape family** for the per-slug attribution
    #     lane: the FIRST PROBE_MODULES-credited probe binding the
    #     BecomeLandCreatureUEOT Effect class to a slug — Mutavault is
    #     the ONLY manland in covered_by_construction with all-bare-
    #     riders Effect shape that round-trips byte-equal through the
    #     bare bridge arm.
    #   * ``test_daggermaw_megalodon_parity.py`` — Daggermaw Megalodon
    #     ({4}{U}{U} Creature — Shark, 0 17lands decks; Stellar Sights /
    #     Special Guests reprint).  **NEW shape family** for the per-
    #     slug attribution lane: the FIRST PROBE_MODULES-credited probe
    #     binding the bridge-simple-vanilla-creature shape family to a
    #     slug via the seated-permanent observation (vigilance keyword
    #     variant, 5/7 P/T).
    #   * ``test_magus_of_the_moon_parity.py`` — Magus of the Moon
    #     ({2}{R} Creature — Human Wizard, 0 17lands decks; Stellar
    #     Sights / Special Guests reprint).  Sibling to the Daggermaw
    #     probe — the FIRST PROBE_MODULES-credited probe binding the
    #     ZERO-keyword variant of the bridge-simple-vanilla-creature
    #     family (2/2 P/T).  The parser-side
    #     ``nonbasic_lands_are_mountains=True`` static bool is
    #     implicit-drop per the half-coverage precedent — the bool
    #     rider does NOT trip the ``static_abilities`` tuple check in
    #     ``_printing_is_bridge_simple_creature``.
    #   * ``test_cackling_slasher_parity.py`` — Cackling Slasher
    #     ({3}{B} Creature — Human Assassin, 0 17lands decks).  The
    #     deathtouch-keyword variant of the bridge-simple-vanilla-
    #     creature family (3/3 P/T).  Closes the batch-5 attribution
    #     gap — the Squire's Lightblade / The Dominion Bracelet
    #     siblings used Cackling Slasher's name as a contextual
    #     reference but exercised a SYNTHETIC Bear as the equip target
    #     so the walker did NOT credit Cackling Slasher.
    #   * ``test_spectral_snatcher_parity.py`` — Spectral Snatcher
    #     ({4}{B}{B} Creature — Spirit, 0 17lands decks; Stellar
    #     Sights / Special Guests reprint).  Sibling to the Magus of
    #     the Moon probe — the (6, 5) P/T variant of the ZERO-keyword
    #     sub-shape; per the cathedral-of-war-style same-Effect-class-
    #     different-printing-slug precedent, each P/T variant earns a
    #     PROBED-tier slot.
    #   * ``test_bedhead_beastie_parity.py`` — Bedhead Beastie ({4}{R}{R}
    #     Creature — Beast, 0 17lands decks).  The menace-keyword
    #     variant of the bridge-simple-vanilla-creature family (5/6
    #     P/T).
    #
    # Pure measurement-attribution + per-slug credit: no engine
    # changes, no Rust changes, no substrate widens.  Net delta:
    # +6 PROBED / -6 covered_by_construction: PROBED 344 → 350;
    # covered_by_construction 71 → 65; BLOCKED unchanged at 60; pool
    # total 475 unchanged.
    REPO_ROOT / "tests" / "test_mutavault_parity.py",
    REPO_ROOT / "tests" / "test_daggermaw_megalodon_parity.py",
    REPO_ROOT / "tests" / "test_magus_of_the_moon_parity.py",
    REPO_ROOT / "tests" / "test_cackling_slasher_parity.py",
    REPO_ROOT / "tests" / "test_spectral_snatcher_parity.py",
    REPO_ROOT / "tests" / "test_bedhead_beastie_parity.py",
    # **covered-by-construction-probe-writing-p8 (2026-05-25):** Five
    # additional per-card real-EoE cross-engine byte-equal probes
    # extending the batch-7 bridge-simple-vanilla-creature shape family
    # to four new per-keyword sub-shapes (flying / trample / double
    # strike / haste) and TWO NEW multi-type-carrier sub-shapes
    # (Artifact+Creature, Enchantment+Creature).  Each per-keyword /
    # per-card-type-tuple variant earns a PROBED-tier slot per the
    # cathedral-of-war-style same-Effect-class-different-printing-slug
    # precedent — same lane discipline as batches 1-7: per-slug
    # attribution credits a PROBED slot per-printing, no engine
    # changes, no Rust changes, no substrate widens.
    #
    #   * ``test_piranha_fly_parity.py`` — Piranha Fly ({1}{U} Creature
    #     — Fish Insect, 2/1, flying; 0 17lands decks — Stellar Sights /
    #     Special Guests reprint).  The FIRST flying-keyword binding
    #     under the bridge-simple-vanilla-creature family templated by
    #     batch 7.
    #   * ``test_shepherding_spirits_parity.py`` — Shepherding Spirits
    #     ({4}{W}{W} Creature — Spirit, 4/5, flying; 0 17lands decks).
    #     The (4, 5) P/T variant of the flying sub-shape — distinct
    #     from Piranha Fly (2/1).
    #   * ``test_slavering_branchsnapper_parity.py`` — Slavering
    #     Branchsnapper ({4}{G}{G} Creature — Lizard, 7/6, trample; 0
    #     17lands decks).  The FIRST trample-keyword binding under the
    #     family.
    #   * ``test_patched_plaything_parity.py`` — Patched Plaything
    #     ({2}{W} Artifact Creature — Toy, 4/3, double strike; 0 17lands
    #     decks).  The FIRST double-strike-keyword binding AND the
    #     FIRST Artifact+Creature multi-type-carrier sub-shape under
    #     the family.  Parser-side ``card_types=("Artifact",
    #     "Creature")`` is documented-drop on round-trip per the bare
    #     ``_printing_is_bridge_simple_creature`` arm (CardDef builds
    #     ``card_type="Creature" + extra_card_types=()``); same
    #     symmetric-drop precedent as the batch-7 subtype drop.
    #   * ``test_fear_of_being_hunted_parity.py`` — Fear of Being
    #     Hunted ({1}{R}{R} Enchantment Creature — Nightmare, 4/2,
    #     haste; 0 17lands decks).  The FIRST haste-keyword binding
    #     AND the FIRST Enchantment+Creature multi-type-carrier sub-
    #     shape under the family.  Parser-side ``card_types=
    #     ("Enchantment", "Creature")`` is documented-drop on round-
    #     trip via the same bare simple-creature CardDef arm.
    #
    # Pure measurement-attribution + per-slug credit: no engine
    # changes, no Rust changes, no substrate widens.  Net delta:
    # +5 PROBED / -5 covered_by_construction: PROBED 350 → 355;
    # covered_by_construction 65 → 60; BLOCKED unchanged at 58; pool
    # total 475 unchanged.
    REPO_ROOT / "tests" / "test_piranha_fly_parity.py",
    REPO_ROOT / "tests" / "test_shepherding_spirits_parity.py",
    REPO_ROOT / "tests" / "test_slavering_branchsnapper_parity.py",
    REPO_ROOT / "tests" / "test_patched_plaything_parity.py",
    REPO_ROOT / "tests" / "test_fear_of_being_hunted_parity.py",
    # **covered-by-construction-probe-writing-p9 (2026-05-25):** Five
    # per-card real-EoE cross-engine byte-equal probes binding the
    # Duskmourn conditional-painland cycle slugs to PROBED-tier slots.
    # The 10 painlands (Abandoned Campground, Bleeding Woods, Etched
    # Cornfield, Lakeside Shack, Murky Sewer, Neglected Manor,
    # Peculiar Lighthouse, Raucous Carnival, Razortrap Gorge,
    # Strangled Cemetery) ALL pass the dedicated bridge predicate
    # ``_printing_is_bridge_nonbasic_painland_conditional`` (Phase-2
    # substrate, 2026-05-23 — see ``trajectory.py:8217-8329``); the
    # bridge round-trip auto-wires per-produce-color
    # ``ActivatedAbility(AddManaToPool(...))`` AAs from the
    # ``mana_produced`` tuple (cross_engine.py:14073-14081) and
    # threads ``enters_tapped_unless_any_player_life_at_most=13``
    # through to the Python CardPrinting.  Per the cathedral-of-war-
    # style same-shape-different-printing-slug precedent, each dual-
    # color painland slug earns its own PROBED-tier slot.
    #
    # This batch picks five DISTINCT color pairs from the cycle (one
    # probe per pair) — the remaining five painlands stay covered-by-
    # construction (sufficient cycle coverage for this batch's quota;
    # the predicate already admits them all, so future batches can
    # template trivially).
    #
    #   * ``test_abandoned_campground_parity.py`` — Abandoned Campground
    #     ({W}{U} painland, 0 17lands decks).  The FIRST PROBE_MODULES-
    #     credited probe binding a Duskmourn-painland slug under the
    #     Phase-2 substrate.  FIRST W/U color-pair binding.
    #   * ``test_bleeding_woods_parity.py`` — Bleeding Woods ({G}{R}
    #     painland, 0 17lands decks).  FIRST G/R color-pair binding.
    #   * ``test_murky_sewer_parity.py`` — Murky Sewer ({U}{B}
    #     painland, 0 17lands decks).  FIRST U/B color-pair binding.
    #   * ``test_razortrap_gorge_parity.py`` — Razortrap Gorge ({B}{R}
    #     painland, 0 17lands decks).  FIRST B/R color-pair binding.
    #   * ``test_strangled_cemetery_parity.py`` — Strangled Cemetery
    #     ({B}{G} painland, 0 17lands decks).  FIRST B/G color-pair
    #     binding AND closes the audit-recovered-10th-member of the
    #     Duskmourn painland cycle per the predicate docstring at
    #     ``trajectory.py:8226-8228``.
    #
    # Pure measurement-attribution + per-slug credit: no engine
    # changes, no Rust changes, no substrate widens.  Net delta:
    # +5 PROBED / -5 covered_by_construction: PROBED 357 → 362;
    # covered_by_construction 60 → 55; BLOCKED unchanged at 58; pool
    # total 475 unchanged.
    REPO_ROOT / "tests" / "test_abandoned_campground_parity.py",
    REPO_ROOT / "tests" / "test_bleeding_woods_parity.py",
    REPO_ROOT / "tests" / "test_murky_sewer_parity.py",
    REPO_ROOT / "tests" / "test_razortrap_gorge_parity.py",
    REPO_ROOT / "tests" / "test_strangled_cemetery_parity.py",
    # **covered-by-construction-probe-writing-p10 (2026-05-25):** Five
    # per-card real-EoE cross-engine byte-equal probes binding the
    # REMAINING five Duskmourn conditional-painland cycle slugs to
    # PROBED-tier slots, **closing the 10-member painland cycle** that
    # batch-9 opened.  The five new color-pair bindings (one DISTINCT
    # pair per probe; all five pairs were uncovered by batch-9):
    #
    #   * ``test_etched_cornfield_parity.py`` — Etched Cornfield
    #     ({G}{W} painland, 0 17lands decks).  FIRST G/W color-pair
    #     binding.
    #   * ``test_lakeside_shack_parity.py`` — Lakeside Shack
    #     ({G}{U} painland, 0 17lands decks).  FIRST G/U color-pair
    #     binding.
    #   * ``test_neglected_manor_parity.py`` — Neglected Manor
    #     ({W}{B} painland, 0 17lands decks).  FIRST W/B color-pair
    #     binding.
    #   * ``test_peculiar_lighthouse_parity.py`` — Peculiar Lighthouse
    #     ({U}{R} painland, 0 17lands decks).  FIRST U/R color-pair
    #     binding.
    #   * ``test_raucous_carnival_parity.py`` — Raucous Carnival
    #     ({W}{R} painland, 0 17lands decks).  FIRST W/R color-pair
    #     binding AND closes the cycle (all 10 dual-color painland
    #     slugs now have dedicated per-slug PROBED-tier probes).
    #
    # Same lane discipline as batches 1-9: per-slug attribution credits
    # a PROBED slot per-printing via the module-scope
    # ``_PRINTINGS = get_active_source().get_printings()`` idiom (the
    # ``_probe_module_probed_cards_via_module_scope_binding`` widen
    # accepts it).  Pure measurement-attribution + per-slug credit: no
    # engine changes, no Rust changes, no substrate widens.  Net delta:
    # +5 PROBED / -5 covered_by_construction: PROBED 362 → 367;
    # covered_by_construction 55 → 50; BLOCKED unchanged at 58; pool
    # total 475 unchanged.
    REPO_ROOT / "tests" / "test_etched_cornfield_parity.py",
    REPO_ROOT / "tests" / "test_lakeside_shack_parity.py",
    REPO_ROOT / "tests" / "test_neglected_manor_parity.py",
    REPO_ROOT / "tests" / "test_peculiar_lighthouse_parity.py",
    REPO_ROOT / "tests" / "test_raucous_carnival_parity.py",
    # **covered-by-construction-probe-writing-p11 (2026-05-25):** Five
    # per-card real-EoE cross-engine byte-equal probes binding the EoE-
    # pool Foundations (FDN) verge-land enemy-color cycle (5 enemy-pair
    # verges; the 5 ally-pair verges are not in the EoE merged pool).
    # The five new color-pair bindings (one DISTINCT pair per probe;
    # **distinct shape sub-axis** from the batch 9 + 10 Duskmourn-
    # painland cycle):
    #
    #   * ``test_blazemire_verge_parity.py`` — Blazemire Verge ({B}{R}
    #     verge, 0 17lands decks).  FIRST B/R color-pair binding on the
    #     parser-emitted-dual-AA sub-shape (Razortrap Gorge ALSO pinned
    #     B/R but on the bridge-auto-wire painland sub-shape — the
    #     orthogonal AA-materialization axis).
    #   * ``test_floodfarm_verge_parity.py`` — Floodfarm Verge ({W}{U}
    #     verge, 0 17lands decks).  FIRST W/U color-pair on the
    #     parser-emit sub-shape (Abandoned Campground pinned W/U on the
    #     painland bridge-auto-wire sub-shape).
    #   * ``test_gloomlake_verge_parity.py`` — Gloomlake Verge ({U}{B}
    #     verge, 0 17lands decks).  FIRST U/B color-pair on the
    #     parser-emit sub-shape (Murky Sewer pinned U/B on the painland
    #     bridge-auto-wire sub-shape).
    #   * ``test_hushwood_verge_parity.py`` — Hushwood Verge ({W}{G}
    #     verge, 0 17lands decks).  FIRST W/G color-pair on EITHER
    #     sub-shape (no W/G painland in batch-9 / batch-10 — Etched
    #     Cornfield was G/W on the painland sub-shape; W/G and G/W are
    #     the same frozenset so this is a per-slug-attribution slot,
    #     not a NEW color-pair).
    #   * ``test_thornspire_verge_parity.py`` — Thornspire Verge
    #     ({G}{R} verge, 0 17lands decks).  FIRST G/R color-pair on the
    #     parser-emit sub-shape (Bleeding Woods pinned G/R on the
    #     painland bridge-auto-wire sub-shape) AND **closes the EoE-
    #     pool FDN-verge enemy-color cycle** (all 5 enemy-pair verges
    #     in the EoE merged pool now have dedicated per-slug PROBED-
    #     tier probes).
    #
    # **Shape-axis distinction from the painland cycle.** The Duskmourn
    # painland probes (batches 9 + 10) go through ``_card_def_to_python_
    # printing``'s bridge auto-wire path: the parser emits ZERO AAs on
    # the live painland printing (the conditional gate is on the
    # ``enters_tapped_unless_any_player_life_at_most`` threshold field
    # instead), and ``_card_def_to_python_printing`` synthesizes one
    # ``ActivatedAbility(AddManaToPool({c}, 1))`` per produce-color via
    # ``cross_engine.py``:14073-14081's auto-wire.  The FDN verges in
    # this batch invert that path: the parser emits the TWO AAs on the
    # live printing directly, the ``_printing_is_bridge_nonbasic_mana_
    # land`` predicate REJECTS on the ``printing.activated_abilities``
    # non-emptiness check (the parser-emit path is §2-declined at the
    # admit gate today — no substrate widen here), so the bridge round-
    # trip pin operates at the per-Effect-dict level via ``_ta_dict_to_
    # python_effect`` rather than the per-CardDef level via
    # ``_card_def_to_python_printing``.  This is the SAME bridge
    # contract the painland sibling probes' (2) Bridge round-trip
    # section exercises — the painland probes verify the bridge-auto-
    # wired AAs are byte-equal to ``_ta_dict_to_python_effect``-bridged
    # AAs.  The verge probes go straight to the parser-emit byte-
    # equality assertion (skipping the CardDef intermediate).
    #
    # Same lane discipline as batches 1-10: per-slug attribution credits
    # a PROBED slot per-printing via the module-scope
    # ``_PRINTINGS = get_active_source().get_printings()`` idiom (the
    # ``_probe_module_probed_cards_via_module_scope_binding`` widen
    # accepts it).  Pure measurement-attribution + per-slug credit: no
    # engine changes, no Rust changes, no substrate widens.  Net delta:
    # +5 PROBED / -5 covered_by_construction: PROBED 367 → 372;
    # covered_by_construction 50 → 45; BLOCKED unchanged at 58; pool
    # total 475 unchanged.
    REPO_ROOT / "tests" / "test_blazemire_verge_parity.py",
    REPO_ROOT / "tests" / "test_floodfarm_verge_parity.py",
    REPO_ROOT / "tests" / "test_gloomlake_verge_parity.py",
    REPO_ROOT / "tests" / "test_hushwood_verge_parity.py",
    REPO_ROOT / "tests" / "test_thornspire_verge_parity.py",
    # **covered-by-construction-probe-writing-p12 (2026-05-25):** Five
    # per-card real-EoE cross-engine byte-equal probes binding the
    # **bare-bridge-clean** sub-shape — the cards whose parser-emitted
    # Effects round-trip BYTE-EQUAL through the bridge arms (the Mutavault
    # bare-riders precedent + the FFFF EEEE-idiom for unit-variant /
    # bare-fielded Effect classes).  Five distinct slugs / per-slug
    # attribution slots:
    #
    #   * ``test_conductive_machete_parity.py`` — Conductive Machete
    #     ({4} Artifact - Equipment, 0 17lands decks).  FIRST PROBE_
    #     MODULES-credited probe binding the
    #     ``ManifestDreadThenAttachSelf`` Effect class to a real-EoE
    #     slug (the Duskmourn-Equipment-ETB-manifest-dread family);
    #     ALSO binds the Equip AA half via the same
    #     ``EquipToTargetCreatureYouControl`` bridge arm Squire's
    #     Lightblade exercises.
    #   * ``test_killers_mask_parity.py`` — Killer's Mask ({2}{B}
    #     Artifact - Equipment, 0 17lands decks).  Per-slug
    #     attribution slot on the same two-effect shape; distinct from
    #     Conductive Machete on the **{2}{B}** printing-mana color
    #     slot + **Equip{2}** cost.
    #   * ``test_cursed_windbreaker_parity.py`` — Cursed Windbreaker
    #     ({2}{U} Artifact - Equipment, 0 17lands decks).  Closes the
    #     3-member Duskmourn-Equipment-ETB-manifest-dread cycle in
    #     the EoE merged pool; distinct on the **{2}{U}** color slot
    #     + **Equip{3}** cost (the {2}/{3}/{4} cost ladder closes).
    #   * ``test_ripchain_razorkin_parity.py`` — Ripchain Razorkin
    #     ({3}{R} Creature - Human Berserker, 0 17lands decks).  FIRST
    #     PROBE_MODULES-credited probe binding the bare ``DrawCards
    #     (amount=1)`` Effect class on a real-EoE ACTIVATED-ABILITY
    #     carrier (prior DrawCards probes pin the class on TA /
    #     spell-effect carriers — Demonic Counsel's search-then-draw
    #     composite, Decode Transmissions' instant — but none drive
    #     the bare primitive via an AA).
    #   * ``test_irreverent_gremlin_parity.py`` — Irreverent Gremlin
    #     ({1}{R} Creature - Gremlin, 0 17lands decks).  FIRST PROBE_
    #     MODULES-credited probe exercising the canonical
    #     ``IfYouDo(MayDo(X), Y)`` looter recursive composite end-to-
    #     end on a real-EoE printing — pins the 4-deep bridge
    #     composition ``if_you_do`` → ``may_do`` → ``discard_self`` +
    #     ``draw_cards`` byte-equal round-trip.
    #
    # **Shape-axis distinction from the verge cycle (batch 11).**  The
    # verge probes exercise the ``add_mana_to_pool`` per-color bridge
    # arm on parser-emitted-dual-AA Land carriers.  This batch exercises
    # FOUR ORTHOGONAL Effect classes: ``EquipToTargetCreatureYouControl``,
    # ``ManifestDreadThenAttachSelf``, ``DrawCards``, and the 3-arm
    # recursive composite ``IfYouDo(MayDo(DiscardSelf), DrawCards)`` —
    # the four leaf-level + composer-level bridge arms exercised
    # simultaneously.  All five cards SHARE the
    # **bridge-byte-equal-Effect** discipline: bridge round-trip
    # produces an Effect bit-identical to the parser-emitted one (no
    # rider-drop narrowing; the per-Mutavault-precedent bare-fielded
    # contract).  Cards in the covered_by_construction tier whose
    # Effects carry bridge-drop riders (granted_keywords on
    # PumpSelfUntilEOT / PumpTargetCreatureUntilEOT; spend_restriction
    # on AddManaToPool for Power Depot / Steelswarm Operator;
    # nonbasic_only on Dust Bowl's DestroyTargetLand;
    # granted_keywords/unblockable/granted_subtype on the remaining
    # manlands' BecomeLandCreatureUEOT; min_power /
    # tapped_only/untapped_only on the wrath variants) STAY covered_
    # by_construction under the IIII / HHHH "covered carrier with
    # non-bridge-clean rider" precedent until either a Rust schema
    # widen or per-card slice ships.
    #
    # Same lane discipline as batches 1-11: per-slug attribution credits
    # a PROBED slot per-printing via the module-scope
    # ``_PRINTINGS = get_active_source().get_printings()`` idiom (the
    # ``_probe_module_probed_cards_via_module_scope_binding`` widen
    # accepts it).  Pure measurement-attribution + per-slug credit: no
    # engine changes, no Rust changes, no substrate widens.  Net delta
    # for this batch in isolation: +5 PROBED / -5 covered_by_
    # construction (relative to the batch-11 baseline).  Worker A's
    # cost-reduction Phase 2 cycle 3-4 probes (Uthros Psionicist + Sami,
    # Wildcat Captain — sha 809d546c + 4b683928) landed concurrently and
    # contribute +2 PROBED from the BLOCKED-SG tier, so the post-rebase
    # headline shows PROBED 372 → 379, covered_by_construction 45 → 40,
    # BLOCKED-SG 58 → 56, pool total 475 unchanged.
    REPO_ROOT / "tests" / "test_conductive_machete_parity.py",
    REPO_ROOT / "tests" / "test_killers_mask_parity.py",
    REPO_ROOT / "tests" / "test_cursed_windbreaker_parity.py",
    REPO_ROOT / "tests" / "test_ripchain_razorkin_parity.py",
    REPO_ROOT / "tests" / "test_irreverent_gremlin_parity.py",
    # **covered-by-construction-probe-writing-p13 (2026-05-25):** Two
    # per-card real-EoE cross-engine byte-equal probes binding the
    # **bare-bridge-clean** sub-shape on the LAST two cards in the
    # 40-card ``covered_by_construction`` tier with verifiable
    # parser-emit ↔ bridge round-trip byte-equality.  Marks the
    # **saturation** of the bare-bridge-clean Effect-class lane this
    # multi-batch campaign rode (batches 1-12 flipped ~60 cards via
    # this idiom).  The remaining 38 covered_by_construction cards
    # all carry bridge-drop riders (granted_keywords on Pump arms;
    # BecomeLandCreatureUEOT (substrate-blocked per HH directive);
    # spend_restriction on AddManaToPool; nonbasic_only narrowing on
    # DestroyTargetLand; tapped_only / untapped_only / min_power
    # narrowing on DestroyAllCreatures; multi-color batched
    # AddManaToPool; ConditionalOnTappedCreatures CreateToken with
    # tapped=True rider; create_token bridge-arm with
    # register_token_printing ceremony scoped-out per JJJJ; et al.).
    # Per-card scout results documented in
    # ``docs/COVERED_BY_CONSTRUCTION_PROBE_WRITING_SATURATION_2026-05-25.md``.
    #
    #   * ``test_plaza_of_heroes_parity.py`` — Plaza of Heroes (Land,
    #     Stellar Sights reprint, 0 17lands decks).  Binds AA[0]'s
    #     bare ``AddManaToPool(produces=(('C', 1),), spend_restriction
    #     =None)`` colorless-mana ability — the bridge-clean half of
    #     a four-AA carrier (AA[1]/[2] have spend_restriction riders;
    #     AA[3] has granted_keywords pump — bridge-drop riders, but
    #     the per-slug attribution flips the WHOLE slug via AA[0]'s
    #     byte-equal round-trip).  Sibling to Mana Confluence (PROBED
    #     'any' coin) and Cascading Cataracts (PROBED {5} 'any-5'
    #     coin); pins the additional ``'C'`` (colorless) dispatch
    #     surface on the round-27 ``add_mana_to_pool`` bridge arm.
    #   * ``test_rust_harvester_parity.py`` — Rust Harvester ({R}
    #     Artifact Creature — Robot, 0 17lands decks).  Binds AA[0]'s
    #     2-arm composite ``Sequence(PutPlusOneCounterOnSelf(amount=1),
    #     DealDamageEqualToSourcePowerAnyTarget)``.  The activation
    #     cost carries the HH-blocked ``exile_artifact_from_graveyard``
    #     rider — the EEEE-idiom (parse + bridge round-trip + Python-
    #     side resolve, NO cross-engine compare_fields) sidesteps the
    #     cost surface entirely by exercising the EFFECT half
    #     directly.  Exercises THREE bridge arms simultaneously
    #     (``sequence`` composer + ``put_plus_one_counter_on_self``
    #     leaf 0 + ``deal_damage_equal_to_source_power_any_target``
    #     leaf 1) — load-bearing for the
    #     ``DealDamageEqualToSourcePowerAnyTarget`` Effect class on a
    #     real-EoE ACTIVATED-ABILITY carrier.
    #
    # Same lane discipline as batches 1-12: per-slug attribution
    # credits a PROBED slot per-printing via the module-scope
    # ``_PRINTINGS = get_active_source().get_printings()`` idiom (the
    # ``_probe_module_probed_cards_via_module_scope_binding`` widen
    # accepts it).  Pure measurement-attribution + per-slug credit:
    # no engine changes, no Rust changes, no substrate widens.  Net
    # delta: +2 PROBED / -2 covered_by_construction (PROBED 379 →
    # 381; covered_by_construction 40 → 38; BLOCKED-SG 56 unchanged;
    # pool total 475 unchanged).
    #
    # **Lane saturation.**  This batch ships the LAST two bare-
    # bridge-clean cards under the established per-slug-attribution
    # idiom.  Subsequent batches must either (a) attack the
    # bridge-drop-rider sub-shapes via Rust schema bumps + sibling
    # bridge arms (e.g., spend_restriction tagging, granted_keywords
    # on pump arms, BecomeLandCreatureUEOT) or (b) pivot to other
    # major DEFERRED rows (Aura Phase 3+ substrate widening at 3
    # cards / 2,783 decks; Carrier-AA substrate widening at 30
    # cards / 34,470 decks; Spacecraft Station subsystem at 8 cards
    # / 41,281 decks; et al.).  Recommended next direction:
    # **Carrier-AA substrate widening** — the largest 1-gate +
    # multi-gate pool in BLOCKED-SG (30 cards, 34,470 decks; highest
    # deck-count leverage among the un-itemised sprawling
    # subsystems).
    REPO_ROOT / "tests" / "test_plaza_of_heroes_parity.py",
    REPO_ROOT / "tests" / "test_rust_harvester_parity.py",
    # Carrier-AA substrate Phase 1 Cycle 3 (2026-05-25) — Swarmyard
    # real-EoE per-card cross-engine byte-equality probe. Closes the
    # ``covered_by_construction`` → PROBED tier flip for Swarmyard
    # (the FIRST PROBE_MODULES-credited probe of the
    # ``RegenerateTargetCreature`` Effect class with the
    # ``allowed_subtypes={Insect, Rat, Spider, Squirrel}`` filter +
    # the SBA-time ``regeneration_shield`` consume + cleanup-step
    # reset closure for the C1 SL entry's "no zone-change reset"
    # failure-mode). The probe drives both engines through two
    # scenarios: (a) carrier-in-play baseline (cleanup drains the
    # unconsumed shield byte-equal) and (b) regenerate-the-attacker
    # SBA-consume (the consume path replaces the destroy byte-equal).
    # See ``docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md`` §2.3 / §7.3 /
    # §10.3 for the campaign context + sibling-swap rationale.
    REPO_ROOT / "tests" / "test_swarmyard_parity.py",
    # **Carrier-AA substrate Phase 1.5a (2026-05-25):** Per-card real-
    # EoE byte-equal probe binding Deserted Temple to the Phase-1.5a
    # widened Carrier-AA admit gate. Phase 1.5a (see
    # ``docs/CARRIER_AA_SUBSTRATE_PHASE_1_5_DESIGN.md`` §2/§5) widens
    # ``_aa_is_phase1_sub_shape_a``'s cost gate from STRICT bare-``{T}``
    # to bare-``{T}`` OR ``{N}, {T}`` (generic-only mana). Deserted
    # Temple was the Phase-1 honest-stop on the cost gate; Phase 1.5a
    # admits it immediately on the gate-widen alone — the
    # ``UntapTargetLand`` Effect was already in the Phase-1 admit set
    # (``226c9738`` C1 substrate). ZERO Rust changes (Rust already
    # routes generic mana for AAs via the ``_python_aa_to_safe_dict``
    # round-trip).
    #
    #   * ``test_deserted_temple_parity.py`` — Deserted Temple ({0}
    #     Land); single AA (``{1}, {T}: Untap target land.``) →
    #     ``UntapTargetLand()`` (unit-variant Effect). The FIRST
    #     PROBE_MODULES-credited probe of ``UntapTargetLand`` on a
    #     real-EoE Land + AA carrier; templates on the sibling
    #     Carrier-AA AA probes (parse + bridge round-trip + Rust
    #     synthetic acceptance + end-to-end loader admit + Python-side
    #     resolve smoke covering both the baseline silent-fizzle line
    #     and the load-bearing untap-a-tapped-Forest line).
    #
    # Net delta: +1 PROBED / -1 covered_by_construction. Carrier-AA
    # BLOCKED-SG row: 30 → 28 cards (combined with the parallel C3
    # Swarmyard probe). Sibling-candidate cards (Terrain Generator,
    # Thespian's Stage, Mystifying Maze) stay honestly DECLINED at
    # the Phase-1 Effect-class admit set
    # ``{RegenerateTargetCreature, UntapTargetLand}`` — the
    # no-silent-auto-grow walk pin in
    # ``test_carrier_aa_phase_1_substrate_cycle_2.py`` codifies the
    # exact +2 admit set. Phase 1.5b (CONDITIONAL) would add Terrain
    # Generator via a Rust ``PutBasicLandFromHandOntoBattlefieldTapped``
    # Effect port.
    REPO_ROOT / "tests" / "test_deserted_temple_parity.py",
    # **Carrier-AA substrate Phase 2a Cycle 2 (2026-05-25):** Per-card
    # real-EoE byte-equal probe binding Petrified Field to the
    # Phase-2a widened Carrier-AA admit gate. Phase 2a (see
    # ``docs/CARRIER_AA_SUBSTRATE_PHASE_2_DESIGN.md`` §2/§5) widens
    # ``_aa_is_phase1_sub_shape_a``'s cost gate from bare-``{T}`` /
    # ``{N}, {T}`` to additionally admit ``sacrifice_self=True`` AND
    # widens ``_carrier_aa_phase_1_effect_classes`` to include
    # ``ReturnTargetLandFromGraveyardToHand`` (the Phase 2a C1
    # substrate landed cross-engine at ``aca39437`` — new Rust
    # Effect variant + parse / resolve / to_pydict arms + cross-engine
    # bridge arms). Petrified Field admits at Phase 2a C2 on the
    # gate-widen + Effect-class widen alone — the cross-engine
    # substrate was already complete (C1 substrate-only landing).
    # ZERO new Rust cost-shape machinery (Lander's ``{N}, Sac:``
    # token-AA precedent already wired ``ActivationCost.sacrifice_
    # self`` parse + Phase 5b cost-pay commit at
    # ``state_ops_actions.rs:1300-1391``).
    #
    #   * ``test_petrified_field_parity.py`` — Petrified Field ({0}
    #     Land); single non-mana AA (``{T}, Sacrifice this land:
    #     Return target land card from your graveyard to your
    #     hand.``) → ``ReturnTargetLandFromGraveyardToHand()`` (unit-
    #     variant Effect, zero-arg frozen dataclass). The FIRST
    #     PROBE_MODULES-credited probe of
    #     ``ReturnTargetLandFromGraveyardToHand`` on a real-EoE Land +
    #     AA carrier; templates on the sibling Carrier-AA AA probes
    #     (parse + bridge round-trip + Rust synthetic acceptance +
    #     end-to-end loader admit + Python-side resolve smoke
    #     covering both the baseline empty-graveyard silent-fizzle
    #     line and the load-bearing return-a-Forest line).
    #
    # Net delta: +1 PROBED / -1 covered_by_construction. Carrier-AA
    # BLOCKED-SG row: 28 → 27 cards. Sibling-candidate cards (Terrain
    # Generator, Thespian's Stage, Mystifying Maze, Scavenger Grounds)
    # stay honestly DECLINED at the Phase-2a Effect-class admit set
    # + cost-shape gates — the no-silent-auto-grow walk pin
    # ``test_carrier_aa_30_no_silent_auto_grow_admit_set_swarmyard_
    # plus_deserted_temple_plus_petrified_field`` in
    # ``test_carrier_aa_phase_1_substrate_cycle_2.py`` codifies the
    # exact +3 admit set (Swarmyard + Deserted Temple + Petrified
    # Field). Phase 2b ships
    # ``PutBasicLandFromHandOntoBattlefieldTapped`` (Terrain
    # Generator).
    REPO_ROOT / "tests" / "test_petrified_field_parity.py",
    # **Spacecraft Station substrate Phase 1 Cycle 4 (2026-05-25):**
    # Per-card real-EoE byte-equal probe binding Galvanizing Sawship
    # — the SOLE Phase-1-admitted Spacecraft printing — through the
    # Phase-1-pilot Station substrate (the zero-ability Spacecraft
    # carrier with ``station_threshold=3`` +
    # ``stationed_keywords={flying, haste}``; 5,938 17lands decks
    # unblocked through the new dedicated admit predicate
    # :func:`_printing_is_bridge_pure_station_spacecraft`). Closes
    # the Spacecraft Phase 1 campaign (C1 substrate Part A ``ea9aa996``
    # + C2 substrate Part B ``62e10ff9`` + C3 Python bridge + FLIP
    # ``e9a31c83``) per design doc §6.3.
    #
    #   * ``test_galvanizing_sawship_parity.py`` — Galvanizing Sawship
    #     (``{5}{R}`` Artifact — Spacecraft, 6/5, station_threshold=3,
    #     stationed_keywords={flying, haste}); the FIRST PROBE_MODULES-
    #     credited probe binding the Spacecraft Station substrate +
    #     ``Action::ActivateStation`` resolver + ``is_creature_now``
    #     stationed-flip + ``battlefield_has_keyword`` stationed-fold.
    #     Drives BOTH engines through three scenarios across the
    #     charge-counter axis: (A) un-stationed baseline (charge=0;
    #     Sawship is NOT a creature; no legal attack), (B) partial-
    #     station (charge=1; 1 ActivateStation resolved; Sawship STILL
    #     NOT a creature; 1 < threshold=3), and (C) the LOAD-BEARING
    #     fully-stationed-and-attacking scenario (charge=3; 3
    #     ActivateStations resolved; Sawship IS a creature with
    #     flying+haste; IS a legal attacker per CR 311 + design
    #     doc §4.5/§4.6). Uses the scripted-picker shape design
    #     doc §6.3 mandates (explicit ``(spacecraft_id, crew_id)`` per
    #     activation via direct ``apply_action``; the bench's
    #     ``attack_all`` strategy would not produce "queue-three-
    #     ActivateStations-then-attack" organically). Each scenario
    #     asserts full ``compare_fields == []`` byte-equality across
    #     the whole field view on both engines.
    #
    # Net delta: +1 PROBED / -1 covered_by_construction. Spacecraft
    # Phase 1 COMPLETE: BLOCKED-SG Station/Spacecraft row drops
    # Sawship; the other 21 EoE Spacecraft printings stay honestly
    # DECLINED on the strict no-abilities admit predicate (the §6.4
    # decline-set bench check in
    # ``test_spacecraft_phase_1_cycle_3_flip.py`` pins this
    # exhaustively). Subsequent phases (Lumen-Class Frigate Phase 2,
    # 5 trigger carriers Phase 3, The Eternity Elevator Phase 4) are
    # scoped in the design doc §7 — ~16-22 cycles across the whole
    # campaign to close all 8 cards / 41,281 decks.
    REPO_ROOT / "tests" / "test_galvanizing_sawship_parity.py",
)

# Tier keys (stable — the doc + test reference these verbatim).
TIER_PROBED = "probed"
TIER_COVERED = "covered_by_construction"
TIER_ADMITTED = "bridge_admitted_bench_exercised"
TIER_BLOCKED_MISSING = "blocked_genuinely_missing"
TIER_BLOCKED_NON_EFFECT = "blocked_non_effect"
TIER_BLOCKED_SUBSYSTEM = "blocked_subsystem_gated"

_TIER_ORDER = (
    TIER_PROBED,
    TIER_COVERED,
    TIER_ADMITTED,
    TIER_BLOCKED_MISSING,
    TIER_BLOCKED_NON_EFFECT,
    TIER_BLOCKED_SUBSYSTEM,
)

_TIER_LABEL = {
    TIER_PROBED: "PROBED byte-equal",
    TIER_COVERED: "Effect+bridge covered (not individually probed)",
    TIER_ADMITTED: "bridge-admitted & bench-exercised",
    TIER_BLOCKED_MISSING: "BLOCKED — genuinely_missing (new-Rust-Effect ask)",
    TIER_BLOCKED_NON_EFFECT: "BLOCKED — blocked_non_effect (non-Effect gate)",
    TIER_BLOCKED_SUBSYSTEM: "BLOCKED — subsystem-gated / Effect-uncovered",
}


# ------------------------------------------------- reuse the coverage parser
#
# Round-66 covered-set extraction precursor: ``covered_python_class_set``
# and ``card_effect_classes`` were factored OUT of this script into the
# production-importable ``mtg_bot.parity.effect_coverage`` module so the
# spell-card-bridge Phase 1 guardrail
# (``trajectory._spell_effect_is_covered_and_bridged``) can query the
# live covered set without a ``scripts/`` import (a layering inversion).
# This script RE-EXPORTS them (unchanged names + signatures) so its own
# consumers (``tests/test_measure_pool_parity.py``, the two
# ``scout_r58`` / ``scout_r63`` scouts, the staleness cron) and the
# test's ``monkeypatch.setattr(mod, "covered_python_class_set", ...)``
# continue to work verbatim. Exactly ONE definition of "covered" — the
# §2-teeth requirement (the parse rule is NOT duplicated here).

if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
# Keep ``scripts/`` on ``sys.path`` for the lazy ``scout_r58`` /
# ``scout_r63`` imports below — previously ensured as a side effect of
# the now-removed ``_coverage_module()`` (it inserted ``SCRIPTS_DIR``);
# the scout breakout must keep rendering into ``docs/POOL_PARITY.md``
# exactly as before this refactor.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from mtg_bot.parity.effect_coverage import (  # noqa: E402,F401
    card_effect_classes,
    covered_python_class_set,
)


# ------------------------------------------------- genuine-probe inventory


def _slug(text: str) -> str:
    """snake_case slug used to match a probe function-name prefix to a
    printed card name. Lowercase, non-alphanumerics → ``_``, collapsed,
    trimmed. ``"Mechan Assembler"`` → ``mechan_assembler``;
    ``"Roaring Furnace // Steaming Sauna"`` is keyed on its LEFT face
    (``roaring_furnace``) since split-card probes name the left face."""
    primary = text.split(" // ")[0]
    return re.sub(r"[^a-z0-9]+", "_", primary.lower()).strip("_")


def _smoke_probed_cards(pool_names: set[str], smoke_path: Path) -> set[str]:
    """``tests/test_parity_smoke.py``'s slug-keyed detection (the
    ORIGINAL, unchanged rule — kept byte-for-byte so the 60 cards it
    already credits are unaffected).

    Detection: every ``def test_cross_engine_real_eoe_<mid>_parity``
    function in the smoke file; ``<mid>`` is matched against the slug
    of each pool card's printed name, longest slug first (so
    ``mechan_assembler`` wins over ``mechan``). Only ``*_parity``
    functions count — ``*_divergence_pin`` functions assert a KNOWN
    divergence, the opposite of byte-equality, and are deliberately
    excluded. Pure text; no engine import."""
    text = smoke_path.read_text(encoding="utf-8")
    fn_mids = re.findall(
        r"def test_cross_engine_real_eoe_(\w+?)_parity\(", text
    )
    # Longest-slug-first so a card whose slug is a prefix of another
    # card's slug doesn't steal the attribution.
    slug_to_name: dict[str, str] = {}
    for n in pool_names:
        slug_to_name.setdefault(_slug(n), n)
    ordered = sorted(slug_to_name, key=len, reverse=True)
    probed: set[str] = set()
    for mid in fn_mids:
        for sg in ordered:
            if mid == sg or mid.startswith(sg + "_"):
                probed.add(slug_to_name[sg])
                break
    return probed


# A ``*_parity`` probe function's GENUINE-card binding: the EoE pool
# printing it drives end-to-end is resolved via
# ``get_active_source().get_printings().get("<Card Name>")`` (or the
# ``[...]`` subscript form). That call — NOT the function-name spelling
# — is the load-bearing "this probe pins THAT card" assertion (the
# function name is only a human label; the batch authors elided
# apostrophes in some names, e.g. ``samis_curiosity`` for
# ``"Sami's Curiosity"``, so a slug-of-the-function-name match would
# silently UNDERCOUNT). We anchor on the genuine binding instead, the
# same thing ``measure_effect_coverage``/``card_effect_classes`` treat
# as authoritative. The name capture tolerates an embedded apostrophe
# (double-quoted Python string) and surrounding whitespace/newlines.
#
# The quoted-string capture must be quote-style aware: a card name
# carries an apostrophe (``"Sami's Curiosity"``,
# ``"Mm'menon, Uthros Exile"``) which a naive ``["']([^"']+)["']``
# would truncate at the embedded ``'`` — the precise bug that made the
# slug rule undercount these. Match a double-quoted string whose body
# may contain ``'`` OR a single-quoted string whose body may contain
# ``"`` (no card name needs an escaped same-style quote). ``\s*`` /
# ``re.DOTALL`` tolerate the multi-line ``.get(\n    "Name"\n)`` form.
_PROBE_GET_PRINTING_RE = re.compile(
    r"get_printings\(\)\s*(?:\.\s*get\s*\(|\[)\s*"
    r"""(?:"([^"]+)"|'([^']+)')""",
    re.DOTALL,
)
# A genuine probe is a TOP-LEVEL (column-0) function whose name starts
# ``test_cross_engine_real_eoe_`` and ends ``_parity``. Anchoring at
# column 0 (``^def`` / ``re.MULTILINE``) means the body is bounded by
# the NEXT column-0 ``def``/``class``/``@`` (or EOF) — so a
# ``*_divergence_pin`` function, a module-level binding, or a helper
# AFTER the last ``*_parity`` function is correctly OUTSIDE every
# credited body (the integrity guard the companion test pins).
_PROBE_FN_HEADER_RE = re.compile(
    r"^def (test_cross_engine_real_eoe_\w+?_parity)\(", re.MULTILINE
)
# A new top-level construct ends the preceding function body.
_TOP_LEVEL_BOUNDARY_RE = re.compile(
    r"^(?:def |class |@|[A-Za-z_])", re.MULTILINE
)


def _probe_module_probed_cards(
    pool_names: set[str], module_path: Path
) -> set[str]:
    """The genuine-real-EoE PROBED cards a dedicated probe module
    (``tests/test_probe_covered_unprobed_*.py``) pins.

    Inclusion predicate (the SAME bar the 60 smoke-file PROBED cards
    meet — match it EXACTLY): a card ``C`` is credited iff the module
    contains a ``def test_cross_engine_real_eoe_<...>_parity`` function
    whose body resolves the GENUINE parsed printing via
    ``get_active_source().get_printings().get("C")`` (or ``[...]``),
    where ``"C"`` is an exact live EoE pool card name. These modules
    use the IDENTICAL idiom as the smoke-file probes (genuine parsed
    ``spell_effect`` / ``triggered_abilities`` on Python, a bridged
    synthetic carrier on Rust, ``compare_fields == []`` over the whole
    field view on a controlled real-EoE state) and the IDENTICAL
    ``..._parity`` naming convention; only the file differs. Functions
    NOT ending ``_parity`` (e.g. ``*_divergence_pin``, or a
    differently-named sweep) contribute nothing — same exclusion as the
    smoke file. A bound name that is not a live pool card (a synthetic
    stub / typo / negative-control fixture) is NOT credited — that is
    the integrity guard against over-counting. Pure text; no engine
    import (mirrors the smoke detector's contract).

    **Module-scope-binding widen (2026-05-24).** Some probe modules
    hoist the printings dict to module scope —
    ``_PRINTINGS = get_active_source().get_printings()`` at the top —
    and call ``_PRINTINGS.get("<Card>")`` inside the ``*_parity``
    function body. The body-scoped scan above never sees the
    ``get_printings()`` call directly (it lives outside the bounded
    function body), so a probe authored this way is silently
    undercounted. To close that gap WITHOUT loosening the bar, the
    helper now also AST-parses the module, detects every module-level
    assignment whose RHS is ``get_active_source().get_printings()`` (or
    bare ``get_printings()``), and credits any ``<bound>.get("<Card>")``
    / ``<bound>["<Card>"]`` reference inside a ``*_parity`` function
    body. A module-level binding to a SPECIFIC card
    (``_X = get_printings().get("Card")``) is NOT recognized as a
    printings-dict binding — only the bare ``get_printings()`` form is
    — so the integrity guard cases in
    ``test_probe_module_synthetic_nonprobe_is_not_counted`` (module-
    level ``_MODULE_LEVEL = get_printings().get("Gravkill")`` and a
    helper that returns ``get_printings().get("Plasma Bolt")`` —
    neither belongs to a credited ``*_parity`` body) all still
    correctly fail to be credited. Pure text + AST; no engine import.
    """
    if not module_path.exists():
        return set()
    text = module_path.read_text(encoding="utf-8")
    probed: set[str] = set()
    # ---- (1) original body-scoped scan: in-body get_printings().get("X").
    for hm in _PROBE_FN_HEADER_RE.finditer(text):
        # The body runs from just after the header line to the start of
        # the NEXT top-level construct (column-0 def/class/@/identifier)
        # or EOF — precisely bounding it to THIS one function.
        body_start = text.index("\n", hm.end()) + 1
        nb = _TOP_LEVEL_BOUNDARY_RE.search(text, body_start)
        body_end = nb.start() if nb else len(text)
        body = text[body_start:body_end]
        for dq, sq in _PROBE_GET_PRINTING_RE.findall(body):
            nm = dq or sq
            if nm in pool_names:
                probed.add(nm)
    # ---- (2) module-scope-binding widen: AST-walk the module to find
    # module-level bindings ``X = (get_active_source().)?get_printings()``,
    # then for each ``*_parity`` function body credit ``X.get("Card")``
    # / ``X["Card"]`` references where ``"Card"`` is a live pool name.
    probed |= _probe_module_probed_cards_via_module_scope_binding(
        pool_names, text
    )
    return probed


def _probe_module_probed_cards_via_module_scope_binding(
    pool_names: set[str], text: str
) -> set[str]:
    """Find ``*_parity`` cards credited via the module-level
    ``_PRINTINGS = get_active_source().get_printings()`` binding idiom.

    Walks the AST in two passes:

      1. Module body — record every ``Assign`` whose targets are
         ``Name`` nodes and whose RHS is ``get_active_source().
         get_printings()`` OR bare ``get_printings()``. The recorded
         names are the printings-dict bindings.
      2. Each top-level function whose name matches the
         ``test_cross_engine_real_eoe_<...>_parity`` shape — walk the
         body for ``<bound>.get("C")`` Call nodes and ``<bound>["C"]``
         Subscript nodes. ``"C"`` is credited iff it is in the live pool.

    A binding whose RHS is ``get_printings().get("X")`` (i.e. an already-
    resolved per-card extraction, not a printings-dict binding) is NOT
    recorded as a dict binding — this is the integrity guard test
    ``test_probe_module_synthetic_nonprobe_is_not_counted`` pins on
    case (4). Equally, a binding inside a function body (not at module
    scope) is NOT walked here — the body-scoped detector above already
    handles that case.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # Defensive: a probe module that does not parse cannot credit
        # anything (mirrors the never-block contract of the body
        # detector — return empty rather than raising).
        return set()
    # Pass 1: module-level printings-dict bindings.
    bindings: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not _is_printings_dict_call(node.value):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                bindings.add(target.id)
    if not bindings:
        return set()
    # Pass 2: every top-level ``*_parity`` function body — credit
    # ``<bound>.get("Card")`` and ``<bound>["Card"]`` references.
    probed: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _PROBE_FN_NAME_RE.match(node.name):
            continue
        for sub in ast.walk(node):
            nm = _extract_bound_card_lookup(sub, bindings)
            if nm is not None and nm in pool_names:
                probed.add(nm)
    return probed


def _is_printings_dict_call(node: ast.AST) -> bool:
    """``True`` iff ``node`` is exactly ``get_active_source().get_printings()``
    OR bare ``get_printings()`` — the printings-DICT binding shape. A
    chained ``.get("X")`` on the end disqualifies it (that is a per-card
    extraction, not a dict binding)."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        # Bare ``get_printings()`` call.
        if (
            isinstance(func, ast.Name)
            and func.id == "get_printings"
            and not node.args
            and not node.keywords
        ):
            return True
        return False
    # ``<receiver>.get_printings()`` form.
    if func.attr != "get_printings":
        return False
    if node.args or node.keywords:
        return False
    # ``<receiver>`` should be ``get_active_source()`` (the canonical
    # shape across the affected probe modules). A literal ``mod.
    # get_printings()`` on some other receiver is intentionally not
    # recognized — we want the same parser-of-truth surface the smoke +
    # body detectors anchor on.
    receiver = func.value
    if not isinstance(receiver, ast.Call):
        return False
    rfunc = receiver.func
    if not isinstance(rfunc, ast.Name):
        return False
    return (
        rfunc.id == "get_active_source"
        and not receiver.args
        and not receiver.keywords
    )


def _extract_bound_card_lookup(
    node: ast.AST, bindings: set[str]
) -> str | None:
    """If ``node`` is ``<bound>.get("Card")`` or ``<bound>["Card"]``
    where ``<bound>`` is one of the recorded module-level printings-
    dict bindings, return ``"Card"``; otherwise ``None``."""
    # ``<bound>.get("Card")`` — single positional string arg.
    if isinstance(node, ast.Call):
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and isinstance(func.value, ast.Name)
            and func.value.id in bindings
            and len(node.args) >= 1
            and not node.keywords
        ):
            arg0 = node.args[0]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                return arg0.value
        return None
    # ``<bound>["Card"]`` — Subscript with constant string slice.
    if isinstance(node, ast.Subscript):
        value = node.value
        if isinstance(value, ast.Name) and value.id in bindings:
            slc = node.slice
            if isinstance(slc, ast.Constant) and isinstance(slc.value, str):
                return slc.value
        return None
    return None


# ``*_parity`` function-name shape (the same predicate the body-scoped
# detector anchors on, in regex form for the AST function-name match —
# kept aligned with ``_PROBE_FN_HEADER_RE``).
_PROBE_FN_NAME_RE = re.compile(
    r"test_cross_engine_real_eoe_\w+?_parity\Z"
)


def genuine_probed_cards(
    pool_names: set[str],
    smoke_path: Path = SMOKE_TEST,
    probe_modules: tuple[Path, ...] = PROBE_MODULES,
) -> set[str]:
    """The set of EoE pool card names that have a genuine real-EoE
    cross-engine *parity* probe pinning them.

    UNION of two detectors at EXACTLY ONE inclusion bar:

      1. ``tests/test_parity_smoke.py`` — slug-keyed ``*_parity``
         function-name match (the original rule, unchanged: the 60
         cards it credits are byte-for-byte unaffected).
      2. the dedicated ``tests/test_probe_covered_unprobed_*.py`` batch
         modules — genuine-``get_printings()``-binding match inside
         each ``*_parity`` function (resolves the
         apostrophe-name-elision the slug rule would silently
         undercount). Same idiom, same naming convention, same
         strength bar (genuine parsed printing driven end-to-end,
         full ``compare_fields`` byte-equality on a controlled
         real-EoE state).

    A card need only meet the bar in EITHER source to be PROBED (set
    union). The honest-measurement-tooling fix: before this, only (1)
    was scanned, so PROBED understated real probe coverage by the
    batch-module cards. The integrity guard: a probe that binds a name
    which is not a live pool card (a synthetic stub) is NOT credited
    — the metric never over-counts."""
    probed = _smoke_probed_cards(pool_names, smoke_path)
    for mod_path in probe_modules:
        probed |= _probe_module_probed_cards(pool_names, mod_path)
    return probed


# ------------------------------------------------- residue worklist split


def residue_blocked_cards(
    path: Path = RESIDUE_WORKLIST,
) -> tuple[set[str], set[str]]:
    """Return ``(genuinely_missing_cards, blocked_non_effect_cards)``
    from the canonical residue worklist. ``closed`` entries are NOT
    blocked (they shipped + bridged) so they are excluded. Card names
    are taken verbatim from each entry's ``card`` field; entries whose
    ``card`` carries a parenthetical qualifier (e.g. the legacy
    duplicate row "Monoist Circuit-Feeder (legacy duplicate row)") are
    normalised to the bare printed name so the consistency cross-check
    keys on the real pool name."""
    import json

    if not path.exists():
        raise RuntimeError(
            f"residue worklist {path} is missing — it is the canonical "
            f"BLOCKED-RUST-EFFECT residue list this metric cross-checks "
            f"against; restore it."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    missing: set[str] = set()
    non_effect: set[str] = set()
    for e in data.get("entries", []):
        card = (e.get("card") or "").strip()
        if not card:
            continue
        # Strip a trailing " (qualifier)" so a legacy-duplicate /
        # annotated row still keys on the real printed name.
        card = re.sub(r"\s*\([^)]*\)\s*$", "", card).strip()
        st = e.get("status")
        if st == "genuinely_missing":
            missing.add(card)
        elif st == "blocked_non_effect":
            non_effect.add(card)
    return missing, non_effect


# ------------------------------------------------- loader admit predicate


def loader_admits(printing) -> bool:
    """True iff the production-deck loader admits this printing — the
    EXACT gate the bench corpus runs through. Mirrors all 17 disjuncts
    of ``trajectory._filter_deck_to_bridge_supported``'s admit gate:

    1. ``_printing_is_bridge_basic_land``
    2. ``_printing_is_bridge_nonbasic_mana_land``
    3. ``_printing_is_bridge_pure_warp_creature``
    4. ``_printing_is_bridge_pure_cost_reduction_creature``
    5. ``_printing_is_bridge_simple_creature``
    6. ``_printing_is_bridge_simple_spell``
    7. ``_printing_is_bridge_simple_aura``
    8. ``_printing_is_bridge_simple_static_anthem_creature``
    9. ``_printing_is_bridge_simple_uncounterable_creature``
   10. ``_printing_is_bridge_simple_static_self_conditional_creature``
   11. ``_printing_is_bridge_static_anthem_pt_conditional_warp_creature``
   12. ``_printing_is_bridge_simple_cast_restriction_enchantment``
   13. ``_printing_is_bridge_simple_enchantment`` — Weftwalking Cycle 2
       (2026-05-24) vanilla non-Creature Enchantment with safe-trigger
       ETB; sole admitted EoE consumer is Weftwalking (~3,680 17lands
       decks). Sibling to the cast-restriction-enchantment arm on the
       Enchantment-type axis with ``triggered_abilities`` half OPEN
       and ``restricts_noncreature_spells_to_one_per_turn`` OFF.
   14. ``_printing_is_bridge_simple_tapped_mana_land`` — non-basic
       land substrate phase 2 (round-85 N1; admits the 5 EoE Planet
       lands as untapped mono-color lands — the parser-flattened
       ``enters_tapped=True`` mono-color shape; the bridge drops
       ``enters_tapped`` on both engines; round-39 Ward / round-60
       shockland symmetric-drop precedent).
   15. ``_printing_is_bridge_keyword_colorless_tapped_mana_land`` —
       non-basic land substrate sub-shape E (Cathedral of War cycle 1,
       2026-05-23; admits Cathedral of War as an untapped colorless
       land — the parser-flattened ``produces=frozenset()`` +
       ``enters_tapped=True`` + ``keywords={'exalted'}`` shape; the
       CardDef synthesizes ``mana_produced=("C",)`` to re-add the
       parser-dropped ``{T}: Add {C}`` line on both engines, and the
       bridge drops ``enters_tapped`` + Exalted on both engines;
       round-60 shockland / round-85 Planet land symmetric-drop
       precedent extended to a keyword-bearing colorless land).
   16. ``_printing_is_bridge_nonbasic_painland_conditional`` — non-
       basic land substrate phase 2 painland conditional (2026-05-23).
   17. ``_printing_is_bridge_simple_carrier_aa_land`` — Carrier-AA
       substrate Phase 1.5a (2026-05-25); admits the bare ``{T}:
       <Phase-1-Effect>`` OR ``{N}, {T}: <Phase-1-Effect>`` single-AA
       Land profile — Swarmyard + Deserted Temple in the EoE pool
       post-Phase-1.5a. Phase-1 cycle 1+2 Rust substrate
       (``226c9738``) ships the ``CardDef.activated_abilities`` field +
       ``Effect::RegenerateTargetCreature`` / ``Effect::
       UntapTargetLand`` variants + ``GameObject.regeneration_shield``
       SBA-time consume + cleanup reset.

    Reused, not reimplemented, so the bench tier and the real bench can
    never disagree on what "admitted" means.

    **warp_cost Phase 3 (round-83, 2026-05-20):** the
    ``_printing_is_bridge_pure_warp_creature`` predicate is admit-arm 3.
    Phases 1+1.5+2 of the warp_cost substrate shipped the full warp
    lifecycle on both engines (CardDef warp fields + Rust
    ``CardPrinting.warp_cost`` + ``cast_creature_warp`` + the END-step
    exile sweep + the exile-recast + Timeline Culler's life-rider +
    graveyard-warp), and the production-deck loader at
    ``trajectory.py:5552`` already routes warp creatures through this
    predicate ahead of the plain simple-creature arm. Including it in
    ``loader_admits`` makes the metric tier-classifier see those
    admitted warp printings as bridge-admitted, closing the warp_cost
    Phase 3 measurement-attribution gap (the 3 single-gated warp cards
    — Red Tiger Mechan, Bygone Colossus, Timeline Culler — accounting
    for 15,436 17lands single-gate decks per the round-58 attribution
    scout).

    **Aura Phase 1 flash widening attribution close (2026-05-21):**
    the ``_printing_is_bridge_simple_aura`` predicate is admit-arm 6.
    The trajectory-side Phase 2 round-79 widen
    (``_AURA_SAFE_EXTRA_KEYWORDS = {"flash"}``) already lets the real
    loader admit Frantic Strength + Shardmage's Rescue end-to-end.

    **loader_admits attribution sweep (2026-05-21):** disjuncts 2 / 5 /
    7 / 8 / 9 — the remaining 5 of the real loader's 9 admit arms — are
    folded in here. Each closes a pure measurement-attribution gap (the
    real loader admits them; the metric helper was stale):

    * ``_printing_is_bridge_nonbasic_mana_land`` — the 5 EoE shocklands
      (Breeding Pool / Godless Shrine / Sacred Foundry / Stomping Ground
      / Watery Grave); 0-Effect, BLOCKED → COVERED post-widen, then
      PROBED via the round-60 shockland bench probe in
      ``tests/test_parity_smoke.py`` (see
      ``test_cross_engine_real_eoe_shockland_through_bench_parity``,
      renamed from
      ``test_r60_genuine_real_eoe_shockland_byte_equal_through_bench``
      by ``feature/cathedral-of-war-probe-rename-p1``).
    * ``_printing_is_bridge_simple_spell`` — the 7 EoE simple
      Instant/Sorcery cards (Biosynthic Burst / Depressurize /
      Diplomatic Relations / Focus Fire / Orbital Plunge / Radiant
      Strike / Seedship Impact); ALL already PROBED via existing
      ``_parity`` probes, so this widen is metric-truthfulness only
      (tier counts unchanged).
    * ``_printing_is_bridge_simple_static_anthem_creature`` — Tannuk,
      Steadfast Second; static-abilities Phase 1 round-79 substrate.
    * ``_printing_is_bridge_simple_uncounterable_creature`` — Frenzied
      Baloth; static-abilities Phase 2 round-80 substrate.
    * ``_printing_is_bridge_simple_static_self_conditional_creature`` —
      Brightspear Zealot / Cloudsculpt Technician / Gravblade Heavy /
      Mechan Shieldmate; static-abilities Phase 3/3.5 rounds 81/82.

    Each carrier has an existing engine-level byte-equal lifecycle
    pin (the canonical probes live in
    ``tests/test_static_layered_abilities_phase{1,2,3}.py`` and in this
    file's shockland bench probe); the ``_parity``-named delegators
    added alongside this widen credit the slug-keyed scanner so the
    cards move all the way to PROBED. Pattern follows the round-83
    warp_cost Phase 3 / round-84 Cosmogoyf idiom: thin delegators
    re-use existing byte-equal helpers, no duplicated probe logic, no
    engine changes.

    **post-flip attribution sweep (2026-05-25):** 3 more disjuncts —
    ``_printing_is_bridge_pure_cost_reduction_creature`` (cost-reduction
    Phase 1/2/3, 2026-05-24/25; admits 5 carriers: Gigastorm Titan,
    Lashwhip Predator, Uthros Psionicist, Sami Wildcat Captain,
    Fungal Colossus),
    ``_printing_is_bridge_simple_enchantment`` (Weftwalking Cycle 2,
    2026-05-24; admits Weftwalking — vanilla non-Creature Enchantment
    with safe-trigger ETB), and
    ``_printing_is_bridge_simple_carrier_aa_land`` (Carrier-AA
    substrate Phase 1.5a, 2026-05-25; admits Swarmyard + Deserted
    Temple) — were folded in here, closing the helper-vs-canonical
    drift today's substrate landings introduced. All 7 cards are
    already PROBED via dedicated per-card probes, so this widen is
    pure metric-truthfulness (tier counts unchanged). The helper now
    mirrors all 17 canonical disjuncts in
    ``trajectory._filter_deck_to_bridge_supported``."""
    from mtg_bot.parity import trajectory as traj

    try:
        return bool(
            traj._printing_is_bridge_basic_land(printing)
            or traj._printing_is_bridge_nonbasic_mana_land(printing)
            or traj._printing_is_bridge_pure_warp_creature(printing)
            # **cost-reduction substrate Phase 1 Cycle 2 (2026-05-24) +
            # Phase 2 Cycle 2 (2026-05-25) + Phase 3 Cycle 2 (2026-05-25).
            # Mirrors the real loader's admit arm in
            # ``_filter_deck_to_bridge_supported``. Admits the 5
            # cost-reduction carriers (Gigastorm Titan, Lashwhip Predator,
            # Uthros Psionicist, Sami Wildcat Captain, Fungal Colossus —
            # ~53,648 17lands decks total). All 5 already PROBED via
            # dedicated per-card probes; this fold is pure
            # metric-truthfulness (tier counts unchanged).
            or traj._printing_is_bridge_pure_cost_reduction_creature(
                printing,
            )
            or traj._printing_is_bridge_simple_creature(printing)
            or traj._printing_is_bridge_simple_spell(printing)
            or traj._printing_is_bridge_simple_aura(printing)
            or traj._printing_is_bridge_simple_static_anthem_creature(
                printing,
            )
            or traj._printing_is_bridge_simple_uncounterable_creature(
                printing,
            )
            or traj._printing_is_bridge_simple_static_self_conditional_creature(
                printing,
            )
            # Static / layered abilities substrate — Phase 4 (Memorial
            # Team Leader Cycle 2 flip, 2026-05-24). Mirrors the real
            # loader's new admit arm in
            # ``_filter_deck_to_bridge_supported``. Memorial Team Leader
            # (~6,229 17lands decks) is the sole live-pool carrier;
            # flips BLOCKED → PROBED via the Cycle 2 admit-set widen +
            # the dedicated per-card real-EoE warp-cast-then-anthem
            # lifecycle probe in
            # ``tests/test_memorial_team_leader_parity.py``. No silent
            # auto-grows — single-card single-cycle FLIP.
            or traj._printing_is_bridge_static_anthem_pt_conditional_warp_creature(
                printing,
            )
            # Static rule-text substrate — Deafening Silence Cycle 1
            # (2026-05-22). Mirrors the real loader's new admit arm
            # in ``_filter_deck_to_bridge_supported``. Deafening
            # Silence (12 17lands decks) flips from BLOCKED →
            # COVERED here (0-Effect, admit-arm fires); the cross-
            # engine bridge round-trip + the parity probe move it
            # to PROBED via the existing slug-keyed scanner pattern.
            or traj._printing_is_bridge_simple_cast_restriction_enchantment(
                printing,
            )
            # **Weftwalking Cycle 2 (2026-05-24).** Mirrors the real
            # loader's admit arm in ``_filter_deck_to_bridge_supported``.
            # Vanilla non-Creature Enchantment whose every ETB
            # triggered_ability round-trips through the safe-trigger
            # recognizer; sole admitted EoE consumer is Weftwalking
            # (~3,680 17lands decks — already PROBED via
            # ``tests/test_weftwalking_parity.py``). Sibling to the
            # cast-restriction-enchantment arm above on the
            # Enchantment-type axis: triggered_abilities half OPEN
            # (every entry must round-trip the safe-trigger recognizer)
            # and ``restricts_noncreature_spells_to_one_per_turn`` OFF.
            # The two arms are mutually exclusive by construction.
            or traj._printing_is_bridge_simple_enchantment(
                printing,
            )
            # Non-basic land substrate — phase 2 (round-85 N1): the
            # 10th admit arm of the real loader; mirrors
            # ``_filter_deck_to_bridge_supported``. The 5 EoE Planet
            # lands (Adagia / Evendo / Kavaron / Susur Secundi /
            # Uthros) flip from BLOCKED -> COVERED here (0-Effect,
            # admit-arm fires, ``not eff_classes and admitted`` arm
            # of ``covered_ok``), and the 5 ``_parity``-named
            # delegators added to ``tests/test_parity_smoke.py`` in
            # the companion lane move them all the way to PROBED via
            # the slug-keyed ``_smoke_probed_cards`` scanner.
            or traj._printing_is_bridge_simple_tapped_mana_land(printing)
            # Non-basic land substrate — sub-shape E (Cathedral of War
            # cycle 1, 2026-05-23): the 11th admit arm of the real
            # loader; mirrors ``_filter_deck_to_bridge_supported``.
            # Cathedral of War (1,205 17lands decks) flips from BLOCKED
            # -> COVERED here (0-Effect, admit-arm fires, ``not
            # eff_classes and admitted`` arm of ``covered_ok``); the
            # dedicated per-card bench probe in
            # ``tests/test_cathedral_of_war_parity.py`` moves it to
            # PROBED.
            or traj._printing_is_bridge_keyword_colorless_tapped_mana_land(
                printing,
            )
            # Non-basic land substrate — phase 2 painland conditional
            # (2026-05-23). Mirrors the real loader's new admit arm
            # in ``_filter_deck_to_bridge_supported``. The 9 Duskmourn
            # painlands (Abandoned Campground / Bleeding Woods /
            # Etched Cornfield / Lakeside Shack / Murky Sewer /
            # Neglected Manor / Peculiar Lighthouse / Raucous Carnival
            # / Razortrap Gorge) flip from BLOCKED -> COVERED here
            # (0-Effect, admit-arm fires) plus Strangled Cemetery as
            # the 10th cycle member the round-59 audit missed. 0 EoE
            # bench signal (all are off-set DSK cards).
            or traj._printing_is_bridge_nonbasic_painland_conditional(
                printing,
            )
            # **Carrier-AA substrate Phase 1.5a (2026-05-25).** Mirrors
            # the real loader's admit arm in
            # ``_filter_deck_to_bridge_supported``. Admits the bare
            # ``{T}: <Phase-1-Effect>`` OR ``{N}, {T}: <Phase-1-Effect>``
            # single-AA Land profile — Swarmyard + Deserted Temple in
            # the EoE pool post-Phase-1.5a. Both already PROBED via
            # dedicated per-card probes
            # (``tests/test_swarmyard_parity.py`` +
            # ``tests/test_deserted_temple_parity.py``); this fold is
            # pure metric-truthfulness (tier counts unchanged).
            or traj._printing_is_bridge_simple_carrier_aa_land(printing)
            # **Spacecraft Station substrate Phase 1 Cycle 3
            # (2026-05-25).** Mirrors the real loader's new admit arm
            # in ``_filter_deck_to_bridge_supported``. Admits exactly
            # Galvanizing Sawship in the EoE pool — the sole single-
            # gated AND zero-ability Spacecraft per the verify-first
            # walk against the 22-Spacecraft live set. Per-card
            # real-EoE probe is Cycle 4 deliverable
            # (Scenarios A/B/C across the charge-counter axis per
            # ``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_1_DESIGN.md``
            # §6.3); this fold lifts the metric from ADMITTED to
            # COVERED-by-construction post-FLIP.
            or traj._printing_is_bridge_pure_station_spacecraft(printing)
        )
    except Exception:
        return False


# ------------------------------------------------- the classifier


@dataclass
class PoolParityResult:
    n_pool: int
    tiers: dict[str, list[str]]
    # Internal-consistency violations: a residue `genuinely_missing`
    # card the class-granularity heuristic WOULD have counted as
    # covered/probed. The worklist's per-card re-walk is the authority
    # on genuine absence (it sees riders the class heuristic can't —
    # e.g. `DestroyTargetCreature` maps to Rust's generic `DestroyTarget`
    # but a `draw_if_undamaged` rider is genuinely unshipped). When this
    # list is non-empty the class heuristic is over-optimistic for
    # those cards and the doc emits a WARNING; the cards are pinned to
    # BLOCKED regardless (the metric never overstates). Each tuple is
    # (card, tier_the_heuristic_would_have_used).
    consistency_violations: list[tuple[str, str]] = field(
        default_factory=list
    )
    # Informational (NOT a violation): residue `blocked_non_effect`
    # cards whose Effects ARE covered/probed at the Effect+bridge level
    # — that is precisely their definition (Effects shipped; the card
    # is gated by a non-Effect path). The metric measures Effect+bridge
    # byte-equality; the residue worklist tracks full-card admit
    # blockers — these legitimately differ and are surfaced as context,
    # not drift. Each tuple is (card, effect_evidence) where
    # effect_evidence is "probed" or "covered".
    blocked_non_effect_with_covered_effects: list[tuple[str, str]] = (
        field(default_factory=list)
    )

    def counts(self) -> dict[str, int]:
        return {k: len(self.tiers[k]) for k in _TIER_ORDER}


def classify_pool() -> PoolParityResult:
    """Walk the EoE pool, classify every printing into exactly one
    tier by the strict precedence in the module docstring, and run the
    residue-worklist internal-consistency cross-check."""
    from mtg_bot.cards.parser.source import OracleParserCardSource

    src = OracleParserCardSource()
    printings = src.get_printings()
    pool_names = set(printings.keys())

    covered_classes = covered_python_class_set()
    probed = genuine_probed_cards(pool_names)
    missing_cards, non_effect_cards = residue_blocked_cards()

    tiers: dict[str, list[str]] = {k: [] for k in _TIER_ORDER}
    violations: list[tuple[str, str]] = []
    bne_covered: list[tuple[str, str]] = []

    for name, printing in sorted(printings.items()):
        eff_classes = card_effect_classes(printing)
        all_effects_covered = bool(eff_classes) and eff_classes.issubset(
            covered_classes
        )
        admitted = loader_admits(printing)
        is_missing = name in missing_cards
        is_non_effect = name in non_effect_cards
        is_probed = name in probed
        covered_ok = (
            all_effects_covered or (not eff_classes and admitted)
        )

        # --- residue-worklist authority over the class heuristic -----
        # The per-card residue re-walk is the source of truth on
        # genuine absence; it sees Effect-shape riders the
        # class-granularity heuristic cannot (e.g. a `draw_if_undamaged`
        # rider on a class that otherwise maps to a live Rust variant).
        # So a `genuinely_missing` card is HARD-pinned to the BLOCKED-
        # missing tier no matter what the probe-name match / class
        # heuristic says — the metric must never overstate parity.
        if is_missing:
            tiers[TIER_BLOCKED_MISSING].append(name)
            if is_probed or covered_ok:
                # The class heuristic disagrees with the per-card
                # re-walk — surface it (the worklist wins, but the
                # heuristic's blind spot is worth a WARNING).
                violations.append(
                    (name, TIER_PROBED if is_probed else TIER_COVERED)
                )
            continue

        # A `blocked_non_effect` card is, BY DEFINITION, one whose
        # Effects ARE shipped/bridged but whose full-card admit is
        # gated by a non-Effect path. Its Effects being covered/probed
        # is EXPECTED, not drift — record it as informational context
        # and pin the card to the blocked_non_effect tier (full-card
        # parity is what's blocked; the metric does not count it as
        # byte-equal).
        if is_non_effect:
            tiers[TIER_BLOCKED_NON_EFFECT].append(name)
            if is_probed:
                bne_covered.append((name, "probed"))
            elif covered_ok:
                bne_covered.append((name, "covered"))
            continue

        # Precedence 1: PROBED (strongest). A genuine probe pins it.
        if is_probed:
            tiers[TIER_PROBED].append(name)
            continue

        # Precedence 2: covered-by-construction. Every emitted Effect
        # class has a live+bridged Rust counterpart. A 0-Effect
        # (vanilla / keyword-only) card qualifies here only if
        # loader-admitted (otherwise it has no cross-engine exercise
        # path and drops to the bench / blocked tier below).
        if covered_ok:
            tiers[TIER_COVERED].append(name)
            continue

        # Precedence 3: bridge-admitted & bench-exercised. The loader
        # admits it (the bench runs it 0-divergence at scale, capped
        # at ~22-25 turns). In practice the loader's admit gate only
        # passes vanilla / safe-trigger creatures + basic lands — all
        # of which have covered (or zero) Effects and were already
        # caught by precedence 2 — so this tier is typically empty.
        # It is kept explicit so that if the admit gate ever widens to
        # admit a card whose Effects are NOT all class-covered, the
        # bench's empirical 0-divergence signal still counts it here
        # rather than dropping it to BLOCKED.
        if admitted:
            tiers[TIER_ADMITTED].append(name)
            continue

        # Precedence 4: BLOCKED — the long subsystem-gated /
        # Effect-uncovered tail (not itemised in the residue worklist).
        tiers[TIER_BLOCKED_SUBSYSTEM].append(name)

    return PoolParityResult(
        n_pool=len(pool_names),
        tiers=tiers,
        consistency_violations=violations,
        blocked_non_effect_with_covered_effects=bne_covered,
    )


# ------------------------------------------------- markdown render


def _pct(n: int, d: int) -> float:
    return (100.0 * n / d) if d else 0.0


def render_markdown(res: PoolParityResult) -> str:
    c = res.counts()
    n = res.n_pool
    probed_n = c[TIER_PROBED]
    covered_n = c[TIER_COVERED]
    admitted_n = c[TIER_ADMITTED]
    # "byte-equal at the Effect+bridge level" = PROBED + covered (every
    # Effect lives + bridges; PROBED additionally has a genuine probe).
    byte_equal_n = probed_n + covered_n
    blocked_total = (
        c[TIER_BLOCKED_MISSING]
        + c[TIER_BLOCKED_NON_EFFECT]
        + c[TIER_BLOCKED_SUBSYSTEM]
    )

    L: list[str] = []
    L.append(
        "Generated by `scripts/measure_pool_parity.py` — "
        "DO NOT EDIT MANUALLY. Run the script to refresh."
    )
    L.append("")
    L.append("# Pool-level cross-engine parity metric")
    L.append("")
    L.append(
        "The authoritative, measured, regenerable answer to *\"what "
        "fraction of the EoE card pool is byte-equal cross-engine?\"* "
        "Every printing the parser claims (the same pool "
        "`measure_effect_coverage.py` walks) is classified into exactly "
        "one honest tier by a strict precedence (strongest evidence "
        "wins). This replaces the three PROXIES the campaign used to "
        "estimate from (per-emission Rust coverage, the residue count, "
        "\"0 FAIL_DIVERGENCE over the admitted subset\") with a single "
        "tracked number."
    )
    L.append("")
    L.append("## Headline")
    L.append("")
    L.append(
        f"- **{byte_equal_n} / {n} EoE cards "
        f"({_pct(byte_equal_n, n):.1f}%) are byte-equal at the "
        f"Effect+bridge level**; of those, **{probed_n} "
        f"({_pct(probed_n, n):.1f}% of the pool) are individually "
        f"pinned by a genuine real-EoE cross-engine byte-equality "
        f"probe** (the strongest evidence), the remaining "
        f"{covered_n} are covered-by-construction (every Effect they "
        f"emit has a live Rust variant + bridge arm, but no genuine "
        f"probe pins THAT card)."
    )
    L.append(
        f"- A further **{admitted_n} ({_pct(admitted_n, n):.1f}%)** "
        f"are bridge-admitted & bench-exercised 0-divergence at scale "
        f"(empirical, but bounded — see the caveat)."
    )
    L.append(
        f"- **{blocked_total} ({_pct(blocked_total, n):.1f}%)** are "
        f"BLOCKED, broken out below."
    )
    L.append("")
    L.append(
        "> **CAVEAT — what this measures vs. what it does NOT.** This "
        "is **Effect+bridge-level byte-equality evidence**, NOT "
        "full-game-trajectory parity. The PROBED tier asserts "
        "byte-equality on a *controlled* cross-engine state (a real "
        "EoE printing driven end-to-end), not over a full random "
        "multi-turn game. The covered-by-construction tier only proves "
        "the card's Effect *primitives* all exist + bridge — it does "
        "**not** prove the card plays byte-equal in a real game. The "
        "bench tier is the empirical full-trajectory signal but is "
        "**capped at ~22-25 turns** (see "
        "`docs/bench_trajectory_parity_smoke.md`) and only over the "
        "loader-admitted subset. **No tier here claims the whole pool "
        "is byte-equal in real full-game trajectories** — that "
        "remains out of scope and is the campaign's open frontier."
    )
    L.append("")

    L.append("## Tiers")
    L.append("")
    L.append("| Tier | Count | % of pool |")
    L.append("|---|---:|---:|")
    for k in _TIER_ORDER:
        L.append(
            f"| {_TIER_LABEL[k]} | {c[k]} | {_pct(c[k], n):.1f}% |"
        )
    L.append(f"| **Pool total** | **{n}** | **100.0%** |")
    L.append("")

    L.append("### Tier definitions")
    L.append("")
    L.append(
        "Evaluated in this strict precedence (a card lands in the "
        "FIRST tier it qualifies for):"
    )
    L.append("")
    L.append(
        "1. **PROBED byte-equal** — a "
        "`test_cross_engine_real_eoe_<slug>_parity` function in "
        "`tests/test_parity_smoke.py` (slug = the card's printed-name "
        "slug, split cards keyed on the left face) asserts "
        "byte-equality for THIS card. `*_divergence_pin` functions are "
        "excluded (they pin a KNOWN divergence). Strongest evidence."
    )
    L.append(
        "2. **Effect+bridge covered (not individually probed)** — "
        "every distinct Python `Effect` class the card emits (walked "
        "with `measure_effect_coverage`'s exact walker) is in that "
        "script's covered-class set (live Rust variant + bridge), AND "
        "the card is not a residue-worklist BLOCKED entry. A "
        "0-Effect vanilla / keyword-only card qualifies here only if "
        "loader-admitted. Covered-by-construction — weaker than a "
        "genuine probe."
    )
    L.append(
        "3. **bridge-admitted & bench-exercised** — the production-deck "
        "loader admits the printing "
        "(`trajectory._printing_is_bridge_basic_land` or "
        "`_printing_is_bridge_simple_creature` — the exact bench admit "
        "gate) and the bench runs it 0-divergence at scale. "
        "Bounded-depth empirical signal (~22-25 turn cap)."
    )
    L.append(
        "4. **BLOCKED** — not byte-equal-covered today; broken out:"
    )
    L.append(
        "   - **genuinely_missing** — a residue-worklist "
        "`genuinely_missing` entry: a TRUE new-Rust-Effect ask (the "
        "load-bearing \"how far from parity\" gap)."
    )
    L.append(
        "   - **blocked_non_effect** — a residue-worklist "
        "`blocked_non_effect` entry: Effects shipped, gated by a "
        "non-Effect path (unbridged event / declined cost-mechanic / "
        "unmodeled subsystem / token-registration substrate)."
    )
    L.append(
        "   - **subsystem-gated / Effect-uncovered** — the long "
        "blocked tail: emits an Effect with no covered Rust "
        "counterpart, or is loader-rejected by a subsystem gate "
        "(Station / Ward / Devour / warp / Aura / Rooms / "
        "BECOMES_TAPPED / dynamic-P/T / activated+static abilities / "
        "planeswalker / …), and is not itemised in the residue "
        "worklist."
    )
    L.append("")

    # Internal-consistency cross-check.
    L.append("## Internal-consistency cross-check (residue worklist)")
    L.append("")
    L.append(
        "The residue worklist's per-card re-walk is the AUTHORITY on "
        "genuine Effect absence (it sees Effect-shape riders the "
        "class-granularity coverage heuristic cannot). A "
        "`genuinely_missing` card is therefore hard-pinned to the "
        "BLOCKED tier regardless of what the class heuristic / probe "
        "name-match says — the metric never overstates parity."
    )
    L.append("")
    if res.consistency_violations:
        L.append(
            f"**WARNING: {len(res.consistency_violations)} "
            f"`genuinely_missing` card(s) the class-granularity "
            f"heuristic WOULD have counted as covered/probed.** They "
            f"are pinned to BLOCKED (the worklist wins), but the "
            f"heuristic's class-level blind spot for these is worth "
            f"reconciling — either the worklist entry is stale (the "
            f"Effect actually shipped → close it; the round-54/55 cron "
            f"is the structural backstop) or the class heuristic is "
            f"genuinely too coarse for that card's rider (expected — "
            f"this is exactly why the per-card worklist exists):"
        )
        L.append("")
        for card, tier in sorted(res.consistency_violations):
            L.append(
                f"- `{card}` — residue `genuinely_missing`; class "
                f"heuristic would have placed it in `{tier}` "
                f"(class-granularity false-positive — pinned BLOCKED)."
            )
    else:
        L.append(
            "- **0 violations** — no `genuinely_missing` residue card "
            "was class-heuristic-counted as covered/probed. The "
            "headline does not overstate parity relative to the honest "
            "residue list."
        )
    L.append("")
    # Informational: blocked_non_effect cards with covered/probed
    # Effects. This is EXPECTED (their definition) — surfaced as
    # context, not drift, so a reader understands the gap between
    # "Effect+bridge byte-equal" and "full-card parity".
    if res.blocked_non_effect_with_covered_effects:
        L.append(
            f"_Context (NOT drift): "
            f"{len(res.blocked_non_effect_with_covered_effects)} "
            f"`blocked_non_effect` card(s) have covered/probed Effects "
            f"— that is their definition (Effects shipped; full-card "
            f"admit gated by a non-Effect path). The metric counts "
            f"Effect+bridge byte-equality; these cards' Effects ARE "
            f"byte-equal but the CARD is not full-game parity-able. "
            f"This is the precise gap between the two — surfaced for "
            f"honesty:_"
        )
        L.append("")
        for card, ev in sorted(
            res.blocked_non_effect_with_covered_effects
        ):
            L.append(
                f"- `{card}` — Effects {ev} at the Effect+bridge "
                f"level; CARD remains `blocked_non_effect` "
                f"(non-Effect gate)."
            )
        L.append("")

    # Per-tier card listings (BLOCKED tiers itemised; covered tiers
    # summarised — the bulk; PROBED listed in full as it's the
    # strongest, most-auditable claim).
    L.append("## PROBED cards (genuine real-EoE byte-equality probes)")
    L.append("")
    if res.tiers[TIER_PROBED]:
        for nm in sorted(res.tiers[TIER_PROBED]):
            L.append(f"- {nm}")
    else:
        L.append("- (none)")
    L.append("")

    for k in (
        TIER_BLOCKED_MISSING,
        TIER_BLOCKED_NON_EFFECT,
    ):
        L.append(f"## {_TIER_LABEL[k]} ({c[k]})")
        L.append("")
        if res.tiers[k]:
            for nm in sorted(res.tiers[k]):
                L.append(f"- {nm}")
        else:
            L.append("- (none)")
        L.append("")

    L.append(
        f"## {_TIER_LABEL[TIER_BLOCKED_SUBSYSTEM]} "
        f"({c[TIER_BLOCKED_SUBSYSTEM]})"
    )
    L.append("")
    L.append(
        "The long blocked tail (not itemised in the residue "
        "worklist). Round-58 N2 broke this **opaque single bucket** out "
        "by gating subsystem so it is the data-driven \"which subsystem "
        "next\" instrument, not one number — see "
        "`docs/SUBSYSTEM_ROADMAP.md` for the leverage analysis + "
        "recommended sequencing. A card may be **multi-gated** (counted "
        "under every gate it trips, so `#cards` does NOT sum to the "
        "tier total); `1gate` is the single-gated count (closing that "
        "one subsystem flips the card) and reconciles exactly. "
        "`decks(1g)` is the cumulative 17lands deck-count of the "
        "single-gated members — the honest leverage signal."
    )
    L.append("")
    L.extend(_render_subsystem_breakout(res))
    L.append("")
    L.append(
        "Full card list (first 60 shown for auditability; the full "
        "set + per-card gate attribution is regenerable from "
        "`scripts/scout_r58_subsystem_attribution.py`):"
    )
    L.append("")
    for nm in sorted(res.tiers[TIER_BLOCKED_SUBSYSTEM])[:60]:
        L.append(f"- {nm}")
    if c[TIER_BLOCKED_SUBSYSTEM] > 60:
        L.append(f"- … and {c[TIER_BLOCKED_SUBSYSTEM] - 60} more")
    L.append("")

    return "\n".join(L) + "\n"


def _subsystem_breakout_rows() -> tuple[list[dict], dict] | tuple[None, None]:
    """Reuse ``scout_r58_subsystem_attribution``'s attribution +
    leverage table verbatim (the subsystem taxonomy is defined ONCE,
    there — this metric never re-derives it, the same discipline as
    reusing ``measure_effect_coverage``'s parser). Returns
    ``(leverage_rows, attribution)`` or ``(None, None)`` if the scout
    is unimportable (defensive: the doc still renders, just without the
    breakout, never blocking the cron)."""
    try:
        import scout_r58_subsystem_attribution as scout  # noqa: E402

        attr = scout.subsystem_attribution()
        dc = scout._deck_counts(set(attr["cards"]))
        rows = scout.leverage_table(attr, dc)
        return rows, attr
    except Exception:  # pragma: no cover - defensive, never blocks
        return None, None


def _render_subsystem_breakout(res: PoolParityResult) -> list[str]:
    """The per-subsystem markdown table for the BLOCKED-subsystem
    section. Honest: it carries the single-gate reconciliation inline
    so a reader can verify the breakout partitions exactly the same
    cards the old opaque count reported."""
    rows, attr = _subsystem_breakout_rows()
    L: list[str] = []
    if rows is None or attr is None:
        L.append(
            "_(subsystem breakout unavailable — "
            "`scout_r58_subsystem_attribution` not importable; the "
            "opaque tier count above is still authoritative.)_"
        )
        return L
    n_total = attr["n_subsystem_gated"]
    n_single = sum(
        1 for cd in attr["cards"].values() if not cd["multi_gated"]
    )
    n_multi = n_total - n_single
    L.append(
        "| Subsystem | #cards | 1gate | multi | decks(tot) | "
        "decks(1g) | Tractability |"
    )
    L.append("|---|---:|---:|---:|---:|---:|---|")
    for r in rows:
        L.append(
            f"| {r['label']} | {r['n_cards']} | {r['n_single_gate']} "
            f"| {r['n_multi_gated']} | {r['deck_count_total']:,} | "
            f"{r['deck_count_single_gate']:,} | {r['tractability']} |"
        )
    L.append("")
    sum_single = sum(len(v) for v in attr["single_gate"].values())
    L.append(
        f"**Reconciliation:** {n_total} subsystem-gated = "
        f"{n_single} single-gated + {n_multi} multi-gated; the per-"
        f"subsystem `1gate` column sums to {sum_single} "
        f"(== single-gated total). The breakout partitions exactly the "
        f"same {n_total} cards the opaque tier count above reports "
        f"(this metric reuses `classify_pool` verbatim — same tier, "
        f"same pool); the headline is unchanged, only the BLOCKED-tail "
        f"detail is itemised."
    )
    unclass = attr["by_subsystem"].get(scout_unclassified_key(), [])
    if unclass:
        L.append("")
        L.append(
            f"**Honest unclassified bucket ({len(unclass)}):** "
            + ", ".join(f"`{u}`" for u in sorted(unclass))
            + " — no taxonomy gate fired; flagged for a hand re-walk "
            "rather than force-guessed (see `docs/SUBSYSTEM_ROADMAP.md`)."
        )
    return L


def scout_unclassified_key() -> str:
    """The scout's ``SUB_UNCLASSIFIED`` key, resolved without a
    top-level import (the scout imports this module — keep the
    dependency lazy / one-directional)."""
    try:
        import scout_r58_subsystem_attribution as scout  # noqa: E402

        return scout.SUB_UNCLASSIFIED
    except Exception:  # pragma: no cover - defensive
        return "unclassified"


# ------------------------------------------------- headline (one-liner)


def headline_line(res: PoolParityResult) -> str:
    """A single never-blocking headline string for the staleness cron /
    post-commit hook. Mirrors the round-52/55 cron headline contract:
    one line, no exit-code semantics for the hook."""
    c = res.counts()
    n = res.n_pool
    be = c[TIER_PROBED] + c[TIER_COVERED]
    viol = len(res.consistency_violations)
    suffix = (
        f" ⚠ {viol} residue-consistency violation(s)" if viol else ""
    )
    # Round-58: surface the subsystem-gated single/multi split inline
    # so the headline is no longer one opaque number — but stay ONE
    # line and NEVER block (the scout import is defensive; if it fails
    # the headline degrades to the plain count, same cron contract).
    sub_detail = f"{c[TIER_BLOCKED_SUBSYSTEM]} subsystem-gated"
    try:
        _rows, _attr = _subsystem_breakout_rows()
        if _attr is not None:
            _ns = sum(
                1
                for cd in _attr["cards"].values()
                if not cd["multi_gated"]
            )
            _nm = _attr["n_subsystem_gated"] - _ns
            sub_detail = (
                f"{c[TIER_BLOCKED_SUBSYSTEM]} subsystem-gated "
                f"({_ns} single-gate / {_nm} multi-gated; "
                f"see docs/SUBSYSTEM_ROADMAP.md)"
            )
    except Exception:  # pragma: no cover - defensive, never blocks
        pass
    return (
        f"[pool-parity] {be}/{n} EoE cards "
        f"({_pct(be, n):.1f}%) byte-equal at the Effect+bridge level "
        f"({c[TIER_PROBED]} genuinely probed); "
        f"{c[TIER_ADMITTED]} bench-exercised; "
        f"{c[TIER_BLOCKED_MISSING]} genuinely_missing / "
        f"{c[TIER_BLOCKED_NON_EFFECT]} blocked_non_effect / "
        f"{sub_detail}. "
        f"NOT full-game-trajectory parity (caveat in "
        f"docs/POOL_PARITY.md).{suffix}"
    )


# ------------------------------------------------- entrypoint


def main(argv: list[str] | None = None) -> int:
    """Default: classify, (re)write ``docs/POOL_PARITY.md``, print the
    full markdown. With ``--headline``: classify and print ONLY the
    one-line never-blocking headline (the post-commit-hook entry — does
    NOT rewrite the doc, mirroring the round-52/55 cron headline
    contract: surface a line, never block, never side-effect on disk).

    Exit code is non-zero iff the residue-consistency cross-check fired
    (a ``genuinely_missing`` card the class heuristic over-counted) —
    for explicit CI / standalone gating only. The post-commit hook
    never propagates it, exactly like the staleness cron.
    """
    argv = sys.argv[1:] if argv is None else argv
    headline_only = "--headline" in argv
    res = classify_pool()
    if headline_only:
        print(headline_line(res))
    else:
        md = render_markdown(res)
        OUTPUT_DOC.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_DOC.write_text(md, encoding="utf-8")
        print(md)
    return 1 if res.consistency_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
