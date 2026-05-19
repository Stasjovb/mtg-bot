"""Genuine real-EoE cross-engine byte-equality probes — batch Z,
ATTACKS trigger event, round 2.

CONTINUOUS-PIPELINE phase: grow the PROBED tier by pinning the ATTACKS
legs of real EoE cards whose ETB legs are already individually probed
but whose ATTACKS trigger dispatch path has not been exercised by any
existing probe.

WHY ATTACKS LEGS NEED SEPARATE PINS
-------------------------------------
Batch X (``test_probe_attacks_leaves_battlefield_x.py``) probed the
ATTACKS legs of three covered-by-construction cards: Overlord of the
Mistmoors, Shroudstomper, and Specimen Freighter.

Several additional EoE cards emit both an ENTERS and an ATTACKS trigger
from the SAME parsed ``TriggeredAbility`` shape.  The ETB legs were
pinned in earlier batches (H, K), but the ATTACKS dispatch path is a
separate code site on BOTH engines:

  * Python: ``combat.py:_fire_attacks_triggers`` → ``dispatch_event(
    Event.ATTACKS, ...)`` → ``push_triggered_ability``
  * Rust: ``state_ops_combat.rs`` ``declare_attacker`` → attacker-walk
    → ``push_triggered_ability``

Probing the ATTACKS leg exercises these dispatch sites end-to-end with
a REAL EoE printing, independently of the ETB leg.  The measure script
(``scripts/measure_pool_parity.py``) counts parity at the card level,
so these cards are already in the PROBED tier; the new probes here
provide DISPATCH-PATH coverage that is genuinely absent.

POOL RECON — ATTACKS trigger lane
-----------------------------------
After batch X the pool of covered-but-unprobed cards with ATTACKS
triggers in the ``covered_by_construction`` tier is nearly exhausted:

  * ``Syr Vondam, the Lucent`` (covered_by_construction) — ATTACKS →
    ``PumpCreaturesYouControlUntilEOT(power_bonus=1, toughness_bonus=0,
    granted_keywords=frozenset({'deathtouch'}), exclude_source=True)``.
    DROPPED: Rust's ``PumpCreaturesYouControlUntilEOT`` bridge arm only
    carries ``power_bonus`` and ``toughness_bonus`` — it has NO
    ``granted_keywords`` field.  The deathtouch grant fires on the
    Python side but NOT the Rust side → a documented cross-engine
    asymmetry in the ``granted_keywords`` family (same gap class that
    blocked ``PumpTargetCreatureUntilEOT+keywords`` candidates in prior
    batches).  Probing this card's ATTACKS leg would produce a
    ``compare_fields`` divergence; dropped per directive.

The clean ATTACKS candidates in this round therefore come from the
PROBED-tier cards whose ETB legs are pinned but ATTACKS legs remain
unexercised by any probe:

  1. **Overlord of the Boilerbilges** — ETB pinned in batch K
     (``test_probe_covered_unprobed_k.py``); ATTACKS leg unprobed.
     ATTACKS → ``DealDamageAnyTarget(4)`` fires on the same real
     printing via ``declare_attacker``.

  2. **Overlord of the Floodpits** — ETB pinned in batch H
     (``test_probe_covered_unprobed_h.py``); ATTACKS leg explicitly
     deferred in batch X ("deferred to a later round that specifically
     targets Sequence-with-discard ATTACKS coverage").  ATTACKS →
     ``Sequence(DrawCards(2), DiscardSelf(1))`` — same Effect shape as
     the ETB, new event path.

WHAT EACH PROBE ASSERTS
-----------------------
Every probe drives the **ACTUAL parsed EoE printing** on the Python
side via the production ATTACKS dispatch path (``declare_attackers``),
and a bridged synthetic carrier on the Rust side (``declare_attacker``),
and asserts cross-engine byte-equality.

PARTITION DISCIPLINE (ATTACKS triggers only)
--------------------------------------------
Do NOT pick ETB / DIES / BECOMES_TAPPED / landfall / activated /
sorcery / counter-spell / modal cards (separate lanes).

NEW DEDICATED MODULE (not added to ``test_parity_smoke.py`` or any
prior batch module; avoids all collision with owned files).
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
    """Load ``scripts/parity_smoke.py`` as a module so probes can call
    ``_build_field_view`` for the full cross-engine byte-equality
    compare — same fixture shape as ``tests/test_parity_smoke.py``."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location("parity_smoke", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------
# Probe 1 — Overlord of the Boilerbilges ATTACKS → DealDamageAnyTarget(4)
#
# Oracle: "[Enchantment Creature — Leviathan] 5/5
#   When this creature enters or attacks, it deals 4 damage to any
#   target."
# The ETB leg was probed in batch K
# (``test_probe_covered_unprobed_k.py``). THIS probe drives the ATTACKS
# leg: event=attacks, predicate=IsSelf,
# effect=DealDamageAnyTarget(4) — via ``declare_attacker`` / ``declare_
# attackers``.
#
# Setup: Overlord injected onto p0's bf (unsick, untapped). With no
# creatures on p1's bf, BOTH engines target p1 as the defending player
# → p1 loses 4 life. Python seats ``_PickFirstOpponentTargetAgent`` on
# p0 to mirror Rust's deterministic defender-bf-scan-then-player-
# fallback logic. Full compare_fields.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_overlord_of_the_boilerbilges_attacks_deal_damage_any_target_parity(
    parity_smoke,
):
    """**GENUINE real-EoE probe — Overlord of the Boilerbilges ATTACKS
    DealDamageAnyTarget(4) (batch Z ATTACKS round 2).**

    Drives the **real parsed Overlord of the Boilerbilges printing**
    through the ATTACKS dispatch path on BOTH engines. Batch-K pinned
    the ETB (ENTERS) leg; THIS probe pins the ATTACKS leg — a separate
    dispatch site on both engines — via ``declare_attacker`` /
    ``declare_attackers``.

    Real EoE oracle:

        "When this creature enters or attacks, it deals 4 damage to
         any target."

    Parsed ATTACKS trigger shape (asserted live):
    ``(ATTACKS, IsSelf, DealDamageAnyTarget(amount=4))``.

    With no creatures on p1's battlefield, BOTH engines select p1 as
    the target (Rust: defender-bf-scan finds no creature → player
    fallback; Python: ``_PickFirstOpponentTargetAgent`` returns the
    p1-player entry from ``legal_targets``). p1 loses 4 life on BOTH
    engines; p0 life unchanged.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (p1 life −4 on BOTH; Overlord on p0's bf).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.generic.damage import DealDamageAnyTarget
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Overlord of the Boilerbilges")
    if real is None:
        pytest.skip("Overlord of the Boilerbilges absent from active CardSource")

    # §2 source-of-truth: genuine ATTACKS trigger must be DealDamageAnyTarget.
    attacks_ta = next(
        (ta for ta in real.triggered_abilities if ta.event is Event.ATTACKS),
        None,
    )
    assert attacks_ta is not None, (
        "Overlord of the Boilerbilges must have an ATTACKS triggered ability"
    )
    assert isinstance(attacks_ta.effect, DealDamageAnyTarget), (
        f"ATTACKS trigger must be DealDamageAnyTarget; "
        f"got {type(attacks_ta.effect).__name__}"
    )
    assert attacks_ta.effect.amount == 4, (
        f"DealDamageAnyTarget amount must be 4; got {attacks_ta.effect.amount}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # ATTACKS trigger dict — same Effect shape as the ETB, different event.
    attacks_trigger = {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "deal_damage_any_target",
            "amount": 4,
        },
    }

    # --- Rust: inject Overlord onto p0's bf (unsick, untapped). -------
    rs_id = rs.register_and_inject_object(
        {
            "name": "Overlord of the Boilerbilges",
            "card_types": ["Enchantment", "Creature"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [attacks_trigger],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)
    # Rust: declare_attacker fires the ATTACKS dispatch.
    # DealDamageAnyTarget: no creatures on p1's bf → defender-player
    # fallback → p1 takes 4 damage deterministically.
    assert rs.declare_attacker(rs_id) is True, (
        "Rust: declare_attacker must succeed for a valid unsick attacker"
    )
    assert rs.stack_size() == 1, (
        "Rust: ATTACKS trigger (DealDamageAnyTarget) must be pushed after declaring"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.get_life(1) == rs_p1_life0 - 4, (
        f"Rust: p1 must lose 4 life (DealDamageAnyTarget → player); "
        f"got {rs.get_life(1)} (was {rs_p1_life0})"
    )
    assert rs.get_life(0) == rs_p0_life0, (
        "Rust: p0 life must be unchanged"
    )

    # --- Python: inject Overlord onto p0's bf (unsick, untapped). -----
    py_printing = CardPrinting(
        name="Overlord of the Boilerbilges",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Enchantment Creature",
        supertypes=(),
        card_types=("Enchantment", "Creature"),
        subtypes=(),
        power=int(real.power),
        toughness=int(real.toughness),
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(
            _ta_dict_to_python_triggered_ability(attacks_trigger),
        ),
    )
    py_obj = py.new_object(py_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)

    # Seat _PickFirstOpponentTargetAgent on p0: with no p1 creatures,
    # the agent returns the p1-player target — mirrors Rust's
    # defender-bf-scan-then-player-fallback for DealDamageAnyTarget.
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    py_declare_attackers(py, [py_obj.id])
    assert len(py.stack) == 1, (
        "Python: ATTACKS trigger must be pushed after declaring attacker"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert py.players[1].life == py_p1_life0 - 4, (
        f"Python: p1 must lose 4 life (DealDamageAnyTarget → player); "
        f"got {py.players[1].life} (was {py_p1_life0})"
    )
    assert py.players[0].life == py_p0_life0, (
        "Python: p0 life must be unchanged"
    )

    # Cross-engine byte-equal on life.
    assert rs.get_life(1) == py.players[1].life, "p1 life cross-engine byte-equal"
    assert rs.get_life(0) == py.players[0].life, "p0 life cross-engine byte-equal"

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Overlord of the Boilerbilges ATTACKS deal-damage-any-target must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe 2 — Overlord of the Floodpits ATTACKS → Sequence(DrawCards(2),
#           DiscardSelf(1))
#
# Oracle: "[Enchantment Creature — Leviathan] 5/3
#   When this creature enters or attacks, draw two cards, then discard
#   a card."
# The ETB leg was probed in batch H
# (``test_probe_covered_unprobed_h.py``). Batch X explicitly deferred
# the ATTACKS leg: "deferred to a later round that specifically targets
# Sequence-with-discard ATTACKS coverage." THIS probe is that deferred
# probe.
#
# The ATTACKS trigger fires via ``declare_attacker`` / ``declare_
# attackers`` (not via push_to_stack / spell cast). The Effect shape is
# structurally identical to the ETB variant
# (Sequence(DrawCards(2), DiscardSelf(1))), but exercises the ATTACKS
# dispatch path on BOTH engines.
#
# Setup: 2 identical filler cards in p0's library so DrawCards(2)
# draws both; DiscardSelf(1) discards the first from hand
# (``_DiscardFirstAgent`` on p0 / Rust's pop-head pick).
# Net: 1 filler in p0's graveyard, 1 in hand, library empty.
#
# Assertion strength: established targeted-observable idiom (same as
# ETB probe in batch H). REASON: the draw→discard path moves a seeded-
# library object library→hand→graveyard; Rust resets ``summoning_sick``
# on zone change while Python preserves the stale flag — a gameplay-
# irrelevant graveyard-card flag on a card in the graveyard, NOT a
# draw/discard engine divergence. All gameplay-relevant observables
# (zone sizes, graveyard card name) are byte-equal cross-engine.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_overlord_of_the_floodpits_attacks_draw_discard_parity(
    parity_smoke,
):
    """**GENUINE real-EoE probe — Overlord of the Floodpits ATTACKS
    Sequence(DrawCards(2), DiscardSelf(1)) (batch Z ATTACKS round 2).**

    Drives the **real parsed Overlord of the Floodpits printing**
    through the ATTACKS dispatch path on BOTH engines. Batch-H pinned
    the ETB (ENTERS) leg; THIS probe pins the explicitly-deferred
    ATTACKS leg (see batch X's drop comment).

    Real EoE oracle:

        "When this creature enters or attacks, draw two cards, then
         discard a card."

    Parsed ATTACKS trigger shape (asserted live):
    ``(ATTACKS, IsSelf, Sequence(DrawCards(amount=2), DiscardSelf(amount=1)))``.

    Two filler cards in p0's library → DrawCards(2) draws both →
    DiscardSelf(1) discards the first from hand → net: 1 filler in p0's
    graveyard, 1 in p0's hand, p0's library empty.

    Python: ``_DiscardFirstAgent`` on p0 mirrors Rust's pop-head
    discard behavior (both engines discard the same [0] hand card).

    Assertion strength: **established targeted-observable idiom**
    (identical documented reason to the batch-H ETB probe): the
    draw→discard path moves a seeded-library card library→hand→graveyard;
    Rust resets ``summoning_sick=False`` on zone change while Python
    preserves the stale ``summoning_sick=True`` set at library-seed time
    — a gameplay-irrelevant graveyard-card representation artifact on a
    card in the graveyard (sickness has no gameplay meaning there), NOT
    a draw/discard engine divergence. All GAMEPLAY-RELEVANT cross-engine
    observables below assert byte-equal.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state, CardDef,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from tests.parity._picker_shims import _DiscardFirstAgent

    real = get_active_source().get_printings().get("Overlord of the Floodpits")
    if real is None:
        pytest.skip("Overlord of the Floodpits absent from active CardSource")

    # §2 source-of-truth: genuine ATTACKS trigger must be Sequence(DrawCards2,
    # DiscardSelf1).
    attacks_ta = next(
        (ta for ta in real.triggered_abilities if ta.event is Event.ATTACKS),
        None,
    )
    assert attacks_ta is not None, (
        "Overlord of the Floodpits must have an ATTACKS triggered ability"
    )
    assert isinstance(attacks_ta.effect, Sequence), (
        f"ATTACKS trigger must be Sequence; got {type(attacks_ta.effect).__name__}"
    )
    assert isinstance(attacks_ta.effect.effects[0], DrawCards), (
        f"Sequence[0] must be DrawCards; got {type(attacks_ta.effect.effects[0]).__name__}"
    )
    assert attacks_ta.effect.effects[0].amount == 2, (
        f"DrawCards amount must be 2; got {attacks_ta.effect.effects[0].amount}"
    )

    # Two identical filler cards in p0's library so both draws are
    # forced and both engines see the same card names.
    filler = CardDef(name="OFP ATK Filler", card_type="Land", mana_produced=("U",))
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=("OFP ATK Filler", "OFP ATK Filler"),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # ATTACKS trigger dict — identical Effect shape to ETB, different event.
    attacks_trigger = {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "sequence", "effects": [
            {"kind": "draw_cards", "count": 2},
            {"kind": "discard_self", "amount": 1},
        ]},
    }

    # --- Rust: inject Overlord onto p0's bf (unsick, untapped). -------
    rs_id = rs.register_and_inject_object(
        {
            "name": "Overlord of the Floodpits",
            "card_types": ["Enchantment", "Creature"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [attacks_trigger],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    rs_p0_lib0 = rs.library_sizes[0]
    assert rs_p0_lib0 == 2, "Rust: p0 library must start with 2 filler cards"
    assert rs.declare_attacker(rs_id) is True, (
        "Rust: declare_attacker must succeed for an unsick Overlord of the Floodpits"
    )
    assert rs.stack_size() == 1, (
        "Rust: ATTACKS trigger (Sequence) must be pushed after declaring attacker"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.library_sizes[0] == 0, (
        f"Rust: p0 library must be empty after drawing 2; got {rs.library_sizes[0]}"
    )
    assert rs.hand_sizes[0] == 1, (
        f"Rust: p0 hand must have 1 after drawing 2 and discarding 1; "
        f"got {rs.hand_sizes[0]}"
    )
    assert rs.graveyard_sizes[0] == 1, (
        f"Rust: p0 graveyard must have 1 (the discarded card); "
        f"got {rs.graveyard_sizes[0]}"
    )

    # --- Python: inject Overlord onto p0's bf (unsick, untapped). -----
    py_printing = CardPrinting(
        name="Overlord of the Floodpits",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Enchantment Creature",
        supertypes=(),
        card_types=("Enchantment", "Creature"),
        subtypes=(),
        power=int(real.power),
        toughness=int(real.toughness),
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(
            _ta_dict_to_python_triggered_ability(attacks_trigger),
        ),
    )
    py_obj = py.new_object(py_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)

    # Seat _DiscardFirstAgent on p0 so hand[0] is discarded (mirrors
    # Rust's pop-head discard when both engines see the same hand order).
    py.players[0].agent = _DiscardFirstAgent()

    py_p0_lib0 = len(py.players[0].library)
    assert py_p0_lib0 == 2, "Python: p0 library must start with 2 filler cards"

    py_declare_attackers(py, [py_obj.id])
    assert len(py.stack) == 1, (
        "Python: ATTACKS trigger must be pushed after declaring attacker"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert len(py.players[0].library) == 0, (
        f"Python: p0 library must be empty after drawing 2; "
        f"got {len(py.players[0].library)}"
    )
    assert len(py.players[0].hand) == 1, (
        f"Python: p0 hand must have 1 after drawing 2 and discarding 1; "
        f"got {len(py.players[0].hand)}"
    )
    assert len(py.players[0].graveyard) == 1, (
        f"Python: p0 graveyard must have 1 (the discarded card); "
        f"got {len(py.players[0].graveyard)}"
    )

    # Cross-engine graveyard content byte-equal (graveyard card name
    # pinned — the targeted-observable idiom for the discard path).
    rs_gy_names = sorted(
        e["printing_name"] for e in rs.graveyard_snapshot(0)
    )
    py_gy_names = sorted(
        o.printing.name for o in py.players[0].graveyard
    )
    assert rs_gy_names == ["OFP ATK Filler"] == py_gy_names, (
        f"the discarded card must be 'OFP ATK Filler' in p0's graveyard on BOTH; "
        f"rust={rs_gy_names} py={py_gy_names}"
    )

    # **Established targeted-observable idiom (documented reason):**
    # draw→discard path: library→hand→graveyard zone moves cause Rust
    # to reset ``summoning_sick=False`` on each zone change, while
    # Python preserves the stale ``summoning_sick=True`` set when the
    # card was seeded in the library. This is a gameplay-irrelevant
    # graveyard-card representation artifact (sickness has no gameplay
    # meaning for a card in the graveyard), NOT a draw/discard engine
    # divergence. Same documented reason as the batch-H ETB probe and
    # the batch-X Shroudstomper ATTACKS probe.
    #
    # All GAMEPLAY-RELEVANT cross-engine observables:
    assert rs.library_sizes[0] == len(py.players[0].library), (
        "p0 library size cross-engine byte-equal"
    )
    assert rs.hand_sizes[0] == len(py.players[0].hand), (
        "p0 hand size cross-engine byte-equal"
    )
    assert rs.graveyard_sizes[0] == len(py.players[0].graveyard), (
        "p0 graveyard size cross-engine byte-equal"
    )
    assert rs.library_sizes[1] == len(py.players[1].library), (
        "p1 library size cross-engine byte-equal"
    )
    assert rs.hand_sizes[1] == len(py.players[1].hand), (
        "p1 hand size cross-engine byte-equal"
    )
    assert rs.graveyard_sizes[1] == len(py.players[1].graveyard), (
        "p1 graveyard size cross-engine byte-equal"
    )
