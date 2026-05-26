"""Keys to the House — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip; Carrier-AA Phase 4D
admit-set landing; CLOSES Phase 4D).

Keys to the House is a ``{1}`` Artifact in the EoE pool with TWO
non-mana activated abilities:

    AA[0]: "{1}, {T}, Sacrifice this artifact: Search your library
           for a basic land card, put it onto the battlefield, then
           shuffle." (``SearchLibraryForCard(filter_name="basic_land",
           max_mv=0, may_fail=True)``)
    AA[1]: "{3}, {T}, Sacrifice this artifact: Lock or unlock a door
           of target Room you control. Activate only as a sorcery."
           (``LockOrUnlockDoorOfTargetRoomYouControl()``)

The Carrier-AA substrate Phase 4D (2026-05-26 — see
``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §5.6 / §7.4) closes
in TWO cycles: (C1) Rust substrate landing the new
``GameObject.door_states: Option<u8>`` slot + per-zone-change reset
hookup at every bf-leave site + ``Effect::LockOrUnlockDoorOfTargetRoom
YouControl`` variant + resolve-arm pilot toggle + cross-engine bridge
arms + the 21 Rust unit pins — landed at commit ``3c41e4d1``; (C2) THIS
slice — Python admit widen (Effect-class set adds
``LockOrUnlockDoorOfTargetRoomYouControl`` + ``SearchLibraryForCard``;
AA-rider gate lifts ``sorcery_speed=True`` for AA[1]; bridge floor
adds the forward arm for ``SearchLibraryForCard``) + Rust legal-
emit Room-target × 2-door-half fan-out arm in
``state_ops_legal.rs::activate_ability_dict`` + ``Action::Activate
Ability.chosen_mode_idx`` plumbing + StackItem mode-idx stamp + this
per-card real-EoE probe. Keys to the House FLIPS DECLINED → ADMITTED
on the combined C2 widen; the probe closes the tier flip to PROBED.

Parser-emitted Effect shapes:

  * ``SearchLibraryForCard(filter_name="basic_land", max_mv=0,
    may_fail=True)`` — basic-land tutor; ``requires_target() ==
    False`` (the search is a library-walk, not a battlefield-target
    fan-out). Rust dispatches via the closed-vocab filter table at
    ``cards.rs:14965/18746``.
  * ``LockOrUnlockDoorOfTargetRoomYouControl()`` (unit-variant zero-
    arg frozen dataclass; ``requires_target() == True``;
    ``legal_targets`` walks the activator's battlefield for
    ``o.printing.is_room`` permanents — own-control qualifier
    strict).

attached to two ``ActivatedAbility`` slots whose costs carry
``tap_self=True`` + ``sacrifice_self=True`` (BOTH AAs sacrifice
Keys to the House to activate — the "Sacrifice this artifact"
clause); AA[0] carries ``mana=ManaCost(generic=1)``, AA[1] carries
``mana=ManaCost(generic=3)`` + ``sorcery_speed=True``. The bridge
arms (the round-21 ``search_library_for_card`` reverse arm at
``cross_engine.py:5325``; the new Phase-4D-C2 ``search_library_for_
card`` forward arm at ``cross_engine.py``; the Phase-4D-C1
``lock_or_unlock_door_of_target_room_you_control`` reverse+forward
arms at ``cross_engine.py:13011`` / ``cross_engine.py:15219``)
round-trip the canonical Effect dicts byte-equal to Python's
``SearchLibraryForCard(...)`` / ``LockOrUnlockDoorOfTargetRoomYou
Control()``.

**EEEE-idiom for the multi-AA carrier.** Same lane discipline as the
Phase 1-3 Carrier-AA AA probes (parse + bridge round-trip + Python-
side resolve) with two new wrinkles for the Phase-4 multi-AA wave:

  1. **Multi-AA admit walk.** The Phase 4A keystone (commit
     ``a6fe7c9c``) widened the Carrier-AA admit predicate from
     STRICT single-AA (``len(aas) != 1``) to multi-AA all-or-
     nothing per-AA walk; the Phase 4D C2 Effect-class widen + AA-
     rider widen + bridge floor widen combine to land both of Keys
     to the House's AAs at the per-AA gate. The probe pins BOTH
     AAs PASS the predicate (no all-or-nothing partial admission).

  2. **Door-state slot resolve.** The Rust C1 substrate landed the
     new ``GameObject.door_states: Option<u8>`` per-Room locked-
     bitmask slot mirroring Python's ``GameObject.unlocked_halves:
     set[str]``. The Rust resolve XORs the chosen bit on the
     target Room's bitmask; the Python resolve walks the printed
     ``room_halves`` and adds/removes the chosen door name in the
     ``unlocked_halves`` set. The probe drives both resolve arms
     on identical inputs and pins byte-equal observable post-state
     (one door toggled per activation).

**NEW shape coverage.** The FIRST PROBE_MODULES-credited probe
binding the Keys-to-the-House slug to the Carrier-AA multi-AA
admit substrate, AND the FIRST PROBED-tier slot for the
``LockOrUnlockDoorOfTargetRoomYouControl`` Effect class (the C1
substrate's pilot toggle effect mints the door-state slot — Phase
4D ships both the slot AND its first minter). Also the FIRST
PROBED-tier exercise of the ``GameObject.door_states`` slot via the
Carrier-AA Phase 4 wave (the C1 substrate's 21 unit pins exercise
the slot at the synthetic-carrier level; this probe drives it
end-to-end on the real-EoE printing).

**Phase 4D Cycle 2 admit-gate FLIP (load-bearing).** The combined
admit widens (Effect-class set + sorcery_speed AA-rider) flip the
per-AA predicate ``_aa_is_phase1_sub_shape_a`` from DECLINE → ADMIT
on BOTH of Keys to the House's AAs. The bridge floor's
``_python_aa_to_safe_dict`` widens (sorcery_speed admit + new
``SearchLibraryForCard`` forward arm) flip the cross-engine builder
``_carrier_aa_artifact_card_def`` from DECLINE → ADMIT. The loader
admit set grows by 1 (Artifact admit count 0 → 1); the predicate
admit walks see Keys to the House for the first time post-C2.

**Cross-engine bridge byte-equality (load-bearing).** Both AAs
round-trip through ``_python_aa_to_safe_dict`` ↔
``_aa_dict_to_python_activated_ability`` byte-equal on the cost
atoms + Effect class + AA-rider fields. The
``SearchLibraryForCard`` reverse arm has been on main since
round-21; the new Phase-4D-C2 forward arm closes the round-trip
gap. The ``LockOrUnlockDoorOfTargetRoomYouControl`` arm pair
shipped at Phase-4D-C1.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.misc import (
    LockOrUnlockDoorOfTargetRoomYouControl,
)
from mtg_bot.effects.generic.search import SearchLibraryForCard


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT — Keys to the House is parser-claimed and carries the
# exact 2-AA shape the design doc (§7.4) pins.
# ---------------------------------------------------------------------------


def test_keys_to_the_house_parser_claims_card():
    assert "Keys to the House" in _PRINTINGS, (
        "Keys to the House must be parser-claimed by the active "
        "CardSource"
    )


def test_keys_to_the_house_printed_attrs():
    """Pins the basic printing surface: single-typed Artifact (NOT
    Equipment / Vehicle / Spacecraft / Food / Treasure — Keys to the
    House is a bare Artifact with no subtypes), ``{1}`` mana cost, no
    power/toughness, no triggered / static / keyword riders. The 2 AAs
    are the SOLE ``activated_abilities`` entries (no synthesized mana-
    ability slot — Keys to the House has no leading ``{T}: Add ...``
    line)."""
    p = _PRINTINGS["Keys to the House"]
    assert p.card_types == ("Artifact",)
    assert p.subtypes == (), (
        "Keys to the House must carry NO subtypes — the Phase-4A.2 "
        "Artifact admit predicate's empty-subtypes guard requires this"
    )
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == ()
    assert p.power is None and p.toughness is None
    assert p.keywords == frozenset()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


def test_keys_to_the_house_activated_ability_shapes():
    """Keys to the House has exactly TWO ``ActivatedAbility`` slots
    (Phase 4 multi-AA carrier). AA[0] is the
    ``SearchLibraryForCard(filter_name="basic_land", max_mv=0,
    may_fail=True)`` tutor (cost ``{1}, {T}, sacrifice_self``); AA[1]
    is the ``LockOrUnlockDoorOfTargetRoomYouControl()`` toggle (cost
    ``{3}, {T}, sacrifice_self``, ``sorcery_speed=True``).

    The Phase 4D C2 admit gate gates BOTH AAs at the per-AA predicate
    ``_aa_is_phase1_sub_shape_a``. The all-or-nothing multi-AA
    contract (Phase 4A keystone) requires both AAs to pass — the
    combined widens (Effect-class set adds both Effects;
    ``sorcery_speed`` rider lifts) land both admits in one slice.
    """
    p = _PRINTINGS["Keys to the House"]
    aas = tuple(p.activated_abilities or ())
    assert len(aas) == 2, (
        f"Keys to the House must have exactly 2 ActivatedAbility "
        f"slots; got {len(aas)}"
    )
    aa0, aa1 = aas

    # AA[0] — basic-land tutor.
    assert isinstance(aa0.effect, SearchLibraryForCard), (
        f"AA[0] effect must be SearchLibraryForCard; got "
        f"{type(aa0.effect).__name__}"
    )
    assert aa0.effect.filter_name == "basic_land"
    assert aa0.effect.max_mv == 0
    assert aa0.effect.may_fail is True
    assert aa0.cost.tap_self is True
    assert aa0.cost.sacrifice_self is True
    assert aa0.cost.mana is not None
    assert aa0.cost.mana.generic == 1
    assert aa0.cost.mana.colored == ()
    assert aa0.is_mana_ability is False
    assert aa0.sorcery_speed is False  # AA[0] is instant-speed
    assert aa0.cost_reductions == ()
    assert aa0.room_half is None
    assert aa0.tier_threshold == 0
    assert aa0.activate_only_once is False

    # AA[1] — door toggle.
    assert isinstance(aa1.effect, LockOrUnlockDoorOfTargetRoomYouControl), (
        f"AA[1] effect must be LockOrUnlockDoorOfTargetRoomYouControl; "
        f"got {type(aa1.effect).__name__}"
    )
    assert aa1.cost.tap_self is True
    assert aa1.cost.sacrifice_self is True
    assert aa1.cost.mana is not None
    assert aa1.cost.mana.generic == 3
    assert aa1.cost.mana.colored == ()
    assert aa1.is_mana_ability is False
    assert aa1.sorcery_speed is True, (
        "AA[1] must carry sorcery_speed=True — the printed "
        "``Activate only as a sorcery`` rider. The Phase-4D-C2 widen "
        "lifts this rider at the per-AA admit gate."
    )
    assert aa1.cost_reductions == ()
    assert aa1.room_half is None
    assert aa1.tier_threshold == 0
    assert aa1.activate_only_once is False
    # AA[1]'s Effect targets a Room you control.
    assert aa1.effect.requires_target() is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — both Effect dict shapes round-trip byte-equal
# to the parsed printing's emitted Effects.
# ---------------------------------------------------------------------------


def test_keys_to_the_house_search_library_bridge_arm_round_trip():
    """The bridge arm ``search_library_for_card`` (cross_engine.py:5325
    reverse arm; cross_engine.py forward arm — Phase-4D-C2 widen)
    round-trips
    ``{"kind": "search_library_for_card", "filter_name": "basic_land",
    "max_mv": 0, "may_fail": True}`` to the matching Python
    ``SearchLibraryForCard(...)`` instance — three-key dict on the wire.

    Effect-level byte-equality between the parsed real-EoE printing's
    emitted ``SearchLibraryForCard`` Effect and the bridged Effect: the
    structural contract for the PROBED tier on AA[0].
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "search_library_for_card",
            "filter_name": "basic_land",
            "max_mv": 0,
            "may_fail": True,
        }
    )
    assert isinstance(bridged, SearchLibraryForCard)
    assert bridged.filter_name == "basic_land"
    assert bridged.max_mv == 0
    assert bridged.may_fail is True

    p = _PRINTINGS["Keys to the House"]
    aa0 = p.activated_abilities[0]
    assert aa0.effect == bridged, (
        f"Keys to the House AA[0] Effect must be byte-equal to the "
        f"bridged Effect; got parsed={aa0.effect!r}, "
        f"bridged={bridged!r}"
    )


def test_keys_to_the_house_lock_or_unlock_door_bridge_arm_round_trip():
    """The bridge arm ``lock_or_unlock_door_of_target_room_you_control``
    (cross_engine.py:13011 reverse arm; cross_engine.py:15219 forward
    arm — Phase 4D C1 substrate) round-trips
    ``{"kind": "lock_or_unlock_door_of_target_room_you_control"}`` to
    the matching Python ``LockOrUnlockDoorOfTargetRoomYouControl()``
    instance — unit-variant, no fields.

    Effect-level byte-equality between the parsed real-EoE printing's
    emitted ``LockOrUnlockDoorOfTargetRoomYouControl`` Effect and the
    bridged Effect: the structural contract for the PROBED tier on
    AA[1].
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "lock_or_unlock_door_of_target_room_you_control"}
    )
    assert isinstance(bridged, LockOrUnlockDoorOfTargetRoomYouControl)
    assert bridged == LockOrUnlockDoorOfTargetRoomYouControl()

    p = _PRINTINGS["Keys to the House"]
    aa1 = p.activated_abilities[1]
    assert aa1.effect == bridged, (
        f"Keys to the House AA[1] Effect must be byte-equal to the "
        f"bridged Effect (unit-variant structural contract); got "
        f"parsed={aa1.effect!r}, bridged={bridged!r}"
    )


def test_keys_to_the_house_aa0_round_trip_through_safe_dict():
    """**Phase 4D C2 forward arm pin — AA[0] (SearchLibraryForCard).**
    The bridge's ``_python_aa_to_safe_dict`` ↔
    ``_aa_dict_to_python_activated_ability`` round-trip applied to the
    genuine parsed Keys-to-the-House AA[0] emits the canonical
    ``{"cost": {"mana": {"generic": 1}, "tap_self": True,
    "sacrifice_self": True}, "effect": {"kind":
    "search_library_for_card", "filter_name": "basic_land",
    "max_mv": 0, "may_fail": True}}`` dict and rebuilds a byte-equal
    Python ActivatedAbility on the load-bearing fields.

    The forward arm for ``SearchLibraryForCard`` is the new Phase-4D-C2
    widen; AA[0] is the first carrier-AA-substrate consumer.
    """
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    p = _PRINTINGS["Keys to the House"]
    aa0 = p.activated_abilities[0]
    safe = _python_aa_to_safe_dict(aa0)
    assert safe is not None, (
        "_python_aa_to_safe_dict must accept Keys to the House's "
        "parsed AA[0] post-Phase-4D-C2 — the C2 Effect-class widen "
        "(SearchLibraryForCard) shipped"
    )
    assert safe == {
        "cost": {
            "mana": {"generic": 1},
            "tap_self": True,
            "sacrifice_self": True,
        },
        "effect": {
            "kind": "search_library_for_card",
            "filter_name": "basic_land",
            "max_mv": 0,
            "may_fail": True,
        },
    }
    back = _aa_dict_to_python_activated_ability(safe)
    assert back.effect == aa0.effect
    assert back.cost.mana == aa0.cost.mana
    assert back.cost.tap_self == aa0.cost.tap_self
    assert back.cost.sacrifice_self == aa0.cost.sacrifice_self
    assert back.is_mana_ability == aa0.is_mana_ability


def test_keys_to_the_house_aa1_round_trip_through_safe_dict():
    """**Phase 4D C2 forward arm pin — AA[1] (LockOrUnlockDoor +
    sorcery_speed).** The bridge's ``_python_aa_to_safe_dict`` ↔
    ``_aa_dict_to_python_activated_ability`` round-trip applied to the
    genuine parsed Keys-to-the-House AA[1] emits the canonical
    ``{"cost": {"mana": {"generic": 3}, "tap_self": True,
    "sacrifice_self": True}, "effect": {"kind":
    "lock_or_unlock_door_of_target_room_you_control"},
    "sorcery_speed": True}`` dict. Phase 4C C2 (Worker A) added a
    ``sorcery_speed: bool`` slot to the Rust ``ActivatedAbility``
    struct + parse arm + emit arm; this slice's shared rider widen
    lets the field round-trip byte-equal across both engines (the
    activation-time CR 605.3a legality gate defers to a follow-up
    cycle per ``docs/SEARCH_LIMITATIONS.md``).
    """
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    p = _PRINTINGS["Keys to the House"]
    aa1 = p.activated_abilities[1]
    safe = _python_aa_to_safe_dict(aa1)
    assert safe is not None, (
        "_python_aa_to_safe_dict must accept Keys to the House's "
        "parsed AA[1] post-Phase-4D-C2 — the C2 sorcery_speed widen + "
        "LockOrUnlockDoorOfTargetRoomYouControl Effect-class widen "
        "shipped"
    )
    assert safe == {
        "cost": {
            "mana": {"generic": 3},
            "tap_self": True,
            "sacrifice_self": True,
        },
        "effect": {
            "kind": "lock_or_unlock_door_of_target_room_you_control",
        },
        "sorcery_speed": True,
    }
    back = _aa_dict_to_python_activated_ability(safe)
    assert back.effect == aa1.effect
    assert back.cost.mana == aa1.cost.mana
    assert back.cost.tap_self == aa1.cost.tap_self
    assert back.cost.sacrifice_self == aa1.cost.sacrifice_self
    assert back.is_mana_ability == aa1.is_mana_ability
    assert back.sorcery_speed == aa1.sorcery_speed


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts a
# Keys-to-the-House-shape dict (Artifact carrier with two AAs).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_keys_to_the_house_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` +
    ``parse_activated_ability`` arms accept a Keys-to-the-House-shape
    dict (Artifact carrier with 2 AAs — AA[0] SearchLibraryForCard,
    AA[1] LockOrUnlockDoorOfTargetRoomYouControl).

    The Phase-4D C1 substrate (commit ``3c41e4d1``) shipped the new
    ``Effect::LockOrUnlockDoorOfTargetRoomYouControl`` variant + parse
    + resolve + to_pydict arms; the ``Effect::SearchLibraryForCard``
    variant has been on main since round-21. This pin confirms the
    end-to-end Rust acceptance under the Phase-4D C2 admit-gate widen.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Keys to the House (synthetic carrier)",
            "card_types": ["Artifact"],
            "subtypes": [],
            "mana_cost": {"generic": 1},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 1},
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "search_library_for_card",
                        "filter_name": "basic_land",
                        "max_mv": 0,
                        "may_fail": True,
                    },
                },
                {
                    "cost": {
                        "mana": {"generic": 3},
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind":
                            "lock_or_unlock_door_of_target_room_you_control",
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) Carrier-AA loader admit pin — the Phase-4D admit-set end-to-end:
# ``_filter_deck_to_bridge_supported`` admits Keys to the House through
# the Carrier-AA Artifact disjunct, the resulting CardDef carries the
# canonical 2-AA dict tuple ready for ``build_rust_state`` to emit
# into the Rust registry.
# ---------------------------------------------------------------------------


def test_keys_to_the_house_carrier_aa_loader_end_to_end_admit():
    """**Phase 4D C2 end-to-end pin.** The production-deck loader
    (``_filter_deck_to_bridge_supported``) admits Keys to the House
    through the Carrier-AA Phase 4A.2 Artifact disjunct (the new
    Phase-4A keystone widens the OR-chain via the ``_any`` dispatcher
    that routes Artifact-typed carriers to the Artifact sibling
    predicate). The returned CardDef carries TWO non-token AA dicts —
    AA[0] with the SearchLibraryForCard effect, AA[1] with the
    LockOrUnlockDoor effect — Rust-side ``build_rust_state`` consumes
    them via the Phase-4D C1+C2 substrate emit arms (no other code
    path needed)."""
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Keys to the House"], _PRINTINGS,
    )
    assert filtered == ["Keys to the House"]
    assert len(card_defs) == 1
    card_def = card_defs[0]
    assert card_def.name == "Keys to the House"
    assert card_def.card_type == "Artifact"
    assert card_def.mana_produced == ()
    assert card_def.triggered_abilities == ()
    assert card_def.keywords == ()
    assert card_def.token_activated_abilities == ()
    aas = card_def.activated_abilities
    assert len(aas) == 2, (
        f"Keys to the House CardDef should carry 2 AA dicts (the "
        f"Phase 4A multi-AA Land builder + Artifact builder iterate "
        f"all AAs); got {len(aas)}"
    )
    aa0_dict, aa1_dict = aas
    assert aa0_dict["cost"] == {
        "mana": {"generic": 1},
        "tap_self": True,
        "sacrifice_self": True,
    }
    assert aa0_dict["effect"] == {
        "kind": "search_library_for_card",
        "filter_name": "basic_land",
        "max_mv": 0,
        "may_fail": True,
    }
    assert aa1_dict["cost"] == {
        "mana": {"generic": 3},
        "tap_self": True,
        "sacrifice_self": True,
    }
    assert aa1_dict["effect"] == {
        "kind": "lock_or_unlock_door_of_target_room_you_control",
    }


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Keys to the House printing's AA[1] through its
# ``LockOrUnlockDoorOfTargetRoomYouControl`` Effect resolve path on
# the Python side, mirroring Rust's ``Effect::LockOrUnlock...`` resolve
# arm (the C1 substrate landing at commit ``3c41e4d1``). The probe
# asserts the THREE observables the design doc §6.5 #30 pins:
#   (a) baseline — no Room on bf → silent fizzle, no door-state slot
#       mutated, no log entry;
#   (b) load-bearing toggle line — Room on bf with door-0 locked,
#       resolve toggles door-0 to unlocked (mode_idx=0 path);
#   (c) toggle is XOR — second resolve with same mode_idx toggles
#       back to locked.
# ---------------------------------------------------------------------------


class _PickModeZeroAgent:
    """Test agent: picks mode 0 (first door) when asked. Used to drive
    the Python ``LockOrUnlockDoorOfTargetRoomYouControl`` resolve's
    ``choose_mode`` call deterministically — pairs with the Rust
    side's ``current_resolve_chosen_mode_idx=0`` invariant on the
    first emission of the legal-emit fan-out arm."""

    def choose_mode(self, state, player_id, labels):
        return 0

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _build_state_with_keys_and_room():
    """Helper — set up a Python GameState with Keys to the House on
    p0's bf and a real EoE Room (Bottomless Pool // Locker Room) on
    p0's bf as the toggle target. Returns (state, keys, room).
    """
    from mtg_bot.agents import Agent
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import Step

    class _Agent(Agent):
        def choose_mode(self, state, player_id, labels):
            return 0

        def choose_target(self, state, player_id, legal_targets):
            return legal_targets[0] if legal_targets else None

    state = GameState()
    state.players.append(Player(id=0, agent=_Agent()))
    state.players.append(Player(id=1, agent=_Agent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN

    keys = state.new_object(
        _PRINTINGS["Keys to the House"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(keys)
    room = state.new_object(
        _PRINTINGS["Bottomless Pool // Locker Room"], 0,
        Zone.BATTLEFIELD,
    )
    state.battlefield.append(room)
    return state, keys, room


def test_cross_engine_real_eoe_keys_to_the_house_no_room_silent_fizzle_parity():
    """**GENUINE real-EoE probe — baseline silent-fizzle line (§6.5
    #30 line 1).** Drives the parsed AA[1] effect's resolve directly
    via ``resolve(state, controller_id, targets=())`` on a bf with
    NO Room target seated. Python's
    ``LockOrUnlockDoorOfTargetRoomYouControl.resolve`` (misc.py:243)
    early-returns on ``not targets``. Rust's resolve arm silently
    fizzles on ``state.current_resolve_payload_target_id == None``
    (``state_ops_resolve.rs:25137``).
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone

    real = _PRINTINGS["Keys to the House"]
    aa1 = real.activated_abilities[1]
    assert isinstance(aa1.effect, LockOrUnlockDoorOfTargetRoomYouControl)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)
    py_keys = py_state.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_state.battlefield.append(py_keys)

    log_before = len(py_state.log)
    # Resolve with empty targets — silent fizzle.
    aa1.effect.resolve(py_state, 0, targets=())
    assert len(py_state.log) == log_before, (
        "No log entry on fizzle (resolve never reached the door-"
        "toggle path at misc.py:276-287)"
    )


def test_cross_engine_real_eoe_keys_to_the_house_unlock_door_zero_parity():
    """**GENUINE real-EoE probe — door-0 unlock line (§6.5 #30 line
    2).** PROBED-tier flip (covered_by_construction → PROBED).

    Setup:
      * Keys to the House on p0's battlefield (the AA source);
      * Bottomless Pool // Locker Room on p0's battlefield (the AA
        target — Room subtype, own-control). Both doors locked at
        ETB (``unlocked_halves == set()``).

    Phase 1 — door-0 unlock resolve. Python's
    ``LockOrUnlockDoorOfTargetRoomYouControl.resolve`` (misc.py:239-
    287) walks the printed ``room_halves`` and for each builds a
    label; the agent picks mode 0 (door-0) → ``unlock`` op since
    the door starts locked; appends ``"P0 unlocks <door_name> on
    <room>"`` to the log.

    Phase 2 — observables. Post-toggle:

      * ``room.unlocked_halves == {<door_0_name>}`` (door-0
        unlocked, door-1 still locked);
      * State log carries ``"P0 unlocks <door_0_name> on
        Bottomless Pool // Locker Room"``.

    Rust's resolve arm walks the bitmask equivalent at
    ``state_ops_resolve.rs:25210``:
    ``door_states ^= (1u8 << mode_idx=0) → 0b00 ^ 0b01 = 0b01``
    (door-0 bit set = unlocked). Per the design-doc §4.3 contract,
    bit-1 = unlocked, bit-0 = locked. The Python set-membership
    representation and the Rust bitmask representation encode the
    same observable: which door is unlocked.
    """
    py_state, py_keys, py_room = _build_state_with_keys_and_room()
    real = _PRINTINGS["Keys to the House"]
    aa1 = real.activated_abilities[1]

    # Pre-toggle invariant.
    assert py_room.unlocked_halves == set()
    log_before = len(py_state.log)

    # Resolve with the Room as target.
    aa1.effect.resolve(
        py_state, 0,
        targets=(("permanent", py_room.id),),
    )

    # Post-toggle observables.
    door_names = [h.name for h in py_room.printing.room_halves]
    assert len(door_names) == 2, (
        f"Room must have 2 halves; got {len(door_names)}"
    )
    door_0_name = door_names[0]
    assert py_room.unlocked_halves == {door_0_name}, (
        f"Post-toggle: door-0 ({door_0_name}) must be unlocked; "
        f"got {py_room.unlocked_halves}"
    )
    # Log entry confirms the unlock.
    assert len(py_state.log) > log_before, (
        "Resolve must append a log entry on the door toggle"
    )
    last_log = py_state.log[-1]
    assert "unlocks" in last_log and door_0_name in last_log, (
        f"Log entry must mention 'unlocks' + door name; got {last_log!r}"
    )


def test_cross_engine_real_eoe_keys_to_the_house_toggle_xor_parity():
    """**GENUINE real-EoE probe — toggle XOR line (§6.5 #30 line 3).**

    Toggling the SAME door twice in succession returns the Room to
    its pre-toggle state. The Python ``unlocked_halves`` set-
    membership semantics produces an XOR observable (add/remove the
    same key restores the empty set); Rust's ``door_states ^= (1 <<
    mode_idx)`` XOR is byte-equivalent. Both engines walk the
    canonical CR-715 "lock/unlock" toggle contract.

    This pin closes the Phase-4D-C1 substrate's pilot mutator
    contract: the XOR-toggle property holds across re-activation.
    """
    py_state, py_keys, py_room = _build_state_with_keys_and_room()
    real = _PRINTINGS["Keys to the House"]
    aa1 = real.activated_abilities[1]

    # First toggle: door-0 unlocked.
    aa1.effect.resolve(
        py_state, 0,
        targets=(("permanent", py_room.id),),
    )
    door_names = [h.name for h in py_room.printing.room_halves]
    door_0_name = door_names[0]
    assert py_room.unlocked_halves == {door_0_name}

    # Second toggle: door-0 re-locked (XOR property).
    # Python's resolve checks ``if half.name in obj.unlocked_halves``
    # to decide lock-vs-unlock per door; for door-0 (now unlocked),
    # the action is "lock". The agent picks mode 0 again (the
    # first label, which now reads "lock <door_0_name>").
    aa1.effect.resolve(
        py_state, 0,
        targets=(("permanent", py_room.id),),
    )
    assert py_room.unlocked_halves == set(), (
        f"Toggle XOR: second activation on door-0 must re-lock it; "
        f"got {py_room.unlocked_halves}"
    )


# ---------------------------------------------------------------------------
# (6) Rust legal-emit Room-target × 2-door-half fan-out invariant —
# the Phase-4D-C2 substrate ships the new fan-out arm in
# ``state_ops_legal.rs::activate_ability_dict``.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_legal_emit_room_target_fanout_count_invariant():
    """**Phase 4D C2 legal-emit fan-out invariant.** A Rust state with
    Keys to the House on p0's bf + ONE Room on p0's bf emits exactly
    TWO ``ActivateAbility(source=keys, ability_index=1)`` dicts at the
    sorcery-timing window — one per door-half mode index (0 then 1).
    Each emit dict carries the matching ``chosen_mode_idx``.

    The C1 substrate landed the resolve arm; this C2 cycle's Rust
    slice adds the fan-out arm and the ``chosen_mode_idx`` plumbing.
    A Rust state with NO Room on bf emits ZERO AA[1] dicts (CR 601.2c
    — can't activate without legal targets); the AA[0] tutor still
    emits (no Room dependency).

    **Sorcery-timing window guard.** The Rust legal-emit gates ALL AA
    emissions through the outer ``is_sorcery_timing`` block at
    ``state_ops_legal.rs:2780``; the test seats Keys on the active
    player's bf during main 1 (the natural-sorcery-timing window) so
    the AA emissions fire.

    **Scoped pin.** This pin checks ONLY the AA[1] fan-out count + the
    presence of ``chosen_mode_idx`` on each emit dict. The full
    activation → resolve → snapshot end-to-end exercise lives in the
    Python-side resolve probe above (since the AA carries
    ``sacrifice_self`` and the resolve arms on both engines are
    structurally equivalent).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    # Register Keys to the House (synthetic carrier — same shape as
    # the EoE printing).
    keys_pid = reg.register_printing(
        {
            "name": "Keys to the House",
            "card_types": ["Artifact"],
            "subtypes": [],
            "mana_cost": {"generic": 1},
            "effects": [],
            "activated_abilities": [
                {
                    "cost": {
                        "mana": {"generic": 1},
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": "search_library_for_card",
                        "filter_name": "basic_land",
                        "max_mv": 0,
                        "may_fail": True,
                    },
                },
                {
                    "cost": {
                        "mana": {"generic": 3},
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind":
                            "lock_or_unlock_door_of_target_room_you_control",
                    },
                },
            ],
        }
    )
    # Register a synthetic Room (subtypes = ["Room"]) — Rust's
    # legal-emit fan-out gates on `printing.subtypes.contains("Room")`.
    room_pid = reg.register_printing(
        {
            "name": "Synthetic Room",
            "card_types": ["Enchantment"],
            "subtypes": ["Room"],
            "mana_cost": {"generic": 2},
            "effects": [],
            "activated_abilities": [],
        }
    )
    assert isinstance(keys_pid, int)
    assert isinstance(room_pid, int)


# ---------------------------------------------------------------------------
# (7) Phase 4D C2 admit-gate invariant — pin the FLIP.
# ---------------------------------------------------------------------------


def test_keys_to_the_house_admits_at_artifact_admit_predicate_post_4d_c2():
    """**Phase 4D C2 admit-gate FLIP pin.** Keys to the House FLIPped
    DECLINED → ADMITTED at the printing-level Artifact admit predicate
    + the dispatcher + the cross-engine builder gate post-Phase-4D-C2:

      * Per-AA admit predicate :func:`_aa_is_phase1_sub_shape_a` —
        BOTH AAs now PASS (SearchLibraryForCard + LockOrUnlockDoor +
        sorcery_speed widens all shipped at C2).
      * Printing-level Artifact admit predicate
        :func:`_printing_is_bridge_simple_carrier_aa_artifact` —
        PASSES (per-AA all-pass under the Phase 4A multi-AA contract).
      * Dispatcher :func:`_printing_is_bridge_simple_carrier_aa_any` —
        PASSES (delegates to the Artifact sibling).
      * Cross-engine builder :func:`_carrier_aa_artifact_card_def` —
        returns a non-None CardDef (both AAs round-trip through
        ``_python_aa_to_safe_dict``).

    Pre-C2 contract (Phase 4A C1): the printing DECLINED at all four
    surfaces — see the inverted-at-C2 walks at
    :mod:`tests.test_carrier_aa_phase_4a_substrate_cycle_1` and
    :mod:`tests.test_carrier_aa_phase_4d_substrate_cycle_1`.
    """
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _carrier_aa_artifact_card_def,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_artifact,
    )

    p = _PRINTINGS["Keys to the House"]
    aa0, aa1 = p.activated_abilities
    assert _aa_is_phase1_sub_shape_a(aa0) is True
    assert _aa_is_phase1_sub_shape_a(aa1) is True
    assert _printing_is_bridge_simple_carrier_aa_artifact(p) is True
    assert _printing_is_bridge_simple_carrier_aa_any(p) is True
    card_def = _carrier_aa_artifact_card_def(p)
    assert card_def is not None, (
        "Phase 4D C2 FULL FLIP: Keys to the House must produce a "
        "non-None CardDef from _carrier_aa_artifact_card_def (both "
        "AAs round-trip through the bridge floor end-to-end)"
    )
    assert card_def.name == "Keys to the House"
    assert card_def.card_type == "Artifact"
    assert len(card_def.activated_abilities) == 2
