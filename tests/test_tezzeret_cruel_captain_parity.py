"""Tezzeret, Cruel Captain — per-card real-EoE cross-engine byte-equal
probe (blocked_subsystem_gated → PROBED tier flip).

Tezzeret, Cruel Captain is a ``{3}`` Legendary Planeswalker — Tezzeret
(starting loyalty 4) in the EoE pool. Printed oracle text:

    "Whenever an artifact you control enters, put a loyalty counter on
    Tezzeret."
    "0: Untap target artifact or creature. If it's an artifact
    creature, put a +1/+1 counter on it."
    "−3: Search your library for an artifact card with mana value 1 or
    less, reveal it, put it into your hand, then shuffle."
    "−7: You get an emblem with '...'."

**Scope of this probe (the loyalty-GAIN trigger substrate).** This
module is the load-bearing PROBED-tier flip evidence for Tezzeret,
Cruel Captain — the LAST non-Duskmourn BLOCKED card in the campaign
(non-DSK 314/315 → 315/315 = 100%). It probes the substrate BOTH
engines model end-to-end:

  * the ``is_planeswalker`` / ``loyalty=4`` printing surface,
  * the loyalty-GAIN triggered ability
    (``PutLoyaltyCounterOnSelf(amount=1)``) — both engines now carry
    the matching Effect (Rust ``Effect::PutLoyaltyCounterOnSelf`` +
    parser ``put_loyalty_counter_on_self`` arm + bridge reverse arm;
    Python ``PutLoyaltyCounterOnSelf``), with the ``loyalty_counters``
    GameObject slot snapshot-surfaced + the walker-at-0 SBA on both
    sides.

The probe drives the loyalty-gain effect through BOTH engines'
resolve paths and asserts byte-equal post-resolve loyalty (4 → 5),
plus parser SoT + bridge round-trip byte-equality of the parsed
real-EoE printing's emitted Effect.

**What stays deferred (HONEST-STOP, documented in
docs/SEARCH_LIMITATIONS.md).** The three loyalty-ACTIVATED abilities
(0 / −3 / −7) and the −7 EMBLEM are NOT probed by this module:

  * The PYTHON parser deliberately STRIPS loyalty-activation lines
    (``planeswalker_builder.py`` ``_LOYALTY_ACTIVATION_PREFIX``) —
    Python does not yet model loyalty-ability activation (no
    pay/add-loyalty cost atom, no sorcery-speed once-per-turn-per-
    walker activation gate, no emblem object). RUST already carries
    the full loyalty-COST activation substrate
    (``ActivationCost.loyalty`` signed cost + emission gate +
    ``loyalty_activated_this_turn`` once-per-turn-per-walker ledger +
    SBA), but the asymmetry means a cross-engine activation probe is
    not byte-equal-buildable on the Python side today.
  * The −7 emblem has no emblem-object substrate on either engine.

This is the planeswalker-loyalty-GAIN slice: the loyalty-counter
field + the loyalty-gain trigger + starting-loyalty/SBA are byte-equal
across engines; the loyalty-ABILITY activation + emblem remain
Python-substrate work (see docs/SEARCH_LIMITATIONS.md). A characterized
partial that ships the planeswalker-loyalty-gain substrate is the WIN
per the campaign's honest-stop policy.

The predicate-gated artifact-ETB FIRING path (the real trigger fires
on "an artifact you control enters", a separate trajectory surface) is
deferred per the synthetic-only-when-event-firing-cascades precedent
(Sunstar Lightsmith's IS_CAST firing parallel) — this probe drives the
effect's resolve directly on both engines, the same EEEE-idiom (parse
+ bridge round-trip + per-engine resolve, no full-trajectory event
firing) that PROBED Sunstar Lightsmith / Illvoi Operative.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.counters import PutLoyaltyCounterOnSelf
from mtg_bot.effects.predicates import Event


_PRINTINGS = get_active_source().get_printings()

_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)

# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Tezzeret is parser-claimed and emits the
# Planeswalker(loyalty=4) + ENTERS/PutLoyaltyCounterOnSelf shape.
# ---------------------------------------------------------------------------


def test_tezzeret_parser_claims_card():
    assert "Tezzeret, Cruel Captain" in _PRINTINGS, (
        "Tezzeret, Cruel Captain must be parser-claimed by the active "
        "CardSource"
    )


def test_tezzeret_printed_planeswalker_surface():
    """Pins the basic printing surface: Legendary Planeswalker —
    Tezzeret, {3} cost, loyalty 4, no P/T."""
    p = _PRINTINGS["Tezzeret, Cruel Captain"]
    assert p.is_planeswalker is True
    assert "Planeswalker" in p.card_types
    assert p.is_legendary is True
    assert "Tezzeret" in p.subtypes
    assert p.loyalty == 4
    assert p.mana_cost.generic == 3
    assert p.mana_cost.colored == ()
    assert p.power is None
    assert p.toughness is None


def test_tezzeret_loyalty_gain_trigger_shape():
    """The parsed printing emits exactly one ENTERS triggered ability
    whose effect is ``PutLoyaltyCounterOnSelf(amount=1)`` — the
    loyalty-gain "whenever an artifact you control enters" rider."""
    p = _PRINTINGS["Tezzeret, Cruel Captain"]
    enters_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.ENTERS
    ]
    assert len(enters_tas) == 1, (
        f"Tezzeret must emit exactly 1 ENTERS triggered ability; got "
        f"{len(enters_tas)}"
    )
    (ta,) = enters_tas
    assert isinstance(ta.effect, PutLoyaltyCounterOnSelf), (
        f"ENTERS effect must be PutLoyaltyCounterOnSelf; got "
        f"{type(ta.effect).__name__}"
    )
    assert ta.effect.amount == 1, (
        f"PutLoyaltyCounterOnSelf amount must be 1; got "
        f"{ta.effect.amount}"
    )


def test_tezzeret_loyalty_activated_abilities_shape():
    """The parsed printing now models ALL THREE of Tezzeret's loyalty
    abilities — 0 / −3 / −7. The −7 emblem is now modeled (the emblem
    substrate landed): it emits a ``CreateEmblem`` effect. The emblem's
    begin-combat 3-counter body is byte-equal cross-engine; only the
    "becomes a 0/0 Robot artifact creature" permanent-animate half is
    honest-stopped (see docs/SEARCH_LIMITATIONS.md + emblem.py).

    Each modeled ability carries the signed-loyalty ``ActivationCost``
    + ``sorcery_speed=True`` (CR 606.3 timing). Sign convention: a
    printed ``0:`` stamps ``loyalty=0``; a printed ``−3:`` stamps
    ``loyalty=3`` (pay-loyalty); a printed ``−7:`` stamps
    ``loyalty=7``."""
    from mtg_bot.effects.generic.emblem import (
        TEZZERET_CRUEL_CAPTAIN_EMBLEM,
        CreateEmblem,
    )
    from mtg_bot.effects.generic.search import SearchLibraryForCard
    from mtg_bot.effects.generic.tap import (
        UntapTargetArtifactOrCreatureConditionalCounter,
    )

    p = _PRINTINGS["Tezzeret, Cruel Captain"]
    aas = p.activated_abilities
    assert len(aas) == 3, (
        f"Tezzeret must model exactly 3 loyalty abilities (0 / −3 / −7); "
        f"the −7 emblem is now modeled. Got {len(aas)}"
    )
    # All loyalty abilities are sorcery-speed (CR 606.3).
    assert all(aa.sorcery_speed for aa in aas), (
        "loyalty abilities must be sorcery-speed"
    )

    # The 0 ability — loyalty cost 0, untap-conditional-counter effect.
    zero = next(aa for aa in aas if aa.cost.loyalty == 0)
    assert isinstance(
        zero.effect, UntapTargetArtifactOrCreatureConditionalCounter
    ), (
        f"0 ability effect must be UntapTargetArtifactOrCreature"
        f"ConditionalCounter; got {type(zero.effect).__name__}"
    )

    # The −3 ability — loyalty cost +3 (pay-loyalty), artifact-MV≤1 tutor.
    minus3 = next(aa for aa in aas if aa.cost.loyalty == 3)
    assert isinstance(minus3.effect, SearchLibraryForCard), (
        f"−3 ability effect must be SearchLibraryForCard; got "
        f"{type(minus3.effect).__name__}"
    )
    assert minus3.effect.filter_name == "artifact_small"
    assert minus3.effect.max_mv == 1

    # The −7 ability — loyalty cost +7 (pay-loyalty), CreateEmblem.
    minus7 = next(aa for aa in aas if aa.cost.loyalty == 7)
    assert isinstance(minus7.effect, CreateEmblem), (
        f"−7 ability effect must be CreateEmblem; got "
        f"{type(minus7.effect).__name__}"
    )
    assert minus7.effect.emblem_kind == TEZZERET_CRUEL_CAPTAIN_EMBLEM


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the put_loyalty_counter_on_self dict round-
# trips byte-equal to the parsed printing's emitted Effect.
# ---------------------------------------------------------------------------


def test_tezzeret_bridge_arm_round_trip():
    """The bridge arm ``put_loyalty_counter_on_self`` translates
    ``{"kind": "put_loyalty_counter_on_self", "amount": 1}`` to the
    matching Python ``PutLoyaltyCounterOnSelf(amount=1)``, and that is
    byte-equal to the parsed real-EoE printing's emitted Effect."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "put_loyalty_counter_on_self", "amount": 1}
    )
    assert isinstance(bridged, PutLoyaltyCounterOnSelf)
    assert bridged.amount == 1

    # Default-handling: amount omitted defaults to 1 (mirrors Rust's
    # parse_effect default + Python's dataclass default).
    bridged_default = _ta_dict_to_python_effect(
        {"kind": "put_loyalty_counter_on_self"}
    )
    assert isinstance(bridged_default, PutLoyaltyCounterOnSelf)
    assert bridged_default.amount == 1

    # Negative amount raises on the bridge (mirrors Rust's contract).
    with pytest.raises(ValueError, match=r"must be non-negative"):
        _ta_dict_to_python_effect(
            {"kind": "put_loyalty_counter_on_self", "amount": -1}
        )

    # Effect-level byte-equality between the parsed real-EoE printing's
    # emitted Effect and the bridged Effect — the structural contract
    # for the PROBED tier.
    p = _PRINTINGS["Tezzeret, Cruel Captain"]
    (ta,) = [
        t for t in p.triggered_abilities if t.event is Event.ENTERS
    ]
    assert ta.effect == bridged, (
        "Tezzeret's parsed Effect must be byte-equal to the bridged "
        "Effect (PutLoyaltyCounterOnSelf structural contract)"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged loyalty-gain trigger dict on a Tezzeret-shape Planeswalker
# carrier (simpler ``source_is_self`` predicate — the real
# "artifact you control enters" predicate's firing is its own surface).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_tezzeret_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``{"kind": "put_loyalty_counter_on_self", "amount": 1}`` dict on a
    Tezzeret-shape Planeswalker carrier with a ``starting_loyalty`` 4
    seed and an ENTERS trigger."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Tezzeret, Cruel Captain (synthetic carrier)",
            "card_types": ["Planeswalker"],
            "supertypes": ["Legendary"],
            "subtypes": ["Tezzeret"],
            "mana_cost": {"generic": 3},
            "starting_loyalty": 4,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "put_loyalty_counter_on_self",
                        "amount": 1,
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# loyalty-gain Effect through BOTH engines' resolve paths and asserts
# byte-equal post-resolve loyalty (4 → 5).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_tezzeret_cruel_captain_loyalty_gain_parity():
    """**GENUINE real-EoE cross-engine probe — Tezzeret, Cruel Captain
    loyalty-gain ENTERS → PutLoyaltyCounterOnSelf(1). PROBED-tier flip
    (blocked_subsystem_gated → PROBED).**

    Drives the loyalty-GAIN effect through BOTH engines:

      * **Python:** seats the GENUINE parsed Tezzeret printing on p0's
        battlefield with ``loyalty_counters=4`` (the printed starting
        loyalty), sets ``resolving_source`` and resolves the parsed
        ENTERS effect → asserts ``loyalty_counters == 5``.
      * **Rust:** registers a Tezzeret-shape Planeswalker carrier with
        ``starting_loyalty=4`` + the bridged
        ``put_loyalty_counter_on_self`` ENTERS trigger, baselines
        loyalty to 4 via ``set_loyalty_counters`` (matching Python's
        printed seed), resolves the auto-pushed ENTERS trigger →
        asserts ``get_loyalty_counters == 5``.

    Both engines produce the byte-equal observable: loyalty 4 → 5.

    Also pins parser SoT + bridge round-trip byte-equality (the parsed
    real-EoE Effect == the bridged Effect), so the cross-engine
    equality is anchored on the ACTUAL parsed printing, not a synthetic
    stand-in.

    **Deferred (HONEST-STOP):** the three loyalty-ACTIVATED abilities
    (0/−3/−7) + the −7 emblem are out of scope — Python does not model
    loyalty-ability activation (parser strips the lines) and no emblem
    substrate exists on either engine. The predicate-gated
    artifact-ETB firing path is deferred per the synthetic-only-when-
    event-firing-cascades precedent (Sunstar Lightsmith parallel).
    See docs/SEARCH_LIMITATIONS.md.
    """
    import mtg_bot_engine  # noqa: F401  (gated by _rust_skip)

    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Tezzeret printing + its loyalty-gain
    #    ENTERS trigger.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Tezzeret, Cruel Captain")
    if real is None:
        pytest.skip("Tezzeret, Cruel Captain absent from active CardSource")
    assert real.is_planeswalker is True
    assert real.loyalty == 4
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Tezzeret must have an ENTERS triggered ability"
    )
    assert isinstance(enters_ta.effect, PutLoyaltyCounterOnSelf)

    # ------------------------------------------------------------------
    # 2. Bridge round-trip: Rust kind dict -> Python Effect, byte-equal
    #    to the parsed real-EoE emission.
    # ------------------------------------------------------------------
    bridged = _ta_dict_to_python_effect(
        {"kind": "put_loyalty_counter_on_self", "amount": 1}
    )
    assert isinstance(bridged, PutLoyaltyCounterOnSelf)
    assert enters_ta.effect == bridged, (
        f"Tezzeret parsed Effect must be byte-equal to bridged; got "
        f"parsed={enters_ta.effect!r}, bridged={bridged!r}"
    )

    # ------------------------------------------------------------------
    # 3. PYTHON-side resolve — seat the GENUINE parsed Tezzeret on p0's
    #    bf with loyalty 4, resolve the parsed loyalty-gain effect.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    py_walker = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD
    )
    py_walker.loyalty_counters = 4  # printed starting loyalty
    py_walker.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_walker)

    assert py_walker.loyalty_counters == 4
    py_state.resolving_source = py_walker
    enters_ta.effect.resolve(py_state, py_walker.controller_id)
    assert py_walker.loyalty_counters == 5, (
        f"Python: Tezzeret loyalty-gain must grow loyalty 4 -> 5; got "
        f"{py_walker.loyalty_counters}"
    )

    # ------------------------------------------------------------------
    # 4. RUST-side resolve — register a Tezzeret-shape Planeswalker
    #    carrier, baseline loyalty to 4, resolve the auto-pushed ENTERS
    #    trigger.
    # ------------------------------------------------------------------
    rust_state = build_rust_state(spec)
    walker_id = rust_state.register_and_inject_object(
        {
            "name": "Tezzeret, Cruel Captain",
            "card_types": ["Planeswalker"],
            "supertypes": ["Legendary"],
            "subtypes": ["Tezzeret"],
            "mana_cost": {"generic": 3},
            "starting_loyalty": 4,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "put_loyalty_counter_on_self",
                        "amount": 1,
                    },
                },
            ],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    # Baseline loyalty to the printed starting loyalty (4), matching
    # Python's seed. ``register_and_inject_object`` does NOT seed
    # ``starting_loyalty`` (the ETB-seed helper runs on the cast/resolve
    # path, not raw inject), so we stamp it explicitly.
    rust_state.set_loyalty_counters(walker_id, 4)
    assert rust_state.get_loyalty_counters(walker_id) == 4

    # Resolve the auto-pushed self-ENTERS loyalty-gain trigger.
    assert rust_state.stack_size() == 1
    rust_state.resolve_top_of_stack()
    assert rust_state.stack_size() == 0
    rust_loyalty = rust_state.get_loyalty_counters(walker_id)
    assert rust_loyalty == 5, (
        f"Rust: Tezzeret loyalty-gain must grow loyalty 4 -> 5; got "
        f"{rust_loyalty}"
    )

    # ------------------------------------------------------------------
    # 5. CROSS-ENGINE byte-equality — both engines land on loyalty 5.
    # ------------------------------------------------------------------
    assert py_walker.loyalty_counters == rust_loyalty == 5, (
        f"Cross-engine loyalty must be byte-equal (both 5); got "
        f"python={py_walker.loyalty_counters}, rust={rust_loyalty}"
    )


# ---------------------------------------------------------------------------
# ZONE_LIBRARY constant (mirrors Rust's u8 zone IDs) used by the
# loyalty-activation probes below.
# ---------------------------------------------------------------------------
ZONE_LIBRARY = 1


# ---------------------------------------------------------------------------
# (5) Loyalty-activation subsystem — Stage 1. The signed-loyalty
# ``ActivationCost`` cost atom round-trips byte-equal cross-engine via the
# bridge, and the once-per-turn-per-walker + sorcery-speed activation gate
# behave identically on both engines.
# ---------------------------------------------------------------------------


def test_loyalty_cost_bridge_round_trip():
    """The activation-cost bridge translates a signed ``loyalty`` int
    byte-equal to the Python ``ActivationCost.loyalty`` field, and the
    full activated-ability dict (cost + effect + sorcery_speed) round-
    trips. Mirrors Rust's ``parse_activation_cost`` ``loyalty`` arm."""
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activation_cost,
        _aa_dict_to_python_activated_ability,
    )

    # Pay-loyalty (a "-3" ability stamps loyalty=3).
    assert _aa_dict_to_python_activation_cost({"loyalty": 3}).loyalty == 3
    # Add-loyalty (a "+2" ability stamps loyalty=-2).
    assert _aa_dict_to_python_activation_cost({"loyalty": -2}).loyalty == -2
    # Bare "0" ability.
    assert _aa_dict_to_python_activation_cost({"loyalty": 0}).loyalty == 0
    # Missing key defaults to 0 (no loyalty cost).
    assert _aa_dict_to_python_activation_cost({}).loyalty == 0

    # bool is disallowed (int-subclass guard mirrors Rust's i32 extract).
    with pytest.raises(ValueError, match=r"loyalty must be an int"):
        _aa_dict_to_python_activation_cost({"loyalty": True})

    # Full ability dict round-trip — the -3 search ability.
    aa = _aa_dict_to_python_activated_ability(
        {
            "cost": {"loyalty": 3},
            "sorcery_speed": True,
            "effect": {
                "kind": "search_library_for_card",
                "filter_name": "artifact_small",
                "max_mv": 1,
                "may_fail": True,
            },
        }
    )
    assert aa.cost.loyalty == 3
    assert aa.sorcery_speed is True


@_rust_skip
def test_cross_engine_loyalty_activation_cost_and_once_per_turn_parity():
    """**Cross-engine byte-equal — the loyalty-activation subsystem.**

    Drives a full loyalty-ability activation through BOTH engines'
    activation paths (Python ``_activate_ability`` / Rust
    ``apply_action({"kind": "activate_ability"})``) and asserts:

      * the signed loyalty COST is paid byte-equal (a -3 ability:
        loyalty 4 -> 1 on both engines),
      * the once-per-turn-per-walker gate (CR 606.3) refuses a second
        activation on both engines.

    Uses the -3 search ability (fully deterministic first-match tutor —
    no agent seating required, byte-equal both engines)."""
    import mtg_bot_engine  # noqa: F401

    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.actions import _activate_ability, ActivateAbility
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import Zone
    from mtg_bot.legal import legal_actions

    tezz = get_active_source().get_printings()["Tezzeret, Cruel Captain"]
    minus3_idx = next(
        i for i, aa in enumerate(tezz.activated_abilities)
        if aa.cost.loyalty == 3
    )

    # ---- PYTHON ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    relic = make_artifact("Tiny Relic", "{1}")
    relic_obj = py.new_object(relic, owner_id=0, zone=Zone.LIBRARY)
    py.player_by_id(0).library.append(relic_obj)
    w = py.new_object(tezz, owner_id=0, zone=Zone.BATTLEFIELD)
    w.loyalty_counters = 4
    py.battlefield.append(w)

    class _FetchAgent:
        def choose_card_from_library(self, state, pid, options):
            return options[0]

    py.player_by_id(0).agent = _FetchAgent()
    _activate_ability(py, 0, w.id, minus3_idx)
    assert w.loyalty_counters == 1, (
        f"Python: -3 ability must pay 3 loyalty (4 -> 1); got "
        f"{w.loyalty_counters}"
    )
    assert (0, w.id) in py.loyalty_activated_this_turn, (
        "Python: once-per-turn ledger must record the activation"
    )
    py_legal_aas = [
        a for a in legal_actions(py, 0)
        if isinstance(a, ActivateAbility) and a.source_id == w.id
    ]
    assert py_legal_aas == [], (
        "Python: no loyalty ability may be offered after the walker "
        "activated this turn (CR 606.3) / insufficient loyalty"
    )

    # ---- RUST ----
    rust = build_rust_state(spec)
    rust.register_and_inject_object(
        {
            "name": "Tiny Relic",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "effects": [],
        },
        0,
        ZONE_LIBRARY,
    )
    walker_id = rust.register_and_inject_object(
        {
            "name": "Tezzeret, Cruel Captain",
            "card_types": ["Planeswalker"],
            "supertypes": ["Legendary"],
            "subtypes": ["Tezzeret"],
            "mana_cost": {"generic": 3},
            "starting_loyalty": 4,
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"loyalty": 3},
                    "sorcery_speed": True,
                    "effect": {
                        "kind": "search_library_for_card",
                        "filter_name": "artifact_small",
                        "max_mv": 1,
                        "may_fail": True,
                    },
                },
            ],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    rust.set_loyalty_counters(walker_id, 4)
    rust.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 0,
        }
    )
    assert rust.get_loyalty_counters(walker_id) == 1, (
        f"Rust: -3 ability must pay 3 loyalty (4 -> 1); got "
        f"{rust.get_loyalty_counters(walker_id)}"
    )
    with pytest.raises(ValueError):
        rust.apply_action(
            {
                "kind": "activate_ability",
                "source_id": walker_id,
                "ability_index": 0,
            }
        )

    # ---- CROSS-ENGINE byte-equality ----
    assert w.loyalty_counters == rust.get_loyalty_counters(walker_id) == 1


@_rust_skip
def test_cross_engine_tezzeret_zero_ability_untap_conditional_counter_parity():
    """**Cross-engine byte-equal — Tezzeret's 0 ability.**

    "Untap target artifact or creature. If it's an artifact creature,
    put a +1/+1 counter on it." Seats a single tapped artifact-creature
    on the controller's battlefield (so both engines' deterministic
    target pick lands on the same object), activates the 0 ability,
    resolves it, and asserts byte-equal: target untapped + one +1/+1
    counter; walker loyalty unchanged (0 cost)."""
    import mtg_bot_engine  # noqa: F401

    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.actions import _activate_ability, resolve_top_of_stack
    from mtg_bot.cards.base import make_creature
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import Zone

    tezz = get_active_source().get_printings()["Tezzeret, Cruel Captain"]
    zero_idx = next(
        i for i, aa in enumerate(tezz.activated_abilities)
        if aa.cost.loyalty == 0
    )

    # ---- PYTHON ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    robot = make_creature("Assembly Robot", "{2}", 2, 2, artifact=True)
    ro = py.new_object(robot, owner_id=0, zone=Zone.BATTLEFIELD)
    ro.tapped = True
    py.battlefield.append(ro)
    w = py.new_object(tezz, owner_id=0, zone=Zone.BATTLEFIELD)
    w.loyalty_counters = 4
    py.battlefield.append(w)

    class _TargetAgent:
        def choose_target(self, state, pid, pool):
            return pool[0]

    py.player_by_id(0).agent = _TargetAgent()
    _activate_ability(py, 0, w.id, zero_idx)
    resolve_top_of_stack(py)
    assert ro.tapped is False, "Python: 0 ability must untap the target"
    assert ro.plus_one_counters == 1, (
        f"Python: artifact creature must get a +1/+1 counter; got "
        f"{ro.plus_one_counters}"
    )
    assert w.loyalty_counters == 4, (
        "Python: 0 ability is a 0-loyalty cost (no change)"
    )

    # ---- RUST ----
    rust = build_rust_state(spec)
    robot_id = rust.register_and_inject_object(
        {
            "name": "Assembly Robot",
            "card_types": ["Artifact", "Creature"],
            "mana_cost": {"generic": 2},
            "power": 2,
            "toughness": 2,
            "effects": [],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    rust.tap_object(robot_id)
    walker_id = rust.register_and_inject_object(
        {
            "name": "Tezzeret, Cruel Captain",
            "card_types": ["Planeswalker"],
            "supertypes": ["Legendary"],
            "subtypes": ["Tezzeret"],
            "mana_cost": {"generic": 3},
            "starting_loyalty": 4,
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"loyalty": 0},
                    "sorcery_speed": True,
                    "effect": {
                        "kind": (
                            "untap_target_artifact_or_creature_"
                            "conditional_counter"
                        ),
                    },
                },
            ],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    rust.set_loyalty_counters(walker_id, 4)
    rust.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 0,
        }
    )
    rust.resolve_top_of_stack()
    assert rust.is_tapped(robot_id) is False, (
        "Rust: 0 ability must untap the target"
    )
    assert rust.get_counters(robot_id) == 1, (
        f"Rust: artifact creature must get a +1/+1 counter; got "
        f"{rust.get_counters(robot_id)}"
    )
    assert rust.get_loyalty_counters(walker_id) == 4

    # ---- CROSS-ENGINE byte-equality ----
    assert ro.plus_one_counters == rust.get_counters(robot_id) == 1
    assert ro.tapped == rust.is_tapped(robot_id) is False


@_rust_skip
def test_cross_engine_tezzeret_minus3_search_artifact_parity():
    """**Cross-engine byte-equal — Tezzeret's -3 ability.**

    "Search your library for an artifact card with mana value 1 or
    less, reveal it, put it into your hand, then shuffle." Seats one
    MV-1 artifact in the library; both engines' deterministic
    first-match tutor fetches it to hand. Asserts byte-equal: the
    artifact moves library -> hand, loyalty 4 -> 1."""
    import mtg_bot_engine  # noqa: F401

    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.actions import _activate_ability, resolve_top_of_stack
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import Zone

    tezz = get_active_source().get_printings()["Tezzeret, Cruel Captain"]
    minus3_idx = next(
        i for i, aa in enumerate(tezz.activated_abilities)
        if aa.cost.loyalty == 3
    )

    # ---- PYTHON ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    relic = make_artifact("Tiny Relic", "{1}")
    relic_obj = py.new_object(relic, owner_id=0, zone=Zone.LIBRARY)
    py.player_by_id(0).library.append(relic_obj)
    w = py.new_object(tezz, owner_id=0, zone=Zone.BATTLEFIELD)
    w.loyalty_counters = 4
    py.battlefield.append(w)

    class _FetchAgent:
        def choose_card_from_library(self, state, pid, options):
            return options[0]

    py.player_by_id(0).agent = _FetchAgent()
    hand_before = len(py.player_by_id(0).hand)
    _activate_ability(py, 0, w.id, minus3_idx)
    resolve_top_of_stack(py)
    py_hand = py.player_by_id(0).hand
    assert len(py_hand) == hand_before + 1, (
        "Python: -3 tutor must add the artifact to hand"
    )
    assert any(c.printing.name == "Tiny Relic" for c in py_hand)
    assert w.loyalty_counters == 1

    # ---- RUST ----
    rust = build_rust_state(spec)
    rust.register_and_inject_object(
        {
            "name": "Tiny Relic",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "effects": [],
        },
        0,
        ZONE_LIBRARY,
    )
    walker_id = rust.register_and_inject_object(
        {
            "name": "Tezzeret, Cruel Captain",
            "card_types": ["Planeswalker"],
            "supertypes": ["Legendary"],
            "subtypes": ["Tezzeret"],
            "mana_cost": {"generic": 3},
            "starting_loyalty": 4,
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"loyalty": 3},
                    "sorcery_speed": True,
                    "effect": {
                        "kind": "search_library_for_card",
                        "filter_name": "artifact_small",
                        "max_mv": 1,
                        "may_fail": True,
                    },
                },
            ],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    rust.set_loyalty_counters(walker_id, 4)
    rust_hand_before = rust.hand_sizes[0]
    rust.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 0,
        }
    )
    rust.resolve_top_of_stack()
    assert rust.hand_sizes[0] == rust_hand_before + 1, (
        "Rust: -3 tutor must add the artifact to hand"
    )
    assert rust.get_loyalty_counters(walker_id) == 1

    # ---- CROSS-ENGINE byte-equality ----
    assert (len(py_hand) - hand_before) == (
        rust.hand_sizes[0] - rust_hand_before
    ) == 1
    assert w.loyalty_counters == rust.get_loyalty_counters(walker_id) == 1


# ---------------------------------------------------------------------------
# (6) EMBLEM substrate (CR 114) — Tezzeret's −7 emblem. The command-zone
# emblem object + CreateEmblem effect + the emblem-sourced begin-combat
# trigger + the 3-counter body are byte-equal cross-engine. The
# becomes-0/0-Robot permanent animate is HONEST-STOPPED (no permanent
# layer-4 type-set + layer-7b P/T-set animate substrate — see
# docs/SEARCH_LIMITATIONS.md + effects/generic/emblem.py).
# ---------------------------------------------------------------------------


def test_tezzeret_emblem_effect_bridge_round_trip():
    """The bridge arms ``create_emblem`` / ``tezzeret_emblem_begin_combat``
    translate the Rust effect dicts to the matching Python effects, and
    the parsed real-EoE −7 ability's emitted Effect is byte-equal to the
    bridged ``CreateEmblem``."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.generic.emblem import (
        TEZZERET_CRUEL_CAPTAIN_EMBLEM,
        CreateEmblem,
        TezzeretEmblemBeginCombat,
    )

    bridged = _ta_dict_to_python_effect(
        {"kind": "create_emblem",
         "emblem_kind": TEZZERET_CRUEL_CAPTAIN_EMBLEM}
    )
    assert isinstance(bridged, CreateEmblem)
    assert bridged.emblem_kind == TEZZERET_CRUEL_CAPTAIN_EMBLEM

    # Unknown emblem kind raises on the bridge (mirrors Rust's contract).
    with pytest.raises(ValueError, match=r"unknown emblem kind"):
        _ta_dict_to_python_effect(
            {"kind": "create_emblem", "emblem_kind": "nonexistent"}
        )

    # The begin-combat body bridge — amount defaults to 3, negative raises.
    body = _ta_dict_to_python_effect(
        {"kind": "tezzeret_emblem_begin_combat"}
    )
    assert isinstance(body, TezzeretEmblemBeginCombat)
    assert body.amount == 3
    body3 = _ta_dict_to_python_effect(
        {"kind": "tezzeret_emblem_begin_combat", "amount": 3}
    )
    assert body3.amount == 3
    with pytest.raises(ValueError, match=r"must be non-negative"):
        _ta_dict_to_python_effect(
            {"kind": "tezzeret_emblem_begin_combat", "amount": -1}
        )

    # The parsed real-EoE −7 ability emits a CreateEmblem byte-equal to
    # the bridged one.
    p = _PRINTINGS["Tezzeret, Cruel Captain"]
    minus7 = next(
        aa for aa in p.activated_abilities if aa.cost.loyalty == 7
    )
    assert minus7.effect == bridged, (
        "Tezzeret's parsed −7 Effect must be byte-equal to the bridged "
        "CreateEmblem"
    )


@_rust_skip
def test_cross_engine_tezzeret_minus7_emblem_begin_combat_parity():
    """**Cross-engine byte-equal — Tezzeret's −7 emblem end to end.**

    Drives the full emblem flow through BOTH engines and asserts every
    observable is byte-equal:

      1. **Activate −7** (pay 7 loyalty) → the emblem lands in the
         command zone (CR 114). Both engines: loyalty 7 → 0, exactly one
         emblem in the command zone.
      2. **Begin-combat trigger** fires from the command-zone emblem
         (NOT a battlefield permanent — the dispatch is extended to scan
         the emblem zone on both engines). Both engines push exactly one
         triggered ability.
      3. **Resolve the body** → three +1/+1 counters land on the target
         artifact the controller controls. Both engines: artifact net
         counters 0 → 3.

    **HONEST-STOP (documented, asserted as NOT applied):** the "if it's
    not a creature, it becomes a 0/0 Robot artifact creature" PERMANENT
    layer-4 type-set + layer-7b P/T-set animate is NOT modeled on either
    engine. The artifact stays a non-creature artifact on both engines
    after the trigger resolves — the counters land, the type/P/T change
    does not. See docs/SEARCH_LIMITATIONS.md + effects/generic/emblem.py.
    """
    import mtg_bot_engine  # noqa: F401

    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
    )
    from mtg_bot.actions import (
        _activate_ability,
        dispatch_event,
        resolve_top_of_stack,
    )
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.emblem import CreateEmblem
    from mtg_bot.effects.predicates import Event as _Ev
    from mtg_bot.game import Zone

    tezz = get_active_source().get_printings()["Tezzeret, Cruel Captain"]
    minus7_idx = next(
        i for i, aa in enumerate(tezz.activated_abilities)
        if aa.cost.loyalty == 7
    )
    assert isinstance(
        tezz.activated_abilities[minus7_idx].effect, CreateEmblem
    )

    # ---- PYTHON ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    # An artifact (non-creature) the controller controls.
    relic = make_artifact("Doohickey", "{2}")
    ao = py.new_object(relic, owner_id=0, zone=Zone.BATTLEFIELD)
    py.battlefield.append(ao)
    w = py.new_object(tezz, owner_id=0, zone=Zone.BATTLEFIELD)
    w.loyalty_counters = 7
    py.battlefield.append(w)

    class _TargetAgent:
        def choose_target(self, state, pid, pool):
            return pool[0]

    py.player_by_id(0).agent = _TargetAgent()
    py.active_player_idx = 0

    # 1. Activate −7 → emblem created, loyalty 7 → 0.
    _activate_ability(py, 0, w.id, minus7_idx)
    resolve_top_of_stack(py)
    assert len(py.emblems) == 1, (
        f"Python: −7 must create exactly one emblem; got {len(py.emblems)}"
    )
    assert py.emblems[0].zone is Zone.COMMAND
    assert py.emblems[0].controller_id == 0
    assert w.loyalty_counters == 0, (
        f"Python: −7 must pay 7 loyalty (7 → 0); got {w.loyalty_counters}"
    )

    # 2. Begin-combat → emblem trigger fires from the command zone.
    dispatch_event(
        py, _Ev.BEGINNING_OF_COMBAT, label="beginning-of-combat",
        player=py.active_player(),
    )
    assert len(py.stack) == 1, (
        "Python: the emblem's begin-combat trigger must go on the stack"
    )
    # 3. Resolve → 3 +1/+1 counters on the artifact.
    resolve_top_of_stack(py)
    assert ao.plus_one_counters == 3, (
        f"Python: emblem must put three +1/+1 counters on the artifact; "
        f"got {ao.plus_one_counters}"
    )
    # HONEST-STOP: the artifact did NOT become a creature.
    assert ao.printing.is_creature is False, (
        "Python: becomes-0/0-Robot animate is honest-stopped — the "
        "artifact must stay a non-creature"
    )

    # ---- RUST ----
    rust = build_rust_state(spec)
    art_id = rust.register_and_inject_object(
        {
            "name": "Doohickey",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 2},
            "effects": [],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    walker_id = rust.register_and_inject_object(
        {
            "name": "Tezzeret, Cruel Captain",
            "card_types": ["Planeswalker"],
            "supertypes": ["Legendary"],
            "subtypes": ["Tezzeret"],
            "mana_cost": {"generic": 3},
            "starting_loyalty": 4,
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {"loyalty": 7},
                    "sorcery_speed": True,
                    "effect": {
                        "kind": "create_emblem",
                        "emblem_kind": "tezzeret_cruel_captain",
                    },
                },
            ],
        },
        0,
        ZONE_BATTLEFIELD,
    )
    rust.set_loyalty_counters(walker_id, 7)

    # 1. Activate −7 → emblem created, loyalty 7 → 0.
    rust.apply_action(
        {
            "kind": "activate_ability",
            "source_id": walker_id,
            "ability_index": 0,
        }
    )
    rust.resolve_top_of_stack()
    rust_emblems = rust.emblems_snapshot()
    assert len(rust_emblems) == 1, (
        f"Rust: −7 must create exactly one emblem; got {len(rust_emblems)}"
    )
    # zone 6 == ZONE_COMMAND.
    assert rust_emblems[0]["zone"] == 6
    assert rust_emblems[0]["controller_id"] == 0
    assert rust.get_loyalty_counters(walker_id) == 0, (
        f"Rust: −7 must pay 7 loyalty (7 → 0); got "
        f"{rust.get_loyalty_counters(walker_id)}"
    )

    # 2. Begin-combat → emblem trigger fires from the command zone.
    rust.dispatch_beginning_of_combat()
    assert rust.stack_size() == 1, (
        "Rust: the emblem's begin-combat trigger must go on the stack"
    )
    # 3. Resolve → 3 +1/+1 counters on the artifact.
    rust.resolve_top_of_stack()
    assert rust.get_counters(art_id) == 3, (
        f"Rust: emblem must put three +1/+1 counters on the artifact; "
        f"got {rust.get_counters(art_id)}"
    )

    # ---- CROSS-ENGINE byte-equality ----
    assert len(py.emblems) == len(rust_emblems) == 1
    assert w.loyalty_counters == rust.get_loyalty_counters(walker_id) == 0
    assert ao.plus_one_counters == rust.get_counters(art_id) == 3
