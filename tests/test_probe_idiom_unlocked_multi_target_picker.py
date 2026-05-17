"""Multi-target-picker idiom + the genuine real-EoE probe it unlocks.

CONTINUOUS-PIPELINE phase — NEW HARNESS-IDIOM slice #2. The
cleanly-probe-constructible covered-but-unprobed frontier is
GENUINELY EXHAUSTED for the *existing* idiom set (batch-F's honest
conclusion). The prior idiom slice landed the highest-leverage of the
5 batch-F-flagged missing idioms (the optional-cost mirror, 3 cards /
~53,668 decks, ``15c57a66``). Verify-first against the LIVE pool
(``measure_pool_parity.classify_pool`` + ``scout_r58._deck_counts``)
re-confirmed the NEXT highest-leverage missing idiom DECISIVELY:

  | missing idiom            | clean single-idiom unlock | 17lands decks |
  |--------------------------|---------------------------|--------------:|
  | optional-cost mirror     | DONE (15c57a66) — 3 cards  |   ~53,668 |
  | **multi-target picker**  | **Weftblade Enhancer**    |    **14,406** |
  | search-agent-path        | Starfield Shepherd        |    12,788 |
  | (multi-idiom, deferred)  | + The Seriema / Cosmogrand|    (split) |
  | StateBound predicate     | Sunstar Expansionist      |    12,252 |

The multi-target picker is the highest-leverage SINGLE clean idiom
remaining. Verify-first established (read-only at LIVE HEAD):

* The ``put_plus_one_counter_on_each_of_up_to_n_target_creatures``
  bridge arm's OWN docstring (``cross_engine.py``:3903-3919) EXPLICITLY
  defers the cross-engine end-to-end probe pending exactly this shim
  ("the cross-engine probe lands when a multi-target shim slice
  ships"); the batch-C agent dropped Weftblade Enhancer on this
  precedent (``test_probe_covered_unprobed_c.py``:76-92).
* It unlocks EXACTLY ONE deck-bearing card — **Weftblade Enhancer
  (14,406 17lands decks)**. The only other consumer (``Grand Entryway
  // Elegant Rotunda``) is 0-deck and a non-constructible split card;
  pinning it would be padding. Honest single-card unlock — NOT >1.
* The search-agent-path tranche (Starfield Shepherd 12,788 + The
  Seriema 3,504 + Cosmogrand Zenith 3,026) is NOT a single clean
  idiom: it needs a modal-choice mirror AND a library-search agent
  path AND each printed card "carries additional triggers / may_fail
  asymmetric agent paths" (the ``search_library_for_card`` bridge
  arm's OWN docstring at ``cross_engine.py``:3774-3781 explicitly
  defers them as a multi-idiom surface, NOT a clean unlock). So the
  multi-target picker — a single focused ``_PickFirst*``-canon shim
  cleanly unlocking 14,406 decks — is the correct verify-first pick.

THE IDIOM (``tests/parity/_picker_shims.
_PickUpToNRustIteratorOrderAgent``)
------------------------------------------------------------------
``Effect::PutPlusOneCounterOnEachOfUpToNTargetCreatures { max_n }``
(Weftblade-Enhancer shape: "When this creature enters, put a +1/+1
counter on each of up to two target creatures"). Rust resolves the
multi-target with NO agent ambiguity (``state_ops_resolve.rs``:
8731-8805 — locate source controller ``cidx``, collect the FIRST
``min(max_n, total)`` creatures by iterating ``[cidx, oidx]`` and
each player's ``battlefield`` Vec in INSERTION order, no
PendingDecision, no pause, no decline path). Python is target-driven:
``requires_target=True``, ``target_count_range=(0, max_n)``; the
Decision pipeline (``actions.py`` ~3215-3262) calls
``Agent.choose_target`` ONCE PER SLOT with the pool shrinking by each
prior pick. The default base ``Agent`` RAISES on ``choose_target`` so
a real cross-engine probe cannot even run.
``_PickUpToNRustIteratorOrderAgent`` forces Python onto Rust's LONE
deterministic branch by returning, each per-slot call, the offered
candidate with the smallest Rust priority key ``(side_rank,
per_side_bf_insertion_index)`` — controller-side bf order first, then
opponent-side bf order, exactly Rust's nested
``for &pidx in &[cidx, oidx] { for obj in bf.iter() }`` scan. It adds
NO degree of freedom Rust lacks — the established ``_PickFirst*`` /
``_SacrificeFirstAgent`` / optional-cost-mirror canon (force Python
onto Rust's single at-resolve path). It is a NEW shim (not a reuse of
``_PickFirstBattlefieldCreatureEitherSideAgent``, which is GLOBAL-bf-
index-keyed and correct only for its one-pick-per-side consumer)
precisely because Rust's resolve here is SIDE-PARTITIONED (all of the
controller's creatures, in controller-bf order, BEFORE any opponent
creature).

BYTE-EQUAL-SAFETY DESIGN (no Python-vs-Rust asymmetry introduced)
-----------------------------------------------------------------
The idiom drives the up-to-N counter-spread WRAPPER IDENTICALLY on
both engines. Verified on a MINIMAL synthetic case (the focused
self-test below): a synthetic
``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)`` ETB carrier
over a MIXED controller/opponent bf, built from ONE trigger-dict on
BOTH engines (the proven ``_ta_dict_to_python_triggered_ability``
bridge round-trip), yields ``compare_fields == []`` over the WHOLE
field view. The idiom is byte-equal by construction — the SAME set of
creatures receives exactly one +1/+1 counter on BOTH engines, in
Rust's exact scan order capped at ``max_n``.

HONEST SCOPE — Weftblade Enhancer is a BARE consumer (no rider)
----------------------------------------------------------------
Verify-first confirmed the genuine Weftblade Enhancer printing's ETB
is a BARE ``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)``
with no condition, no UEOT rider, no composed second effect. So the
genuine probe asserts FULL ``compare_fields == []`` (the strongest
tier) — nothing reaches an inner leg, the mirror is exact. (Weftblade
Enhancer also carries a ``warp_cost`` — irrelevant here: the probe
casts/seats the creature normally, the warp alt-cost is never paid;
the ETB resolve path is identical regardless of how it entered.)

NEW DEDICATED MODULE — registered in
``scripts/measure_pool_parity.PROBE_MODULES``. Avoids all
sibling/protected collisions; touches no STALENESS-SENTINEL.
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


def _seat_vanilla_creature_bf(py, name, owner_id):
    """Seat a plain 2/2 vanilla creature on ``owner_id``'s battlefield,
    non-summoning-sick, untapped, undamaged — a bait target. Seated in
    bf-insertion order so Python's per-side bf position and Rust's
    per-player ``battlefield`` Vec position coincide."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    o = py.new_object(
        CardPrinting(
            name=name, mana_cost_str="", mana_cost=ManaCost(generic=0),
            type_line="Creature", supertypes=(),
            card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
            keywords=frozenset(),
        ),
        owner_id=owner_id, zone=Zone.BATTLEFIELD,
    )
    o.summoning_sick = False
    o.tapped = False
    o.damage = 0
    o.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(o)
    return o


def _rs_seat_vanilla_creature(rs, name, owner_id):
    """Register a plain 2/2 vanilla creature on ``owner_id``'s Rust
    battlefield (ZONE_BATTLEFIELD == 2)."""
    return rs.register_and_inject_object(
        {
            "name": name, "card_types": ["Creature"],
            "mana_cost": {"generic": 0}, "power": 2, "toughness": 2,
            "effects": [], "triggered_abilities": [],
        },
        owner_id, 2,
    )


def _fv_diff(parity_smoke_mod, py, rs):
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    return compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )


# ---------------------------------------------------------------------
# IDIOM SELF-TEST — the multi-target picker mirror is byte-equal on a
# minimal synthetic case (the byte-equal-safety proof for the idiom
# itself, before it is used on any real card).
# ---------------------------------------------------------------------


def test_multi_target_picker_idiom_self_test_byte_equal(parity_smoke):
    """**Focused idiom self-test — the multi-target picker mirror is
    byte-equal on a MINIMAL synthetic
    ``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)`` case.**

    A synthetic ``max_n=2`` ETB carrier built from ONE trigger-dict on
    BOTH engines (the proven ``_ta_dict_to_python_triggered_ability``
    bridge round-trip). The bf is MIXED: TWO p0-controlled bait
    creatures + ONE p1-controlled bait creature, seated in an order
    that interleaves the sides on the global ``state.battlefield`` —
    so a GLOBAL-bf-index shim would diverge from Rust's
    SIDE-PARTITIONED scan but the new two-level
    ``(side_rank, per_side_bf_index)`` shim does not.
    ``_PickUpToNRustIteratorOrderAgent`` on p0 forces Python onto
    Rust's lone deterministic branch.

    Expectation: Rust's scan picks the FIRST 2 creatures controller-bf
    first then opponent-bf — i.e. the TWO p0 baits get a +1/+1 counter
    and the p1 bait does NOT (Rust fills ``max_n=2`` from the
    controller side before reaching the opponent). FULL
    ``compare_fields == []`` over the WHOLE field view. This proves the
    idiom introduces NO Python-vs-Rust asymmetry — it reproduces Rust's
    side-partitioned iterator exactly, including the controller-before-
    opponent precedence that a naive global-index shim would break.
    """
    sys.path.insert(
        0, str(pathlib.Path(__file__).resolve().parent)
    )
    from parity._picker_shims import _PickUpToNRustIteratorOrderAgent
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba

    trig = {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "put_plus_one_counter_on_each_of_up_to_n_target_creatures",
            "max_n": 2,
        },
    }
    py_ta = _ta_dict_to_python_triggered_ability(trig)
    carrier = CardPrinting(
        name="SynthCounterCarrier", mana_cost_str="{4}",
        mana_cost=ManaCost(generic=4),
        type_line="Creature", supertypes=(),
        card_types=("Creature",), subtypes=(),
        power=3, toughness=4, produces=frozenset(),
        keywords=frozenset(), triggered_abilities=(py_ta,),
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    py.players[0].agent = _PickUpToNRustIteratorOrderAgent()
    # Interleave sides on the GLOBAL bf so a global-index shim would
    # mis-order: p0-A, p1-X, p0-B.  Rust's per-side scan still picks
    # p0-A then p0-B (controller side first, max_n=2 filled before
    # reaching p1-X).
    py_a = _seat_vanilla_creature_bf(py, "p0 Bait A", 0)
    py_x = _seat_vanilla_creature_bf(py, "p1 Bait X", 1)
    py_b = _seat_vanilla_creature_bf(py, "p0 Bait B", 0)

    py_spell = py.new_object(carrier, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    by_name = {o.printing.name: o for o in py.battlefield}
    assert by_name["p0 Bait A"].plus_one_counters == 1, (
        "Python: controller-side first creature must get +1/+1"
    )
    assert by_name["p0 Bait B"].plus_one_counters == 1, (
        "Python: controller-side second creature must get +1/+1 "
        "(max_n=2 fills BOTH controller baits before the opponent)"
    )
    assert by_name["p1 Bait X"].plus_one_counters == 0, (
        "Python: opponent creature must NOT get a counter — max_n=2 "
        "was exhausted by the two controller-side creatures (Rust's "
        "side-partitioned scan; a global-index shim would mis-target)"
    )

    # Rust: register in the SAME interleaved global order; the per-
    # player battlefield Vec keeps p0=[A,B], p1=[X].
    rs_a = _rs_seat_vanilla_creature(rs, "p0 Bait A", 0)
    rs_x = _rs_seat_vanilla_creature(rs, "p1 Bait X", 1)
    rs_b = _rs_seat_vanilla_creature(rs, "p0 Bait B", 0)
    rs_carrier = rs.register_and_inject_object(
        {"name": "SynthCounterCarrier", "card_types": ["Creature"],
         "mana_cost": {"generic": 4}, "power": 3, "toughness": 4,
         "effects": [], "triggered_abilities": [trig]}, 0, 0)
    rs.push_to_stack(rs_carrier, 0)
    rs.resolve_top_of_stack()
    n = 0
    while (rs.stack_size() > 0 or rs.has_pending_decision()) and n < 12:
        if rs.has_pending_decision():
            rs.auto_resolve_pending_decisions("default")
        else:
            rs.resolve_top_of_stack()
        n += 1
    rs.apply_sbas()

    rs_by_id = {e["id"]: e for e in rs.battlefield_snapshot()}
    assert rs_by_id[rs_a].get("counters", 0) == 1, (
        "Rust: controller-side first creature must get +1/+1"
    )
    assert rs_by_id[rs_b].get("counters", 0) == 1, (
        "Rust: controller-side second creature must get +1/+1"
    )
    assert rs_by_id[rs_x].get("counters", 0) == 0, (
        "Rust: opponent creature must NOT get a counter "
        "(side-partitioned scan, max_n=2 filled controller-side)"
    )

    diffs = _fv_diff(parity_smoke, py, rs)
    assert diffs == [], (
        f"multi-target picker idiom self-test must be byte-equal "
        f"across the WHOLE field view on BOTH (the idiom introduces "
        f"NO Python-vs-Rust asymmetry); diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Idiom-unlocked probe — Weftblade Enhancer (~14,406 17lands decks).
#
# Verified covered (PutPlusOneCounterOnEachOfUpToNTargetCreatures ∈
# covered set) + unprobed at HEAD. Genuine parsed printing:
#   3/4 Creature ({5}{W}, warp {2}{W}); ENTERS trigger →
#   PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2).
# BARE consumer — no condition, no rider, no composed effect; the
# multi-target picker mirror drives it FULL compare_fields byte-equal.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_weftblade_enhancer_up_to_n_counters_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Weftblade Enhancer
    (~14,406 17lands decks). Multi-target-picker idiom-unlocked
    covered→PROBED.**

    Python: the ACTUAL parsed Weftblade Enhancer printing (3/4
    Creature) cast as a spell, resolving to a permanent whose ENTERS
    trigger (``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)``)
    fires with ``_PickUpToNRustIteratorOrderAgent`` on p0 forcing
    Rust's lone deterministic at-resolve iterator. Rust: a bridged
    synthetic carrier with the EXACT
    enters/source_is_self/put_plus_one_counter_on_each_of_up_to_n_
    target_creatures(max_n=2) trigger dict.

    The bf is MIXED — TWO p0-controlled bait creatures + ONE
    p1-controlled bait creature, seated to interleave the sides on the
    global ``state.battlefield``. Rust's resolve
    (``state_ops_resolve.rs``:8731-8805) scans controller-bf first then
    opponent-bf, filling ``max_n=2`` from the two p0 baits BEFORE
    reaching the p1 bait. The genuine Weftblade Enhancer ETB is a BARE
    ``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)`` (no
    condition, no rider — verify-first confirmed), so the wrapper is
    the WHOLE observable.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the two p0 baits + the Enhancer itself,
    each with their byte-equal counter slot; the p1 bait at net 0 on
    BOTH; byte-equal — verified). Concretely double-pinned (the genuine
    parsed trigger is asserted to be the
    ``PutPlusOneCounterOnEachOfUpToNTargetCreatures`` shape with
    ``max_n == 2``; the picked creatures' net counters are 1/1/0 on
    BOTH).
    """
    sys.path.insert(
        0, str(pathlib.Path(__file__).resolve().parent)
    )
    from parity._picker_shims import _PickUpToNRustIteratorOrderAgent
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    )

    real = get_active_source().get_printings().get("Weftblade Enhancer")
    if real is None:
        pytest.skip("Weftblade Enhancer absent from active CardSource")
    assert "Creature" in real.card_types
    etb = next(
        (ta for ta in (real.triggered_abilities or ())
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, "Weftblade Enhancer must have an ENTERS trigger"
    assert isinstance(
        etb.effect, PutPlusOneCounterOnEachOfUpToNTargetCreatures
    ), (
        f"genuine Weftblade Enhancer ETB must be "
        f"PutPlusOneCounterOnEachOfUpToNTargetCreatures; got "
        f"{type(etb.effect).__name__}"
    )
    assert etb.effect.max_n == 2, (
        f"genuine Weftblade Enhancer max_n must be 2; got "
        f"{etb.effect.max_n}"
    )
    # BARE consumer assertion: no condition rider (the wrapper is the
    # whole observable; this is why FULL compare_fields is honest).
    assert getattr(etb, "condition", None) is None, (
        "Weftblade Enhancer ETB must be a BARE trigger (no condition "
        "rider) for the FULL-compare_fields byte-equal claim"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    py.players[0].agent = _PickUpToNRustIteratorOrderAgent()
    # Interleave sides on the GLOBAL bf: p0-A, p1-X, p0-B.
    py_a = _seat_vanilla_creature_bf(py, "WB Bait A (p0)", 0)
    py_x = _seat_vanilla_creature_bf(py, "WB Bait X (p1)", 1)
    py_b = _seat_vanilla_creature_bf(py, "WB Bait B (p0)", 0)

    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_by_name = {o.printing.name: o for o in py.battlefield}
    assert "Weftblade Enhancer" in py_by_name, (
        "Weftblade Enhancer must resolve onto p0's battlefield"
    )
    assert py_by_name["WB Bait A (p0)"].plus_one_counters == 1, (
        "Python: controller-side first bait must get +1/+1 "
        "(Rust scan order)"
    )
    assert py_by_name["WB Bait B (p0)"].plus_one_counters == 1, (
        "Python: controller-side second bait must get +1/+1 "
        "(max_n=2 fills BOTH p0 baits before the opponent)"
    )
    assert py_by_name["WB Bait X (p1)"].plus_one_counters == 0, (
        "Python: opponent bait must NOT get a counter — max_n=2 was "
        "exhausted by the two controller-side baits"
    )
    # The Enhancer itself is NOT a legal self-target only by chance of
    # ordering: Rust scans controller bf which now includes the
    # Enhancer; but it ENTERS AFTER the two baits (higher bf index),
    # and max_n=2 is filled by the two baits first — so the Enhancer
    # is unmodified on BOTH. Pin it explicitly.
    assert py_by_name["Weftblade Enhancer"].plus_one_counters == 0, (
        "Python: the Enhancer enters AFTER the two p0 baits; max_n=2 "
        "is filled by the baits, so the Enhancer itself stays net 0"
    )

    # ---- Rust: bridged synthetic carrier with the same trigger
    # shape; register the baits in the SAME interleaved global order so
    # the per-player battlefield Vec is p0=[A,B,Enhancer], p1=[X]. ----
    rs_a = _rs_seat_vanilla_creature(rs, "WB Bait A (p0)", 0)
    rs_x = _rs_seat_vanilla_creature(rs, "WB Bait X (p1)", 1)
    rs_b = _rs_seat_vanilla_creature(rs, "WB Bait B (p0)", 0)
    rs_enh = rs.register_and_inject_object(
        {
            "name": "Weftblade Enhancer",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 5, "W": 1},
            "power": 3, "toughness": 4, "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": (
                            "put_plus_one_counter_on_each_of_up_to_n_"
                            "target_creatures"
                        ),
                        "max_n": 2,
                    },
                }
            ],
        },
        0, 0,
    )
    rs.push_to_stack(rs_enh, 0)
    rs.resolve_top_of_stack()
    n = 0
    while (rs.stack_size() > 0 or rs.has_pending_decision()) and n < 12:
        if rs.has_pending_decision():
            rs.auto_resolve_pending_decisions("default")
        else:
            rs.resolve_top_of_stack()
        n += 1
    rs.apply_sbas()

    rs_by_id = {e["id"]: e for e in rs.battlefield_snapshot()}
    assert rs_by_id[rs_a].get("counters", 0) == 1, (
        "Rust: controller-side first bait must get +1/+1"
    )
    assert rs_by_id[rs_b].get("counters", 0) == 1, (
        "Rust: controller-side second bait must get +1/+1"
    )
    assert rs_by_id[rs_x].get("counters", 0) == 0, (
        "Rust: opponent bait must NOT get a counter "
        "(side-partitioned scan, max_n=2 filled controller-side)"
    )
    assert rs_by_id[rs_enh].get("counters", 0) == 0, (
        "Rust: the Enhancer enters AFTER the two p0 baits; max_n=2 "
        "filled by the baits — Enhancer stays net 0"
    )

    diffs = _fv_diff(parity_smoke, py, rs)
    assert diffs == [], (
        f"Weftblade Enhancer up-to-N counter-spread must be "
        f"byte-equal across the WHOLE field view on BOTH (the "
        f"multi-target picker mirror introduces NO Python-vs-Rust "
        f"asymmetry); diffs={diffs}"
    )
