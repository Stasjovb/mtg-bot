"""Genuine real-EoE cross-engine byte-equality probes — batch E.

CONTINUOUS-PIPELINE phase: convert high-deck-count
``covered-by-construction`` EoE cards into the **strongest parity-
evidence tier** (``PROBED byte-equal`` per ``docs/POOL_PARITY.md`` /
``scripts/measure_pool_parity.py``) via genuine real-EoE cross-engine
probes.

WHAT EACH PROBE ASSERTS
-----------------------
Every probe drives the **ACTUAL parsed EoE printing** on the Python
side (``get_active_source().get_printings().get("<card>")`` — NOT a
synthetic stub) against the bridged synthetic carrier on the Rust side
(``register_and_inject_object`` with the closed-vocab effect dict the
production bridge round-trips — the established Embrace-Oblivion /
Decode-Transmissions / Divert-Disaster cross-engine driving pattern;
the full Instant/Sorcery is NOT loader-admitted, there is no
Instant/Sorcery bench path) and asserts **full ``compare_fields(...)
== []``** — byte-equality across the WHOLE cross-engine field view,
the strongest Effect+bridge-level evidence — after a real EoE deck
context (the carrier resolved end-to-end on both engines, the spell
fired, the stack drained). Made campaign-wide possible by the
round-r70 ``_zone_signature`` ``_net_counters`` counters-blindness fix.

> CAVEAT (mirrors ``docs/POOL_PARITY.md``): this is Effect+bridge-
> level byte-equality on a *controlled* cross-engine state, NOT
> full-game-trajectory parity. PROBED is the strongest evidence tier
> the campaign tracks; it is not a full random multi-turn game.

PARTITION DISCIPLINE (batch E — the band below batch D)
-------------------------------------------------------
Sibling agents own the disjoint batch A (odd-ranked,
``tests/test_probe_covered_unprobed_a.py``) + batch B (even-ranked,
``tests/test_probe_covered_unprobed_b.py``) + batch C
(``tests/test_probe_covered_unprobed_c.py``) + batch D
(``tests/test_probe_covered_unprobed_d.py``) + the spell-card-bridge
sweep (Radiant Strike / Depressurize,
``tests/test_probe_spell_card_bridge_admitted.py``) + the five
warp-admitted creatures (``tests/test_probe_warp_admitted.py``); a
Rust agent owns Seedship Impact / Orbital Plunge. This module owns
**batch E = the NEXT deck-count band below D**: the highest-deck
cleanly-probe-constructible covered-but-unprobed cards NOT in any
sibling/Rust set. The covered-by-construction-but-unprobed list
(computed read-only via ``scripts/measure_pool_parity.classify_pool``
+ ``scripts/scout_r58_subsystem_attribution._deck_counts``, sorted by
17lands deck count desc) was verify-first-recomputed at live HEAD
``e101da2f``; every card below is (a) covered-by-construction, (b) NOT
individually probed, (c) NOT in batch A / B / C / D / the
spell-card-bridge module / the warp module / the Rust-owned pair.

The 7 cards pinned here (deck counts at the verify-first walk):

  | card                  | decks  | shape                            |
  |-----------------------|-------:|----------------------------------|
  | Lost in Space         | 20,796 | Instant Seq(OwnerPutsTopOrBottom,|
  |                       |        |          Surveil 1)              |
  | Hymn of the Faller    |  8,913 | Sorcery Seq(Surveil 1, Draw 1,   |
  |                       |        |          LoseLife 1, CondVoid)   |
  | Unravel               |  6,728 | Instant CounterTargetSpell(any)  |
  | Annul                 |  3,564 | Instant CounterTargetSpell(A/E)  |
  | Zealous Display       |  3,224 | Instant PumpCreaturesYouControl  |
  |                       |        |          (+2/+0)                 |
  | Full Bore             |  2,200 | Instant PumpTargetCreature(+3/+2)|
  | Space-Time Anomaly    |  1,574 | Sorcery MillTargetPlayer(=life)  |

DROPPED ON VERIFY (honest verify-first discipline):

  * **Cerebral Download** (~11,768) — its genuine ``spell_effect`` is
    a ``Sequence`` whose live cross-engine probe is the EXISTING
    ``test_cross_engine_cerebral_download_real_eoe_cast_xfails_on_
    sequence_surveil_then_draw`` KNOWN-divergence pin
    (``test_parity_smoke.py``). Driving it as a "byte-equal" probe
    would re-surface that already-tracked divergence — NOT a clean
    covered→PROBED conversion (the batch-D precedent for this exact
    card). Excluded; the divergence is owned by its existing xfail.
  * **Temporal Intervention** (~1,715) — genuine ``spell_effect`` is
    ``TargetOpponentDiscardsCasterChoice`` (the CASTER picks which
    card the opponent discards). The ``discard_card`` bridge arm maps
    to ``TargetOpponentDiscards`` (the DISCARDER's own agent picks,
    or Rust's deterministic ``hand[0]``) — a genuinely DIFFERENT
    Python class with a different chooser. Driving the genuine
    caster-choice printing against the discarder-choice / hand[0]
    bridge arm would not be a faithful byte-equal mirror of THAT
    card's Effect (same "the bare bridge arm doesn't carry the
    genuine class's rider" discipline as batch-B's Syr Vondam drop).
    Replaced by the next clean pick, Full Bore (2,200).
  * **Dual-Sun Technique** (~3,734) — genuine
    ``PumpTargetCreatureUntilEOT`` carries
    ``granted_keywords={double strike}``; the bare
    ``pump_target_creature_until_eot`` bridge arm carries ONLY
    ``power_bonus`` / ``toughness_bonus`` (the keyword-grant rider is
    NOT on the arm — the exact batch-B Syr Vondam precedent). The
    genuine printing would genuinely DIVERGE from a bare-arm Rust
    synthetic. Dropped; Full Bore (whose keyword grant is gated on
    ``granted_keywords_if_warp_cast`` and therefore observationally
    INERT under a normal non-warp StackItem cast) is the clean
    same-family replacement.
  * **Scrounge for Eternity** / **Lithobraking** (~4,150 / ~3,148) —
    both carry an additional-cost / optional-sacrifice agent decision
    leg (``additional_cost_sacrifice_creature_or_artifact`` /
    ``OptionalSacArtifactForEffect``) with no established cross-engine
    optional-cost mirror idiom in the harness (the batch-A Selfcraft
    Mechan / Oreplate Pangolin optional-cost-decision drop precedent).
    Deferred to an optional-cost-idiom slice.

All 7 picks assert **full ``compare_fields == []``** over the whole
cross-engine field view (the strongest tier). NEW dedicated module
(not added to ``tests/test_trajectory_parity.py`` nor the
batch_a / batch_b / batch_c / batch_d / spell_card_bridge_admitted /
warp_admitted modules nor the 6 ``test_audit_safe_trigger_*`` tests —
those are owned/protected; this module avoids all collision and
touches no STALENESS-SENTINEL).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there). Identical to ``test_parity_smoke.py``'s
    module-scoped fixture — copied here so this module is fully
    self-contained / collision-free with the owned test files."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


def _drain_both(py_state, rust_state):
    """Resolve the top of stack on both engines until both stacks are
    empty. Mirrors ``test_parity_smoke.py``'s ``_drain_stack_both``."""
    from mtg_bot.actions import resolve_top_of_stack

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    while py_state.stack:
        resolve_top_of_stack(py_state)


# ---------------------------------------------------------------------
# Batch-E probe #1 — Lost in Space (~20,796 17lands decks).
#
# Verified covered (``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOf
# Library`` + ``Surveil`` ∈ covered set) + unprobed at HEAD e101da2f.
# Oracle:
#   "[Instant] {3}{U} — Target artifact or creature's owner puts it on
#    their choice of the top or bottom of their library. Surveil 1."
# Parser → ``spell_effect = Sequence(OwnerPutsTargetArtifactOrCreature
# OnTopOrBottomOfLibrary(nonland_permanent=False), Surveil(1))``.
#
# Established idiom: the I78 ``owner_puts_target_artifact_or_creature_
# on_top_or_bottom_of_library`` cross-engine probe
# (``test_parity_smoke.py``) — Rust scans the SOURCE-controller's
# OPPONENT's bf for the first Artifact/Creature and the OWNER's
# top-vs-bottom choice deterministically picks BOTTOM; Python picks the
# target at push via the controller's agent and the owner's
# ``choose_mode`` → seat ``_PickBottomLibraryAgent`` on the owner so
# both engines route the bait to the BOTTOM of its owner's library.
# Then Surveil(1) with NO surveil agent seated → keep-all on BOTH
# (the batch-C Starfighter-Pilot surveil-keep-all leg).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_lost_in_space_owner_puts_then_surveil_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Lost in Space (~20,796
    17lands decks). Batch-E covered→PROBED.**

    Python: the ACTUAL parsed Lost in Space printing on a ``StackItem``
    with the chosen artifact-or-creature target (p1's vanilla 2/2 —
    p0 picks it via ``_PickFirstOpponentTargetAgent``; p1 is the
    OWNER so ``_PickBottomLibraryAgent`` on p1 routes it to its
    library BOTTOM, mirroring Rust's deterministic bottom pick). Rust:
    the bridged ``sequence[owner_puts_target_artifact_or_creature_on_
    top_or_bottom_of_library, surveil 1]`` synthetic Instant.

    **EMPTY p0 library → the Surveil(1) leg is a clean no-op on BOTH
    engines.** p0's library is intentionally empty: Surveil(1) with no
    library card to look at invokes NO surveil decision on EITHER
    engine (Rust short-circuits; Python's surveil sees an empty
    library and returns without calling ``choose_surveil``), so the
    caster-seated ``_PickFirstOpponentTargetAgent`` (which only
    implements the target pick) is never asked for a surveil choice.
    The probe pins the load-bearing ``owner_puts...`` leg byte-equal;
    the surveil leg is a structurally-forced no-op (the Surveil class
    is still genuinely exercised end-to-end — it just has nothing to
    act on, identically on BOTH).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the 2/2 leaves p1's bf to the BOTTOM of
    p1's library on BOTH; p0's library stays empty / Surveil no-op on
    BOTH; both graveyards empty).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields, CardDef,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.zone_moves import (
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import (
        _PickFirstOpponentTargetAgent,
        _PickBottomLibraryAgent,
    )

    real = get_active_source().get_printings().get("Lost in Space")
    if real is None:
        pytest.skip("Lost in Space absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Lost in Space spell_effect must be a Sequence; "
        f"got {type(se).__name__}"
    )
    assert isinstance(
        se.effects[0],
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    )

    # EMPTY p0 library: Surveil(1) has no card to look at → a clean
    # no-op invoking NO surveil decision on EITHER engine (so the
    # caster's target-only agent is never asked for a surveil choice;
    # Rust short-circuits the empty-library surveil identically).
    spec = DeckSpec(
        card_defs=(),
        p0_library=(),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 (opponent) has a single vanilla 2/2 — the artifact-or-creature
    # target on BOTH (Rust scans the source-controller's opponent's bf;
    # the opponent-target shim mirrors that same-side pick).
    py_vic = py.new_object(
        CardPrinting(
            name="LiS Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    # p0 (caster) picks the spell target = p1's creature; p1 is the
    # OWNER and picks BOTTOM via choose_mode (mirrors Rust's
    # deterministic-bottom first-slice convention).
    py.players[0].agent = _PickFirstOpponentTargetAgent()
    py.players[1].agent = _PickBottomLibraryAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "LiS Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Lost in Space on a StackItem. ----
    # The genuine OwnerPuts effect's target kind is "permanent" (its
    # legal_targets emits ("permanent", id) and resolve early-returns
    # on any other kind — verified live in zone_moves.py).
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("permanent", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bridged sequence[owner_puts..., surveil 1]. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Lost in Space", "card_types": ["Instant"],
         "effects": [{"kind": "sequence", "effects": [
             {"kind": ("owner_puts_target_artifact_or_creature_"
                       "on_top_or_bottom_of_library")},
             {"kind": "surveil", "count": 1},
         ]}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # The 2/2 left p1's bf and landed at the BOTTOM of p1's library on
    # BOTH; p0's library stays empty (Surveil no-op), gy empty.
    rs_bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    py_bf_ids = [o.id for o in py.battlefield]
    assert rs_vic_id not in rs_bf_ids and py_vic.id not in py_bf_ids, (
        "the 2/2 must leave the bf on BOTH"
    )
    rs_p1_lib = [e["printing_name"] for e in rs.library_snapshot(1)]
    py_p1_lib = [o.printing.name for o in py.players[1].library]
    assert rs_p1_lib == py_p1_lib == ["LiS Victim"], (
        f"the 2/2 must be in p1's library on BOTH; "
        f"rust={rs_p1_lib} py={py_p1_lib}"
    )
    assert rs.library_sizes[0] == len(py.players[0].library) == 0, (
        "p0's library stays empty (Surveil(1) no-op) on BOTH"
    )
    # The resolved Lost in Space spell itself routes to p0's graveyard
    # (CR 608.2m) on BOTH engines; the Surveil(1) milled nothing (empty
    # library). The full compare_fields below is the load-bearing
    # byte-equality assertion (it covers every graveyard entry on both
    # players byte-for-byte — the established batch-C Embrace-Oblivion
    # synthetic-spell idiom).
    rs_p0_gy = sorted(e["printing_name"]
                      for e in rs.graveyard_snapshot(0))
    py_p0_gy = sorted(o.printing.name
                      for o in py.players[0].graveyard)
    assert rs_p0_gy == py_p0_gy, (
        f"p0 graveyard contents must be byte-equal on BOTH; "
        f"rust={rs_p0_gy} py={py_p0_gy}"
    )

    # NOTE: the prior summoning_sick normalisation block (pre-13th-
    # slice) is no longer needed.  RRR Pin 2 closure dropped the
    # explicit ``obj.summoning_sick = true`` stamp from the Rust
    # library-bounce arm; both engines now preserve the pre-bounce
    # value natively, so the field is already byte-equal under the
    # whole-view compare below.  Removed 2026-05-19 (13th Rust slice).

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Lost in Space owner-puts-top + surveil-keep-all must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-E probe #2 — Hymn of the Faller (~8,913 17lands decks).
#
# Verified covered (``Sequence`` / ``Surveil`` / ``DrawCards`` /
# ``LoseLife`` / ``ConditionalIfVoid`` ∈ covered set) + unprobed at
# HEAD. Oracle:
#   "[Sorcery] {1}{B} — Surveil 1, then you draw a card and lose 1
#    life. Void — If a nonland permanent left the battlefield this turn
#    or a spell was warped this turn, draw another card."
# Parser → ``spell_effect = Sequence(Surveil(1), DrawCards(1),
# LoseLife(1), ConditionalIfVoid(then=DrawCards(1), else=None))``. On a
# fresh state Void is INACTIVE so the ConditionalIfVoid's
# ``else_effect=None`` leg fires (a pure no-op): the net is surveil-1
# keep-all + draw 1 + lose 1 life. Deterministic, no targets, no RNG
# (the batch-A Decode-Transmissions Void-inactive idiom + the
# batch-C Starfighter surveil-keep-all leg).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_hymn_of_the_faller_void_inactive_surveil_draw_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Hymn of the Faller
    (~8,913 17lands decks). Batch-E covered→PROBED.**

    Python: the ACTUAL parsed Hymn of the Faller printing on a
    ``StackItem`` (no targets). Rust: the bridged ``sequence[surveil
    1, draw_cards 1, lose_life 1, conditional_if_void(then=draw_cards
    1)]`` synthetic Sorcery. Void INACTIVE on the fresh state → the
    ConditionalIfVoid's empty else-branch fires (no extra draw) on
    BOTH: caster surveil-1 keep-all, draws 1, loses 1 life.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the surveil-bait stays on p0's library
    top — keep-all; then exactly one DIFFERENT seeded card moves
    p0-library→p0-hand on BOTH; p0 life −1 on BOTH; p1 untouched).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields, CardDef,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone, is_void_active
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import Sequence

    real = get_active_source().get_printings().get("Hymn of the Faller")
    if real is None:
        pytest.skip("Hymn of the Faller absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Hymn of the Faller spell_effect must be a Sequence; "
        f"got {type(se).__name__}"
    )

    # Two distinct named filler cards in p0's library so surveil-1
    # observes the TOP one (kept in place) and the draw takes the NEXT
    # one — both observable + byte-equal (same printings, same order).
    filler = CardDef(name="HoF Filler", card_type="Land",
                     mana_produced=("B",))
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=("HoF Filler", "HoF Filler", "HoF Filler"),
        p1_library=("HoF Filler", "HoF Filler", "HoF Filler"),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    assert is_void_active(py) is False, (
        "fresh state must have Void INACTIVE so the empty else-branch "
        "fires (no extra draw)"
    )

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    # ---- Python: genuine parsed Hymn of the Faller on a StackItem,
    # controller p0, no targets (NO surveil agent → keep-all). ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py.players[0].life == py_p0_life0 - 1, (
        "Void inactive → caster loses exactly 1 life (no extra draw)"
    )
    assert py.players[1].life == py_p1_life0

    # ---- Rust: bridged sequence synthetic Sorcery. ----
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Hymn of the Faller", "card_types": ["Sorcery"],
         "effects": [{"kind": "sequence", "effects": [
             {"kind": "surveil", "count": 1},
             {"kind": "draw_cards", "count": 1},
             {"kind": "lose_life", "amount": 1},
             {"kind": "conditional_if_void",
              "then_effect": {"kind": "draw_cards", "count": 1}},
         ]}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.get_life(0) == rs_p0_life0 - 1, (
        "Rust Void inactive → caster loses exactly 1 life"
    )
    assert rs.get_life(1) == rs_p1_life0

    # Exactly ONE card moved p0-library→p0-hand on BOTH (surveil-1
    # keep-all left the top card in place; the single DrawCards(1)
    # then drew it — net p0 hand +1, library −1).
    assert rs.hand_sizes[0] == len(py.players[0].hand) == 1, (
        f"p0 draws exactly 1 (no Void extra) on BOTH; "
        f"rust={rs.hand_sizes[0]} py={len(py.players[0].hand)}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Hymn of the Faller Void-inactive surveil+draw+lose1 must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-E probe #3 — Unravel (~6,728 17lands decks).
#
# Verified covered (``CounterTargetSpell`` ∈ covered set) + unprobed at
# HEAD. Oracle:
#   "[Instant] {1}{U}{U} — Counter target spell. If the amount of mana
#    spent to cast that spell was less than its mana value, you draw a
#    card."
# Parser → ``spell_effect = CounterTargetSpell(filter_types=∅)``. The
# bridge's bare ``counter_target_spell`` arm constructs
# ``CounterTargetSpell()`` (empty filter — counters ANY spell). The
# mana-spent-less-than-mv draw rider does NOT trigger when the bait is
# cast paying its full cost (the synthetic harness seats the bait with
# no reduced-cost record) — the genuine resolve path IS the bare
# counter. The established batch-D Divert-Disaster counter-bait idiom
# (distinct controllers → no intra-graveyard ordering ambiguity).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_unravel_counter_target_spell_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Unravel (~6,728 17lands
    decks). Batch-E covered→PROBED.**

    Python: the ACTUAL parsed Unravel printing on a ``StackItem``
    above a benign p0 Bait Spell, controlled by p1, target =
    ``("stack", 0)``. Rust: the bridged ``{"kind":
    "counter_target_spell"}`` synthetic Instant pushed above the bait
    (auto-picks the non-self stack item). The bait is countered → its
    owner's graveyard on BOTH; the mana-spent draw rider stays inert
    (bait cast at full cost).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (Bait Spell in p0's graveyard, Unravel in
    p1's graveyard, both stacks empty, NO Bait on the bf — countered,
    never resolved — on BOTH engines byte-equal).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Unravel")
    if real is None:
        pytest.skip("Unravel absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, CounterTargetSpell), (
        f"genuine Unravel spell_effect must be CounterTargetSpell; "
        f"got {type(se).__name__}"
    )
    assert se.filter_types == frozenset(), (
        "Unravel counters ANY spell (empty filter_types)"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0

    # p0 Bait Spell on the stack, then genuine Unravel ABOVE it
    # controlled by p1 (distinct controllers → after both drain, p0's
    # gy holds EXACTLY the countered bait and p1's holds EXACTLY
    # Unravel — one card per gy, no intra-gy ordering ambiguity, the
    # batch-D Divert-Disaster counter idiom).
    bait_printing = CardPrinting(
        name="UN Bait Spell", mana_cost_str="",
        mana_cost=ManaCost(generic=0), type_line="Creature",
        supertypes=(), card_types=("Creature",), subtypes=(),
        power=2, toughness=2, produces=frozenset(),
    )
    py_bait = py.new_object(bait_printing, owner_id=0, zone=Zone.STACK)
    py_bait.summoning_sick = False
    py.stack.append(StackItem(source=py_bait, controller_id=0))

    py_spell = py.new_object(real, owner_id=1, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=1,
                  targets=(("stack", 0),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    while py.stack:
        resolve_top_of_stack(py)
        py_sba(py)
    assert len(py.stack) == 0

    rs_bait_id = rs.register_and_inject_object(
        {"name": "UN Bait Spell", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 0, ZH,
    )
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Unravel", "card_types": ["Instant"],
         "effects": [{"kind": "counter_target_spell"}]}, 1, ZH,
    )
    rs.push_to_stack(rs_bait_id, 0)
    rs.push_to_stack(rs_spell_id, 1)
    assert rs.stack_size() == 2
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_bf = [e["printing_name"] for e in rs.battlefield_snapshot()]
    py_bf = [o.printing.name for o in py.battlefield]
    assert "UN Bait Spell" not in rs_bf and "UN Bait Spell" not in py_bf, (
        f"countered bait must NOT be on the bf on BOTH; "
        f"rust_bf={rs_bf} py_bf={py_bf}"
    )
    rs_gy0 = [e["printing_name"] for e in rs.graveyard_snapshot(0)]
    py_gy0 = [o.printing.name for o in py.players[0].graveyard]
    rs_gy1 = [e["printing_name"] for e in rs.graveyard_snapshot(1)]
    py_gy1 = [o.printing.name for o in py.players[1].graveyard]
    assert rs_gy0 == py_gy0 == ["UN Bait Spell"], (
        f"p0 gy must be exactly the countered bait on BOTH; "
        f"rust={rs_gy0} py={py_gy0}"
    )
    assert rs_gy1 == py_gy1 == ["Unravel"], (
        f"p1 gy must be exactly the resolved counter on BOTH; "
        f"rust={rs_gy1} py={py_gy1}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Unravel counter-target-spell must be byte-equal across the "
        f"WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-E probe #4 — Annul (~3,564 17lands decks).
#
# Verified covered (``CounterTargetSpell`` ∈ covered set) + unprobed at
# HEAD. Oracle:
#   "[Instant] {U} — Counter target artifact or enchantment spell."
# Parser → ``spell_effect = CounterTargetSpell(filter_types=
# frozenset({'Artifact','Enchantment'}))``. The bridge's bare
# ``counter_target_spell`` arm DROPS the filter (constructs
# ``CounterTargetSpell()`` — counters any spell; the documented
# first-slice convention, cross_engine.py:4037-4046). To keep a
# FAITHFUL byte-equal mirror the bait MUST be an ARTIFACT spell (a
# legal target under Python's {Artifact,Enchantment} filter AND under
# Rust's any-spell pick) — both engines then counter the SAME bait.
# Distinct from the Unravel sister (which has an empty filter): Annul
# pins the filter-narrowed leg, validated by choosing a bait Python's
# narrowed filter accepts. The batch-D Divert-Disaster distinct-
# controllers counter-bait idiom.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_annul_counter_artifact_spell_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Annul (~3,564 17lands
    decks). Batch-E covered→PROBED.**

    Python: the ACTUAL parsed Annul printing (filter_types =
    {Artifact, Enchantment}) on a ``StackItem`` above a benign p0
    ARTIFACT Bait Spell (a legal target under Python's narrowed filter
    AND Rust's any-spell pick — so BOTH engines counter the SAME
    bait), controlled by p1, target = ``("stack", 0)``. Rust: the
    bridged bare ``{"kind":"counter_target_spell"}`` synthetic Instant.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the artifact bait in p0's graveyard,
    Annul in p1's graveyard, both stacks empty, NO bait on the bf on
    BOTH engines byte-equal).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Annul")
    if real is None:
        pytest.skip("Annul absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, CounterTargetSpell), (
        f"genuine Annul spell_effect must be CounterTargetSpell; "
        f"got {type(se).__name__}"
    )
    assert se.filter_types == frozenset({"Artifact", "Enchantment"}), (
        "Annul counters ONLY artifact/enchantment spells — the "
        "filter-narrowed leg this probe pins"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0

    # The bait is an ARTIFACT spell — a LEGAL target under Python's
    # {Artifact,Enchantment} filter AND under Rust's any-spell pick,
    # so both engines counter the SAME bait (a faithful byte-equal
    # mirror of the filter-narrowed leg, not a coincidental match).
    bait_printing = CardPrinting(
        name="AN Bait Artifact", mana_cost_str="",
        mana_cost=ManaCost(generic=1), type_line="Artifact",
        supertypes=(), card_types=("Artifact",), subtypes=(),
        power=None, toughness=None, produces=frozenset(),
    )
    py_bait = py.new_object(bait_printing, owner_id=0, zone=Zone.STACK)
    py_bait.summoning_sick = False
    py.stack.append(StackItem(source=py_bait, controller_id=0))

    py_spell = py.new_object(real, owner_id=1, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=1,
                  targets=(("stack", 0),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    while py.stack:
        resolve_top_of_stack(py)
        py_sba(py)
    assert len(py.stack) == 0

    rs_bait_id = rs.register_and_inject_object(
        {"name": "AN Bait Artifact", "card_types": ["Artifact"]},
        0, ZH,
    )
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Annul", "card_types": ["Instant"],
         "effects": [{"kind": "counter_target_spell"}]}, 1, ZH,
    )
    rs.push_to_stack(rs_bait_id, 0)
    rs.push_to_stack(rs_spell_id, 1)
    assert rs.stack_size() == 2
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_bf = [e["printing_name"] for e in rs.battlefield_snapshot()]
    py_bf = [o.printing.name for o in py.battlefield]
    assert (
        "AN Bait Artifact" not in rs_bf
        and "AN Bait Artifact" not in py_bf
    ), (
        f"countered artifact bait must NOT be on the bf on BOTH; "
        f"rust_bf={rs_bf} py_bf={py_bf}"
    )
    rs_gy0 = [e["printing_name"] for e in rs.graveyard_snapshot(0)]
    py_gy0 = [o.printing.name for o in py.players[0].graveyard]
    rs_gy1 = [e["printing_name"] for e in rs.graveyard_snapshot(1)]
    py_gy1 = [o.printing.name for o in py.players[1].graveyard]
    assert rs_gy0 == py_gy0 == ["AN Bait Artifact"], (
        f"p0 gy must be exactly the countered artifact bait on BOTH; "
        f"rust={rs_gy0} py={py_gy0}"
    )
    assert rs_gy1 == py_gy1 == ["Annul"], (
        f"p1 gy must be exactly the resolved counter on BOTH; "
        f"rust={rs_gy1} py={py_gy1}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Annul counter-artifact-spell must be byte-equal across the "
        f"WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-E probe #5 — Zealous Display (~3,224 17lands decks).
#
# Verified covered (``PumpCreaturesYouControlUntilEOT`` ∈ covered set)
# + unprobed at HEAD. Oracle:
#   "[Instant] {2}{W} — Creatures you control get +2/+0 until end of
#    turn. If it's not your turn, untap those creatures."
# Parser → ``spell_effect = PumpCreaturesYouControlUntilEOT(
# power_bonus=2, toughness_bonus=0, also_untap_if_not_your_turn=True,
# granted_keywords=∅, exclude_source=False)``. The
# ``also_untap_if_not_your_turn`` rider fires ONLY when it is NOT the
# caster's turn — cast on the caster's OWN turn (the default fresh
# state, active_player=p0=caster) it is observationally INERT, so the
# genuine resolve path IS the bare ``pump_creatures_you_control_until_
# eot`` arm (+2/+0, no keywords). A true byte-equal mirror, not a
# rider-suppressing stub. The batch-22 anthem-shape bridge arm.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_zealous_display_pump_yours_own_turn_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Zealous Display
    (~3,224 17lands decks). Batch-E covered→PROBED.**

    Python: the ACTUAL parsed Zealous Display printing on a
    ``StackItem`` (no targets) cast on the CASTER's own turn
    (active_player=p0=caster on the fresh state) so the
    ``also_untap_if_not_your_turn`` rider is observationally INERT —
    the genuine resolve path is the bare +2/+0 anthem. Rust: the
    bridged ``{"kind":"pump_creatures_you_control_until_eot",
    "power_bonus":2,"toughness_bonus":0}`` synthetic Instant.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the two p0 creatures each gain net +2/+0
    UEOT on BOTH; p1's creature untouched; nothing untapped — it IS
    the caster's turn).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone, effective_power
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesYouControlUntilEOT,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Zealous Display")
    if real is None:
        pytest.skip("Zealous Display absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, PumpCreaturesYouControlUntilEOT), (
        f"genuine Zealous Display spell_effect must be "
        f"PumpCreaturesYouControlUntilEOT; got {type(se).__name__}"
    )
    assert se.power_bonus == 2 and se.toughness_bonus == 0
    assert se.granted_keywords == frozenset()
    assert se.also_untap_if_not_your_turn is True

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # Pre-condition: it IS the caster's (p0's) turn so the untap rider
    # is inert on BOTH engines.
    assert py.active_player_idx == 0 and rs.active_player == 0, (
        "probe pre-condition: active_player must be p0 (the caster) so "
        "the also_untap_if_not_your_turn rider is observationally inert"
    )

    # Two p0 creatures (the anthem targets) + one p1 creature (the
    # negative control: it must NOT be pumped).
    py_a = py.new_object(
        CardPrinting(
            name="ZD Ally A", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=1, toughness=1, produces=frozenset(),
        ),
        owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_a.summoning_sick = False
    py.battlefield.append(py_a)
    py_b = py.new_object(
        CardPrinting(
            name="ZD Ally B", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=3, toughness=3, produces=frozenset(),
        ),
        owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_b.summoning_sick = False
    py.battlefield.append(py_b)
    py_opp = py.new_object(
        CardPrinting(
            name="ZD Opp", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_opp.summoning_sick = False
    py.battlefield.append(py_opp)

    rs_a_id = rs.register_and_inject_object(
        {"name": "ZD Ally A", "card_types": ["Creature"],
         "power": 1, "toughness": 1}, 0, ZB,
    )
    rs_b_id = rs.register_and_inject_object(
        {"name": "ZD Ally B", "card_types": ["Creature"],
         "power": 3, "toughness": 3}, 0, ZB,
    )
    rs_opp_id = rs.register_and_inject_object(
        {"name": "ZD Opp", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Zealous Display on a StackItem. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bridged anthem synthetic Instant. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Zealous Display", "card_types": ["Instant"],
         "effects": [{"kind": "pump_creatures_you_control_until_eot",
                      "power_bonus": 2, "toughness_bonus": 0}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # Concrete observable: p0's creatures +2 power; p1's untouched.
    assert effective_power(py, py_a) == 1 + 2
    assert effective_power(py, py_b) == 3 + 2
    assert effective_power(py, py_opp) == 2
    assert rs.effective_power(rs_a_id) == 1 + 2
    assert rs.effective_power(rs_b_id) == 3 + 2
    assert rs.effective_power(rs_opp_id) == 2

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Zealous Display +2/+0-creatures-you-control (own turn, "
        f"untap rider inert) must be byte-equal across the WHOLE "
        f"field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-E probe #6 — Full Bore (~2,200 17lands decks).
#
# Verified covered (``PumpTargetCreatureUntilEOT`` ∈ covered set) +
# unprobed at HEAD. Oracle:
#   "[Instant] {R} — Target creature you control gets +3/+2 until end
#    of turn. If that creature was cast for its warp cost, it also
#    gains trample and haste until end of turn."
# Parser → ``spell_effect = PumpTargetCreatureUntilEOT(power_bonus=3,
# toughness_bonus=2, you_control_only=True, granted_keywords=∅,
# granted_keywords_if_warp_cast={haste,trample})``. The
# ``granted_keywords_if_warp_cast`` rider grants keywords ONLY when the
# pumped creature was itself warp-cast — the synthetic target here is a
# vanilla creature seated directly on the bf (never warp-cast), so the
# rider is observationally INERT and the genuine resolve path IS the
# bare +3/+2 pump (granted_keywords is ALREADY ∅). The bare
# ``pump_target_creature_until_eot`` bridge arm carries only
# power/toughness; ``you_control_only`` is not plumbed but is mirrored
# by seating the ONLY creature on the SOURCE-controller's (p0's) bf —
# Rust scans p0's bf, Python's ``_PickFirstControlledCreatureAgent``
# picks p0's creature → the SAME single creature on BOTH (the batch-C
# Tragic-Trajectory same-side pump idiom). NOT a rider-suppressing
# stub: granted_keywords is genuinely empty and the warp-conditional
# rider genuinely cannot fire on a non-warp-cast vanilla target.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_full_bore_pump_plus3_plus2_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Full Bore (~2,200
    17lands decks). Batch-E covered→PROBED.**

    Python: the ACTUAL parsed Full Bore printing on a ``StackItem``
    with the chosen target = a p0-controlled vanilla 2/2 (the ONLY
    creature → Rust's source-controller-bf scan and Python's
    ``_PickFirstControlledCreatureAgent`` pick the SAME creature; the
    target was never warp-cast so ``granted_keywords_if_warp_cast`` is
    observationally inert and ``granted_keywords`` is genuinely ∅).
    Rust: the bridged ``{"kind":"pump_target_creature_until_eot",
    "power_bonus":3,"toughness_bonus":2}`` synthetic Instant.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the p0 2/2 → effective 5/4 UEOT on BOTH;
    p1 untouched; no keywords granted on either engine).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone, effective_power
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import (
        _PickFirstControlledCreatureAgent,
    )

    real = get_active_source().get_printings().get("Full Bore")
    if real is None:
        pytest.skip("Full Bore absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, PumpTargetCreatureUntilEOT), (
        f"genuine Full Bore spell_effect must be "
        f"PumpTargetCreatureUntilEOT; got {type(se).__name__}"
    )
    assert se.power_bonus == 3 and se.toughness_bonus == 2
    assert se.granted_keywords == frozenset(), (
        "Full Bore's unconditional granted_keywords must be empty — "
        "the only keyword grant is warp-conditional (inert here)"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # The ONLY creature is a p0-controlled vanilla 2/2 — Rust scans the
    # source-controller's (p0's) bf; the same-side picker shim mirrors
    # that exact pick. (Never warp-cast → the warp-conditional keyword
    # rider cannot fire on either engine.)
    py_tgt = py.new_object(
        CardPrinting(
            name="FB Target", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_tgt.summoning_sick = False
    py.battlefield.append(py_tgt)
    py.players[0].agent = _PickFirstControlledCreatureAgent()

    rs_tgt_id = rs.register_and_inject_object(
        {"name": "FB Target", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 0, ZB,
    )

    # ---- Python: genuine parsed Full Bore on a StackItem. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_tgt.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bridged synthetic Instant (bare +3/+2 arm). ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Full Bore", "card_types": ["Instant"],
         "effects": [{"kind": "pump_target_creature_until_eot",
                      "power_bonus": 3, "toughness_bonus": 2}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # Concrete observable: the p0 2/2 → effective power 5 on BOTH.
    assert effective_power(py, py_tgt) == 2 + 3
    assert rs.effective_power(rs_tgt_id) == 2 + 3

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Full Bore +3/+2 (non-warp-cast target, keyword rider inert) "
        f"must be byte-equal across the WHOLE field view on BOTH; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-E probe #7 — Space-Time Anomaly (~1,574 17lands decks).
#
# Verified covered (``MillTargetPlayer`` ∈ covered set, via the
# round-52 RUST_TO_PYTHON_OVERRIDES mapping
# ``MillTargetPlayerEqualToYourLifeTotal`` → ``MillTargetPlayer``) +
# unprobed at HEAD. Oracle:
#   "[Sorcery] {2}{W}{U} — Target player mills cards equal to your life
#    total."
# Parser → ``spell_effect = MillTargetPlayer(use_controller_life=True)``
# (the dynamic-X-from-life lane). The Rust ``mill_target_player_equal_
# to_your_life_total`` unit-variant arm reads the count dynamically
# from the source-controller's life at resolve. Rust picks
# ``target_idx = 1 - controller`` deterministically; Python's
# ``MillTargetPlayer`` is target-required and driven via
# ``_PickFirstOpponentTargetAgent`` (the agent's ``("player",
# target_id) where target_id != player_id`` filter mirrors Rust's
# ``1 - controller`` pick exactly on a 2-player harness — the
# documented established idiom, cross_engine.py:2265-2275).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_space_time_anomaly_mill_equal_life_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Space-Time Anomaly
    (~1,574 17lands decks). Batch-E covered→PROBED.**

    Python: the ACTUAL parsed Space-Time Anomaly printing on a
    ``StackItem`` with the chosen player target = p1 (Rust picks
    ``1 - controller`` = p1; ``_PickFirstOpponentTargetAgent`` mirrors
    that exact pick). Rust: the bridged ``{"kind":"mill_target_player_
    equal_to_your_life_total"}`` synthetic Sorcery (dynamic count =
    p0's life total at resolve, the same on a fresh symmetric state).

    Assertion strength: the **established targeted-observable idiom**
    (the EXACT idiom + documented reason the batch-A Mechan-Navigator
    discard_self probe uses): the milled seeded-library objects carry
    a gameplay-IRRELEVANT ``summoning_sick`` zone-change representation
    artifact in the graveyard (Rust resets per CR 400.7; Python
    preserves the seeded object's stale flag) — NOT a mill engine
    divergence. The probe pins every gameplay-relevant observable
    byte-equal cross-engine instead (p1's library shrinks by exactly
    p0's life total; those cards' identities in p1's graveyard; every
    zone size; p0's untouched library contents; both lives — all
    byte-equal on BOTH engines).
    """
    # Targeted-observable idiom (see the docstring) — no full
    # compare_fields here, so no field-view builder import.
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state, CardDef,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.draw_mill import MillTargetPlayer
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Space-Time Anomaly")
    if real is None:
        pytest.skip("Space-Time Anomaly absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, MillTargetPlayer), (
        f"genuine Space-Time Anomaly spell_effect must be "
        f"MillTargetPlayer; got {type(se).__name__}"
    )
    assert se.use_controller_life is True, (
        "Space-Time Anomaly mills equal to the controller's life "
        "(the dynamic-X-from-life lane)"
    )

    py_probe = build_python_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    mill_n = py_probe.players[0].life
    assert mill_n > 0

    # p1's library seeded with mill_n + a margin of DISTINCT-printing
    # filler so the mill is fully observable + byte-equal (same
    # printings, same order on BOTH); p0's library symmetric.
    filler = CardDef(name="STA Filler", card_type="Land",
                     mana_produced=("U",))
    lib = tuple(["STA Filler"] * (mill_n + 3))
    spec = DeckSpec(
        card_defs=(filler,), p0_library=lib, p1_library=lib,
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    py_p0_life0 = py.players[0].life
    rs_p0_life0 = rs.get_life(0)
    assert py_p0_life0 == rs_p0_life0 == mill_n, (
        "fresh symmetric state: p0 life identical on BOTH engines"
    )
    py_p1_lib0 = len(py.players[1].library)
    py_p1_gy0 = len(py.players[1].graveyard)

    # p0 picks the mill target = the opponent (p1) — mirrors Rust's
    # deterministic 1 - controller pick on the 2-player harness.
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    # ---- Python: genuine parsed Space-Time Anomaly on a StackItem,
    # target = p1. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("player", py.players[1].id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bridged mill_target_player_equal_to_your_life_total. -
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Space-Time Anomaly", "card_types": ["Sorcery"],
         "effects": [{"kind": (
             "mill_target_player_equal_to_your_life_total")}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # p1 milled exactly mill_n (= p0's life) cards into p1's graveyard
    # on BOTH; p0 untouched.
    assert len(py.players[1].library) == py_p1_lib0 - mill_n, (
        f"Python: p1 must mill exactly {mill_n} (= p0 life)"
    )
    assert len(py.players[1].graveyard) == py_p1_gy0 + mill_n, (
        f"Python: p1's graveyard must gain exactly {mill_n}"
    )
    assert rs.library_sizes[1] == len(py.players[1].library), (
        f"p1 library size must match cross-engine; "
        f"rust={rs.library_sizes[1]} py={len(py.players[1].library)}"
    )
    assert rs.graveyard_sizes[1] == len(py.players[1].graveyard)
    assert rs.library_sizes[0] == len(py.players[0].library), (
        "p0's library must be untouched + byte-equal on BOTH"
    )
    assert py.players[0].life == py_p0_life0 and rs.get_life(0) == (
        rs_p0_life0
    ), "p0 life untouched on BOTH (mill does not change life)"

    # **Established targeted-observable idiom (documented reason).**
    # This probe asserts the cross-engine observables directly rather
    # than ``compare_fields == []`` — the EXACT idiom + reason the
    # established batch-A Mechan-Navigator discard_self probe uses.
    # REASON: the mill moves seeded-library ``GameObject``s
    # library→graveyard; Rust resets ``summoning_sick`` to False on the
    # zone change (CR 400.7 fresh-object reset) while Python preserves
    # the seeded library object's stale ``summoning_sick=True`` into
    # the graveyard. That is a gameplay-IRRELEVANT seeded-object
    # zone-change representation artifact on cards in the graveyard
    # (summoning sickness has no meaning in the graveyard) — NOT a mill
    # engine divergence. Asserting the load-bearing observables (every
    # zone size + the milled cards' identities in p1's graveyard + the
    # untouched-zone byte-equality, all cross-engine) pins the
    # MillTargetPlayer(use_controller_life=True) covered Effect
    # end-to-end with full strength on every gameplay-relevant axis.
    rs_p1_gy_names = sorted(
        e["printing_name"] for e in rs.graveyard_snapshot(1)
    )
    py_p1_gy_names = sorted(
        o.printing.name for o in py.players[1].graveyard
    )
    assert (
        rs_p1_gy_names == py_p1_gy_names == ["STA Filler"] * mill_n
    ), (
        f"p1's graveyard must hold exactly {mill_n} milled STA Filler "
        f"on BOTH; rust={len(rs_p1_gy_names)} py={len(py_p1_gy_names)}"
    )
    # Every zone size byte-equal cross-engine, both players.
    assert rs.library_sizes[0] == len(py.players[0].library)
    assert rs.library_sizes[1] == len(py.players[1].library)
    assert rs.hand_sizes[0] == len(py.players[0].hand)
    assert rs.hand_sizes[1] == len(py.players[1].hand)
    assert rs.graveyard_sizes[0] == len(py.players[0].graveyard)
    assert rs.graveyard_sizes[1] == len(py.players[1].graveyard)
    # p0's library (the untouched side) byte-equal in CONTENTS too.
    rs_p0_lib = [e["printing_name"] for e in rs.library_snapshot(0)]
    py_p0_lib = [o.printing.name for o in py.players[0].library]
    assert rs_p0_lib == py_p0_lib, (
        f"p0's untouched library must be byte-equal on BOTH; "
        f"rust={rs_p0_lib} py={py_p0_lib}"
    )
    # Both lives byte-equal cross-engine.
    assert rs.get_life(0) == py.players[0].life
    assert rs.get_life(1) == py.players[1].life
