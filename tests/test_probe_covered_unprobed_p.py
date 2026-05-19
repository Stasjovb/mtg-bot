"""Genuine real-EoE cross-engine byte-equality probes — batch P.

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

PARTITION DISCIPLINE (batch P — SORCERY round 4, after G + J + M)
------------------------------------------------------------------
This module is batch P, the fourth round of SORCERY (and trivially-
resolving INSTANT) covered-but-unprobed probes, extending the sorcery
lane after batches G (Scrounge for Eternity / Pyroclasm / Final
Vengeance), J (Murder / Impossible Inferno / Midnight Mayhem /
Winter's Intervention), and M (Scorching Dragonfire / Untimely
Malfunction / Turn Inside Out). Sibling agents Q (activated-abilities,
continuing O2 lane) and R (may-do / optional-cost cards) run in
parallel worktrees. The covered-by-construction-but-unprobed list
(computed read-only via ``scripts/measure_pool_parity.classify_pool``,
sorted by 17lands deck count desc) was verify-first-recomputed at live
HEAD 446058b1; every card below is (a) covered-by-construction, (b)
NOT individually probed, (c) NOT in any sibling batch, (d) an Instant
or Sorcery with a ``spell_effect`` that resolves directly with no
creature-trigger involvement.

The 3 cards pinned here (deck counts from ``data/17lands/
eoe_decks.json.gz`` at verify-first walk):

  1. Don't Make a Sound  (~0 17lands decks) — Instant,
     CounterTargetSpell(filter_types=frozenset())
  2. Commune with Evil   (~0 17lands decks) — Sorcery,
     Sequence(LookTopNPutOneInHandRestToGraveyard(n=4), GainLife(3))
  3. Trial of Agony      (~0 17lands decks) — Sorcery,
     DealDamageToTargetCreature(amount=5)

DROPPED-ON-VERIFY (honest verify-first discipline):

  * **Get Out** (~0 decks) — ``CounterTargetSpell(filter_types=
    frozenset({'Creature', 'Enchantment'}))``. The bridge arm returns
    ``CounterTargetSpell()`` with default empty ``filter_types`` — a
    schema narrowing (the Rust first slice does NOT plumb
    ``filter_types``). A probe using the real Get Out printing on the
    Python side would carry the non-empty filter while the Rust
    synthetic carrier has no filter. The field-view compare succeeds
    on most scenarios (the effect outcome — bait countered — is the
    same), but the Python class's ``legal_targets`` would exclude
    non-Creature/Enchantment baits that the Rust arm would still
    target. Bridge narrowness is documented; excluded until a
    Rust ``filter_types`` substrate lands.
  * **Temporal Intervention** (~1,715 decks) — ``spell_effect`` is
    ``TargetOpponentDiscardsCasterChoice`` (the CASTER picks which
    card the opponent discards). The ``discard_card`` bridge arm maps
    to ``TargetOpponentDiscards`` (the DISCARDER's own agent picks) —
    a genuinely DIFFERENT resolution semantic documented in the
    batch-G drops. Excluded.
  * **Split Up** (~0 decks) — ``ModalChooseOne(DestroyAllCreatures(
    tapped_only=True), DestroyAllCreatures(untapped_only=True))``.
    Rust's ``destroy_all_creatures`` bridge arm constructs the bare
    unrestricted ``DestroyAllCreatures()`` (no ``tapped_only`` /
    ``untapped_only`` narrowing fields). The tapped/untapped
    restriction is unplumbed; any probe scenario with creatures on
    BOTH tapped and untapped state would diverge. Excluded.
  * **Enter the Enigma** (~0 decks) — ``Sequence(GrantUnblockableUEOT,
    DrawCards(1))``. The ``grant_keyword_to_target_creature_until_eot``
    bridge arm returns ``PumpTargetCreatureUntilEOT(granted_keywords=
    {keyword})`` — a DIFFERENT Python class from ``GrantUnblockableUEOT``.
    The field-view compare reconstructs the Python class from the Rust
    dict via the bridge arm, yielding ``PumpTargetCreatureUntilEOT``
    rather than ``GrantUnblockableUEOT`` on the reconstructed side;
    the observables (keyword grant) may still agree, but the class
    mismatch is a structural bridge asymmetry. Excluded until a
    dedicated ``GrantUnblockableUEOT`` bridge arm lands.
  * **Dual-Sun Technique** (~3,734 decks) — ``PumpTargetCreatureUntilEOT``
    with ``draw_if_target_has_plus_one_counter=1``; the Rust
    ``pump_target_creature_until_eot`` bridge arm carries NO draw-if-
    counter rider. Documented in batch-G drops. Excluded.
  * **Come Back Wrong / Seized from Slumber / Unwanted Remake** (~0
    decks each) — all parse to ``DestroyTargetCreature(
    draw_if_undamaged_amount=0)`` — the same shape as Murder
    (batch J). Low marginal value; the ``destroy_target`` arm is
    already PROBED-level evidence via Murder. Excluded.
  * **Violent Urge / Give In to Violence / Rig for War / Jump Scare /
    Horrid Vigor / Dark Endurance** — all ``PumpTargetCreatureUntilEOT``
    with non-empty ``granted_keywords`` rider. The bridge arm does NOT
    plumb ``granted_keywords`` into the dict shape. Excluded per
    batch-M drop documentation.
  * **Manifest Dread / Under the Skin / Break Down the Door** — all
    ``ManifestDread``. The ManifestDread bridge is a bridge-defer (no
    ``manifest_dread`` bridge arm exists in the closed vocab). Excluded.
  * **Vanish from Sight** (~0 decks) — ``Sequence(
    OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary(
    nonland_permanent=True), Surveil(1))``. Two documented engine
    asymmetries prevent byte-equal compare_fields:
    (1) ``summoning_sick`` reset: Rust's arm (state_ops_resolve.rs:10158)
    explicitly sets ``obj.summoning_sick = true`` when moving the
    bounced creature to library; Python's ``zone_moves.py`` does NOT
    reset it — the pre-bounce value persists. (2) Top-vs-bottom default:
    Rust's arm uses ``lib_mut.push(obj)`` (appends to tail = bottom);
    Python's no-agent path uses ``choice=0`` = top (``library.insert(0,
    obj)``). Both are structural engine asymmetries in the library-bounce
    arm that require further parity work before a clean byte-equal probe
    is possible. Excluded.
  * **Demonic Counsel** (~0 decks) — ``SearchLibraryForCard(filter_name=
    'demon', may_fail=False)``. The ``search_library_for_card`` bridge
    arm requires a ``filter_name`` field; both engines search an empty
    library and produce the same no-op. However, the SearchLibrary bridge
    defer is documented in prior batches as a bridge-defer for the full-
    library-search path. The empty-library scenario avoids the defer, but
    the probe would be substantively weaker (no card moves). Excluded as
    low marginal value given the empty-library constraint.
  * NOTE: ``Trial of Agony`` (probe #3 here) has the same bridge arm as
    ``Scorching Dragonfire`` (batch M, ``deal_damage`` arm, amount=3) and
    ``Impossible Inferno`` (batch J, amount=6). Despite the arm being
    already PROBED, the CARD gains PROBED status by being driven via its
    ACTUAL parsed printing. Deck count is 0 but the card is in the
    covered-by-construction set and benefits from individual promotion.

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the batch_a / batch_b / batch_c / batch_d / batch_e / batch_f /
batch_g / batch_h / batch_i / batch_j / batch_k / batch_l /
spell_card_bridge_admitted / warp_admitted / warp_combat_interaction
modules nor the 6 ``test_audit_safe_trigger_*`` tests — those are
owned/protected; this module avoids all collision and touches no
STALENESS-SENTINEL). Registration in
``scripts/measure_pool_parity.PROBE_MODULES`` is the orchestrator's
separate wire-in step (per the established G/H/I/J/K/L/M batch
cadence).
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
# Batch-P probe #1 — Don't Make a Sound (~0 17lands decks; EoE).
#
# Covered (``CounterTargetSpell`` in covered set) + unprobed at HEAD.
# Oracle:
#   "[Instant] {2}{U} — Counter target spell."
# Parser -> ``spell_effect = CounterTargetSpell(filter_types=frozenset())``.
#
# The ``counter_target_spell`` bridge arm (cross_engine.py:4039)
# returns ``CounterTargetSpell()`` with default empty ``filter_types``,
# matching the genuine parsing exactly (``filter_types=frozenset()``
# is the default).
#
# Probe shape (mirrors the ``counterspell_side_channel`` pattern in
# cross_engine.py:15271 — the established bait-and-counter idiom):
#
#   Python side: push a vanilla Creature bait for p0 on the stack, then
#   push the GENUINE parsed "Don't Make a Sound" for p1 with target
#   ``("stack", 0)`` (the bait). Two ``resolve_top_of_stack`` calls:
#   first resolves the counter (sets bait.countered=True, routes
#   counter to p1's graveyard); second resolves the bait (countered
#   branch routes bait source to p0's graveyard without ETB).
#
#   Rust side: register bait and "Don't Make a Sound" synthetic
#   carriers, push both to stack, then one ``resolve_top_of_stack``
#   (Effect::CounterTargetSpell removes bait from stack + routes to
#   p0's graveyard inline, then move_source_post_resolve routes the
#   counter to p1's graveyard).
#
# Observable: bait in p0's graveyard, counter in p1's graveyard,
# both stacks empty, lives unchanged on BOTH. Full compare_fields
# byte-equal.
#
# This is the FIRST real-EoE probe of the ``counter_target_spell``
# bridge arm as a genuine EoE Instant card (the existing counterspell
# tests in test_parity_smoke.py use SYNTHETIC counter-printing
# objects, not the actual EoE parsing).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_dont_make_a_sound_counter_target_spell_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Don't Make a Sound
    (~0 17lands decks; genuine EoE covered card). Batch-P covered->PROBED.**

    Python: the ACTUAL parsed "Don't Make a Sound" printing on a
    ``StackItem`` targeting a bait creature spell (bait at stack[0],
    counter at stack[1]). Rust: the bridged
    ``{"kind":"counter_target_spell"}`` synthetic Instant pushing above
    the same bait in Rust's stack.

    Bait creature spell for p0 is placed on the stack first; then
    "Don't Make a Sound" is placed on top for p1 with the bait as its
    target. Counter resolves: bait is countered (goes to p0's graveyard
    without ETB), counter goes to p1's graveyard. Lives unchanged.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (empty battlefield, bait in p0's GY,
    counter in p1's GY, empty stacks, lives unchanged on BOTH).
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
        f"Don't Make a Sound filter_types must be empty frozenset; "
        f"got {se.filter_types}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2   # ZONE_BATTLEFIELD
    ZH = 0   # ZONE_HAND

    # ---- Python: bait creature spell on p0's stack slot 0. ----
    py_bait = py.new_object(
        CardPrinting(
            name="DMAS Bait Creature", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=0, zone=Zone.HAND,
    )
    py_bait.summoning_sick = False
    py.players[0].hand.append(py_bait)

    # Mimic p0 casting the bait: hand -> stack.
    py.players[0].hand.remove(py_bait)
    py_bait.zone = Zone.STACK
    py.stack.append(StackItem(source=py_bait, controller_id=0))

    # ---- Python: genuine "Don't Make a Sound" for p1 on stack slot 1
    # (top), targeting the bait at stack index 0. ----
    py_spell = py.new_object(real, owner_id=1, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell,
            controller_id=1,
            targets=(("stack", 0),),
        )
    )

    # Python: resolve counter (top of stack) first — bait gets
    # countered=True, counter source routes to p1 graveyard.
    resolve_top_of_stack(py)
    # Python: resolve bait (now top, countered) — routes to p0 GY,
    # no ETB fires.
    resolve_top_of_stack(py)
    py_sba(py)

    assert len(py.stack) == 0
    py_p0_gy_names = [o.printing.name for o in py.players[0].graveyard]
    py_p1_gy_names = [o.printing.name for o in py.players[1].graveyard]
    assert "DMAS Bait Creature" in py_p0_gy_names, (
        f"bait must be in p0 graveyard after counter (Python); "
        f"got {py_p0_gy_names}"
    )
    assert "Don't Make a Sound" in py_p1_gy_names, (
        f"Don't Make a Sound must be in p1 graveyard after resolve "
        f"(Python); got {py_p1_gy_names}"
    )
    assert py_bait not in py.battlefield, (
        "DMAS Bait Creature must NOT be on Python bf (countered spell)"
    )

    # ---- Rust: bait creature in ZONE_HAND, inject + push; then
    # counter printing injected, push on top. One resolve handles both.
    rs_bait_id = rs.register_and_inject_object(
        {"name": "DMAS Bait Creature",
         "card_types": ["Creature"],
         "power": 2, "toughness": 2},
        0, ZH,
    )
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Don't Make a Sound",
         "card_types": ["Instant"],
         "effects": [{"kind": "counter_target_spell"}]},
        1, ZH,
    )
    rs.push_to_stack(rs_bait_id, 0)     # bait at stack bottom
    rs.push_to_stack(rs_spell_id, 1)    # counter at top
    # Effect::CounterTargetSpell removes bait inline + routes both to
    # their respective graveyards in one resolve_top_of_stack call.
    rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.stack_size() == 0

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Don't Make a Sound counter-target-spell must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-P probe #2 — Commune with Evil (~0 17lands decks; EoE).
#
# Covered (``Sequence``, ``LookTopNPutOneInHandRestToGraveyard``, and
# ``GainLife`` all in covered set) + unprobed at HEAD. Oracle:
#   "[Sorcery] {2}{B} — Look at the top four cards of your library.
#    Put one of them into your hand and the rest into your graveyard.
#    You gain 3 life."
# Parser -> ``spell_effect = Sequence(effects=(
#   LookTopNPutOneInHandRestToGraveyard(n=4), GainLife(amount=3)))``.
#
# The ``sequence`` bridge arm (cross_engine.py:1494) recursively parses
# child effects. Both child arms are independently bridged:
#   * ``look_top_n_put_one_in_hand_rest_to_graveyard`` (n=4) — queues
#     ``PendingDecision::PickCardFromExaminedChoice`` and short-circuits;
#     ``resolve_top_of_stack`` auto-resolves via ``auto_resolve_pending``
#     with "keep_all_on_top" strategy (maps to pick_top = cards[0]).
#   * ``gain_life`` (amount=3) — resolves synchronously.
#
# Python determinism: ``LookTopNPutOneInHandRestToGraveyard.resolve``
# with ``agent=None`` falls through to ``examined[0]`` (the topmost
# examined card). Rust auto-resolve picks ``cards[0]`` (the same
# topmost). Both engines agree on which card goes to hand vs graveyard.
#
# Library setup: p0's library is seeded with 4 named cards so the
# probe can witness which card was chosen (examined[0] = "CwE Card A")
# and which went to graveyard. GainLife(3) fires after: p0's life
# increases by 3 on both engines.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_commune_with_evil_look_top_4_gain_life_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Commune with Evil
    (~0 17lands decks; genuine EoE covered card). Batch-P covered->PROBED.**

    Python: the ACTUAL parsed Commune with Evil printing on a
    ``StackItem`` (no target — Sorcery resolves via p0 controller).
    Rust: the bridged
    ``{"kind":"sequence","effects":[{"kind":
    "look_top_n_put_one_in_hand_rest_to_graveyard","n":4},
    {"kind":"gain_life","amount":3}]}`` synthetic Sorcery.

    p0's library is seeded with 4 identical "CwE Filler" 1/1 creatures via
    DeckSpec (ensuring matching IDs and ``summoning_sick=True`` on BOTH
    engines via the ``push_object`` path). Both engines look at the top 4
    cards; ``cards[0]`` / ``examined[0]`` (the topmost card, id=0) goes
    to p0's hand; ids 1,2,3 go to p0's graveyard. Then GainLife(3) fires:
    p0 life = 20 + 3 = 23 on BOTH.

    ``resolve_top_of_stack`` auto-resolves the
    ``PickCardFromExaminedChoice`` pending decision (via "keep_all_on_top"
    strategy's pick_top fallback) — no explicit ``auto_resolve_pending``
    call needed.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (p0 hand +1, p0 GY +3, p0 library empty,
    p0 life +3, p1 unchanged on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.library_lookat import (
        LookTopNPutOneInHandRestToGraveyard,
    )
    from mtg_bot.effects.generic.life import GainLife

    real = get_active_source().get_printings().get("Commune with Evil")
    if real is None:
        pytest.skip("Commune with Evil absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Commune with Evil spell_effect must be Sequence; "
        f"got {type(se).__name__}"
    )
    assert len(se.effects) == 2
    assert isinstance(se.effects[0], LookTopNPutOneInHandRestToGraveyard), (
        f"Commune with Evil first effect must be "
        f"LookTopNPutOneInHandRestToGraveyard; got "
        f"{type(se.effects[0]).__name__}"
    )
    assert se.effects[0].n == 4, (
        f"Commune with Evil LookTopN must be n=4; got {se.effects[0].n}"
    )
    assert isinstance(se.effects[1], GainLife), (
        f"Commune with Evil second effect must be GainLife; got "
        f"{type(se.effects[1]).__name__}"
    )
    assert se.effects[1].amount == 3, (
        f"Commune with Evil GainLife must be amount=3; got "
        f"{se.effects[1].amount}"
    )

    # Seed p0's library using DeckSpec with 4 identical filler cards.
    # DeckSpec's build_python_state / build_rust_state both use the
    # same `push_object` / `new_object` paths that allocate IDs
    # sequentially (0,1,2,3) and set summoning_sick=True for library
    # objects (CE1 / CR 302.1 parity fix). Using identical card names
    # so all 4 slots are interchangeable; the compare_fields 8-tuple
    # comparison only needs the values to be byte-equal, not distinct.
    filler = CardDef(
        name="CwE Filler", card_type="Creature", power=1, toughness=1,
    )
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=("CwE Filler",) * 4,
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0   # ZONE_HAND
    # p0 already has 4 "CwE Filler" cards in library (ids 0..3),
    # summoning_sick=True on BOTH engines via the DeckSpec path.

    # ---- Python: genuine parsed Commune with Evil on a StackItem,
    # controller p0 (Sorcery — no target). ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0, targets=())
    )

    py_life_before = py.players[0].life  # = 20
    py_hand_before = len(py.players[0].hand)  # = 0 (empty hand from spec)
    py_lib_before = len(py.players[0].library)  # = 4

    # No agent on p0 -> LookTopNPutOneInHandRestToGraveyard falls through
    # to examined[0] (library[0] = id=0 "CwE Filler") for hand; the rest
    # (ids 1,2,3) go to graveyard. Then GainLife(3).
    resolve_top_of_stack(py)
    py_sba(py)

    assert len(py.stack) == 0
    # Hand grew by 1: the examined[0] CwE Filler (id=0).
    assert len(py.players[0].hand) == py_hand_before + 1, (
        f"Commune with Evil: p0 hand must grow by 1 (Python); "
        f"got {len(py.players[0].hand)}"
    )
    py_hand_names = [o.printing.name for o in py.players[0].hand]
    assert py_hand_names == ["CwE Filler"], (
        f"Commune with Evil: hand must contain 'CwE Filler' (Python); "
        f"got {py_hand_names}"
    )
    # Library is now empty (all 4 examined cards moved: 1 to hand, 3 to GY).
    assert len(py.players[0].library) == 0, (
        f"Commune with Evil: p0 library must be empty after "
        f"look-4 (Python); size={len(py.players[0].library)}"
    )
    # Graveyard has 3 CwE Fillers + Commune with Evil.
    py_gy = py.players[0].graveyard
    assert len(py_gy) == 4, (
        f"Commune with Evil: p0 GY must have 4 cards (3 fillers + spell) "
        f"(Python); got {len(py_gy)}"
    )
    # GainLife(3) fired: p0 life = 20 + 3 = 23.
    assert py.players[0].life == py_life_before + 3, (
        f"Commune with Evil: p0 life must be {py_life_before + 3} "
        f"after GainLife(3) (Python); got {py.players[0].life}"
    )

    # ---- Rust: bridged Sequence(look_top_n=4, gain_life=3) synthetic
    # Sorcery. The library is already seeded with 4 CwE Filler cards
    # (ids 0..3, summoning_sick=True) from build_rust_state(spec).
    # The spell is injected separately so register_and_inject_object
    # picks the next available id (=4) — matching Python's id=4.
    rs_life_before = rs.get_life(0)

    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Commune with Evil",
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind": "sequence",
                    "effects": [
                        {
                            "kind": (
                                "look_top_n_put_one_in_hand_rest_to_graveyard"
                            ),
                            "n": 4,
                        },
                        {"kind": "gain_life", "amount": 3},
                    ],
                }
            ],
        },
        0, ZH,
    )

    rs.push_to_stack(rs_spell_id, 0)
    # resolve_top_of_stack auto-resolves the PickCardFromExaminedChoice
    # pending decision (auto_resolve_pending "keep_all_on_top" maps
    # PickCardFromExamined to pick cards[0] — the topmost filler with
    # id=0). GainLife(3) fires synchronously inside the Sequence arm's
    # per-child auto_resolve_pending loop.
    rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.stack_size() == 0
    assert rs.library_sizes[0] == 0, (
        f"Commune with Evil: Rust p0 library must be empty after "
        f"look-4; got {rs.library_sizes[0]}"
    )
    assert rs.hand_sizes[0] == 1, (
        f"Commune with Evil: Rust p0 hand must have 1 card; "
        f"got {rs.hand_sizes[0]}"
    )
    assert rs.get_life(0) == rs_life_before + 3, (
        f"Commune with Evil: Rust p0 life must be {rs_life_before + 3} "
        f"after GainLife(3); got {rs.get_life(0)}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Commune with Evil look-top-4/gain-life-3 must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-P probe #3 — Trial of Agony (~0 17lands decks; EoE).
#
# Covered (``DealDamageToTargetCreature`` in covered set) + unprobed
# at HEAD. Oracle:
#   "[Sorcery] {3}{R} — Trial of Agony deals 5 damage to target
#    creature."
# Parser -> ``spell_effect = DealDamageToTargetCreature(amount=5,
#   targets=(TargetSpec(IsCreature()),), optional=False)``.
#
# The ``deal_damage`` bridge arm (cross_engine.py:568) with
# ``target: {"kind": "any_creature"}`` maps to Python's
# ``DealDamageToTargetCreature``. Same bridge arm as Scorching
# Dragonfire (batch M, amount=3) and Impossible Inferno (batch J,
# amount=6). Despite the arm being PROBED via those cards, Trial of
# Agony itself gains PROBED status by being driven through its ACTUAL
# parsed EoE printing.
#
# A vanilla 2/6 creature is seated on p1's bf: 5 damage < 6
# toughness, so the creature SURVIVES with 5 damage counters on BOTH
# engines — the non-lethal-damage branch confirms the amount=5
# variant is byte-equal. Rust picks the first creature on the
# defender's bf; Python's ``_PickFirstOpponentTargetAgent`` mirrors
# that pick exactly (single opponent creature -> forced).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_trial_of_agony_deal_5_damage_to_creature_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Trial of Agony
    (~0 17lands decks; genuine EoE covered card). Batch-P covered->PROBED.**

    Python: the ACTUAL parsed Trial of Agony printing on a
    ``StackItem`` with the chosen creature target. Rust: the bridged
    ``{"kind":"deal_damage","amount":5,"target":{"kind":"any_creature"}}``
    synthetic Sorcery (AnyCreature first-slice picker -> p1 bf[0]).

    A vanilla 2/6 creature on p1's bf takes 5 non-lethal damage and
    survives (5 < 6 toughness). The observable: creature remains on bf
    with 5 damage counters on BOTH engines. This probe drives Trial of
    Agony's ACTUAL EoE parsing to earn PROBED tier; the ``deal_damage``
    bridge arm was already exercised by Scorching Dragonfire (batch M,
    amount=3, non-lethal) and Impossible Inferno (batch J, amount=6,
    lethal). Trial of Agony's amount=5 is in the same non-lethal branch
    as Scorching Dragonfire but with a different card identity and amount.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (2/6 still on p1's battlefield with 5
    damage; no graveyard movement; lives unchanged on BOTH).
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
    from mtg_bot.effects.generic.damage import DealDamageToTargetCreature
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Trial of Agony")
    if real is None:
        pytest.skip("Trial of Agony absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, DealDamageToTargetCreature), (
        f"genuine Trial of Agony spell_effect must be "
        f"DealDamageToTargetCreature; got {type(se).__name__}"
    )
    assert se.amount == 5, (
        f"Trial of Agony must deal 5 damage; got {se.amount}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD
    ZH = 0  # ZONE_HAND

    # p1 has a single 2/6 creature. 5 damage < 6 toughness -> survives.
    # Observables: creature remains on bf with 5 damage counters on BOTH.
    py_vic = py.new_object(
        CardPrinting(
            name="ToA Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=6, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "ToA Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 6}, 1, ZB,
    )

    # ---- Python: genuine parsed Trial of Agony on a StackItem,
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
    assert py_vic in py.battlefield, (
        "ToA Victim (2/6) must survive 5 non-lethal damage (Python)"
    )
    assert py_vic.damage == 5, (
        f"ToA Victim must have 5 damage counters (Python); "
        f"got {py_vic.damage}"
    )

    # ---- Rust: bridged deal_damage any_creature(5) synthetic Sorcery. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Trial of Agony", "card_types": ["Sorcery"],
         "effects": [{"kind": "deal_damage", "amount": 5,
                      "target": {"kind": "any_creature"}}]},
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_vic_state = next(
        (e for e in rs.battlefield_snapshot() if e["id"] == rs_vic_id),
        None,
    )
    assert rs_vic_state is not None, (
        "ToA Victim (2/6) must survive 5 non-lethal damage (Rust)"
    )
    assert rs_vic_state.get("damage", 0) == 5, (
        f"ToA Victim must have 5 damage (Rust); "
        f"got {rs_vic_state.get('damage', 0)}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Trial of Agony deal-5-to-creature must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )
