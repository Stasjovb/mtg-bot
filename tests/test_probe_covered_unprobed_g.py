"""Genuine real-EoE cross-engine byte-equality probes — batch G.

CONTINUOUS-PIPELINE phase: convert high-value
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
Decode-Transmissions / Sami's-Curiosity cross-engine driving pattern;
the full Sorcery/Instant is NOT loader-admitted, there is no
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

PARTITION DISCIPLINE (batch G — SORCERY primary, trivial INSTANT ok)
---------------------------------------------------------------------
Sibling agents own the disjoint batch A (odd-ranked,
``tests/test_probe_covered_unprobed_a.py``) + B (even-ranked,
``tests/test_probe_covered_unprobed_b.py``) + C + D + E + F + the
spell-card-bridge sweep (``tests/test_probe_spell_card_bridge_
admitted.py``) + the warp-admitted creatures (``tests/test_probe_
warp_admitted.py``) + the warp+combat-interaction module; a Rust
agent owns Seedship Impact / Orbital Plunge; sibling agents H and I
own ETB-trigger and DIES-trigger cards respectively. This module owns
**batch G**: SORCERY-primary (and trivially-resolving INSTANT where
clean) covered-but-unprobed cards NOT in any sibling/Rust set. The
covered-by-construction-but-unprobed list (computed read-only via
``scripts/measure_pool_parity.classify_pool``, sorted by 17lands deck
count desc) was verify-first-recomputed at live HEAD; every card
below is (a) covered-by-construction, (b) NOT individually probed,
(c) NOT in any sibling batch, (d) a Sorcery (or trivial Instant) with
a spell_effect that resolves directly with no creature-trigger
involvement.

The 3 cards pinned here (deck counts from ``data/17lands/
eoe_decks.json.gz`` at verify-first walk):

  1. Scrounge for Eternity  (rank ~, ~4,150) — Sorcery,
     Sequence(ReturnCreatureFromYourGraveyardToBattlefield,
              CreateToken Lander)
  2. Pyroclasm              (rank ~,      0) — Sorcery,
     DealNDamageToEachCreature(2)
  3. Final Vengeance        (rank ~,      0) — Sorcery,
     ExileTargetCreature

DROPPED-ON-VERIFY (honest verify-first discipline):

  * **Diplomatic Relations** (~29,818 decks) — genuine
    ``DiplomaticRelationsEffect`` requires a 2-slot heterogeneous
    target (friendly creature slot 0 + opponent creature slot 1) on
    the StackItem. The established probe idiom uses a single-slot
    ``StackItem(targets=(...))`` on Python and a single-resolver
    ``push_to_stack`` on Rust; the 2-slot shape routes through the
    ``step_both`` / ``trajectory.setup_matched_game`` idiom (see
    ``test_bridge_spell_card_lever_phase2_diplomatic_relations_real_
    eoe_cast_resolve_parity`` in ``test_cross_engine_etb_triggers.py``
    — a different driving pattern with no ``test_cross_engine_real_eoe_
    <slug>_parity`` function name prefix). Driving the 2-slot shape via
    the batch-G single-slot carrier idiom is not constructible without
    a new multi-slot push helper — out of scope for a non-Rust,
    non-Python-source slice. Dropped; the existing Phase-2 lever pin
    covers the Effect+bridge evidence at the ``step_both`` level.
  * **Cerebral Download** (~11,768 decks) — its ``Sequence`` spell_effect
    is the EXISTING known-divergence xfail pin in ``test_parity_smoke.py``
    (batch D/E precedent). Excluded; driving it as a byte-equal probe
    would re-surface that tracked divergence.
  * **Temporal Intervention** (~1,715 decks) — genuine ``spell_effect``
    is ``TargetOpponentDiscardsCasterChoice`` (the CASTER picks which
    card the opponent discards). The ``discard_card`` bridge arm maps
    to ``TargetOpponentDiscards`` (the DISCARDER's own agent picks) — a
    genuinely DIFFERENT resolution semantic; batch E already documented
    this drop. Excluded.
  * **Dual-Sun Technique** (~3,734 decks) — ``PumpTargetCreatureUntilEOT``
    with ``draw_if_target_has_plus_one_counter=1``; the Rust
    ``grant_keywords_to_target_creature_until_eot`` bridge arm carries
    NO draw-if-counter rider, so a faithful byte-equal mirror requires
    either a new bridge rider or constraining the probe to the zero-
    counter case (which suppresses the draw — the genuinely interesting
    leg). Dropped; the effect-coverage tier already captures
    ``PumpTargetCreatureUntilEOT`` via other probes.

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the batch_a / batch_b / batch_c / batch_d / batch_e / batch_f /
spell_card_bridge_admitted / warp_admitted / warp_combat_interaction
modules nor the 6 ``test_audit_safe_trigger_*`` tests — those are
owned/protected; this module avoids all collision and touches no
STALENESS-SENTINEL). Registered in
``scripts/measure_pool_parity.PROBE_MODULES``.
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


# ---------------------------------------------------------------------
# Batch-G probe #1 — Scrounge for Eternity (~4,150 17lands decks).
#
# Highest-deck covered-but-unprobed sorcery in the batch-G partition.
# Verified covered (``ReturnCreatureFromYourGraveyardToBattlefield`` +
# ``CreateToken`` ∈ covered set) + unprobed at HEAD. Oracle:
#   "[Sorcery] {3}{B} — Return target creature or Spacecraft card with
#    mana value 5 or less from your graveyard to the battlefield.
#    Create a Lander token."
# Parser → ``spell_effect = Sequence(
#   ReturnCreatureFromYourGraveyardToBattlefield(or_spacecraft=True,
#       max_mv=5, target_kind='graveyard_creature'),
#   CreateToken(token_printing=Lander, count=1))``.
#
# The covered ``return_creature_from_your_graveyard_to_battlefield``
# bridge arm is a unit variant (no fields — ignores max_mv /
# or_spacecraft). The synthetic carrier seeding uses only a plain
# creature with MV 0 in the graveyard so the max_mv=5 constraint is
# trivially satisfied on BOTH engines — the covered Effect half is
# byte-equal end-to-end.
#
# Lander pid is registered on Rust (registry_size before injection);
# the intrinsic Python TOKEN_PRINTINGS["Lander"] is seeded in p0's
# library so the starting field view is symmetric — the established
# Sami's-Curiosity / Beamsaw-Prospector idiom (batch D).
# _PickFirstLegalTargetAgent mirrors Rust's iterator-order graveyard
# scan on the Python side.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_scrounge_for_eternity_return_then_lander_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Scrounge for Eternity
    (~4,150 17lands decks). Batch-G covered→PROBED.**

    Python: the ACTUAL parsed Scrounge for Eternity printing on a
    ``StackItem`` with a seeded graveyard creature as the reanimation
    target. Rust: the bridged ``sequence[return_creature_from_your_
    graveyard_to_battlefield, create_token(Lander)]`` synthetic Sorcery.
    Both engines reanimate the first creature from p0's graveyard and
    create one Lander token on p0's battlefield.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (reanimated creature + Lander token both on
    p0's battlefield on BOTH; graveyard empty on BOTH; p0 life and hand
    unchanged on BOTH).
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
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.graveyard import (
        ReturnCreatureFromYourGraveyardToBattlefield,
    )
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstLegalTargetAgent

    real = get_active_source().get_printings().get("Scrounge for Eternity")
    if real is None:
        pytest.skip("Scrounge for Eternity absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Scrounge for Eternity spell_effect must be a Sequence; "
        f"got {type(se).__name__}"
    )
    assert isinstance(se.effects[0], ReturnCreatureFromYourGraveyardToBattlefield), (
        f"first effect must be ReturnCreatureFromYourGraveyardToBattlefield; "
        f"got {type(se.effects[0]).__name__}"
    )
    assert se.effects[0].or_spacecraft is True
    assert se.effects[0].max_mv == 5

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZG = 4  # ZONE_GRAVEYARD

    # Register Lander pid on Rust; seed TOKEN_PRINTINGS["Lander"] in
    # p0's library so the field-view token-printing-id is symmetric
    # on both engines — the established Sami's-Curiosity idiom (batch D).
    lander_pid = rs.registry_size
    rs.register_and_inject_object(
        {"name": "Lander", "card_types": ["Artifact"],
         "supertypes": ["Token"], "mana_cost": {"generic": 0}},
        0, 1,  # owner p0, ZONE_HAND (inert pre-probe)
    )
    py_lander_seed = py.new_object(
        TOKEN_PRINTINGS["Lander"], owner_id=0, zone=Zone.LIBRARY
    )
    py_lander_seed.summoning_sick = False
    py.players[0].library.append(py_lander_seed)

    # Seat a vanilla 2/2 creature in p0's graveyard on BOTH engines.
    # MV 0 (ManaCost generic=0) satisfies the genuine max_mv=5 guard.
    bait_printing = CardPrinting(
        name="SfE Bait", mana_cost_str="",
        mana_cost=ManaCost(generic=0), type_line="Creature",
        supertypes=(), card_types=("Creature",), subtypes=(),
        power=2, toughness=2, produces=frozenset(),
    )
    # Seat the bait on the battlefield first, then kill it via lethal
    # damage + SBA — Rust's register_and_inject_object only supports
    # zones 0-3 (HAND/LIBRARY/BATTLEFIELD/STACK), not GRAVEYARD directly.
    py_bait = py.new_object(bait_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_bait.summoning_sick = False
    py_bait.tapped = False
    py_bait.damage = 0
    py_bait.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_bait)

    rs_bait_id = rs.register_and_inject_object(
        {"name": "SfE Bait", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 0, ZB,
    )

    # Deal lethal damage to move both bait creatures bf→graveyard
    # so they become valid reanimation targets for Scrounge for Eternity.
    py_bait.damage = 2  # toughness = 2, so lethal
    rs.deal_damage(rs_bait_id, 2)
    py_sba(py)
    rs.apply_sbas()
    assert py_bait not in py.battlefield, "bait must be dead (Python)"
    assert py_bait in py.players[0].graveyard, "bait must be in p0 gy (Python)"
    assert rs.stack_size() == 0, "no triggers expected after plain bait death"

    # _PickFirstLegalTargetAgent picks legal_targets[0] = the first
    # graveyard_creature in p0's graveyard — the single seeded bait.
    py.players[0].agent = _PickFirstLegalTargetAgent()

    assert len(py.battlefield) == 0 and rs.stack_size() == 0

    # ---- Python: genuine parsed Scrounge for Eternity on a StackItem
    # with the graveyard creature as the explicit reanimation target.
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("graveyard_creature", py_bait.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    py_bf_names = [o.printing.name for o in py.battlefield]
    assert "SfE Bait" in py_bf_names, (
        f"SfE Bait must be reanimated to p0 bf (Python); bf={py_bf_names}"
    )
    assert "Lander" in py_bf_names, (
        f"Lander must be created on p0 bf (Python); bf={py_bf_names}"
    )

    # ---- Rust: bridged sequence[return_creature_from_graveyard,
    # create_token(Lander)]. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Scrounge for Eternity", "card_types": ["Sorcery"],
         "effects": [{"kind": "sequence", "effects": [
             {"kind": "return_creature_from_your_graveyard_to_battlefield"},
             {"kind": "create_token", "count": 1,
              "token_printing_id": lander_pid},
         ]}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    rs_bf = rs.battlefield_snapshot()
    rs_bf_names = [e["printing_name"] for e in rs_bf]
    assert "SfE Bait" in rs_bf_names, (
        f"SfE Bait must be reanimated to p0 bf (Rust); bf={rs_bf_names}"
    )
    assert "Lander" in rs_bf_names, (
        f"Lander must be created on p0 bf (Rust); bf={rs_bf_names}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Scrounge for Eternity return+Lander must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-G probe #2 — Pyroclasm (~0 17lands decks; genuine EoE card).
#
# Covered (``DealNDamageToEachCreature`` ∈ covered set) + unprobed at
# HEAD. Oracle:
#   "[Sorcery] {1}{R} — Pyroclasm deals 2 damage to each creature."
# Parser → ``spell_effect = DealNDamageToEachCreature(amount=2)``.
#
# The ``damage_each_creature`` bridge arm (cross_engine.py:4684) maps
# to Python's ``DealNDamageToEachCreature(amount=2)`` exactly. Both
# engines implicitly target every creature on EITHER bf and apply 2
# damage; SBAs then destroy the creatures at ≤0 toughness. The probe
# seats one 2/2 creature on each side — both die after the sweep
# (2 damage ≥ 2 toughness) — the destroyed creatures land in their
# respective graveyards on BOTH engines byte-equal.
# Deck count is 0 in the 17lands draft pool (Pyroclasm is a
# non-EoE reprint not drafted in the 17lands sample window) but is a
# genuine EoE pool member and genuinely covered-by-construction.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_pyroclasm_deal_2_to_each_creature_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Pyroclasm
    (~0 17lands decks; genuine EoE covered card). Batch-G covered→PROBED.**

    Python: the ACTUAL parsed Pyroclasm printing on a ``StackItem`` (no
    targets — sweep). Rust: the bridged ``{"kind":"damage_each_creature",
    "amount":2}`` synthetic Sorcery. One 2/2 on p0's bf + one 2/2 on
    p1's bf — both take 2 damage → 0 toughness → SBA-destroyed, one in
    each graveyard on BOTH engines.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (both 2/2s in their respective graveyards,
    battlefield empty, lives unchanged on BOTH).
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
    from mtg_bot.effects.generic.damage import DealNDamageToEachCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Pyroclasm")
    if real is None:
        pytest.skip("Pyroclasm absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, DealNDamageToEachCreature), (
        f"genuine Pyroclasm spell_effect must be DealNDamageToEachCreature; "
        f"got {type(se).__name__}"
    )
    assert se.amount == 2

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # Seat one 2/2 on each side — both die to 2-damage sweep.
    def _seat_py(owner_id, tag):
        p = CardPrinting(
            name=f"Pyro {tag}", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        )
        o = py.new_object(p, owner_id=owner_id, zone=Zone.BATTLEFIELD)
        o.summoning_sick = False
        o.tapped = False
        o.damage = 0
        o.etb_timestamp = py.next_timestamp
        py.next_timestamp += 1
        py.battlefield.append(o)
        return o

    py_p0 = _seat_py(0, "P0")
    py_p1 = _seat_py(1, "P1")

    rs_p0_id = rs.register_and_inject_object(
        {"name": "Pyro P0", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 0, ZB,
    )
    rs_p1_id = rs.register_and_inject_object(
        {"name": "Pyro P1", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Pyroclasm on a StackItem (no targets).
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert len(py.battlefield) == 0, (
        f"both 2/2s must be dead post-Pyroclasm (Python); "
        f"bf={[o.printing.name for o in py.battlefield]}"
    )

    # ---- Rust: bridged damage_each_creature synthetic Sorcery. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Pyroclasm", "card_types": ["Sorcery"],
         "effects": [{"kind": "damage_each_creature", "amount": 2}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    rs_bf = rs.battlefield_snapshot()
    assert len(rs_bf) == 0, (
        f"both 2/2s must be dead post-Pyroclasm (Rust); "
        f"bf={[e['printing_name'] for e in rs_bf]}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Pyroclasm deal-2-to-each-creature must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-G probe #3 — Final Vengeance (~0 17lands decks; genuine EoE).
#
# Covered (``ExileTargetCreature`` ∈ covered set, itself a subclass of
# the covered ``Exile`` class) + unprobed at HEAD. Oracle:
#   "[Sorcery] {3}{B} — Exile target creature."
# Parser → ``spell_effect = ExileTargetCreature(targets=(
#   TargetSpec(IsCreature()),))``.
#
# The ``exile_target`` bridge arm (cross_engine.py:2675) maps to
# Python's ``Exile(targets=(TargetSpec(IsCreature()),))`` (the base
# class of ExileTargetCreature). Rust picks the first creature on
# the defender's bf; Python's _PickFirstOpponentTargetAgent mirrors
# that pick exactly (a single opponent creature → forced). The targeted
# creature is exiled to its owner's exile zone on BOTH engines.
# Exile bypasses indestructible per CR 702.12c — distinct from destroy.
# Deck count is 0 in the 17lands draft pool but the card is a genuine
# EoE pool member and genuinely covered-by-construction.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_final_vengeance_exile_target_creature_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Final Vengeance
    (~0 17lands decks; genuine EoE covered card). Batch-G covered→PROBED.**

    Python: the ACTUAL parsed Final Vengeance printing on a
    ``StackItem`` with the chosen creature target. Rust: the bridged
    ``{"kind":"exile_target","target":{"kind":"any_creature"}}``
    synthetic Sorcery (AnyCreature first-slice picker → p1 bf[0]).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the p1 2/2 exiled → p1 exile zone on
    BOTH; battlefield empty on BOTH; lives unchanged on BOTH).
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
    from mtg_bot.effects.generic.exile import ExileTargetCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Final Vengeance")
    if real is None:
        pytest.skip("Final Vengeance absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, ExileTargetCreature), (
        f"genuine Final Vengeance spell_effect must be ExileTargetCreature; "
        f"got {type(se).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 has a single vanilla 2/2 creature — the exile target on BOTH.
    py_vic = py.new_object(
        CardPrinting(
            name="FV Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "FV Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Final Vengeance on a StackItem,
    # controller p0, chosen target = p1's creature. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py_vic not in py.battlefield, (
        "FV Victim must be exiled, not on bf (Python)"
    )
    assert py_vic not in py.players[1].graveyard, (
        "FV Victim must be in exile, not graveyard (Python)"
    )

    # ---- Rust: bridged exile_target synthetic Sorcery. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Final Vengeance", "card_types": ["Sorcery"],
         "effects": [{"kind": "exile_target",
                      "target": {"kind": "any_creature"}}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    rs_bf = rs.battlefield_snapshot()
    rs_alive = any(e["id"] == rs_vic_id for e in rs_bf)
    assert rs_alive is False, (
        f"FV Victim must be exiled, not on bf (Rust); bf={[e['printing_name'] for e in rs_bf]}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Final Vengeance exile-target-creature must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )
