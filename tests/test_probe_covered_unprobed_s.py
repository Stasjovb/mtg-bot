"""Genuine real-EoE cross-engine byte-equality probes — batch S.

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

PARTITION DISCIPLINE (batch S — SORCERY round 5, after G + J + M + P)
-----------------------------------------------------------------------
This module is batch S, the fifth round of SORCERY (and trivially-
resolving INSTANT) covered-but-unprobed probes, extending the sorcery
lane after batches G (Scrounge for Eternity / Pyroclasm / Final
Vengeance), J (Murder / Impossible Inferno / Midnight Mayhem /
Winter's Intervention), M (Scorching Dragonfire / Untimely
Malfunction / Turn Inside Out), and P (Don't Make a Sound / Commune
with Evil / Trial of Agony). Sibling agents T (activated-abilities,
continuing Q) and U (modal+counter-spell, continuing R) run in
parallel worktrees. The covered-by-construction-but-unprobed list
(computed read-only via ``scripts/measure_pool_parity.classify_pool``,
sorted by 17lands deck count desc) was verify-first-recomputed at live
HEAD ef69f634; every card below is (a) covered-by-construction, (b)
NOT individually probed, (c) NOT in any sibling batch, (d) an Instant
or Sorcery with a ``spell_effect`` that resolves directly with no
creature-trigger involvement.

The 3 cards pinned here (deck counts from ``data/17lands/
eoe_decks.json.gz`` at verify-first walk):

  1. Drag to the Roots  (~0 17lands decks) — Instant,
     DestroyTargetNonlandPermanent()
  2. Emerge from the Cocoon  (~0 17lands decks) — Sorcery,
     Sequence(ReturnCreatureFromYourGraveyardToBattlefield,
     GainLife(3))
  3. Glimmerburst  (~0 17lands decks) — Instant,
     Sequence(DrawCards(2), CreateToken(Glimmer 1/1
     Enchantment+Creature, count=1))

DROPPED-ON-VERIFY (honest verify-first discipline):

  * **Come Back Wrong / Seized from Slumber / Unwanted Remake** (~0
    decks each) — all parse to ``DestroyTargetCreature(
    draw_if_undamaged_amount=0)`` — the same shape as Murder (batch
    J). Low marginal value; the ``destroy_target`` arm is already
    PROBED-level evidence via Murder. Excluded.
  * **Withering Torment** (~0 decks) — ``Sequence(
    DestroyTargetCreature(or_enchantment=True), LoseLife(2))``. The
    ``destroy_target`` bridge arm (``cross_engine.py``) only supports
    ``any_creature`` filter and does NOT plumb the ``or_enchantment``
    rider. A probe using the real Withering Torment printing on the
    Python side would carry ``or_enchantment=True`` while the Rust
    synthetic carrier must use the bare ``any_creature`` filter. The
    field-view compare succeeds on scenarios where only creatures are
    present, but the Python class's ``legal_targets`` would admit
    enchantments that the Rust arm would not. Bridge narrowness is
    documented; excluded until a Rust ``or_enchantment`` substrate
    lands on the destroy arm.
  * **Temporal Intervention** (~0 decks) — ``TargetOpponentDiscardsCasterChoice``
    (the CASTER picks which card the opponent discards). The
    ``discard_card`` bridge arm maps to ``TargetOpponentDiscards``
    (the DISCARDER's own agent picks) — a genuinely DIFFERENT
    resolution semantic documented in the batch-G drops. Excluded.
  * **Diplomatic Relations** (~0 decks) — ``DiplomaticRelationsEffect()``.
    The ``diplomatic_relations_effect`` bridge arm exists and the
    Python class has a working 2-slot resolve. However, the Rust
    ``push_to_stack`` API only seats ``target_obj_id_2 = None``
    (Phase-1 single-target contract); the 2-slot target binding that
    ``DiplomaticRelationsEffect`` requires must go through
    ``cast_spell_noncreature`` (the production cast path), not the
    synthetic ``push_to_stack`` probe idiom. The synthetic probe
    pattern cannot seat two distinct targets simultaneously via
    ``push_to_stack``. Excluded until a 2-slot synthetic-push variant
    lands in the Rust API.
  * **Manifest Dread / Under the Skin / Break Down the Door /
    Unnerving Grasp** — all contain ``ManifestDread``. The
    ManifestDread bridge is a bridge-defer (no ``manifest_dread``
    bridge arm exists in the closed vocab). Excluded.
  * **Dual-Sun Technique / Give In to Violence / Dark Endurance /
    Jump Scare / Horrid Vigor / Rig for War / Violent Urge** — all
    ``PumpTargetCreatureUntilEOT`` with non-empty ``granted_keywords``
    rider. The bridge arm does NOT plumb ``granted_keywords`` into the
    dict shape. Excluded per batch-M drop documentation.
  * **Let's Play a Game** (~0 decks) — ``ModalChooseOne(
    PumpCreaturesOpponentsControlUntilEOT, EachOpponentDiscards(2),
    Sequence(EachOpponentLosesLife(3), GainLife(3)))``. Modal card
    → lane U (modal+counter-spell partition). Excluded from this
    (sorcery) lane.
  * **Split Up** (~0 decks) — ``ModalChooseOne(DestroyAllCreatures(
    tapped_only=True), DestroyAllCreatures(untapped_only=True))``.
    Modal card AND tapped/untapped narrowing unplumbed in Rust's
    ``destroy_all_creatures`` arm. Excluded (both modal and known
    gap class).
  * **Demonic Counsel** (~0 decks) — ``SearchLibraryForCard(filter_name=
    'demon', may_fail=False)``. SearchLibrary bridge-defer documented
    in prior batches; the empty-library scenario avoids the defer but
    the probe would be substantively weaker (no card moves). Excluded
    as low marginal value given the empty-library constraint.

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the batch_a / batch_b / batch_c / batch_d / batch_e / batch_f /
batch_g / batch_h / batch_i / batch_j / batch_k / batch_l /
spell_card_bridge_admitted / warp_admitted / warp_combat_interaction
modules nor the 6 ``test_audit_safe_trigger_*`` tests — those are
owned/protected; this module avoids all collision and touches no
STALENESS-SENTINEL). Registration in
``scripts/measure_pool_parity.PROBE_MODULES`` is the orchestrator's
separate wire-in step (per the established G/H/I/J/K/L/M/P batch
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
# Batch-S probe #1 — Drag to the Roots (~0 17lands decks; EoE).
#
# Covered (``DestroyTargetNonlandPermanent`` in covered set) + unprobed
# at HEAD. Oracle:
#   "[Instant] {2}{B} — Destroy target nonland permanent."
# Parser -> ``spell_effect = DestroyTargetNonlandPermanent(
#   targets=(TargetSpec(~IsLand() & ~IsPlayer(), ...),))``.
#
# The ``destroy_target_nonland_permanent`` bridge arm (cross_engine.py)
# is a UNIT VARIANT — no companion fields beyond ``kind``. Python's
# ``DestroyTargetNonlandPermanent`` is a frozen dataclass with no
# constructor parameters (the ``targets`` tuple is set in
# ``__post_init__`` to a ``TargetSpec(~IsLand() & ~IsPlayer())``).
# The bridge constructs the bare class.
#
# Probe shape (mirrors the ``destroy_target`` / ``deal_damage``
# first-creature idiom — the established creature-victim pattern):
#
#   Python side: a vanilla 2/2 creature ("DtR Victim") on p1's
#   battlefield. p0 casts the GENUINE parsed "Drag to the Roots"
#   with the victim as the chosen nonland-permanent target. The spell
#   resolves: victim is destroyed (moves to p1's graveyard), Drag to
#   the Roots moves to p0's graveyard. Lives unchanged.
#
#   Rust side: the victim injected onto p1's bf; synthetic
#   ``{"kind":"destroy_target_nonland_permanent"}`` carrier pushed to
#   stack by p0. Rust's resolve arm scans BOTH players' bf in
#   ETB-timestamp order and picks the first non-Land, non-indestructible
#   permanent (the victim). Both stacks empty post-resolve.
#
# Observable: victim in p1's graveyard, spell in p0's graveyard,
# empty battlefields, lives unchanged on BOTH. Full compare_fields
# byte-equal.
#
# This is the FIRST real-EoE probe of the
# ``destroy_target_nonland_permanent`` bridge arm as a genuine EoE
# Instant card (the arm was previously exercised only via synthetic
# carriers in the existing test suite).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_drag_to_the_roots_destroy_nonland_permanent_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Drag to the Roots
    (~0 17lands decks; genuine EoE covered card). Batch-S covered->PROBED.**

    Python: the ACTUAL parsed "Drag to the Roots" printing on a
    ``StackItem`` targeting a vanilla 2/2 creature on p1's battlefield
    (nonland permanent). Rust: the bridged
    ``{"kind":"destroy_target_nonland_permanent"}`` synthetic Instant
    (unit variant — no companion fields) pushed by p0.

    A vanilla 2/2 creature ("DtR Victim") is seated on p1's battlefield.
    p0 casts the Instant: the victim is destroyed and moves to p1's
    graveyard on BOTH engines; the spell itself routes to p0's graveyard.
    Lives unchanged.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (empty battlefields, victim in p1's GY,
    spell in p0's GY, both stacks empty, lives unchanged on BOTH).
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
    from mtg_bot.effects.generic.destroy import DestroyTargetNonlandPermanent
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Drag to the Roots")
    if real is None:
        pytest.skip("Drag to the Roots absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, DestroyTargetNonlandPermanent), (
        f"genuine Drag to the Roots spell_effect must be "
        f"DestroyTargetNonlandPermanent; got {type(se).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2   # ZONE_BATTLEFIELD
    ZH = 0   # ZONE_HAND

    # ---- Python: a vanilla 2/2 creature on p1's battlefield. ----
    py_vic = py.new_object(
        CardPrinting(
            name="DtR Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)

    # ---- Python: genuine "Drag to the Roots" for p0 on the stack,
    # targeting the victim (nonland permanent). ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell,
            controller_id=0,
            targets=(("creature", py_vic.id),),
        )
    )

    resolve_top_of_stack(py)
    py_sba(py)

    assert len(py.stack) == 0
    assert py_vic not in py.battlefield, (
        "DtR Victim must NOT be on Python bf (destroyed)"
    )
    py_p1_gy_names = [o.printing.name for o in py.players[1].graveyard]
    py_p0_gy_names = [o.printing.name for o in py.players[0].graveyard]
    assert "DtR Victim" in py_p1_gy_names, (
        f"victim must be in p1's graveyard after destroy (Python); "
        f"got {py_p1_gy_names}"
    )
    assert "Drag to the Roots" in py_p0_gy_names, (
        f"Drag to the Roots must be in p0's graveyard (Python); "
        f"got {py_p0_gy_names}"
    )

    # ---- Rust: victim on p1's bf; synthetic destroy-nonland-permanent
    # Instant pushed by p0. Unit variant — no companion fields. ----
    rs_vic_id = rs.register_and_inject_object(
        {"name": "DtR Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2},
        1, ZB,
    )
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Drag to the Roots", "card_types": ["Instant"],
         "effects": [{"kind": "destroy_target_nonland_permanent"}]},
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.stack_size() == 0
    rs_bf_names = [e["printing_name"] for e in rs.battlefield_snapshot()]
    assert "DtR Victim" not in rs_bf_names, (
        "DtR Victim must NOT be on Rust bf (destroyed)"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Drag to the Roots destroy-nonland-permanent must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-S probe #2 — Emerge from the Cocoon (~0 17lands decks; EoE).
#
# Covered (``Sequence``, ``ReturnCreatureFromYourGraveyardToBattlefield``,
# and ``GainLife`` all in covered set) + unprobed at HEAD. Oracle:
#   "[Sorcery] {3}{G} — Return target creature card from your graveyard
#    to the battlefield. You gain 3 life."
# Parser -> ``spell_effect = Sequence(effects=(
#   ReturnCreatureFromYourGraveyardToBattlefield(), GainLife(amount=3)))``.
#
# The ``sequence`` bridge arm (cross_engine.py) recursively parses
# child effects. Both child arms are independently bridged:
#   * ``return_creature_from_your_graveyard_to_battlefield`` (unit
#     variant) — Rust scans source-controller's graveyard top-to-bottom
#     for the first creature card and moves it to the battlefield (I83
#     controller-of-effect fix: derives controller from
#     ``current_resolve_source_controller``). Python's
#     ``ReturnCreatureFromYourGraveyardToBattlefield.resolve`` drives
#     off the ``targets`` tuple (``("graveyard_creature", id)``), which
#     the probe seats explicitly in the StackItem.
#   * ``gain_life`` (amount=3) — resolves synchronously.
#
# Python determinism: the graveyard_creature target is explicitly bound
# in the StackItem's ``targets`` tuple (mirroring the push-time cast
# binding). Rust's unit-variant arm scans the graveyard iterator-order
# and picks the first creature (the only creature present). Both
# engines agree: the corpse returns to p0's bf, p0 gains 3 life.
#
# Graveyard setup: p0's graveyard is seeded with one named creature
# ("EftC Corpse" 2/2) directly injected (not via library→draw). Rust
# uses graveyard zone 3 for injection. Python uses Zone.GRAVEYARD.
# After resolve: corpse on p0's bf, p0 life = 23, Emerge routes to
# p0's graveyard. Full compare_fields byte-equal.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_emerge_from_the_cocoon_reanimate_gain_life_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Emerge from the Cocoon
    (~0 17lands decks; genuine EoE covered card). Batch-S covered->PROBED.**

    Python: the ACTUAL parsed Emerge from the Cocoon printing on a
    ``StackItem`` with the graveyard_creature target explicitly bound.
    Rust: the bridged ``{"kind":"sequence","effects":[
    {"kind":"return_creature_from_your_graveyard_to_battlefield"},
    {"kind":"gain_life","amount":3}]}`` synthetic Sorcery.

    p0's graveyard is seeded with a single 2/2 creature ("EftC Corpse").
    The spell resolves: the corpse returns to p0's bf (controller stamped
    p0 via I83 controller-of-effect fix), p0 gains 3 life (life = 23).
    Emerge from the Cocoon routes to p0's graveyard. Both stacks empty
    post-resolve.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (corpse on p0's bf, p0 life = 23, spell in
    p0's GY, both stacks empty, p1 unchanged on BOTH).
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
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Emerge from the Cocoon")
    if real is None:
        pytest.skip("Emerge from the Cocoon absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Emerge from the Cocoon spell_effect must be Sequence; "
        f"got {type(se).__name__}"
    )
    assert len(se.effects) == 2
    assert isinstance(
        se.effects[0], ReturnCreatureFromYourGraveyardToBattlefield
    ), (
        f"Emerge from the Cocoon first effect must be "
        f"ReturnCreatureFromYourGraveyardToBattlefield; got "
        f"{type(se.effects[0]).__name__}"
    )
    assert isinstance(se.effects[1], GainLife), (
        f"Emerge from the Cocoon second effect must be GainLife; got "
        f"{type(se.effects[1]).__name__}"
    )
    assert se.effects[1].amount == 3, (
        f"Emerge from the Cocoon GainLife must be amount=3; "
        f"got {se.effects[1].amount}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0   # ZONE_HAND
    ZG = 3   # ZONE_GRAVEYARD

    # ---- Python: seed a 2/2 creature into p0's graveyard. ----
    py_corpse = py.new_object(
        CardPrinting(
            name="EftC Corpse", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=0, zone=Zone.GRAVEYARD,
    )
    py.players[0].graveyard.append(py_corpse)

    py_life_before = py.players[0].life  # = 20

    # ---- Python: genuine Emerge from the Cocoon on a StackItem,
    # controller p0, with the graveyard_creature target explicitly bound.
    # The ReturnCreatureFromYourGraveyardToBattlefield.resolve checks
    # ``if not targets: return`` — the target must be bound at push time.
    # ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell,
            controller_id=0,
            targets=(("graveyard_creature", py_corpse.id),),
        )
    )
    resolve_top_of_stack(py)
    py_sba(py)

    assert len(py.stack) == 0
    # Corpse must be on p0's bf after reanimation.
    py_corpse_on_bf = next(
        (o for o in py.battlefield if o.printing.name == "EftC Corpse"),
        None,
    )
    assert py_corpse_on_bf is not None, (
        "EftC Corpse must be on Python p0's bf after reanimation"
    )
    assert py_corpse_on_bf.controller_id == 0, (
        f"EftC Corpse must be controller=0 (Python); "
        f"got {py_corpse_on_bf.controller_id}"
    )
    # p0 graveyard must have the spell (corpse left); spell routes there.
    py_p0_gy_names = [o.printing.name for o in py.players[0].graveyard]
    assert "Emerge from the Cocoon" in py_p0_gy_names, (
        f"Emerge from the Cocoon must be in p0's graveyard (Python); "
        f"got {py_p0_gy_names}"
    )
    # GainLife(3) fired: p0 life = 20 + 3 = 23.
    assert py.players[0].life == py_life_before + 3, (
        f"Emerge from the Cocoon: p0 life must be {py_life_before + 3} "
        f"after GainLife(3) (Python); got {py.players[0].life}"
    )

    # ---- Rust: seed corpse in p0's graveyard (zone 3). Rust's
    # return_creature_from_your_graveyard_to_battlefield resolve scans
    # source-controller's graveyard iterator-order, picks first creature. ----
    rs_corpse_id = rs.register_and_inject_object(
        {"name": "EftC Corpse", "card_types": ["Creature"],
         "power": 2, "toughness": 2},
        0, ZG,
    )
    assert rs.find_object_zone(rs_corpse_id) == ZG

    rs_life_before = rs.get_life(0)

    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Emerge from the Cocoon",
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind": "sequence",
                    "effects": [
                        {
                            "kind": (
                                "return_creature_from_your_graveyard_to_battlefield"
                            ),
                        },
                        {"kind": "gain_life", "amount": 3},
                    ],
                }
            ],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.stack_size() == 0
    rs_bf = rs.battlefield_snapshot()
    rs_corpse_state = next(
        (e for e in rs_bf if e["printing_name"] == "EftC Corpse"),
        None,
    )
    assert rs_corpse_state is not None, (
        "EftC Corpse must be on Rust bf after reanimation"
    )
    assert rs_corpse_state.get("controller_id") == 0, (
        f"EftC Corpse must be controller=0 (Rust); "
        f"got {rs_corpse_state.get('controller_id')}"
    )
    assert rs.get_life(0) == rs_life_before + 3, (
        f"Emerge from the Cocoon: Rust p0 life must be "
        f"{rs_life_before + 3} after GainLife(3); got {rs.get_life(0)}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Emerge from the Cocoon reanimate+gain-life-3 must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-S probe #3 — Glimmerburst (~0 17lands decks; EoE).
#
# Covered (``Sequence``, ``DrawCards``, and ``CreateToken`` all in
# covered set) + unprobed at HEAD. Oracle:
#   "[Instant] {2}{W}{U} — Draw two cards. Create a 1/1 white Glimmer
#    enchantment creature token."
# Parser -> ``spell_effect = Sequence(effects=(DrawCards(amount=2),
#   CreateToken(token_printing=Glimmer 1/1 Enchantment+Creature,
#   count=1, tapped=False, each_player=False)))``.
#
# The ``sequence`` bridge arm recursively parses child effects:
#   * ``draw_cards`` (count=2) — Rust parse arm uses ``"count"`` key
#     (NOT ``"amount"``); Python's ``DrawCards.amount`` maps from that
#     key. DrawCards draws from p0's library (2 cards seeded via
#     DeckSpec); p0 hand grows by 2.
#   * ``create_token`` (count=1, token_printing_id=<glimmer_pid>) —
#     Rust creates a Glimmer 1/1 Enchantment+Creature token on the
#     source-controller's (p0's) bf. Python's ``CreateToken.resolve``
#     mints from the registered ``TOKEN_PRINTINGS["Glimmer"]`` printing.
#
# Glimmer token registration: following the established
# ``register_token_printing(pid, py_printing)`` idiom (e.g. Tunnel
# Surveyor probe in batch H, Galactic Wayfarer probe in
# test_parity_smoke.py). The Glimmer token printing pid is obtained
# from ``rs.registry_size`` before injection; the token seed is
# injected into p0's HAND (zone 0) on Rust (the only reliable ordering
# technique — library injection prepends to the top, which would
# interfere with draw order). The Python side mirrors the seed via
# ``py.players[0].hand.append(py_glimmer_seed)``. Post-spell, both
# sides have: hand = [Glimmer-seed, GB Filler × 2], bf = [Glimmer-token].
#
# Library setup: p0's library is seeded with 2 "GB Filler" 1/1
# creatures via DeckSpec (both engines build the same id-0/id-1 ordering
# so the DrawCards draw is symmetric).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_glimmerburst_draw_2_create_glimmer_token_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Glimmerburst
    (~0 17lands decks; genuine EoE covered card). Batch-S covered->PROBED.**

    Python: the ACTUAL parsed Glimmerburst printing on a ``StackItem``
    (no target — Instant resolves via p0 controller). Rust: the bridged
    ``{"kind":"sequence","effects":[{"kind":"draw_cards","count":2},
    {"kind":"create_token","count":1,"token_printing_id":<glimmer_pid>}]}``
    synthetic Instant.

    p0's library is seeded with 2 "GB Filler" 1/1 creatures via DeckSpec.
    A Glimmer token printing is registered on both engines (pid from
    ``rs.registry_size``; seed injected into p0's HAND so library
    draw-order is unaffected). After resolve: p0 draws 2 cards (hand
    grows by 2), 1 Glimmer 1/1 Enchantment+Creature token appears on
    p0's bf, Glimmerburst routes to p0's graveyard. Both stacks empty.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (p0 hand +2 fillers + 1 Glimmer-seed,
    p0 library empty, 1 Glimmer token on p0's bf, spell in p0's GY,
    p1 unchanged, lives unchanged on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
        register_token_printing, clear_token_printings,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.tokens import CreateToken

    clear_token_printings()

    real = get_active_source().get_printings().get("Glimmerburst")
    if real is None:
        pytest.skip("Glimmerburst absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Glimmerburst spell_effect must be Sequence; "
        f"got {type(se).__name__}"
    )
    assert len(se.effects) == 2
    assert isinstance(se.effects[0], DrawCards), (
        f"Glimmerburst first effect must be DrawCards; got "
        f"{type(se.effects[0]).__name__}"
    )
    assert se.effects[0].amount == 2, (
        f"Glimmerburst DrawCards must be amount=2; "
        f"got {se.effects[0].amount}"
    )
    assert isinstance(se.effects[1], CreateToken), (
        f"Glimmerburst second effect must be CreateToken; got "
        f"{type(se.effects[1]).__name__}"
    )
    assert se.effects[1].token_printing.name == "Glimmer", (
        f"Glimmerburst CreateToken must mint a Glimmer token; "
        f"got {se.effects[1].token_printing.name!r}"
    )
    assert se.effects[1].count == 1, (
        f"Glimmerburst CreateToken must be count=1; "
        f"got {se.effects[1].count}"
    )

    # Seed p0's library with 2 filler cards via DeckSpec (ids 0 and 1;
    # summoning_sick=True from DeckSpec push path — byte-equal on BOTH).
    filler = CardDef(
        name="GB Filler", card_type="Creature", power=1, toughness=1,
    )
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=("GB Filler", "GB Filler"),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0   # ZONE_HAND

    # ---- Register Glimmer token pid on Rust (established
    # token-pid idiom). Inject into HAND (zone 0) on Rust so the seed
    # appears in p0's hand field view. Mirror in Python via hand append.
    # Using HAND (not library) preserves the DeckSpec library draw
    # order: library injection via register_and_inject_object prepends
    # to the top of the library Vec (making the Glimmer drawn first,
    # diverging from Python's append-to-end ordering). ----
    glimmer_pid = rs.registry_size
    rs.register_and_inject_object(
        {"name": "Glimmer", "card_types": ["Enchantment", "Creature"],
         "supertypes": ["Token"], "power": 1, "toughness": 1,
         "mana_cost": {"generic": 0}},
        0, ZH,  # ZONE_HAND (inert seed for pid assignment)
    )
    py_glimmer_seed = py.new_object(
        TOKEN_PRINTINGS["Glimmer"], owner_id=0, zone=Zone.HAND,
    )
    py_glimmer_seed.summoning_sick = False
    py.players[0].hand.append(py_glimmer_seed)
    register_token_printing(glimmer_pid, TOKEN_PRINTINGS["Glimmer"])

    py_lib_before = len(py.players[0].library)  # = 2
    py_hand_before = len(py.players[0].hand)     # = 1 (the Glimmer seed)

    # ---- Python: genuine parsed Glimmerburst on a StackItem,
    # controller p0 (Instant — no target). ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0, targets=())
    )
    resolve_top_of_stack(py)
    py_sba(py)

    assert len(py.stack) == 0
    # DrawCards(2): p0 library drains by 2, hand grows by 2.
    assert len(py.players[0].library) == 0, (
        f"Glimmerburst: p0 library must be empty after DrawCards(2) "
        f"(Python); size={len(py.players[0].library)}"
    )
    assert len(py.players[0].hand) == py_hand_before + 2, (
        f"Glimmerburst: p0 hand must grow by 2 after DrawCards(2) "
        f"(Python); got {len(py.players[0].hand)}"
    )
    # CreateToken(Glimmer, 1): 1 Glimmer token on p0's bf.
    py_glimmer_tokens = [
        o for o in py.battlefield if o.printing.name == "Glimmer"
    ]
    assert len(py_glimmer_tokens) == 1, (
        f"Glimmerburst: exactly 1 Glimmer token on Python p0's bf; "
        f"got {len(py_glimmer_tokens)}"
    )
    # Glimmerburst routes to p0's graveyard.
    py_p0_gy_names = [o.printing.name for o in py.players[0].graveyard]
    assert "Glimmerburst" in py_p0_gy_names, (
        f"Glimmerburst must be in p0's graveyard (Python); "
        f"got {py_p0_gy_names}"
    )

    # ---- Rust: bridged Sequence(draw_cards count=2, create_token
    # Glimmer pid) synthetic Instant. The library is already seeded
    # with 2 GB Filler cards (ids 0+1) from build_rust_state(spec).
    # The Glimmer seed is already in p0's hand (id=2, injected above).
    # The spell is injected next (id=3) — matching Python's id=3.
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Glimmerburst",
            "card_types": ["Instant"],
            "effects": [
                {
                    "kind": "sequence",
                    "effects": [
                        {"kind": "draw_cards", "count": 2},
                        {
                            "kind": "create_token",
                            "count": 1,
                            "token_printing_id": glimmer_pid,
                        },
                    ],
                }
            ],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert rs.stack_size() == 0
    assert rs.library_sizes[0] == 0, (
        f"Glimmerburst: Rust p0 library must be empty after "
        f"DrawCards(2); got {rs.library_sizes[0]}"
    )
    assert rs.hand_sizes[0] == py_hand_before + 2, (
        f"Glimmerburst: Rust p0 hand must be {py_hand_before + 2} "
        f"(seed + 2 drawn); got {rs.hand_sizes[0]}"
    )
    rs_glimmer_tokens = [
        e for e in rs.battlefield_snapshot()
        if e["printing_name"] == "Glimmer"
    ]
    assert len(rs_glimmer_tokens) == 1, (
        f"Glimmerburst: exactly 1 Glimmer token on Rust p0's bf; "
        f"got {len(rs_glimmer_tokens)}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Glimmerburst draw-2/create-Glimmer-token must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )
