"""Entropic Battlecruiser — per-card real-EoE cross-engine byte-equal
probe (``covered_by_construction`` → PROBED tier flip; Spacecraft
Station substrate Phase 3C Cycle 3 closure marker for Scenarios A+B+C
per design doc §6.4 #15).

Entropic Battlecruiser is a ``{3}{B}`` Artifact — Spacecraft in the EoE
pool carrying the Phase-3C-Cycle-3 two-trigger shape:

    Power/Toughness: 3/10
    Station threshold: 8
    Stationed keywords: flying, deathtouch
    Triggered abilities:
      MODE 0 — ATTACKS trigger (always fires; tier=0):
        event = Event.ATTACKS
        predicate = IsSelf(subject=None)
        effect = EachOpponentDiscardsOrLosesLife(life_if_cant=3)
        tier_threshold = 0
        once_per_turn = False
      MODE 1 — DISCARDS_CARD trigger (LOAD-BEARING tier-1 gate; tier=1):
        event = Event.DISCARDS_CARD
        predicate = Controlled(by=OPPONENT, subject=None)
        effect = TargetPlayerLosesLife(amount=3)
        tier_threshold = 1 (LOAD-BEARING — the SECOND consumer of the
            Phase-3C C1 tier-gate substrate; trigger fires only when
            the source's charge_counters >= 1)
        once_per_turn = False

Per design doc §3C, Entropic Battlecruiser is one of three carriers in
the Phase 3C admit set (Synthesizer Labship 3C-C2 + Entropic
Battlecruiser 3C-C3 + Infinite Guideline Station 3C-C4). The strict
admit predicate
:func:`mtg_bot.parity.trajectory._printing_is_bridge_phase_3_trigger_
spacecraft` positively rejects every non-Phase-3-A/B/C-Cycle-3 carrier
(the §6.6 decline-set bench check pins this exhaustively in
``test_spacecraft_phase_3a_cycle_2_flip.py`` — Infinite Guideline
Station has CreateTokenPerMulticoloredPermanent /
DrawCardPerMulticoloredPermanent effects and stays DECLINED until C4
ships).

**Multi-cycle DECLINED → ADMITTED → PROBED transition.**

  * **Phase 3C Cycle 1 (Rust substrate landing, commit ``ebc94a5c``,
    2026-05-26).** Rust substrate: new ``TriggeredAbility.tier_threshold:
    i32`` slot on ``cards.rs::TriggeredAbility`` + trigger-firing-time
    gate at ``state_ops_resolve.rs::dispatch_event`` chokepoint +
    cross-engine bridge dict-to-Python tier_threshold thread-through in
    ``cross_engine.py``. Entropic Battlecruiser STAYED DECLINED at
    every admit gate (substrate-only invariant).
  * **Phase 3C Cycle 2 (Synthesizer Labship FLIP, commit ``277ad6d6``,
    2026-05-26).** Synthesizer Labship admitted; Entropic
    Battlecruiser STAYED DECLINED (different Effect classes).
  * **Phase 3C Cycle 3 (THE FLIP, this slice, 2026-05-26).** Combined
    Rust + Python cycle:
      - New ``Effect::EachOpponentDiscardsOrLosesLife { life_if_cant:
        i32 }`` Rust **sibling-variant** (NOT a widen of
        ``Effect::EachOpponentDiscards`` per design doc §4.5 / §9.9 —
        preserves the 9 existing EoE production callers of
        EachOpponentDiscards at their byte-equal shape) on
        ``cards.rs::Effect`` + parse / to_pydict / resolve arms +
        cross-engine bridge dict-to-Python arm in ``cross_engine.py``.
      - ``Effect::TargetPlayerLosesLife`` already shipped (PPP Pin 1,
        10th Rust slice) — verified absent-no-rework.
      - New ``state.resolving_discards_card_player_id: u8`` transient
        slot seeded by ``dispatch_event``'s ``Event::DiscardsCard``
        branch so ``first_legal_trigger_target`` can wire the
        discarding-player fixed target onto ``TargetPlayerLosesLife``
        at trigger push time. Sibling-narrow precedent of the JJJ Pin 2
        ``PutPoisonCountersOnTargetPlayer`` /
        ``resolving_combat_damage_target_player_id`` pattern.
      - Widen :data:`_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES` to
        include ``EachOpponentDiscardsOrLosesLife`` +
        ``TargetPlayerLosesLife`` + widen
        :data:`_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES` to include
        ``(Event.DISCARDS_CARD, Controlled(by=OPPONENT, subject=None))``.
      - Per-card builder's matching DISCARDS_CARD event arm +
        Controlled(OPPONENT) predicate dict + the two Effect-dict-emit
        arms (threading the new ``tier_threshold`` slot positively
        when > 0).
    Entropic Battlecruiser DECLINED → ADMITTED (admit set 5 → 6; the
    SIXTH Spacecraft admit after Sawship + Lumen-Class Frigate +
    Larval Scoutlander + Sledge-Class Seedship + Synthesizer Labship).
  * **Phase 3C Cycle 3 (THIS LANE; THE PROBE — Scenarios A+B+C).**
    Per-card real-EoE cross-engine byte-equality probe driving BOTH
    engines through THREE scenarios across the ATTACKS-and-charge-
    counter axes (the load-bearing tier-gate axis per design doc §6.4
    #15):

    (A) **Mode-0 ATTACKS trigger, tier=0, p1 hand empty (life-loss
        branch).** Entropic Battlecruiser on p0's bf (unsick) with
        ``charge_counters=0``. p1's hand EMPTY. Declare Entropic
        Battlecruiser as attacker; mode-0 ATTACKS/IsSelf trigger fires
        unconditionally (tier=0). Resolves through the new
        ``EachOpponentDiscardsOrLosesLife`` arm — empty-hand branch
        fires: p1 loses 3 life. NO ``Event::DiscardsCard`` is
        dispatched (the alternative branch fires INSTEAD of the
        discard). The mode-1 DISCARDS_CARD trigger is NOT awakened in
        this scenario (no discard happened).

    (B) **Mode-0 + mode-1 chain, tier-1 gate OPEN (charge=1, at
        tier=1).** Entropic Battlecruiser on p0's bf with
        ``charge_counters=1``. p1's hand has 1 card (a synthetic
        non-creature artifact). Declare Entropic Battlecruiser as
        attacker. Mode-0 ATTACKS trigger fires + resolves through the
        non-empty-hand branch: p1 discards hand[0] →
        ``Event::DiscardsCard`` dispatched on p1 subject. The mode-1
        trigger's tier-gate is OPEN (charge=1 >= tier=1) so it FIRES;
        the discarding-player (p1) is wired as the pre-fixed target
        via the new ``resolving_discards_card_player_id`` slot;
        mode-1's ``TargetPlayerLosesLife(3)`` resolves and subtracts
        3 from p1's life. **THIS IS THE LOAD-BEARING SECOND TIER-GATE
        CONSUMER PROOF — the C1 substrate fires under real charge
        counters for Entropic Battlecruiser's mode-1.**

    (C) **Mode-1 tier-1 gate CLOSED (charge=0, below tier=1).**
        Entropic Battlecruiser on p0's bf with ``charge_counters=0``.
        p1's hand has 1 card. Declare Entropic Battlecruiser as
        attacker. Mode-0 ATTACKS trigger fires + p1 discards hand[0]
        → ``Event::DiscardsCard`` dispatched. BUT the mode-1
        DISCARDS_CARD trigger's tier-gate is CLOSED (charge=0 < tier=1)
        so it does NOT fire on either engine. p1 still has 20 life
        post-resolve (no mode-1 life loss).

**Scripted-picker semantics.** Python's
``EachOpponentDiscardsOrLosesLife.resolve`` walks each opponent's hand
and calls ``agent.choose_discard`` to pick the discarded card. The
probe sets a picker shim on p1 that deterministically returns
``hand_ids[0]`` (mirrors Rust's ``hand[0]`` pop convention). On
empty-hand opponents (Scenario A) the agent is never invoked. No
target selection on mode-1: ``TargetPlayerLosesLife`` uses the
pre-fixed target (the discarding player); no agent decision is
required.

**Real-EoE-signal discipline.** This module uses the live
``OracleParserCardSource`` Entropic Battlecruiser printing on the
Python side AND the canonical Rust registry dict shape emitted by the
C3 bridge forward arm
``_spec_card_to_printing_dict(_phase_3_trigger_spacecraft_card_def(
p))`` on the Rust side — the SAME printing shape both engines read
(verified pre-flight via the C3 bridge round-trip pin). The synthetic
non-creature artifact used to populate p1's hand is a ``{0}`` Artifact
(sibling shape to the Lander used in Synthesizer Labship's probe).

This module is the Spacecraft Phase 3C Cycle 3 closure marker; the
Phase-3C-Cycle-3 admit set is exhaustively pinned at Larval
Scoutlander (3A) + Sledge-Class Seedship (3B) + Synthesizer Labship
(3C-C2) + Entropic Battlecruiser (3C-C3) post-Cycle-3.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


# Skip Rust-engine probes if the extension isn't built.
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (Rust int encoding).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


# Canonical Rust dict for Entropic Battlecruiser — the EXACT shape
# ``_spec_card_to_printing_dict`` emits via the C3 forward arm
# ``_phase_3_trigger_spacecraft_card_def``. Both engines read this
# same printing shape (verified pre-flight via the C3 bridge round-
# trip pin below).
_ENTROPIC_BATTLECRUISER_RUST_DICT = {
    "name": "Entropic Battlecruiser",
    "card_types": ["Artifact"],
    "mana_cost": {"generic": 3, "B": 1},
    "effects": [],
    "power": 3,
    "toughness": 10,
    "subtypes": ["Spacecraft"],
    "station_threshold": 8,
    "stationed_keywords": ["deathtouch", "flying"],
    "triggered_abilities": [
        {
            "event": "attacks",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "each_opponent_discards_or_loses_life",
                "life_if_cant": 3,
            },
        },
        {
            "event": "discards_card",
            "predicate": {"kind": "controlled_by_opponent"},
            "effect": {
                "kind": "target_player_loses_life",
                "amount": 3,
            },
            "tier_threshold": 1,
        },
    ],
}


# Canonical synthetic non-creature artifact Rust dict — a ``{0}``
# artifact, used as the discardable card in p1's hand.
_DUMMY_ARTIFACT_RUST_DICT = {
    "name": "Test Junk",
    "card_types": ["Artifact"],
    "subtypes": [],
    "mana_cost": {"generic": 0},
    "effects": [],
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Entropic Battlecruiser is parser-claimed and emits
# the expected Phase-3C-Cycle-3 shape.
# ---------------------------------------------------------------------------


def test_entropic_battlecruiser_parser_claims_card():
    """Pins the active CardSource is producing the Entropic
    Battlecruiser printing under its canonical EoE name.
    """
    assert "Entropic Battlecruiser" in _PRINTINGS, (
        "Entropic Battlecruiser must be parser-claimed by the active "
        "CardSource (EoE set + reprint coverage)"
    )


def test_entropic_battlecruiser_printed_attrs():
    """Pins the basic printing surface: Artifact — Spacecraft, 3/10,
    cost ``{3}{B}``, ``station_threshold=8``, stationed_keywords =
    ``{deathtouch, flying}``, TWO triggers (mode-0 ATTACKS + mode-1
    DISCARDS_CARD) with the canonical Phase-3C-Cycle-3 shape.
    """
    p = _PRINTINGS["Entropic Battlecruiser"]
    assert p.card_types == ("Artifact",)
    assert "Spacecraft" in p.subtypes
    assert p.power == 3 and p.toughness == 10
    assert p.mana_cost.generic == 3
    assert ("B", 1) in p.mana_cost.colored
    assert p.station_threshold == 8
    assert p.stationed_keywords == frozenset({"deathtouch", "flying"})
    # The §2 teeth — TWO triggers; zero static/activated; no warp /
    # spell_effect / loyalty / room_halves / cost_reductions.
    assert p.activated_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.warp_cost is None
    assert p.keywords == frozenset()
    assert len(p.triggered_abilities) == 2
    # Mode 0 — ATTACKS / IsSelf / EachOpponentDiscardsOrLosesLife.
    from mtg_bot.effects.generic.life import (
        EachOpponentDiscardsOrLosesLife,
        TargetPlayerLosesLife,
    )
    from mtg_bot.effects.predicates import Controlled, Event, IsSelf, OPPONENT
    mode_0, mode_1 = p.triggered_abilities
    assert mode_0.event is Event.ATTACKS
    assert isinstance(mode_0.predicate, IsSelf)
    assert mode_0.predicate.subject is None
    assert isinstance(mode_0.effect, EachOpponentDiscardsOrLosesLife)
    assert mode_0.effect.life_if_cant == 3
    assert mode_0.tier_threshold == 0
    assert mode_0.once_per_turn is False
    # Mode 1 — DISCARDS_CARD / Controlled(OPPONENT) / TargetPlayerLosesLife.
    # **LOAD-BEARING — the SECOND tier-gate substrate consumer.**
    assert mode_1.event is Event.DISCARDS_CARD
    assert isinstance(mode_1.predicate, Controlled)
    assert mode_1.predicate.by is OPPONENT
    assert mode_1.predicate.subject is None
    assert isinstance(mode_1.effect, TargetPlayerLosesLife)
    assert mode_1.effect.amount == 3
    assert mode_1.tier_threshold == 1, (
        "Entropic Battlecruiser's DISCARDS_CARD trigger MUST carry "
        "tier_threshold=1 — this is the SECOND Phase-3 consumer of "
        "the Cycle-1 tier-gate substrate."
    )
    assert mode_1.once_per_turn is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the C3 forward arm
# ``_spec_card_to_printing_dict`` round-trip on the genuine parsed
# Entropic Battlecruiser printing through the new dedicated admit
# predicate. Pins the canonical Rust dict shape this probe drives both
# engines through.
# ---------------------------------------------------------------------------


def test_entropic_battlecruiser_bridge_round_trip_canonical_rust_dict():
    """The C3 admit-gate's bridge: Python printing →
    :func:`_phase_3_trigger_spacecraft_card_def` → CardDef →
    ``_spec_card_to_printing_dict`` → canonical Rust registry dict
    matches ``_ENTROPIC_BATTLECRUISER_RUST_DICT`` byte-equal. Pins the
    probe's source-of-truth that both engines read the SAME printing
    shape.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    p_orig = _PRINTINGS["Entropic Battlecruiser"]
    cd = trajectory._phase_3_trigger_spacecraft_card_def(p_orig)
    assert cd is not None, (
        "Entropic Battlecruiser must pass the Phase-3C-Cycle-3 admit "
        "predicate post-FLIP"
    )
    pd = _spec_card_to_printing_dict(cd)
    # Compare modulo stationed_keywords list order (frozenset round-
    # trip is deterministic but the comparison should be order-
    # agnostic).
    pd_canon = dict(pd)
    pd_canon["stationed_keywords"] = sorted(pd["stationed_keywords"])
    expected = dict(_ENTROPIC_BATTLECRUISER_RUST_DICT)
    expected["stationed_keywords"] = sorted(expected["stationed_keywords"])
    assert pd_canon == expected, (
        f"Entropic Battlecruiser Rust registry dict must match the "
        f"probe's pinned shape (the bridge SoT for both engines); got "
        f"pd_canon={pd_canon!r}, expected={expected!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust effect-arm parse smoke — the canonical Entropic
# Battlecruiser Rust dict parses on ``register_printing``.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_canonical_entropic_battlecruiser_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Entropic
    Battlecruiser registry-dict shape — the SAME dict the C3 forward
    emit arm produces for the live Entropic Battlecruiser printing.
    Threading ``triggered_abilities`` with the new
    ``each_opponent_discards_or_loses_life`` effect kind + the
    ``target_player_loses_life`` effect kind + the
    ``controlled_by_opponent`` predicate + ``discards_card`` event +
    ``tier_threshold=1`` round-trips byte-equal through
    ``Registry.register_printing``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_ENTROPIC_BATTLECRUISER_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Entropic Battlecruiser"


# ---------------------------------------------------------------------------
# (4) Loader end-to-end admit — Entropic Battlecruiser admits at the
# deck-level filter post-Cycle-3 (the FLIP marker mirror).
# ---------------------------------------------------------------------------


def test_entropic_battlecruiser_loader_end_to_end_admit():
    """End-to-end loader admit: pass ``["Entropic Battlecruiser"]`` to
    ``_filter_deck_to_bridge_supported`` → admitted; CardDef emitted
    carries the Phase-3C-Cycle-3 two-trigger shape.
    """
    from mtg_bot.parity import trajectory
    filt, defs = trajectory._filter_deck_to_bridge_supported(
        ["Entropic Battlecruiser"], _PRINTINGS,
    )
    assert filt == ["Entropic Battlecruiser"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Entropic Battlecruiser"
    assert cd.triggered_abilities == (
        {
            "event": "attacks",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "each_opponent_discards_or_loses_life",
                "life_if_cant": 3,
            },
        },
        {
            "event": "discards_card",
            "predicate": {"kind": "controlled_by_opponent"},
            "effect": {
                "kind": "target_player_loses_life",
                "amount": 3,
            },
            "tier_threshold": 1,
        },
    )


# ---------------------------------------------------------------------------
# Picker shim for Python's discard decision.
# ---------------------------------------------------------------------------


def _make_first_hand_picker():
    """Returns an Agent that picks hand[0] (mirrors Rust's
    deterministic hand[0]-pop convention)."""
    from mtg_bot.agents import Agent

    class _PickFirstHandCard(Agent):
        def choose_discard(self, state, player_id, hand_ids):
            return hand_ids[0] if hand_ids else None

    return _PickFirstHandCard()


# ---------------------------------------------------------------------------
# (5) Scenario A — Mode-0 ATTACKS trigger, tier=0, p1 hand EMPTY.
# Mode-0 fires unconditionally; empty-hand branch: p1 loses 3 life.
# NO Event::DiscardsCard dispatched (alternative branch); mode-1 never
# observes a discard.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_entropic_battlecruiser_mode_0_empty_hand_scenario_a_parity():
    """**GENUINE real-EoE cross-engine probe — Scenario A (Mode-0
    ATTACKS, empty-hand branch). PROBED tier flip evidence (Cycle 3
    closure marker, scenario A — the life-loss alternative branch).**

    Pre-state on both engines:
      * Entropic Battlecruiser on p0's bf (unsick) with
        ``charge_counters=0``.
      * p1's hand EMPTY.
      * Both players at 20 life.

    Drive: ``declare_attacker`` / ``combat.declare_attackers``
    fires the ATTACKS trigger on both engines. The mode-0
    ``EachOpponentDiscardsOrLosesLife`` resolve walks p1's empty hand
    and fires the alternative branch: p1's life -= 3 = 17. NO
    ``Event::DiscardsCard`` is dispatched (the alternative replaces
    the discard); mode-1's DISCARDS_CARD trigger has no firing chance
    in this scenario.

    Post-resolve (both engines):
      * Stack empty.
      * Entropic Battlecruiser tapped from attacking.
      * p1 at 17 life (= 20 - 3).
      * p0 at 20 life unchanged.
      * No graveyard movement on either side (no discard happened).
    """
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    eb_printing = _PRINTINGS.get("Entropic Battlecruiser")
    if eb_printing is None:
        pytest.skip("Entropic Battlecruiser absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python side: seat Entropic Battlecruiser on p0's bf, unsick,
    # charge_counters=0.
    py_eb = py.new_object(
        eb_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_eb.summoning_sick = False
    py_eb.charge_counters = 0
    py_eb.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_eb)
    # p1's hand is empty (no setup needed).
    assert len(py.players[1].hand) == 0
    py.active_player_idx = 0
    py.priority_player_idx = 0
    # No agent invocations in this scenario — alternative branch fires
    # without needing a choose_discard pick.
    py.players[0].agent = None
    py.players[1].agent = None

    # Pre-state pin: both at 20 life.
    assert py.players[0].life == 20
    assert py.players[1].life == 20

    # ---- Rust side: same shape.
    rs_eb = rs.register_and_inject_object(
        _ENTROPIC_BATTLECRUISER_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.clear_summoning_sick_for_player(0)
    rs.set_charge_counters(rs_eb, 0)
    assert rs.life_totals == [20, 20]

    # ---- Declare Entropic Battlecruiser as attacker on both engines.
    py_declare_attackers(py, [py_eb.id])
    assert len(py.stack) == 1, (
        "Python: Entropic Battlecruiser's ATTACKS trigger MUST push "
        "onto the stack (mode-0 is tier=0, fires unconditionally)"
    )
    assert rs.declare_attacker(rs_eb) is True
    assert rs.stack_size() == 1, (
        "Rust: Entropic Battlecruiser's ATTACKS trigger MUST push onto "
        "the stack (mode-0 tier=0)"
    )

    # ---- Drain stacks (mode-0 resolves through the empty-hand
    # alternative branch — p1 loses 3 life on both engines).
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # ---- Post-resolve observables.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0

    # **The load-bearing pin** — p1 lost 3 life on both engines
    # (alternative branch fired since hand was empty).
    assert py.players[1].life == 17, (
        f"Python: p1 MUST have lost 3 life (empty-hand alternative "
        f"branch fired); got life={py.players[1].life}"
    )
    rs_lives = rs.life_totals
    assert rs_lives[1] == 17, (
        f"Rust: p1 MUST have lost 3 life (empty-hand alternative "
        f"branch fired); got life={rs_lives[1]}"
    )
    # p0's life unchanged.
    assert py.players[0].life == 20
    assert rs_lives[0] == 20
    # p1's hand still empty + graveyard still empty on Python
    # (no discard happened in the alternative branch).
    assert len(py.players[1].hand) == 0
    assert py.players[1].graveyard == []
    # Entropic Battlecruiser tapped from attacking.
    assert py_eb.tapped is True
    assert rs.is_tapped(rs_eb) is True


# ---------------------------------------------------------------------------
# (6) Scenario B — Mode-0 + Mode-1 chain, tier-1 gate OPEN (charge=1).
# Mode-0 fires + p1 discards hand[0]. DiscardsCard event dispatches +
# mode-1's tier-gate is OPEN so it fires; p1 (discarding player) is
# pre-fixed target; mode-1's TargetPlayerLosesLife(3) resolves; p1
# loses 3 more life. p1 total life loss = 3 (from mode-1).
# **LOAD-BEARING SECOND TIER-GATE CONSUMER PROOF.**
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_entropic_battlecruiser_tier_gate_open_scenario_b_parity():
    """**GENUINE real-EoE cross-engine probe — Scenario B (Mode-1
    tier-gate OPEN, charge=1 == tier=1). PROBED tier flip evidence
    (Cycle 3 closure marker, scenario B — THE LOAD-BEARING SECOND
    tier-gate-open path; proves the C1 tier-gate substrate FIRES
    correctly under real charge counters for Entropic Battlecruiser's
    mode-1 trigger).**

    Pre-state on both engines:
      * Entropic Battlecruiser on p0's bf (unsick) with
        ``charge_counters=1`` (AT the mode-1 tier_threshold=1 gate —
        exactly the load-bearing >= threshold case).
      * p1's hand has 1 card (synthetic ``{0}`` non-creature artifact;
        the only discardable card).
      * Both players at 20 life.

    Drive: ``declare_attacker`` fires the mode-0 ATTACKS trigger
    (tier=0, fires unconditionally). The mode-0 resolve walks p1's
    non-empty hand and fires the DISCARD branch — p1 discards hand[0]
    (deterministic first-pick via the agent shim on Python, hand[0]
    pop on Rust). ``Event::DiscardsCard`` is dispatched on p1's
    subject AFTER the card moves to graveyard. The mode-1 trigger
    on Entropic Battlecruiser observes the DISCARDS_CARD event:
      - Mode-1's predicate ``Controlled(OPPONENT)`` matches (p1 is
        Entropic Battlecruiser's opponent — controller is p0).
      - Mode-1's tier-gate at ``state_ops_resolve.rs::dispatch_event``
        sees ``tier_threshold=1`` AND ``source.charge_counters=1 >= 1``
        and ADMITS the firing.
      - Mode-1 is pushed onto the stack with the discarding player
        (p1) as the pre-fixed target via the new
        ``resolving_discards_card_player_id`` slot (Rust) /
        ``fire_opponent_discards_triggers``'s ``fixed_targets=(("player",
        p1.id),)`` (Python).
      - Mode-1 resolves through the ``TargetPlayerLosesLife(3)`` arm
        → p1's life -= 3 = 17.

    Post-resolve (both engines):
      * Stack empty.
      * Entropic Battlecruiser tapped from attacking.
      * p1 at 17 life (= 20 - 3 from mode-1 life loss).
      * p1's hand empty.
      * p1's graveyard has the discarded artifact.
      * p0 at 20 life unchanged.
    """
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    eb_printing = _PRINTINGS.get("Entropic Battlecruiser")
    if eb_printing is None:
        pytest.skip("Entropic Battlecruiser absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: synthetic ``{0}`` non-creature artifact in p1's hand
    # (mirrors _DUMMY_ARTIFACT_RUST_DICT exactly).
    junk_printing = CardPrinting(
        name="Test Junk",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
    )

    # ---- Python side: Entropic Battlecruiser on p0's bf, unsick,
    # charge=1; synthetic junk in p1's hand.
    py_eb = py.new_object(
        eb_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_eb.summoning_sick = False
    py_eb.charge_counters = 1
    py_eb.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_eb)
    py_junk = py.new_object(
        junk_printing, owner_id=1, zone=Zone.HAND,
    )
    py.players[1].hand.append(py_junk)
    py.active_player_idx = 0
    py.priority_player_idx = 0
    # Picker shim on p1 — picks hand[0] for choose_discard.
    py.players[0].agent = None
    py.players[1].agent = _make_first_hand_picker()

    # Pre-state pins.
    assert py.players[0].life == 20
    assert py.players[1].life == 20
    assert len(py.players[1].hand) == 1
    assert py.players[1].graveyard == []

    # ---- Rust side: same shape.
    rs_eb = rs.register_and_inject_object(
        _ENTROPIC_BATTLECRUISER_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.clear_summoning_sick_for_player(0)
    rs.set_charge_counters(rs_eb, 1)
    rs_junk = rs.register_and_inject_object(
        _DUMMY_ARTIFACT_RUST_DICT, 1, ZONE_HAND,
    )
    assert rs.life_totals == [20, 20]
    assert rs.find_object_zone(rs_junk) == ZONE_HAND

    # ---- Declare Entropic Battlecruiser as attacker.
    py_declare_attackers(py, [py_eb.id])
    assert len(py.stack) == 1, (
        "Python: Entropic Battlecruiser's mode-0 ATTACKS trigger MUST "
        "push onto the stack"
    )
    assert rs.declare_attacker(rs_eb) is True
    assert rs.stack_size() == 1, (
        "Rust: Entropic Battlecruiser's mode-0 ATTACKS trigger MUST "
        "push onto the stack"
    )

    # ---- Drain stacks (mode-0 resolves, p1 discards, mode-1 fires
    # via the tier-1 gate, mode-1 resolves, p1 loses 3 life).
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # ---- Post-resolve observables (the load-bearing pins).
    assert len(py.stack) == 0
    assert rs.stack_size() == 0

    # **Python: p1 discarded the junk + lost 3 life (mode-1 fired).**
    assert py.players[1].life == 17, (
        f"Python: p1 MUST have lost 3 life (mode-1 DISCARDS_CARD trigger "
        f"fired via tier-1 gate OPEN at charge=1); got life="
        f"{py.players[1].life}"
    )
    assert len(py.players[1].hand) == 0, (
        f"Python: p1's hand MUST be empty after the discard; got "
        f"{len(py.players[1].hand)} cards"
    )
    assert len(py.players[1].graveyard) == 1, (
        f"Python: p1's graveyard MUST contain the discarded card; got "
        f"{len(py.players[1].graveyard)} cards"
    )
    assert py.players[0].life == 20

    # **Rust: p1 discarded the junk + lost 3 life via mode-1.**
    rs_lives_b = rs.life_totals
    assert rs_lives_b[1] == 17, (
        f"Rust: p1 MUST have lost 3 life via mode-1 (the SECOND tier-"
        f"gate consumer of the C1 substrate, tier=1 gate OPEN at "
        f"charge=1); got life={rs_lives_b[1]}"
    )
    assert rs.find_object_zone(rs_junk) == ZONE_GRAVEYARD, (
        f"Rust: the discarded artifact MUST be in the graveyard; got "
        f"zone={rs.find_object_zone(rs_junk)}"
    )
    assert rs_lives_b[0] == 20

    # Entropic Battlecruiser tapped from attacking.
    assert py_eb.tapped is True
    assert rs.is_tapped(rs_eb) is True
    # Entropic Battlecruiser's charge_counters unchanged on both engines
    # (mode-1 firing doesn't consume the charge — the gate is a read).
    assert py_eb.charge_counters == 1
    assert rs.get_charge_counters(rs_eb) == 1


# ---------------------------------------------------------------------------
# (7) Scenario C — Mode-1 tier-1 gate CLOSED (charge=0, below tier=1).
# Mode-0 fires + p1 discards. DISCARDS_CARD dispatches. BUT mode-1's
# tier-gate is CLOSED so mode-1 does NOT fire; p1 keeps 20 life
# (modulo the lack of mode-1 life loss).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_entropic_battlecruiser_mode_1_tier_gate_closed_scenario_c_parity():
    """**GENUINE real-EoE cross-engine probe — Scenario C (Mode-1
    tier-gate CLOSED, charge=0 < tier=1). PROBED tier flip evidence
    (Cycle 3 closure marker, scenario C — the tier-gate-closed silent
    decline path for mode-1; sibling of the Synthesizer Labship
    Scenario A pin for the BEGINNING_OF_COMBAT family).**

    Pre-state on both engines:
      * Entropic Battlecruiser on p0's bf (unsick) with
        ``charge_counters=0`` (BELOW the mode-1 tier_threshold=1).
      * p1's hand has 1 card.
      * Both players at 20 life.

    Drive: ``declare_attacker`` fires mode-0 (tier=0, always).
    Mode-0 resolve discards p1's hand[0] → DISCARDS_CARD dispatched.
    Mode-1 observes the event but the tier-gate at
    ``state_ops_resolve.rs::dispatch_event`` sees
    ``tier_threshold=1`` AND ``source.charge_counters=0 < 1`` and
    SKIPS the firing (skip via the ``_ => continue`` arm in the
    tier-gate match). Python's ``should_fire_trigger`` enforces the
    SAME gate.

    Post-resolve (both engines):
      * Stack empty.
      * Entropic Battlecruiser tapped from attacking.
      * p1 at 20 life UNCHANGED (no mode-1 life loss).
      * p1's hand empty + graveyard has the discarded card (mode-0
        fired normally; only mode-1 is gated off).
      * p0 at 20 life unchanged.
    """
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    eb_printing = _PRINTINGS.get("Entropic Battlecruiser")
    if eb_printing is None:
        pytest.skip("Entropic Battlecruiser absent from active CardSource")

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    junk_printing = CardPrinting(
        name="Test Junk",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
    )

    # ---- Python side: Entropic Battlecruiser on p0's bf, unsick,
    # charge=0 (BELOW tier=1); synthetic junk in p1's hand.
    py_eb = py.new_object(
        eb_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_eb.summoning_sick = False
    py_eb.charge_counters = 0
    py_eb.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_eb)
    py_junk = py.new_object(
        junk_printing, owner_id=1, zone=Zone.HAND,
    )
    py.players[1].hand.append(py_junk)
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.players[0].agent = None
    py.players[1].agent = _make_first_hand_picker()

    assert py.players[1].life == 20

    # ---- Rust side: same shape.
    rs_eb = rs.register_and_inject_object(
        _ENTROPIC_BATTLECRUISER_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.clear_summoning_sick_for_player(0)
    rs.set_charge_counters(rs_eb, 0)
    rs_junk = rs.register_and_inject_object(
        _DUMMY_ARTIFACT_RUST_DICT, 1, ZONE_HAND,
    )
    assert rs.life_totals == [20, 20]

    # ---- Declare Entropic Battlecruiser as attacker.
    py_declare_attackers(py, [py_eb.id])
    assert rs.declare_attacker(rs_eb) is True

    # ---- Drain stacks (mode-0 fires + p1 discards + DISCARDS_CARD
    # dispatched, BUT mode-1 is gated off by tier-1 gate closed).
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # ---- Post-resolve observables.
    assert len(py.stack) == 0
    assert rs.stack_size() == 0

    # **The load-bearing pin** — p1 still at 20 life on both engines
    # (mode-1 did NOT fire because tier-gate is closed).
    assert py.players[1].life == 20, (
        f"Python: p1 MUST still be at 20 life (mode-1 DISCARDS_CARD "
        f"trigger gated off — tier=1 > charge=0); got life="
        f"{py.players[1].life}"
    )
    rs_lives_c = rs.life_totals
    assert rs_lives_c[1] == 20, (
        f"Rust: p1 MUST still be at 20 life (mode-1 tier-gate CLOSED); "
        f"got life={rs_lives_c[1]}"
    )

    # Mode-0 STILL fired normally — p1 still discarded.
    assert len(py.players[1].hand) == 0, (
        "Python: mode-0 fires normally (tier=0); p1's hand MUST be "
        "empty after the discard"
    )
    assert len(py.players[1].graveyard) == 1, (
        "Python: mode-0 discard branch fired; the discarded artifact "
        "MUST be in p1's graveyard"
    )
    assert rs.find_object_zone(rs_junk) == ZONE_GRAVEYARD, (
        "Rust: mode-0 discarded the junk to p1's graveyard"
    )
    # p0's life unchanged.
    assert py.players[0].life == 20
    assert rs_lives_c[0] == 20
