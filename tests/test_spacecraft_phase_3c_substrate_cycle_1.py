"""**Spacecraft Phase 3C Cycle 1 (2026-05-26).**

Tests for the Phase 3C Cycle 1 Rust substrate landing per
``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_3_DESIGN.md`` §4.1 (Rust
spec) + §5 (Python bridge spec) + §6.1 (test plan) + §7.3 (cycle
table).

Deliverables (Cycle 1 Rust slice, per design doc §4.1):

  - New ``i32`` slot on Rust's ``TriggeredAbility`` struct
    (``cards.rs::TriggeredAbility``): ``tier_threshold``. Mirrors
    Python's ``TriggeredAbility.tier_threshold: int = 0`` at
    ``effects/base.py:718`` AND the sibling
    ``ActivatedAbility.tier_threshold`` at ``cards.rs:10490``
    (CE20 follow-up Slice 3 precedent).
  - New parse arm in ``parse_triggered_ability``: reads optional
    ``"tier_threshold": int >= 0`` from the dict (defaults to 0 when
    absent — back-compat with every pre-Phase-3 trigger dict).
    Negative values raise ``ValueError``.
  - New trigger-firing-time gate in
    ``state_ops_resolve::dispatch_event``: when
    ``ability.tier_threshold > 0``, the source GameObject's
    ``charge_counters`` must be ``>= tier_threshold`` for the trigger
    to fire (sibling of ``ability.once_per_turn`` gate). Mirrors
    Python's ``should_fire_trigger`` at ``turn.py:469-473``.
  - Bridge thread-through (``cross_engine.py``):
    ``_ta_dict_to_python_triggered_ability`` reads
    ``tier_threshold`` from the dict and threads it to the Python
    ``TriggeredAbility`` constructor (defaults to 0 on missing key).

This is a **substrate-only closure** — the slot + gate + bridge
arrive together so a follow-up sub-cycle (3C Cycle 2: Synthesizer
Labship; 3C Cycle 3: Entropic Battlecruiser; 3C Cycle 4: Infinite
Guideline Station) can ship per-card Effect-class admit widens
WITHOUT re-touching the substrate. The 3 Phase-3C carriers (those
that load-bear the tier gate) STAY DECLINED at the production-deck
admit gate post-Cycle-1 because:

  - Their Effect classes (``TargetArtifactBecomesCreatureUEOT``,
    ``EachOpponentDiscardsOrLosesLife``,
    ``CreateTokenPerMulticoloredPermanent``,
    ``DrawCardPerMulticoloredPermanent``) are NOT yet on any Rust
    Effect enum / bridge dispatch path (Cycles 2-4 ship them).
  - Their (event, predicate) shapes include
    ``(BEGINNING_OF_COMBAT, Controlled(YOU))`` and
    ``(DISCARDS_CARD, Controlled(OPPONENT))`` which are NOT yet on
    any Phase-3 admit predicate's event-shape table (Phase-3 admit
    predicate ships in Cycle 2 alongside the first per-card flip).

**Verify-first findings (live tree, post-3B merge `717df1b6`):**

  - Synthesizer Labship (BEGINNING_OF_COMBAT/Controlled(YOU)
    TargetArtifactBecomesCreatureUEOT(2,2,{flying}), tier=2);
  - Entropic Battlecruiser (ATTACKS/IsSelf
    EachOpponentDiscardsOrLosesLife(life_if_cant=3), tier=0 +
    DISCARDS_CARD/Controlled(OPPONENT) TargetPlayerLosesLife(3),
    tier=1);
  - Infinite Guideline Station (ENTERS/IsSelf
    CreateTokenPerMulticoloredPermanent, tier=0 + ATTACKS/IsSelf
    DrawCardPerMulticoloredPermanent, tier=0).
  - The 2 load-bearing tier-gated triggers across the 3 carriers
    are Synthesizer Labship's tier=2 BEGINNING_OF_COMBAT trigger
    and Entropic Battlecruiser's tier=1 DISCARDS_CARD trigger —
    these justify the substrate slot.
  - Python's ``TriggeredAbility`` dataclass at ``effects/base.py:718``
    already carries ``tier_threshold: int = 0`` (Python side has
    been honoring it for ages; Rust side was the substrate gap).
  - Python's ``should_fire_trigger`` at ``turn.py:469-473`` already
    honors the gate on the Python side. The Rust dispatch gate at
    ``state_ops_resolve.rs:927-951`` is what Cycle 1 ports.

**Test plan (per design doc §6.1):**

  1. Rust ``TriggeredAbility.tier_threshold`` parse arm: a registry
     dict carrying ``tier_threshold=0/1/2/12`` round-trips. Missing
     key defaults to 0. Negative value raises.
  2. Rust trigger-firing-time gate (closed, source below tier):
     synthetic CardPrinting with a ``tier_threshold=2`` trigger;
     with the source's ``charge_counters=0`` AND ``=1``, the
     dispatch site at ``state_ops_resolve.rs`` does NOT push the
     trigger onto the stack.
  3. Rust trigger-firing-time gate (open, source at or above tier):
     same synthetic carrier; with the source's
     ``charge_counters>=2``, the dispatch site DOES push the
     trigger.
  4. Back-compat — ``tier_threshold=0`` triggers fire unchanged:
     a synthetic ``tier_threshold=0`` ETB trigger fires regardless
     of source charge_counters.
  5. Bridge round-trip — ``tier_threshold`` thread-through: a
     bridge dict carrying ``tier_threshold=2`` constructs a Python
     ``TriggeredAbility`` with ``tier_threshold == 2``. Missing
     key defaults to 0.
  6. Substrate-only invariant pin — the 3 Phase-3C carriers
     STAY DECLINED at the live admit gate post-Cycle-1
     (substrate-only invariant; Cycles 2-4 ship the per-card
     flips).
  7. Phase 1 / Phase 2 / Phase 3A / Phase 3B non-regression — the
     5 currently-admitted Spacecraft (Larval Scoutlander +
     Sledge-Class Seedship from Phase 3 + earlier-phase admits)
     keep working with the new substrate.
"""

from __future__ import annotations

import importlib.util

import pytest


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
# Parser SoT / verify-first
# ---------------------------------------------------------------------------


def test_python_triggered_ability_carries_tier_threshold_slot():
    """**Parser SoT pin.** Python's ``TriggeredAbility`` dataclass
    at ``effects/base.py:680`` carries the ``tier_threshold: int = 0``
    slot that the Rust substrate Cycle 1 mirrors.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.generic.draw_mill import DrawCards

    ta_default = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=DrawCards(amount=1),
    )
    assert ta_default.tier_threshold == 0

    ta_tier2 = TriggeredAbility(
        event=Event.BEGINNING_OF_COMBAT,
        predicate=IsSelf(),
        effect=DrawCards(amount=1),
        tier_threshold=2,
    )
    assert ta_tier2.tier_threshold == 2


def test_three_phase_3c_carriers_load_bear_tier_threshold_substrate():
    """**Verify-first pin — the 3 Phase-3C carriers' triggers
    confirm tier_threshold load-bearing.**

    Synthesizer Labship's BEGINNING_OF_COMBAT trigger carries
    ``tier_threshold=2`` (the design-doc-§4.1 substrate load-bearing
    case); Entropic Battlecruiser's DISCARDS_CARD trigger carries
    ``tier_threshold=1``; Infinite Guideline Station's triggers all
    carry ``tier_threshold=0`` (no gate). These 3 carriers' shapes
    justify the Cycle-1 substrate.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource

    ps = OracleParserCardSource().get_printings()

    syn = ps["Synthesizer Labship"]
    assert "Spacecraft" in syn.subtypes
    assert syn.station_threshold == 9
    tas = tuple(syn.triggered_abilities or ())
    assert len(tas) == 1
    assert tas[0].tier_threshold == 2  # Load-bearing.

    ent = ps["Entropic Battlecruiser"]
    assert "Spacecraft" in ent.subtypes
    assert ent.station_threshold == 8
    tas = tuple(ent.triggered_abilities or ())
    assert len(tas) == 2
    # mode-0 (ATTACKS) has tier=0; mode-1 (DISCARDS_CARD) has tier=1.
    assert tas[0].tier_threshold == 0
    assert tas[1].tier_threshold == 1  # Load-bearing.

    igs = ps["Infinite Guideline Station"]
    assert "Spacecraft" in igs.subtypes
    assert igs.station_threshold == 12
    tas = tuple(igs.triggered_abilities or ())
    assert len(tas) == 2
    # Both ENTERS + ATTACKS modes carry tier=0 (always fire).
    assert tas[0].tier_threshold == 0
    assert tas[1].tier_threshold == 0


# ---------------------------------------------------------------------------
# Rust register_printing parse arm — `tier_threshold` round-trip
# ---------------------------------------------------------------------------


def _bare_creature_def(engine, name: str, ta_dicts: list[dict] | None = None):
    """Build a minimal CardPrinting registry dict for a vanilla 2/2
    creature with the supplied triggered abilities. Mirrors the
    register_printing dict shape from existing Phase-3 test fixtures.
    """
    pdict = {
        "name": name,
        "card_types": ["Creature"],
        "subtypes": ["Bear"],
        "power": 2,
        "toughness": 2,
    }
    if ta_dicts is not None:
        pdict["triggered_abilities"] = ta_dicts
    return pdict


def test_rust_register_printing_accepts_tier_threshold_zero(engine):
    """**Rust parse pin — back-compat.** A trigger dict that OMITS
    the ``tier_threshold`` key parses cleanly (defaults to 0 — no
    gate). Pre-Phase-3 dict shape stays accepted unchanged.
    """
    reg = engine.Registry()
    ta_dict = {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
        # tier_threshold omitted -> defaults to 0
    }
    reg.register_printing(_bare_creature_def(engine, "Bear A", [ta_dict]))


def test_rust_register_printing_accepts_tier_threshold_positive(engine):
    """**Rust parse pin — positive value.** A trigger dict carrying
    ``tier_threshold`` in {1, 2, 12} (the per-card admit set covers
    {0, 1, 2}, and Infinite Guideline Station's station_threshold is
    12 — a future widen could carry tier=12 triggers) parses cleanly.
    """
    reg = engine.Registry()
    for tier in (1, 2, 12):
        ta_dict = {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {"kind": "draw_cards", "count": 1},
            "tier_threshold": tier,
        }
        reg.register_printing(_bare_creature_def(engine, f"Bear-{tier}", [ta_dict]))


def test_rust_register_printing_rejects_negative_tier_threshold(engine):
    """**Rust parse pin — negative rejects.** A trigger dict
    carrying ``tier_threshold=-1`` raises ``ValueError`` (mirrors the
    sibling ``ActivatedAbility.tier_threshold`` parse arm at
    ``cards.rs:16604``).
    """
    reg = engine.Registry()
    ta_dict = {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
        "tier_threshold": -1,
    }
    with pytest.raises(ValueError, match="tier_threshold"):
        reg.register_printing(_bare_creature_def(engine, "Bear N", [ta_dict]))


def test_rust_register_printing_rejects_non_int_tier_threshold(engine):
    """**Rust parse pin — type-checked.** A non-int ``tier_threshold``
    (e.g., a string) raises ``ValueError``. Backstop for malformed
    fixtures.
    """
    reg = engine.Registry()
    ta_dict = {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
        "tier_threshold": "not_a_number",
    }
    with pytest.raises(ValueError, match="tier_threshold"):
        reg.register_printing(_bare_creature_def(engine, "Bear S", [ta_dict]))


# ---------------------------------------------------------------------------
# Cross-engine bridge thread-through
# ---------------------------------------------------------------------------


def test_bridge_ta_dict_threads_tier_threshold_default_zero():
    """**Bridge round-trip pin (default 0).**
    ``_ta_dict_to_python_triggered_ability`` defaults missing
    ``tier_threshold`` to 0 (back-compat with every pre-Phase-3
    trigger dict).
    """
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
    )

    back = _ta_dict_to_python_triggered_ability({
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "draw_cards", "count": 1},
        # tier_threshold omitted
    })
    assert back.tier_threshold == 0


def test_bridge_ta_dict_threads_tier_threshold_positive():
    """**Bridge round-trip pin (positive).** A bridge dict carrying
    ``tier_threshold=2`` reconstructs a Python ``TriggeredAbility``
    with ``tier_threshold == 2``. This is the load-bearing path for
    Synthesizer Labship's tier=2 BEGINNING_OF_COMBAT trigger
    (Cycle-2 closure).
    """
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
    )

    back = _ta_dict_to_python_triggered_ability({
        "event": "beginning_of_combat",
        "predicate": {"kind": "always"},
        "effect": {"kind": "draw_cards", "count": 1},
        "tier_threshold": 2,
    })
    assert back.tier_threshold == 2


def test_bridge_ta_dict_threads_tier_threshold_one():
    """**Bridge round-trip pin (tier=1).** Mirrors Entropic
    Battlecruiser mode-1's DISCARDS_CARD/Controlled(OPPONENT) tier=1
    shape (Cycle-3 closure precedent).
    """
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_triggered_ability,
    )

    back = _ta_dict_to_python_triggered_ability({
        "event": "discards_card",
        "predicate": {"kind": "controlled_by_opponent"},
        "effect": {"kind": "target_player_loses_life", "amount": 3},
        "tier_threshold": 1,
    })
    assert back.tier_threshold == 1


# ---------------------------------------------------------------------------
# Substrate-only invariant pin: the 3 Phase-3C carriers stay declined
# ---------------------------------------------------------------------------


def test_three_phase_3c_carriers_stay_declined_at_admit_gate_post_cycle_1():
    """**Substrate-only invariant pin (the load-bearing
    no-silent-auto-grow gate).** ``_python_ta_to_safe_dict`` returns
    None for each of the 3 Phase-3C carriers' triggers post-Cycle-1
    because their Effect classes are NOT yet on any Rust Effect /
    bridge / safe-set table.

    Cycle 2 ships ``Effect::TargetArtifactBecomesCreatureUEOT`` +
    Synthesizer Labship FLIP via a SEPARATE admit predicate
    (``_printing_is_bridge_phase_3_trigger_spacecraft``); Cycle 3
    ships ``EachOpponentDiscardsOrLosesLife`` + Entropic
    Battlecruiser FLIP; Cycle 4 ships
    ``CreateTokenPerMulticoloredPermanent`` +
    ``DrawCardPerMulticoloredPermanent`` + Infinite Guideline Station
    FLIP. Until then the carriers decline.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _python_ta_to_safe_dict

    ps = OracleParserCardSource().get_printings()
    for name in (
        "Synthesizer Labship",
        "Entropic Battlecruiser",
        "Infinite Guideline Station",
    ):
        printing = ps[name]
        for ta in printing.triggered_abilities or ():
            assert _python_ta_to_safe_dict(ta) is None, (
                f"{name}: trigger {ta.event} / {type(ta.effect).__name__} "
                f"SHOULD decline post-Cycle-1 (substrate-only)"
            )


def test_three_phase_3c_carriers_decline_at_production_loader_filter():
    """**Loader-filter pin.** The production-deck loader's
    bridge-filter (``_filter_deck_to_bridge_supported``) rejects each
    of the 3 Phase-3C carriers post-Cycle-1 — they all land in the
    ``not_bridged_sink`` (resolved but unsupported).
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _filter_deck_to_bridge_supported,
    )

    ps = OracleParserCardSource().get_printings()
    names = [
        "Synthesizer Labship",
        "Entropic Battlecruiser",
        "Infinite Guideline Station",
    ]
    unresolved: list = []
    not_bridged: list = []
    filtered_names, _ = _filter_deck_to_bridge_supported(
        names,
        ps,
        unresolved_sink=unresolved,
        not_bridged_sink=not_bridged,
    )
    # None of the 3 carriers get past the bridge admit gate.
    assert filtered_names == []
    # None are unresolved — they exist in the printings dict.
    assert unresolved == []
    # All 3 carriers land in the not-bridged sink.
    assert set(not_bridged) == set(names)


# ---------------------------------------------------------------------------
# Rust trigger-firing-time gate — sanity unit
# ---------------------------------------------------------------------------


def test_rust_register_printing_accepts_etb_with_tier_threshold(engine):
    """**Rust dispatch sanity pin.** Verify the register-printing
    path accepts a synthetic ETB trigger carrying ``tier_threshold``
    of 0 / 1 / 2 in all three slots — confirms the substrate is
    end-to-end wired (struct + parse + storage). The actual gate
    behavior (closed vs open) is exercised by the per-card real-EoE
    probe in Cycle 2 (Synthesizer Labship at tier=2).
    """
    reg = engine.Registry()
    for tier in (0, 1, 2):
        ta_dict = {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {"kind": "draw_cards", "count": 1},
            "tier_threshold": tier,
        }
        reg.register_printing(
            _bare_creature_def(engine, f"Bear-Tier-{tier}", [ta_dict])
        )


# ---------------------------------------------------------------------------
# Phase 1 / Phase 2 / Phase 3A / Phase 3B non-regression
# ---------------------------------------------------------------------------


def test_phase_1_carrier_still_admits_post_cycle_1():
    """**Non-regression pin.** Galvanizing Sawship — a Phase-1
    pure-station Spacecraft — keeps admitting at the
    ``_printing_is_bridge_pure_station_spacecraft`` gate post-
    Cycle-1.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_pure_station_spacecraft,
    )

    ps = OracleParserCardSource().get_printings()
    printing = ps["Galvanizing Sawship"]
    assert _printing_is_bridge_pure_station_spacecraft(printing)


def test_phase_2_carrier_still_admits_post_cycle_1():
    """**Non-regression pin.** Lumen-Class Frigate — Phase-2's
    static-anthem Spacecraft — keeps admitting at the
    ``_printing_is_bridge_phase_2_static_anthem_spacecraft`` gate
    post-Cycle-1.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_phase_2_static_anthem_spacecraft,
    )

    ps = OracleParserCardSource().get_printings()
    printing = ps["Lumen-Class Frigate"]
    assert _printing_is_bridge_phase_2_static_anthem_spacecraft(printing)
