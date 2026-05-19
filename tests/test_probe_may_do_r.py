"""Genuine real-EoE cross-engine byte-equality probes — batch R.

EXPLORATORY PIVOT — round 4 may-do / optional-cost / modal shape lane.

MISSION
-------
Probe cards whose **primary effect is a MAY-DO / OPTIONAL-COST shape**
(``MayDo`` combinator, ``IfYouDo(MayDo(...), ...)`` pattern) or, as
secondary / tertiary lanes, **MULTI-MODE / CHOOSE-ONE** (``ModalChooseOne``)
and **COUNTER-TARGET-SPELL** (``CounterTargetSpell``) shapes.

WHAT EACH PROBE ASSERTS (identical bar to batches A-N)
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

MAY-DO LANE RECONNAISSANCE (honest verify-first)
-------------------------------------------------
The ``MayDo`` bridge arm (``cross_engine.py``:1564) is live and wired.
Only FOUR EoE pool cards parse with ``MayDo`` in their effect tree:

  | card                | tier         | blocking reason               |
  |---------------------|--------------|-------------------------------|
  | Melded Moxite       | PROBED       | already probed (test_parity_  |
  |                     |              | smoke.py:18169)               |
  | Irreverent Gremlin  | covered      | trigger predicate contains    |
  |                     |              | ``HasPowerAtMost(n=2)`` — NOT |
  |                     |              | in Rust bridge predicate vocab|
  | Vengeful Possession | uncovered    | ``ThreatenTargetCreatureUEOT``|
  |                     |              | not in covered set            |
  | Attack-in-the-Box   | uncovered/   | ``ScheduleSelfSacAtNextEnd-   |
  |                     | subsystem-   | Step`` not in covered set;    |
  |                     | blocked      | BECOMES_TAPPED-family gate    |

**MAY-DO LANE IS CLOSED.** Melded Moxite is already PROBED.
Irreverent Gremlin was documented as dropped in batches K and N (same
``HasPowerAtMost`` block; re-verified at HEAD branch
``feature/probe-batch-r``). The two remaining candidates fail the
covered-class requirement. No new MayDo-family probe is constructible
without first landing the missing Rust substrates — out of scope for
a non-Rust slice.

MODAL (CHOOSE-ONE) PIVOT — secondary lane
-----------------------------------------
``ModalChooseOne`` is in the covered set; the ``choose_one_mode`` bridge
arm (``cross_engine.py``:6028) is live. Covered-not-probed modal
candidates (instants only — Sorcery family reserved for sibling
worktree P):

  | card             | modes                                        | clean? |
  |------------------|----------------------------------------------|--------|
  | Live or Die      | mode0=ReturnCreature→bf (targeted graveyard) | YES — |
  |                  | mode1=DestroyTargetCreature (targeted bf)    | probe  |
  |                  |                                              | mode 1 |
  | Twist Reality    | mode0=CounterTargetSpell                     | mode0  |
  |                  | mode1=ManifestDread(1) — bridge deferred     | ok;    |
  |                  |                                              | mode1  |
  |                  |                                              | has    |
  |                  |                                              | agent  |
  |                  |                                              | hook   |

``Live or Die`` (Instant) mode 1 is the cleanest modal pick: the
``chosen_modes=(1,)`` field on ``StackItem`` locks Python's
``ModalChooseOne.resolve`` onto mode 1 (``DestroyTargetCreature``),
and the Rust synthetic carrier uses just the ``destroy_target`` effect
dict directly — the exact "drive the chosen mode's COVERED effect
through the bridge" pattern. Byte-equal end-to-end verified before
writing this file.

COUNTER-TARGET-SPELL TERTIARY LANE
------------------------------------
Two additional unprobed Instant-type cards with ``CounterTargetSpell``
shapes remain (Duskmourn cards, in-pool, covered, not probed):

  | card                | filter_types               | bait choice   |
  |---------------------|----------------------------|---------------|
  | Don't Make a Sound  | frozenset() — any spell    | Creature bait |
  | Get Out             | {Creature, Enchantment}    | Creature bait |
  |                     |                            | (in filter)   |

Both use the established batch-D/E counter-bait idiom (Divert-Disaster /
Unravel / Annul precedent): seat a legal bait spell on the Python stack
with the correct target; the Rust synthetic Instant uses the bare
``counter_target_spell`` arm (which counters any spell — the bait is in
both filters). Distinct controllers → one card per graveyard, no
intra-graveyard ordering ambiguity.

The 3 probes shipped here (all verified byte-equal before commit):

  | card                | primary shape     | mode / arm used       |
  |---------------------|-------------------|-----------------------|
  | Live or Die         | ModalChooseOne    | mode 1 → Destroy target |
  | Don't Make a Sound  | CounterTargetSpell| any-spell filter      |
  | Get Out             | CounterTargetSpell| Creature-or-Enchantment|

All 3 assert **full ``compare_fields == []``** (the strongest tier).

DROPPED-ON-VERIFY (honest reconnaissance)
------------------------------------------
  * **Irreverent Gremlin** — ETB predicate ``HasPowerAtMost(n=2)``
    absent from Rust bridge predicate vocabulary. Documented in batches
    K and N; re-confirmed at HEAD.
  * **Vengeful Possession** — ``ThreatenTargetCreatureUEOT`` not in
    covered class set; modal + uncovered effect gap. Dropped.
  * **Attack-in-the-Box** — ``ScheduleSelfSacAtNextEndStep`` not in
    covered set; also BECOMES_TAPPED subsystem gate. Dropped.
  * **Split Up** (Sorcery) — family reserved for sibling worktree P.
  * **Let's Play a Game** (Sorcery) — family reserved for sibling
    worktree P.
  * **Twist Reality** mode 1 — ``ManifestDread`` bridge arm explicitly
    defers cross-engine probes (choose_card_from_library agent hook;
    cross_engine.py:6347-6357). Dropped.
  * **Cosmogrand Zenith** — triggered ability predicate contains
    ``StateBound(SpellsCastThisTurn(n=2))`` — not in Rust bridge
    predicate vocabulary. Dropped.

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the batch_a through batch_n / batch_o / batch_o2 nor the
``test_audit_safe_trigger_*`` nor the ``test_probe_idiom_*`` tests —
those are owned/protected; this module avoids all collision).
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
# Batch-R probe #1 — Live or Die (Duskmourn Instant, in EoE pool).
#
# Modal shape: ``ModalChooseOne(modes=(ReturnCreatureFromYourGraveyard
# ToBattlefield(...), DestroyTargetCreature(...)))``
# Covered (all effect classes ∈ covered set); unprobed at HEAD.
#
# Oracle (verbatim, data/duskmourn.json):
#   "[Instant] {1}{B} — Choose one —
#    • Return target creature card from your graveyard to the battlefield.
#    • Destroy target creature."
# Parser → spell_effect = ModalChooseOne(modes=(Return..., Destroy...))
#
# PROBE DESIGN — mode 1 (DestroyTargetCreature) leg:
#   Python: StackItem with chosen_modes=(1,) locks ModalChooseOne.resolve
#     onto mode 1. targets=(("creature", vic.id),) provides the destroy
#     target. Mode 1 fires: the 2/2 victim lands in p1's graveyard.
#   Rust: synthetic Instant with just the ``destroy_target`` arm (the
#     COVERED mode-1 effect, driven directly — the established Radiant-
#     Strike / Depressurize pattern; the full modal carrier is NOT
#     loader-admitted in Rust). Rust auto-picks the lone battlefield
#     creature as the target; same outcome.
#
# DROPPED — mode 0 (ReturnCreatureFromYourGraveyardToBattlefield):
#   requires a graveyard creature target AND an agent call
#   (choose_target for graveyard_creature kind) — adds a shim layer
#   beyond a single effect-level interaction. Mode 1 is the cleaner
#   solo pick for this batch.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_live_or_die_modal_destroy_mode1_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Live or Die (Duskmourn
    Instant, EoE pool). Batch-R covered→PROBED — modal lane.**

    Python: the ACTUAL parsed Live or Die printing on a ``StackItem``
    with ``chosen_modes=(1,)`` (mode 1 = DestroyTargetCreature) and
    target = p1's vanilla 2/2 victim creature. ``ModalChooseOne.resolve``
    reads ``state.resolving_modes[0] = 1`` and fires mode 1 only; the
    victim is destroyed and moves to p1's graveyard.

    Rust: the bridged ``{"kind": "destroy_target", "target": {"kind":
    "any_creature"}}`` synthetic Instant (the established Radiant-Strike /
    Depressurize driving pattern — the full modal ChooseOneMode is NOT
    loader-admitted; the COVERED effect is driven directly).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (victim in p1's graveyard, Live or Die in
    p0's graveyard, both stacks empty, both battlefields empty) —
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
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.destroy import DestroyTargetCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Live or Die")
    if real is None:
        pytest.skip("Live or Die absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, ModalChooseOne), (
        f"genuine Live or Die spell_effect must be ModalChooseOne; "
        f"got {type(se).__name__}"
    )
    assert len(se.modes) == 2, (
        "Live or Die must have exactly 2 modes"
    )
    assert isinstance(se.modes[1], DestroyTargetCreature), (
        f"mode[1] must be DestroyTargetCreature; "
        f"got {type(se.modes[1]).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # ---- p1 has a single vanilla 2/2 victim — the destroy target on
    # BOTH engines (Python: chosen by the probe; Rust: auto-picked via
    # the any_creature first-slice scan — sole bf creature). ----
    py_vic = py.new_object(
        CardPrinting(
            name="LoD Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=2), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)

    rs_vic_id = rs.register_and_inject_object(
        {"name": "LoD Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2},
        1, ZB,
    )

    # ---- Python: genuine Live or Die with chosen_modes=(1,) selects
    # mode 1 = DestroyTargetCreature. Target = p1's victim creature. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            targets=(("creature", py_vic.id),),
            chosen_modes=(1,),
        )
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: synthetic Instant driving the covered destroy_target arm
    # (the mode-1 effect directly, not wrapped in choose_one_mode). ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Live or Die", "card_types": ["Instant"],
         "effects": [{"kind": "destroy_target",
                      "target": {"kind": "any_creature"}}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # Both engines must have destroyed the victim.
    rs_alive = any(
        e["id"] == rs_vic_id for e in rs.battlefield_snapshot()
    )
    py_alive = any(o.id == py_vic.id for o in py.battlefield)
    assert rs_alive is False and py_alive is False, (
        f"victim must be destroyed on BOTH; "
        f"rust_alive={rs_alive} py_alive={py_alive}"
    )

    # Full field-view byte-equality — the strongest tier.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Live or Die mode-1 destroy must be byte-equal across the WHOLE "
        f"field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-R probe #2 — Don't Make a Sound (Duskmourn Instant, in EoE pool).
#
# Oracle (verbatim, data/duskmourn.json):
#   "[Instant] {1}{U} — Counter target spell."
# Parser → spell_effect = CounterTargetSpell(filter_types=frozenset())
#
# Covered (``CounterTargetSpell`` ∈ covered set); unprobed at HEAD.
# Shape identical to Divert Disaster / Unravel (already PROBED);
# this probe promotes a NEW card to the PROBED tier.
#
# PROBE DESIGN — established batch-D/E counter-bait idiom:
#   p0's Creature bait spell below the counter on the stack.
#   Python: genuine Don't Make a Sound (p1, controller) targets the
#     bait (("stack", 0)). CounterTargetSpell.resolve → bait exiled
#     to p0's graveyard; Don't Make a Sound → p1's graveyard.
#   Rust: synthetic Instant with {"kind": "counter_target_spell"} pushed
#     above the bait. Rust auto-picks the top non-self stack item (the
#     bait). Same outcome, byte-equal.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_dont_make_a_sound_counter_target_spell_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Don't Make a Sound
    (Duskmourn Instant, EoE pool). Batch-R covered→PROBED — counter
    lane.**

    Python: the ACTUAL parsed Don't Make a Sound printing (filter_types =
    frozenset() — any spell) on a ``StackItem`` above a benign p0 Bait
    Creature Spell, controlled by p1, target = ``("stack", 0)`` (the
    bait). Rust: the bridged bare ``{"kind": "counter_target_spell"}``
    synthetic Instant pushed above the bait; Rust auto-picks the top
    non-self stack item (the bait).

    The bait is countered → moves to p0's graveyard on BOTH; Don't Make
    a Sound → p1's graveyard on BOTH. Distinct controllers prevent any
    intra-graveyard ordering ambiguity (the established batch-D/E
    Divert-Disaster / Unravel / Annul counter-bait idiom).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view — byte-equal across BOTH engines.
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

    real = get_active_source().get_printings().get("Don't Make a Sound")
    if real is None:
        pytest.skip("Don't Make a Sound absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, CounterTargetSpell), (
        f"genuine Don't Make a Sound spell_effect must be "
        f"CounterTargetSpell; got {type(se).__name__}"
    )
    assert se.filter_types == frozenset(), (
        "Don't Make a Sound counters ANY spell (empty filter_types)"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0

    # ---- p0 Bait Creature Spell (bottom of stack), then p1's genuine
    # Don't Make a Sound ABOVE it targeting the bait. ----
    bait_printing = CardPrinting(
        name="DMAS Bait Creature", mana_cost_str="",
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
        StackItem(source=py_spell, controller_id=1,
                  targets=(("stack", 0),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    while py.stack:
        resolve_top_of_stack(py)
        py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bait first, then synthetic counter on top. ----
    rs_bait_id = rs.register_and_inject_object(
        {"name": "DMAS Bait Creature", "card_types": ["Creature"],
         "power": 2, "toughness": 2},
        0, ZH,
    )
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Don't Make a Sound", "card_types": ["Instant"],
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

    # The bait never resolved → must NOT be on either battlefield.
    rs_bf = [e["printing_name"] for e in rs.battlefield_snapshot()]
    py_bf = [o.printing.name for o in py.battlefield]
    assert "DMAS Bait Creature" not in rs_bf and "DMAS Bait Creature" not in py_bf, (
        f"countered bait must NOT be on bf on BOTH; "
        f"rust_bf={rs_bf} py_bf={py_bf}"
    )

    # Graveyard check: exactly one card per owner, in the right gy.
    rs_gy0 = [e["printing_name"] for e in rs.graveyard_snapshot(0)]
    py_gy0 = [o.printing.name for o in py.players[0].graveyard]
    rs_gy1 = [e["printing_name"] for e in rs.graveyard_snapshot(1)]
    py_gy1 = [o.printing.name for o in py.players[1].graveyard]
    assert rs_gy0 == py_gy0 == ["DMAS Bait Creature"], (
        f"p0 gy must be exactly the countered bait on BOTH; "
        f"rust={rs_gy0} py={py_gy0}"
    )
    assert rs_gy1 == py_gy1 == ["Don't Make a Sound"], (
        f"p1 gy must be exactly Don't Make a Sound on BOTH; "
        f"rust={rs_gy1} py={py_gy1}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Don't Make a Sound counter must be byte-equal across the WHOLE "
        f"field view on BOTH engines; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-R probe #3 — Get Out (Duskmourn Instant, in EoE pool).
#
# Oracle (verbatim, data/duskmourn.json):
#   "[Instant] {2}{U} — Counter target creature or enchantment spell."
# Parser → spell_effect = CounterTargetSpell(filter_types=frozenset(
#   {'Creature', 'Enchantment'}))
#
# Covered (``CounterTargetSpell`` ∈ covered set); unprobed at HEAD.
# Distinct from Don't Make a Sound (narrowed filter): the bait is a
# Creature spell — in Get Out's filter AND in Rust's any-spell pick —
# so both engines counter the SAME bait (same idiom as batch-E Annul,
# which has filter_types={'Artifact','Enchantment'}).
#
# PROBE DESIGN — established Annul counter-bait idiom:
#   Creature bait (in {Creature, Enchantment} filter) on p0's stack,
#   genuine Get Out (p1) targeting the bait. Rust: bare
#   counter_target_spell (any spell → picks the bait). Same outcome.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_get_out_counter_creature_or_enchantment_spell_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Get Out (Duskmourn
    Instant, EoE pool). Batch-R covered→PROBED — counter lane,
    creature-or-enchantment filter.**

    Python: the ACTUAL parsed Get Out printing (filter_types =
    {Creature, Enchantment}) on a ``StackItem`` above a benign p0
    Creature Bait Spell (a legal target under Get Out's narrowed filter
    AND under Rust's any-spell pick — so BOTH engines counter the SAME
    bait). Rust: the bridged bare ``{"kind": "counter_target_spell"}``
    synthetic Instant.

    The bait is countered → p0's graveyard on BOTH; Get Out →
    p1's graveyard on BOTH. Distinct controllers → no intra-graveyard
    ordering ambiguity (the established batch-E Annul counter-bait
    idiom, applied to the creature-or-enchantment filter variant).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view — byte-equal across BOTH engines.
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

    real = get_active_source().get_printings().get("Get Out")
    if real is None:
        pytest.skip("Get Out absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, CounterTargetSpell), (
        f"genuine Get Out spell_effect must be CounterTargetSpell; "
        f"got {type(se).__name__}"
    )
    assert se.filter_types == frozenset({"Creature", "Enchantment"}), (
        "Get Out counters only creature or enchantment spells — the "
        "filter-narrowed leg this probe pins"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0

    # ---- The bait is a Creature spell — a LEGAL target under Get Out's
    # {Creature, Enchantment} filter AND under Rust's any-spell pick,
    # so BOTH engines counter the SAME bait (parallel to batch-E Annul's
    # Artifact bait, which is likewise in {Artifact, Enchantment}).  ----
    bait_printing = CardPrinting(
        name="GO Bait Creature", mana_cost_str="",
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
        StackItem(source=py_spell, controller_id=1,
                  targets=(("stack", 0),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    while py.stack:
        resolve_top_of_stack(py)
        py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bait first, then the synthetic counter on top. ----
    rs_bait_id = rs.register_and_inject_object(
        {"name": "GO Bait Creature", "card_types": ["Creature"],
         "power": 2, "toughness": 2},
        0, ZH,
    )
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Get Out", "card_types": ["Instant"],
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

    # The bait never resolved → must NOT be on either battlefield.
    rs_bf = [e["printing_name"] for e in rs.battlefield_snapshot()]
    py_bf = [o.printing.name for o in py.battlefield]
    assert "GO Bait Creature" not in rs_bf and "GO Bait Creature" not in py_bf, (
        f"countered bait must NOT be on bf on BOTH; "
        f"rust_bf={rs_bf} py_bf={py_bf}"
    )

    # Graveyard check: exactly one card per owner, in the right gy.
    rs_gy0 = [e["printing_name"] for e in rs.graveyard_snapshot(0)]
    py_gy0 = [o.printing.name for o in py.players[0].graveyard]
    rs_gy1 = [e["printing_name"] for e in rs.graveyard_snapshot(1)]
    py_gy1 = [o.printing.name for o in py.players[1].graveyard]
    assert rs_gy0 == py_gy0 == ["GO Bait Creature"], (
        f"p0 gy must be exactly the countered bait on BOTH; "
        f"rust={rs_gy0} py={py_gy0}"
    )
    assert rs_gy1 == py_gy1 == ["Get Out"], (
        f"p1 gy must be exactly Get Out on BOTH; "
        f"rust={rs_gy1} py={py_gy1}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Get Out counter-creature-or-enchantment must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )
