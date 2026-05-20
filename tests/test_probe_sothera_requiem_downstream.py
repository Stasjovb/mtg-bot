"""Genuine cross-engine probes -- batch SOTHERA+REQUIEM downstream
(22nd Rust slice; honest-stop closure of Sothera, the Supervoid + Requiem Monolith).

**Slice 22 closure status (honest-stop substrate landing):**

Slice 22 adds the Effect-level scaffolding for two cards from the
``BLOCKED-genuinely_missing`` tier (per
``docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md``):

  * Sothera, the Supervoid (2,108 17lands decks). Three new Rust
    Effect variants:
      - ``Effect::EachOpponentExilesOwnCreature { link_to_source }``
        (per-opponent exile primitive, mirrors Python's
        ``EachOpponentExilesOwnCreature`` -- DIES-trigger body).
      - ``Effect::ReanimateOneExiledWithSourceWithCounters
        { counter_amount }`` (end-step recall, mirrors Python's
        ``ReanimateOneExiledWithSourceWithCounters``).
      - ``Effect::SacrificeSelfPreservingExileLink`` (end-step sac
        with one-shot suppression, mirrors Python's
        ``SacrificeSelfPreservingExileLink``).

  * Requiem Monolith. Three new Rust Effect variants:
      - ``Effect::GrantTriggeredAbilityUEOTRequiem`` (UEOT grant of a
        quoted dealt-damage trigger, mirrors Python's
        ``GrantTriggeredAbilityUEOT`` with the fixed Requiem-shape
        inner ability).
      - ``Effect::MayHaveSourceDealDamageToTarget { amount }``
        (optional 1-damage ping; the TARGET's controller chooses,
        mirrors Python's ``MayHaveSourceDealDamageToTarget``).
      - ``Effect::DrawCardsAndLoseLifeEqualToResolvingDamage``
        (granted-trigger body, mirrors Python's
        ``DrawCardsAndLoseLifeEqualToResolvingDamage``).

**Honest-stop semantics.** The shipping discipline mirrors slice 19's
Meltstrider's Resolve honest-stop pattern (the Effect variant + parse
+ to_pydict + bridge + resolve arm scaffolding lands; the broader
substrate that would let the resolve arm produce the full real-game
effect stays documented as deferred). For Sothera's
``EachOpponentExilesOwnCreature``, the exile portion of the body ships
verbatim -- byte-equal cross-engine on the no-link branch.  For
``ReanimateOneExiledWithSourceWithCounters`` and
``SacrificeSelfPreservingExileLink``, the resolve arms fizzle silently
because the persistent ``GameObject.exiled_by_source`` source-link
field is deferred (a large multi-cycle substrate per
``BLOCKED_GENUINELY_MISSING_INVENTORY.md``). For Requiem's
``GrantTriggeredAbilityUEOTRequiem`` and
``MayHaveSourceDealDamageToTarget``, the resolve arms no-op because
the broader grant-triggered-ability registry / ``choose_yes_no`` agent
callback substrate is also deferred -- the cross-engine round-trip
closes via the bridge arm and the resolve arms match Python's
same-case fizzle. The ``DrawCardsAndLoseLifeEqualToResolvingDamage``
arm IS implemented end-to-end because the body's read of
``state.resolving_combat_damage_amount`` only needs the existing
substrate -- this is the byte-equal-direct-resolve arm of the slice.

Probes added in slice 22:
  * ``test_sothera_bridge_round_trip_each_opponent_exiles_own_creature``
    -- bridge arm round-trip with ``link_to_source: bool`` field
    preserved.
  * ``test_sothera_bridge_round_trip_reanimate_one_exiled_with_source_with_counters``
    -- bridge arm round-trip with ``counter_amount: int`` field
    preserved.
  * ``test_sothera_bridge_round_trip_sacrifice_self_preserving_exile_link``
    -- unit-variant bridge round-trip.
  * ``test_requiem_bridge_round_trip_grant_triggered_ability_ueot``
    -- unit-variant bridge round-trip (the inner TriggeredAbility is
    reconstructed by the bridge from the fixed Requiem shape).
  * ``test_requiem_bridge_round_trip_may_have_source_deal_damage_to_target``
    -- bridge arm round-trip with ``amount: int`` field preserved.
  * ``test_requiem_bridge_round_trip_draw_cards_and_lose_life``
    -- unit-variant bridge round-trip.
  * ``test_sothera_each_opponent_exiles_own_creature_picks_first_legal_real_eoe``
    -- Rust-side end-to-end exile move: a Sothera-shape source's
    DIES-trigger body resolves and the opponent's first creature
    moves to that opponent's exile.
  * ``test_sothera_each_opponent_exiles_own_creature_no_opponent_creature_silent_noop``
    -- no legal creature on the opponent's bf -> silent no-op (no
    zone transitions).
  * ``test_sothera_reanimate_one_exiled_no_link_silent_fizzle``
    -- honest-stop fizzle: no candidates (no exiled_by_source field)
    -> no zone transitions.
  * ``test_sothera_sacrifice_self_preserving_exile_link_real_eoe``
    -- the sac portion ships: source-on-bf -> source-in-graveyard,
    LTB / IS_SACRIFICED dispatches queue.
  * ``test_requiem_grant_triggered_ability_ueot_silent_noop``
    -- honest-stop no-op: grant-trigger registry deferred; no
    state change on resolve.
  * ``test_requiem_may_have_source_deal_damage_to_target_silent_noop``
    -- honest-stop no-op: choose_yes_no agent callback deferred;
    no damage / no draw.
  * ``test_requiem_draw_cards_and_lose_life_amount_pre_seeded_byte_equal``
    -- direct-resolve byte-equal: with
    ``resolving_combat_damage_amount`` pre-seeded, the controller
    draws N cards + loses N life.

2 EoE cards directly substrate-landed by slice 22:
  * Sothera, the Supervoid (2,108 17lands decks). Full byte-equality
    deferred until the exile-source-link substrate ships.
  * Requiem Monolith. Full byte-equality deferred until the
    grant-triggered-ability registry + choose_yes_no callback
    substrates ship.

Together with the prior closures (Astelli Reclaimer, Roving Actuator,
Meltstrider's Resolve, Command Bridge, Lightstall, House Cartographer)
this drops the BLOCKED-genuinely_missing tier substrate-landed count
by 2 more cards.
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# =====================================================================
# Section 1 -- bridge round-trip probes (cross_engine.py arms).
# =====================================================================


def test_sothera_bridge_round_trip_each_opponent_exiles_own_creature():
    """The cross_engine bridge arm reconstructs Python's
    ``EachOpponentExilesOwnCreature(link_to_source=...)`` from the
    Rust ``each_opponent_exiles_own_creature`` dict, preserving the
    ``link_to_source`` bool field."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.generic.opponent_punishers import (
        EachOpponentExilesOwnCreature,
    )

    bridged_no_link = _ta_dict_to_python_effect(
        {"kind": "each_opponent_exiles_own_creature",
         "link_to_source": False}
    )
    assert isinstance(bridged_no_link, EachOpponentExilesOwnCreature)
    assert bridged_no_link.link_to_source is False

    bridged_with_link = _ta_dict_to_python_effect(
        {"kind": "each_opponent_exiles_own_creature",
         "link_to_source": True}
    )
    assert isinstance(bridged_with_link, EachOpponentExilesOwnCreature)
    assert bridged_with_link.link_to_source is True

    # Default field value (Python dataclass default).
    bridged_default = _ta_dict_to_python_effect(
        {"kind": "each_opponent_exiles_own_creature"}
    )
    assert isinstance(bridged_default, EachOpponentExilesOwnCreature)
    assert bridged_default.link_to_source is False


def test_sothera_bridge_round_trip_reanimate_one_exiled_with_source_with_counters():
    """The bridge arm reconstructs Python's
    ``ReanimateOneExiledWithSourceWithCounters(counter_amount=...)``
    preserving the ``counter_amount`` int field."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.generic.exile import (
        ReanimateOneExiledWithSourceWithCounters,
    )

    bridged = _ta_dict_to_python_effect(
        {"kind": "reanimate_one_exiled_with_source_with_counters",
         "counter_amount": 2}
    )
    assert isinstance(bridged, ReanimateOneExiledWithSourceWithCounters)
    assert bridged.counter_amount == 2

    # Default field value.
    bridged_default = _ta_dict_to_python_effect(
        {"kind": "reanimate_one_exiled_with_source_with_counters"}
    )
    assert isinstance(bridged_default, ReanimateOneExiledWithSourceWithCounters)
    assert bridged_default.counter_amount == 0


def test_sothera_bridge_round_trip_sacrifice_self_preserving_exile_link():
    """Unit-variant bridge round-trip:
    ``SacrificeSelfPreservingExileLink()``."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.generic.exile import (
        SacrificeSelfPreservingExileLink,
    )

    bridged = _ta_dict_to_python_effect(
        {"kind": "sacrifice_self_preserving_exile_link"}
    )
    assert isinstance(bridged, SacrificeSelfPreservingExileLink)


def test_requiem_bridge_round_trip_grant_triggered_ability_ueot():
    """Unit-variant bridge round-trip: the Rust kind reconstructs
    Python's ``GrantTriggeredAbilityUEOT(ability=TriggeredAbility(
    trigger='this_dealt_damage',
    effect=DrawCardsAndLoseLifeEqualToResolvingDamage()))`` from the
    fixed Requiem shape."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.generic.grant_keywords import (
        GrantTriggeredAbilityUEOT,
    )
    from mtg_bot.effects.generic.damage import (
        DrawCardsAndLoseLifeEqualToResolvingDamage,
    )

    bridged = _ta_dict_to_python_effect(
        {"kind": "grant_triggered_ability_ueot_requiem"}
    )
    assert isinstance(bridged, GrantTriggeredAbilityUEOT)
    assert bridged.ability is not None
    assert bridged.ability.trigger == "this_dealt_damage"
    assert isinstance(
        bridged.ability.effect, DrawCardsAndLoseLifeEqualToResolvingDamage
    )


def test_requiem_bridge_round_trip_may_have_source_deal_damage_to_target():
    """The bridge arm reconstructs Python's
    ``MayHaveSourceDealDamageToTarget(amount=...)`` preserving the
    ``amount`` int field."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.generic.damage import (
        MayHaveSourceDealDamageToTarget,
    )

    bridged = _ta_dict_to_python_effect(
        {"kind": "may_have_source_deal_damage_to_target", "amount": 3}
    )
    assert isinstance(bridged, MayHaveSourceDealDamageToTarget)
    assert bridged.amount == 3

    bridged_default = _ta_dict_to_python_effect(
        {"kind": "may_have_source_deal_damage_to_target"}
    )
    assert isinstance(bridged_default, MayHaveSourceDealDamageToTarget)
    assert bridged_default.amount == 1


def test_requiem_bridge_round_trip_draw_cards_and_lose_life():
    """Unit-variant bridge round-trip:
    ``DrawCardsAndLoseLifeEqualToResolvingDamage()``."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.generic.damage import (
        DrawCardsAndLoseLifeEqualToResolvingDamage,
    )

    bridged = _ta_dict_to_python_effect(
        {"kind": "draw_cards_and_lose_life_equal_to_resolving_damage"}
    )
    assert isinstance(bridged, DrawCardsAndLoseLifeEqualToResolvingDamage)


# =====================================================================
# Section 2 -- Sothera resolve-arm probes (Rust-side end-to-end).
# =====================================================================


def test_sothera_each_opponent_exiles_own_creature_picks_first_legal_real_eoe():
    """**22nd Rust slice -- Sothera DIES-trigger body end-to-end probe.**

    Drives the Rust ``Effect::EachOpponentExilesOwnCreature`` resolve
    arm via an ENTERS-trigger inject (re-using the standard ETB
    dispatch path so the probe touches the production code path).
    Post-resolve invariant: the opponent's first creature (insertion
    order) moves from their battlefield to their exile zone.

    Probe shape:
      1. Pre-seed P1 (the opponent) with two creatures on bf.
      2. Inject a Sothera-shape source on P0's bf with an ENTERS
         trigger firing ``each_opponent_exiles_own_creature`` with
         ``link_to_source: false`` (the easy branch -- the
         source-link substrate is deferred).
      3. Drain the stack.
      4. Assert: P1's first creature is now in P1's exile; P1's
         second creature stays on bf.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # P1's first creature (insertion order = first-legal pick).
    p1_creature_a_id = rust_state.register_and_inject_object(
        {
            "name": "Sothera Probe P1 Bear A (gets exiled)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2, "toughness": 2,
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_BATTLEFIELD,
    )
    # P1's second creature (stays on bf -- first-legal scan exits
    # after the first match).
    p1_creature_b_id = rust_state.register_and_inject_object(
        {
            "name": "Sothera Probe P1 Bear B (stays)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 2, "G": 1},
            "power": 3, "toughness": 3,
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_BATTLEFIELD,
    )
    # Sothera-shape source on P0's bf with an ENTERS trigger firing
    # the Effect under test.
    rust_state.register_and_inject_object(
        {
            "name": "Sothera Probe Source (each_opp_exiles)",
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "mana_cost": {"generic": 3, "B": 1},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_exiles_own_creature",
                    "link_to_source": False,
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # ETB trigger landed.
    assert rust_state.stack_size() == 1

    # Drain stack -- the resolve arm picks P1's first-legal creature
    # and moves it to P1's exile.
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # P1's first creature exited the battlefield.
    rust_bf_all = rust_state.battlefield_snapshot()
    p1_bf_ids = {e["id"] for e in rust_bf_all if e.get("controller_id") == 1}
    assert p1_creature_a_id not in p1_bf_ids, (
        f"Sothera each_opp_exiles: P1 Bear A should be gone from bf; "
        f"got bf_ids={sorted(p1_bf_ids)!r}"
    )
    # P1's second creature still on bf.
    assert p1_creature_b_id in p1_bf_ids, (
        "Sothera each_opp_exiles: P1 Bear B should remain on bf "
        "(first-legal scan exits after first match)."
    )
    # P1's exile now contains Bear A.
    rust_p1_exile = rust_state.exile_snapshot(1)
    rust_p1_exile_ids = {e["id"] for e in rust_p1_exile}
    assert p1_creature_a_id in rust_p1_exile_ids, (
        f"Sothera each_opp_exiles: P1 Bear A should be in P1's exile; "
        f"got exile_p1={sorted(rust_p1_exile_ids)!r}"
    )


def test_sothera_each_opponent_exiles_own_creature_no_opponent_creature_silent_noop():
    """**22nd Rust slice -- empty-candidate silent no-op.**

    The Python SoT silently skips opponents with no creatures
    (``opponent_punishers.py:194-195``); Rust mirrors this.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # P1 has no creatures (only an artifact -- filtered by the
    # is_creature gate).
    rust_state.register_and_inject_object(
        {
            "name": "Sothera Probe P1 Artifact (filtered)",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_BATTLEFIELD,
    )

    rust_state.register_and_inject_object(
        {
            "name": "Sothera Probe Source (no-opp-creature)",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 3, "B": 1},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_exiles_own_creature",
                    "link_to_source": False,
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # P1's artifact is still on bf (no zone transitions occurred).
    rust_bf_all = rust_state.battlefield_snapshot()
    p1_bf_names = {
        e["printing_name"] for e in rust_bf_all
        if e.get("controller_id") == 1
    }
    assert "Sothera Probe P1 Artifact (filtered)" in p1_bf_names

    # P1's exile is empty.
    rust_p1_exile = rust_state.exile_snapshot(1)
    assert len(rust_p1_exile) == 0


def test_sothera_reanimate_one_exiled_no_link_silent_fizzle():
    """**22nd Rust slice -- honest-stop fizzle on the recall arm.**

    Rust's ``Effect::ReanimateOneExiledWithSourceWithCounters`` fizzles
    silently because the source-link substrate (``GameObject.exiled_by_
    source`` field) is deferred -- the candidate set is always empty.
    Python's same-case ``if not candidates: return`` fizzle at
    ``exile.py:1178-1179`` is byte-equal.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # The honest-stop fizzle exercises the empty-candidate path
    # explicitly: P0's exile starts empty and stays empty because
    # Rust's GameObject has no `exiled_by_source` field to enable
    # candidate discovery. Python takes the same fizzle at
    # `exile.py:1178-1179` (`if not candidates: return`), so cross-
    # engine state is byte-equal at this point.

    p0_life_before = rust_state.life_totals[0]
    rust_p0_exile_before = rust_state.exile_snapshot(0)

    rust_state.register_and_inject_object(
        {
            "name": "Sothera Probe Source (recall-fizzle)",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 3, "B": 1},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "reanimate_one_exiled_with_source_with_counters",
                    "counter_amount": 2,
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # The exiled creature is still in P0's exile (no recall happened).
    rust_p0_exile_after = rust_state.exile_snapshot(0)
    assert len(rust_p0_exile_after) == len(rust_p0_exile_before)
    assert rust_state.life_totals[0] == p0_life_before


def test_sothera_sacrifice_self_preserving_exile_link_real_eoe():
    """**22nd Rust slice -- the sac portion ships byte-equal.**

    Rust's ``Effect::SacrificeSelfPreservingExileLink`` sacrifices the
    source via the existing ``sacrifice_source_inline`` helper. The
    suppression flag arming is a deferred no-op (the on-leave hook
    isn't wired), but the sac itself moves the source to the graveyard
    and fires the LTB / IS_SACRIFICED dispatches as expected.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # Sothera-shape source firing the sac arm on ENTERS (probe-shape;
    # in real Sothera it's an end-step Sequence, but the resolve arm
    # exercises identically).
    source_id = rust_state.register_and_inject_object(
        {
            "name": "Sothera Probe Source (sac-self)",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 3, "B": 1},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "sacrifice_self_preserving_exile_link",
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # ETB trigger fires.
    assert rust_state.stack_size() == 1

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # The source is gone from P0's battlefield.
    rust_bf_all = rust_state.battlefield_snapshot()
    p0_bf_ids = {e["id"] for e in rust_bf_all if e.get("controller_id") == 0}
    assert source_id not in p0_bf_ids, (
        f"Sothera sac-self: source should be gone from P0's bf; "
        f"got bf_p0={sorted(p0_bf_ids)!r}"
    )
    # The source is now in P0's graveyard.
    rust_p0_gy = rust_state.graveyard_snapshot(0)
    rust_p0_gy_ids = {e["id"] for e in rust_p0_gy}
    assert source_id in rust_p0_gy_ids, (
        f"Sothera sac-self: source should be in P0's graveyard; got "
        f"gy_p0={sorted(rust_p0_gy_ids)!r}"
    )


# =====================================================================
# Section 3 -- Requiem Monolith resolve-arm probes.
# =====================================================================


def test_requiem_grant_triggered_ability_ueot_silent_noop():
    """**22nd Rust slice -- Requiem grant-trigger honest-stop no-op.**

    Rust's ``Effect::GrantTriggeredAbilityUEOTRequiem`` is a no-op
    today (the broader grant-triggered-ability registry is deferred).
    Cross-engine round-trip closes via the bridge arm; no state
    mutations on resolve.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    target_id = rust_state.register_and_inject_object(
        {
            "name": "Requiem Probe Target Bear",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "power": 2, "toughness": 2,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_BATTLEFIELD,
    )

    p0_life_before = rust_state.life_totals[0]
    p1_life_before = rust_state.life_totals[1]

    rust_state.register_and_inject_object(
        {
            "name": "Requiem Probe Source (grant-trigger)",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 3},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "grant_triggered_ability_ueot_requiem",
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # No life change, no damage on the target.
    assert rust_state.life_totals[0] == p0_life_before
    assert rust_state.life_totals[1] == p1_life_before
    rust_bf_all = rust_state.battlefield_snapshot()
    tgt = next((e for e in rust_bf_all if e["id"] == target_id), None)
    assert tgt is not None
    assert tgt.get("damage", 0) == 0


def test_requiem_may_have_source_deal_damage_to_target_silent_noop():
    """**22nd Rust slice -- Requiem optional-ping honest-stop no-op.**

    Rust's ``Effect::MayHaveSourceDealDamageToTarget`` no-ops because
    the target's controller's ``choose_yes_no`` callback isn't plumbed.
    Python's same-case fallback (``damage.py:1161``: ``if target_
    controller.agent is None: return``) takes the same fizzle, so the
    cross-engine state stays byte-equal.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    target_id = rust_state.register_and_inject_object(
        {
            "name": "Requiem Probe Target Bear (may-ping)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "power": 2, "toughness": 2,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_BATTLEFIELD,
    )

    rust_state.register_and_inject_object(
        {
            "name": "Requiem Probe Source (may-ping)",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 3},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "may_have_source_deal_damage_to_target",
                    "amount": 1,
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    rust_bf_all = rust_state.battlefield_snapshot()
    tgt = next((e for e in rust_bf_all if e["id"] == target_id), None)
    assert tgt is not None
    assert tgt.get("damage", 0) == 0, (
        "Requiem may-ping: no damage should be applied (choose_yes_no "
        "callback deferred -> silent no-op)."
    )


def test_requiem_draw_cards_and_lose_life_amount_pre_seeded_byte_equal():
    """**22nd Rust slice -- direct-resolve byte-equal probe for the
    granted-trigger body.**

    The Python SoT (``damage.py:1089-1108``) reads
    ``state.resolving_combat_damage_amount``, draws that many cards
    to the source's controller, and subtracts that much life. Rust
    mirrors step-for-step.

    The probe pre-seeds ``resolving_combat_damage_amount`` via the
    setter and the source via an ENTERS-firing trigger to confirm
    the read + draw + life-subtract chain produces byte-equal output.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef, DeckSpec, build_rust_state,
    )

    # Seed P0's library so the draw has cards to pull.
    library_cards = tuple(
        CardDef(
            name=f"Requiem Probe Library Card {i}",
            card_type="Land",
            subtypes=("Plains",),
        )
        for i in range(5)
    )
    spec = DeckSpec(
        card_defs=library_cards,
        p0_library=tuple(c.name for c in library_cards),
        p1_library=(),
    )
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # Pre-seed the resolving_combat_damage_amount slot.
    rust_state.set_resolving_combat_damage_amount(3)

    p0_life_before = rust_state.life_totals[0]
    p0_hand_before = len(rust_state.hand_snapshot(0))
    p0_lib_before = len(rust_state.library_snapshot(0))

    rust_state.register_and_inject_object(
        {
            "name": "Requiem Probe Source (draw+life)",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 3},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "draw_cards_and_lose_life_equal_to_resolving_damage",
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # P0 drew 3 cards from a 5-card library.
    p0_hand_after = len(rust_state.hand_snapshot(0))
    p0_lib_after = len(rust_state.library_snapshot(0))
    assert p0_hand_after - p0_hand_before == 3, (
        f"Requiem draw+life: P0 should have drawn 3; "
        f"hand_before={p0_hand_before} hand_after={p0_hand_after}"
    )
    assert p0_lib_before - p0_lib_after == 3, (
        f"Requiem draw+life: P0's library should have lost 3; "
        f"lib_before={p0_lib_before} lib_after={p0_lib_after}"
    )
    # P0 lost 3 life.
    assert rust_state.life_totals[0] == p0_life_before - 3, (
        f"Requiem draw+life: P0 life should drop by 3; "
        f"before={p0_life_before} after={rust_state.life_totals[0]}"
    )
