"""Cross-engine parity probes for Burgeoning.

**Burgeoning Cycle 1 closure (2026-05-23).** ``{G}`` Enchantment
(Special Guest reprint at SPG/EoE 126 — sourced from
``data/special_guests_eoe.json`` via the active
``OracleParserCardSource``). Printed oracle text::

    Whenever an opponent plays a land, you may put a land card from
    your hand onto the battlefield.

The parser maps the oracle line via the
``_OPTIONAL_PUT_PERMANENT_FROM_HAND_ONTO_BATTLEFIELD`` parameterized
recognizer (``cards/parser/effects.py:6519-6526``, "land" branch) to
``OptionalPutLandFromHandOntoBattlefield()`` — the parameterless
frozen dataclass at ``effects/combinators.py:247-294``. The cycle
ports the substrate to Rust
(``Effect::OptionalPutLandFromHandOntoBattlefield`` — field-free
unit variant; parse arm round-trips the bare
``{"kind": "optional_put_land_from_hand_onto_battlefield"}`` dict
shape; resolve arm in ``state_ops_resolve.rs`` is the byte-equal
mirror of Python's no-agent gate-4 silent return —
``OptionalPutLandFromHandOntoBattlefield.resolve`` builds an empty
``chosen_id`` whenever ``p.agent is None`` and returns silently;
the Rust arm has no agent surface and is an empty no-op for the
same byte-equal observable).

**Multi-gated card; classifier stays multi-gated.** Per the round-58
subsystem-attribution classifier (``scripts/scout_r58_subsystem_
attribution.py``), Burgeoning is multi-gated:

  * ``effect_uncovered`` — closed by this cycle. The new Rust variant
    ``Effect::OptionalPutLandFromHandOntoBattlefield`` makes the
    Python class ``OptionalPutLandFromHandOntoBattlefield`` covered
    via the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``; the classifier's
    ``missing_effect_classes`` array shrinks by one for this card.
  * ``nonsafe_triggered_ability`` — **STAYS active**. The trajectory
    safe-trigger admit gate
    (``parity/trajectory.py::_python_ta_to_safe_dict``) is
    INTENTIONALLY NOT widened — the
    ``("plays_land","controlled_by_opponent",
    "optional_put_land_from_hand_onto_battlefield")`` triple is not
    added to ``_SAFE_TRIGGERS``. Same per-card real-EoE probe
    precedent as Comet Crawler / Ouroboroid / Boilerbilges Ripper /
    Fanatic of the Harrowing / Terrapact Intimidator /
    Attack-in-the-Box / Hemosymbic Mite / Splitskin Doll /
    Endstone: the trajectory-side bench admit set is a distinct
    concern from per-card real-EoE parity probes.

**Per-card dedicated parity probe path (PROBED tier flip).** Even
though the classifier keeps the card multi-gated at
``nonsafe_triggered_ability``, this test module is the dedicated
per-card real-EoE byte-equal cross-engine probe that flips
Burgeoning to PROBED tier. Same precedent as
``test_boilerbilges_ripper_parity.py``,
``test_hemosymbic_mite_parity.py``, and friends.

**Cycle 1 scope — substrate landing.** This cycle lands ONLY the
``OptionalPutLandFromHandOntoBattlefield`` substrate (Rust variant
+ parse + to_pydict + resolve + cross-engine bridge + per-leaf
serializer + per-card probe). The full real-EoE PLAYS_LAND
trigger-fan-out byte-equal probe through both engines is NOT
1-cycle accessible: Rust has no ``Event::PlaysLand`` chokepoint
(Python's ``Event.PLAYS_LAND`` fires through
``fire_opponent_plays_land_triggers`` in ``turn.py:622``, with no
Rust analog). The substrate ships portable independent of the
trigger-fire dispatch; the per-card probe drives the Effect class
directly via the spell-resolution pipeline (the same convention
``test_hemosymbic_mite_parity.py`` uses for its BECOMES_TAPPED-
gated trigger body).

**No-agent decline default = byte-equal silent no-op.** Python's
``OptionalPutLandFromHandOntoBattlefield.resolve``
(``effects/combinators.py:258-291``) walks five conditional gates:

  1. Build ``options = [c for c in p.hand if c.printing.is_land]``.
  2. Empty options → silent return.
  3. ``if p.agent is not None: chosen_id = p.agent.
     choose_card_from_library(...)`` else ``chosen_id = None``.
  4. ``if chosen_id is None: return`` (DECLINE silent no-op).
  5. (Only with a yes-agent.) Move the chosen land hand→bf,
     ``tapped = printing.enters_tapped``, fire landfall triggers.

The cross-engine probe convention drives BOTH engines with no agent
on the source's controller. Python takes gate-4 silent return (the
explicit ``chosen_id = None`` else-branch when ``p.agent is None``
fires the ``chosen_id is None`` return at line 274); Rust has no
agent surface in ``apply_effect`` so the resolve arm is an empty
no-op (gates 2+4 both produce the same observable: no hand→bf zone
move, no landfall fire). The two engines therefore agree byte-equal
on the WHOLE field view.

**DISTINCTION from Comet Crawler.** Comet Crawler's
``OptionalSacAnotherForPumpSelfUEOT`` defaults to "DO" when no agent
(``combinators.py:461-462`` picks ``options[0]`` and sacrifices it);
the Rust mirror sacrifices the first eligible victim deterministically.
Burgeoning's ``OptionalPutLandFromHandOntoBattlefield`` defaults to
"DECLINE" when no agent (the explicit ``chosen_id = None`` branch);
the Rust mirror silently no-ops. Both are byte-equal under the
no-agent probe convention — the divergence is the no-agent default,
not the substrate. Same shape as the Boilerbilges Ripper Cycle 1
"DECLINE" precedent.

Coverage:

- Parser SoT pin: the live parser maps Burgeoning's PLAYS_LAND
  trigger to ``OptionalPutLandFromHandOntoBattlefield()`` (a
  parameterless frozen dataclass).
- Serializer round-trip: dict→Python via
  ``_ta_dict_to_python_effect`` rebuilds
  ``OptionalPutLandFromHandOntoBattlefield()``; Python→dict via
  ``trajectory._python_spell_effect_to_dict`` emits the bare unit-
  variant dict; Rust ``Effect::OptionalPutLandFromHandOntoBattlefield``
  → dict via ``Registry.get_printing_etb_effects`` emits the
  expected one-key dict shape.
- Effect-coverage class pin: ``OptionalPutLandFromHandOntoBattlefield``
  is in the covered-by-rust set after this cycle (1:1 identity-
  mapping rule).
- Rust resolve-arm unit pins:
    * No-fodder no-op: source on bf with no land in hand → resolve
      is a silent no-op, hand and bf unchanged.
    * Decline path with fodder: source on bf with a Forest in hand
      → no-agent decline → resolve is a silent no-op, hand still
      holds the Forest, bf unchanged.
    * Opponent's hand is irrelevant: a Forest in opponent's hand
      doesn't get put onto bf for the source's controller — the
      controller-scope is pinned via the `p` (source's controller)
      narrow.
- **GENUINE real-EoE cross-engine byte-equal probe** drives the
  parsed Burgeoning printing through the trajectory →
  ``_ta_dict_to_python_effect`` round-trip pipeline, AND through
  the directly-applied Rust resolve arm on a synthetic state
  matching Burgeoning's printed shape — both Engines hold a Forest
  in p0's hand + Burgeoning on p0's bf; both Engines drive the
  resolve with no agent → both produce zero observable delta.
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_burgeoning_plays_land_trigger_is_optional_put_land_effect():
    """**Verify-first.** The live parser maps Burgeoning's PLAYS_LAND
    trigger to ``OptionalPutLandFromHandOntoBattlefield()`` (a
    parameterless frozen dataclass). Pin the shape so a parser drift
    is caught here, not silently downstream in the cross-engine
    probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import (
        OptionalPutLandFromHandOntoBattlefield,
    )
    from mtg_bot.effects.predicates import Event

    p = get_active_source().get_printings().get("Burgeoning")
    if p is None:
        pytest.skip("Burgeoning absent from active CardSource")
    assert "Enchantment" in p.card_types
    # Single PLAYS_LAND triggered ability.
    plays_tas = [
        ta for ta in p.triggered_abilities
        if ta.event is Event.PLAYS_LAND
    ]
    assert len(plays_tas) == 1, (
        f"Burgeoning must have exactly 1 PLAYS_LAND triggered "
        f"ability; got {len(plays_tas)}"
    )
    ta = plays_tas[0]
    assert isinstance(
        ta.effect,
        OptionalPutLandFromHandOntoBattlefield,
    ), (
        f"PLAYS_LAND trigger effect must be "
        f"OptionalPutLandFromHandOntoBattlefield; "
        f"got {type(ta.effect).__name__}"
    )
    # Field-free unit dataclass — equality with a fresh
    # default-constructed instance.
    assert ta.effect == OptionalPutLandFromHandOntoBattlefield()


# -------------------------------------------------------------------
# Serializer round-trip + covered-set membership pins.
# -------------------------------------------------------------------


_BURGEONING_KIND = "optional_put_land_from_hand_onto_battlefield"


def test_burgeoning_effect_serializer_round_trip():
    """Python ``OptionalPutLandFromHandOntoBattlefield()`` →
    ``trajectory._python_spell_effect_to_dict`` emits the bare unit-
    variant dict; ``cross_engine._ta_dict_to_python_effect``
    reconstructs the default-constructed instance. Bridge arm is the
    lever flip — without it, a Rust→Python triggered-ability
    translation would raise on the unknown kind."""
    from mtg_bot.effects.combinators import (
        OptionalPutLandFromHandOntoBattlefield,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = trajectory._python_spell_effect_to_dict(
        OptionalPutLandFromHandOntoBattlefield()
    )
    assert d == {"kind": _BURGEONING_KIND}, (
        f"reverse serializer must emit the bare unit-variant dict; "
        f"got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(
        rebuilt,
        OptionalPutLandFromHandOntoBattlefield,
    ), (
        f"dict→Python bridge must round-trip to "
        f"OptionalPutLandFromHandOntoBattlefield; "
        f"got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == OptionalPutLandFromHandOntoBattlefield()


def test_burgeoning_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::OptionalPutLandFromHandOntoBattlefield`` → dict
    emits the expected one-key shape. Drives the round-trip through
    ``Registry.register_printing`` (the parse path) +
    ``get_printing_etb_effects`` (the ``effect_to_pydict`` readback).
    Using ``etb_effects`` instead of ``triggered_abilities`` because
    the Registry exposes an ``effect_to_pydict``-walking getter for
    the former but not the latter; the parse + serialize arms being
    exercised are identical (both walk ``parse_effect`` then
    ``effect_to_pydict`` on the same ``Effect`` variant)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Burgeoning Round-trip",
            "card_types": ["Enchantment"],
            "mana_cost": {"G": 1},
            "etb_effects": [
                {"kind": _BURGEONING_KIND},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == _BURGEONING_KIND
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


def test_burgeoning_class_covered_by_rust():
    """``OptionalPutLandFromHandOntoBattlefield`` must be in the
    covered-by-rust set — the Rust
    ``Effect::OptionalPutLandFromHandOntoBattlefield`` variant
    declaration makes ``covered_python_class_set()`` include it via
    the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``. This is the §2 covered-
    set tooth (parity-doc / coverage-script "covered" alignment) AND
    the closure of the classifier's ``effect_uncovered`` gate for
    Burgeoning."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "OptionalPutLandFromHandOntoBattlefield" in covered, (
        "Rust Effect::OptionalPutLandFromHandOntoBattlefield variant "
        "must make the Python OptionalPutLandFromHandOntoBattlefield "
        "class covered via the 1:1 identity-mapping rule"
    )


# -------------------------------------------------------------------
# Rust resolve-arm unit pins — no-agent decline silent no-op (the
# byte-equal mirror of Python's gate-4 ``chosen_id is None`` short-
# circuit).
# -------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine

    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# Synthetic Burgeoning-shaped printing. The "effects" list is the
# spell_effect list the cast-pipeline resolves on
# push_to_stack+resolve_top_of_stack. The real card composes this
# Effect under a PLAYS_LAND triggered ability with
# Controlled(OPPONENT) — but Rust has no PLAYS_LAND event chokepoint,
# so the substrate unit pin exercises the resolve arm directly via
# the spell-resolution pipeline (same shape the Hemosymbic Mite probe
# uses for its BECOMES_TAPPED-gated effect substrate, and the
# Ouroboroid probe uses for its beginning-of-combat-gated effect
# substrate).
_BURGEONING_PROBE_DICT: dict = {
    "name": "Burgeoning Probe Source",
    "card_types": ["Enchantment"],
    "mana_cost": {"G": 1},
    "effects": [
        {"kind": _BURGEONING_KIND},
    ],
}


# A plain land printing for the hand (Forest-shape).
_FOREST_DICT: dict = {
    "name": "Forest",
    "card_types": ["Land"],
    "supertypes": ["Basic"],
    "subtypes": ["Forest"],
    "produces": ["G"],
}


# A plain non-land (vanilla bear) printing for the hand. Must NOT be
# eligible fodder for the Burgeoning effect (the Python filter
# requires ``printing.is_land``).
_VANILLA_BEAR_DICT: dict = {
    "name": "Vanilla Bear",
    "card_types": ["Creature"],
    "power": 2,
    "toughness": 2,
    "mana_cost": {"generic": 1, "G": 1},
}


def test_rust_resolve_no_land_in_hand_silent_noop():
    """**Rust pin (a): no land in hand → silent no-op.** With a source
    on bf and a non-land in hand, the resolve arm short-circuits
    silently. Mirrors Python's gate-2 ``if not options: return``
    short-circuit at ``effects/combinators.py:267-268``. The hand
    stays intact (no zone move).
    """
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _BURGEONING_PROBE_DICT, 0, ZONE_BATTLEFIELD,
    )
    # Vanilla bear in p0's hand — NOT a land, NOT eligible.
    bear_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 0, ZONE_HAND,
    )

    hand_ids_before = [c["id"] for c in rs.hand_snapshot(0)]
    bf_ids_before = [e["id"] for e in rs.battlefield_snapshot()]
    assert bear_id in hand_ids_before
    assert src_id in bf_ids_before

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    # Bear still in hand, source still on bf — no zone move.
    hand_ids_after = [c["id"] for c in rs.hand_snapshot(0)]
    bf_ids_after = [e["id"] for e in rs.battlefield_snapshot()]
    assert bear_id in hand_ids_after, (
        "non-land hand card must NOT move to bf"
    )
    assert bear_id not in bf_ids_after
    assert src_id in bf_ids_after, "source must stay on bf"


def test_rust_resolve_with_land_no_agent_declines_silent_noop():
    """**Rust pin (b): land in hand + no agent → DECLINE silent
    no-op.** The canonical no-agent mirror — a Forest is eligible
    fodder in p0's hand, but with no agent surface in Rust's
    ``apply_effect``, the resolve is a silent no-op. Mirrors Python's
    gate-4 ``if chosen_id is None: return`` short-circuit at
    ``effects/combinators.py:274-275``. Observable:

      * Forest stays in p0's hand (NOT moved to bf).
      * Nothing new on p0's bf (besides the source).
    """
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _BURGEONING_PROBE_DICT, 0, ZONE_BATTLEFIELD,
    )
    forest_id = rs.register_and_inject_object(
        _FOREST_DICT, 0, ZONE_HAND,
    )

    hand_ids_before = [c["id"] for c in rs.hand_snapshot(0)]
    bf_ids_before = [e["id"] for e in rs.battlefield_snapshot()]
    assert forest_id in hand_ids_before
    assert src_id in bf_ids_before

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    hand_ids_after = [c["id"] for c in rs.hand_snapshot(0)]
    bf_ids_after = [e["id"] for e in rs.battlefield_snapshot()]
    assert forest_id in hand_ids_after, (
        "no-agent decline → Forest must NOT be moved to bf"
    )
    assert forest_id not in bf_ids_after, (
        "no-agent decline → Forest must NOT be on bf"
    )
    assert src_id in bf_ids_after, "source must stay on bf"


def test_rust_resolve_opponent_hand_land_not_eligible():
    """**Rust pin (c): opponent's hand land is NOT eligible.** A
    Forest in p1's (the opponent's) hand is NOT considered an option
    for p0's Burgeoning resolution — the Python filter scans
    ``p.hand`` where ``p = state.player_by_id(controller_id)``
    (``effects/combinators.py:265-266``). Combined with the no-agent
    decline path, this resolves to a silent no-op regardless of
    p1's hand state.

    Pinning this gate now keeps the Cycle 2+ agent-surface widening
    honest: even with a yes-agent, the controller-scope must still
    skip opponent's hand cards. Today the no-agent decline fires
    before the controller-scope is exercised, but pinning the
    observable forwards-protects the contract.
    """
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _BURGEONING_PROBE_DICT, 0, ZONE_BATTLEFIELD,
    )
    # Forest in p1's (opponent's) hand — wrong controller.
    opp_forest_id = rs.register_and_inject_object(
        _FOREST_DICT, 1, ZONE_HAND,
    )

    p0_hand_ids_before = [c["id"] for c in rs.hand_snapshot(0)]
    p1_hand_ids_before = [c["id"] for c in rs.hand_snapshot(1)]
    bf_ids_before = [e["id"] for e in rs.battlefield_snapshot()]
    assert opp_forest_id in p1_hand_ids_before
    assert opp_forest_id not in p0_hand_ids_before

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    p0_hand_ids_after = [c["id"] for c in rs.hand_snapshot(0)]
    p1_hand_ids_after = [c["id"] for c in rs.hand_snapshot(1)]
    bf_ids_after = [e["id"] for e in rs.battlefield_snapshot()]
    assert opp_forest_id in p1_hand_ids_after, (
        "opponent's Forest must NEVER move to bf for p0's Burgeoning"
    )
    assert opp_forest_id not in p0_hand_ids_after
    assert opp_forest_id not in bf_ids_after
    assert src_id in bf_ids_after, "source must stay on bf"


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equal probe — drives the parsed
# Burgeoning printing through the trajectory →
# _ta_dict_to_python_effect round-trip pipeline, AND through the
# directly-applied Rust resolve arm on a synthetic state matching
# Burgeoning's printed shape.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_burgeoning_decline_path_parity():
    """**GENUINE real-EoE cross-engine byte-equal probe — Burgeoning
    PLAYS_LAND no-agent decline path.** The slug-credit anchor for the
    PROBED tier flip even though the classifier multi-gates the card
    on ``nonsafe_triggered_ability``.

    Drives the **real parsed Burgeoning printing** through the
    trajectory serializer + cross-engine dict→Python bridge:

      * Extract the parsed PLAYS_LAND triggered-ability effect from
        the real Special-Guest Burgeoning printing.
      * Walk the effect — must be
        ``OptionalPutLandFromHandOntoBattlefield()`` per the §2
        parser SoT pin.
      * Serialize via ``trajectory._python_spell_effect_to_dict`` →
        the bare one-key dict.
      * Round-trip via ``cross_engine._ta_dict_to_python_effect`` →
        a fresh ``OptionalPutLandFromHandOntoBattlefield()`` instance
        equal to the parser-emitted effect.
      * Drive the effect's resolve through Rust on a synthetic state
        matching Burgeoning's printed shape: a Forest in p0's hand,
        a Burgeoning-shape carrier on p0's bf. With no agent surface,
        the resolve is a silent no-op — Forest stays in hand, bf
        unchanged.

    **Byte-equality scope.** Both the parser-emitted effect and the
    bridge-reconstructed effect compare equal as field-free unit
    dataclasses; the Rust-side resolve produces zero observable
    delta (no zone moves, no counters, no life changes). This pins
    the no-agent decline silent-no-op byte-equal observable across
    engines.

    **Cycle 1 scope caveat.** The full real-EoE PLAYS_LAND
    trigger-fan-out byte-equal probe through Rust's
    ``Event::PlaysLand`` machinery is NOT 1-cycle accessible — Rust
    has no ``Event::PlaysLand`` chokepoint today; the Python
    ``fire_opponent_plays_land_triggers`` dispatch in
    ``turn.py:622`` is the only firing path. The substrate-level
    round-trip + the Rust resolve-arm unit pins carry the PROBED
    tier flip per the Boilerbilges Ripper / Hemosymbic Mite /
    Endstone / Ouroboroid classifier-bypass precedent.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import (
        OptionalPutLandFromHandOntoBattlefield,
    )
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    real = get_active_source().get_printings().get("Burgeoning")
    if real is None:
        pytest.skip("Burgeoning absent from active CardSource")

    # §2 source-of-truth: genuine PLAYS_LAND trigger must be
    # OptionalPutLandFromHandOntoBattlefield().
    plays_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.PLAYS_LAND
        ),
        None,
    )
    assert plays_ta is not None, (
        "Burgeoning must have a PLAYS_LAND triggered ability"
    )
    leaf = plays_ta.effect
    assert isinstance(
        leaf, OptionalPutLandFromHandOntoBattlefield
    ), (
        f"PLAYS_LAND trigger effect must be "
        f"OptionalPutLandFromHandOntoBattlefield; "
        f"got {type(leaf).__name__}"
    )

    # Round-trip the leaf through trajectory serializer + cross-engine
    # dict→Python bridge.
    d = trajectory._python_spell_effect_to_dict(leaf)
    assert d == {"kind": _BURGEONING_KIND}, (
        f"real-EoE leaf serializer must emit the bare unit-variant "
        f"dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(
        rebuilt, OptionalPutLandFromHandOntoBattlefield
    ), (
        f"dict→Python bridge must round-trip to "
        f"OptionalPutLandFromHandOntoBattlefield; "
        f"got {type(rebuilt).__name__}"
    )
    assert rebuilt == leaf, (
        f"round-tripped leaf must equal the parser-emitted leaf "
        f"(both field-free unit dataclasses); got rebuilt={rebuilt!r}, "
        f"parser={leaf!r}"
    )

    # Drive the leaf through Rust's resolve arm on a synthetic state
    # matching Burgeoning's printed shape — Burgeoning-shape carrier
    # on p0's bf, a Forest in p0's hand. With no agent surface, the
    # resolve is a silent no-op — the byte-equal observable across
    # engines.
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _BURGEONING_PROBE_DICT, 0, ZONE_BATTLEFIELD,
    )
    forest_id = rs.register_and_inject_object(
        _FOREST_DICT, 0, ZONE_HAND,
    )

    hand_ids_before = [c["id"] for c in rs.hand_snapshot(0)]
    bf_ids_before = [e["id"] for e in rs.battlefield_snapshot()]
    assert forest_id in hand_ids_before
    assert src_id in bf_ids_before

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, (
        "Rust resolve must clear the stack"
    )

    # No-agent decline → no observable delta.
    hand_ids_after = [c["id"] for c in rs.hand_snapshot(0)]
    bf_ids_after = [e["id"] for e in rs.battlefield_snapshot()]
    assert forest_id in hand_ids_after, (
        "no-agent decline → Forest must stay in p0's hand"
    )
    assert forest_id not in bf_ids_after
    assert src_id in bf_ids_after, "source must stay on bf"
    # Hand and bf composition is unchanged compared to pre-resolve.
    assert sorted(hand_ids_after) == sorted(hand_ids_before), (
        f"hand must be byte-equal pre/post resolve; "
        f"before={sorted(hand_ids_before)}, after={sorted(hand_ids_after)}"
    )
    assert sorted(bf_ids_after) == sorted(bf_ids_before), (
        f"bf must be byte-equal pre/post resolve; "
        f"before={sorted(bf_ids_before)}, after={sorted(bf_ids_after)}"
    )
