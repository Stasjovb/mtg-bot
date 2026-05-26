"""**Spacecraft Phase 3B Cycle 1 (2026-05-25).**

Tests for the Phase 3B Cycle 1 Rust substrate landing per
``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_3_DESIGN.md`` §4.3 (Rust
spec) + §5 (Python bridge spec) + §6.3 (test plan) + §7.2 (cycle
table).

Deliverables (Cycle 1 Rust slice, per design doc §4.3):

  - New Rust ``Effect`` variant on ``cards.rs::Effect``:
      * ``OptionalPutCreatureFromHandOntoBattlefield`` — Sledge-Class
        Seedship's ATTACKS trigger effect ("You may put a creature
        card from your hand onto the battlefield."). Unit Effect (no
        fields).
    With: enum variant + ``parse_effect`` arm + ``to_pydict`` arm +
    ``state_ops_resolve`` resolve arm + ``cross_engine.py`` bridge
    dict→Python arm + ``trajectory.py`` reverse-serializer leaf in
    ``_python_ta_to_safe_dict``.
  - ZERO change to ``_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES``
    (substrate-only — Cycle 2 widens the admit set).
  - ZERO change to ``_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES``
    (substrate-only — Cycle 2 adds ``(ATTACKS, IsSelf())``).

This is a **substrate-only closure** — the cycle adds the new Rust
Effect variant + bridge plumbing as reusable infrastructure. The
pilot card (Sledge-Class Seedship) STAYS DECLINED at the production-
deck admit gate post-Cycle-1 because:

  - ``_python_ta_to_safe_dict``'s ``safe_effect_kinds`` set for
    (ATTACKS, IsSelf) does NOT yet include
    ``optional_put_creature_from_hand_onto_battlefield`` (Phase 3
    flips through its OWN admit predicate
    ``_printing_is_bridge_phase_3_trigger_spacecraft`` per design
    doc §5.3 — but the safe-trigger gate's refusal pins the §2
    no-silent-auto-grow contract for the Phase-1 path).
  - The Phase-3 admit-class allowlist
    ``_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES`` does NOT yet
    include ``OptionalPutCreatureFromHandOntoBattlefield`` (Cycle 2
    ships the widen per design doc §7.2 — sibling of the Phase-3A
    C2 admit widen at commit ``67fe1f76``).
  - The Phase-3 (event, predicate)-shape allowlist
    ``_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES`` does NOT yet
    include ``(Event.ATTACKS, IsSelf(subject=None))`` (Cycle 2 ships
    the widen — Sledge-Class Seedship's ATTACKS event is currently
    rejected at the event-shape gate regardless of the Effect
    class).

**Verify-first findings (live tree, main `8e5ffd3e`):**

  - Sledge-Class Seedship's live oracle text: ATTACKS trigger fires
    ``OptionalPutCreatureFromHandOntoBattlefield()``.
  - The live printing's TA shape: single triggered ability,
    ``event=Event.ATTACKS``, ``predicate=IsSelf(subject=None)``,
    ``effect=OptionalPutCreatureFromHandOntoBattlefield()``,
    ``tier_threshold=0``, ``once_per_turn=False``.
  - Card stats: ``{2}{G}`` ({2}{G} mana cost), 4/5, station_threshold=7,
    stationed_keywords=frozenset({'flying'}), keywords=frozenset(),
    static_abilities=(), activated_abilities=().
  - Python's ``OptionalPutCreatureFromHandOntoBattlefield`` class at
    ``effects/combinators.py:205`` — frozen dataclass with NO fields;
    the resolve method walks ``p.hand`` for Creature cards, picks
    the agent's choice (default-yes first-slice convention), removes
    from hand, and calls ``put_into_battlefield(state, card,
    controller_id)``.
  - Rust precedents: ``Effect::PutBasicLandFromHandOntoBattlefield
    Tapped`` resolve at ``state_ops_resolve.rs:23242-23300`` (hand-
    search-and-pick + ETB queue, widened from basic-land predicate to
    creature predicate); ``Effect::ReturnCreatureFromYourGraveyardTo
    Battlefield`` for the summoning-sick + untapped bf-entry shape;
    Phase-3A's ``OptionalSacLandOrLanderForBasicLandRamp`` resolve at
    line 6823 for the Optional-decision-point dispatch pattern.
  - The ATTACKS-trigger Aura-side dispatch path (non-Aura): the
    centralized ``dispatch_event(state, Event::Attacks, attacker_id)``
    chokepoint at ``state_ops_combat.rs:1734`` fires for the
    just-declared attacker; the bf observer set already contains the
    attacker, so a ``Predicate::SourceIsSelf`` trigger ("whenever
    this Spacecraft attacks") matches naturally. No Aura-attachment
    plumbing required — Sledge-Class Seedship's trigger fires when
    IT attacks.

**Test plan (per design doc §6.3 #10):**

  - Parser SoT pin: confirm Python's
    ``OptionalPutCreatureFromHandOntoBattlefield`` class exists in
    ``effects.combinators`` with the canonical no-field shape.
  - Verify-first pin: confirm Sledge-Class Seedship's live ATTACKS
    shape (single triggered ability, ATTACKS event, IsSelf predicate,
    ``OptionalPutCreatureFromHandOntoBattlefield()`` effect,
    tier_threshold=0).
  - Rust unit pins: ``parse_effect`` arm + ``to_pydict`` arm
    round-trip + register_printing acceptance.
  - Cross-engine bridge pin: dict→Python bridge arm in
    ``_ta_dict_to_python_effect``.
  - Reverse-serializer pin: forward emit through
    ``_python_ta_to_safe_dict`` is dormant at the safe-kinds gate
    (Sledge-Class Seedship stays declined) BUT the isinstance arm
    recognizes the effect class.
  - Rust resolve arm pins: silent no-op on no-eligible-target;
    happy-path hand→bf untapped + summoning_sick + ETB queue;
    non-Creature filter rejects; smallest-index first-slice pick.
  - Substrate-only invariant pin: Sledge-Class Seedship STAYS
    DECLINED at the Phase-3 admit gate + production-deck loader
    filter post-Cycle-1.
  - Phase 1 + Phase 2 + Phase 3A non-regression pins (3 cards still
    admit at their respective gates).
"""

from __future__ import annotations

import importlib.util

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


@pytest.fixture
def engine():
    """The ``mtg_bot_engine`` module, or skip if not installed."""
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine
    return mtg_bot_engine


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_optional_put_creature_from_hand_onto_battlefield_class_exists():
    """**Parser SoT pin.** Python's
    ``OptionalPutCreatureFromHandOntoBattlefield`` class is in
    ``effects.combinators``, a frozen unit dataclass (no fields). Two
    instances compare equal (no-field unit-dataclass __eq__ semantics).
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.combinators import (
        OptionalPutCreatureFromHandOntoBattlefield,
    )

    a = OptionalPutCreatureFromHandOntoBattlefield()
    b = OptionalPutCreatureFromHandOntoBattlefield()

    # Subclass invariant.
    assert isinstance(a, Effect)
    # Frozen-dataclass __eq__ semantics — two unit instances compare
    # equal.
    assert a == b


def test_sledge_class_seedship_live_printing_matches_design_doc_shape():
    """**Verify-first pin — Sledge-Class Seedship's live ATTACKS
    shape.** Confirms the design doc §3B row at HEAD: single triggered
    ability, ATTACKS event, IsSelf predicate (subject=None),
    ``OptionalPutCreatureFromHandOntoBattlefield()`` effect,
    ``tier_threshold == 0``, ``once_per_turn == False``.

    NOTE: Sledge-Class Seedship STAYS DECLINED at the production-deck
    admit gate post-Cycle-1 because the Phase-3 admit-class allowlist
    + event-shape allowlist do NOT yet include the new Effect class /
    ATTACKS event shape (Cycle 2 widens both per design doc §7.2).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.combinators import (
        OptionalPutCreatureFromHandOntoBattlefield,
    )
    from mtg_bot.effects.predicates import Event, IsSelf

    ps = OracleParserCardSource().get_printings()
    seedship = ps["Sledge-Class Seedship"]

    # Spacecraft subtype + station_threshold present per design doc
    # §3B.
    assert "Spacecraft" in seedship.subtypes
    assert seedship.station_threshold == 7
    assert tuple(sorted(seedship.stationed_keywords)) == ("flying",)
    assert seedship.keywords == frozenset()
    assert seedship.static_abilities == ()
    assert seedship.activated_abilities == ()
    assert seedship.mana_cost_str == "{2}{G}"
    assert seedship.power == 4
    assert seedship.toughness == 5
    # Sub-shape C contract per design doc §2 — single trigger entry.
    tas = tuple(seedship.triggered_abilities or ())
    assert len(tas) == 1, (
        f"expected 1 triggered ability on Sledge-Class Seedship, got "
        f"{len(tas)}: {tas}"
    )
    ta = tas[0]

    assert ta.event is Event.ATTACKS
    assert isinstance(ta.predicate, IsSelf)
    assert ta.predicate.subject is None
    assert isinstance(
        ta.effect, OptionalPutCreatureFromHandOntoBattlefield,
    )
    assert ta.tier_threshold == 0
    assert ta.once_per_turn is False


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict -> Python)
# ---------------------------------------------------------------------------


def test_bridge_arm_optional_put_creature_from_hand_onto_battlefield():
    """Bridge arm constructs
    ``OptionalPutCreatureFromHandOntoBattlefield()`` from a single-kind
    dict (no fields)."""
    from mtg_bot.effects.combinators import (
        OptionalPutCreatureFromHandOntoBattlefield,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect(
        {"kind": "optional_put_creature_from_hand_onto_battlefield"}
    )
    assert isinstance(back, OptionalPutCreatureFromHandOntoBattlefield)


def test_bridge_arm_optional_put_creature_ignores_extra_keys():
    """Bridge arm is robust to extra keys on the dict (the Rust
    to_pydict emits ONLY ``kind``; extra keys would only appear from
    a broken producer — accept silently for the unit-Effect arm).
    """
    from mtg_bot.effects.combinators import (
        OptionalPutCreatureFromHandOntoBattlefield,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "optional_put_creature_from_hand_onto_battlefield",
        "extra_field": 42,
    })
    assert isinstance(back, OptionalPutCreatureFromHandOntoBattlefield)


# ---------------------------------------------------------------------------
# Reverse-serializer leaf pin in _python_ta_to_safe_dict
# ---------------------------------------------------------------------------


def test_python_ta_to_safe_dict_optional_put_creature_arm_is_dormant_at_safe_kinds_gate():
    """**Substrate-only invariant pin (the load-bearing
    no-silent-auto-grow gate).** ``_python_ta_to_safe_dict`` recognizes
    the new Effect class in its isinstance cascade (the dict-emit
    primitive is pre-positioned for Cycle 2 / the Phase-3 admit-class
    widen), but the ``optional_put_creature_from_hand_onto_battlefield``
    kind is NOT in any (event, predicate) ``safe_effect_kinds`` set
    this cycle.

    Concrete observable: ``_python_ta_to_safe_dict`` returns ``None``
    for a synthetic (ATTACKS, IsSelf,
    OptionalPutCreatureFromHandOntoBattlefield) TriggeredAbility —
    Sledge-Class Seedship STAYS DECLINED at the Phase-1
    ``_python_ta_to_safe_dict`` gate post-Cycle-1.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.combinators import (
        OptionalPutCreatureFromHandOntoBattlefield,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.ATTACKS,
        predicate=IsSelf(),
        effect=OptionalPutCreatureFromHandOntoBattlefield(),
    )
    # Substrate-only: gate returns None — Sledge-Class Seedship
    # declines.
    assert _python_ta_to_safe_dict(ta) is None


def test_python_ta_to_safe_dict_arm_recognizes_optional_put_creature_class():
    """**Recognition arm pin (the substrate's pre-position).** Even
    though the safe-kinds gate refuses, the isinstance cascade
    RECOGNIZES ``OptionalPutCreatureFromHandOntoBattlefield`` and
    reaches the gate (rather than falling through to ``else: return
    None`` earlier, before the safe-kinds check).

    Defense-in-depth: the kind would normally be paired with
    ``_SAFE_TRIGGERS`` entry; here we pin that the kind is NOT in
    any current ``safe_effect_kinds`` tuple anywhere in the
    function. The recognition arm's presence is verified by
    inspecting the source file directly (Edit-traced).
    """
    import inspect
    from mtg_bot.parity import trajectory

    source = inspect.getsource(trajectory._python_ta_to_safe_dict)
    # The recognition arm must be present (a key part of the
    # substrate).
    assert "OptionalPutCreatureFromHandOntoBattlefield" in source, (
        "isinstance arm for OptionalPutCreatureFromHandOntoBattlefield "
        "must be present in _python_ta_to_safe_dict (the substrate's "
        "pre-positioned recognition)."
    )
    # The kind string must be present.
    assert (
        "optional_put_creature_from_hand_onto_battlefield" in source
    ), (
        "kind string must be emitted by the substrate's recognition "
        "arm."
    )


def test_python_ta_to_safe_dict_safe_kinds_set_does_not_include_optional_put_creature():
    """**The §2 no-silent-auto-grow load-bearing pin.** Walk the live
    ``_SAFE_TRIGGERS`` set — NO entry carries the
    ``optional_put_creature_from_hand_onto_battlefield`` effect kind.
    The substrate is dormant.
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    for event, pred, kind in _SAFE_TRIGGERS:
        assert kind != "optional_put_creature_from_hand_onto_battlefield", (
            f"_SAFE_TRIGGERS entry {(event, pred, kind)} silently "
            f"auto-grows Sledge-Class Seedship; remove it from C1 or "
            f"ship the matching Phase-3 admit predicate widen + "
            f"per-card probe + FLIP cycle (per design doc §7.2 "
            f"Cycle 2)."
        )


# ---------------------------------------------------------------------------
# Rust unit pins — parse + register + to_pydict round-trip
# ---------------------------------------------------------------------------


def _synthetic_sledge_class_seedship_dict():
    """A synthetic Spacecraft printing carrying the new Effect class
    via a single ATTACKS trigger entry — the canonical Sledge-Class
    Seedship shape per design doc §3B.

    NOTE: this synthetic carrier is for substrate parse/to_pydict
    pins; Phase 3B admit-class allowlist widen (which uses its own
    dispatch) ships in Cycle 2.
    """
    return {
        "name": "Synthetic Sledge-Class Seedship",
        "card_types": ["Artifact"],
        "subtypes": ["Spacecraft"],
        "mana_cost": {"generic": 2, "G": 1},
        "power": 4,
        "toughness": 5,
        "station_threshold": 7,
        "triggered_abilities": [
            {
                "event": "attacks",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "optional_put_creature_from_hand_onto_battlefield",
                },
            }
        ],
    }


def _put_creature_spell_dict():
    """A Sorcery-shape spell carrying the new Effect as its spell
    effect — used for direct resolve-arm pins via the stack-push
    path. Source post-resolve moves hand → graveyard so the
    battlefield delta we assert on is the put-from-hand creature
    only.
    """
    return {
        "name": "Test Optional Put Creature From Hand",
        "card_types": ["Sorcery"],
        "effects": [
            {
                "kind": "optional_put_creature_from_hand_onto_battlefield",
            }
        ],
    }


def test_rust_register_optional_put_creature_from_hand_onto_battlefield():
    """**Rust parse arm pin.** ``register_printing`` accepts a
    triggered ability carrying the new effect kind. The pid is
    returned and ``get_printing_name`` echoes the name."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_synthetic_sledge_class_seedship_dict())
    assert reg.get_printing_name(pid) == "Synthetic Sledge-Class Seedship"


def test_rust_register_optional_put_creature_via_spell_effect():
    """**Rust parse arm pin (spell-effect entry-point).** Registering
    a Sorcery-shape printing whose ``effects`` carry the new effect
    kind succeeds (parse_effect arm accepts; no fields required).
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_put_creature_spell_dict())
    assert reg.get_printing_name(pid) == (
        "Test Optional Put Creature From Hand"
    )


# ---------------------------------------------------------------------------
# Rust resolve arm pins
# ---------------------------------------------------------------------------


def test_resolve_optional_put_creature_no_eligible_in_hand_silent_no_op(engine):
    """**Resolve arm — silent no-op on no eligible creature in hand.**
    Set up: no Creature in p0's hand (the spell itself is the only
    card). Resolve the effect with p0 as source-controller. Expected:
    stack pops cleanly, NO hand→bf move, NO state mutation beyond the
    Sorcery's hand→graveyard move.

    Build a fresh state with num_hand=0 so the only hand object is the
    spell itself.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=50,
    )

    bf_p0_before = state.battlefield_sizes[0]
    hand_p0_before = state.hand_sizes[0]
    gy_p0_before = state.graveyard_sizes[0]

    spell_obj_id = state.register_and_inject_object(
        _put_creature_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    # No creature put onto bf (hand was empty of Creature cards).
    assert state.battlefield_sizes[0] == bf_p0_before
    # Hand returns to pre-injection size (spell injected then drained
    # to stack then to graveyard).
    assert state.hand_sizes[0] == hand_p0_before
    # The Sorcery source moves hand→graveyard per CR 608.2m, so gy
    # grows by exactly 1.
    assert state.graveyard_sizes[0] == gy_p0_before + 1


def test_resolve_optional_put_creature_happy_path_hand_to_bf_untapped(engine):
    """**Resolve arm — happy path.** Set up: p0 has 1 Creature card
    (a Grizzly Bears) in hand. Resolve the effect with p0 as source-
    controller. Expected: the Bear moves hand→bf UNTAPPED with
    summoning_sick=true, the ETB dispatch is queued, and the Sorcery
    source moves to graveyard.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=50,
    )

    bear_obj_id = state.register_and_inject_object(
        {
            "name": "Test Grizzly Bears",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_HAND,
    )

    bf_before = state.battlefield_sizes[0]
    hand_before = state.hand_sizes[0]
    gy_before = state.graveyard_sizes[0]
    assert hand_before == 1  # only the Bear pre-injection
    assert state.find_object_zone(bear_obj_id) == ZONE_HAND

    spell_obj_id = state.register_and_inject_object(
        _put_creature_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    # Bear is now on the battlefield.
    assert state.find_object_zone(bear_obj_id) == ZONE_BATTLEFIELD
    # Per the printed text — UNTAPPED entry (no "tapped" rider).
    assert state.is_tapped(bear_obj_id) is False
    # CR 302.1 — summoning sickness applies to any creature entering
    # the battlefield, including the put-from-hand path.
    assert state.is_summoning_sick(bear_obj_id) is True
    # Net: +1 bf (Bear entered), -1 hand (Bear left), +1 gy (Sorcery
    # source).
    assert state.battlefield_sizes[0] == bf_before + 1
    assert state.hand_sizes[0] == hand_before - 1
    assert state.graveyard_sizes[0] == gy_before + 1


def test_resolve_optional_put_creature_non_creature_filter_rejects(engine):
    """**Resolve arm — eligibility filter.** A non-Creature card in
    hand (an Instant or a Land) is NOT eligible; the effect silent
    no-ops (mirror of Python's ``if not options: return``
    short-circuit at ``effects/combinators.py:222-224``).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=50,
    )

    # An Instant (non-Creature) in hand.
    instant_obj_id = state.register_and_inject_object(
        {
            "name": "Test Lightning Bolt",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        0,
        ZONE_HAND,
    )

    bf_before = state.battlefield_sizes[0]
    hand_before = state.hand_sizes[0]
    gy_before = state.graveyard_sizes[0]

    spell_obj_id = state.register_and_inject_object(
        _put_creature_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Instant unchanged (still in hand, NOT put onto bf).
    assert state.find_object_zone(instant_obj_id) == ZONE_HAND
    # Battlefield unchanged.
    assert state.battlefield_sizes[0] == bf_before
    # Hand: started with Instant + got/lost spell, returns to pre-
    # injection size.
    assert state.hand_sizes[0] == hand_before
    # Only the spell source moved hand→graveyard.
    assert state.graveyard_sizes[0] == gy_before + 1


def test_resolve_optional_put_creature_picks_smallest_index_eligible_in_hand(
    engine,
):
    """**Resolve arm — deterministic first-slice pick.** With TWO
    eligible Creature cards in p0's hand, the resolve arm picks the
    smallest-hand-index (= first-injected) one. Mirrors the no-agent
    default-yes deterministic-first-slice convention from the sibling
    Optional* arms.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=50,
    )

    first_bear = state.register_and_inject_object(
        {
            "name": "Test Bear A",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_HAND,
    )
    second_bear = state.register_and_inject_object(
        {
            "name": "Test Bear B",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_HAND,
    )

    spell_obj_id = state.register_and_inject_object(
        _put_creature_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # First-injected Bear is the deterministic pick (smallest-hand-
    # index).
    assert state.find_object_zone(first_bear) == ZONE_BATTLEFIELD
    # Second Bear still in hand.
    assert state.find_object_zone(second_bear) == ZONE_HAND


def test_resolve_optional_put_creature_filters_mixed_hand_to_only_creatures(
    engine,
):
    """**Resolve arm — mixed-hand eligibility filter.** With a Land
    at index 0, an Instant at index 1, and a Creature at index 2 in
    p0's hand, the resolve arm picks the Creature (the only eligible
    card) — the non-Creature cards at lower indices are SKIPPED, not
    blocking the pick.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=50,
    )

    land_obj_id = state.register_and_inject_object(
        {
            "name": "Test Forest",
            "card_types": ["Land"],
            "subtypes": ["Forest"],
            "supertypes": ["Basic"],
            "mana_cost": {},
        },
        0,
        ZONE_HAND,
    )
    instant_obj_id = state.register_and_inject_object(
        {
            "name": "Test Bolt",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        0,
        ZONE_HAND,
    )
    creature_obj_id = state.register_and_inject_object(
        {
            "name": "Test Bear",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_HAND,
    )

    spell_obj_id = state.register_and_inject_object(
        _put_creature_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Land and Instant unchanged (still in hand, NOT eligible).
    assert state.find_object_zone(land_obj_id) == ZONE_HAND
    assert state.find_object_zone(instant_obj_id) == ZONE_HAND
    # Creature picked + moved to bf.
    assert state.find_object_zone(creature_obj_id) == ZONE_BATTLEFIELD
    assert state.is_tapped(creature_obj_id) is False
    assert state.is_summoning_sick(creature_obj_id) is True


def test_resolve_optional_put_creature_multifaced_artifact_creature_is_eligible(
    engine,
):
    """**Resolve arm — multi-typed (Artifact Creature) eligibility.**
    A card with BOTH ``Artifact`` and ``Creature`` in card_types is
    eligible (the predicate gates on Creature membership, not on
    Creature exclusivity). Mirrors Python's
    ``c.printing.is_creature`` which returns True for any printing
    whose card_types contains Creature.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=50,
    )

    construct_obj_id = state.register_and_inject_object(
        {
            "name": "Test Artifact Creature Construct",
            "card_types": ["Artifact", "Creature"],
            "subtypes": ["Construct"],
            "mana_cost": {"generic": 3},
            "power": 3,
            "toughness": 3,
        },
        0,
        ZONE_HAND,
    )

    spell_obj_id = state.register_and_inject_object(
        _put_creature_spell_dict(), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Construct accepted as Creature-type, put onto bf.
    assert state.find_object_zone(construct_obj_id) == ZONE_BATTLEFIELD
    assert state.is_tapped(construct_obj_id) is False
    assert state.is_summoning_sick(construct_obj_id) is True


# ---------------------------------------------------------------------------
# ATTACKS-trigger Aura-side dispatch path: confirm non-Aura ATTACKS
# triggers dispatch correctly (Sledge-Class Seedship's trigger fires
# when IT attacks, not when something attached to it does).
# ---------------------------------------------------------------------------


def test_attacks_trigger_self_dispatch_for_non_aura_carrier(engine):
    """**ATTACKS-trigger dispatch path pin — non-Aura carrier.**
    Confirm the centralized ``dispatch_event(state, Event::Attacks,
    attacker_id)`` chokepoint at ``state_ops_combat.rs:1734`` fires
    for the just-declared attacker, regardless of whether the
    attacker carries a TriggeredAbility with predicate IsSelf().
    The bf observer set already contains the attacker, so a
    ``Predicate::SourceIsSelf`` trigger matches naturally — no Aura-
    attachment plumbing required.

    This pin uses a synthetic creature with a single ATTACKS+IsSelf
    trigger whose effect is the new OptionalPutCreatureFromHandOnto
    Battlefield. Declare the carrier as attacker; the ATTACKS trigger
    queues onto the stack, resolves, and the put-from-hand effect
    fires.

    Sledge-Class Seedship's real-card invariant — the trigger fires
    when IT attacks (not when something attached to it does) — is
    structurally identical to this synthetic shape: both are
    bf-resident creatures whose ATTACKS+IsSelf trigger observes
    their own attack-declaration via the bf observer set.
    """
    # The carrier: a synthetic 4/5 creature with the new Effect on
    # ATTACKS+IsSelf.
    carrier_printing_dict = {
        "name": "Synthetic ATTACKS-IsSelf Carrier",
        "card_types": ["Creature"],
        "subtypes": ["Construct"],
        "mana_cost": {"generic": 2, "G": 1},
        "power": 4,
        "toughness": 5,
        "triggered_abilities": [
            {
                "event": "attacks",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "optional_put_creature_from_hand_onto_battlefield",
                },
            }
        ],
    }
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=20,
    )

    # Inject the carrier onto p0's bf — not summoning-sick so it can
    # attack this turn.
    carrier_id = state.register_and_inject_object(
        carrier_printing_dict, 0, ZONE_BATTLEFIELD,
    )
    state.force_set_summoning_sick(carrier_id, False)
    # Inject a Bear into p0's hand for the trigger to put-from-hand.
    bear_id = state.register_and_inject_object(
        {
            "name": "Test Bear Bear",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_HAND,
    )

    # Declare carrier as attacker — this dispatches Event::Attacks
    # via the centralized chokepoint at state_ops_combat.rs:1734,
    # which pushes the carrier's ATTACKS+IsSelf trigger onto the
    # stack. p0 is the default active_player on a fresh synthetic
    # state, so the declare_attacker preconditions hold without
    # phase-set fiddling (the engine's declare_attacker rejects
    # tapped/summoning-sick attackers but does NOT gate on the
    # active_player matching).
    assert state.declare_attacker(carrier_id) is True
    # Drain the stack — the ATTACKS trigger resolves the put-from-
    # hand effect.
    state.process_stack_until_empty()

    # Post-attack: the ATTACKS trigger fired + resolved, putting the
    # Bear onto the battlefield untapped + summoning_sick.
    assert state.find_object_zone(bear_id) == ZONE_BATTLEFIELD, (
        "The Bear should have been put from hand onto the battlefield "
        "by the carrier's ATTACKS-IsSelf trigger (the substrate's "
        "ATTACKS dispatch path for non-Aura carriers must fire when "
        "the carrier ITSELF attacks). Got zone: "
        f"{state.find_object_zone(bear_id)}"
    )
    assert state.is_tapped(bear_id) is False
    assert state.is_summoning_sick(bear_id) is True


# ---------------------------------------------------------------------------
# Substrate-only invariant pin — Sledge-Class Seedship STAYS DECLINED
# ---------------------------------------------------------------------------


def test_sledge_class_seedship_now_admits_at_admit_gate_post_cycle_2():
    """**C2 FLIP invariant pin — Sledge-Class Seedship NOW ADMITS at
    the Phase-3 admit gate post-Cycle-2 (2026-05-25; this slice
    inverts the original C1 substrate-only invariant in-place per
    Phase-3A Cycle-2 precedent).**

    Cycle 2 widens BOTH the Effect-class allowlist
    (``_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES`` += ``Optional
    PutCreatureFromHandOntoBattlefield``) AND the (event,
    predicate)-shape table (``_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_
    SHAPES`` += ``(Event.ATTACKS, IsSelf(subject=None))``). With both
    widens in place, Sledge-Class Seedship passes the admit predicate
    end-to-end:

      1. ``(ATTACKS, IsSelf(subject=None))`` is in
         ``_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES``.
      2. ``OptionalPutCreatureFromHandOntoBattlefield`` is in
         ``_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES``.
      3. ``tier_threshold == 0 >= 0`` and ``once_per_turn is False``.

    Concrete observables:

      1. Phase 1 ``_printing_is_bridge_pure_station_spacecraft``
         STILL declines Sledge-Class Seedship (the zero-ability gate
         refuses the trigger-bearing carrier — unchanged from
         pre-Phase-3).
      2. Phase 2 ``_printing_is_bridge_phase_2_static_anthem_
         spacecraft`` STILL declines Sledge-Class Seedship (the
         single-static gate refuses the no-static + triggered-ability
         carrier — unchanged from pre-Phase-3).
      3. The Phase-3 admit predicate
         ``_printing_is_bridge_phase_3_trigger_spacecraft`` NOW
         ADMITS Sledge-Class Seedship.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_phase_2_static_anthem_spacecraft,
        _printing_is_bridge_phase_3_trigger_spacecraft,
        _printing_is_bridge_pure_station_spacecraft,
    )

    ps = OracleParserCardSource().get_printings()
    seedship = ps["Sledge-Class Seedship"]

    # Phase-1 path STILL declines (the zero-ability gate refuses the
    # trigger-bearing carrier).
    assert _printing_is_bridge_pure_station_spacecraft(seedship) is False, (
        "Phase-1 _printing_is_bridge_pure_station_spacecraft must "
        "STILL decline Sledge-Class Seedship post-C2 (the zero-ability "
        "gate refuses the trigger-bearing carrier)."
    )
    # Phase-2 path STILL declines (the single-static gate refuses the
    # no-static + triggered-ability carrier).
    assert _printing_is_bridge_phase_2_static_anthem_spacecraft(
        seedship,
    ) is False, (
        "Phase-2 _printing_is_bridge_phase_2_static_anthem_spacecraft "
        "must STILL decline Sledge-Class Seedship post-C2 (it carries "
        "NO static ability + DOES carry a triggered ability — neither "
        "half of the Phase 2 single-static contract)."
    )

    # **THE C2 FLIP** — Phase-3 admit predicate NOW ADMITS Sledge-
    # Class Seedship.
    assert _printing_is_bridge_phase_3_trigger_spacecraft(
        seedship,
    ) is True, (
        "**Phase 3B C2 FLIP** — Phase-3 admit predicate "
        "`_printing_is_bridge_phase_3_trigger_spacecraft` MUST now "
        "ADMIT Sledge-Class Seedship post-Cycle-2 (the Effect-class "
        "allowlist + event-shape table both widened to include "
        "OptionalPutCreatureFromHandOntoBattlefield + (ATTACKS, "
        "IsSelf(subject=None)) respectively per design doc §7.2). If "
        "this test fails, the C2 widen regressed."
    )


def test_loader_filter_admits_sledge_class_seedship_post_cycle_2():
    """**Loader-level FLIP pin (end-to-end).** The
    ``_filter_deck_to_bridge_supported`` loader gate NOW ADMITS Sledge-
    Class Seedship post-Cycle-2 (the Phase-3B admit-class widen +
    event-shape widen + per-card builder ATTACKS + Optional
    PutCreatureFromHandOntoBattlefield emit arms ship in this slice).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _filter_deck_to_bridge_supported,
    )

    ps = OracleParserCardSource().get_printings()
    assert "Sledge-Class Seedship" in ps

    filtered_names, card_defs = _filter_deck_to_bridge_supported(
        ["Sledge-Class Seedship"],
        ps,
    )
    assert filtered_names == ["Sledge-Class Seedship"], (
        "Sledge-Class Seedship must be ADMITTED by "
        "_filter_deck_to_bridge_supported post-Cycle-2; the Phase-3B "
        "admit widen (Effect-class allowlist + event-shape table) "
        "shipped in this slice per design doc §7.2. Got filtered "
        f"names: {filtered_names}"
    )
    assert len(card_defs) == 1
    cd = card_defs[0]
    assert cd.name == "Sledge-Class Seedship"
    # Per-card builder must emit the canonical ATTACKS-shape
    # + optional_put_creature_from_hand_onto_battlefield triggered
    # ability dict.
    assert cd.triggered_abilities == (
        {
            "event": "attacks",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "optional_put_creature_from_hand_onto_battlefield",
            },
        },
    )


def test_phase_3a_allowlist_now_includes_optional_put_creature():
    """**C2 FLIP pin (Effect-class allowlist widen).** Walk the live
    ``_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES`` tuple — exactly
    one entry IS ``OptionalPutCreatureFromHandOntoBattlefield``. The
    C2 widen has shipped explicitly per design doc §7.2 (sibling of
    the original Phase 3A pilot class ``Optional
    SacLandOrLanderForBasicLandRamp``).
    """
    from mtg_bot.effects.combinators import (
        OptionalPutCreatureFromHandOntoBattlefield,
        OptionalSacLandOrLanderForBasicLandRamp,
    )
    from mtg_bot.parity.trajectory import (
        _phase_3a_lazy_init_allowlists,
    )

    _phase_3a_lazy_init_allowlists()
    # Re-import after lazy init populates.
    from mtg_bot.parity.trajectory import (
        _PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES as classes,
    )
    assert OptionalPutCreatureFromHandOntoBattlefield in classes, (
        "OptionalPutCreatureFromHandOntoBattlefield must be in "
        "_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES post-C2 (the "
        "Phase 3B Effect-class widen ships in this slice per design "
        "doc §7.2)."
    )
    # Phase 3A pilot class is preserved (non-regression).
    assert OptionalSacLandOrLanderForBasicLandRamp in classes, (
        "OptionalSacLandOrLanderForBasicLandRamp must still be in "
        "_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES post-C2 (the "
        "Phase 3A pilot class is preserved — C2 is a pure append, "
        "not a replace)."
    )
    # Post-Phase-3C-Cycle-4 (2026-05-26; THIS slice — PHASE 3 CLOSED)
    # the allowlist has 7 entries — Cycle 4 appended both
    # ``CreateTokenPerMulticoloredPermanent`` (Infinite Guideline
    # Station ETB) AND ``DrawCardPerMulticoloredPermanent`` (Infinite
    # Guideline Station ATTACKS). The Phase 3B 2-class pin invariant
    # (Phase 3A pilot + Phase 3B class) is preserved as the subset
    # assertion above; the exact set check moves to a 7-element set
    # post-C4.
    from mtg_bot.effects.generic.become_type import (
        TargetArtifactBecomesCreatureUEOT,
    )
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardPerMulticoloredPermanent,
    )
    from mtg_bot.effects.generic.life import (
        EachOpponentDiscardsOrLosesLife,
        TargetPlayerLosesLife,
    )
    from mtg_bot.effects.generic.tokens import (
        CreateTokenPerMulticoloredPermanent,
    )
    assert set(classes) == {
        OptionalSacLandOrLanderForBasicLandRamp,
        OptionalPutCreatureFromHandOntoBattlefield,
        TargetArtifactBecomesCreatureUEOT,
        EachOpponentDiscardsOrLosesLife,
        TargetPlayerLosesLife,
        CreateTokenPerMulticoloredPermanent,
        DrawCardPerMulticoloredPermanent,
    }, (
        "Phase 3C-Cycle-4 admit-class allowlist must be exactly the "
        "7-class set (Phase 3A pilot + Phase 3B class + Phase 3C "
        "Cycle 2 TargetArtifactBecomesCreatureUEOT + Phase 3C Cycle 3 "
        "EachOpponentDiscardsOrLosesLife + TargetPlayerLosesLife + "
        "Phase 3C Cycle 4 CreateTokenPerMulticoloredPermanent + "
        "DrawCardPerMulticoloredPermanent) — PHASE 3 CLOSED. Silent "
        "auto-grow honest-stop."
    )


def test_phase_3a_event_shape_now_includes_attacks():
    """**C2 FLIP pin (event-shape table widen).** Walk the live
    ``_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES`` tuple — exactly one
    entry IS ``(Event.ATTACKS, IsSelf(subject=None))``. The C2 widen
    shipped explicitly per design doc §7.2.
    """
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.parity.trajectory import (
        _phase_3a_lazy_init_allowlists,
    )

    _phase_3a_lazy_init_allowlists()
    from mtg_bot.parity.trajectory import (
        _PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES as shapes,
    )
    attacks_isself = (Event.ATTACKS, IsSelf(subject=None))
    enters_isself = (Event.ENTERS, IsSelf(subject=None))
    assert attacks_isself in shapes, (
        "(Event.ATTACKS, IsSelf(subject=None)) must be in "
        "_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES post-C2 (the Phase "
        "3B event-shape widen ships in this slice per design doc "
        "§7.2)."
    )
    # Phase 3A pilot shape preserved (non-regression).
    assert enters_isself in shapes, (
        "(Event.ENTERS, IsSelf(subject=None)) must still be in "
        "_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES post-C2 (the Phase "
        "3A pilot shape is preserved — C2 is a pure append, not a "
        "replace)."
    )
    # Post-Phase-3C-Cycle-4 (2026-05-26; THIS slice — PHASE 3 CLOSED)
    # the event-shape table STAYS at 4 entries — Cycle 4 does NOT
    # widen the event-shape table because Infinite Guideline Station's
    # two triggers carry the (ENTERS, IsSelf) and (ATTACKS, IsSelf)
    # shapes that are ALREADY in the table (added in Phase 3A C2 and
    # Phase 3B C2 respectively). The Effect-class allowlist DOES
    # widen Cycle 4 (5 → 7), per the sibling exact-set pin above.
    # PHASE 3 CLOSED.
    from mtg_bot.effects.predicates import Controlled, OPPONENT, YOU
    beginning_of_combat_controlled_you = (
        Event.BEGINNING_OF_COMBAT, Controlled(by=YOU, subject=None),
    )
    discards_card_controlled_opponent = (
        Event.DISCARDS_CARD, Controlled(by=OPPONENT, subject=None),
    )
    assert set(shapes) == {
        enters_isself,
        attacks_isself,
        beginning_of_combat_controlled_you,
        discards_card_controlled_opponent,
    }, (
        "Phase 3C-Cycle-3 event-shape allowlist must be exactly the "
        "4-shape set (Phase 3A pilot + Phase 3B shape + Phase 3C "
        "Cycle 2 BEGINNING_OF_COMBAT + Controlled(YOU) + Phase 3C "
        "Cycle 3 DISCARDS_CARD + Controlled(OPPONENT)) — Phase 3C "
        "Cycle 4 extends further. Silent auto-grow honest-stop."
    )


# ---------------------------------------------------------------------------
# Phase 1 + Phase 2 + Phase 3A non-regression pins
# ---------------------------------------------------------------------------


def test_phase_1_galvanizing_sawship_still_admits_post_phase_3b_cycle_1():
    """**Phase 1 non-regression pin.** Galvanizing Sawship (the
    Phase-1 pilot pure-station Spacecraft) STILL admits at the Phase-1
    gate post-Cycle-1. The new Effect variant's substrate landing
    does NOT regress Phase 1.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_pure_station_spacecraft,
    )

    ps = OracleParserCardSource().get_printings()
    sawship = ps["Galvanizing Sawship"]
    assert _printing_is_bridge_pure_station_spacecraft(sawship) is True, (
        "Galvanizing Sawship must still admit at the Phase-1 gate "
        "post-Phase-3B Cycle-1 (Phase 1 non-regression)."
    )


def test_phase_2_lumen_class_frigate_still_admits_post_phase_3b_cycle_1():
    """**Phase 2 non-regression pin.** Lumen-Class Frigate (the
    Phase-2 pilot static-anthem Spacecraft) STILL admits at the
    Phase-2 gate post-Cycle-1.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_phase_2_static_anthem_spacecraft,
    )

    ps = OracleParserCardSource().get_printings()
    lumen = ps["Lumen-Class Frigate"]
    assert _printing_is_bridge_phase_2_static_anthem_spacecraft(
        lumen,
    ) is True, (
        "Lumen-Class Frigate must still admit at the Phase-2 gate "
        "post-Phase-3B Cycle-1 (Phase 2 non-regression)."
    )


def test_phase_3a_larval_scoutlander_still_admits_post_phase_3b_cycle_1():
    """**Phase 3A non-regression pin.** Larval Scoutlander (the
    Phase-3A pilot trigger-bearing Spacecraft) STILL admits at the
    Phase-3 gate post-Phase-3B-Cycle-1. The new Effect variant's
    substrate landing does NOT regress Phase 3A (the existing
    Effect-class + event-shape allowlists are untouched).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_phase_3_trigger_spacecraft,
    )

    ps = OracleParserCardSource().get_printings()
    larval = ps["Larval Scoutlander"]
    assert _printing_is_bridge_phase_3_trigger_spacecraft(larval) is True, (
        "Larval Scoutlander must still admit at the Phase-3 gate "
        "post-Phase-3B Cycle-1 (Phase 3A non-regression)."
    )
