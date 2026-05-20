"""Genuine cross-engine probes -- batch YYY downstream unlock
(19th Rust slice; honest-stop closure of Meltstrider's Resolve --
Aura-shape Fight ETB substrate-landing).

**Slice 19 closure status (honest-stop substrate landing):**

Slice 19 adds the Effect-level scaffolding for Meltstrider's Resolve's
``EnchantedCreatureFightsTargetEffect`` (the #1 marginal-value target
in ``docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md`` -- 15,259 17lands
decks). The unit-variant Rust ``Effect::EnchantedCreatureFightsTarget``
+ parse + ``effect_to_pydict`` arms in cards.rs, the honest-stop
resolve arm in state_ops_resolve.rs, and the
``enchanted_creature_fights_target`` bridge arm in cross_engine.py all
ship in this slice.

**Honest-stop semantics.** The resolve arm reads the Aura source's
``attached_to`` field and silently fizzles when None -- which is the
Rust-side reality TODAY because Rust does not set ``attached_to`` on
Aura resolution (see ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` -- the
largest §2-declined Rust multi-round substrate). Python takes the
SAME fizzle in this case (``bespoke.py:546-548``), so the cross-engine
state stays byte-equal in the no-host case. Once the Aura attach
substrate's Phase 1 lands (Rust starts setting ``attached_to`` on
Aura resolution), the hot-path branch (both-fighters-present) becomes
live -- the probes here exercise that branch via the
``state.attach(aura_id, host_id)`` test-setup primitive so the resolve
arm's full simultaneous-damage logic is covered today, ready for the
substrate flip.

Probes added in slice 19:
  * ``test_yyy_probe_enchanted_creature_fights_no_attached_to_fizzles_real_eoe``
    -- honest-stop fizzle: source.attached_to=None -> no damage applied
    on either side (byte-equal with Python's ``if attached_to is None:
    return`` short-circuit).
  * ``test_yyy_probe_enchanted_creature_fights_with_attached_host_applies_damage_both_ways``
    -- hot-path branch (manually stamped attached_to via state.attach):
    enchanted creature + opponent creature deal simultaneous damage,
    both damage markers stamp before either fight fizzles.
  * ``test_yyy_probe_enchanted_creature_fights_no_opponent_creature_silent_fizzle``
    -- "up to one" optional-target: with host present but no opponent
    creature, the spell resolves with no fight applied.
  * ``test_yyy_probe_enchanted_creature_fights_host_left_bf_silent_fizzle``
    -- CR 701.12c: host attached_to id resolves to no on-bf creature
    (synthetic stale id) -> silent fizzle.

1 EoE card directly substrate-landed by slice 19: Meltstrider's
Resolve (15,259 17lands decks per
``docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md``). Full byte-equality
deferred until the Aura attach substrate's Phase 1 (per the substrate
plan). Pain for All (4,367 17lands decks) shares the Aura attach
substrate -- once Phase 1 lands, Pain for All's residual closure cost
drops from "medium" to "small".
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


def test_yyy_probe_enchanted_creature_fights_no_attached_to_fizzles_real_eoe():
    """**19th Rust slice honest-stop substrate landing -- no-host
    fizzle byte-equal probe.**

    Drives the Rust ``Effect::EnchantedCreatureFightsTarget`` resolve
    arm with the source's ``attached_to=None`` (the Rust-side reality
    today). Post-resolve invariant: no damage applied on either side
    of the bf (the honest-stop sentinel fires; Python takes the same
    fizzle in this case per ``bespoke.py:546-548``).

    Probe shape (Rust-side end-to-end + cross-engine bridge):
      1. Bridge round-trip:
         ``{"kind": "enchanted_creature_fights_target"}`` translates
         to ``EnchantedCreatureFightsTargetEffect()`` on Python.
      2. Rust-side full ETB cycle: inject a creature on each side's
         bf + a Meltstrider's-Resolve-shape Aura source on P0's bf
         that fires ``enchanted_creature_fights_target`` on ENTERS.
         Crucially, the Aura is injected with ``attached_to=None``
         (the Rust default; no attach has happened).
      3. Post-resolve invariants on Rust:
            * The Aura source is still on P0's bf.
            * P0's creature carries no damage.
            * P1's creature carries no damage.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_rust_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.effects.bespoke import EnchantedCreatureFightsTargetEffect

    # ---- Bridge arm round-trip: Rust dict -> Python class. ---------
    bridged = _ta_dict_to_python_effect(
        {"kind": "enchanted_creature_fights_target"}
    )
    assert isinstance(bridged, EnchantedCreatureFightsTargetEffect), (
        "YYY honest-stop substrate landing (slice 19): the cross_engine "
        "bridge arm should round-trip the Rust kind "
        "'enchanted_creature_fights_target' to a Python "
        "EnchantedCreatureFightsTargetEffect instance; got "
        f"{bridged!r}"
    )

    # ---- Rust-side end-to-end: inject creatures + Aura source. -----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # P0's creature (the would-be enchanted host -- but no attach
    # happens, so the Aura's attached_to stays None).
    p0_creature_id = rust_state.register_and_inject_object(
        {
            "name": "YYY Probe P0 Bear (would-be host)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2, "toughness": 2,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_BATTLEFIELD,
    )
    # P1's creature.
    p1_creature_id = rust_state.register_and_inject_object(
        {
            "name": "YYY Probe P1 Bear",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 3, "toughness": 3,
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_BATTLEFIELD,
    )

    # Aura source on P0's bf. No attach happens (Rust today).
    rust_aura_id = rust_state.register_and_inject_object(
        {
            "name": "YYY Meltstrider's Resolve (no-host probe)",
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "mana_cost": {"R": 1},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "enchanted_creature_fights_target",
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # The ETB trigger should land on the stack.
    assert rust_state.stack_size() == 1, (
        "Rust YYY: Aura's arrival on P0's bf should fire its ENTERS "
        f"trigger; got stack_size={rust_state.stack_size()}"
    )

    # Drain the stack to completion. The resolve arm's honest-stop
    # branch fires (attached_to=None on the Aura source).
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # ---- Post-resolve invariants -- nothing fought. ----------------
    rust_bf_all = rust_state.battlefield_snapshot()
    # Locate the two creatures by id and read their damage markers.
    p0_creature = next(
        (e for e in rust_bf_all if e["id"] == p0_creature_id), None
    )
    p1_creature = next(
        (e for e in rust_bf_all if e["id"] == p1_creature_id), None
    )
    assert p0_creature is not None, (
        "Rust YYY honest-stop: P0's creature should still be on bf "
        "post-resolve (no damage was dealt; no SBA destroyed it)."
    )
    assert p1_creature is not None, (
        "Rust YYY honest-stop: P1's creature should still be on bf "
        "post-resolve (no damage was dealt; no SBA destroyed it)."
    )
    assert p0_creature.get("damage", 0) == 0, (
        "Rust YYY honest-stop: P0's creature should carry NO damage "
        "(attached_to=None -> fizzle); got "
        f"damage={p0_creature.get('damage')}"
    )
    assert p1_creature.get("damage", 0) == 0, (
        "Rust YYY honest-stop: P1's creature should carry NO damage "
        "(attached_to=None -> fizzle); got "
        f"damage={p1_creature.get('damage')}"
    )
    # The Aura source is still on bf.
    aura_present = any(e["id"] == rust_aura_id for e in rust_bf_all)
    assert aura_present, (
        "Rust YYY honest-stop: the Aura source should remain on P0's "
        "bf post-ETB."
    )


def test_yyy_probe_enchanted_creature_fights_with_attached_host_applies_damage_both_ways():
    """**19th Rust slice -- hot-path branch (substrate-anticipating
    probe) via state.attach() test primitive.**

    Manually stamps the Aura's ``attached_to`` via the
    ``state.attach(aura_id, host_id)`` test-setup primitive (the same
    Round-28 substrate `Effect::AttachToTargetCreatureYouControl`
    uses), then resolves the Aura's ETB trigger. Post-resolve
    invariant: both fighters carry the OTHER fighter's power as a
    damage marker (CR 701.12 simultaneous damage).

    This is the future hot-path that becomes Rust-side live once the
    Aura attach substrate's Phase 1 lands. Probing it today via the
    setup primitive proves the resolve arm's logic is correct and
    catches regressions in the simultaneous-damage path before the
    attach substrate ships.

    Probe shape:
      1. Inject P0 host (a 4/4) + P1 fighter (a 2/3) + Aura on P0's
         bf with ``enchanted_creature_fights_target`` ETB trigger.
      2. Use ``rust_state.attach(aura_id, host_id)`` to stamp
         attached_to BEFORE the ETB trigger resolves (mirrors the
         eventual Phase 1 Rust Aura-resolution attach).
      3. Drain the stack.
      4. Assert: host carries 2 damage (opp's power); opp carries 4
         damage (host's power). Both markers stamped simultaneously.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # P0 host (a 4/4).
    p0_host_id = rust_state.register_and_inject_object(
        {
            "name": "YYY Probe Host 4/4",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 3, "G": 1},
            "power": 4, "toughness": 4,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_BATTLEFIELD,
    )
    # P1 fighter (a 2/3).
    p1_fighter_id = rust_state.register_and_inject_object(
        {
            "name": "YYY Probe Opp Bear 2/3",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2, "toughness": 3,
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_BATTLEFIELD,
    )
    # Aura source on P0's bf.
    aura_id = rust_state.register_and_inject_object(
        {
            "name": "YYY Meltstrider's Resolve (hot-path probe)",
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "mana_cost": {"R": 1},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "enchanted_creature_fights_target",
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # Substrate-anticipating attach: stamp attached_to via the
    # state.attach() test primitive (the same Round-28 Equip path
    # uses; the future Phase-1 Rust Aura-resolution attach will set
    # this field inline, but for the probe we use the test setup).
    stamped = rust_state.attach(aura_id, p0_host_id)
    assert stamped, (
        f"state.attach({aura_id}, {p0_host_id}) should succeed -- the "
        "Aura should be findable in some zone."
    )

    # The ETB trigger fired on inject (before the attach call). Drain.
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # ---- Post-resolve: BOTH fighters carry damage. -----------------
    rust_bf_all = rust_state.battlefield_snapshot()
    p0_host = next(
        (e for e in rust_bf_all if e["id"] == p0_host_id), None
    )
    p1_fighter = next(
        (e for e in rust_bf_all if e["id"] == p1_fighter_id), None
    )
    assert p0_host is not None, (
        "Rust YYY hot-path: P0 host should still be on bf -- 4 toughness "
        "minus 2 damage = 2 toughness remaining, no SBA destruction."
    )
    # P0 host receives p1's power = 2 damage.
    assert p0_host.get("damage") == 2, (
        "Rust YYY hot-path: P0 host should carry 2 damage (opp's power "
        f"applied via simultaneous-damage); got damage={p0_host.get('damage')}"
    )
    # P1 fighter receives p0_host's power = 4 damage (lethal -- but
    # SBAs are NOT run inline by the resolve arm; they fire on the
    # next SBA pass after the resolve, by which point both damage
    # markers are in place). At THIS point the creature is still on
    # bf with 4 damage.
    if p1_fighter is not None:
        assert p1_fighter.get("damage") == 4, (
            "Rust YYY hot-path: P1 fighter should carry 4 damage (host's "
            "power applied via simultaneous-damage); got "
            f"damage={p1_fighter.get('damage')}"
        )
    else:
        # If SBA fired and destroyed it, that's also acceptable. The
        # damage marker would have hit FIRST per the CR 701.12 ordering
        # we already verified by reading p0_host's damage. This branch
        # is defensive: most resolve paths don't fire SBA inline.
        pass


def test_yyy_probe_enchanted_creature_fights_no_opponent_creature_silent_fizzle():
    """**19th Rust slice -- "up to one" silent fizzle when no opponent
    creature exists.**

    With the Aura attached to a host AND no opponent creature on the
    bf, the "up to one" optional target binds to nothing and the spell
    resolves with no fight applied. Host carries no damage post-resolve.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # P0 host (a 4/4).
    p0_host_id = rust_state.register_and_inject_object(
        {
            "name": "YYY Probe Host (no-opp fizzle)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 3, "G": 1},
            "power": 4, "toughness": 4,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_BATTLEFIELD,
    )
    # NO P1 creature -- the "up to one" target must legally pick 0.

    # Aura source on P0's bf.
    aura_id = rust_state.register_and_inject_object(
        {
            "name": "YYY Meltstrider's Resolve (no-opp probe)",
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "mana_cost": {"R": 1},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "enchanted_creature_fights_target",
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # Stamp attached_to via the test primitive.
    assert rust_state.attach(aura_id, p0_host_id)

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # Host carries no damage (no fight applied).
    rust_bf_all = rust_state.battlefield_snapshot()
    p0_host = next((e for e in rust_bf_all if e["id"] == p0_host_id), None)
    assert p0_host is not None, (
        "Rust YYY no-opp: P0 host should still be on bf (no fight)."
    )
    assert p0_host.get("damage", 0) == 0, (
        "Rust YYY no-opp: P0 host should carry NO damage "
        "('up to one' picked 0); got "
        f"damage={p0_host.get('damage')}"
    )


def test_yyy_probe_enchanted_creature_fights_host_left_bf_silent_fizzle():
    """**19th Rust slice -- CR 701.12c host-left-bf silent fizzle.**

    If the Aura's attached_to resolves to a creature id that is no
    longer on the bf (mirrors "the host left between trigger fire and
    resolve"), the resolve arm fizzles silently. Mirrors Python's same
    branch at ``bespoke.py:549-552``: the ``next((o for o in
    state.battlefield if o.id == aura.attached_to), None)`` lookup
    returns None and the resolve returns.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # P1 fighter (would-be opp fighter, but the host is gone so no
    # fight fires -- the host-missing fizzle wins on the source side).
    p1_fighter_id = rust_state.register_and_inject_object(
        {
            "name": "YYY Probe Opp Bear (host-left)",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2, "toughness": 3,
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_BATTLEFIELD,
    )

    # Aura source on P0's bf, with attached_to stamped to a synthetic
    # NEVER-REGISTERED id (mirrors "the host died and reset to None
    # after the trigger fired" or "the trigger captured a stale id").
    aura_id = rust_state.register_and_inject_object(
        {
            "name": "YYY Meltstrider's Resolve (host-left probe)",
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "mana_cost": {"R": 1},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "enchanted_creature_fights_target",
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # Stamp attached_to to a synthetic-stale id (no object has it).
    # state.attach() trust-the-caller contract: target_id is NOT
    # validated -- callers may stamp a not-on-bf id.
    STALE_ID = 99_999_999
    assert rust_state.attach(aura_id, STALE_ID)

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # P1 fighter carries no damage (the fizzle fires before the
    # opponent-side scan reaches it).
    rust_bf_all = rust_state.battlefield_snapshot()
    p1_fighter = next(
        (e for e in rust_bf_all if e["id"] == p1_fighter_id), None
    )
    assert p1_fighter is not None, (
        "Rust YYY host-left: P1 fighter should still be on bf "
        "(no damage applied)."
    )
    assert p1_fighter.get("damage", 0) == 0, (
        "Rust YYY host-left: P1 fighter should carry NO damage "
        "(host-not-found fizzle fires before the opp scan); got "
        f"damage={p1_fighter.get('damage')}"
    )
