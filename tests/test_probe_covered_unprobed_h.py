"""Genuine real-EoE cross-engine byte-equality probes — batch H.

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
resolve path on BOTH engines, and asserts either **full
``compare_fields(...) == []``** (byte-equality across the WHOLE
cross-engine field view — the strongest tier) or the **established
targeted-observable idiom** (with a precise documented reason, exactly
as the established Mechan Navigator / Uthros Scanship probes use).

> CAVEAT (mirrors ``docs/POOL_PARITY.md``): this is Effect+bridge-
> level byte-equality on a *controlled* cross-engine state, NOT
> full-game-trajectory parity. PROBED is the strongest evidence tier
> the campaign tracks; it is not a full random multi-turn game.

PARTITION DISCIPLINE (batch H — ETB TRIGGERS ONLY)
---------------------------------------------------
Sibling agents own: batch A (odd-ranked covered-but-unprobed), B
(even-ranked DIES/landfall), C, D, E (DIES/landfall/misc), F
(keyword-only creatures), G (sorcery shapes), I (DIES-trigger shapes).
This module owns **batch H**: ETB-triggered creature cards whose
primary parser output is a ``triggered_abilities`` entry with
``event = Event.ENTERS`` (or equivalent ETB event), covered-by-
construction, genuinely unprobed at live HEAD. ``BECOMES_TAPPED``
cards (batch A's Chrome Companion + Mechan Navigator) are excluded.
Cards with non-bridge-expressible predicates (``HasCounter``,
``StateBound``, ``OpponentControlsMoreLandsThanYou``) are dropped
following the batch-A/F drop-on-verify precedent.

The 4 cards pinned here (deck counts from ``data/17lands/
eoe_decks.json.gz`` at verify-first HEAD):

  | card                    | decks | shape                              |
  |-------------------------|------:|------------------------------------|
  | Friendly Ghost          |     0 | ETB PumpTargetCreatureUntilEOT+2/+4|
  | Overlord of the Floodpits |   0 | ETB Sequence(DrawCards2, Discard1) |
  | Overlord of the Mistmoors |   0 | ETB CreateToken(2× Insect 2/1 fly) |
  | Tunnel Surveyor         |     0 | ETB CreateToken(1× Glimmer 1/1)    |

DROPPED-ON-VERIFY (honest honest-stops):
  * **Syr Vondam, the Lucent** (~9,752) — ETB →
    ``PumpCreaturesYouControlUntilEOT(power_bonus=1,
    granted_keywords={'deathtouch'})``. Rust's
    ``Effect::PumpCreaturesYouControlUntilEOT { power_bonus,
    toughness_bonus }`` has NO ``granted_keywords`` field — a
    faithful synthetic mirror cannot convey the deathtouch grant
    without a new Rust substrate. Dropped (batch-B precedent:
    "the bare synthetic doesn't carry the genuine card's other
    rider/trigger").
  * **Starfield Shepherd** (~14,834) — ETB →
    ``ModalChooseOne`` over two ``SearchLibraryForCard`` modes.
    The ``search_library_for_card`` bridge arm's own docstring
    (``cross_engine.py``) explicitly defers the Starfield Shepherd
    real-EoE probe ("the printed-card variants carry additional
    triggers / may_fail asymmetric agent paths"). Dropped (batch-F
    precedent).
  * **Sunstar Expansionist** (~14,313) — two ETB triggers; the
    higher-leverage ``CreateToken`` leg is gated by
    ``And(IsSelf, StateBound(OpponentControlsMoreLandsThanYou))``
    — a ``StateBound`` predicate NOT in the bridge's predicate
    vocabulary. Dropped (batch-F precedent).
  * **Balemurk Leech** / **Entity Tracker** / **Cult Healer** /
    **Optimistic Scavenger** / **Scrabbling Skullcrab** /
    **Erratic Apparition** / **Dashing Bloodsucker** (all 0 decks)
    — ETB predicate is
    ``And(Subject(IsEnchantment()), ControlledByYou())``, which
    requires a ``subject_is_enchantment`` Rust bridge predicate arm
    that does NOT exist. Dropped.

3/4 probes assert **full ``compare_fields == []``** (Friendly Ghost /
Overlord of the Mistmoors / Tunnel Surveyor — the strongest tier).
Overlord of the Floodpits uses the **established targeted-observable
idiom**: the ETB ``Sequence(DrawCards(2), DiscardSelf(1))`` moves a
seeded-library object library→hand→graveyard; Rust resets
``summoning_sick`` on zone change while Python preserves the stale
flag — a gameplay-irrelevant graveyard-card representation artifact,
NOT a draw/discard engine divergence. Asserting the gameplay-relevant
observables (zone sizes + graveyard card name) pins the Effect
byte-equal with full strength on every gameplay-relevant axis (the
exact Mechan Navigator / Uthros Scanship idiom + documented reason).

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor the batch_a / batch_b / batch_c / batch_d / batch_e / batch_f /
batch_g / batch_i modules nor the 6 ``test_audit_safe_trigger_*``
tests — those are owned/protected; this module avoids all collision).
Registered in ``scripts/measure_pool_parity.PROBE_MODULES``.
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
# Batch-H probe #1 — Friendly Ghost (0 17lands decks).
#
# Covered: ``PumpTargetCreatureUntilEOT`` ∈ covered set + unprobed.
# Oracle: "[Creature — Spirit] {3}{W} 2/4
#   When this creature enters, target creature gets +2/+4 until end
#   of turn."
# Parser → ETB trigger: event=enters, predicate=IsSelf,
# effect=PumpTargetCreatureUntilEOT(power_bonus=2, toughness_bonus=4).
# Rust bridge arm: ``pump_target_creature_until_eot`` (established
# Dubious Delicacy / Rayblade Trooper / Sinister Cryologist idiom).
# Target is the first creature on p0's own bf (the pre-seated bait).
# Python uses ``_PickFirstControlledCreatureAgent`` on p0 to mirror
# Rust's source-controller bf-first scan. The bait is a 1/1 creature;
# after the +2/+4 buff it becomes 3/5 on BOTH engines.
# Assertion strength: full ``compare_fields``.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_friendly_ghost_etb_pump_target_creature_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Friendly Ghost
    (0 17lands decks). Batch-H covered→PROBED.**

    Python: the ACTUAL parsed Friendly Ghost printing cast as a spell,
    resolving onto p0's battlefield; its ETB
    (IsSelf → PumpTargetCreatureUntilEOT{+2/+4}) fires, targeting a
    pre-seated 1/1 bait creature on p0's bf. Rust: the bridged
    synthetic carrier with the exact ``pump_target_creature_until_eot``
    trigger dict; target is the first creature on p0's bf.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (bait at effective 3/5 on BOTH; Friendly
    Ghost on p0's bf; no life changes).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone, effective_power, effective_toughness
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstControlledCreatureAgent

    real = get_active_source().get_printings().get("Friendly Ghost")
    if real is None:
        pytest.skip("Friendly Ghost absent from active CardSource")
    assert "Creature" in real.card_types
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, "Friendly Ghost must have an ENTERS trigger"
    assert isinstance(etb.effect, PumpTargetCreatureUntilEOT), (
        f"genuine Friendly Ghost ETB must be PumpTargetCreatureUntilEOT;"
        f" got {type(etb.effect).__name__}"
    )
    assert etb.effect.power_bonus == 2
    assert etb.effect.toughness_bonus == 4

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0

    # ---- Pre-seat bait 1/1 creature on p0's bf (pump target). ----
    # Rust: inject to bf so it is Vec[0] — Rust picks the first
    # creature on p0's bf. Python: same insertion order ensures the
    # _PickFirstControlledCreatureAgent shim picks this creature.
    rs_bait_id = rs.register_and_inject_object(
        {"name": "FG Bait", "card_types": ["Creature"],
         "power": 1, "toughness": 1}, 0, ZB,
    )
    py_bait = py.new_object(
        CardPrinting(
            name="FG Bait", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=1, toughness=1, produces=frozenset(),
        ),
        owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bait.summoning_sick = False
    py_bait.tapped = False
    py.battlefield.append(py_bait)
    py.players[0].agent = _PickFirstControlledCreatureAgent()

    # ---- Python: genuine parsed Friendly Ghost on the stack → bf.
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Friendly Ghost"
               for o in py.battlefield), (
        "Friendly Ghost should resolve onto p0's battlefield"
    )
    assert len(py.stack) == 1, (
        "Friendly Ghost ETB trigger should be on the Python stack"
    )

    # ---- Rust: bridged synthetic carrier with the same ETB shape. ----
    rs_id = rs.register_and_inject_object(
        {
            "name": "Friendly Ghost",
            "card_types": ["Creature"],
            "power": int(real.power) if real.power is not None else 2,
            "toughness": int(real.toughness) if real.toughness is not None else 4,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "pump_target_creature_until_eot",
                        "power_bonus": 2,
                        "toughness_bonus": 4,
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
        "Friendly Ghost ETB trigger should be on the Rust stack"
    )

    # ---- Drain both stacks (PumpTargetCreatureUntilEOT resolves). ----
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # Observable: bait creature gets +2/+4 on BOTH engines.
    py_pow = effective_power(py, py_bait)
    py_tou = effective_toughness(py, py_bait)
    rs_pow = rs.effective_power(rs_bait_id)
    rs_tou = rs.effective_toughness(rs_bait_id)
    assert py_pow == 3 and rs_pow == 3, (
        f"bait must be 3 power after +2 on BOTH; py={py_pow} rs={rs_pow}"
    )
    assert py_tou == 5 and rs_tou == 5, (
        f"bait must be 5 toughness after +4 on BOTH; py={py_tou} rs={rs_tou}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Friendly Ghost ETB pump-target must be byte-equal across "
        f"the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-H probe #2 — Overlord of the Floodpits (0 17lands decks).
#
# Covered: ``Sequence`` / ``DrawCards`` / ``DiscardSelf`` ∈ covered
# set + unprobed. Oracle: "[Enchantment Creature — Leviathan] 5/3
#   When this creature enters, draw two cards, then discard a card.
#   Whenever this creature attacks, draw two cards, then discard a
#   card."
# This probe drives the ETB leg only (event=enters, predicate=IsSelf,
# effect=Sequence(DrawCards(2), DiscardSelf(1))). The ATTACKS leg is
# not fired (no combat).
# Two identical filler cards seed p0's library; DrawCards(2) draws
# both; DiscardSelf(1) discards one via _DiscardFirstAgent → net is
# one filler in p0's graveyard, one in hand, library empty.
# Assertion strength: **established targeted-observable idiom** (the
# EXACT idiom + documented reason the Mechan Navigator / Uthros
# Scanship discard_self probes use): the draw→discard path moves a
# seeded-library object library→hand→graveyard; Rust resets
# ``summoning_sick`` on zone change while Python preserves the stale
# flag — a gameplay-irrelevant graveyard-card representation artifact,
# NOT a draw/discard engine divergence.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_overlord_of_the_floodpits_etb_draw_discard_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Overlord of the
    Floodpits (0 17lands decks). Batch-H covered→PROBED.**

    Python: the ACTUAL parsed Overlord of the Floodpits printing cast
    as a spell; its ETB (IsSelf → Sequence(DrawCards(2), DiscardSelf(1)))
    fires. Rust: the bridged synthetic carrier.

    Two identical filler cards in p0's library → draw 2 → hand has 2
    → discard 1 (``_DiscardFirstAgent`` / Rust pops hand[0]) → net:
    1 filler in p0's graveyard, 1 in hand, library empty.

    Assertion strength: **established targeted-observable idiom** (same
    as Mechan Navigator / Uthros Scanship). REASON: the draw→discard
    path moves a seeded-library object library→hand→graveyard; Rust
    resets ``summoning_sick`` to False on zone change while Python
    preserves the seeded object's stale ``summoning_sick=True`` — a
    gameplay-irrelevant graveyard-card flag on a card in the graveyard,
    NOT a draw/discard engine divergence. The probe pins all
    gameplay-relevant observables (zone sizes + graveyard card name)
    byte-equal cross-engine.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state, CardDef,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from tests.parity._picker_shims import _DiscardFirstAgent

    real = get_active_source().get_printings().get(
        "Overlord of the Floodpits"
    )
    if real is None:
        pytest.skip("Overlord of the Floodpits absent from active CardSource")
    assert "Creature" in real.card_types
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Overlord of the Floodpits must have an ENTERS trigger"
    )
    assert isinstance(etb.effect, Sequence), (
        f"genuine Overlord of the Floodpits ETB must be a Sequence;"
        f" got {type(etb.effect).__name__}"
    )
    assert isinstance(etb.effect.effects[0], DrawCards)
    assert etb.effect.effects[0].amount == 2

    # Two identical filler cards in p0's library so both draws are
    # forced and both engines draw the same names. After drawing 2
    # and discarding 1, the graveyard has 1 card of known name.
    filler = CardDef(
        name="OFC Filler", card_type="Land", mana_produced=("U",)
    )
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=("OFC Filler", "OFC Filler"),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0

    py_p0_lib0 = len(py.players[0].library)
    py_p0_gy0 = len(py.players[0].graveyard)
    rs_p0_lib0 = rs.library_sizes[0]
    rs_p0_gy0 = rs.graveyard_sizes[0]

    # Python: discarding player is p0 (the source's controller);
    # seat _DiscardFirstAgent so hand[0] is discarded (matches Rust's
    # pop-head discard behavior when both engines see the same order).
    py.players[0].agent = _DiscardFirstAgent()

    # ---- Python: genuine parsed Overlord of the Floodpits on stack. --
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Overlord of the Floodpits"
               for o in py.battlefield), (
        "Overlord of the Floodpits should resolve onto p0's battlefield"
    )
    assert len(py.stack) == 1, (
        "ETB trigger should be on the Python stack after resolve"
    )

    # ---- Rust: bridged synthetic carrier. ----
    rs_id = rs.register_and_inject_object(
        {
            "name": "Overlord of the Floodpits",
            "card_types": ["Enchantment", "Creature"],
            "power": int(real.power) if real.power is not None else 5,
            "toughness": int(real.toughness) if real.toughness is not None else 3,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "sequence", "effects": [
                        {"kind": "draw_cards", "count": 2},
                        {"kind": "discard_self", "amount": 1},
                    ]},
                }
            ],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 1, (
        "ETB trigger should be on the Rust stack after resolve"
    )

    # ---- Drain both stacks (Sequence resolves: draw 2, discard 1). --
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # **Established targeted-observable idiom (documented reason).**
    # REASON: the draw→discard path moves a seeded-library object
    # library→hand→graveyard; Rust resets ``summoning_sick`` on zone
    # change while Python preserves the stale flag — a gameplay-
    # irrelevant graveyard-card representation artifact on a graveyard
    # card (sickness has no meaning there), NOT a draw/discard engine
    # divergence. Pin all gameplay-relevant observables byte-equal
    # (the EXACT Mechan Navigator / Uthros Scanship idiom + reason).
    rs_p0_gy_names = sorted(
        e["printing_name"] for e in rs.graveyard_snapshot(0)
    )
    py_p0_gy_names = sorted(
        o.printing.name for o in py.players[0].graveyard
    )
    # Net: DrawCards(2) library→hand, DiscardSelf(1) hand→graveyard →
    # 1 filler in graveyard, 1 in hand, library empty on BOTH engines.
    assert rs_p0_gy_names == ["OFC Filler"] == py_p0_gy_names, (
        f"the drawn-then-discarded card must be in p0's graveyard on "
        f"BOTH; rust={rs_p0_gy_names} py={py_p0_gy_names}"
    )
    assert rs.library_sizes[0] == 0, "Rust p0 lib empty after draw 2"
    assert len(py.players[0].library) == 0, "Py p0 lib empty after draw 2"
    assert rs.hand_sizes[0] == 1, "Rust p0 hand has 1 after draw 2 discard 1"
    assert len(py.players[0].hand) == 1, "Py p0 hand has 1 after draw 2 discard 1"
    assert rs.graveyard_sizes[0] == rs_p0_gy0 + 1
    assert len(py.players[0].graveyard) == py_p0_gy0 + 1
    # Cross-engine zone sizes byte-equal.
    assert rs.library_sizes[0] == len(py.players[0].library)
    assert rs.hand_sizes[0] == len(py.players[0].hand)
    assert rs.graveyard_sizes[0] == len(py.players[0].graveyard)
    assert rs.library_sizes[1] == len(py.players[1].library)
    assert rs.hand_sizes[1] == len(py.players[1].hand)
    assert rs.graveyard_sizes[1] == len(py.players[1].graveyard)


# ---------------------------------------------------------------------
# Batch-H probe #3 — Overlord of the Mistmoors (0 17lands decks).
#
# Covered: ``CreateToken`` ∈ covered set + unprobed. Oracle:
# "[Enchantment Creature — Leviathan] 6/6
#   Whenever this creature enters or attacks, create two 2/1 white
#   Insect creature tokens with flying."
# This probe drives the ETB leg only (event=enters, predicate=IsSelf,
# effect=CreateToken(token=Insect 2/1 flying, count=2)).
# Insect token pid registered on Rust; Python uses intrinsic
# TOKEN_PRINTINGS["Insect"] (the established Gravpack-Monoist /
# Beamsaw-Prospector token-pid idiom).
# Assertion strength: full ``compare_fields``.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_overlord_of_the_mistmoors_etb_create_insect_tokens_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Overlord of the
    Mistmoors (0 17lands decks). Batch-H covered→PROBED.**

    Python: the ACTUAL parsed Overlord of the Mistmoors printing cast
    as a spell; its ETB (IsSelf → CreateToken(Insect 2/1 flying,
    count=2)) fires. Rust: the bridged synthetic carrier with the
    ``create_token`` trigger dict.

    Two Insect tokens spawn on p0's bf on BOTH engines; the ATTACKS
    leg is not fired (no combat in this probe).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (2 Insect tokens on p0's bf on BOTH;
    life totals unchanged).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.tokens import CreateToken

    real = get_active_source().get_printings().get(
        "Overlord of the Mistmoors"
    )
    if real is None:
        pytest.skip("Overlord of the Mistmoors absent from active CardSource")
    assert "Creature" in real.card_types
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, (
        "Overlord of the Mistmoors must have an ENTERS trigger"
    )
    assert isinstance(etb.effect, CreateToken), (
        f"genuine Overlord of the Mistmoors ETB must be CreateToken;"
        f" got {type(etb.effect).__name__}"
    )
    assert etb.effect.token_printing.name == "Insect"
    assert etb.effect.count == 2
    assert etb.effect.tapped is False
    assert etb.effect.each_player is False

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0

    # Register Insect token pid on Rust (established token-pid idiom).
    # Python uses the intrinsic TOKEN_PRINTINGS["Insect"] so the
    # spawned token name matches on both sides in the field view.
    insect_pid = rs.registry_size
    rs.register_and_inject_object(
        {"name": "Insect", "card_types": ["Creature"],
         "supertypes": ["Token"], "power": 2, "toughness": 1,
         "mana_cost": {"generic": 0}},
        0, 1,  # owner=0, ZONE_LIBRARY (inert seed for pid assignment)
    )
    py_seed = py.new_object(
        TOKEN_PRINTINGS["Insect"], owner_id=0, zone=Zone.LIBRARY
    )
    py_seed.summoning_sick = False
    py.players[0].library.append(py_seed)

    # ---- Python: genuine parsed Overlord of the Mistmoors on stack. --
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Overlord of the Mistmoors"
               for o in py.battlefield), (
        "Overlord of the Mistmoors should resolve onto p0's battlefield"
    )
    assert len(py.stack) == 1, (
        "ETB trigger should be on the Python stack after resolve"
    )

    # ---- Rust: bridged synthetic carrier with the same ETB shape. ----
    rs_id = rs.register_and_inject_object(
        {
            "name": "Overlord of the Mistmoors",
            "card_types": ["Enchantment", "Creature"],
            "power": int(real.power) if real.power is not None else 6,
            "toughness": int(real.toughness) if real.toughness is not None else 6,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "create_token",
                        "count": 2,
                        "token_printing_id": insect_pid,
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

    # ---- Drain both stacks (CreateToken resolves: 2 Insects spawn). --
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # Concrete observable: exactly 2 Insect tokens on p0's bf on BOTH.
    rs_insect_n = sum(
        1 for e in rs.battlefield_snapshot()
        if e["printing_name"] == "Insect"
    )
    py_insect_n = sum(
        1 for o in py.battlefield if o.printing.name == "Insect"
    )
    assert rs_insect_n == 2 == py_insect_n, (
        f"Overlord of the Mistmoors ETB → exactly 2 Insects on BOTH; "
        f"rust={rs_insect_n} py={py_insect_n}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Overlord of the Mistmoors ETB create-insect-tokens must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-H probe #4 — Tunnel Surveyor (0 17lands decks).
#
# Covered: ``CreateToken`` ∈ covered set + unprobed. Oracle:
# "[Creature — Human Scout] {2}{U} 2/2
#   When this creature enters, create a 1/1 white Glimmer enchantment
#   creature token."
# Parser → ETB trigger: event=enters, predicate=IsSelf,
# effect=CreateToken(token=Glimmer 1/1 Enchantment+Creature, count=1).
# Glimmer token pid registered on Rust; Python uses intrinsic
# TOKEN_PRINTINGS["Glimmer"]. The Glimmer is the first
# Enchantment+Creature dual-type token in the probe suite — its
# card_types carry BOTH "Enchantment" AND "Creature", distinct from
# the Robot (Artifact+Creature) and Insect (Creature-only) shapes.
# Assertion strength: full ``compare_fields``.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_tunnel_surveyor_etb_create_glimmer_token_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Tunnel Surveyor
    (0 17lands decks). Batch-H covered→PROBED.**

    Python: the ACTUAL parsed Tunnel Surveyor printing cast as a spell;
    its ETB (IsSelf → CreateToken(Glimmer 1/1 Enchantment+Creature,
    count=1)) fires. Rust: the bridged synthetic carrier.

    The Glimmer token is the first Enchantment+Creature dual-type token
    probed end-to-end — distinct from Robot (Artifact+Creature) and
    Insect (Creature-only). Pins that the ``create_token`` bridge arm
    is invariant w.r.t. Enchantment dual-type tokens.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (1 Glimmer token on p0's bf on BOTH; life
    totals unchanged).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.tokens import CreateToken

    real = get_active_source().get_printings().get("Tunnel Surveyor")
    if real is None:
        pytest.skip("Tunnel Surveyor absent from active CardSource")
    assert "Creature" in real.card_types
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, "Tunnel Surveyor must have an ENTERS trigger"
    assert isinstance(etb.effect, CreateToken), (
        f"genuine Tunnel Surveyor ETB must be CreateToken;"
        f" got {type(etb.effect).__name__}"
    )
    assert etb.effect.token_printing.name == "Glimmer"
    assert etb.effect.count == 1
    assert etb.effect.tapped is False
    assert etb.effect.each_player is False

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0

    # Register Glimmer token pid on Rust (established token-pid idiom).
    glimmer_pid = rs.registry_size
    rs.register_and_inject_object(
        {"name": "Glimmer", "card_types": ["Enchantment", "Creature"],
         "supertypes": ["Token"], "power": 1, "toughness": 1,
         "mana_cost": {"generic": 0}},
        0, 1,  # owner=0, ZONE_LIBRARY (inert seed for pid assignment)
    )
    py_seed = py.new_object(
        TOKEN_PRINTINGS["Glimmer"], owner_id=0, zone=Zone.LIBRARY
    )
    py_seed.summoning_sick = False
    py.players[0].library.append(py_seed)

    # ---- Python: genuine parsed Tunnel Surveyor on the stack → bf. --
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    assert any(o.printing.name == "Tunnel Surveyor"
               for o in py.battlefield), (
        "Tunnel Surveyor should resolve onto p0's battlefield"
    )
    assert len(py.stack) == 1, (
        "ETB trigger should be on the Python stack after resolve"
    )

    # ---- Rust: bridged synthetic carrier. ----
    rs_id = rs.register_and_inject_object(
        {
            "name": "Tunnel Surveyor",
            "card_types": ["Creature"],
            "power": int(real.power) if real.power is not None else 2,
            "toughness": int(real.toughness) if real.toughness is not None else 2,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "create_token",
                        "count": 1,
                        "token_printing_id": glimmer_pid,
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

    # ---- Drain both stacks (CreateToken resolves: 1 Glimmer spawns). -
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # Concrete observable: exactly 1 Glimmer token on p0's bf on BOTH.
    rs_glimmer_n = sum(
        1 for e in rs.battlefield_snapshot()
        if e["printing_name"] == "Glimmer"
    )
    py_glimmer_n = sum(
        1 for o in py.battlefield if o.printing.name == "Glimmer"
    )
    assert rs_glimmer_n == 1 == py_glimmer_n, (
        f"Tunnel Surveyor ETB → exactly 1 Glimmer on BOTH; "
        f"rust={rs_glimmer_n} py={py_glimmer_n}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Tunnel Surveyor ETB create-glimmer-token must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )
