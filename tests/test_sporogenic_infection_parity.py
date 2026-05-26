"""Sporogenic Infection — per-card real-EoE probe (``covered_by_
construction`` -> PROBED tier flip; Aura-attachment substrate Phase 3+
Phase C closure marker for Scenarios 1+2+3 per design doc
``docs/AURA_ATTACH_SUBSTRATE_PHASE_3_DESIGN.md`` section 7 row 5).

Sporogenic Infection is a ``{1}{B}`` Enchantment - Aura in the EoE
pool (positive-control carrier; 0 17lands decks per design doc section
0 row 4 — the deck-count signal is on substrate correctness, not deck
volume). Live trigger surface:

    Mana cost: {1}{B}
    Enchant creature
    Triggered ability A (the ENTERS long pole; Phase C admit shape):
        event       = Event.ENTERS
        predicate   = IsSelf(subject=None)
        effect      = TargetOpponentSacrificesCreatureOtherThanEnchanted()
        once_per_turn = False
    Triggered ability B (Tail-X1, the damage-echo destroy tail —
    shared with Cracked Skull per design doc section 3):
        event       = Event.DEALT_DAMAGE
        predicate   = IsHost(subject=None)
        effect      = DestroyEnchantedPermanent()
        once_per_turn = False

Per design doc section 3 (Phase C carrier) + section 7 row 5
(Sporogenic Infection probe spec).

**Phase C combined slice DECLINED -> ADMITTED -> PROBED transition.**

The Aura Phase 3+ Phase C closure is a single combined slice (Rust +
Python + probe) — there is no substrate-only Cycle 1 because the
Tail-X1 widen already shipped in Phase B Cycle 2 (Cracked Skull); the
Phase C cycle only needs the ENTERS-half Effect class
(``TargetOpponentSacrificesCreatureOtherThanEnchanted``) to land
across Rust + Python + bridge in lockstep with the admit-gate widen
and the per-card real-EoE probe.

  * **Rust substrate (this slice, 2026-05-26).** New
    ``Effect::TargetOpponentSacrificesCreatureOtherThanEnchanted``
    unit variant on ``cards.rs::Effect`` + parse / to_pydict / resolve
    arms + new ``PendingDecision::SacrificeChoice`` variant with the
    ``excluded_object_id: Option<u32>`` slot + ``submit_sacrifice_
    decision`` py-method + auto-resolve arm (default picks
    ``candidates[0]`` — the TARGET opponent's deterministic-first sac
    pick) + fingerprint arm + cross-engine bridge dict-to-Python arm
    in ``cross_engine.py``.
  * **Python widen (this slice, 2026-05-26).** Widen
    :func:`_aura_triggers_are_phase3_safe` with Sporogenic's ENTERS-
    half shape (the Tail-X1 widen already shipped with Phase B Cycle
    2 — the all-or-nothing gate closes for Sporogenic the moment its
    ENTERS half lands). Widen
    :func:`_python_ta_to_safe_dict_aura_phase3` with the matching
    ENTERS-half emitter arm. Sporogenic Infection DECLINED ->
    ADMITTED (the +0 deck flip — positive-control carrier; admit set
    grows by ONE Aura).
  * **Phase C closure (THIS LANE; THE PROBE — Scenarios 1+2+3).**
    Per-card real-EoE probe driving the **actual live Sporogenic
    Infection printing** (resolved via :class:`OracleParserCardSource`,
    NOT a synthetic CardDef — the real-EoE-signal discipline) through
    three scenarios:

    (1) **The ETB resolve + target opponent sacrifices a non-host
        creature.** Attach Sporogenic to a host on caster's bf; seed
        the target opponent's battlefield with TWO additional
        creatures (the host's already there; total = 3 creatures on
        the target's side, of which one is the host). Drive the ETB
        trigger via ``_trigger_etb_abilities``; the trigger queues,
        targets the opponent (first legal player target). On
        resolve: the candidate set excludes the host (the Aura's
        ``attached_to``); the target opponent's agent picks one of
        the two non-host creatures via ``choose_sacrifice``; that
        creature lands on the target's graveyard. The host stays.
    (2) **ETB resolve when target controls ONLY the host (silent
        no-op).** Sporogenic attached to a host on caster's bf;
        target opponent controls ONLY the host (no other creatures).
        The candidate enumeration filters everything (host excluded),
        leaving an empty list. Silent fizzle — no sacrifice happens.
    (3) **Combat damage path — Tail-X1 DestroyEnchantedPermanent.**
        Sporogenic attached to caster's host bear; opponent's blocker
        takes combat damage from Sporogenic's host (via
        ``_fire_enchanted_dealt_damage_triggers`` mirror — direct
        invocation of the dispatch_event path). Sporogenic's Tail-X1
        fires: DEALT_DAMAGE + IsHost matches when an attached aura's
        attached_to == obj.id; the DestroyEnchantedPermanent effect
        reads ``state.resolving_source`` (Sporogenic) and destroys
        ``aura.attached_to`` (the host bear). The host leaves the
        battlefield; Sporogenic falls off as state-based action
        (CR 704.5n — Aura attached to nothing goes to graveyard).

**Scripted-picker semantics.** Scenario 1 uses scripted agents on
BOTH players (the caster's agent picks the first legal player
target; the target opponent's agent picks the first non-host
creature via ``choose_sacrifice``). Mirrors Rust's deterministic-
first auto-resolve defaults for ``PendingDecision::SacrificeChoice``
(default ``candidates[0]``).

**Cross-engine byte-equal pin (Scenarios 1 + 3 deferred).** This
slice lands all three scenarios as Python-engine real-EoE probes;
the cross-engine byte-equal pins for Scenario 1 (Rust ETB push site
of ``PendingDecision::SacrificeChoice`` via the ENTERS-trigger fan-
out at ``first_legal_trigger_target``) and Scenario 3 (Tail-X1
DEALT_DAMAGE dispatch into ``Effect::DestroyEnchantedPermanent``'s
resolve from an Aura source) are deferred to a follow-up Rust slice
— same honest-stop shape Phase A's Chorale parity and Phase B's
Cracked Skull parity both took. The admit-gate flip + the per-card
real-EoE Python-engine probe + the Rust register-acceptance pin are
the load-bearing Phase C evidence.

**Real-EoE-signal discipline.** This module uses the live
``OracleParserCardSource`` Sporogenic Infection printing on the
Python side — the SAME printing the loader admits at the bench
filter.

This module is the Aura-attachment Phase C closure marker —
**Aura Phase 3+ campaign COMPLETE.** No further Phase D / Phase 4+
Aura cycle is planned in the design doc; the next substrate-level
Aura work would be a new design doc per the multi-cycle campaign
discipline.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.agents import Agent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


# Skip Rust-engine probes if the extension isn't built. (Phase C's
# probe is Python-only; reserved for the follow-up cross-engine slice.)
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


class _PickFirstAgent(Agent):
    """Scripted picker — picks the first legal target / first legal
    sacrifice candidate.

    Mirrors Rust's deterministic-first auto-resolve defaults:
      - ``PendingDecision::SacrificeChoice`` default
        ``candidates[0]``.
    """

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_sacrifice(self, state, player_id, legal_object_ids):
        return legal_object_ids[0] if legal_object_ids else None


# ---------------------------------------------------------------------------
# (1) Parser SoT — Sporogenic Infection is parser-claimed and emits
# the expected TWO-trigger Phase-3+ Phase-C shape.
# ---------------------------------------------------------------------------


def test_sporogenic_infection_parser_claims_card():
    """Pins the active CardSource is producing the Sporogenic Infection
    printing under its canonical EoE name.
    """
    assert "Sporogenic Infection" in _PRINTINGS, (
        "Sporogenic Infection must be parser-claimed by the active "
        "CardSource (EoE set + reprint coverage)"
    )


def test_sporogenic_infection_printed_attrs():
    """Pins the basic printing surface: Enchantment - Aura, cost
    ``{1}{B}``, ``aura_enchant_type='creature'``, TWO triggered
    abilities with the canonical Phase-3+ Phase-C shape (the section
    2 teeth — the admit predicate's load-bearing gates).
    """
    from mtg_bot.effects.generic.destroy import DestroyEnchantedPermanent
    from mtg_bot.effects.generic.opponent_punishers import (
        TargetOpponentSacrificesCreatureOtherThanEnchanted,
    )
    from mtg_bot.effects.predicates import Event, IsHost, IsSelf

    p = _PRINTINGS["Sporogenic Infection"]
    assert p.is_aura is True
    assert p.aura_enchant_type == "creature"
    # The section 2 teeth — no static / activated / spell-effect /
    # warp / cost-reduction riders.
    assert p.activated_abilities == ()
    assert p.static_abilities == ()
    assert p.spell_effect is None
    assert p.warp_cost is None
    # Two triggered abilities (the Phase-C long pole + Tail-X1).
    assert len(p.triggered_abilities) == 2
    ta_etb, ta_dd = p.triggered_abilities
    # Phase-C ENTERS long pole: ENTERS + IsSelf(subject=None) +
    # TargetOpponentSacrificesCreatureOtherThanEnchanted.
    assert ta_etb.event is Event.ENTERS
    assert isinstance(ta_etb.predicate, IsSelf)
    assert ta_etb.predicate.subject is None
    assert isinstance(
        ta_etb.effect, TargetOpponentSacrificesCreatureOtherThanEnchanted
    )
    assert ta_etb.once_per_turn is False
    # Tail-X1: DEALT_DAMAGE + IsHost(subject=None) +
    # DestroyEnchantedPermanent.
    assert ta_dd.event is Event.DEALT_DAMAGE
    assert isinstance(ta_dd.predicate, IsHost)
    assert ta_dd.predicate.subject is None
    assert isinstance(ta_dd.effect, DestroyEnchantedPermanent)
    assert ta_dd.once_per_turn is False


# ---------------------------------------------------------------------------
# (2) Loader admit pin — Sporogenic Infection now admits at the bench
# loader post Phase-C closure.
# ---------------------------------------------------------------------------


def test_cracked_skull_still_admits_post_phase_c_closure():
    """**Adjacent-carrier regression pin.** Cracked Skull (the Phase B
    positive-control flip carrier) MUST still admit post-Phase-C
    closure — Phase C only ADDS the Sporogenic ENTERS-half admit
    shape, it does NOT touch the Phase B Cracked Skull shapes (ETB
    long pole + Tail-X1).
    """
    from mtg_bot.parity import trajectory

    p = _PRINTINGS["Cracked Skull"]
    assert (
        trajectory._aura_triggers_are_phase3_safe(p.triggered_abilities)
        is True
    )
    assert trajectory._printing_is_bridge_simple_aura(p) is True


def test_cryoshatter_stays_declined_post_phase_c_closure():
    """**No-silent-auto-grow guard.** Cryoshatter is ALSO an Aura whose
    Tail half is exactly Tail-X1 (DEALT_DAMAGE + IsHost +
    DestroyEnchantedPermanent — shared with Sporogenic + Cracked
    Skull), but its OTHER trigger is
    ``BECOMES_TAPPED + IsHost + DestroyEnchantedPermanent`` —
    BECOMES_TAPPED is NOT in the Phase-3 safe set today. The all-or-
    nothing gate keeps Cryoshatter DECLINED (would-be silent auto-
    grow blocked) even after Phase C closure.
    """
    from mtg_bot.parity import trajectory

    p = _PRINTINGS["Cryoshatter"]
    assert (
        trajectory._aura_triggers_are_phase3_safe(p.triggered_abilities)
        is False
    )
    assert trajectory._printing_is_bridge_simple_aura(p) is False


def test_sporogenic_infection_loader_admits_post_phase_c_closure():
    """**The +0 deck positive-control flip — load-bearing admit pin.**
    The live Sporogenic Infection printing now admits at the loader
    filter (Phase C closure widen). Aura Phase 3+ campaign COMPLETE.
    """
    from mtg_bot.parity import trajectory

    p_orig = _PRINTINGS["Sporogenic Infection"]
    assert (
        trajectory._aura_triggers_are_phase3_safe(p_orig.triggered_abilities)
        is True
    )
    assert trajectory._printing_is_bridge_simple_aura(p_orig) is True


def test_sporogenic_infection_loader_emits_canonical_dict():
    """**Forward bridge round-trip.** The live Sporogenic Infection
    printing flows through ``_printing_to_card_def`` -> ``_spec_card_
    to_printing_dict`` -> canonical Rust registry dict matches the
    expected Phase-C shape. Pins the probe's source-of-truth that
    Rust reads the same printing shape Python does.
    """
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict

    p_orig = _PRINTINGS["Sporogenic Infection"]
    cd = trajectory._printing_to_card_def(p_orig)
    assert cd is not None
    pd = _spec_card_to_printing_dict(cd)
    assert pd["name"] == "Sporogenic Infection"
    assert pd["is_aura"] is True
    assert pd["aura_enchant_type"] == "creature"
    assert len(pd["triggered_abilities"]) == 2
    # Order is parser-order: ENTERS then DEALT_DAMAGE.
    assert pd["triggered_abilities"][0] == {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "target_opponent_sacrifices_creature_other_than_enchanted",
        },
        "once_per_turn": False,
    }
    assert pd["triggered_abilities"][1] == {
        "event": "dealt_damage",
        "predicate": {"kind": "is_host"},
        "effect": {"kind": "destroy_enchanted_permanent"},
        "once_per_turn": False,
    }


def test_sporogenic_infection_loader_end_to_end_admit():
    """End-to-end loader admit: pass ``["Sporogenic Infection"]`` to
    ``_filter_deck_to_bridge_supported`` -> admitted; CardDef emitted
    carries the Phase-3+ Phase-C trigger shape.
    """
    from mtg_bot.parity import trajectory

    filt, defs = trajectory._filter_deck_to_bridge_supported(
        ["Sporogenic Infection"], _PRINTINGS,
    )
    assert filt == ["Sporogenic Infection"]
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Sporogenic Infection"
    assert cd.is_aura is True
    assert len(cd.triggered_abilities) == 2


# ---------------------------------------------------------------------------
# (3) Rust unit pin — the canonical Sporogenic Infection Rust dict
# registers cleanly on ``register_printing``.
# ---------------------------------------------------------------------------


# Canonical Rust registry dict for Sporogenic Infection — what the
# forward arm ``_spec_card_to_printing_dict(_printing_to_card_def(p))``
# emits.
_SPOROGENIC_INFECTION_RUST_DICT = {
    "name": "Sporogenic Infection",
    "card_types": ["Enchantment"],
    "is_aura": True,
    "aura_enchant_type": "creature",
    "mana_cost": {"generic": 1, "B": 1},
    "effects": [],
    "triggered_abilities": [
        {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "target_opponent_sacrifices_creature_other_than_enchanted",
            },
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
def test_rust_parser_accepts_canonical_sporogenic_infection_dict():
    """Lockstep pin: Rust's parse arm accepts the canonical Sporogenic
    Infection registry dict — the SAME dict the forward arm produces
    for the live Sporogenic Infection printing. Threading
    ``triggered_abilities`` with both halves
    (TargetOpponentSacrificesCreatureOtherThanEnchanted +
    DestroyEnchantedPermanent) round-trips byte-equal through
    ``Registry.register_printing``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_SPOROGENIC_INFECTION_RUST_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Sporogenic Infection"


# ---------------------------------------------------------------------------
# (4) Cross-engine bridge round-trip pins.
# ---------------------------------------------------------------------------


def test_cross_engine_bridge_round_trip_for_target_opponent_sacrifices_other_than_enchanted():
    """**Forward + reverse bridge round-trip.**
    ``_ta_dict_to_python_effect({"kind": "target_opponent_sacrifices_
    creature_other_than_enchanted"})`` returns
    ``TargetOpponentSacrificesCreatureOtherThanEnchanted()``; the
    inverse ``_python_ta_to_safe_dict_aura_phase3`` emitter for the
    same shape produces a dict whose effect kind is exactly that
    string. Round-trip byte-equal.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.opponent_punishers import (
        TargetOpponentSacrificesCreatureOtherThanEnchanted,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # Forward (dict -> Python).
    eff = _ta_dict_to_python_effect(
        {
            "kind": "target_opponent_sacrifices_creature_other_than_enchanted",
        }
    )
    assert isinstance(eff, TargetOpponentSacrificesCreatureOtherThanEnchanted)

    # Reverse (Python -> dict).
    ta = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(subject=None),
        effect=TargetOpponentSacrificesCreatureOtherThanEnchanted(),
        once_per_turn=False,
    )
    d = trajectory._python_ta_to_safe_dict_aura_phase3(ta)
    assert d == {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "target_opponent_sacrifices_creature_other_than_enchanted",
        },
        "once_per_turn": False,
    }


# ---------------------------------------------------------------------------
# (5) Scenario 1 — ETB resolve + target opponent sacrifices a non-host
# creature.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_sporogenic_infection_etb_sacrifice_scenario_1_parity():
    """**Scenario 1 — THE LOAD-BEARING ETB sacrifice path.** Drives
    the live Sporogenic Infection printing through its ENTERS-trigger
    long pole on the Python engine:

      Pre-state:
        * p0's Sporogenic Infection on bf, attached to a host on
          p1's side (Sporogenic is enchant-an-opponent's-creature; the
          host is opponent-controlled).
        * p1's bf has: the host bear (the attached one) + TWO
          additional Wild Bear creatures (so the target has 3
          creatures total, of which one is the host).
        * Both players use ``_PickFirstAgent``.

      Drive: put Sporogenic Infection onto p0's bf attached to the
      host, then call ``_trigger_etb_abilities`` to fire its ENTERS
      trigger. The trigger queues + targets p1 (the only legal
      opponent target). On resolve:
        * The candidate enumeration walks p1's bf creatures filtered
          to id != host_id (the Aura's attached_to).
        * Two candidates remain (the two non-host bears).
        * p1's agent ``choose_sacrifice`` picks the first non-host
          candidate id.
        * That bear leaves p1's bf and lands on p1's graveyard.

      Post-resolve:
        * p1's bf: host_bear + ONE non-host bear (one was sacrificed).
        * p1's graveyard: ONE bear (the sacrificed one).
        * The host bear REMAINS on bf (it was excluded from the sac
          options per the "other than enchanted creature" clause).
        * Sporogenic Infection still on bf (it just resolved; only
          dies if the host leaves).
        * Stack empty.
    """
    from mtg_bot.actions import drain_stack
    from mtg_bot.actions import _trigger_etb_abilities as _eat
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0

    # p1's host bear on bf (unsick) — the Aura's attached_to.
    host_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    host_bear.summoning_sick = False
    state.battlefield.append(host_bear)

    # p1's TWO additional Wild Bears (the sac candidates).
    nonhost_bear_1 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    nonhost_bear_1.summoning_sick = False
    state.battlefield.append(nonhost_bear_1)
    nonhost_bear_2 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    nonhost_bear_2.summoning_sick = False
    state.battlefield.append(nonhost_bear_2)

    # p0's Sporogenic Infection on bf, attached to p1's host bear
    # (mirrors the bench-loader admit-then-attach flow; the ENTERS
    # trigger is the long pole the probe drives).
    sporogenic = state.new_object(
        _PRINTINGS["Sporogenic Infection"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    sporogenic.attached_to = host_bear.id
    state.battlefield.append(sporogenic)

    # ---- Drive: ENTERS-trigger fan-out for Sporogenic Infection (the
    # Aura itself entering -> IsSelf(subject=None) matches; the trigger
    # pushes a stack item; resolve walks the
    # TargetOpponentSacrificesCreatureOtherThanEnchanted.resolve path).
    _eat(state, sporogenic)
    drain_stack(state)

    # ---- Post-resolve observables.
    # First non-host bear (deterministic-first) sacrificed.
    assert nonhost_bear_1 in state.players[1].graveyard, (
        "First non-host bear (deterministic-first sac choice) must "
        "have been sacrificed"
    )
    assert nonhost_bear_1 not in state.battlefield
    # The OTHER non-host bear stays on bf.
    assert nonhost_bear_2 in state.battlefield
    # The host bear is excluded from the sac options ("other than
    # enchanted creature") and remains on bf.
    assert host_bear in state.battlefield, (
        "Host bear must remain on bf — excluded from sac options "
        "per the 'other than enchanted creature' clause"
    )
    # Sporogenic Infection still on bf (host alive, Aura legal).
    assert sporogenic in state.battlefield
    # Stack drained.
    assert state.stack == []


# ---------------------------------------------------------------------------
# (6) Scenario 2 — ETB resolve when target controls ONLY the host
# (silent no-op).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_sporogenic_infection_etb_only_host_silent_fizzle_scenario_2_parity():
    """**Scenario 2 — Empty candidate set (silent no-op).** Drives the
    ETB-trigger long pole when the target controls ONLY the host:

      Pre-state:
        * p0's Sporogenic Infection on bf, attached to p1's host bear.
        * p1's bf has ONLY the host bear (no other creatures).
        * Both players use ``_PickFirstAgent``.

      Drive: fire Sporogenic's ENTERS trigger. Resolve walks:
        * Candidate enumeration filters p1's bf to creatures whose
          id != host_id. Empty (host was the only creature, and is
          excluded).
        * ``if not legal: return`` -> silent fizzle.

      Post-resolve:
        * p1's bf: ONLY the host bear (unchanged).
        * p1's graveyard: EMPTY (no sacrifice happened).
        * Sporogenic Infection still on bf.
        * Stack drained.
    """
    from mtg_bot.actions import drain_stack
    from mtg_bot.actions import _trigger_etb_abilities as _eat
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0

    host_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    host_bear.summoning_sick = False
    state.battlefield.append(host_bear)

    sporogenic = state.new_object(
        _PRINTINGS["Sporogenic Infection"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    sporogenic.attached_to = host_bear.id
    state.battlefield.append(sporogenic)

    # ---- Drive.
    _eat(state, sporogenic)
    drain_stack(state)

    # ---- Post-resolve observables: nothing changed.
    assert host_bear in state.battlefield
    assert state.players[1].graveyard == []
    assert sporogenic in state.battlefield
    # Stack drained.
    assert state.stack == []


# ---------------------------------------------------------------------------
# (7) Scenario 3 — Combat damage path, Tail-X1 DestroyEnchantedPermanent.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_sporogenic_infection_dealt_damage_destroy_host_scenario_3_parity():
    """**Scenario 3 — Tail-X1 DEALT_DAMAGE destroys the enchanted host.**
    Drives the second triggered ability via the
    ``_fire_enchanted_dealt_damage_triggers`` dispatch (the same
    centralized fire site combat damage uses):

      Pre-state:
        * p0's Wild Bear on bf (the host) attached to Sporogenic
          Infection.

      Drive: call
      ``_fire_enchanted_dealt_damage_triggers(state, host_bear, 1)``
      directly (the same dispatch_event Event.DEALT_DAMAGE call
      combat code uses). Sporogenic Infection's IsHost predicate
      matches (its attached_to == host_bear.id). The trigger queues +
      resolves; the DestroyEnchantedPermanent.resolve arm reads
      ``state.resolving_source`` (Sporogenic Infection) and destroys
      its attached_to (the host bear). Then a CR 704.5n state-based
      action sweeps Sporogenic off the battlefield because its
      enchanted host is gone.

      Post-resolve:
        * host_bear OFF bf (destroyed -> p0's graveyard).
        * Sporogenic Infection OFF bf (CR 704.5n SBA: Aura attached
          to nothing -> graveyard).
    """
    from mtg_bot.actions import drain_stack
    from mtg_bot.combat import _fire_enchanted_dealt_damage_triggers
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import state_based_actions

    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0

    host_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    host_bear.summoning_sick = False
    state.battlefield.append(host_bear)

    sporogenic = state.new_object(
        _PRINTINGS["Sporogenic Infection"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    sporogenic.attached_to = host_bear.id
    state.battlefield.append(sporogenic)

    # Sanity pre-state.
    assert host_bear in state.battlefield
    assert sporogenic in state.battlefield
    assert sporogenic.attached_to == host_bear.id

    # ---- Drive: enchanted creature is dealt 1 damage -> Tail-X1 fires.
    _fire_enchanted_dealt_damage_triggers(state, host_bear, 1)
    drain_stack(state)
    # Extra SBA pass for the Aura-attached-to-nothing CR 704.5n sweep.
    state_based_actions(state)

    # ---- Post-resolve observables.
    assert host_bear not in state.battlefield, (
        "Host bear must be destroyed by Sporogenic Infection's Tail-X1"
    )
    assert host_bear in state.players[0].graveyard, (
        "Host bear must move to p0's graveyard via destroy"
    )
    # Sporogenic Infection falls off via CR 704.5n SBA (Aura attached
    # to nothing).
    assert sporogenic not in state.battlefield, (
        "Sporogenic Infection must fall off via CR 704.5n SBA after "
        "host leaves"
    )
    assert state.stack == []


# ---------------------------------------------------------------------------
# (8) Aura-set-walk no-silent-auto-grow pin — the EXACT set of EoE
# Auras admitted by ``_printing_is_bridge_simple_aura`` post-Phase-C
# closure has grown by ONE (Sporogenic Infection), no surprise admits.
# ---------------------------------------------------------------------------


def test_aura_admit_set_includes_sporogenic_infection_post_phase_c_closure():
    """**No-silent-auto-grow pin.** The admit set grew from {Phase B
    closure} ∪ {Cracked Skull} to {Phase B closure} ∪ {Cracked Skull,
    Sporogenic Infection} — Sporogenic is the ONLY Aura newly admitted
    by this slice. Cryoshatter remains explicitly DECLINED (the
    BECOMES_TAPPED + IsHost + DestroyEnchantedPermanent shape is still
    outside the safe set).
    """
    from mtg_bot.parity import trajectory

    # Sporogenic ADMITS (newly).
    assert (
        trajectory._printing_is_bridge_simple_aura(
            _PRINTINGS["Sporogenic Infection"]
        )
        is True
    )
    # Cryoshatter DECLINES (still). No silent auto-grow.
    assert (
        trajectory._printing_is_bridge_simple_aura(_PRINTINGS["Cryoshatter"])
        is False
    )
    # Cracked Skull still admits (Phase B carrier, adjacent regression).
    assert (
        trajectory._printing_is_bridge_simple_aura(_PRINTINGS["Cracked Skull"])
        is True
    )
    # Chorale of the Void still admits (Phase A carrier, adjacent
    # regression).
    assert (
        trajectory._printing_is_bridge_simple_aura(
            _PRINTINGS["Chorale of the Void"]
        )
        is True
    )


# ---------------------------------------------------------------------------
# (9) Rust substrate pin — the new PendingDecision::SacrificeChoice
# pending-decisions surface dict.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (9) Rust substrate pins — drive PendingDecision::SacrificeChoice
# via a synthetic Sorcery-shape spell that carries the new Effect as
# its spell_effect (mirroring the Phase B Cycle 1 substrate test
# pattern at ``test_aura_phase_3_phase_b_substrate_cycle_1.py:72``).
# This isolates the Rust resolve arm + decision-pump dispatchers
# from the Aura admit/attach plumbing.
#
# **NB: the synthetic Sorcery spell has no source_obj on the
# battlefield with attached_to set**, so the Rust resolve arm's
# excluded_id derivation returns None and the candidate filter
# admits the WHOLE target's bf creature set. This is the right
# substrate-only shape — the per-card real-EoE probe in Scenario 1
# above is the load-bearing pin that the Aura's attached_to is read
# correctly at resolve time and excludes the host.
# ---------------------------------------------------------------------------


# Zone constants -- mirror ``rust/src/state_ops_zones.rs``.
_ZONE_HAND = 0
_ZONE_LIBRARY = 1
_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3


def _opponent_sac_spell_dict():
    """A Sorcery-shape spell carrying the new Effect as its spell
    effect -- used for direct resolve-arm pins via the stack-push
    path. The Sorcery shape lets us drive the resolve arm without
    routing through the Aura admit/attach machinery; the cost is
    that source.attached_to is None at resolve time (so the resolve
    arm's excluded_id is None and the candidate filter admits ALL
    target creatures). The Aura attached_to exclusion is pinned by
    Scenario 1 above via the live printing's Python engine drive.
    """
    return {
        "name": "Test Opponent Sac Spell",
        "card_types": ["Sorcery"],
        "effects": [
            {
                "kind": "target_opponent_sacrifices_creature_other_than_enchanted",
            }
        ],
    }


@_rust_skip
def test_rust_resolve_pushes_sacrifice_choice_with_excluded_object_id_none():
    """**Rust resolve arm pin -- happy path (synthetic Sorcery
    source).** The Sorcery spell has no attached_to (source isn't an
    Aura), so excluded_object_id surfaces as None; the candidate set
    is the full target opponent's creature bf. Mirrors the C1
    Phase-B substrate test fixture shape.
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    # Two creatures on p1's bf.
    creature_ids: list[int] = []
    for name in ["Creature A", "Creature B"]:
        cid = state.register_and_inject_object(
            {
                "name": name,
                "card_types": ["Creature"],
                "subtypes": ["Bear"],
                "mana_cost": {"generic": 1, "G": 1},
                "power": 2,
                "toughness": 2,
            },
            1,
            _ZONE_BATTLEFIELD,
        )
        creature_ids.append(cid)
    spell_id = state.register_and_inject_object(
        _opponent_sac_spell_dict(), 0, _ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()
    pds = state.pending_decisions()
    sac_choices = [p for p in pds if p["kind"] == "SacrificeChoice"]
    assert len(sac_choices) == 1
    sc = sac_choices[0]
    # Resolving controller is p0; target opponent is p1.
    assert sc["controller"] == 0
    assert sc["target_player_id"] == 1
    # Both creatures on p1's bf are candidates (Sorcery source -> no
    # excluded host).
    assert sorted(sc["candidates"]) == sorted(creature_ids)
    # excluded_object_id is None (the source is a Sorcery, not an
    # attached Aura).
    assert sc["excluded_object_id"] is None


@_rust_skip
def test_rust_resolve_silent_fizzle_when_target_bf_empty():
    """**Rust resolve arm pin -- empty-bf gate.** Target opponent
    (p1) has no creatures -> silent fizzle, no SacrificeChoice push.
    Mirrors the C1 Phase-B empty-hand silent-fizzle pin.
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    spell_id = state.register_and_inject_object(
        _opponent_sac_spell_dict(), 0, _ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack()
    pds = state.pending_decisions()
    sac_choices = [p for p in pds if p["kind"] == "SacrificeChoice"]
    assert sac_choices == []


@_rust_skip
def test_rust_resolve_filters_noncreatures_from_candidates():
    """**Rust resolve arm pin -- creature filter.** Non-creature
    permanents (e.g. lands) on the target's bf MUST be filtered out
    of the candidate set. Mirrors Python's `o.printing.is_creature`
    filter at opponent_punishers.py:124.
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    # One creature + one land on p1's bf.
    creature_id = state.register_and_inject_object(
        {
            "name": "Test Bear",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1,
        _ZONE_BATTLEFIELD,
    )
    land_id = state.register_and_inject_object(
        {
            "name": "Test Land",
            "card_types": ["Land"],
            "mana_cost": {},
        },
        1,
        _ZONE_BATTLEFIELD,
    )
    spell_id = state.register_and_inject_object(
        _opponent_sac_spell_dict(), 0, _ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()
    pds = state.pending_decisions()
    sac_choices = [p for p in pds if p["kind"] == "SacrificeChoice"]
    assert len(sac_choices) == 1
    sc = sac_choices[0]
    # Only the creature is a candidate; the land is filtered.
    assert sc["candidates"] == [creature_id]
    assert land_id not in sc["candidates"]


@_rust_skip
def test_rust_submit_sacrifice_decision_happy_path_sacrifices_creature():
    """**Submit dispatcher pin -- happy path.** ``submit_sacrifice_
    decision(Some(id))`` validates the id is in candidates, removes
    the creature from the target's bf, and moves it to the target's
    graveyard via the shared sacrifice_inline helper.
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    creature_ids: list[int] = []
    for name in ["Creature X", "Creature Y"]:
        cid = state.register_and_inject_object(
            {
                "name": name,
                "card_types": ["Creature"],
                "subtypes": ["Bear"],
                "mana_cost": {"generic": 1, "G": 1},
                "power": 2,
                "toughness": 2,
            },
            1,
            _ZONE_BATTLEFIELD,
        )
        creature_ids.append(cid)
    spell_id = state.register_and_inject_object(
        _opponent_sac_spell_dict(), 0, _ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()

    # Submit a specific candidate (the SECOND, not the auto-default).
    chosen_id = creature_ids[1]
    state.submit_sacrifice_decision(chosen_id)

    # That creature moved to p1's graveyard; the other remains on bf.
    assert state.find_object_zone(chosen_id) == _ZONE_GRAVEYARD
    assert state.find_object_zone(creature_ids[0]) == _ZONE_BATTLEFIELD


@_rust_skip
def test_rust_submit_sacrifice_decision_rejects_unknown_id():
    """**Submit dispatcher pin -- transactional validation.** An
    unknown chosen_id raises ValueError WITHOUT mutating state (the
    pending decision stays on the queue).
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    creature_id = state.register_and_inject_object(
        {
            "name": "Test Bear",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1,
        _ZONE_BATTLEFIELD,
    )
    spell_id = state.register_and_inject_object(
        _opponent_sac_spell_dict(), 0, _ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()

    with pytest.raises(ValueError, match="not one of the candidate"):
        state.submit_sacrifice_decision(99999)
    # Queue intact post-failed-submit.
    pds = state.pending_decisions()
    assert pds[0]["kind"] == "SacrificeChoice"
    # Creature still on bf.
    assert state.find_object_zone(creature_id) == _ZONE_BATTLEFIELD


@_rust_skip
def test_rust_submit_sacrifice_decision_none_is_silent_fizzle():
    """**Submit dispatcher pin -- decline path.** ``submit_sacrifice
    _decision(None)`` consumes the head without sacrificing (silent
    fizzle; defensive, since the production push gates on
    non-empty candidates).
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    creature_id = state.register_and_inject_object(
        {
            "name": "Test Bear",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2,
            "toughness": 2,
        },
        1,
        _ZONE_BATTLEFIELD,
    )
    spell_id = state.register_and_inject_object(
        _opponent_sac_spell_dict(), 0, _ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()

    state.submit_sacrifice_decision(None)
    # Queue drained; creature still on bf.
    pds = state.pending_decisions()
    assert not any(p["kind"] == "SacrificeChoice" for p in pds)
    assert state.find_object_zone(creature_id) == _ZONE_BATTLEFIELD


@_rust_skip
def test_rust_submit_sacrifice_decision_no_pending_raises():
    """**Submit dispatcher pin -- empty-queue guard.** Calling
    ``submit_sacrifice_decision`` with no pending decision raises
    ValueError.
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    with pytest.raises(ValueError, match="no pending decision"):
        state.submit_sacrifice_decision(42)
    with pytest.raises(ValueError, match="no pending decision"):
        state.submit_sacrifice_decision(None)


@_rust_skip
def test_rust_submit_sacrifice_decision_rejects_wrong_head():
    """**Submit dispatcher pin -- discriminant mismatch.** When the
    head of the pending-decisions queue is a different variant,
    submit_sacrifice_decision rejects with a typed error and the
    decision STAYS on the queue.
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield=0, num_hand=1, num_library=10,
    )
    surveil_pid = state.register_and_inject_object(
        {
            "name": "Test Surveil Spell (sac-dispatcher discriminant guard)",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "surveil", "count": 2}],
        },
        0,
        _ZONE_HAND,
    )
    state.push_to_stack(surveil_pid, 0)
    state.resolve_top_of_stack_pause()
    pds = state.pending_decisions()
    assert pds[0]["kind"] == "SurveilChoice"
    with pytest.raises(
        ValueError,
        match="head of pending-decisions queue is not a SacrificeChoice",
    ):
        state.submit_sacrifice_decision(42)
    pds_after = state.pending_decisions()
    assert pds_after[0]["kind"] == "SurveilChoice"


@_rust_skip
def test_rust_auto_resolve_sacrifice_first_picks_candidates_zero():
    """**Auto-resolve default pin.** ``auto_resolve_pending_
    decisions("default")`` / `"sacrifice_first"` picks candidates[0]
    (deterministic-first; mirrors the
    OpponentHandCardChoice / GraveyardCardChoice convention).
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    creature_ids: list[int] = []
    for name in ["Creature Alpha", "Creature Beta"]:
        cid = state.register_and_inject_object(
            {
                "name": name,
                "card_types": ["Creature"],
                "subtypes": ["Bear"],
                "mana_cost": {"generic": 1, "G": 1},
                "power": 2,
                "toughness": 2,
            },
            1,
            _ZONE_BATTLEFIELD,
        )
        creature_ids.append(cid)
    spell_id = state.register_and_inject_object(
        _opponent_sac_spell_dict(), 0, _ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()

    state.auto_resolve_pending_decisions("default")
    # First creature (candidates[0]) sacrificed; the second remains.
    assert state.find_object_zone(creature_ids[0]) == _ZONE_GRAVEYARD
    assert state.find_object_zone(creature_ids[1]) == _ZONE_BATTLEFIELD


@_rust_skip
def test_rust_auto_resolve_sacrifice_first_strategy_explicit():
    """**Auto-resolve explicit-strategy pin.** The explicit
    ``"sacrifice_first"`` strategy name is recognized (not just
    ``"default"``).
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    creature_ids: list[int] = []
    for name in ["Creature A1", "Creature B1"]:
        cid = state.register_and_inject_object(
            {
                "name": name,
                "card_types": ["Creature"],
                "subtypes": ["Bear"],
                "mana_cost": {"generic": 1, "G": 1},
                "power": 2,
                "toughness": 2,
            },
            1,
            _ZONE_BATTLEFIELD,
        )
        creature_ids.append(cid)
    spell_id = state.register_and_inject_object(
        _opponent_sac_spell_dict(), 0, _ZONE_HAND,
    )
    state.push_to_stack(spell_id, 0)
    state.resolve_top_of_stack_pause()
    state.auto_resolve_pending_decisions("sacrifice_first")
    assert state.find_object_zone(creature_ids[0]) == _ZONE_GRAVEYARD


@_rust_skip
def test_rust_auto_resolve_rejects_unknown_strategy():
    """**Auto-resolve strategy validation pin.** Strategies not in
    the allowlist raise ValueError.
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield=0, num_hand=0, num_library=10,
    )
    with pytest.raises(ValueError, match="unknown strategy"):
        state.auto_resolve_pending_decisions("not_a_real_strategy_for_sac")
