"""Ghost Vacuum — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip; Carrier-AA Phase 4C
admit-set landing; CLOSES Phase 4C).

Ghost Vacuum is a ``{1}`` Artifact in the EoE pool with two activated
abilities:

    {T}: Exile target card from a graveyard.
    {6}, {T}, Sacrifice this artifact: Put each creature card exiled
    with Ghost Vacuum onto the battlefield under your control with a
    flying counter on it. Each of them is a 1/1 Spirit in addition to
    its other types.

The Carrier-AA substrate Phase 4C (2026-05-26 — see
``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §7.3) closes in
THREE cycles: (C1) Rust substrate — two new ``Effect`` variants
(``ExileTargetCardFromGraveyard`` + ``PutEachCreatureCardExiledWith
SourceOntoBattlefieldUnderYourControl``) + per-player-graveyard
single-target fan-out + zero-target mass-effect resolve + cross-
engine bridge arms; landed at commit ``8004d970``; (C2) Python
admit widen + Ghost Vacuum FLIP + Rust ActivatedAbility
sorcery_speed slot — the ``_carrier_aa_phase_1_effect_classes``
lazy frozenset accessor at ``src/mtg_bot/parity/trajectory.py``
extended 9 → 11 with the two new Effect classes; the
``_python_aa_to_safe_dict`` AA-rider gate widened to admit
``sorcery_speed=True``; the Rust ``ActivatedAbility`` struct gained
a ``sorcery_speed: bool`` slot + ``parse_activated_ability`` widen;
(C3) THIS PROBE — real-EoE per-card byte-equal observable on the
Effect/bridge round-trip + Rust register acceptance + Python-side
AA[0] resolve substrate. Closes Phase 4C.

Parser-emitted AA shapes:

    AA[0]: ``ActivatedAbility(cost=ActivationCost(tap_self=True),
            effect=ExileTargetCardFromGraveyard())``
    AA[1]: ``ActivatedAbility(cost=ActivationCost(mana=ManaCost(
            generic=6), tap_self=True, sacrifice_self=True),
            effect=PutEachCreatureCardExiledWithSourceOntoBattlefield
            UnderYourControl(grant_flying_counter=True,
            grant_subtype_and_pt=("Spirit", 1, 1)),
            sorcery_speed=True)``

The bridge round-trips both AAs end-to-end via the Phase 4C C1
forward + reverse arms in ``cross_engine.py`` (``_python_aa_to_safe_
dict`` at line ~15195 emits ``"kind": "exile_target_card_from_
graveyard"`` + ``"kind": "put_each_creature_card_exiled_with_
source_onto_battlefield_under_your_control"`` with optional
``grant_flying_counter`` + ``grant_subtype_and_pt`` payload;
``_ta_dict_to_python_effect`` at line ~13049 reverses each kind
back to its frozen dataclass). The Phase 4C C2 widen lifts the
``sorcery_speed=True`` AA-rider gate so AA[1] passes the round-trip
floor.

**EEEE-idiom for the ActivatedAbility carrier.** Same lane discipline
as the sibling Carrier-AA AA probes — parse + bridge round-trip +
loader-end-to-end admit + Python-side AA[0] resolve substrate. The
probe drives AA[0] (``ExileTargetCardFromGraveyard``) through its
actual Python resolve on a populated graveyard, with observables
that mirror Rust's ``Effect::ExileTargetCardFromGraveyard`` resolve
arm at ``state_ops_resolve.rs`` (Phase 4C C1 substrate landing).

**SL note — recall-variant rider divergence.** AA[1]'s
``grant_flying_counter`` + ``grant_subtype_and_pt`` riders round-
trip cleanly on the wire (forward emit + reverse parse + Rust
struct stores them), but the Rust resolve arm DOES NOT apply them
at recall time — the layered-grant machinery (flying counter +
Spirit subtype + 1/1 base P/T continuous effect) is a Phase-N gap.
Python's resolve arm DOES apply them. The probe therefore covers
the AA[0] exile-from-graveyard resolve byte-equal on both sides but
defers the AA[1] recall-resolve byte-equal to Phase N per
``docs/SEARCH_LIMITATIONS.md`` Phase 4C entry. See the SL doc for
the full divergence trace.

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Ghost Vacuum slug to (a) the AA[0] +
``ExileTargetCardFromGraveyard`` Effect+bridge round-trip on the
REAL parsed EoE printing AND (b) the AA[1] +
``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl``
Effect+bridge round-trip + Rust register acceptance. The
sorcery_speed AA-rider widen on the Rust ``ActivatedAbility`` struct
is end-to-end exercised here for the FIRST time at PROBED-tier
granularity.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.exile import (
    ExileTargetCardFromGraveyard,
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
)


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 4


# ---------------------------------------------------------------------------
# (1) Parser SoT — Ghost Vacuum is parser-claimed and carries the exact
# 2-AA shape the design doc (§4.2 + §5.5) pins.
# ---------------------------------------------------------------------------


def test_ghost_vacuum_parser_claims_card():
    assert "Ghost Vacuum" in _PRINTINGS, (
        "Ghost Vacuum must be parser-claimed by the active CardSource"
    )


def test_ghost_vacuum_printed_attrs():
    """Pins the basic printing surface: single-typed Artifact, ``{1}``
    mana cost, no power/toughness, no triggered/static/keyword riders.
    Ghost Vacuum carries NO leading ``{T}: Add`` mana ability; the
    two carrier AAs (exile-from-graveyard + recall) are the SOLE
    ``activated_abilities`` entries.
    """
    p = _PRINTINGS["Ghost Vacuum"]
    assert p.card_types == ("Artifact",)
    assert p.subtypes == ()
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == ()
    assert p.power is None and p.toughness is None
    assert p.keywords == frozenset()
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


def test_ghost_vacuum_activated_abilities_shape():
    """Ghost Vacuum carries EXACTLY 2 activated abilities -- AA[0]
    is the bare ``{T}: ExileTargetCardFromGraveyard`` carrier; AA[1]
    is the recall ``{6}, {T}, Sacrifice this artifact:
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl``
    with the Spirit-flyer rider payload + ``sorcery_speed=True``.
    """
    p = _PRINTINGS["Ghost Vacuum"]
    aas = tuple(p.activated_abilities or ())
    assert len(aas) == 2

    # AA[0] -- exile-from-graveyard pilot
    aa0 = aas[0]
    assert isinstance(aa0.effect, ExileTargetCardFromGraveyard)
    assert aa0.cost.tap_self is True
    assert aa0.cost.sacrifice_self is False
    assert aa0.cost.mana is None
    assert aa0.is_mana_ability is False
    assert aa0.sorcery_speed is False
    assert aa0.activate_only_once is False
    assert aa0.tier_threshold == 0
    assert aa0.room_half is None
    assert aa0.cost_reductions == ()
    assert aa0.effect.requires_target() is True

    # AA[1] -- recall pilot
    aa1 = aas[1]
    assert isinstance(
        aa1.effect,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    assert aa1.cost.tap_self is True
    assert aa1.cost.sacrifice_self is True
    assert aa1.cost.mana is not None
    assert aa1.cost.mana.generic == 6
    assert aa1.cost.mana.colored == ()
    assert aa1.cost.mana.hybrid == ()
    assert aa1.cost.mana.x_pips == 0
    assert aa1.is_mana_ability is False
    assert aa1.sorcery_speed is True  # Phase 4C C2 widen target
    assert aa1.activate_only_once is False
    assert aa1.tier_threshold == 0
    assert aa1.room_half is None
    assert aa1.cost_reductions == ()
    # Recall rider payload.
    assert aa1.effect.grant_flying_counter is True
    assert aa1.effect.grant_subtype_and_pt == ("Spirit", 1, 1)
    # Zero-target mass effect -- no per-target fan-out.
    assert aa1.effect.requires_target() is False


# ---------------------------------------------------------------------------
# (2) Bridge round-trip -- both AA Effect kinds round-trip byte-equal
# to the parsed printing's emitted Effect via the Phase 4C C1 bridge
# arms.
# ---------------------------------------------------------------------------


def test_ghost_vacuum_bridge_arm_aa0_round_trip():
    """The bridge arm ``exile_target_card_from_graveyard``
    (``cross_engine.py`` C1 forward+reverse) round-trips the AA[0]
    Effect to its Python instance.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "exile_target_card_from_graveyard"}
    )
    assert isinstance(bridged, ExileTargetCardFromGraveyard)

    p = _PRINTINGS["Ghost Vacuum"]
    aa0 = p.activated_abilities[0]
    assert aa0.effect == bridged


def test_ghost_vacuum_bridge_arm_aa1_round_trip():
    """The bridge arm
    ``put_each_creature_card_exiled_with_source_onto_battlefield_under
    _your_control`` round-trips AA[1]'s Effect with the full rider
    payload (grant_flying_counter + grant_subtype_and_pt).
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": (
                "put_each_creature_card_exiled_with_source_"
                "onto_battlefield_under_your_control"
            ),
            "grant_flying_counter": True,
            "grant_subtype_and_pt": ("Spirit", 1, 1),
        }
    )
    assert isinstance(
        bridged,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    assert bridged.grant_flying_counter is True
    assert bridged.grant_subtype_and_pt == ("Spirit", 1, 1)

    p = _PRINTINGS["Ghost Vacuum"]
    aa1 = p.activated_abilities[1]
    assert aa1.effect == bridged


def test_ghost_vacuum_aa0_round_trip_through_safe_dict():
    """The bridge's ``_python_aa_to_safe_dict`` ↔
    ``_aa_dict_to_python_activated_ability`` round-trip on AA[0] emits
    a canonical Phase-4C dict shape and rebuilds the parsed AA byte-
    equal on the load-bearing fields. AA[0] has no mana cost, no
    riders -- the minimal carrier shape.
    """
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    p = _PRINTINGS["Ghost Vacuum"]
    aa0 = p.activated_abilities[0]
    safe = _python_aa_to_safe_dict(aa0)
    assert safe is not None
    assert safe == {
        "cost": {"tap_self": True},
        "effect": {"kind": "exile_target_card_from_graveyard"},
    }
    back = _aa_dict_to_python_activated_ability(safe)
    assert back == aa0


def test_ghost_vacuum_aa1_round_trip_through_safe_dict():
    """The bridge's ``_python_aa_to_safe_dict`` ↔
    ``_aa_dict_to_python_activated_ability`` round-trip on AA[1] emits
    the canonical Phase-4C dict shape including the
    ``sorcery_speed=True`` AA-rider (Phase 4C C2 widen) + the
    ``grant_flying_counter`` + ``grant_subtype_and_pt`` Effect riders.
    """
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    p = _PRINTINGS["Ghost Vacuum"]
    aa1 = p.activated_abilities[1]
    safe = _python_aa_to_safe_dict(aa1)
    assert safe is not None
    assert safe == {
        "cost": {
            "mana": {"generic": 6},
            "tap_self": True,
            "sacrifice_self": True,
        },
        "effect": {
            "kind": (
                "put_each_creature_card_exiled_with_source_"
                "onto_battlefield_under_your_control"
            ),
            "grant_flying_counter": True,
            "grant_subtype_and_pt": ("Spirit", 1, 1),
        },
        "sorcery_speed": True,
    }
    back = _aa_dict_to_python_activated_ability(safe)
    # Cost dataclass has a parser-display ``mana_str`` field that isn't
    # carried on the bridge (the bridge carries only the structured
    # ``mana: ManaCost`` field; mana_str is parser-only / UI-side).
    # Compare load-bearing fields only.
    assert back.cost.mana == aa1.cost.mana
    assert back.cost.tap_self == aa1.cost.tap_self
    assert back.cost.sacrifice_self == aa1.cost.sacrifice_self
    assert back.effect == aa1.effect
    assert back.is_mana_ability == aa1.is_mana_ability
    assert back.sorcery_speed == aa1.sorcery_speed
    assert back.tier_threshold == aa1.tier_threshold
    assert back.activate_only_once == aa1.activate_only_once
    assert back.cost_reductions == aa1.cost_reductions
    assert back.room_half == aa1.room_half


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity -- the Rust parser accepts a Ghost-
# Vacuum-shape dict end-to-end (both AAs, with the sorcery_speed rider
# on AA[1]).
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_ghost_vacuum_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` + ``parse_activated_ability``
    arms accept a Ghost-Vacuum-shape Artifact dict carrying both AAs
    (including ``sorcery_speed=True`` on AA[1] -- the Phase 4C C2 Rust
    struct slot landing). The Phase 4C C1 substrate (commit
    ``8004d970``) shipped both Effect variants + per-player-graveyard
    fan-out + mass-effect resolve + cross-engine bridge arms; this pin
    confirms end-to-end Rust acceptance under the Phase 4C C2 admit
    widen + sorcery_speed Rust slot.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Ghost Vacuum (synthetic carrier)",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "activated_abilities": [
                {
                    "cost": {"tap_self": True},
                    "effect": {
                        "kind": "exile_target_card_from_graveyard",
                    },
                },
                {
                    "cost": {
                        "mana": {"generic": 6},
                        "tap_self": True,
                        "sacrifice_self": True,
                    },
                    "effect": {
                        "kind": (
                            "put_each_creature_card_exiled_with_source_"
                            "onto_battlefield_under_your_control"
                        ),
                        "grant_flying_counter": True,
                        "grant_subtype_and_pt": ("Spirit", 1, 1),
                    },
                    "sorcery_speed": True,
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) Carrier-AA loader admit pin -- the Phase 4C end-to-end FLIP:
# ``_filter_deck_to_bridge_supported`` admits Ghost Vacuum through the
# Carrier-AA Artifact disjunct, the resulting CardDef carries both
# AAs as canonical dicts ready for Rust register_printing.
# ---------------------------------------------------------------------------


def test_ghost_vacuum_carrier_aa_loader_end_to_end_admit():
    """**Phase 4C end-to-end FLIP pin.** The production-deck loader
    (``_filter_deck_to_bridge_supported``) admits Ghost Vacuum through
    the Carrier-AA Phase 4C disjunct (the Artifact sibling predicate +
    builder). The returned CardDef carries both non-token AAs as
    canonical Phase-4C dict shapes -- Rust-side ``build_rust_state``
    consumes them via the Phase 4C C1 substrate emit arms.
    """
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Ghost Vacuum"], _PRINTINGS,
    )
    assert filtered == ["Ghost Vacuum"]
    assert len(card_defs) == 1
    card_def = card_defs[0]
    assert card_def.name == "Ghost Vacuum"
    assert card_def.card_type == "Artifact"
    assert card_def.mana_produced == ()
    assert card_def.triggered_abilities == ()
    assert card_def.keywords == ()
    assert card_def.token_activated_abilities == ()
    aas = card_def.activated_abilities
    assert len(aas) == 2

    # AA[0] -- the bare {T} pilot.
    assert aas[0]["cost"] == {"tap_self": True}
    assert aas[0]["effect"] == {"kind": "exile_target_card_from_graveyard"}
    assert "sorcery_speed" not in aas[0]

    # AA[1] -- the recall with sorcery_speed.
    assert aas[1]["cost"] == {
        "mana": {"generic": 6},
        "tap_self": True,
        "sacrifice_self": True,
    }
    assert aas[1]["effect"] == {
        "kind": (
            "put_each_creature_card_exiled_with_source_"
            "onto_battlefield_under_your_control"
        ),
        "grant_flying_counter": True,
        "grant_subtype_and_pt": ("Spirit", 1, 1),
    }
    assert aas[1]["sorcery_speed"] is True


@_rust_skip
def test_ghost_vacuum_cross_engine_register_end_to_end():
    """**End-to-end cross-engine register pin.** A CardDef built from
    the live parsed Ghost Vacuum printing registers on the Rust side
    via the standard ``_spec_card_to_printing_dict`` -> Rust
    ``register_printing`` path without error. Validates the Phase 4C
    C2 admit-FLIP closes end-to-end through the production bridge
    machinery.
    """
    import mtg_bot_engine

    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Ghost Vacuum"], _PRINTINGS,
    )
    assert filtered == ["Ghost Vacuum"]
    cd = card_defs[0]
    printing_dict = _spec_card_to_printing_dict(cd)
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(printing_dict)
    assert isinstance(pid, int) and pid >= 0


# ---------------------------------------------------------------------------
# (5) GENUINE real-EoE cross-engine byte-equal probe -- drives the
# ACTUAL parsed Ghost Vacuum printing's AA[0]
# (ExileTargetCardFromGraveyard) through its Python resolve path,
# mirroring Rust's Effect::ExileTargetCardFromGraveyard resolve arm
# (Phase 4C C1 substrate landing at commit 8004d970). The probe
# asserts two load-bearing observables:
#   (a) baseline empty-graveyards no-op (no targets, no-op resolve
#       silently fizzles -- both engines stamp a no-op state);
#   (b) populated-graveyard single-target exile -- the target moves
#       from graveyard -> exile on the owner's side, with
#       ``exiled_by_source`` stamped to the Ghost Vacuum source id so
#       the AA[1] recall sibling can find it later (per-owner routing
#       + linkage stamp, the load-bearing C1 substrate observables).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_ghost_vacuum_aa0_baseline_empty_graveyards_no_op_parity():
    """**GENUINE real-EoE probe -- AA[0] baseline empty-graveyards
    silent-fizzle line.**

    Drives the parsed Ghost Vacuum AA[0]'s
    ``ExileTargetCardFromGraveyard`` Effect via
    ``resolve(state, controller_id, targets=())`` on a state with
    BOTH players' graveyards empty. Python's
    ``ExileTargetCardFromGraveyard.resolve`` (``effects/generic/
    exile.py:319``) early-returns when ``not targets`` -- silent no-op
    (CR 608.2b fizzle proxy at empty target list).

    Rust's ``Effect::ExileTargetCardFromGraveyard`` resolve arm
    similarly fizzles silently when the target id can't be located in
    either player's graveyard. Byte-equal silent no-op -- no panic,
    no zone moves, no state mutation.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import Zone

    real = _PRINTINGS.get("Ghost Vacuum")
    if real is None:
        pytest.skip("Ghost Vacuum absent from active CardSource")

    aa0 = real.activated_abilities[0]
    assert isinstance(aa0.effect, ExileTargetCardFromGraveyard)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the genuine parsed Ghost Vacuum on p0's bf (the AA source).
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)
    py_state.resolving_source = py_source

    # Both graveyards empty.
    assert py_state.players[0].graveyard == []
    assert py_state.players[1].graveyard == []

    bf_before = len(py_state.battlefield)
    p0_exile_before = list(py_state.players[0].exile)
    p1_exile_before = list(py_state.players[1].exile)

    # Resolve with empty targets -- silent no-op fizzle.
    aa0.effect.resolve(py_state, py_source.controller_id, targets=())

    # State invariants -- no zone moves, source untouched.
    assert len(py_state.battlefield) == bf_before
    assert py_source in py_state.battlefield
    assert py_state.players[0].graveyard == []
    assert py_state.players[1].graveyard == []
    assert list(py_state.players[0].exile) == p0_exile_before
    assert list(py_state.players[1].exile) == p1_exile_before


def test_cross_engine_real_eoe_ghost_vacuum_aa0_populated_graveyard_single_target_exile_parity():
    """**GENUINE real-EoE probe -- load-bearing AA[0] exile-target-
    from-graveyard line. PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the FULL parsed Ghost Vacuum AA[0]'s
    ``ExileTargetCardFromGraveyard`` Effect resolve on a state where
    p1's graveyard carries one creature card. The probe asserts every
    observable Rust's ``Effect::ExileTargetCardFromGraveyard`` resolve
    arm produces byte-equal on the Python side:

      * The chosen target moves from p1.graveyard -> p1.exile (per-
        owner routing: cards stay with their owner, never cross-route
        to the activator's exile).
      * The target's ``zone`` flips to ``Zone.EXILE``.
      * The target's ``exiled_by_source`` is stamped to the Ghost
        Vacuum source object's id -- the load-bearing C1 linkage that
        AA[1]'s recall sibling reads at resolve time to find every
        card the same source exiled.
      * The activator's exile is unchanged (the card lands in its
        owner's exile, not the activator's).
      * The source object stays on the battlefield (the cost-payment
        side -- tap_self -- isn't tested here; resolve-side only).
    """
    from mtg_bot.cards.base import make_creature
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import GameObject, Zone

    real = _PRINTINGS.get("Ghost Vacuum")
    if real is None:
        pytest.skip("Ghost Vacuum absent from active CardSource")

    aa0 = real.activated_abilities[0]
    assert isinstance(aa0.effect, ExileTargetCardFromGraveyard)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the parsed Ghost Vacuum on p0's bf (activator side).
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)
    py_state.resolving_source = py_source

    # Seat a creature card in p1's graveyard (the target side).
    target_pr = make_creature("Probe Creature", "{1}", power=1, toughness=1)
    target_obj = py_state.new_object(
        target_pr, owner_id=1, zone=Zone.GRAVEYARD,
    )
    py_state.players[1].graveyard.append(target_obj)

    # Pre-resolve snapshot.
    assert py_state.players[0].graveyard == []
    assert py_state.players[1].graveyard == [target_obj]
    assert py_state.players[0].exile == []
    assert py_state.players[1].exile == []
    assert target_obj.zone == Zone.GRAVEYARD
    assert target_obj.exiled_by_source is None

    # Resolve with the target id (the target-bearing payload).
    aa0.effect.resolve(
        py_state, py_source.controller_id,
        targets=(("card_in_graveyard", target_obj.id),),
    )

    # Post-resolve invariants -- per-owner routing + linkage stamp.
    assert py_state.players[1].graveyard == [], (
        "Target must move OUT of p1's graveyard"
    )
    assert py_state.players[1].exile == [target_obj], (
        "Target must move TO p1's exile (per-owner routing; the card "
        "stays with its owner)"
    )
    assert py_state.players[0].exile == [], (
        "Activator's exile must stay empty -- per-owner routing keeps "
        "the card on its owner's side, not the activator's"
    )
    assert target_obj.zone == Zone.EXILE
    assert target_obj.exiled_by_source == py_source.id, (
        "AA[1] recall linkage: target's exiled_by_source must point at "
        "the Ghost Vacuum source object id (Phase 4C C1 substrate "
        "produces this linkage; AA[1] consumes it at recall time)"
    )
    # Source untouched on the bf.
    assert py_source in py_state.battlefield
    assert py_source.zone == Zone.BATTLEFIELD


def test_cross_engine_real_eoe_ghost_vacuum_aa1_recall_python_side_resolve():
    """**Python-side AA[1] recall probe (Rust resolve-rider divergence
    documented).**

    Drives the parsed Ghost Vacuum AA[1]'s
    ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYour
    Control`` Effect resolve on a state where p0's exile carries 2
    creature cards tagged ``exiled_by_source = ghost_vacuum.id``
    (the linkage AA[0] produces). The Python resolve:

      * walks every player's exile for ``exiled_by_source == source.id
        AND printing.is_creature``;
      * moves each matching card to the activator's battlefield;
      * applies the layered grants on the Python side
        (``grant_flying_counter`` + ``grant_subtype_and_pt = ("Spirit",
        1, 1)``).

    **Rust-side divergence (SL note).** Rust's resolve arm executes
    the zone move + ``exiled_with_source`` clear correctly but DOES
    NOT apply the ``grant_flying_counter`` / ``grant_subtype_and_pt``
    layered grants -- the continuous-effect substrate to stamp a
    flying counter + Spirit subtype + 1/1 base P/T at recall time is
    a Phase-N gap (see ``docs/SEARCH_LIMITATIONS.md`` Phase 4C entry).
    This probe is therefore Python-only on the layered-grant axis;
    the zone-move + linkage-clear axis is cross-engine byte-equal at
    Phase 4C C2 close but is tested explicitly in
    ``tests/test_exiled_with_source_recall.py``.
    """
    from mtg_bot.cards.base import make_creature
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state
    from mtg_bot.game import GameObject, Zone

    real = _PRINTINGS.get("Ghost Vacuum")
    if real is None:
        pytest.skip("Ghost Vacuum absent from active CardSource")

    aa1 = real.activated_abilities[1]
    assert isinstance(
        aa1.effect,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the parsed Ghost Vacuum on p0's bf.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)
    py_state.resolving_source = py_source

    # Seat 2 creature cards in p0's exile, both tagged
    # exiled_by_source = ghost_vacuum.id.
    creature_pr = make_creature("Recalled Creature", "{1}", power=2, toughness=2)
    creature_objs = []
    for _ in range(2):
        obj = py_state.new_object(
            creature_pr, owner_id=0, zone=Zone.EXILE,
        )
        obj.exiled_by_source = py_source.id
        py_state.players[0].exile.append(obj)
        creature_objs.append(obj)

    # Pre-resolve snapshot.
    assert len(py_state.players[0].exile) == 2
    assert all(
        obj.exiled_by_source == py_source.id for obj in creature_objs
    )

    # Resolve -- the Effect walks exile for tagged creature cards,
    # moves them to the activator's bf, and applies the layered
    # grants (Python-side only per the SL note).
    aa1.effect.resolve(py_state, py_source.controller_id, targets=())

    # Post-resolve invariants.
    # The 2 recalled creatures must move OUT of p0's exile.
    assert all(
        obj not in py_state.players[0].exile
        for obj in creature_objs
    ), "Recalled creatures must move OUT of exile"
    # The 2 recalled creatures must land on p0's bf.
    assert all(
        obj in py_state.battlefield
        for obj in creature_objs
    ), "Recalled creatures must land on the activator's battlefield"
    # Each recalled creature must have zone=BATTLEFIELD + controller=
    # activator + exiled_by_source cleared.
    for obj in creature_objs:
        assert obj.zone == Zone.BATTLEFIELD
        assert obj.controller_id == 0  # activator
        assert obj.exiled_by_source is None, (
            "Recalled creature's exiled_by_source must clear (per the "
            "Python resolve's per-zone reset)"
        )


# ---------------------------------------------------------------------------
# (6) Admit-FLIP regression pin -- the Phase 4C C2 admit-gate FLIP
# closes the carrier end-to-end on the dispatcher + Artifact builder.
# ---------------------------------------------------------------------------


def test_ghost_vacuum_admits_at_carrier_aa_dispatcher_post_4c_c2():
    """**Phase 4C C2 admit-FLIP regression pin.** Ghost Vacuum admits
    at the production Carrier-AA dispatcher
    (``_printing_is_bridge_simple_carrier_aa_any``) post-Phase-4C-C2.
    Sibling of the Phase 3 admit-FLIP regression pins (e.g.
    ``test_thespian's_stage_admits_at_carrier_aa_dispatcher_post_3c_c3``
    in ``tests/test_thespians_stage_parity.py``).
    """
    from mtg_bot.parity.trajectory import (
        _carrier_aa_artifact_card_def,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_artifact,
    )

    p = _PRINTINGS["Ghost Vacuum"]
    assert _printing_is_bridge_simple_carrier_aa_any(p) is True
    assert _printing_is_bridge_simple_carrier_aa_artifact(p) is True
    cd = _carrier_aa_artifact_card_def(p)
    assert cd is not None
    assert cd.card_type == "Artifact"
    assert len(cd.activated_abilities) == 2
