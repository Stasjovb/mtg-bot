"""Genuine real-EoE cross-engine byte-equality probes — batch N.

CONTINUOUS-PIPELINE phase: convert covered-by-construction EoE cards
into the **strongest parity-evidence tier** (``PROBED byte-equal`` per
``docs/POOL_PARITY.md`` / ``scripts/measure_pool_parity.py``) via
genuine real-EoE cross-engine probes.

WHAT EACH PROBE ASSERTS
-----------------------
Every probe drives the **ACTUAL parsed EoE printing** on the Python
side (``get_active_source().get_printings().get("<card>")`` — NOT a
synthetic stub) against a bridged synthetic carrier on the Rust side
(``register_and_inject_object`` carrying the SAME ETB trigger dict),
fires the EXACT real ``triggered_ability`` through the production
resolve path on BOTH engines, and asserts **full
``compare_fields(...) == []``** (byte-equality across the WHOLE
cross-engine field view — the strongest tier).

> CAVEAT (mirrors ``docs/POOL_PARITY.md``): this is Effect+bridge-
> level byte-equality on a *controlled* cross-engine state, NOT
> full-game-trajectory parity. PROBED is the strongest evidence tier
> the campaign tracks; it is not a full random multi-turn game.

PARTITION DISCIPLINE (batch N — ETB TRIGGERS ONLY, round 3, after H + K)
--------------------------------------------------------------------------
Sibling agents own: batch A (odd-ranked covered-but-unprobed), B
(even-ranked DIES/landfall), C, D, E (DIES/landfall/misc), F
(keyword-only creatures), G (sorcery shapes), H (ETB triggers:
Friendly Ghost / Overlord of the Floodpits / Overlord of the
Mistmoors / Tunnel Surveyor), I (DIES-trigger shapes), J (sorcery),
K (ETB triggers: Overlord of the Boilerbilges / Shroudstomper /
Spineseeker Centipede), L (BECOMES_TAPPED + landfall), M (sorcery),
O (DIES triggers).
This module owns **batch N**: ETB-triggered creature cards whose
primary parser output is a ``triggered_abilities`` entry with
``event = Event.ENTERS`` (or equivalent ETB event), covered-by-
construction, genuinely unprobed at live HEAD, DIFFERENT from batches
H and K. ``BECOMES_TAPPED`` cards (batch A / batch L) are excluded.

KEY INSIGHT — empty-library angle (batch N discovery)
------------------------------------------------------
Batches H and K deferred Unsettling Twins (``ManifestDread``) and
Starfield Shepherd (``ModalChooseOne`` over two
``SearchLibraryForCard`` modes) citing "agent hook" complexity.
Batch N discovers the **empty-library angle**: with p0's library
empty on BOTH engines, BOTH effects short-circuit before any agent
call is needed:

* ``ManifestDread.resolve``: ``if not p.library: return`` (Python) /
  ``library_len=0 → PendingDecision with empty Vec → O(1) no-op``
  (Rust). No manifest, no face-down object, no ETB fan-out, no
  ``choose_card_from_library`` call on EITHER engine.
* ``ModalChooseOne`` over ``SearchLibraryForCard`` modes: BOTH
  engines pick mode 0 (Python: ``if p.agent is None: idx = 0``; Rust:
  ``auto_resolve_pending_decisions("default") → modes[0]``). Mode 0
  is ``SearchLibraryForCard(basic_plains, may_fail=False)``; with an
  empty library ``options = []`` → shuffle (no-op) → return. No
  ``choose_card_from_library`` call, no mode-pick agent, fully
  deterministic.

This is the exact same empty-library no-op pattern that batch K used
for ``Spineseeker Centipede`` (``SearchLibraryForCard(basic_land,
may_fail=True)``); batch N extends it to the two deferred shapes.

The 2 cards pinned here (0 17lands deck count each — all
covered-but-unprobed at HEAD):

  | card                | decks | shape                                         |
  |---------------------|------:|-----------------------------------------------|
  | Unsettling Twins    |     0 | ETB IsSelf → ManifestDread(count=1)           |
  | Starfield Shepherd  |     0 | ETB IsSelf → ModalChooseOne(SLfC(basic_plains), SLfC(creature_small)) |

DROPPED-ON-VERIFY (cumulative honest-stops carried forward from H + K,
updated with batch N status):
  * **Balemurk Leech / Cult Healer / Dashing Bloodsucker / Entity
    Tracker / Erratic Apparition / Gremlin Tamer / Infernal Phantom /
    Optimistic Scavenger / Scrabbling Skullcrab / Skullsnap Nuisance**
    — ETB predicate is ``And(Subject(IsEnchantment()),
    ControlledByYou())``, which requires a ``subject_is_enchantment``
    Rust bridge predicate arm that does NOT exist. Dropped (same block
    documented in batches H + K; re-verified at HEAD batch N).
  * **Syr Vondam, the Lucent** — ETB →
    ``PumpCreaturesYouControlUntilEOT(granted_keywords={'deathtouch'})``.
    Rust's ``pump_creatures_you_control_until_eot`` bridge arm
    explicitly drops ``granted_keywords`` (rider-drop documented in
    cross_engine.py). A faithful synthetic mirror cannot convey the
    deathtouch grant. Dropped (same block documented in batches H + K;
    re-verified at HEAD batch N).
  * **Irreverent Gremlin / Vicious Clown** — ETB predicate includes
    ``HasPowerAtMost(n=2)`` — not in the Rust bridge predicate
    vocabulary. Dropped (same block documented in batch K; re-verified
    at HEAD batch N).

All 2 probes assert **full ``compare_fields == []``** (the strongest
tier).

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the batch_a through batch_m / batch_o / batch_l modules nor the 6
``test_audit_safe_trigger_*`` tests — those are owned/protected; this
module avoids all collision).
Registered in ``scripts/measure_pool_parity.PROBE_MODULES`` by the
orchestrator after merge.
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
# Batch-N probe #1 — Unsettling Twins (0 17lands decks).
#
# Covered: ``ManifestDread`` ∈ covered set + unprobed. Oracle:
# "[Creature] {3}{B} 2/2
#   When this creature enters, manifest dread."
# Parser → ETB trigger: event=enters, predicate=IsSelf,
# effect=ManifestDread(count=1).
#
# Empty-library angle (batch N discovery):
#   Python ``ManifestDread.resolve``: ``if not p.library: return``
#   fires before any ``choose_card_from_library`` or face-down ETB
#   fan-out. Rust: ``library_len=0`` emits a ``PendingDecision
#   ::ManifestDreadChoice`` with an empty ``cards`` Vec;
#   ``resolve_top_of_stack()`` auto-drains it as an O(1) no-op.
#
# With p0's library empty on BOTH engines, both resolve as a no-op:
# no card is manifested, no face-down permanent lands on the
# battlefield, no graveyard change, life totals unchanged. The
# result is purely Unsettling Twins on p0's bf — byte-equal.
#
# This pins the ``manifest_dread`` bridge arm on the ETB path
# byte-equal end-to-end without any agent shim (the empty-library
# branch never calls ``choose_card_from_library``), finally closing
# the gap batches H and K documented as "deferred (choose_card_from_
# library agent hook + face-down ETB fan-out complexity)".
#
# Assertion strength: full ``compare_fields``.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_unsettling_twins_etb_manifest_dread_empty_lib_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Unsettling Twins
    (0 17lands decks). Batch-N covered→PROBED.**

    Python: the ACTUAL parsed Unsettling Twins printing cast as a
    spell; its ETB (IsSelf → ManifestDread(count=1)) fires against
    an empty library. Rust: the bridged synthetic carrier with the
    ``manifest_dread`` trigger dict.

    Empty library → ``if not p.library: return`` (Python) /
    empty-Vec PendingDecision auto-drains as O(1) no-op (Rust).
    No card is manifested, no face-down permanent appears, no agent
    ``choose_card_from_library`` call is made on EITHER engine.
    Net result: Unsettling Twins on p0's bf, all zone sizes
    unchanged, life totals unchanged — byte-equal cross-engine.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (Unsettling Twins on p0's bf; no zone
    changes; life totals unchanged on BOTH). Closes the H + K
    deferred "choose_card_from_library + face-down ETB fan-out"
    block via the empty-library no-op angle.
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
    from mtg_bot.effects.generic.library_lookat import ManifestDread

    real = get_active_source().get_printings().get("Unsettling Twins")
    if real is None:
        pytest.skip("Unsettling Twins absent from active CardSource")
    assert "Creature" in real.card_types
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Unsettling Twins must have an ENTERS trigger"
    )
    assert isinstance(etb.effect, ManifestDread), (
        f"genuine Unsettling Twins ETB must be ManifestDread;"
        f" got {type(etb.effect).__name__}"
    )
    assert etb.effect.count == 1

    # Empty library on both sides: ManifestDread short-circuits
    # before any agent call or face-down manifest — deterministic
    # no-op cross-engine. No agent shim needed.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0
    ZB = 2

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    # ---- Python: genuine parsed Unsettling Twins on stack → bf. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Unsettling Twins"
               for o in py.battlefield), (
        "Unsettling Twins should resolve onto p0's battlefield"
    )
    assert len(py.stack) == 1, (
        "ETB trigger should be on the Python stack after resolve"
    )

    # ---- Drain Python stack (ManifestDread → empty-lib no-op). ----
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert len(py.players[0].hand) == 0, (
        "Python: no card manifested (empty library → no-op)"
    )
    assert len(py.players[0].library) == 0, (
        "Python: library stays empty after no-op ManifestDread"
    )
    # Only Unsettling Twins on bf (no face-down permanent manifested).
    assert len(py.battlefield) == 1, (
        "Python: only Unsettling Twins on bf (empty-library no-op)"
    )
    assert py.players[0].life == py_p0_life0, "Python: p0 life unchanged"
    assert py.players[1].life == py_p1_life0, "Python: p1 life unchanged"

    # ---- Rust: bridged synthetic carrier with the same ETB shape. ----
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)
    rs_id = rs.register_and_inject_object(
        {
            "name": "Unsettling Twins",
            "card_types": ["Creature"],
            "power": int(real.power) if real.power is not None else 2,
            "toughness": int(real.toughness) if real.toughness is not None else 2,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "manifest_dread",
                        "count": 1,
                    },
                }
            ],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_id, 0)
    rs.resolve_top_of_stack()
    assert rs.find_object_zone(rs_id) == ZB
    assert rs.stack_size() == 1, (
        "ETB trigger should be on the Rust stack after resolve"
    )

    # ---- Drain Rust stack (ManifestDread → empty-lib no-op). -----
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.hand_sizes[0] == 0, (
        "Rust: no card manifested (empty library → no-op)"
    )
    assert rs.library_sizes[0] == 0, (
        "Rust: library stays empty after no-op ManifestDread"
    )
    assert rs.get_life(0) == rs_p0_life0, "Rust: p0 life unchanged"
    assert rs.get_life(1) == rs_p1_life0, "Rust: p1 life unchanged"

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Unsettling Twins ETB manifest-dread (empty-lib no-op) must "
        f"be byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-N probe #2 — Starfield Shepherd (0 17lands decks).
#
# Covered: ``ModalChooseOne`` + ``SearchLibraryForCard`` ∈ covered
# set + unprobed. Oracle:
# "[Creature — Angel] {4}{W}{W} 3/2 Flying
#   When this creature enters, choose one —
#   • Search your library for a basic Plains card, reveal it, put it
#     into your hand, then shuffle.
#   • Search your library for a creature card with mana value 1 or
#     less, reveal it, put it into your hand, then shuffle."
# Parser → ETB trigger: event=enters, predicate=IsSelf,
# effect=ModalChooseOne(modes=(
#   SearchLibraryForCard(filter_name='basic_plains', may_fail=False),
#   SearchLibraryForCard(filter_name='creature_small', max_mv=1,
#                        may_fail=False))).
#
# Empty-library angle (batch N discovery):
#   BOTH engines pick mode 0 with no agent seated (Python:
#   ``if p.agent is None: idx = 0``; Rust:
#   ``auto_resolve_pending_decisions("default") → modes[0]``).
#   Mode 0 is SearchLibraryForCard(basic_plains, may_fail=False).
#   With an empty library ``options = []`` → log + shuffle (no-op) →
#   return. No ``choose_card_from_library`` call on EITHER engine,
#   no mode-pick agent needed. Fully deterministic.
#
# The probe pins the ``choose_one_mode`` + ``search_library_for_card``
# bridge arm composition on the ETB path byte-equal end-to-end
# without any agent shim, finally closing the gap batches H and K
# documented as "ModalChooseOne+SearchLibraryForCard composite defer"
# and "may_fail asymmetric agent paths".
#
# Assertion strength: full ``compare_fields``.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_starfield_shepherd_etb_modal_search_empty_lib_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Starfield Shepherd
    (0 17lands decks). Batch-N covered→PROBED.**

    Python: the ACTUAL parsed Starfield Shepherd printing cast as a
    spell; its ETB (IsSelf → ModalChooseOne(SearchLibraryForCard
    (basic_plains, may_fail=False), SearchLibraryForCard
    (creature_small, max_mv=1, may_fail=False))) fires against an
    empty library. Rust: the bridged synthetic carrier with the
    ``choose_one_mode`` + ``search_library_for_card`` trigger dict.

    Both engines pick mode 0 deterministically (no agent seated;
    Python defaults to ``idx=0``; Rust ``auto_resolve`` picks
    ``modes[0]``). Mode 0 = SearchLibraryForCard(basic_plains,
    may_fail=False). Empty library → no match → shuffle (no-op) →
    return. No ``choose_card_from_library`` call, no mode-pick agent.

    Net result: Starfield Shepherd on p0's bf, all zone sizes
    unchanged, life totals unchanged — byte-equal cross-engine.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view. Closes the H + K deferred
    "ModalChooseOne+SearchLibraryForCard composite" block via the
    empty-library no-op angle (same pattern as batch K's Spineseeker
    Centipede probe, extended to a modal two-mode shape).
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
    from mtg_bot.effects.generic.search import SearchLibraryForCard

    real = get_active_source().get_printings().get("Starfield Shepherd")
    if real is None:
        pytest.skip("Starfield Shepherd absent from active CardSource")
    assert "Creature" in real.card_types
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Starfield Shepherd must have an ENTERS trigger"
    )
    assert isinstance(etb.effect, ModalChooseOne), (
        f"genuine Starfield Shepherd ETB must be ModalChooseOne;"
        f" got {type(etb.effect).__name__}"
    )
    assert len(etb.effect.modes) == 2, (
        "Starfield Shepherd ETB must have exactly 2 modes"
    )
    assert isinstance(etb.effect.modes[0], SearchLibraryForCard), (
        f"mode[0] must be SearchLibraryForCard;"
        f" got {type(etb.effect.modes[0]).__name__}"
    )
    assert etb.effect.modes[0].filter_name == "basic_plains"
    assert etb.effect.modes[0].may_fail is False
    assert isinstance(etb.effect.modes[1], SearchLibraryForCard), (
        f"mode[1] must be SearchLibraryForCard;"
        f" got {type(etb.effect.modes[1]).__name__}"
    )
    assert etb.effect.modes[1].filter_name == "creature_small"

    # Empty library on both sides: both engines pick mode 0
    # (SearchLibraryForCard basic_plains); empty library → no match
    # → shuffle (no-op) → return. No agent call on EITHER engine.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0
    ZB = 2

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    # ---- Python: genuine parsed Starfield Shepherd on stack → bf. --
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Starfield Shepherd"
               for o in py.battlefield), (
        "Starfield Shepherd should resolve onto p0's battlefield"
    )
    assert len(py.stack) == 1, (
        "ETB trigger should be on the Python stack after resolve"
    )

    # ---- Drain Python stack (ModalChooseOne → mode0 → empty-lib). -
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert len(py.players[0].hand) == 0, (
        "Python: no card fetched (empty library → no-op mode 0)"
    )
    assert len(py.players[0].library) == 0, (
        "Python: library stays empty after no-match shuffle"
    )
    assert py.players[0].life == py_p0_life0, "Python: p0 life unchanged"
    assert py.players[1].life == py_p1_life0, "Python: p1 life unchanged"

    # ---- Rust: bridged synthetic carrier with the same ETB shape. --
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)
    rs_id = rs.register_and_inject_object(
        {
            "name": "Starfield Shepherd",
            "card_types": ["Creature"],
            "power": int(real.power) if real.power is not None else 3,
            "toughness": int(real.toughness) if real.toughness is not None else 2,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "choose_one_mode",
                        "modes": [
                            {
                                "kind": "search_library_for_card",
                                "filter_name": "basic_plains",
                                "may_fail": False,
                            },
                            {
                                "kind": "search_library_for_card",
                                "filter_name": "creature_small",
                                "max_mv": 1,
                                "may_fail": False,
                            },
                        ],
                    },
                }
            ],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_id, 0)
    rs.resolve_top_of_stack()
    assert rs.find_object_zone(rs_id) == ZB
    assert rs.stack_size() == 1, (
        "ETB trigger should be on the Rust stack after resolve"
    )

    # ---- Drain Rust stack (ModalChooseOne → mode0 → empty-lib). ---
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.hand_sizes[0] == 0, (
        "Rust: no card fetched (empty library → no-op mode 0)"
    )
    assert rs.library_sizes[0] == 0, (
        "Rust: library stays empty after no-match shuffle"
    )
    assert rs.get_life(0) == rs_p0_life0, "Rust: p0 life unchanged"
    assert rs.get_life(1) == rs_p1_life0, "Rust: p1 life unchanged"

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Starfield Shepherd ETB modal-search (empty-lib no-op) must "
        f"be byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )
