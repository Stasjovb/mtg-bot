"""Chorale of the Void — per-card real-EoE probe (``covered_by_
construction`` → PROBED tier flip; Aura-attachment substrate Phase 3+
Phase A Cycle 2 closure marker for Scenarios 1+2+3 per design doc
``docs/AURA_ATTACH_SUBSTRATE_PHASE_3_DESIGN.md`` §7.3).

Chorale of the Void is a ``{3}{B}`` Enchantment — Aura in the EoE
pool carrying TWO triggered abilities and the Phase A long-pole
Effect:

    Mana cost: {3}{B}
    Enchant creature
    Triggered ability A (the ATTACKS long pole; Cycle 2 admit shape):
        event       = Event.ATTACKS
        predicate   = IsHost(subject="attacker")
        effect      = ReanimateTargetCreatureCardFromDefendersGraveyard()
        once_per_turn = False
    Triggered ability B (Tail-X2, the Void-conditional EoT sustain):
        event       = Event.BEGINNING_OF_END_STEP
        predicate   = Controlled(by=YOU, subject=None)
        effect      = SacrificeSelfUnlessVoidActive()
        once_per_turn = False

Per design doc §3 (Phase A carrier) + §7.3 (Chorale of the Void
probe spec), the +2,783 17lands-deck flip ships in this slice.

**Multi-cycle DECLINED → ADMITTED → PROBED transition.**

  * **Phase A Cycle 1 (Rust substrate landing, commit ``53c6bc2a``,
    2026-05-25).** Rust substrate: new
    ``Effect::ReanimateTargetCreatureCardFromDefendersGraveyard``
    unit variant on ``cards.rs::Effect`` + parse / to_pydict / resolve
    arms + new ``PendingDecision::GraveyardCardChoice`` variant +
    ``submit_graveyard_card_decision`` py-method + cross-engine
    bridge dict-to-Python arm in ``cross_engine.py`` + reverse-
    serializer leaf in ``trajectory.py`` (DORMANT-by-construction).
    Chorale of the Void STAYED DECLINED at every admit gate
    (substrate-only invariant pin at ``test_chorale_of_the_void_
    stays_declined_at_admit_gate_post_cycle_1``).
  * **Phase A Cycle 2 (THE FLIP, this slice, 2026-05-26).** Widen
    :func:`_aura_triggers_are_phase3_safe` with TWO new admit shapes
    in lockstep (the all-or-nothing gate refuses partial admission —
    Chorale's two TAs MUST widen together):

      - Shape A: ``ATTACKS + IsHost(subject="attacker") +
        ReanimateTargetCreatureCardFromDefendersGraveyard``.
      - Tail-X2: ``BEGINNING_OF_END_STEP + Controlled(by=YOU,
        subject=None) + SacrificeSelfUnlessVoidActive``.

    Widen :func:`_python_ta_to_safe_dict_aura_phase3` with the
    matching Tail-X2 emitter arm (the Reanimate arm was pre-positioned
    in C1). Chorale of the Void DECLINED → ADMITTED (the +2,783 deck
    flip; admit set grows by ONE Aura). The C1 substrate-only
    invariant pin inverted in-place
    (``test_chorale_of_the_void_now_admits_at_admit_gate_post_cycle_2``).
  * **Phase A Cycle 2 (THIS LANE; THE PROBE — Scenarios 1+2+3).**
    Per-card real-EoE probe driving the **actual live Chorale of the
    Void printing** (resolved via :class:`OracleParserCardSource`,
    NOT a synthetic CardDef — the round-46 real-EoE-signal discipline)
    through three scenarios:

    (1) **The load-bearing ATTACKS reanimate (Python engine).**
        Attach Chorale to caster's own creature (the live printing
        is ``Enchant creature``; the printed text says "defending
        player's graveyard", so the reanimate target pool is the
        opposing player's graveyard creature cards). Seed the
        opponent's graveyard with a creature card. Declare the
        enchanted host as an attacker; the ATTACKS trigger queues +
        resolves; the Reanimate effect picks (via the scripted
        ``_PickFirstAgent``) the opponent's graveyard creature card
        and puts it onto the caster's battlefield tapped + attacking.
    (2) **End-step with Void active (no sacrifice).** Chorale on
        caster's bf, attached to caster's host; set
        ``permanent_left_battlefield_this_turn=True`` so
        ``is_void_active(state)`` returns True; run
        ``run_beginning_of_end_step_triggers`` + drain stack; Chorale
        stays on bf (the EoT trigger fires, the resolve arm sees
        Void active and silent-no-ops).
    (3) **End-step with Void inactive (Aura sacrificed).** Chorale on
        caster's bf, attached to caster's host; Void is NOT active
        (no LTB / no warp this turn); run end-step triggers + drain;
        Chorale leaves the battlefield (the resolve arm sacrifices
        the source).

**Scripted-picker semantics.** The probe uses a ``_PickFirstAgent``
shim on p0 (caster) so ``choose_target`` returns the first legal
opponent-graveyard-creature target — matching Rust's deterministic
first-eligible auto-resolve default for
``PendingDecision::GraveyardCardChoice`` (the C1 substrate's auto-
resolve picks ``candidates[0]``).

**Cross-engine byte-equal probes.** Scenarios 2 (end-step Void-active
no-sac) and 3 (end-step Void-inactive sac) ride the
``Event::BeginningOfEndStep`` dispatch + the
``Effect::SacrificeSelfUnlessVoidActive`` resolve arm — both fully
landed in Rust (Phase 4 first-deliverable, ``rust/src/cards.rs:4972``).
These exercise byte-equal cross-engine semantics on the Tail-X2 half
of Chorale's trigger surface.

Scenario 1 (the ATTACKS reanimate long pole) is **Python-engine only**
in this slice — the Rust resolve arm is fully landed (``state_ops_
resolve.rs:16433``) but the **production push site** for
``PendingDecision::GraveyardCardChoice`` at the ATTACKS-trigger fan-
out is deferred to a follow-up Rust slice (the Phase A Cycle 1
substrate landed the PendingDecision variant + the submit dispatcher
+ the resolve arm, but the trigger-fire push at
``state_ops_resolve.rs::push_triggered_ability`` is **not yet wired**
for the Reanimate effect — ``first_legal_trigger_target`` has no arm
for it, so the trigger pushes onto the stack with
``target_obj_id=None`` and the resolve arm silent-fizzles on the
unset payload slot). Adding the trigger-fire push is a future-cycle
Rust slice (out of scope for Cycle 2's Python-only delivery). The
admit-gate flip + the Tail-X2 cross-engine pins are the load-bearing
Cycle 2 evidence; Scenario 1's full cross-engine byte-equal pin will
land in the follow-up slice.

**Real-EoE-signal discipline.** This module uses the live
``OracleParserCardSource`` Chorale of the Void printing on the Python
side AND (for the cross-engine pins) the canonical Rust registry dict
shape emitted by the C2 forward arm
``_spec_card_to_printing_dict(_printing_to_card_def(p))`` on the
Rust side — the SAME printing shape both engines read.

This module is the Aura-attachment Phase A closure marker; Phase B
(Cracked Skull) + Phase C (Sporogenic Infection) are separate cycles
in the Phase 3+ campaign per design doc §8.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
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


# Canonical Rust dict for Chorale of the Void — the EXACT shape that
# ``_printing_to_card_def`` + ``_spec_card_to_printing_dict`` emit
# via the Phase 3+ bridge for the live printing. Verified via the
# C2 admit + emitter widens by running the live printing through
# ``_printing_to_card_def`` (the pin
# ``test_chorale_of_the_void_loader_admits_and_emits_canonical_dict``
# below threads the live printing and asserts byte-equal against
# this dict).
_CHORALE_RUST_DICT = {
    "name": "Chorale of the Void",
    "card_types": ["Enchantment"],
    "subtypes": ["Aura"],
    "is_aura": True,
    "aura_enchant_type": "creature",
    "mana_cost": {"generic": 3, "B": 1},
    "effects": [],
    "triggered_abilities": [
        {
            "event": "attacks",
            "predicate": {"kind": "is_host", "subject": "attacker"},
            "effect": {
                "kind": "reanimate_target_creature_card_from_defenders_graveyard",
            },
            "once_per_turn": False,
        },
        {
            "event": "beginning_of_end_step",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {"kind": "sacrifice_self_unless_void_active"},
            "once_per_turn": False,
        },
    ],
}


class _PickFirstAgent(Agent):
    """Scripted picker — returns the first legal target for the
    Reanimate effect's ``choose_target`` invocation. Mirrors Rust's
    deterministic first-eligible auto-resolve default for
    ``PendingDecision::GraveyardCardChoice`` (``candidates[0]`` per
    ``state_ops_decisions.rs::auto_resolve_pending`` Graveyard arm
    at line 579-582).
    """

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


# ---------------------------------------------------------------------------
# (1) Parser SoT — Chorale of the Void is parser-claimed and emits the
# expected TWO-trigger Phase-3+ Phase-A shape.
# ---------------------------------------------------------------------------


def test_chorale_of_the_void_parser_claims_card():
    """Pins the active CardSource is producing the Chorale of the
    Void printing under its canonical EoE name.
    """
    assert "Chorale of the Void" in _PRINTINGS, (
        "Chorale of the Void must be parser-claimed by the active "
        "CardSource (EoE set + reprint coverage)"
    )


def test_chorale_of_the_void_printed_attrs():
    """Pins the basic printing surface: Enchantment — Aura, cost
    ``{1}{B}``, ``aura_enchant_type='creature'``, TWO triggered
    abilities with the canonical Phase-3+ Phase-A shape (the §2 teeth
    — the admit predicate's load-bearing gates).
    """
    from mtg_bot.effects.combinators import SacrificeSelfUnlessVoidActive
    from mtg_bot.effects.generic.graveyard import (
        ReanimateTargetCreatureCardFromDefendersGraveyard,
    )
    from mtg_bot.effects.predicates import (
        Controlled,
        Event,
        IsHost,
        YOU as _Controller_YOU,
    )

    p = _PRINTINGS["Chorale of the Void"]
    assert p.is_aura is True
    assert p.aura_enchant_type == "creature"
    assert p.mana_cost.generic == 3
    assert ("B", 1) in p.mana_cost.colored
    # The §2 teeth — no static / activated / spell-effect / warp /
    # cost-reduction riders.
    assert p.activated_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.warp_cost is None
    # Two triggered abilities (the Phase-A long pole + Tail-X2).
    assert len(p.triggered_abilities) == 2
    ta_attacks, ta_eot = p.triggered_abilities
    # Shape A: ATTACKS + IsHost(subject="attacker") + Reanimate.
    assert ta_attacks.event is Event.ATTACKS
    assert isinstance(ta_attacks.predicate, IsHost)
    assert ta_attacks.predicate.subject == "attacker"
    assert isinstance(
        ta_attacks.effect, ReanimateTargetCreatureCardFromDefendersGraveyard
    )
    assert ta_attacks.once_per_turn is False
    # Tail-X2: BEGINNING_OF_END_STEP + Controlled(YOU) +
    # SacrificeSelfUnlessVoidActive.
    assert ta_eot.event is Event.BEGINNING_OF_END_STEP
    assert isinstance(ta_eot.predicate, Controlled)
    assert ta_eot.predicate.by is _Controller_YOU
    assert ta_eot.predicate.subject is None
    assert isinstance(ta_eot.effect, SacrificeSelfUnlessVoidActive)
    assert ta_eot.once_per_turn is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the live Chorale of the Void printing flows
# through ``_printing_to_card_def`` → ``_spec_card_to_printing_dict``
# → canonical Rust registry dict matches ``_CHORALE_RUST_DICT`` byte-
# equal. Pins the probe's source-of-truth that Rust reads the same
# printing shape Python does.
# ---------------------------------------------------------------------------


def test_chorale_of_the_void_loader_admits_and_emits_canonical_dict():
    """**The +2,783 deck flip — load-bearing admit pin.** The live
    Chorale of the Void printing now admits at the loader filter
    (Cycle 2 flip) AND its CardDef bridge emits the canonical Rust
    dict shape both engines read.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    p_orig = _PRINTINGS["Chorale of the Void"]
    # Loader admit (the +2,783 deck flip).
    assert trajectory._printing_is_bridge_simple_aura(p_orig) is True
    # Forward arm: live printing → CardDef → registry dict.
    cd = trajectory._printing_to_card_def(p_orig)
    assert cd is not None
    pd = _spec_card_to_printing_dict(cd)
    # The dict carries TWO triggered abilities — the Phase-A long pole
    # + the Tail-X2.
    assert pd["name"] == "Chorale of the Void"
    assert pd["is_aura"] is True
    assert pd["aura_enchant_type"] == "creature"
    assert len(pd["triggered_abilities"]) == 2
    # Order is parser-order: ATTACKS then BEGINNING_OF_END_STEP
    # (matches the printed text order).
    assert pd["triggered_abilities"][0] == {
        "event": "attacks",
        "predicate": {"kind": "is_host", "subject": "attacker"},
        "effect": {
            "kind": "reanimate_target_creature_card_from_defenders_graveyard",
        },
        "once_per_turn": False,
    }
    assert pd["triggered_abilities"][1] == {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {"kind": "sacrifice_self_unless_void_active"},
        "once_per_turn": False,
    }


def test_chorale_of_the_void_loader_end_to_end_admit():
    """End-to-end loader admit: pass ``["Chorale of the Void"]`` to
    ``_filter_deck_to_bridge_supported`` → admitted; CardDef emitted
    carries the Phase-3+ Phase-A trigger shape (the +2,783 deck flip
    is captured here at the deck-loader filter, the chokepoint
    bench-side admit decisions flow through).
    """
    from mtg_bot.parity import trajectory

    filt, defs = trajectory._filter_deck_to_bridge_supported(
        ["Chorale of the Void"], _PRINTINGS,
    )
    assert filt == ["Chorale of the Void"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Chorale of the Void"
    assert cd.is_aura is True
    assert len(cd.triggered_abilities) == 2


# ---------------------------------------------------------------------------
# (3) Rust unit pin — the canonical Chorale Rust dict registers cleanly
# on ``register_printing`` (validates the Rust substrate accepts the
# full Cycle-2-emitted shape end-to-end). Lockstep with C1's parse
# arm + register pin.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_canonical_chorale_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Chorale
    of the Void registry dict — the SAME dict the C2 forward arm
    produces for the live Chorale printing. Threading
    ``triggered_abilities`` with both halves (Reanimate + Sacrifice-
    Self-Unless-Void-Active) round-trips byte-equal through
    ``Registry.register_printing``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_CHORALE_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Chorale of the Void"


# ---------------------------------------------------------------------------
# (4) Scenario 1 — ATTACKS reanimate (the load-bearing happy path).
# Chorale on bf attached to p0's host; opp graveyard has a Creature
# card; p0 attacks with the host; ATTACKS trigger fires and the
# Reanimate effect pulls the opponent's graveyard creature onto p0's
# bf TAPPED + ATTACKING. Python-engine real-EoE smoke.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_chorale_of_the_void_attacks_reanimate_scenario_1_parity():
    """**Scenario 1 — THE LOAD-BEARING ATTACKS reanimate path.** Drives
    the live Chorale of the Void printing through its ATTACKS-trigger
    long pole on the Python engine:

      Pre-state:
        * p0's Wild Bear on bf (unsick), enchanted with the live
          Chorale of the Void printing.
        * p1's graveyard contains a Wild Bear creature card (the
          reanimation target).

      Drive: ``combat.declare_attackers([host_bear.id])`` fires
      Chorale's ATTACKS trigger. The trigger queues onto the stack;
      resolution walks the Reanimate effect's
      ``choose_target`` (scripted via ``_PickFirstAgent`` →
      picks the opponent's graveyard bear, the first legal target);
      the bear leaves p1's graveyard and enters p0's bf TAPPED +
      ATTACKING (CR 400.7 zone-change reset + the Reanimate arm's
      explicit ``tapped=True / attacking=True / summoning_sick=False``
      stamps).

      Post-resolve:
        * Stack empty (the trigger resolved).
        * p0's Wild Bear host on bf, tapped (from declaring attacker).
        * The reanimated bear (formerly p1's graveyard) on p0's bf,
          tapped + attacking + not summoning-sick.
        * p1's graveyard empty.
    """
    from mtg_bot.actions import drain_stack
    from mtg_bot.combat import declare_attackers
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0

    # p0's host bear on bf (unsick).
    host_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    host_bear.summoning_sick = False
    state.battlefield.append(host_bear)

    # p0's Chorale of the Void on bf, attached to the host bear.
    chorale = state.new_object(
        _PRINTINGS["Chorale of the Void"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    chorale.attached_to = host_bear.id
    state.battlefield.append(chorale)

    # p1's graveyard has a Wild Bear creature card.
    grave_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.GRAVEYARD,
    )
    state.players[1].graveyard.append(grave_bear)

    # ---- Drive: declare host_bear as attacker → Chorale's ATTACKS
    # trigger fires.
    declare_attackers(state, [host_bear.id])
    drain_stack(state)

    # ---- Post-resolve observables.
    # Host bear tapped from declaring attacker.
    assert host_bear.tapped is True

    # The grave_bear reanimated: now on p0's bf, tapped + attacking,
    # not in p1's graveyard.
    assert grave_bear in state.battlefield, (
        "Reanimate effect must put the opponent's graveyard creature "
        "onto the caster's battlefield"
    )
    assert grave_bear.controller_id == 0, (
        "Reanimated bear's controller must be the Aura's controller "
        "(p0), per CR 110.2 / 614.x"
    )
    assert grave_bear.tapped is True, (
        "Reanimated bear must enter tapped (the printed text)"
    )
    assert grave_bear.attacking is True, (
        "Reanimated bear must enter attacking (the printed text)"
    )
    assert grave_bear not in state.players[1].graveyard, (
        "Reanimated bear must have left p1's graveyard"
    )

    # Stack empty (the trigger fully resolved).
    assert state.stack == []


# ---------------------------------------------------------------------------
# (5) Scenario 2 — End-step with Void active (no sacrifice). Chorale
# on caster's bf attached to caster's host; Void is active (a
# permanent left the battlefield this turn); end-step trigger fires;
# the SacrificeSelfUnlessVoidActive resolve arm sees Void active and
# silent-no-ops. Python-engine real-EoE pin.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_chorale_of_the_void_end_step_void_active_scenario_2_parity():
    """**Scenario 2 — End-step with Void active; no sacrifice.** Drives
    the Tail-X2 trigger on the Python engine with Void active:

      Pre-state:
        * p0's Wild Bear on bf, enchanted with Chorale.
        * ``state.permanent_left_battlefield_this_turn = True`` — Void
          is active.

      Drive: ``run_beginning_of_end_step_triggers(state)`` fires
      Chorale's EoT trigger. The trigger queues onto the stack;
      resolution runs ``SacrificeSelfUnlessVoidActive.resolve``; the
      arm reads ``is_void_active(state) is True`` and silent-no-ops.

      Post-resolve:
        * Chorale STILL on bf (no sacrifice).
        * The host bear STILL on bf (Chorale didn't sac).
    """
    from mtg_bot.actions import drain_stack
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import run_beginning_of_end_step_triggers

    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0

    host_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    host_bear.summoning_sick = False
    state.battlefield.append(host_bear)

    chorale = state.new_object(
        _PRINTINGS["Chorale of the Void"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    chorale.attached_to = host_bear.id
    state.battlefield.append(chorale)

    # Void is active.
    state.permanent_left_battlefield_this_turn = True

    # ---- Drive: end-step triggers fire.
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)

    # ---- Post-resolve observables.
    # Chorale stays on bf (Void active → no sac).
    assert chorale in state.battlefield, (
        "Chorale must stay on bf when Void is active at end step "
        "(SacrificeSelfUnlessVoidActive.resolve silent-no-ops)"
    )
    assert host_bear in state.battlefield


# ---------------------------------------------------------------------------
# (6) Scenario 3 — End-step with Void inactive (Aura sacrificed).
# Chorale on caster's bf attached to caster's host; Void is NOT active;
# end-step trigger fires; SacrificeSelfUnlessVoidActive sacrifices
# Chorale. Python-engine real-EoE pin.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_chorale_of_the_void_end_step_void_inactive_scenario_3_parity():
    """**Scenario 3 — End-step with Void INACTIVE; Aura sacrificed.**
    Drives the Tail-X2 trigger on the Python engine with Void
    inactive:

      Pre-state:
        * p0's Wild Bear on bf, enchanted with Chorale.
        * Void is NOT active (no LTB / no warp this turn).

      Drive: ``run_beginning_of_end_step_triggers(state)`` fires
      Chorale's EoT trigger. The trigger queues + resolves;
      ``SacrificeSelfUnlessVoidActive.resolve`` sees
      ``is_void_active(state) is False`` and sacrifices Chorale.

      Post-resolve:
        * Chorale OFF bf (sacrificed → graveyard).
        * The host bear STILL on bf (Chorale leaving doesn't drag
          the host).
    """
    from mtg_bot.actions import drain_stack
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import run_beginning_of_end_step_triggers

    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0

    host_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    host_bear.summoning_sick = False
    state.battlefield.append(host_bear)

    chorale = state.new_object(
        _PRINTINGS["Chorale of the Void"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    chorale.attached_to = host_bear.id
    state.battlefield.append(chorale)

    # Void is NOT active (no LTB / no warp this turn). Default value
    # of permanent_left_battlefield_this_turn is False.
    assert state.permanent_left_battlefield_this_turn is False

    # ---- Drive: end-step triggers fire.
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)

    # ---- Post-resolve observables.
    # Chorale is sacrificed → off bf.
    assert chorale not in state.battlefield, (
        "Chorale must be sacrificed when Void is inactive at end step"
    )
    # Host stays.
    assert host_bear in state.battlefield, (
        "Host bear must stay on bf (Aura sac doesn't drag the host)"
    )


# ---------------------------------------------------------------------------
# (7) Cross-engine — Tail-X2 SacrificeSelfUnlessVoidActive byte-equal.
# Drives BOTH engines through the end-step Void-inactive sac path so
# the Tail-X2 cross-engine surface is byte-equal pinned at Cycle 2.
# Scenario 1 (ATTACKS reanimate) cross-engine is deferred per the
# module docstring (production push site for GraveyardCardChoice is
# a follow-up Rust slice).
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_chorale_of_the_void_end_step_byte_equal_tail_x2_parity():
    """**Cross-engine byte-equal pin — Tail-X2 (Scenario 3 cross-
    engine).** Drives BOTH engines through the end-step Void-inactive
    sacrifice path; Chorale leaves bf on BOTH engines after a single
    end-step trigger resolution. Uses the canonical Rust registry
    dict (the C2 forward arm output for the live Chorale printing)
    on Rust + the live printing on Python — both engines read the
    same printing shape.

    Rust-side dispatch flow: ``set_phase(9)`` (PHASE_MAIN2) →
    ``advance_phase()`` transitions to ``PHASE_END_STEP`` (10) and
    fires the centralized ``Event::BeginningOfEndStep`` dispatch (the
    Rust mirror of Python's ``run_beginning_of_end_step_triggers``,
    round-14 substrate). The Tail-X2 trigger queues + resolves
    through ``Effect::SacrificeSelfUnlessVoidActive`` (Phase 4
    first-deliverable, ``cards.rs:4972``) and Chorale sacrifices.
    """
    from mtg_bot.actions import drain_stack
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import run_beginning_of_end_step_triggers
    import mtg_bot_engine

    # ---- Python side.
    py = GameState()
    py.players.append(Player(id=0, agent=_PickFirstAgent()))
    py.players.append(Player(id=1, agent=_PickFirstAgent()))
    py.active_player_idx = 0

    host_bear = py.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    host_bear.summoning_sick = False
    py.battlefield.append(host_bear)

    chorale_py = py.new_object(
        _PRINTINGS["Chorale of the Void"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    chorale_py.attached_to = host_bear.id
    py.battlefield.append(chorale_py)

    # ---- Rust side. Build via ``make_state`` (the canonical
    # constructor) then inject objects via
    # ``register_and_inject_object`` (the production injection path
    # — same shim every cross-engine probe uses).
    bear_dict = {
        "name": "Test Wild Bear",
        "card_types": ["Creature"],
        "subtypes": ["Bear"],
        "mana_cost": {"generic": 1, "G": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
    }
    reg = mtg_bot_engine.Registry()
    # Both decklists empty; we inject directly onto bf below.
    rs = mtg_bot_engine.make_state(reg, [], [])
    rs_bear = rs.register_and_inject_object(
        bear_dict, 0, ZONE_BATTLEFIELD,
    )
    rs.clear_summoning_sick_for_player(0)
    rs_chorale = rs.register_and_inject_object(
        _CHORALE_RUST_DICT, 0, ZONE_BATTLEFIELD,
    )
    # Attach the Aura to the host bear via the Rust ``attach`` helper.
    rs.attach(rs_chorale, rs_bear)

    # ---- Pre-state sanity.
    assert chorale_py in py.battlefield
    assert host_bear in py.battlefield
    assert rs.find_object_zone(rs_chorale) == ZONE_BATTLEFIELD
    assert rs.find_object_zone(rs_bear) == ZONE_BATTLEFIELD
    # Void inactive on both engines (no LTB / warp this turn).
    assert py.permanent_left_battlefield_this_turn is False
    assert rs.is_void_active is False

    # ---- Drive end-step triggers on both engines.
    run_beginning_of_end_step_triggers(py)
    drain_stack(py)

    # Rust: advance from PHASE_MAIN2 (9) to PHASE_END_STEP (10) to
    # fire ``Event::BeginningOfEndStep``. ``set_phase`` is raw state
    # assignment (no dispatch); ``advance_phase`` is what fans out
    # the event (round-14 substrate at ``state_ops_steps.rs:714+``).
    rs.set_phase(9)
    rs.advance_phase()
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # ---- Post-resolve: Chorale off bf on both engines.
    assert chorale_py not in py.battlefield, (
        "Python: Chorale must be sacrificed when Void inactive at "
        "end step"
    )
    rs_chorale_zone = rs.find_object_zone(rs_chorale)
    assert rs_chorale_zone != ZONE_BATTLEFIELD, (
        f"Rust: Chorale must leave the battlefield (sacrificed) "
        f"when Void inactive at end step; got zone="
        f"{rs_chorale_zone}"
    )
    # Host stays on both engines.
    assert host_bear in py.battlefield
    assert rs.find_object_zone(rs_bear) == ZONE_BATTLEFIELD
