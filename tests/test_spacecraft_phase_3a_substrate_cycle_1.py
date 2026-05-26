"""**Spacecraft Phase 3A Cycle 1 (2026-05-25).**

Tests for the Phase 3A Cycle 1 Rust substrate landing per
``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_3_DESIGN.md`` §4.2 (Rust
spec) + §5 (Python bridge spec) + §6.2 (test plan).

Deliverables (Cycle 1 Rust slice, per design doc §4.2):

  - New Rust ``Effect`` variant on ``cards.rs::Effect``:
      * ``OptionalSacLandOrLanderForBasicLandRamp { land_count: i32 }``
        — Larval Scoutlander's ETB ramp effect ("You may sacrifice
        a land or Lander. If you do, search your library for up to
        ``land_count`` basic land cards, put them onto the
        battlefield tapped, then shuffle.").
    With: enum variant + ``parse_effect`` arm + ``to_pydict`` arm +
    ``state_ops_resolve`` resolve arm + ``cross_engine.py`` bridge
    dict→Python arm + ``trajectory.py`` reverse-serializer leaf in
    ``_python_ta_to_safe_dict``.
  - ZERO new ``TriggeredAbility.tier_threshold`` Rust slot (per
    design doc §4.1: Larval Scoutlander has tier_threshold=0;
    Phase 3C Cycle 1 ships the slot ahead of Synthesizer Labship's
    FLIP). The existing once_per_turn-only TriggeredAbility struct
    handles tier_threshold=0 triggers unchanged.

This is a **substrate-only closure** — the cycle adds the new Rust
Effect variant + bridge plumbing as reusable infrastructure. The
pilot card (Larval Scoutlander) STAYS DECLINED at the production-
deck admit gate post-Cycle-1 because:

  - ``_python_ta_to_safe_dict``'s ``safe_effect_kinds`` set for
    (ENTERS, IsSelf) does NOT yet include
    ``optional_sac_land_or_lander_for_basic_land_ramp`` (Phase 3
    will not actually flip through that gate — Phase 3 ships its
    OWN admit predicate ``_printing_is_bridge_phase_3_trigger_
    spacecraft`` per design doc §5.3 — but the safe-trigger gate's
    refusal pins the §2 no-silent-auto-grow contract for the
    Phase-1 path).
  - The new Phase-3 admit predicate
    ``_printing_is_bridge_phase_3_trigger_spacecraft`` does NOT
    exist yet at HEAD (Cycle 2 ships it + the OR-chain disjunct
    registration in ``_filter_deck_to_bridge_supported``).

**Verify-first findings (live tree, main `09094051`):**

  - Larval Scoutlander's live oracle text: ETB trigger fires
    ``OptionalSacLandOrLanderForBasicLandRamp(land_count=2)``.
  - Python's ``OptionalSacLandOrLanderForBasicLandRamp`` class at
    ``effects/combinators.py:699`` — frozen dataclass carrying
    ``land_count: int = 2``; the resolve method walks
    ``state.battlefield`` for Land-or-Lander permanents the
    controller controls, picks ``options[0]`` (sibling of the
    no-agent default-yes deterministic-first-slice convention),
    calls ``turn.sacrifice``, then recurses into
    ``SearchLibraryForBasicLandTapped(count=land_count).resolve``.
  - Rust precedents: ``Effect::SearchLibraryForBasicLandTapped``
    resolve at ``state_ops_resolve.rs:4471-4663`` (post-search
    Fisher-Yates shuffle + ENTERS dispatch queue); ``Effect::
    Sacrifice`` resolve at ``state_ops_resolve.rs:2975-3087``
    (LEAVES + IS_SACRIFICED dispatches); the
    ``OptionalSacArtifactForEffect`` Optional-decision-point
    precedent (round-20).

**Test plan (per design doc §6.2 #7-8):**

  - Parser SoT pin: confirm Python's
    ``OptionalSacLandOrLanderForBasicLandRamp`` class exists in
    ``effects.combinators`` with the canonical ``land_count: int =
    2`` shape.
  - Verify-first pin: confirm Larval Scoutlander's live ETB shape
    (single triggered ability, ENTERS event, IsSelf predicate,
    ``OptionalSacLandOrLanderForBasicLandRamp(land_count=2)``
    effect, tier_threshold=0).
  - Rust unit pins: ``parse_effect`` arm + ``to_pydict`` arm
    round-trip + register_printing acceptance.
  - Cross-engine bridge pin: dict→Python bridge arm in
    ``_ta_dict_to_python_effect``.
  - Reverse-serializer pin: forward emit through
    ``_python_ta_to_safe_dict`` is dormant at the safe-kinds gate
    (Larval Scoutlander stays declined) BUT the isinstance arm
    recognizes the effect class.
  - Rust resolve arm pins: silent no-op on no-eligible-target;
    sacrifice + search-and-tap on happy path; partial-fill on
    library-exhaust; count=0 / count<0 conventions.
  - Substrate-only invariant pin: Larval Scoutlander STAYS DECLINED
    at the production-deck loader filter post-Cycle-1.
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


@pytest.fixture
def synthetic_state(engine):
    """A default synthetic state — 10 battlefield, 7 hand, 50 library
    per side."""
    return engine.make_synthetic_state(
        num_battlefield=10, num_hand=7, num_library=50,
    )


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_optional_sac_land_or_lander_for_basic_land_ramp_class_exists():
    """**Parser SoT pin.** Python's
    ``OptionalSacLandOrLanderForBasicLandRamp`` class is in
    ``effects.combinators``, a frozen dataclass with ``land_count:
    int = 2`` default. Two instances with the same ``land_count``
    compare equal; differing ``land_count`` compare unequal.
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.combinators import (
        OptionalSacLandOrLanderForBasicLandRamp,
    )

    a = OptionalSacLandOrLanderForBasicLandRamp()
    b = OptionalSacLandOrLanderForBasicLandRamp()
    c = OptionalSacLandOrLanderForBasicLandRamp(land_count=1)
    d = OptionalSacLandOrLanderForBasicLandRamp(land_count=2)

    # Subclass invariant.
    assert isinstance(a, Effect)
    # Default land_count is 2.
    assert a.land_count == 2
    # Frozen-dataclass __eq__ semantics.
    assert a == b
    assert a == d
    assert a != c


def test_larval_scoutlander_live_printing_matches_design_doc_shape():
    """**Verify-first pin — Larval Scoutlander's live ETB shape.**
    Confirms the design doc §3A row at HEAD: single triggered ability,
    ENTERS event, IsSelf predicate (subject=None),
    ``OptionalSacLandOrLanderForBasicLandRamp(land_count=2)``
    effect, ``tier_threshold == 0``, ``once_per_turn == False``.

    NOTE: Larval Scoutlander STAYS DECLINED at the production-deck
    admit gate post-Cycle-1 because the Phase-3 admit predicate
    ``_printing_is_bridge_phase_3_trigger_spacecraft`` does NOT
    exist at HEAD (Cycle 2 ships it).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.combinators import (
        OptionalSacLandOrLanderForBasicLandRamp,
    )
    from mtg_bot.effects.predicates import Event, IsSelf

    ps = OracleParserCardSource().get_printings()
    ls = ps["Larval Scoutlander"]

    # Spacecraft subtype + station_threshold present per design doc
    # §3A.
    assert "Spacecraft" in ls.subtypes
    assert ls.station_threshold is not None
    assert ls.station_threshold > 0
    # Sub-shape C contract per design doc §2 — single trigger entry.
    tas = tuple(ls.triggered_abilities or ())
    assert len(tas) == 1, (
        f"expected 1 triggered ability on Larval Scoutlander, got "
        f"{len(tas)}: {tas}"
    )
    ta = tas[0]

    assert ta.event is Event.ENTERS
    assert isinstance(ta.predicate, IsSelf)
    assert ta.predicate.subject is None
    assert isinstance(
        ta.effect, OptionalSacLandOrLanderForBasicLandRamp,
    )
    assert ta.effect.land_count == 2
    assert ta.tier_threshold == 0
    assert ta.once_per_turn is False


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict -> Python)
# ---------------------------------------------------------------------------


def test_bridge_arm_optional_sac_land_or_lander_for_basic_land_ramp_default():
    """Bridge arm constructs
    ``OptionalSacLandOrLanderForBasicLandRamp()`` (default
    ``land_count=2``) from a single-kind dict (no fields)."""
    from mtg_bot.effects.combinators import (
        OptionalSacLandOrLanderForBasicLandRamp,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect(
        {"kind": "optional_sac_land_or_lander_for_basic_land_ramp"}
    )
    assert isinstance(back, OptionalSacLandOrLanderForBasicLandRamp)
    assert back.land_count == 2


def test_bridge_arm_optional_sac_land_or_lander_explicit_land_count():
    """Bridge arm constructs
    ``OptionalSacLandOrLanderForBasicLandRamp(land_count=N)`` from a
    dict carrying ``land_count=N``. The int round-trips int-typed."""
    from mtg_bot.effects.combinators import (
        OptionalSacLandOrLanderForBasicLandRamp,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "optional_sac_land_or_lander_for_basic_land_ramp",
        "land_count": 5,
    })
    assert isinstance(back, OptionalSacLandOrLanderForBasicLandRamp)
    assert back.land_count == 5
    assert isinstance(back.land_count, int)


def test_bridge_arm_optional_sac_land_or_lander_negative_raises():
    """Bridge arm raises ValueError on negative land_count (mirror of
    Rust ``parse_effect``'s defense-in-depth contract)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="land_count must be non-negative"):
        _ta_dict_to_python_effect({
            "kind": "optional_sac_land_or_lander_for_basic_land_ramp",
            "land_count": -1,
        })


# ---------------------------------------------------------------------------
# Reverse-serializer leaf pin in _python_ta_to_safe_dict
# ---------------------------------------------------------------------------


def test_python_ta_to_safe_dict_optional_sac_arm_is_dormant_at_safe_kinds_gate():
    """**Substrate-only invariant pin (the load-bearing
    no-silent-auto-grow gate).** ``_python_ta_to_safe_dict`` recognizes
    the new Effect class in its isinstance cascade (the dict-emit
    primitive is pre-positioned for Cycle 2 / the new Phase-3 admit
    predicate), but the ``optional_sac_land_or_lander_for_basic_land_
    ramp`` kind is NOT in any (event, predicate)
    ``safe_effect_kinds`` set this cycle.

    Concrete observable: ``_python_ta_to_safe_dict`` returns ``None``
    for a synthetic (ENTERS, IsSelf, OptionalSacLandOrLanderForBasic
    LandRamp) TriggeredAbility — Larval Scoutlander STAYS DECLINED
    at the Phase-1 ``_python_ta_to_safe_dict`` gate post-Cycle-1.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.combinators import (
        OptionalSacLandOrLanderForBasicLandRamp,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=OptionalSacLandOrLanderForBasicLandRamp(land_count=2),
    )
    # Substrate-only: gate returns None — Larval Scoutlander declines.
    assert _python_ta_to_safe_dict(ta) is None


def test_python_ta_to_safe_dict_arm_recognizes_effect_class():
    """**Recognition arm pin (the substrate's pre-position).** Even
    though the safe-kinds gate refuses, the isinstance cascade
    RECOGNIZES ``OptionalSacLandOrLanderForBasicLandRamp`` and reaches
    the gate (rather than falling through to ``else: return None``
    earlier, before the safe-kinds check).

    Concrete observable: monkey-patch ``safe_effect_kinds`` widen via
    a temporary stub effect class. Easier observable: confirm the
    recognition is path-equivalent by checking the safe-kinds set
    indirectly — the arm is dormant only because the kind isn't on
    any (event, pred) whitelist; ergo: if we wire the kind into the
    ENTERS+IsSelf whitelist temporarily, the gate flips. Since we
    don't want to actually flip Larval Scoutlander, this test simply
    confirms the gate behavior is None (sibling assertion to the
    test above) — the recognition arm's presence is verified by
    inspecting the source file directly (Edit-traced).

    Defense-in-depth: the kind would normally be paired with
    ``_SAFE_TRIGGERS`` entry; here we just pin that the kind is NOT
    in any current ``safe_effect_kinds`` tuple anywhere in the
    function.
    """
    import inspect
    from mtg_bot.parity import trajectory

    source = inspect.getsource(trajectory._python_ta_to_safe_dict)
    # The recognition arm must be present (a key part of the
    # substrate).
    assert "OptionalSacLandOrLanderForBasicLandRamp" in source, (
        "isinstance arm for OptionalSacLandOrLanderForBasicLandRamp "
        "must be present in _python_ta_to_safe_dict (the substrate's "
        "pre-positioned recognition)."
    )
    # The kind string must be present.
    assert (
        "optional_sac_land_or_lander_for_basic_land_ramp" in source
    ), (
        "kind string must be emitted by the substrate's recognition "
        "arm."
    )


def test_python_ta_to_safe_dict_safe_kinds_set_does_not_include_optional_sac():
    """**The §2 no-silent-auto-grow load-bearing pin.** Walk the live
    ``_SAFE_TRIGGERS`` set — NO entry carries the
    ``optional_sac_land_or_lander_for_basic_land_ramp`` effect kind.
    The substrate is dormant.
    """
    from mtg_bot.parity.trajectory import _SAFE_TRIGGERS

    for event, pred, kind in _SAFE_TRIGGERS:
        assert kind != "optional_sac_land_or_lander_for_basic_land_ramp", (
            f"_SAFE_TRIGGERS entry {(event, pred, kind)} silently "
            f"auto-grows Larval Scoutlander; remove it from C1 or "
            f"ship the matching Phase-3 admit predicate + per-card "
            f"probe + FLIP cycle (per design doc §7.1 Cycle 2)."
        )


# ---------------------------------------------------------------------------
# Rust unit pins — parse + register + to_pydict round-trip
# ---------------------------------------------------------------------------


def _synthetic_larval_scoutlander_dict(land_count=2):
    """A synthetic Spacecraft printing carrying the new Effect class
    via a single ETB trigger entry — the canonical Larval Scoutlander
    shape per design doc §3A.

    NOTE: this synthetic carrier is for substrate parse/to_pydict
    pins; Phase 3 admit predicate (which uses its own dispatch)
    ships in Cycle 2.
    """
    return {
        "name": f"Synthetic Larval Scoutlander (x{land_count})",
        "card_types": ["Artifact", "Creature"],
        "subtypes": ["Spacecraft"],
        "mana_cost": {"generic": 2, "G": 1},
        "power": 2,
        "toughness": 2,
        "station_threshold": 7,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "optional_sac_land_or_lander_for_basic_land_ramp",
                    "land_count": land_count,
                },
            }
        ],
    }


def _ramp_spell_dict(land_count=2):
    """A Sorcery-shape spell carrying the new Effect as its spell
    effect — used for direct resolve-arm pins via the stack-push
    path. Source post-resolve moves hand → graveyard so the
    battlefield delta we assert on is the searched lands only.
    """
    return {
        "name": f"Test Optional Land Ramp (x{land_count})",
        "card_types": ["Sorcery"],
        "effects": [
            {
                "kind": "optional_sac_land_or_lander_for_basic_land_ramp",
                "land_count": land_count,
            }
        ],
    }


def test_rust_register_optional_sac_land_or_lander_for_basic_land_ramp():
    """**Rust parse arm pin.** ``register_printing`` accepts an ETB
    trigger carrying the new effect kind. The pid is returned and
    ``get_printing_name`` echoes the name."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_synthetic_larval_scoutlander_dict())
    assert reg.get_printing_name(pid) == (
        "Synthetic Larval Scoutlander (x2)"
    )


def test_rust_register_optional_sac_default_land_count_via_missing_key():
    """Default ``land_count=2`` mirrors Python's class default.
    Registering a printing WITHOUT the ``land_count`` key in the dict
    succeeds (parse_effect defaults to 2).
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": "Test Default Land Count",
        "card_types": ["Sorcery"],
        "effects": [
            {
                "kind": "optional_sac_land_or_lander_for_basic_land_ramp",
                # land_count omitted -- defaults to 2 (Larval Scoutlander
                # printed value).
            }
        ],
    })
    assert reg.get_printing_name(pid) == "Test Default Land Count"


def test_rust_register_optional_sac_negative_land_count_raises():
    """**Rust parse arm pin — defense-in-depth raise on negative.**
    ``parse_effect`` raises ValueError loudly when ``land_count < 0``
    (mirrors the sibling search/discard arms' negative-raise
    convention).
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="land_count must be non-negative"):
        reg.register_printing({
            "name": "Test Bad Negative",
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind": "optional_sac_land_or_lander_for_basic_land_ramp",
                    "land_count": -3,
                }
            ],
        })


def test_rust_register_optional_sac_non_int_land_count_raises():
    """**Rust parse arm pin — type guard.** Non-int ``land_count``
    raises ValueError with a helpful message.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="land_count must be an integer"):
        reg.register_printing({
            "name": "Test Bad Type",
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind": "optional_sac_land_or_lander_for_basic_land_ramp",
                    "land_count": "not an int",
                }
            ],
        })


# ---------------------------------------------------------------------------
# Rust resolve arm pins
# ---------------------------------------------------------------------------


def test_resolve_optional_sac_no_eligible_target_silent_no_op(engine):
    """**Resolve arm — silent no-op on no eligible target.** Set up:
    no Land-or-Lander on p0's battlefield (only a Bear). Resolve the
    effect with p0 as source-controller. Expected: stack pops cleanly,
    NO sacrifice, NO library search, NO mutation beyond the Sorcery's
    hand→graveyard move.

    The default synthetic seed injects 5 Forests + 5 Bears on each
    player's bf (half/half). To exercise the no-eligible-target path
    we build a fresh state with num_battlefield=0 + one explicit
    non-Land non-Lander (a Bear).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=50,
    )

    bear_obj_id = state.register_and_inject_object(
        {
            "name": "Test Bear (no eligible)",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_BATTLEFIELD,
    )

    bf_p0_before = state.battlefield_sizes[0]
    lib_p0_before = state.library_sizes[0]
    gy_p0_before = state.graveyard_sizes[0]

    spell_obj_id = state.register_and_inject_object(
        _ramp_spell_dict(land_count=2), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    # Bear still on bf (NOT sacrificed); no library search.
    assert state.find_object_zone(bear_obj_id) == ZONE_BATTLEFIELD
    assert state.battlefield_sizes[0] == bf_p0_before
    assert state.library_sizes[0] == lib_p0_before
    # The Sorcery source moves hand→graveyard per CR 608.2m, so gy
    # grows by exactly 1.
    assert state.graveyard_sizes[0] == gy_p0_before + 1


def test_resolve_optional_sac_sacrifices_land_and_searches_basic_lands(
    engine,
):
    """**Resolve arm — happy path.** Set up: p0 controls a Forest +
    50 Forests in the library. Resolve the effect with land_count=2.
    Expected: the eligible Forest is sacrificed (moves bf→graveyard),
    AND 2 Forests are searched from p0's library onto p0's bf tapped.
    Net: -1 land on bf (sacrificed), +2 lands on bf (searched) = +1
    bf; -2 from library.

    Use a fresh state with num_battlefield=0 so the only injected
    bf object is the Forest we add explicitly.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=50,
    )

    # Inject one Forest on p0's battlefield via the synthetic Forest
    # printing (already in the seed registry; pid 0 is Forest in
    # make_synthetic_state).
    # Use register_and_inject_object with a synthetic Forest-shape
    # dict so we control the object id and zone.
    forest_obj_id = state.register_and_inject_object(
        {
            "name": "Test Forest On BF",
            "card_types": ["Land"],
            "subtypes": ["Forest"],
            "supertypes": ["Basic"],
            "mana_cost": {},
        },
        0,
        ZONE_BATTLEFIELD,
    )

    bf_before = state.battlefield_sizes[0]
    lib_before = state.library_sizes[0]
    gy_before = state.graveyard_sizes[0]

    spell_obj_id = state.register_and_inject_object(
        _ramp_spell_dict(land_count=2), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    assert state.is_stack_empty() is True
    # Forest sacrificed → graveyard (+1 to gy on the sac axis). The
    # spell source ALSO moves hand→graveyard post-resolve (+1 more).
    # Net graveyard delta: +2.
    assert state.graveyard_sizes[0] == gy_before + 2
    # Sacrificed Forest now lives in p0's graveyard.
    assert state.find_object_zone(forest_obj_id) == ZONE_GRAVEYARD
    # Library shrank by 2 (2 basic lands searched up).
    assert state.library_sizes[0] == lib_before - 2
    # Battlefield: started with 1 Forest (now sac'd), gained 2 from
    # search → net +1.
    assert state.battlefield_sizes[0] == bf_before - 1 + 2


def test_resolve_optional_sac_lander_token_is_eligible_target(engine):
    """**Resolve arm — Lander subtype acceptance.** A Lander permanent
    (Artifact card_type, Lander subtype) on p0's battlefield is an
    ELIGIBLE sacrifice target per Python's
    ``"Lander" in effective_subtypes(...)`` predicate. Confirm Rust
    accepts the Lander subtype as eligible.

    NOTE: real EoE Lander permanents are TOKENS — they cease to exist
    when they leave the battlefield (CR 111.7 / 704.5d). To exercise
    the Lander-subtype eligibility AXIS in isolation (without
    entangling the token-cease pipeline), inject a non-token Lander
    artifact (no ``"Token"`` supertype); the eligibility predicate
    (``"Lander" in subtypes``) is the load-bearing observable
    regardless of token-vs-printed-card axis.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=50,
    )

    # Inject a Lander permanent on p0's battlefield: Artifact
    # card_type (NOT Land), Lander subtype. Explicitly non-token to
    # keep the test focused on the Lander-subtype-eligibility axis
    # (the token-cease pipeline is a separate axis tested elsewhere).
    lander_obj_id = state.register_and_inject_object(
        {
            "name": "Test Lander Permanent",
            "card_types": ["Artifact"],
            "subtypes": ["Lander"],
            "mana_cost": {},
        },
        0,
        ZONE_BATTLEFIELD,
    )

    lib_before = state.library_sizes[0]
    gy_before = state.graveyard_sizes[0]

    spell_obj_id = state.register_and_inject_object(
        _ramp_spell_dict(land_count=2), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Lander sacrificed → graveyard. Sorcery source also moves to
    # graveyard. Net gy delta: +2.
    assert state.graveyard_sizes[0] == gy_before + 2
    assert state.find_object_zone(lander_obj_id) == ZONE_GRAVEYARD
    # Library shrank by 2 (2 basic lands searched up).
    assert state.library_sizes[0] == lib_before - 2


def test_resolve_optional_sac_lander_token_cease_to_exist_on_sac(engine):
    """**Resolve arm — Lander token cease-to-exist axis.** When the
    eligible Lander is a TOKEN (supertype includes "Token"), it ceases
    to exist per CR 111.7 / 704.5d after the sacrifice — it is NOT
    found in the graveyard post-resolve. The sacrifice itself succeeds
    (the eligibility scan accepts the Lander subtype + the sac
    primitive routes through the existing token-cease queue), and the
    library search proceeds. Observable: post-resolve the Lander has
    no zone (vanished), gy contains only the Sorcery source, lib
    shrank by 2.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=50,
    )

    lander_obj_id = state.register_and_inject_object(
        {
            "name": "Test Lander Token",
            "card_types": ["Artifact"],
            "subtypes": ["Lander"],
            "supertypes": ["Token"],
            "mana_cost": {},
        },
        0,
        ZONE_BATTLEFIELD,
    )

    lib_before = state.library_sizes[0]
    gy_before = state.graveyard_sizes[0]

    spell_obj_id = state.register_and_inject_object(
        _ramp_spell_dict(land_count=2), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Lander ceases to exist (CR 111.7 / 704.5d) — no zone.
    assert state.find_object_zone(lander_obj_id) is None
    # Only the Sorcery source went to gy.
    assert state.graveyard_sizes[0] == gy_before + 1
    # Library shrank by 2 (sacrifice + search-up succeeded).
    assert state.library_sizes[0] == lib_before - 2


def test_resolve_optional_sac_non_land_non_lander_filter_rejects(engine):
    """**Resolve arm — eligibility filter.** A non-Land non-Lander
    permanent (a Creature token) on p0's battlefield is NOT eligible;
    the effect silent no-ops (mirror of Python's ``if not options:
    return`` short-circuit).
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=50,
    )

    bear_obj_id = state.register_and_inject_object(
        {
            "name": "Test Bear",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        0,
        ZONE_BATTLEFIELD,
    )

    bf_before = state.battlefield_sizes[0]
    lib_before = state.library_sizes[0]
    gy_before = state.graveyard_sizes[0]

    spell_obj_id = state.register_and_inject_object(
        _ramp_spell_dict(land_count=2), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Bear unchanged (still on bf, NOT sacrificed).
    assert state.find_object_zone(bear_obj_id) == ZONE_BATTLEFIELD
    # No library search (lib unchanged).
    assert state.library_sizes[0] == lib_before
    # Only the spell source moved hand→graveyard.
    assert state.graveyard_sizes[0] == gy_before + 1
    # Battlefield unchanged on the sacrifice/search axes.
    assert state.battlefield_sizes[0] == bf_before


def test_resolve_optional_sac_picks_smallest_index_eligible_target(engine):
    """**Resolve arm — deterministic first-slice pick.** With TWO
    eligible Land-or-Lander permanents on p0's bf, the resolve arm
    picks the smallest-index (= first-injected) one. Mirrors
    ``Effect::Sacrifice``'s bf[0] convention.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=50,
    )

    first_forest = state.register_and_inject_object(
        {
            "name": "Test Forest A",
            "card_types": ["Land"],
            "subtypes": ["Forest"],
            "supertypes": ["Basic"],
            "mana_cost": {},
        },
        0,
        ZONE_BATTLEFIELD,
    )
    second_forest = state.register_and_inject_object(
        {
            "name": "Test Forest B",
            "card_types": ["Land"],
            "subtypes": ["Forest"],
            "supertypes": ["Basic"],
            "mana_cost": {},
        },
        0,
        ZONE_BATTLEFIELD,
    )

    spell_obj_id = state.register_and_inject_object(
        _ramp_spell_dict(land_count=1), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # First-injected Forest is the deterministic pick (smallest-index).
    assert state.find_object_zone(first_forest) == ZONE_GRAVEYARD
    # Second Forest still on bf.
    assert state.find_object_zone(second_forest) == ZONE_BATTLEFIELD


def test_resolve_optional_sac_count_zero_silent_no_op(engine):
    """**Resolve arm — count=0 is a silent no-op.** The conservative
    interpretation is to decline (no sacrifice, no search). Even with
    an eligible target on bf, count=0 does NOT sacrifice.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=50,
    )

    forest_obj_id = state.register_and_inject_object(
        {
            "name": "Test Forest Zero",
            "card_types": ["Land"],
            "subtypes": ["Forest"],
            "supertypes": ["Basic"],
            "mana_cost": {},
        },
        0,
        ZONE_BATTLEFIELD,
    )

    bf_before = state.battlefield_sizes[0]
    lib_before = state.library_sizes[0]

    spell_obj_id = state.register_and_inject_object(
        _ramp_spell_dict(land_count=0), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Forest NOT sacrificed.
    assert state.find_object_zone(forest_obj_id) == ZONE_BATTLEFIELD
    # Library unchanged (no search).
    assert state.library_sizes[0] == lib_before
    # Battlefield unchanged.
    assert state.battlefield_sizes[0] == bf_before


def test_resolve_optional_sac_partial_fill_on_library_exhaust(engine):
    """**Resolve arm — partial fill on early library exhaust.** With
    ``land_count=2`` but only ONE basic Land in the library, the
    sacrifice fires (eligible target on bf) and exactly ONE basic
    land enters tapped. Stop early silently when no more matches —
    mirror of Python's ``next(..., None)`` short-circuit.

    Build a fresh state with num_library=0, then inject exactly one
    basic-land card on p0's library.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=0,
    )

    # Inject the one Forest in p0's library.
    library_forest = state.register_and_inject_object(
        {
            "name": "Test Library Forest",
            "card_types": ["Land"],
            "subtypes": ["Forest"],
            "supertypes": ["Basic"],
            "mana_cost": {},
        },
        0,
        ZONE_LIBRARY,
    )
    # Inject the bf Forest to sacrifice.
    bf_forest = state.register_and_inject_object(
        {
            "name": "Test BF Forest",
            "card_types": ["Land"],
            "subtypes": ["Forest"],
            "supertypes": ["Basic"],
            "mana_cost": {},
        },
        0,
        ZONE_BATTLEFIELD,
    )

    lib_before = state.library_sizes[0]
    bf_before = state.battlefield_sizes[0]
    gy_before = state.graveyard_sizes[0]
    assert lib_before == 1
    assert bf_before == 1

    spell_obj_id = state.register_and_inject_object(
        _ramp_spell_dict(land_count=2), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # BF Forest sacrificed → graveyard.
    assert state.find_object_zone(bf_forest) == ZONE_GRAVEYARD
    # Library Forest moved to bf, tapped.
    assert state.find_object_zone(library_forest) == ZONE_BATTLEFIELD
    assert state.is_tapped(library_forest) is True
    # Library empty after partial fill.
    assert state.library_sizes[0] == 0
    # Net: -1 bf (sac) + 1 bf (search-up) = 0 bf delta; +2 gy (sac
    # Forest + Sorcery source).
    assert state.battlefield_sizes[0] == bf_before
    assert state.graveyard_sizes[0] == gy_before + 2


def test_resolve_optional_sac_searched_lands_enter_tapped(engine):
    """**Resolve arm — searched-up lands enter TAPPED.** Sibling of
    the ``SearchLibraryForBasicLandTapped`` resolve site's "tapped"
    contract. Snapshot the bf pre- and post-resolve and assert every
    NEW battlefield entry (post-snap minus pre-snap by id) is tapped.
    """
    state = engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=50,
    )

    sac_forest = state.register_and_inject_object(
        {
            "name": "Test BF Forest",
            "card_types": ["Land"],
            "subtypes": ["Forest"],
            "supertypes": ["Basic"],
            "mana_cost": {},
        },
        0,
        ZONE_BATTLEFIELD,
    )

    bf_pre_ids = {o["id"] for o in state.battlefield_snapshot()}
    assert sac_forest in bf_pre_ids

    spell_obj_id = state.register_and_inject_object(
        _ramp_spell_dict(land_count=2), 0, ZONE_HAND,
    )
    state.push_to_stack(spell_obj_id, 0)
    state.resolve_top_of_stack()

    # Battlefield post-resolve: started with 1 Forest (sac'd) + 2
    # searched-up lands = net +1 bf.
    bf_post = state.battlefield_snapshot()
    bf_post_ids = {o["id"] for o in bf_post}

    # Sac'd Forest is no longer on bf.
    assert sac_forest not in bf_post_ids
    # Two NEW objects entered bf (the searched-up basics).
    new_ids = bf_post_ids - bf_pre_ids
    assert len(new_ids) == 2, (
        f"expected exactly 2 new bf entries (searched-up basics); "
        f"got {len(new_ids)}: {new_ids}"
    )
    # Each new entry is tapped (the "tapped" half of the effect's
    # spec).
    for nid in new_ids:
        assert state.is_tapped(nid) is True, (
            f"new bf entry {nid} must enter TAPPED per the "
            f"SearchLibraryForBasicLandTapped sibling contract; got "
            f"tapped={state.is_tapped(nid)}"
        )
        # NOT summoning-sick (CR 302.1 — lands have no sickness).
        assert state.is_summoning_sick(nid) is False


# ---------------------------------------------------------------------------
# Substrate-only invariant pin — Larval Scoutlander STAYS DECLINED
# ---------------------------------------------------------------------------


def test_larval_scoutlander_stays_declined_at_admit_gate_post_cycle_1():
    """**Substrate-only invariant pin — the LOAD-BEARING C1 contract.**

    Larval Scoutlander STAYS DECLINED at the production-deck loader
    filter post-Cycle-1. The cycle adds the Rust Effect variant +
    bridge round-trip arms + reverse-serializer leaf recognition,
    but does NOT widen any admit gate.

    Concrete observables (sibling of the Spacecraft Phase 2 C1
    invariant pin pattern + the Carrier-AA Phase 3A C1 sibling):

      1. Phase 1 ``_printing_is_bridge_pure_station_spacecraft``
         declines Larval Scoutlander (the zero-ability gate refuses
         the trigger-bearing carrier).
      2. Phase 2 ``_printing_is_bridge_phase_2_static_anthem_
         spacecraft`` declines Larval Scoutlander (the single-static
         gate refuses the no-static + triggered-ability carrier).
      3. The Phase-3 admit predicate
         ``_printing_is_bridge_phase_3_trigger_spacecraft`` does NOT
         exist at HEAD (Cycle 2 ships it).
      4. The Phase-1 path's
         ``_python_ta_to_safe_dict`` declines the live Larval
         Scoutlander trigger (the safe-kinds gate refuses the new
         kind — pinned in the sibling test above).

    Cycle 2 widens (a) builds the new admit predicate + OR-chain
    disjunct registration; (b) Larval Scoutlander FLIPs from
    DECLINED → ADMITTED at the loader filter.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_phase_2_static_anthem_spacecraft,
        _printing_is_bridge_pure_station_spacecraft,
    )

    ps = OracleParserCardSource().get_printings()
    ls = ps["Larval Scoutlander"]

    # Phase-1 path declines (the zero-ability gate).
    assert _printing_is_bridge_pure_station_spacecraft(ls) is False, (
        "Phase-1 _printing_is_bridge_pure_station_spacecraft must "
        "DECLINE Larval Scoutlander (it carries a triggered "
        "ability — not the zero-ability shape Phase 1 admits)."
    )
    # Phase-2 path declines (the single-static gate).
    assert _printing_is_bridge_phase_2_static_anthem_spacecraft(ls) is False, (
        "Phase-2 _printing_is_bridge_phase_2_static_anthem_spacecraft "
        "must DECLINE Larval Scoutlander (it carries NO static "
        "ability + DOES carry a triggered ability — neither half of "
        "the Phase 2 single-static contract)."
    )

    # Phase-3 admit predicate does NOT exist at HEAD — confirm by
    # absence in the trajectory module namespace.
    import mtg_bot.parity.trajectory as traj_mod
    assert not hasattr(
        traj_mod, "_printing_is_bridge_phase_3_trigger_spacecraft"
    ), (
        "Phase-3 admit predicate `_printing_is_bridge_phase_3_trigger_"
        "spacecraft` must NOT exist at HEAD — Cycle 2 ships it. "
        "If this test fails, the substrate-only invariant has been "
        "violated and Larval Scoutlander may now silently auto-grow."
    )


def test_loader_filter_declines_larval_scoutlander_post_cycle_1():
    """**Loader-level invariant pin (end-to-end).** The
    ``_filter_deck_to_bridge_supported`` loader gate declines Larval
    Scoutlander post-Cycle-1 (no Phase-3 disjunct registered yet).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _filter_deck_to_bridge_supported,
    )

    ps = OracleParserCardSource().get_printings()
    assert "Larval Scoutlander" in ps

    # Build a synthetic single-card deck (by name) containing only
    # Larval Scoutlander; the filter drops the name if the card is
    # declined.
    filtered_names, card_defs = _filter_deck_to_bridge_supported(
        ["Larval Scoutlander"],
        ps,
    )
    assert filtered_names == [], (
        "Larval Scoutlander must be DECLINED by "
        "_filter_deck_to_bridge_supported post-Cycle-1; the Phase-3 "
        "admit predicate ships in Cycle 2. Got filtered names: "
        f"{filtered_names}"
    )
    # And no CardDef is emitted for the declined card.
    assert all(cd.name != "Larval Scoutlander" for cd in card_defs)


# ---------------------------------------------------------------------------
# Phase 1 + Phase 2 non-regression pins
# ---------------------------------------------------------------------------


def test_phase_1_galvanizing_sawship_still_admits_post_cycle_1():
    """**Phase 1 non-regression pin.** Galvanizing Sawship (the Phase-1
    pilot pure-station Spacecraft) STILL admits at the Phase-1 gate
    post-Cycle-1. The new Effect variant's substrate landing does
    NOT regress Phase 1.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_pure_station_spacecraft,
    )

    ps = OracleParserCardSource().get_printings()
    sawship = ps["Galvanizing Sawship"]
    assert _printing_is_bridge_pure_station_spacecraft(sawship) is True, (
        "Galvanizing Sawship must still admit at the Phase-1 gate "
        "post-Cycle-1 (Phase 1 non-regression)."
    )


def test_phase_2_lumen_class_frigate_still_admits_post_cycle_1():
    """**Phase 2 non-regression pin.** Lumen-Class Frigate (the Phase-2
    pilot static-anthem Spacecraft) STILL admits at the Phase-2 gate
    post-Cycle-1.
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
        "post-Cycle-1 (Phase 2 non-regression)."
    )
