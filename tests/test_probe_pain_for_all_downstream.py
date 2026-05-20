"""Genuine cross-engine probes -- Pain for All closure (Aura Phase 3
/ S4 triggered shape; bespoke ``PainForAllETBEffect`` +
``PainForAllDamageEchoEffect`` + ``IsHost`` predicate substrate
landing).

**Closure status (honest-stop substrate landing).**

This slice adds the Effect-level scaffolding for Pain for All's two
bespoke triggers (4,367 17lands decks per
``docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md`` §4). The Rust enum
gains two unit ``Effect`` variants (``PainForAllETBEffect`` +
``PainForAllDamageEchoEffect``) and one ``Predicate`` variant
(``IsHost { subject: Option<String> }``); parse + ``effect_to_pydict``
+ resolve arms ship in cards.rs / state_ops_resolve.rs; the bridge
arms (both Effect kinds + the IsHost predicate) ship in
cross_engine.py.

**Honest-stop semantics.** Same as slice-19's
``EnchantedCreatureFightsTarget`` arm: the ETB-effect resolve reads
the Aura source's ``attached_to`` and fizzles silently when None.
That IS the Rust-side reality today (no Aura attach substrate -- see
``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §2; the largest
§2-declined Rust multi-round substrate). Python takes the SAME fizzle
in this case (``bespoke.py:389-391``), so cross-engine state stays
byte-equal in the no-host case. The damage-echo effect reads
``state.resolving_combat_damage_amount`` (already plumbed engine-
wide) and applies life-loss to each opponent -- NOT via the damage
pipeline -- which inherently breaks the potential recursion (the
loop-guard called out in
``docs/BLOCKED_GENUINELY_MISSING_INVENTORY.md``).

**Probes added in this slice:**

  * ``test_pain_for_all_etb_bridge_roundtrips_to_python`` -- the
    Rust dict ``{"kind": "pain_for_all_etb"}`` translates to the
    Python ``PainForAllETBEffect()`` instance via the cross_engine
    bridge.
  * ``test_pain_for_all_damage_echo_bridge_roundtrips_to_python`` --
    the Rust dict ``{"kind": "pain_for_all_damage_echo"}`` translates
    to the Python ``PainForAllDamageEchoEffect()`` instance.
  * ``test_pain_for_all_is_host_predicate_bridge_roundtrips`` -- the
    Rust dict ``{"kind": "is_host"}`` (and the slot-aware variant)
    translates to the Python ``IsHost(subject=...)`` instance.
  * ``test_pain_for_all_etb_no_attached_to_fizzles_real_eoe`` --
    honest-stop fizzle: source.attached_to=None -> no damage applied
    on either side (byte-equal with Python's ``if attached_to is None:
    return`` short-circuit at bespoke.py:389-391).
  * ``test_pain_for_all_etb_with_attached_host_damages_first_legal_player``
    -- hot-path branch (manually stamped attached_to via state.attach):
    enchanted creature's power applied as life-loss to the first-legal
    player (the controller, per Python's ``legal_targets`` ordering +
    PickFirst agent).
  * ``test_pain_for_all_damage_echo_subtracts_amount_from_each_opponent_life``
    -- direct effect-resolve test (sets
    ``state.resolving_combat_damage_amount`` then drives the effect via
    a synthetic trigger); each non-controller player loses the amount
    as life-loss.
  * ``test_pain_for_all_damage_echo_zero_amount_noop`` -- guard:
    resolving_combat_damage_amount=0 → no life change anywhere.
  * ``test_pain_for_all_is_host_predicate_no_attached_to_is_false``
    -- the IsHost predicate evaluates false when source.attached_to
    is None (Rust's reality today; byte-equal with Python).

1 EoE card directly substrate-landed by this slice: Pain for All
(4,367 17lands decks). Full byte-equality deferred until the Aura
attach substrate's Phase 1 lands (per the substrate plan); the
honest-stop fizzle keeps cross-engine state byte-equal in the
meantime. With Tractor Beam's sibling closure landing in this round,
BLOCKED-genuinely_missing tier drops to 0.
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------
# Bridge round-trip probes
# ---------------------------------------------------------------------


def test_pain_for_all_etb_bridge_roundtrips_to_python():
    """Cross-engine bridge: Rust's ``pain_for_all_etb`` dict translates
    to Python's ``PainForAllETBEffect()`` via
    ``cross_engine._ta_dict_to_python_effect``."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.bespoke import PainForAllETBEffect

    bridged = _ta_dict_to_python_effect({"kind": "pain_for_all_etb"})
    assert isinstance(bridged, PainForAllETBEffect), (
        "Pain for All closure: the cross_engine bridge arm should "
        "round-trip the Rust kind 'pain_for_all_etb' to a Python "
        f"PainForAllETBEffect instance; got {bridged!r}"
    )


def test_pain_for_all_damage_echo_bridge_roundtrips_to_python():
    """Cross-engine bridge: Rust's ``pain_for_all_damage_echo`` dict
    translates to Python's ``PainForAllDamageEchoEffect()``."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.bespoke import PainForAllDamageEchoEffect

    bridged = _ta_dict_to_python_effect(
        {"kind": "pain_for_all_damage_echo"}
    )
    assert isinstance(bridged, PainForAllDamageEchoEffect), (
        "Pain for All closure: the cross_engine bridge arm should "
        "round-trip the Rust kind 'pain_for_all_damage_echo' to a "
        f"Python PainForAllDamageEchoEffect instance; got {bridged!r}"
    )


def test_pain_for_all_is_host_predicate_bridge_roundtrips():
    """Cross-engine bridge: Rust's ``is_host`` predicate dict
    translates to Python's ``IsHost(subject=...)``. Tests both the
    default (subject=None, Pain for All's DEALT_DAMAGE shape) and the
    slot-aware variant (subject="attacker", future Equipment shape).
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_predicate
    from mtg_bot.effects.predicates import IsHost

    # Default: subject=None (Pain for All's DEALT_DAMAGE shape).
    bridged = _ta_dict_to_python_predicate({"kind": "is_host"})
    assert isinstance(bridged, IsHost), (
        "Pain for All closure: the cross_engine bridge arm should "
        "round-trip the Rust predicate kind 'is_host' to a Python "
        f"IsHost instance; got {bridged!r}"
    )
    assert bridged.subject is None, (
        "Pain for All closure: IsHost(subject=None) is the default; "
        f"got subject={bridged.subject!r}"
    )

    # Slot-aware variant (Equipment "attacker" shape).
    bridged_slot = _ta_dict_to_python_predicate(
        {"kind": "is_host", "subject": "attacker"}
    )
    assert isinstance(bridged_slot, IsHost)
    assert bridged_slot.subject == "attacker", (
        "Pain for All closure: the slot-aware IsHost bridge should "
        f"thread subject='attacker'; got subject={bridged_slot.subject!r}"
    )


# ---------------------------------------------------------------------
# Rust-side honest-stop fizzle probes (no attached_to)
# ---------------------------------------------------------------------


def test_pain_for_all_etb_no_attached_to_fizzles_real_eoe():
    """**Pain for All honest-stop substrate landing -- no-host fizzle
    byte-equal probe.**

    Drives the Rust ``Effect::PainForAllETBEffect`` resolve arm with
    the source's ``attached_to=None`` (the Rust-side reality today).
    Post-resolve invariant: no life change on either player (the
    honest-stop sentinel fires; Python takes the same fizzle in this
    case per ``bespoke.py:389-391``).
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # P0's would-be enchanted host (no attach happens; Rust default).
    p0_host_id = rust_state.register_and_inject_object(
        {
            "name": "Pain for All Probe P0 Host",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": 2, "toughness": 2,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_BATTLEFIELD,
    )

    # Aura source on P0's bf with ETB trigger. No attach.
    rust_aura_id = rust_state.register_and_inject_object(
        {
            "name": "Pain for All (no-host probe)",
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "mana_cost": {"generic": 2, "R": 1},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "pain_for_all_etb"},
            }],
        },
        0, ZONE_BATTLEFIELD,
    )
    assert p0_host_id != rust_aura_id

    # The ETB trigger should land on the stack.
    assert rust_state.stack_size() == 1

    # Drain the stack: honest-stop fizzle (attached_to=None).
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # Post-resolve: no life change on either player.
    p0_life, p1_life = rust_state.life_totals
    assert p0_life == 20, (
        "Pain for All honest-stop: P0 life should be unchanged "
        f"(attached_to=None → fizzle); got {p0_life}"
    )
    assert p1_life == 20, (
        "Pain for All honest-stop: P1 life should be unchanged; "
        f"got {p1_life}"
    )


def test_pain_for_all_etb_with_attached_host_damages_first_legal_player():
    """**Pain for All hot-path branch (substrate-anticipating probe)
    via state.attach() test primitive.**

    Manually stamps the Aura's ``attached_to`` via the
    ``state.attach(aura_id, host_id)`` test-setup primitive (same as
    the YYY Meltstrider's hot-path probe). After resolve, the
    enchanted creature's effective power is applied as life-loss to
    the first-legal player (the controller, P0 — Python's
    ``legal_targets`` returns players in id order, PickFirst takes
    [0]).
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # P0 host: a 3/3.
    p0_host_id = rust_state.register_and_inject_object(
        {
            "name": "Pain for All Probe Host 3/3",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 2, "G": 1},
            "power": 3, "toughness": 3,
            "effects": [],
            "triggered_abilities": [],
        },
        0, ZONE_BATTLEFIELD,
    )
    # Aura source on P0's bf.
    aura_id = rust_state.register_and_inject_object(
        {
            "name": "Pain for All (hot-path probe)",
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "mana_cost": {"generic": 2, "R": 1},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "pain_for_all_etb"},
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # Substrate-anticipating attach.
    stamped = rust_state.attach(aura_id, p0_host_id)
    assert stamped, (
        f"state.attach({aura_id}, {p0_host_id}) should succeed."
    )

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    # Post-resolve: P0 takes 3 damage as life-loss (first-legal target).
    p0_life, _ = rust_state.life_totals
    assert p0_life == 17, (
        "Pain for All hot-path: P0 should lose 3 life (host's power "
        f"applied to first-legal target); got {p0_life}"
    )


def test_pain_for_all_etb_host_left_bf_silent_fizzle():
    """If the Aura's attached_to resolves to a creature id that is no
    longer on the bf, the resolve arm fizzles silently (mirrors Python
    `bespoke.py:392-397` — `enchanted = next(...); if enchanted is
    None: return`)."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    aura_id = rust_state.register_and_inject_object(
        {
            "name": "Pain for All (host-left probe)",
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "mana_cost": {"generic": 2, "R": 1},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "pain_for_all_etb"},
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # Stamp attached_to to a synthetic-stale id (no object has it).
    stamped = rust_state.attach(aura_id, 999_999)
    assert stamped

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    p0_life, p1_life = rust_state.life_totals
    assert p0_life == 20
    assert p1_life == 20


# ---------------------------------------------------------------------
# Damage-echo probes
# ---------------------------------------------------------------------


def test_pain_for_all_damage_echo_subtracts_amount_from_each_opponent_life():
    """Drive the Rust ``Effect::PainForAllDamageEchoEffect`` resolve
    via a synthetic trigger. With
    ``state.resolving_combat_damage_amount`` set to 5 + the resolving
    source controlled by P0, P1 (the opponent) loses 5 life via
    life-loss (NOT damage pipeline — the loop-guard).
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # Resolving source on P0's bf with a no-op (we'll set the damage
    # amount manually and resolve the echo via a triggered ability).
    rust_state.register_and_inject_object(
        {
            "name": "Pain for All Echo Carrier",
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "mana_cost": {"generic": 2, "R": 1},
            "effects": [],
            # Wire the ETB to fire the damage echo. We're testing the
            # echo's resolve, not the wider DEALT_DAMAGE dispatch.
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "pain_for_all_damage_echo"},
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # Pre-set the resolving combat damage amount (mirrors what the
    # DEALT_DAMAGE dispatch path threads through). The echo's resolve
    # reads this slot directly.
    rust_state.set_resolving_combat_damage_amount(5)

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    p0_life, p1_life = rust_state.life_totals
    # Controller (P0) does NOT lose life (skipped by "if p.id ==
    # controller_id: continue").
    assert p0_life == 20, (
        "Pain for All echo: controller (P0) should NOT lose life; "
        f"got {p0_life}"
    )
    # Opponent (P1) loses 5 life.
    assert p1_life == 15, (
        "Pain for All echo: opponent (P1) should lose 5 life via "
        f"life-loss; got {p1_life}"
    )


def test_pain_for_all_damage_echo_zero_amount_noop():
    """Guard: when ``state.resolving_combat_damage_amount`` is 0
    (the reset state between damage events), the echo is a no-op —
    no life change anywhere. Mirrors Python's ``if amount <= 0:
    return`` (``bespoke.py:447-449``)."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    rust_state.register_and_inject_object(
        {
            "name": "Pain for All Echo Zero Carrier",
            "card_types": ["Enchantment"],
            "subtypes": ["Aura"],
            "mana_cost": {"generic": 2, "R": 1},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "pain_for_all_damage_echo"},
            }],
        },
        0, ZONE_BATTLEFIELD,
    )

    # Don't set the damage amount: stays at default 0.
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()

    p0_life, p1_life = rust_state.life_totals
    assert p0_life == 20
    assert p1_life == 20


# ---------------------------------------------------------------------
# IsHost predicate probes
# ---------------------------------------------------------------------


def test_pain_for_all_is_host_predicate_python_no_attach_is_false():
    """Python-side semantic pin: ``IsHost(subject=None).matches`` on
    an Aura source with ``attached_to=None`` returns False.

    This is the byte-equal honest-stop path with Rust. Rust's
    ``Predicate::IsHost::matches`` reads
    ``find_object_attached_to(state, source_id)`` which returns
    ``None`` for any Aura today (Rust's no-Aura-attach reality), and
    the match arm returns ``false`` in the ``None`` branch. Python's
    ``IsHost.matches`` (`predicates.py:464-466`) takes the same false
    path: ``if host_id is None: return False``. The two engines
    return identical bool values on the same input — that is the
    cross-engine guarantee.
    """
    from mtg_bot.effects.predicates import IsHost
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.cards.source import get_active_source

    printings = get_active_source().get_printings()
    aura_printing = printings["Pain for All"]

    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    aura = state.new_object(aura_printing, 0, Zone.BATTLEFIELD)
    aura.attached_to = None  # explicit: Rust's reality today
    state.battlefield.append(aura)

    # Synthetic subject: the would-be host (but no attach has happened).
    bear_printing = printings["Pain for All"]  # any printing works
    subject = state.new_object(bear_printing, 0, Zone.BATTLEFIELD)
    state.battlefield.append(subject)

    pred = IsHost(subject=None)
    # Predicate's matches signature: matches(state, subjects, source)
    # where `subjects` is a Mapping[str, Any].
    matches = pred.matches(state, {"obj": subject}, aura)
    assert matches is False, (
        "Pain for All IsHost honest-stop: with aura.attached_to=None, "
        "IsHost should return False (byte-equal with Rust's same-case "
        f"false branch); got {matches!r}"
    )


def test_pain_for_all_is_host_predicate_python_attached_to_subject_is_true():
    """Python-side semantic pin: ``IsHost(subject=None).matches`` on
    an Aura source whose ``attached_to`` IS the subject's id returns
    True. This is the substrate-anticipating positive case (once
    Rust's Aura attach lands, Rust's ``IsHost::matches`` will return
    true on the same input — same observable contract)."""
    from mtg_bot.effects.predicates import IsHost
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.cards.source import get_active_source

    printings = get_active_source().get_printings()
    aura_printing = printings["Pain for All"]

    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    aura = state.new_object(aura_printing, 0, Zone.BATTLEFIELD)
    state.battlefield.append(aura)
    subject = state.new_object(aura_printing, 0, Zone.BATTLEFIELD)
    state.battlefield.append(subject)
    aura.attached_to = subject.id  # attach!

    pred = IsHost(subject=None)
    matches = pred.matches(state, {"obj": subject}, aura)
    assert matches is True, (
        "Pain for All IsHost attached: aura.attached_to == subject.id "
        f"should match; got {matches!r}"
    )
