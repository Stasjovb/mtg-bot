"""Genuine real-EoE cross-engine byte-equality probes — batch K.

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

PARTITION DISCIPLINE (batch K — ETB TRIGGERS ONLY, extending batch H)
----------------------------------------------------------------------
Sibling agents own: batch A (odd-ranked covered-but-unprobed), B
(even-ranked DIES/landfall), C, D, E (DIES/landfall/misc), F
(keyword-only creatures), G (sorcery shapes), H (ETB triggers:
Friendly Ghost / Overlord of the Floodpits / Overlord of the
Mistmoors / Tunnel Surveyor), I (DIES-trigger shapes), J (sorcery),
L (BECOMES_TAPPED + landfall).
This module owns **batch K**: ETB-triggered creature cards whose
primary parser output is a ``triggered_abilities`` entry with
``event = Event.ENTERS`` (or equivalent ETB event), covered-by-
construction, genuinely unprobed at live HEAD, DIFFERENT from batch H.
``BECOMES_TAPPED`` cards (batch A / batch L) are excluded. Cards with
non-bridge-expressible predicates (``HasCounter``, ``StateBound``,
``OpponentControlsMoreLandsThanYou``) are dropped following the
batch-A/F/H drop-on-verify precedent. Cards whose primary ETB uses
``subject_is_enchantment`` predicate (not in Rust bridge vocab) are
dropped following batch H.

The 3 cards pinned here (0 17lands deck count each — all
covered-but-unprobed at HEAD):

  | card                         | decks | shape                            |
  |------------------------------|------:|----------------------------------|
  | Overlord of the Boilerbilges |     0 | ETB IsSelf → DealDamageAnyTarget(4) |
  | Shroudstomper                |     0 | ETB IsSelf → Sequence(Sequence(EachOpponentLosesLife2, GainLife2), DrawCards1) |
  | Spineseeker Centipede        |     0 | ETB IsSelf → SearchLibraryForCard(basic_land, may_fail=True) empty-lib no-op |

DROPPED-ON-VERIFY (honest honest-stops):
  * **Balemurk Leech / Cult Healer / Dashing Bloodsucker / Entity
    Tracker / Erratic Apparition / Gremlin Tamer / Infernal Phantom /
    Optimistic Scavenger / Scrabbling Skullcrab / Skullsnap Nuisance**
    — ETB predicate is ``And(Subject(IsEnchantment()),
    ControlledByYou())``, which requires a ``subject_is_enchantment``
    Rust bridge predicate arm that does NOT exist. Dropped (same block
    documented in batch H).
  * **Syr Vondam, the Lucent** — ETB →
    ``PumpCreaturesYouControlUntilEOT(granted_keywords={'deathtouch'})``.
    Rust's variant has NO ``granted_keywords`` field. Dropped
    (same block documented in batch H).
  * **Sunstar Expansionist** — ETB gated by
    ``StateBound(OpponentControlsMoreLandsThanYou)`` — not in bridge
    vocabulary. Dropped (same block documented in batch H).
  * **Starfield Shepherd** — ETB → ``ModalChooseOne`` over two
    ``SearchLibraryForCard`` modes; deferred per batch H's documented
    rationale (``may_fail`` asymmetric agent paths). Dropped.
  * **Unsettling Twins** — ETB → ``ManifestDread(1)``; cross-engine
    probe explicitly deferred in the ``manifest_dread`` bridge arm
    docstring (``choose_card_from_library`` agent hook + face-down ETB
    fan-out complexity). Dropped.
  * **Vicious Clown / Irreverent Gremlin** — ETB predicate includes
    ``HasPowerAtMost(n=2)`` — not in the Rust bridge predicate
    vocabulary. Dropped.

All 3 probes assert **full ``compare_fields == []``** (the strongest
tier).

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the batch_a through batch_j / batch_l modules nor the 6
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
# Batch-K probe #1 — Overlord of the Boilerbilges (0 17lands decks).
#
# Covered: ``DealDamageAnyTarget`` ∈ covered set + unprobed. Oracle:
# "[Enchantment Creature — Leviathan] {5}{B}{R} 5/5
#   When this creature enters or attacks, it deals 4 damage to any
#   target."
# This probe drives the ETB leg only (event=enters, predicate=IsSelf,
# effect=DealDamageAnyTarget(amount=4)). The ATTACKS leg is not fired
# (no combat in this probe).
#
# With no creatures on either bf, Rust's deterministic pick is the
# defender-player (p1). Python's ``_PickFirstOpponentTargetAgent``
# scans legal_targets for opponent-side targets and returns the p1
# player entry — a faithful mirror of Rust's "scan defender bf for
# first creature, else defender-player" fallback on an empty board.
#
# The ATTACKS leg is a structural duplicate of the ETB shape and is
# out of scope for this probe (no combat; left for a future probe if
# the ATTACKS event acquires a dedicated bridge path).
#
# Assertion strength: full ``compare_fields``.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_overlord_of_the_boilerbilges_etb_deal_damage_any_target_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Overlord of the
    Boilerbilges (0 17lands decks). Batch-K covered→PROBED.**

    Python: the ACTUAL parsed Overlord of the Boilerbilges printing
    cast as a spell; its ETB (IsSelf → DealDamageAnyTarget{4}) fires.
    The ``_PickFirstOpponentTargetAgent`` on p0 mirrors Rust's
    deterministic defender-player fallback (no creatures on board →
    the opponent-player is the only legal target). Rust: the bridged
    synthetic carrier with the ``deal_damage_any_target`` trigger dict.

    With an empty battlefield (no creatures) on BOTH engines, the 4
    damage goes to p1 (the defender-player) on BOTH engines → p1 life
    16, p0 life 20 cross-engine byte-equal.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (p1 life −4 on BOTH; p0 life unchanged;
    Overlord on p0's bf). The ATTACKS leg is not fired.
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
    from mtg_bot.effects.generic.damage import DealDamageAnyTarget
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get(
        "Overlord of the Boilerbilges"
    )
    if real is None:
        pytest.skip(
            "Overlord of the Boilerbilges absent from active CardSource"
        )
    assert "Creature" in real.card_types
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Overlord of the Boilerbilges must have an ENTERS trigger"
    )
    assert isinstance(etb.effect, DealDamageAnyTarget), (
        f"genuine Overlord of the Boilerbilges ETB must be "
        f"DealDamageAnyTarget; got {type(etb.effect).__name__}"
    )
    assert etb.effect.amount == 4

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0
    ZB = 2

    # Python: seat the targeting agent on p0 — with no opponent
    # creatures on board, the agent returns the p1-player target,
    # exactly mirroring Rust's defender-bf-scan-then-fallback-to-
    # defender-player logic.
    py.players[0].agent = _PickFirstOpponentTargetAgent()
    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    # ---- Python: genuine parsed Overlord of the Boilerbilges on stack.
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Overlord of the Boilerbilges"
               for o in py.battlefield), (
        "Overlord of the Boilerbilges should resolve onto p0's battlefield"
    )
    assert len(py.stack) == 1, (
        "ETB trigger should be on the Python stack after resolve"
    )

    # ---- Drain Python stack (DealDamageAnyTarget resolves → p1 −4). --
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py.players[1].life == py_p1_life0 - 4, (
        "Python: p1 must lose 4 life (DealDamageAnyTarget → player target)"
    )
    assert py.players[0].life == py_p0_life0, (
        "Python: p0 life unchanged (Overlord only deals to any-target)"
    )

    # ---- Rust: bridged synthetic carrier with the same ETB shape. ----
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)
    rs_id = rs.register_and_inject_object(
        {
            "name": "Overlord of the Boilerbilges",
            "card_types": ["Enchantment", "Creature"],
            "power": int(real.power) if real.power is not None else 5,
            "toughness": int(real.toughness) if real.toughness is not None else 5,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "deal_damage_any_target",
                        "amount": 4,
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

    # ---- Drain Rust stack (DealDamageAnyTarget → defender-player p1). -
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.get_life(1) == rs_p1_life0 - 4, (
        "Rust: p1 must lose 4 life (DealDamageAnyTarget → defender-player)"
    )
    assert rs.get_life(0) == rs_p0_life0, (
        "Rust: p0 life unchanged"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Overlord of the Boilerbilges ETB deal-damage-any-target must "
        f"be byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-K probe #2 — Shroudstomper (0 17lands decks).
#
# Covered: ``Sequence`` / ``EachOpponentLosesLife`` / ``GainLife`` /
# ``DrawCards`` ∈ covered set + unprobed. Oracle:
# "[Creature — Beast] {5}{G}{G} 5/5
#   When this creature enters or attacks, each opponent loses 2 life
#   and you gain 2 life, then draw a card."
# This probe drives the ETB leg only (event=enters, predicate=IsSelf,
# effect=Sequence(Sequence(EachOpponentLosesLife(2), GainLife(2)),
# DrawCards(1))). The ATTACKS leg is a structural duplicate and is not
# fired (no combat in this probe).
#
# The ETB effect is a nested Sequence: the outer Sequence has two
# children — (1) an inner Sequence(EachOpponentLosesLife2, GainLife2)
# and (2) DrawCards(1). The Rust bridge ``sequence`` arm handles
# nested composers recursively (each child dict is translated via the
# same ``_ta_dict_to_python_effect`` recursive call), so the nested
# representation round-trips faithfully. One filler card in p0's
# library makes the DrawCards(1) draw observable and forced → the
# drawn card appears in p0's hand on BOTH engines.
#
# Assertion strength: full ``compare_fields``.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_shroudstomper_etb_life_drain_draw_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Shroudstomper
    (0 17lands decks). Batch-K covered→PROBED.**

    Python: the ACTUAL parsed Shroudstomper printing cast as a spell;
    its ETB (IsSelf → Sequence(Sequence(EachOpponentLosesLife(2),
    GainLife(2)), DrawCards(1))) fires. Rust: the bridged synthetic
    carrier with the nested-``sequence`` trigger dict.

    One filler card in p0's library → DrawCards(1) draws it → p0
    hand has 1 card after the trigger resolves on BOTH engines.
    p1 loses 2 life, p0 gains 2 life, p0 draws 1 — cross-engine
    byte-equal.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (p1 life −2, p0 life +2, p0 hand +1,
    p0 library empty on BOTH). The ATTACKS leg is not fired.
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
    from mtg_bot.effects.generic.draw_mill import DrawCards

    real = get_active_source().get_printings().get("Shroudstomper")
    if real is None:
        pytest.skip("Shroudstomper absent from active CardSource")
    assert "Creature" in real.card_types
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, "Shroudstomper must have an ENTERS trigger"
    assert isinstance(etb.effect, Sequence), (
        f"genuine Shroudstomper ETB must be a Sequence;"
        f" got {type(etb.effect).__name__}"
    )
    assert len(etb.effect.effects) == 2
    assert isinstance(etb.effect.effects[0], Sequence), (
        "outer Sequence[0] must itself be an inner Sequence "
        "(EachOpponentLosesLife + GainLife)"
    )
    assert isinstance(etb.effect.effects[1], DrawCards), (
        "outer Sequence[1] must be DrawCards"
    )
    assert etb.effect.effects[1].amount == 1

    # One filler card in p0's library so DrawCards(1) is observable +
    # forced — both engines draw the same named card.
    filler = CardDef(
        name="SS Filler", card_type="Land", mana_produced=("U",)
    )
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=("SS Filler",),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0
    ZB = 2

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    # ---- Python: genuine parsed Shroudstomper on the stack → bf. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Shroudstomper"
               for o in py.battlefield), (
        "Shroudstomper should resolve onto p0's battlefield"
    )
    assert len(py.stack) == 1, (
        "ETB trigger should be on the Python stack after resolve"
    )

    # ---- Drain Python stack (nested Sequence resolves). ----
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py.players[1].life == py_p1_life0 - 2, (
        "Python: p1 loses 2 life (EachOpponentLosesLife)"
    )
    assert py.players[0].life == py_p0_life0 + 2, (
        "Python: p0 gains 2 life (GainLife)"
    )
    assert len(py.players[0].hand) == 1, (
        "Python: p0 draws 1 from the filler library"
    )
    assert len(py.players[0].library) == 0, (
        "Python: p0 library empty after drawing the filler"
    )

    # ---- Rust: bridged synthetic carrier with the nested Sequence. ---
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)
    rs_id = rs.register_and_inject_object(
        {
            "name": "Shroudstomper",
            "card_types": ["Creature"],
            "power": int(real.power) if real.power is not None else 5,
            "toughness": int(real.toughness) if real.toughness is not None else 5,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "sequence", "effects": [
                        {"kind": "sequence", "effects": [
                            {"kind": "each_opponent_loses_life",
                             "amount": 2},
                            {"kind": "gain_life", "amount": 2},
                        ]},
                        {"kind": "draw_cards", "count": 1},
                    ]},
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

    # ---- Drain Rust stack (nested Sequence resolves). ----
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.get_life(1) == rs_p1_life0 - 2, (
        "Rust: p1 loses 2 life (EachOpponentLosesLife)"
    )
    assert rs.get_life(0) == rs_p0_life0 + 2, (
        "Rust: p0 gains 2 life (GainLife)"
    )
    assert rs.hand_sizes[0] == 1, (
        "Rust: p0 draws 1 from the filler library"
    )
    assert rs.library_sizes[0] == 0, (
        "Rust: p0 library empty after drawing the filler"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Shroudstomper ETB nested-sequence (drain+draw) must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-K probe #3 — Spineseeker Centipede (0 17lands decks).
#
# Covered: ``SearchLibraryForCard`` ∈ covered set + unprobed. Oracle:
# "[Creature — Insect] {G} 2/1
#   When this creature enters, search your library for a basic land
#   card, reveal it, put it into your hand, then shuffle."
# Parser → ETB trigger: event=enters, predicate=IsSelf,
# effect=SearchLibraryForCard(filter_name='basic_land', may_fail=True).
#
# With an EMPTY library (no basic lands), BOTH engines take the
# no-match branch: Python logs "no basic_land found" and shuffles
# (no-op); Rust resolves SearchLibraryForCard with 0 matches and
# shuffles (no-op). The result is observationally identical on BOTH:
# p0 hand stays empty, p0 library stays empty, no life changes. This
# pins the ``search_library_for_card`` bridge arm on the ETB path
# byte-equal end-to-end without an agent shim (the empty-library no-
# match branch never calls ``choose_card_from_library``).
#
# Assertion strength: full ``compare_fields``.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_spineseeker_centipede_etb_search_basic_land_empty_lib_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Spineseeker Centipede
    (0 17lands decks). Batch-K covered→PROBED.**

    Python: the ACTUAL parsed Spineseeker Centipede printing cast as a
    spell; its ETB (IsSelf → SearchLibraryForCard(basic_land,
    may_fail=True)) fires against an empty library. Rust: the bridged
    synthetic carrier with the ``search_library_for_card`` trigger dict.

    Empty library → no basic lands → both engines take the no-match
    branch: Python shuffles (no-op), Rust shuffles (no-op). No card
    moves to p0's hand on EITHER engine → p0 hand stays empty, p0
    library stays empty. No agent ``choose_card_from_library`` call
    is made (the empty-options branch short-circuits before the hook).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (Spineseeker Centipede on p0's bf; all
    zone sizes unchanged; life totals unchanged on BOTH).
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
    from mtg_bot.effects.generic.search import SearchLibraryForCard

    real = get_active_source().get_printings().get("Spineseeker Centipede")
    if real is None:
        pytest.skip("Spineseeker Centipede absent from active CardSource")
    assert "Creature" in real.card_types
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Spineseeker Centipede must have an ENTERS trigger"
    )
    assert isinstance(etb.effect, SearchLibraryForCard), (
        f"genuine Spineseeker Centipede ETB must be SearchLibraryForCard;"
        f" got {type(etb.effect).__name__}"
    )
    assert etb.effect.filter_name == "basic_land"
    assert etb.effect.may_fail is True

    # Empty library on both sides: no basic lands → no-match branch →
    # no agent call, pure shuffle (no-op). Deterministic cross-engine.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0
    ZB = 2

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    # ---- Python: genuine parsed Spineseeker Centipede on stack → bf. -
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Spineseeker Centipede"
               for o in py.battlefield), (
        "Spineseeker Centipede should resolve onto p0's battlefield"
    )
    assert len(py.stack) == 1, (
        "ETB trigger should be on the Python stack after resolve"
    )

    # ---- Drain Python stack (SearchLibraryForCard → empty-lib no-op). -
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert len(py.players[0].hand) == 0, (
        "Python: no card fetched (empty library → no-op shuffle)"
    )
    assert len(py.players[0].library) == 0, (
        "Python: library stays empty after no-match shuffle"
    )
    assert py.players[0].life == py_p0_life0, "Python: p0 life unchanged"
    assert py.players[1].life == py_p1_life0, "Python: p1 life unchanged"

    # ---- Rust: bridged synthetic carrier. ----
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)
    rs_id = rs.register_and_inject_object(
        {
            "name": "Spineseeker Centipede",
            "card_types": ["Creature"],
            "power": int(real.power) if real.power is not None else 2,
            "toughness": int(real.toughness) if real.toughness is not None else 1,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "search_library_for_card",
                        "filter_name": "basic_land",
                        "may_fail": True,
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

    # ---- Drain Rust stack (SearchLibraryForCard → empty-lib no-op). --
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.hand_sizes[0] == 0, (
        "Rust: no card fetched (empty library → no-op shuffle)"
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
        f"Spineseeker Centipede ETB search-basic-land (empty-lib no-op) "
        f"must be byte-equal across the WHOLE field view on BOTH; "
        f"diffs={diffs}"
    )
