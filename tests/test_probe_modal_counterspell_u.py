"""Genuine real-EoE cross-engine byte-equality probes — batch U.

PIVOT EXTENSION — round 5 modal + counter-spell lane.

MISSION
-------
Extend the modal / counter-spell byte-equality probe surface started in
batch R (``tests/test_probe_may_do_r.py``).  Batch U searches the full
covered-by-construction-but-unprobed set for additional EoE Instant cards
whose ``spell_effect`` is ``ModalChooseOne(...)`` or
``CounterTargetSpell(filter_types=frozenset())`` and adds genuine
real-EoE byte-equal probes for each remaining clean candidate.

WHAT EACH PROBE ASSERTS (identical bar to batches A-R)
-------------------------------------------------------
Every probe drives the **ACTUAL parsed EoE pool printing** on the Python
side (``get_active_source().get_printings().get("<card>")`` — NOT a
synthetic stub) against a bridged synthetic carrier on the Rust side
(``register_and_inject_object`` carrying the SAME effect dict), fires
the EXACT real effect through the production resolve path on BOTH
engines, and asserts **full ``compare_fields(...) == []``** (byte-equality
across the WHOLE cross-engine field view — the strongest tier).

> CAVEAT (mirrors ``docs/POOL_PARITY.md``): this is Effect+bridge-level
> byte-equality on a *controlled* cross-engine state, NOT full-game-
> trajectory parity. PROBED is the strongest evidence tier the campaign
> tracks; it is not a full random multi-turn game.

FAMILY SCOPE (this batch)
--------------------------
MODAL (ModalChooseOne) Instants and COUNTER-SPELL (CounterTargetSpell
with ``filter_types=frozenset()``) Instants ONLY — the two families
explored in batch R.  Sorcery-type cards in these families are reserved
for the sibling sorcery worktree (S).

RECONNAISSENCE — cumulative covered / probed state at HEAD
-----------------------------------------------------------
After batch R, the following cards are already PROBED in these lanes:

  | card                | family / arm                          |
  |---------------------|---------------------------------------|
  | Annul               | CounterTargetSpell {Artifact,Enchant} |
  | Divert Disaster     | CounterTargetSpell frozenset()        |
  | Don't Make a Sound  | CounterTargetSpell frozenset()        |
  | Get Out             | CounterTargetSpell {Creature,Enchant} |
  | Live or Die         | ModalChooseOne mode 1 → DestroyTarget |
  | Unravel             | CounterTargetSpell frozenset()        |

Remaining covered-by-construction candidates (Instant only):

  | card              | spell_effect                           | clean? |
  |-------------------|----------------------------------------|--------|
  | Twist Reality     | ModalChooseOne(                        | YES —  |
  |                   |   mode0=CounterTargetSpell(frozenset)|  probe |
  |                   |   mode1=ManifestDread(count=1))       |  mode 0|

PROBE STRATEGY — Twist Reality mode 0
--------------------------------------
``Twist Reality`` (Instant ``{1}{U}``) is the sole remaining
covered-by-construction Instant in the modal / counter-spell family that
is not yet in the PROBED tier.

``spell_effect = ModalChooseOne(modes=(CounterTargetSpell(frozenset()),
ManifestDread(count=1)))``

``effect_coverage.covered_python_class_set()`` confirms ALL three emitted
classes (``ModalChooseOne``, ``CounterTargetSpell``, ``ManifestDread``)
are in the covered set — the card is covered-by-construction.

Mode 0 probe strategy: ``chosen_modes=(0,)`` on the ``StackItem`` locks
``ModalChooseOne.resolve`` onto mode 0 (``CounterTargetSpell``), exactly
as batch R used ``chosen_modes=(1,)`` to lock Live or Die onto mode 1.
The Rust synthetic Instant uses the bare ``counter_target_spell`` arm
(the established Divert-Disaster / Unravel / Don't-Make-a-Sound
counter-bait idiom).  Distinct controllers → one card per graveyard,
no intra-graveyard ordering ambiguity.

EXHAUSTION REPORT — LANE NOW FULLY PROBED
------------------------------------------
After this batch U probe, the modal + counter-spell EoE Instant lane is
fully exhausted at current bridge limits.  Every covered-by-construction
card in these families has a probe function.  The remaining modal / counter
EoE cards are all BLOCKED; the specific blockers are itemised below.

DROPPED-ON-VERIFY (honest reconnaissance, complete inventory)
-------------------------------------------------------------
The following covered-by-construction or effect-present candidates were
inspected and dropped; they cannot yield a new probe today:

  * **Twist Reality mode 1** — ``ManifestDread`` bridge arm explicitly
    defers cross-engine probes (``choose_card_from_library`` agent hook
    + ``put_into_battlefield`` face-down ETB-trigger fan-out;
    ``cross_engine.py``:6347-6357).  Dropped.

  * **Reroute Systems** — mode 1 emits ``DealDamageToTargetTappedCreature``,
    which is NOT in the covered class set.  Card is subsystem-gated /
    Effect-uncovered → BLOCKED tier.  Dropped.

  * **Scour for Scrap** — mode 1 emits
    ``ReturnTargetArtifactCardFromYourGraveyardToHand``, which is NOT
    in the covered class set.  Card is subsystem-gated / Effect-uncovered
    → BLOCKED tier.  Dropped.

  * **Archenemy's Charm** — mode 1 emits
    ``ReturnUpToNCreaturesFromYourGraveyardToHand`` and mode 2 emits
    ``PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl``,
    both absent from the covered class set.  Card is subsystem-gated /
    Effect-uncovered → BLOCKED tier.  Dropped.

  * **Drill Too Deep** — mode 0 emits
    ``PutChargeCountersOnTargetSpacecraftOrPlanetYouControl``, which is
    NOT in the covered class set.  Card is subsystem-gated /
    Effect-uncovered → BLOCKED tier even though mode 1 (DestroyTargetArtifact)
    is itself covered.  A covered-by-construction requirement is not
    satisfied; Drill Too Deep cannot be promoted to PROBED by a mode-1-only
    probe without misrepresenting the card's overall bridge coverage.
    Dropped.

  * **Warping Wail** — mode 0 emits
    ``ExileTargetCreatureWithPowerOrToughnessAtMost``, which is NOT in
    the covered class set.  Card is subsystem-gated / Effect-uncovered
    → BLOCKED tier even though mode 1 (``CounterTargetSpell{Sorcery}``)
    and mode 2 (``CreateToken``) are individually covered.  Dropped.

  * **CounterTargetSpell instants (all)** — ``Annul``, ``Divert Disaster``,
    ``Don't Make a Sound``, ``Get Out``, and ``Unravel`` are already in
    the PROBED tier from batches D/E/R.  No new CounterTargetSpell
    Instant cards remain in the covered-by-construction pool.

  * **Let's Play a Game, Split Up, Ruinous Rampage** — Sorcery type;
    family reserved for sibling worktree S.  Dropped.

PROBE SHIPPED IN THIS BATCH (1)
--------------------------------
  | card            | primary shape     | mode / arm used              |
  |-----------------|-------------------|------------------------------|
  | Twist Reality   | ModalChooseOne    | mode 0 → CounterTargetSpell  |
  |                 |                   | (frozenset())                |

All assert **full ``compare_fields == []``** (the strongest tier).

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the batch_a through batch_r probe modules — those are owned /
protected; this module avoids all collision).
Registered in ``scripts/measure_pool_parity.PROBE_MODULES`` by the
orchestrator after merge.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


# Skip the whole module if the Rust extension isn't built — mirrors the
# ``tests/test_parity_smoke.py`` / ``tests_rust/conftest.py`` policy so
# a fresh checkout without maturin doesn't break the gate.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (it's a script, not
    a package member) so probes can call ``_build_field_view`` for the
    full cross-engine byte-equality compare — same fixture shape as
    ``tests/test_parity_smoke.py`` and all prior batch modules."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------
# Batch-U probe #1 — Twist Reality (EoE Instant, in EoE pool).
#
# Oracle (verbatim, data/edge_of_eternities.json):
#   "[Instant] {1}{U} — Choose one —
#    • Counter target spell.
#    • Manifest dread. (Look at the top two cards of your library. Put
#      one into your hand and the other onto the battlefield face down
#      as a 2/2 creature. If the facedown card isn't a creature, it
#      remains face down until it's turned face up.)"
# Parser → spell_effect = ModalChooseOne(modes=(
#   CounterTargetSpell(filter_types=frozenset()),
#   ManifestDread(count=1)
# ))
#
# Covered-by-construction: all three emitted Effect classes
# (ModalChooseOne, CounterTargetSpell, ManifestDread) are in
# effect_coverage.covered_python_class_set().  Unprobed at HEAD.
#
# PROBE DESIGN — mode 0 (CounterTargetSpell) leg:
#   Python: StackItem with chosen_modes=(0,) locks ModalChooseOne.resolve
#     onto mode 0.  targets=(("stack", 0),) provides the counter target
#     (p0's Creature bait spell below Twist Reality on the stack,
#     controlled by p1 above it).  Mode 0 fires: the bait is countered
#     → p0's graveyard; Twist Reality → p1's graveyard.
#   Rust: synthetic Instant with just the bare ``counter_target_spell``
#     arm (the established Divert-Disaster / Unravel / Don't-Make-a-Sound
#     counter-bait idiom; the full modal ChooseOneMode carrier is NOT
#     loader-admitted in Rust).  Rust auto-picks the top non-self stack
#     item (the bait).  Same outcome, distinct controllers, no intra-
#     graveyard ordering ambiguity.
#
# DROPPED — mode 1 (ManifestDread):
#   ManifestDread bridge arm explicitly defers cross-engine probes
#   (choose_card_from_library agent hook + put_into_battlefield face-down
#   ETB-trigger fan-out; cross_engine.py:6347-6357).  Dropped.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_twist_reality_modal_counter_mode0_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Twist Reality (EoE
    Instant, EoE pool). Batch-U covered→PROBED — modal lane, mode 0.**

    Python: the ACTUAL parsed Twist Reality printing on a ``StackItem``
    with ``chosen_modes=(0,)`` (mode 0 = CounterTargetSpell,
    filter_types=frozenset() — any spell) and target = ``("stack", 0)``
    (p0's vanilla Creature Bait Spell on the bottom of the stack,
    controlled by p1 sitting above it).  ``ModalChooseOne.resolve``
    reads ``state.resolving_modes[0] = 0`` and fires mode 0 only; the
    bait is countered and moves to p0's graveyard; Twist Reality moves
    to p1's graveyard.

    Rust: the bridged bare ``{"kind": "counter_target_spell"}`` synthetic
    Instant (the established Divert-Disaster / Unravel / Don't-Make-a-
    Sound driving pattern — the full modal ChooseOneMode carrier is NOT
    loader-admitted; the COVERED effect is driven directly).  Rust
    auto-picks the top non-self stack item (the bait).

    Distinct controllers → one card per graveyard, no intra-graveyard
    ordering ambiguity (the established batch-D/E/R counter-bait idiom).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (bait in p0's graveyard, Twist Reality in
    p1's graveyard, both stacks empty, both battlefields empty) —
    byte-equal cross-engine.
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
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.library_lookat import ManifestDread
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Twist Reality")
    if real is None:
        pytest.skip("Twist Reality absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, ModalChooseOne), (
        f"genuine Twist Reality spell_effect must be ModalChooseOne; "
        f"got {type(se).__name__}"
    )
    assert len(se.modes) == 2, (
        "Twist Reality must have exactly 2 modes"
    )
    assert isinstance(se.modes[0], CounterTargetSpell), (
        f"mode[0] must be CounterTargetSpell; "
        f"got {type(se.modes[0]).__name__}"
    )
    assert se.modes[0].filter_types == frozenset(), (
        "Twist Reality mode 0 counters ANY spell (empty filter_types)"
    )
    assert isinstance(se.modes[1], ManifestDread), (
        f"mode[1] must be ManifestDread; "
        f"got {type(se.modes[1]).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0

    # ---- p0 Bait Creature Spell (bottom of stack, controlled by p0),
    # then p1's genuine Twist Reality ABOVE it with chosen_modes=(0,)
    # targeting the bait.  Distinct controllers → no intra-graveyard
    # ordering ambiguity (established batch-D/E/R counter-bait idiom). ----
    bait_printing = CardPrinting(
        name="TR Bait Creature", mana_cost_str="",
        mana_cost=ManaCost(generic=2), type_line="Creature",
        supertypes=(), card_types=("Creature",), subtypes=(),
        power=2, toughness=2, produces=frozenset(),
    )
    py_bait = py.new_object(bait_printing, owner_id=0, zone=Zone.STACK)
    py_bait.summoning_sick = False
    py.stack.append(StackItem(source=py_bait, controller_id=0))

    py_spell = py.new_object(real, owner_id=1, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=1,
            targets=(("stack", 0),),
            chosen_modes=(0,),
        )
    )
    resolve_top_of_stack(py)
    py_sba(py)
    while py.stack:
        resolve_top_of_stack(py)
        py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bait first, then synthetic counter on top (same bait
    # idiom as Don't Make a Sound in batch R). ----
    rs_bait_id = rs.register_and_inject_object(
        {"name": "TR Bait Creature", "card_types": ["Creature"],
         "power": 2, "toughness": 2},
        0, ZH,
    )
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Twist Reality", "card_types": ["Instant"],
         "effects": [{"kind": "counter_target_spell"}]},
        1, ZH,
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

    # The bait was countered → must NOT be on either battlefield.
    rs_bf = [e["printing_name"] for e in rs.battlefield_snapshot()]
    py_bf = [o.printing.name for o in py.battlefield]
    assert "TR Bait Creature" not in rs_bf and "TR Bait Creature" not in py_bf, (
        f"countered bait must NOT be on bf on BOTH; "
        f"rust_bf={rs_bf} py_bf={py_bf}"
    )

    # Graveyard check: exactly one card per owner, in the correct gy.
    rs_gy0 = [e["printing_name"] for e in rs.graveyard_snapshot(0)]
    py_gy0 = [o.printing.name for o in py.players[0].graveyard]
    rs_gy1 = [e["printing_name"] for e in rs.graveyard_snapshot(1)]
    py_gy1 = [o.printing.name for o in py.players[1].graveyard]
    assert rs_gy0 == py_gy0 == ["TR Bait Creature"], (
        f"p0 gy must be exactly the countered bait on BOTH; "
        f"rust={rs_gy0} py={py_gy0}"
    )
    assert rs_gy1 == py_gy1 == ["Twist Reality"], (
        f"p1 gy must be exactly Twist Reality on BOTH; "
        f"rust={rs_gy1} py={py_gy1}"
    )

    # Full field-view byte-equality — the strongest tier.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Twist Reality mode-0 counter must be byte-equal across the WHOLE "
        f"field view on BOTH engines; diffs={diffs}"
    )
