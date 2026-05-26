"""Cracked Skull — per-card real-EoE probe (``covered_by_
construction`` -> PROBED tier flip; Aura-attachment substrate Phase 3+
Phase B Cycle 2 closure marker for Scenarios 1+2+3 per design doc
``docs/AURA_ATTACH_SUBSTRATE_PHASE_3_DESIGN.md`` section 7 row 3).

Cracked Skull is a ``{2}{B}`` Enchantment - Aura in the EoE pool
(positive-control carrier; 0 17lands decks per design doc section 0
row 2 — the deck-count signal is on substrate correctness, not deck
volume). Live trigger surface:

    Mana cost: {2}{B}
    Enchant creature
    Triggered ability A (the ENTERS long pole; Cycle 2 admit Shape A):
        event       = Event.ENTERS
        predicate   = IsSelf(subject=None)
        effect      = TargetOpponentLookHandMayDiscard()
        once_per_turn = False
    Triggered ability B (Tail-X1, the damage-echo destroy tail —
    shared with Sporogenic Infection per design doc section 3):
        event       = Event.DEALT_DAMAGE
        predicate   = IsHost(subject=None)
        effect      = DestroyEnchantedPermanent()
        once_per_turn = False

Per design doc section 3 (Phase B carrier) + section 7 row 3 (Cracked
Skull probe spec).

**Multi-cycle DECLINED -> ADMITTED -> PROBED transition.**

  * **Phase B Cycle 1 (Rust substrate landing, commit ``1e0788ff``,
    2026-05-26).** Rust substrate: new
    ``Effect::TargetOpponentLookHandMayDiscard`` unit variant on
    ``cards.rs::Effect`` + parse / to_pydict / resolve arms + two new
    ``PendingDecision`` variants (``MayDiscardChoice`` +
    ``OpponentHandCardChoice``) + ``submit_may_discard_decision`` /
    ``submit_opponent_hand_card_decision`` py-methods + one-way reveal
    bitfield (``publicly_known_to_caster_bits: u32`` on GameObject) +
    cross-engine bridge dict-to-Python arm in ``cross_engine.py`` +
    reverse-serializer leaf in ``trajectory.py`` (DORMANT-by-construction).
    Cracked Skull STAYED DECLINED at every admit gate (substrate-only
    invariant pin at ``test_cracked_skull_stays_declined_at_admit_gate_
    post_cycle_1``).
  * **Phase B Cycle 2 (THE FLIP, this slice, 2026-05-26).** Widen
    :func:`_aura_triggers_are_phase3_safe` with TWO new admit shapes
    in lockstep (the all-or-nothing gate refuses partial admission —
    Cracked Skull's two TAs MUST widen together):

      - Shape A: ``ENTERS + IsSelf(subject=None) +
        TargetOpponentLookHandMayDiscard``.
      - Tail-X1: ``DEALT_DAMAGE + IsHost(subject=None) +
        DestroyEnchantedPermanent``.

    Widen :func:`_python_ta_to_safe_dict_aura_phase3` with the
    matching Tail-X1 emitter arm (the look-may-discard arm was pre-
    positioned in C1). Cracked Skull DECLINED -> ADMITTED (the +0
    deck flip — positive-control carrier; admit set grows by ONE
    Aura). The C1 substrate-only invariant pin inverted in-place
    (``test_cracked_skull_now_admits_at_admit_gate_post_cycle_2``).
    The Tail-X1 widen ALSO positions Sporogenic Infection for Phase
    C closure (Sporogenic shares the same Tail-X1 shape; Phase C
    closes Sporogenic by adding its ENTERS half
    ``TargetOpponentSacrificesCreatureOtherThanEnchanted``).
  * **Phase B Cycle 2 (THIS LANE; THE PROBE — Scenarios 1+2+3).**
    Per-card real-EoE probe driving the **actual live Cracked Skull
    printing** (resolved via :class:`OracleParserCardSource`, NOT a
    synthetic CardDef — the real-EoE-signal discipline) through three
    scenarios:

    (1) **The ETB resolve + may-discard yes path.** Attach Cracked
        Skull to a host on caster's bf; seed the target opponent's
        hand with TWO nonland cards + ONE land. Drive the ETB
        trigger via ``_trigger_etb_abilities``; the trigger queues,
        targets the opponent (first legal player target), and on
        resolve walks the hand: stamps publicly_known_to (one-way
        reveal), gates on nonland-options non-empty, then calls
        caster.agent.choose_yes_no -> YES (the
        ``_YesPickFirstAgent`` default), then
        choose_card_from_opponent_hand -> first nonland. The opponent
        discards that nonland card to their graveyard. The land
        stays.
    (2) **ETB resolve + may-discard NO path (decline).** Same setup;
        caster.agent.choose_yes_no -> NO (the
        ``_NoDeclineAgent``). The look-step still stamps
        publicly_known_to (one-way reveal happens before the may
        gate), but no card moves. The full opponent hand stays
        intact.
    (3) **Combat damage path — Tail-X1 DestroyEnchantedPermanent.**
        Cracked Skull attached to caster's host bear on bf;
        opponent's blocker takes combat damage from Cracked Skull's
        host (via ``_fire_enchanted_dealt_damage_triggers`` mirror
        — direct invocation of the dispatch_event path). Cracked
        Skull's Tail-X1 fires: DEALT_DAMAGE + IsHost matches when
        an attached aura's attached_to == obj.id; the
        DestroyEnchantedPermanent effect reads
        ``state.resolving_source`` (Cracked Skull) and destroys
        ``aura.attached_to`` (the host bear). The host leaves the
        battlefield; Cracked Skull falls off as state-based action
        (CR 704.5n — Aura attached to nothing goes to graveyard).

**Scripted-picker semantics.** Scenarios 1 and 2 use scripted agents
(``_YesPickFirstAgent`` / ``_NoDeclineAgent``) on the caster so the
ETB-trigger fan-out's target-pick, the may-discard yes/no gate, and
the directed-discard card pick all resolve deterministically.
Mirrors Rust's deterministic-first auto-resolve defaults for
``PendingDecision::MayDiscardChoice`` (default YES per C1 substrate
at ``auto_resolve_pending`` MayDiscard arm) and
``PendingDecision::OpponentHandCardChoice`` (default candidates[0]).

**Cross-engine byte-equal pin (Scenario 3 Tail-X1 deferred).** This
slice (Python-only per the Worker-A delivery scope) lands all three
scenarios as Python-engine real-EoE probes; the cross-engine byte-
equal pin for Scenarios 1 (ETB push site of MayDiscardChoice via
the ENTERS-trigger fan-out at ``first_legal_trigger_target``) and 3
(Tail-X1 DEALT_DAMAGE dispatch into DestroyEnchantedPermanent's
resolve) is deferred to a follow-up Rust slice — same honest-stop
shape Phase A's Chorale parity took (Scenario 1 cross-engine
deferred at ``test_chorale_of_the_void_parity.py``). The admit-
gate flip is the load-bearing Cycle 2 evidence; the per-card real-
EoE Python-engine probe pins the substrate's correctness on the
live carrier.

**Real-EoE-signal discipline.** This module uses the live
``OracleParserCardSource`` Cracked Skull printing on the Python
side — the SAME printing the loader admits at the bench filter.

This module is the Aura-attachment Phase B closure marker; Phase C
(Sporogenic Infection) is the next cycle per design doc section 8
row 5-7.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


# Skip Rust-engine probes if the extension isn't built. (Cycle 2's
# probe is Python-only; reserved for the follow-up cross-engine slice.)
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


class _YesPickFirstAgent(Agent):
    """Scripted picker — answers Yes to the may-discard gate and picks
    the first legal target / first card from opponent hand.

    Mirrors Rust's deterministic-first auto-resolve defaults:
      - ``PendingDecision::MayDiscardChoice`` default YES (per C1
        substrate at ``auto_resolve_pending_decisions``).
      - ``PendingDecision::OpponentHandCardChoice`` default
        ``candidates[0]``.
    """

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_yes_no(self, state, player_id, prompt):
        return True

    def choose_card_from_opponent_hand(
        self, state, player_id, opponent_hand_ids,
    ):
        return opponent_hand_ids[0] if opponent_hand_ids else None


class _NoDeclineAgent(Agent):
    """Scripted picker — answers No to the may-discard gate (declines
    the directed discard). Used by Scenario 2.
    """

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_yes_no(self, state, player_id, prompt):
        return False

    def choose_card_from_opponent_hand(
        self, state, player_id, opponent_hand_ids,
    ):
        # Should not be reached — choose_yes_no returns False first.
        return opponent_hand_ids[0] if opponent_hand_ids else None


# ---------------------------------------------------------------------------
# (1) Parser SoT — Cracked Skull is parser-claimed and emits the
# expected TWO-trigger Phase-3+ Phase-B shape.
# ---------------------------------------------------------------------------


def test_cracked_skull_parser_claims_card():
    """Pins the active CardSource is producing the Cracked Skull
    printing under its canonical EoE name.
    """
    assert "Cracked Skull" in _PRINTINGS, (
        "Cracked Skull must be parser-claimed by the active "
        "CardSource (EoE set + reprint coverage)"
    )


def test_cracked_skull_printed_attrs():
    """Pins the basic printing surface: Enchantment - Aura, cost
    ``{2}{B}``, ``aura_enchant_type='creature'``, TWO triggered
    abilities with the canonical Phase-3+ Phase-B shape (the section
    2 teeth — the admit predicate's load-bearing gates).
    """
    from mtg_bot.effects.generic.destroy import DestroyEnchantedPermanent
    from mtg_bot.effects.generic.discard import (
        TargetOpponentLookHandMayDiscard,
    )
    from mtg_bot.effects.predicates import Event, IsHost, IsSelf

    p = _PRINTINGS["Cracked Skull"]
    assert p.is_aura is True
    assert p.aura_enchant_type == "creature"
    # The section 2 teeth — no static / activated / spell-effect /
    # warp / cost-reduction riders.
    assert p.activated_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.warp_cost is None
    # Two triggered abilities (the Phase-B long pole + Tail-X1).
    assert len(p.triggered_abilities) == 2
    ta_etb, ta_dd = p.triggered_abilities
    # Shape A: ENTERS + IsSelf(subject=None) +
    # TargetOpponentLookHandMayDiscard.
    assert ta_etb.event is Event.ENTERS
    assert isinstance(ta_etb.predicate, IsSelf)
    assert ta_etb.predicate.subject is None
    assert isinstance(ta_etb.effect, TargetOpponentLookHandMayDiscard)
    assert ta_etb.once_per_turn is False
    # Tail-X1: DEALT_DAMAGE + IsHost(subject=None) +
    # DestroyEnchantedPermanent.
    assert ta_dd.event is Event.DEALT_DAMAGE
    assert isinstance(ta_dd.predicate, IsHost)
    assert ta_dd.predicate.subject is None
    assert isinstance(ta_dd.effect, DestroyEnchantedPermanent)
    assert ta_dd.once_per_turn is False


# ---------------------------------------------------------------------------
# (2) Loader admit pin — Cracked Skull now admits at the bench loader
# post Phase-B-Cycle-2 widen.
# ---------------------------------------------------------------------------


def test_sporogenic_infection_stays_declined_post_phase_b_cycle_2():
    """**No-silent-auto-grow guard.** Sporogenic Infection shares
    Tail-X1 (DEALT_DAMAGE + IsHost + DestroyEnchantedPermanent) with
    Cracked Skull and is positioned for Phase C closure by THIS
    slice's Tail-X1 widen — but its ENTERS half carries
    ``TargetOpponentSacrificesCreatureOtherThanEnchanted`` which is
    NOT in the Phase-3 safe set yet (Phase C adds it). The all-or-
    nothing gate keeps Sporogenic DECLINED until Phase C closure.
    """
    from mtg_bot.parity import trajectory

    p = _PRINTINGS["Sporogenic Infection"]
    assert (
        trajectory._aura_triggers_are_phase3_safe(p.triggered_abilities)
        is False
    )
    assert trajectory._printing_is_bridge_simple_aura(p) is False


def test_cryoshatter_stays_declined_post_phase_b_cycle_2():
    """**No-silent-auto-grow guard.** Cryoshatter is ALSO an Aura whose
    Tail half is exactly Tail-X1 (DEALT_DAMAGE + IsHost +
    DestroyEnchantedPermanent), but its OTHER trigger is
    ``BECOMES_TAPPED + IsHost + DestroyEnchantedPermanent`` —
    BECOMES_TAPPED is NOT in the Phase-3 safe set today. The all-or-
    nothing gate keeps Cryoshatter DECLINED (would-be silent auto-
    grow blocked).
    """
    from mtg_bot.parity import trajectory

    p = _PRINTINGS["Cryoshatter"]
    assert (
        trajectory._aura_triggers_are_phase3_safe(p.triggered_abilities)
        is False
    )
    assert trajectory._printing_is_bridge_simple_aura(p) is False


def test_cracked_skull_loader_admits_post_phase_b_cycle_2():
    """**The +0 deck positive-control flip — load-bearing admit pin.**
    The live Cracked Skull printing now admits at the loader filter
    (Phase B Cycle 2 widen).
    """
    from mtg_bot.parity import trajectory

    p_orig = _PRINTINGS["Cracked Skull"]
    assert trajectory._printing_is_bridge_simple_aura(p_orig) is True


def test_cracked_skull_loader_emits_canonical_dict():
    """**Forward bridge round-trip.** The live Cracked Skull printing
    flows through ``_printing_to_card_def`` -> ``_spec_card_to_
    printing_dict`` -> canonical Rust registry dict matches the
    expected Phase-B shape. Pins the probe's source-of-truth that
    Rust reads the same printing shape Python does.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    p_orig = _PRINTINGS["Cracked Skull"]
    cd = trajectory._printing_to_card_def(p_orig)
    assert cd is not None
    pd = _spec_card_to_printing_dict(cd)
    assert pd["name"] == "Cracked Skull"
    assert pd["is_aura"] is True
    assert pd["aura_enchant_type"] == "creature"
    assert len(pd["triggered_abilities"]) == 2
    # Order is parser-order: ENTERS then DEALT_DAMAGE.
    assert pd["triggered_abilities"][0] == {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "target_opponent_look_hand_may_discard"},
        "once_per_turn": False,
    }
    assert pd["triggered_abilities"][1] == {
        "event": "dealt_damage",
        "predicate": {"kind": "is_host"},
        "effect": {"kind": "destroy_enchanted_permanent"},
        "once_per_turn": False,
    }


def test_cracked_skull_loader_end_to_end_admit():
    """End-to-end loader admit: pass ``["Cracked Skull"]`` to
    ``_filter_deck_to_bridge_supported`` -> admitted; CardDef emitted
    carries the Phase-3+ Phase-B trigger shape.
    """
    from mtg_bot.parity import trajectory

    filt, defs = trajectory._filter_deck_to_bridge_supported(
        ["Cracked Skull"], _PRINTINGS,
    )
    assert filt == ["Cracked Skull"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Cracked Skull"
    assert cd.is_aura is True
    assert len(cd.triggered_abilities) == 2


# ---------------------------------------------------------------------------
# (3) Rust unit pin — the canonical Cracked Skull Rust dict registers
# cleanly on ``register_printing``.
# ---------------------------------------------------------------------------


# Canonical Rust registry dict for Cracked Skull — what the forward arm
# ``_spec_card_to_printing_dict(_printing_to_card_def(p))`` emits.
_CRACKED_SKULL_RUST_DICT = {
    "name": "Cracked Skull",
    "card_types": ["Enchantment"],
    "is_aura": True,
    "aura_enchant_type": "creature",
    "mana_cost": {"generic": 2, "B": 1},
    "effects": [],
    "triggered_abilities": [
        {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {"kind": "target_opponent_look_hand_may_discard"},
            "once_per_turn": False,
        },
        {
            "event": "dealt_damage",
            "predicate": {"kind": "is_host"},
            "effect": {"kind": "destroy_enchanted_permanent"},
            "once_per_turn": False,
        },
    ],
}


@_rust_skip
def test_rust_parser_accepts_canonical_cracked_skull_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Cracked
    Skull registry dict — the SAME dict the C2 forward arm produces
    for the live Cracked Skull printing. Threading
    ``triggered_abilities`` with both halves
    (TargetOpponentLookHandMayDiscard + DestroyEnchantedPermanent)
    round-trips byte-equal through ``Registry.register_printing``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_CRACKED_SKULL_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Cracked Skull"


# ---------------------------------------------------------------------------
# (4) Scenario 1 — ETB resolve + may-discard YES path.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_cracked_skull_etb_may_discard_yes_scenario_1_parity():
    """**Scenario 1 — THE LOAD-BEARING ETB may-discard YES path.**
    Drives the live Cracked Skull printing through its ENTERS-trigger
    long pole on the Python engine:

      Pre-state:
        * p0's Wild Bear on bf (the host).
        * p1's hand has TWO nonland creature cards (Wild Bear, Wild
          Bear) and ONE land card (Forest).
        * p0's agent is ``_YesPickFirstAgent`` (says yes to may-
          discard; picks first nonland).

      Drive: put Cracked Skull onto p0's bf attached to host_bear,
      then call ``_trigger_etb_abilities`` to fire its ENTERS trigger.
      The trigger queues + targets p1 (the only legal opponent
      target). On resolve:
        * The look-step stamps publicly_known_to with p0 on EVERY
          card in p1's hand (one-way reveal).
        * Nonland options (the two bears) gate non-empty -> proceed.
        * choose_yes_no -> True -> proceed.
        * choose_card_from_opponent_hand -> the first bear's id.
        * That bear leaves p1's hand and lands on p1's graveyard.

      Post-resolve:
        * p1's hand: ONE bear + ONE forest (the other nonland card
          and the land remain).
        * p1's graveyard: ONE bear (the discarded one).
        * Stack empty.
    """
    from mtg_bot.actions import drain_stack
    from mtg_bot.game import GameState, Player, Zone, reveal_to as _r
    from mtg_bot.actions import _trigger_etb_abilities  # noqa: F401

    state = GameState()
    state.players.append(Player(id=0, agent=_YesPickFirstAgent()))
    state.players.append(Player(id=1, agent=_YesPickFirstAgent()))
    state.active_player_idx = 0

    # p0's host bear on bf (unsick).
    host_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    host_bear.summoning_sick = False
    state.battlefield.append(host_bear)

    # p1's hand: two nonland creature cards + one land.
    hand_bear_1 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.HAND,
    )
    hand_bear_2 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.HAND,
    )
    hand_forest = state.new_object(
        _PRINTINGS["Forest"], owner_id=1, zone=Zone.HAND,
    )
    state.players[1].hand.extend([hand_bear_1, hand_bear_2, hand_forest])

    # p0's Cracked Skull on bf, attached to the host bear (mirrors
    # the bench-loader admit-then-attach flow; the ENTERS trigger is
    # the long pole the probe drives).
    cracked = state.new_object(
        _PRINTINGS["Cracked Skull"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    cracked.attached_to = host_bear.id
    state.battlefield.append(cracked)

    # ---- Drive: ENTERS-trigger fan-out for Cracked Skull (the Aura
    # itself entering -> IsSelf(subject=None) matches; the trigger
    # pushes a stack item; resolve walks the TargetOpponentLookHand
    # MayDiscard.resolve path).
    from mtg_bot.actions import _trigger_etb_abilities as _eat
    _eat(state, cracked)
    drain_stack(state)

    # ---- Post-resolve observables.
    # Look-step stamped publicly_known_to (one-way reveal).
    for c in (hand_bear_1, hand_bear_2, hand_forest):
        if c is hand_bear_1:
            # The discarded one moved zones; check via direct flag
            # (the look-step ran BEFORE the discard).
            pass
        else:
            assert 0 in c.publicly_known_to, (
                f"{c.printing.name} must be publicly_known_to p0 "
                f"(one-way reveal during the look-step)"
            )
    # The discarded bear (first nonland in scan order) moved to p1's
    # graveyard.
    assert hand_bear_1 in state.players[1].graveyard, (
        "First nonland (hand_bear_1) must have been discarded"
    )
    assert hand_bear_1 not in state.players[1].hand
    # The other bear + the land STILL in p1's hand.
    assert hand_bear_2 in state.players[1].hand
    assert hand_forest in state.players[1].hand
    # Stack drained.
    assert state.stack == []


# ---------------------------------------------------------------------------
# (5) Scenario 2 — ETB resolve + may-discard NO path (decline).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_cracked_skull_etb_may_discard_no_scenario_2_parity():
    """**Scenario 2 — End-step with may-discard declined.** Drives the
    ENTERS-trigger long pole with the may-gate answering No:

      Pre-state:
        * p0's Wild Bear on bf (the host).
        * p1's hand has TWO nonland creature cards (Wild Bear, Wild
          Bear) and ONE land card (Forest).
        * p0's agent is ``_NoDeclineAgent`` (says no to may-discard).

      Drive: Cracked Skull on p0's bf attached to host_bear; fire its
      ENTERS trigger. Resolve walks:
        * look-step stamps publicly_known_to on EVERY card in p1's
          hand (the look happens BEFORE the may gate per the printed
          text — caster sees the hand even if they decline).
        * Nonland options non-empty -> proceed to the may gate.
        * choose_yes_no -> False -> silent fizzle; no discard.

      Post-resolve:
        * p1's hand: TWO bears + ONE forest (intact — nothing
          discarded).
        * p1's graveyard: EMPTY.
        * publicly_known_to_caster stamped on every hand card (the
          one-way reveal ran before the gate).
    """
    from mtg_bot.actions import drain_stack
    from mtg_bot.actions import _trigger_etb_abilities as _eat
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=_NoDeclineAgent()))
    state.players.append(Player(id=1, agent=_NoDeclineAgent()))
    state.active_player_idx = 0

    host_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    host_bear.summoning_sick = False
    state.battlefield.append(host_bear)

    hand_bear_1 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.HAND,
    )
    hand_bear_2 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.HAND,
    )
    hand_forest = state.new_object(
        _PRINTINGS["Forest"], owner_id=1, zone=Zone.HAND,
    )
    state.players[1].hand.extend([hand_bear_1, hand_bear_2, hand_forest])

    cracked = state.new_object(
        _PRINTINGS["Cracked Skull"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    cracked.attached_to = host_bear.id
    state.battlefield.append(cracked)

    # ---- Drive: ENTERS-trigger fan-out for Cracked Skull.
    _eat(state, cracked)
    drain_stack(state)

    # ---- Post-resolve observables: nothing moved.
    # All three hand cards remain in p1's hand.
    assert hand_bear_1 in state.players[1].hand
    assert hand_bear_2 in state.players[1].hand
    assert hand_forest in state.players[1].hand
    # p1's graveyard empty.
    assert state.players[1].graveyard == []
    # publicly_known_to stamped on each (one-way reveal ran before the
    # decline).
    assert 0 in hand_bear_1.publicly_known_to
    assert 0 in hand_bear_2.publicly_known_to
    assert 0 in hand_forest.publicly_known_to
    # Stack drained.
    assert state.stack == []


# ---------------------------------------------------------------------------
# (6) Scenario 3 — Combat damage path, Tail-X1 DestroyEnchantedPermanent.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_cracked_skull_dealt_damage_destroy_host_scenario_3_parity():
    """**Scenario 3 — Tail-X1 DEALT_DAMAGE destroys the enchanted host.**
    Drives the second triggered ability via the
    ``_fire_enchanted_dealt_damage_triggers`` dispatch (the same
    centralized fire site combat damage uses):

      Pre-state:
        * p0's Wild Bear on bf (the host) attached to Cracked Skull.

      Drive: call
      ``_fire_enchanted_dealt_damage_triggers(state, host_bear, 1)``
      directly (the same dispatch_event Event.DEALT_DAMAGE call
      combat code uses; the amount carries through to the resolving
      effect via state.resolving_combat_damage_amount). Cracked
      Skull's IsHost predicate matches (its attached_to == host_bear.id).
      The trigger queues + resolves; the
      DestroyEnchantedPermanent.resolve arm reads
      ``state.resolving_source`` (Cracked Skull) and destroys its
      attached_to (the host bear). Then a CR 704.5n state-based
      action sweeps Cracked Skull off the battlefield because its
      enchanted host is gone.

      Post-resolve:
        * host_bear OFF bf (destroyed -> p0's graveyard).
        * Cracked Skull OFF bf (CR 704.5n SBA: Aura attached to
          nothing -> graveyard).
    """
    from mtg_bot.actions import drain_stack
    from mtg_bot.combat import _fire_enchanted_dealt_damage_triggers
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import state_based_actions

    state = GameState()
    state.players.append(Player(id=0, agent=_YesPickFirstAgent()))
    state.players.append(Player(id=1, agent=_YesPickFirstAgent()))
    state.active_player_idx = 0

    host_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    host_bear.summoning_sick = False
    state.battlefield.append(host_bear)

    cracked = state.new_object(
        _PRINTINGS["Cracked Skull"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    cracked.attached_to = host_bear.id
    state.battlefield.append(cracked)

    # Sanity pre-state.
    assert host_bear in state.battlefield
    assert cracked in state.battlefield
    assert cracked.attached_to == host_bear.id

    # ---- Drive: enchanted creature is dealt 1 damage -> Tail-X1
    # fires. (Combat damage assignment goes through this same dispatch
    # in production; calling it directly is the surgical probe of the
    # Tail-X1 trigger -> DestroyEnchantedPermanent resolve path.)
    _fire_enchanted_dealt_damage_triggers(state, host_bear, 1)
    drain_stack(state)
    # Extra SBA pass to clean up the Aura-attached-to-nothing CR
    # 704.5n state (drain_stack already runs SBAs after each
    # resolve, but the host destroyed inside the trigger resolve
    # is removed by the destroy helper, then the post-resolve SBA
    # walks Aura attachment and sweeps Cracked Skull).
    state_based_actions(state)

    # ---- Post-resolve observables.
    assert host_bear not in state.battlefield, (
        "Host bear must be destroyed by Cracked Skull's Tail-X1"
    )
    assert host_bear in state.players[0].graveyard, (
        "Host bear must move to p0's graveyard via destroy"
    )
    # Cracked Skull falls off via CR 704.5n SBA (Aura attached to
    # nothing).
    assert cracked not in state.battlefield, (
        "Cracked Skull must fall off via CR 704.5n SBA after host "
        "leaves"
    )
    assert state.stack == []
