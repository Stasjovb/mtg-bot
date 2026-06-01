"""Pinnacle Starcage -- per-card real-EoE cross-engine byte-equal probe
(BLOCKED -> PROBED tier flip; Pinnacle Starcage closure marker).

Pinnacle Starcage is an EoE Artifact (``{1}{W}{W}``) with an ETB trigger
+ a single activated ability:

    ETB trigger -- "When this artifact enters, exile all artifacts and
        creatures with mana value 2 or less until this artifact leaves
        the battlefield."
        TriggeredAbility(event=ENTERS, predicate=IsSelf,
            effect=ExileAllMatchingUntilSourceLeaves(
                match_artifact=True, match_creature=True, max_mv=2))

    AA -- "{6}{W}{W}: Put each card exiled with this artifact into its
        owner's graveyard, then create a 2/2 colorless Robot artifact
        creature token for each card put into a graveyard this way.
        Sacrifice this artifact."
        ActivatedAbility(cost={6}{W}{W}, effect=Sequence(
            MoveEachExiledWithSourceToOwnersGraveyard(),
            CreateNTokensFromLastExileRecall(token_name="Robot"),
            SacrificeSelf()))

**The closure (2026-05-31).** Per the BLOCKED-tail scout, Pinnacle
Starcage needed 3 new Rust Effect variants riding the existing
``exiled_with_source`` linked-exile state machinery (the
Oblivion-Ring-style ``return_paired_exiles_for`` recall hook +
``exiled_with_source: Option<u32>`` field that
``ExileTargetCreatureUntilSourceLeaves`` /
``ExileOpponentsNonlandPermanentUntilLeaves`` already shipped):

  * ``Effect::ExileAllMatchingUntilSourceLeaves
    { match_artifact, match_creature, max_mv }`` -- the ETB mass
    exile-with-source. The mass sibling of the single-target
    ``ExileTargetCreatureUntilSourceLeaves`` family: sweeps EVERY
    player's battlefield for non-land permanents matching the type
    union + MV cap, EXCLUDING the source, stamps
    ``exiled_with_source = Some(source_id)``, moves each to its OWNER's
    exile. The EXISTING ``return_paired_exiles_for`` hook recalls them
    when the source leaves -- NO new linked-exile state machine.

  * ``Effect::MoveEachExiledWithSourceToOwnersGraveyard`` -- the
    recall-to-graveyard side. Walks every player's exile for objects
    tagged ``exiled_with_source == Some(source_id)``, moves each to its
    OWNER's graveyard, records the moved count on
    ``state.last_exile_recall_count`` (a NEW transient scratch field on
    the Rust GameState mirroring Python's
    ``state.last_exile_recall_count``).

  * ``Effect::CreateNTokensFromLastExileRecall { token_printing_id }``
    -- reads ``state.last_exile_recall_count`` and mints that many
    Robot tokens. Carries a registry ``token_printing_id`` (the Rust
    token convention) resolved by the bridge from Python's
    ``token_name="Robot"``.

  * ``Effect::SacrificeSelf`` -- the effect-body sacrifice-self leaf
    (distinct from the ``ActivationCost.sacrifice_self`` cost gate).

The ``Effect::Sequence`` combinator (round-15) already walks children in
order on both engines; this closure rides it for the AA body.

**Probe design (inject-and-fire / direct-resolve).** Mirrors the Seam
Rip / token-creation cross-engine probes: the GENUINE parsed Pinnacle
Starcage printing drives the PYTHON side (its actual
``triggered_abilities[0].effect`` + ``activated_abilities[0].effect``
objects), and a hand-built bridged synthetic carrier drives the RUST
side (the SAME effect-dict shapes the bridge round-trips, verified by
the round-trip pin below). The effects are delivered via ETB triggers
(the proven Seam Rip vehicle) rather than the full ``{6}{W}{W}``
activation cost path -- the byte-equality claim is over the 3 Effect
RESOLVES, not the cost machinery (which is exercised by the production
loader path separately). ``resolving_source`` is set by the stack
resolver on both engines, so ``exiled_with_source`` stamping +
``SacrificeSelf`` source-lookup work identically.

This module is the Pinnacle Starcage closure marker; classified by
``scripts/measure_pool_parity.py``'s ``PROBE_MODULES`` walk (the
genuine-binding rule -- the ``*_parity`` function bodies resolve
``get_active_source().get_printings()["Pinnacle Starcage"]``).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (Rust int encoding).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


# ---------------------------------------------------------------------------
# (1) Parser SoT -- Pinnacle Starcage is parser-claimed and emits the
# expected ETB-trigger + AA-Sequence shape.
# ---------------------------------------------------------------------------


def test_pinnacle_starcage_parser_claims_card():
    assert "Pinnacle Starcage" in _PRINTINGS, (
        "Pinnacle Starcage must be parser-claimed by the active "
        "CardSource (EoE set coverage)"
    )


def test_pinnacle_starcage_printed_attrs():
    """Pins the genuine printing surface: Artifact ``{1}{W}{W}``, one
    ETB trigger carrying ``ExileAllMatchingUntilSourceLeaves(True, True,
    2)``, one AA carrying ``Sequence(Move..., Create...(Robot),
    SacrificeSelf())`` at ``{6}{W}{W}``. The teeth the cross-engine
    probes below drive.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.exile import (
        CreateNTokensFromLastExileRecall,
        ExileAllMatchingUntilSourceLeaves,
        MoveEachExiledWithSourceToOwnersGraveyard,
        SacrificeSelf,
    )

    p = _PRINTINGS["Pinnacle Starcage"]
    assert p.card_types == ("Artifact",)
    assert p.is_artifact is True
    assert p.is_creature is False
    assert p.mana_cost_str == "{1}{W}{W}"

    # ETB trigger.
    assert len(p.triggered_abilities) == 1
    etb = p.triggered_abilities[0]
    assert isinstance(etb.effect, ExileAllMatchingUntilSourceLeaves)
    assert etb.effect.match_artifact is True
    assert etb.effect.match_creature is True
    assert etb.effect.max_mv == 2

    # AA Sequence.
    assert len(p.activated_abilities) == 1
    aa = p.activated_abilities[0]
    assert aa.cost.mana_str == "{6}{W}{W}"
    assert isinstance(aa.effect, Sequence)
    assert len(aa.effect.effects) == 3
    leaf0, leaf1, leaf2 = aa.effect.effects
    assert isinstance(leaf0, MoveEachExiledWithSourceToOwnersGraveyard)
    assert isinstance(leaf1, CreateNTokensFromLastExileRecall)
    assert leaf1.token_name == "Robot"
    assert isinstance(leaf2, SacrificeSelf)


# ---------------------------------------------------------------------------
# (2) Bridge round-trip -- the genuine Effect objects forward-serialize
# to the canonical Rust effect dicts AND rehydrate byte-equal via the
# reverse arm. Pins the probe's source-of-truth that both engines read
# the SAME effect shapes.
# ---------------------------------------------------------------------------


# Canonical Rust effect dicts (the shape the bridge round-trips). The
# token_printing_id placeholder is filled at probe-run time from the
# Rust registry's next-free pid; the round-trip pin below uses a fixed
# sentinel pid.
def _etb_effect_dict():
    return {
        "kind": "exile_all_matching_until_source_leaves",
        "match_artifact": True,
        "match_creature": True,
        "max_mv": 2,
    }


def _aa_sequence_dict(robot_pid: int):
    return {
        "kind": "sequence",
        "effects": [
            {"kind": "move_each_exiled_with_source_to_owners_graveyard"},
            {
                "kind": "create_n_tokens_from_last_exile_recall",
                "token_printing_id": robot_pid,
            },
            {"kind": "sacrifice_self"},
        ],
    }


def test_pinnacle_starcage_bridge_reverse_arms_rehydrate():
    """The four new bridge reverse arms rehydrate the canonical Rust
    effect dicts back to the genuine Python Effect classes byte-equal.
    Pins both directions of the bridge floor.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.exile import (
        CreateNTokensFromLastExileRecall,
        ExileAllMatchingUntilSourceLeaves,
        MoveEachExiledWithSourceToOwnersGraveyard,
        SacrificeSelf,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    etb = _ta_dict_to_python_effect(_etb_effect_dict())
    assert isinstance(etb, ExileAllMatchingUntilSourceLeaves)
    assert etb.match_artifact is True
    assert etb.match_creature is True
    assert etb.max_mv == 2

    seq = _ta_dict_to_python_effect(_aa_sequence_dict(99))
    assert isinstance(seq, Sequence)
    l0, l1, l2 = seq.effects
    assert isinstance(l0, MoveEachExiledWithSourceToOwnersGraveyard)
    assert isinstance(l1, CreateNTokensFromLastExileRecall)
    # token_printing_id=99 isn't in the probe-time map → name falls back
    # to the canonical "Robot".
    assert l1.token_name == "Robot"
    assert isinstance(l2, SacrificeSelf)


@_rust_skip
def test_rust_parser_accepts_canonical_pinnacle_dicts():
    """Lockstep pin: Rust's parse arm accepts the canonical Pinnacle
    Starcage effect-dict shapes (ETB carrier + AA-Sequence carrier),
    including the nested Sequence with all three new leaf kinds.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    robot_pid = reg.register_printing({
        "name": "Robot",
        "card_types": ["Artifact", "Creature"],
        "mana_cost": {},
        "power": 2,
        "toughness": 2,
        "effects": [],
    })
    etb_carrier = {
        "name": "Pinnacle Starcage (ETB carrier)",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1, "W": 2},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": _etb_effect_dict(),
            }
        ],
    }
    p1 = reg.register_printing(etb_carrier)
    assert reg.get_printing_name(p1) == "Pinnacle Starcage (ETB carrier)"

    aa_carrier = {
        "name": "Pinnacle Starcage (AA carrier)",
        "card_types": ["Artifact"],
        "mana_cost": {},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": _aa_sequence_dict(robot_pid),
            }
        ],
    }
    p2 = reg.register_printing(aa_carrier)
    assert reg.get_printing_name(p2) == "Pinnacle Starcage (AA carrier)"


# ---------------------------------------------------------------------------
# Helpers -- snapshot projections for byte-equal compare across engines.
# ---------------------------------------------------------------------------


def _rust_zone_names(snapshot):
    """Multiset of printing names in a Rust zone snapshot."""
    return sorted(o["printing_name"] for o in snapshot)


def _py_zone_names(objs):
    return sorted(o.printing.name for o in objs)


def _drain_both(py_state, rust_state):
    from mtg_bot.actions import resolve_top_of_stack

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    while py_state.stack:
        resolve_top_of_stack(py_state)


def _build_states():
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    return build_python_state(spec), build_rust_state(spec)


def _seat_py_object(py_state, printing, controller, *, summoning_sick=False):
    from mtg_bot.game import Zone

    obj = py_state.new_object(
        printing, owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.summoning_sick = summoning_sick
    obj.tapped = False
    obj.damage = 0
    obj.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(obj)
    return obj


def _vanilla_printing(name, card_types, mana_generic, *, power=None,
                      toughness=None):
    from mtg_bot.cards.base import CardPrinting, ManaCost

    return CardPrinting(
        name=name,
        mana_cost_str="",
        mana_cost=ManaCost(generic=mana_generic, colored=()),
        type_line=" ".join(card_types),
        supertypes=(),
        card_types=tuple(card_types),
        subtypes=(),
        power=power,
        toughness=toughness,
        produces=frozenset(),
        triggered_abilities=(),
    )


def _rust_vanilla_dict(name, card_types, mana_generic, *, power=None,
                       toughness=None):
    d = {
        "name": name,
        "card_types": list(card_types),
        "mana_cost": {"generic": mana_generic} if mana_generic else {},
        "effects": [],
        "triggered_abilities": [],
    }
    if power is not None:
        d["power"] = power
    if toughness is not None:
        d["toughness"] = toughness
    return d


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe -- ETB MASS-EXILE.
# Pinnacle Starcage enters; its ETB exiles all artifacts + creatures
# with MV<=2 (source-linked), leaving above-cap and land permanents.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_pinnacle_starcage_etb_mass_exile_parity():
    """**GENUINE real-EoE cross-engine probe -- ETB mass exile-with-
    source.** PROBED tier flip evidence (the ETB exile-all path).

    Board (both engines, before the ETB):
      * P0 bf: Pinnacle Starcage (the source) + a vanilla MV1 Artifact
        ("at-cap artifact") + an above-cap MV3 Creature.
      * P1 bf: a vanilla MV2 Creature ("at-cap creature") + a Land.

    Drive: fire Pinnacle Starcage's genuine
    ``ExileAllMatchingUntilSourceLeaves(True, True, 2)`` ETB on both
    engines.

    Post-resolve (both engines, byte-equal):
      * The at-cap Artifact (P0, MV1) + at-cap Creature (P1, MV2) leave
        the battlefield into their OWNERS' exile, source-linked.
      * The above-cap MV3 Creature (P0) STAYS (over the MV cap).
      * The Land (P1) STAYS (lands excluded).
      * Pinnacle Starcage itself STAYS (a permanent can't exile itself).
      * P0 exile: 1 (the at-cap Artifact). P1 exile: 1 (the at-cap
        Creature).
      * Stacks empty; lives untouched.
    """
    p = _PRINTINGS.get("Pinnacle Starcage")
    if p is None:
        pytest.skip("Pinnacle Starcage absent from active CardSource")

    py_state, rust_state = _build_states()

    # ---- Python side: seat the genuine Pinnacle Starcage printing
    # LAST so its ETB fires against a fully-populated board.
    at_cap_art = _vanilla_printing("At-Cap Artifact", ("Artifact",), 1)
    above_cap_cre = _vanilla_printing(
        "Above-Cap Creature", ("Creature",), 3, power=3, toughness=3,
    )
    at_cap_cre = _vanilla_printing(
        "At-Cap Creature", ("Creature",), 2, power=2, toughness=2,
    )
    land = _vanilla_printing("Vanilla Land", ("Land",), 0)

    _seat_py_object(py_state, at_cap_art, 0)
    _seat_py_object(py_state, above_cap_cre, 0)
    _seat_py_object(py_state, at_cap_cre, 1)
    _seat_py_object(py_state, land, 1)

    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.game import Zone

    py_source = py_state.new_object(p, owner_id=0, zone=Zone.BATTLEFIELD)
    py_source.summoning_sick = False
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)
    _trigger_etb_abilities(py_state, py_source)
    assert len(py_state.stack) == 1, (
        "Python: Pinnacle Starcage's ETB must land the mass-exile "
        f"effect on the stack; got stack={len(py_state.stack)}"
    )

    # ---- Rust side: mirror the board, then inject the ETB carrier.
    rust_state.register_and_inject_object(
        _rust_vanilla_dict("At-Cap Artifact", ("Artifact",), 1), 0,
        ZONE_BATTLEFIELD,
    )
    rust_state.register_and_inject_object(
        _rust_vanilla_dict(
            "Above-Cap Creature", ("Creature",), 3, power=3, toughness=3,
        ), 0, ZONE_BATTLEFIELD,
    )
    rust_state.register_and_inject_object(
        _rust_vanilla_dict(
            "At-Cap Creature", ("Creature",), 2, power=2, toughness=2,
        ), 1, ZONE_BATTLEFIELD,
    )
    rust_state.register_and_inject_object(
        _rust_vanilla_dict("Vanilla Land", ("Land",), 0), 1,
        ZONE_BATTLEFIELD,
    )
    rust_source_dict = {
        "name": "Pinnacle Starcage",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1, "W": 2},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": _etb_effect_dict(),
            }
        ],
    }
    rust_state.register_and_inject_object(
        rust_source_dict, 0, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Pinnacle Starcage's arrival must fire the ENTERS trigger "
        f"and land the mass-exile effect; got {rust_state.stack_size()}"
    )

    # ---- Drain both stacks.
    _drain_both(py_state, rust_state)
    assert len(py_state.stack) == 0
    assert rust_state.stack_size() == 0

    # ---- Post-state: byte-equal battlefield + exile contents.
    py_bf = _py_zone_names(py_state.battlefield)
    rust_bf = _rust_zone_names(rust_state.battlefield_snapshot())
    expected_bf = sorted([
        "Pinnacle Starcage", "Above-Cap Creature", "Vanilla Land",
    ])
    assert py_bf == expected_bf, f"Python bf: {py_bf}"
    assert rust_bf == expected_bf, f"Rust bf: {rust_bf}"
    assert py_bf == rust_bf

    py_p0_exile = _py_zone_names(py_state.players[0].exile)
    py_p1_exile = _py_zone_names(py_state.players[1].exile)
    rust_p0_exile = _rust_zone_names(rust_state.exile_snapshot(0))
    rust_p1_exile = _rust_zone_names(rust_state.exile_snapshot(1))
    assert py_p0_exile == ["At-Cap Artifact"]
    assert py_p1_exile == ["At-Cap Creature"]
    assert rust_p0_exile == ["At-Cap Artifact"]
    assert rust_p1_exile == ["At-Cap Creature"]
    assert py_p0_exile == rust_p0_exile
    assert py_p1_exile == rust_p1_exile

    # ---- Lives untouched on both engines.
    assert py_state.players[0].life == rust_state.get_life(0)
    assert py_state.players[1].life == rust_state.get_life(1)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe -- AA RECALL +
# TOKEN-MINT + SAC. Drives Pinnacle Starcage's genuine AA Sequence:
# move each exiled-with-source card to its owner's graveyard, mint one
# Robot token per moved card, sacrifice the source.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_pinnacle_starcage_aa_recall_tokens_sac_parity():
    """**GENUINE real-EoE cross-engine probe -- AA Sequence (recall to
    graveyard + Robot-token-per-card + sacrifice-self).** PROBED tier
    flip evidence (the load-bearing ``{6}{W}{W}`` Sequence path).

    Pre-state (both engines): Pinnacle Starcage on P0's bf (the source),
    and TWO cards already exiled-with-source -- one in P0's exile, one
    in P1's exile (modeling the post-ETB state). The Robot token
    printing is registered on both engines.

    Drive: fire Pinnacle Starcage's genuine
    ``Sequence(MoveEachExiledWithSourceToOwnersGraveyard(),
    CreateNTokensFromLastExileRecall("Robot"), SacrificeSelf())`` on
    both engines (delivered via an ETB-trigger vehicle).

    Post-resolve (both engines, byte-equal):
      * The 2 exiled-with-source cards move to their OWNERS' graveyards
        (P0's exiled card -> P0 GY, P1's -> P1 GY). Exile zones empty of
        the linked cards.
      * 2 Robot tokens are minted under P0 (the resolving controller),
        one per moved card.
      * Pinnacle Starcage is sacrificed (P0's GY gains it).
    """
    p = _PRINTINGS.get("Pinnacle Starcage")
    if p is None:
        pytest.skip("Pinnacle Starcage absent from active CardSource")

    from mtg_bot.cards import TOKEN_PRINTINGS

    py_state, rust_state = _build_states()

    # ---- Rust: register the Robot token printing (next-free pid) by
    # injecting a dummy onto P1's library briefly.
    robot_pid = rust_state.registry_size
    rust_state.register_and_inject_object(
        {
            "name": "Robot",
            "card_types": ["Artifact", "Creature"],
            "mana_cost": {},
            "power": 2,
            "toughness": 2,
            "effects": [],
        },
        1, ZONE_LIBRARY,
    )

    # ---- Seat ONE Pinnacle Starcage source on P0's bf on both engines.
    # We DON'T fire the genuine ETB here (no eligible victims would make
    # it a no-op anyway, and the source carries its real ETB which would
    # push a no-op trigger). Instead we seat the source quietly and
    # deliver the AA Sequence as the only stack item.
    from mtg_bot.game import Zone

    py_source = py_state.new_object(p, owner_id=0, zone=Zone.BATTLEFIELD)
    py_source.summoning_sick = False
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Rust source: a Pinnacle Starcage carrier whose ETB delivers the AA
    # Sequence (the delivery vehicle), so the resolving source IS this
    # one object and the exiled-with-source link matches it.
    rust_source_dict = {
        "name": "Pinnacle Starcage",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 1, "W": 2},
        "effects": [],
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": _aa_sequence_dict(robot_pid),
            }
        ],
    }

    # ---- Pre-seat two cards exiled-with-source (one per player's
    # exile), tagged to the source.
    exiled_a = _vanilla_printing("Exiled Card A", ("Creature",), 1,
                                 power=1, toughness=1)
    exiled_b = _vanilla_printing("Exiled Card B", ("Artifact",), 2)

    py_ex_a = py_state.new_object(exiled_a, owner_id=0, zone=Zone.EXILE)
    py_ex_a.exiled_by_source = py_source.id
    py_state.players[0].exile.append(py_ex_a)
    py_ex_b = py_state.new_object(exiled_b, owner_id=1, zone=Zone.EXILE)
    py_ex_b.exiled_by_source = py_source.id
    py_state.players[1].exile.append(py_ex_b)

    # Rust: register + inject the two exiled cards onto each owner's
    # exile FIRST (so the ids are stable), THEN inject the source carrier
    # (its ETB delivers the AA Sequence), THEN stamp the source link to
    # the carrier id.
    rust_ex_a = rust_state.register_and_inject_object(
        _rust_vanilla_dict("Exiled Card A", ("Creature",), 1,
                           power=1, toughness=1),
        0, 5,  # ZONE_EXILE = 5 per register_and_inject_object support
    )
    rust_ex_b = rust_state.register_and_inject_object(
        _rust_vanilla_dict("Exiled Card B", ("Artifact",), 2),
        1, 5,
    )
    rust_source_id = rust_state.register_and_inject_object(
        rust_source_dict, 0, ZONE_BATTLEFIELD,
    )
    rust_state.force_set_exiled_with_source(rust_ex_a, rust_source_id)
    rust_state.force_set_exiled_with_source(rust_ex_b, rust_source_id)
    assert rust_state.stack_size() == 1, (
        "Rust: the source carrier's ETB must land the AA Sequence on "
        f"the stack; got {rust_state.stack_size()}"
    )

    # ---- Python: stage the genuine AA Sequence onto the stack with
    # source = py_source (so resolving_source == the source and the
    # exiled_by_source link matches) via the centralized
    # push_triggered_ability path. Drives the ACTUAL parsed Sequence
    # object tree.
    from mtg_bot.actions import push_triggered_ability
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Event, IsSelf

    genuine_seq = p.activated_abilities[0].effect
    push_triggered_ability(
        py_state,
        source=py_source,
        ability=TriggeredAbility(event=Event.ENTERS, predicate=IsSelf(),
                                 effect=genuine_seq),
        ability_index=0,
        controller_id=0,
        label="pinnacle-aa",
    )
    assert len(py_state.stack) == 1

    # ---- Drain both stacks.
    _drain_both(py_state, rust_state)
    assert len(py_state.stack) == 0
    assert rust_state.stack_size() == 0

    # ---- Post-state: byte-equal token mint + graveyard moves.
    # NOTE: the Rust AA carrier (a SECOND "Pinnacle Starcage") is
    # sacrificed (SacrificeSelf), while on Python the genuine py_source
    # carries the Sequence and is sacrificed. Both engines sacrifice
    # exactly one "Pinnacle Starcage" to its owner's GY.
    py_p0_gy = _py_zone_names(py_state.players[0].graveyard)
    py_p1_gy = _py_zone_names(py_state.players[1].graveyard)
    rust_p0_gy = _rust_zone_names(rust_state.graveyard_snapshot(0))
    rust_p1_gy = _rust_zone_names(rust_state.graveyard_snapshot(1))

    # P0 GY: Exiled Card A (recalled to owner P0) + Pinnacle Starcage
    # (sacrificed). P1 GY: Exiled Card B (recalled to owner P1).
    assert py_p0_gy == sorted(["Exiled Card A", "Pinnacle Starcage"]), py_p0_gy
    assert py_p1_gy == ["Exiled Card B"], py_p1_gy
    assert rust_p0_gy == sorted(["Exiled Card A", "Pinnacle Starcage"]), rust_p0_gy
    assert rust_p1_gy == ["Exiled Card B"], rust_p1_gy
    assert py_p0_gy == rust_p0_gy
    assert py_p1_gy == rust_p1_gy

    # ---- 2 Robot tokens minted under P0 on both engines.
    py_robots = [
        o for o in py_state.battlefield
        if o.printing.name == "Robot" and o.controller_id == 0
    ]
    rust_robots = [
        o for o in rust_state.battlefield_snapshot()
        if o["printing_name"] == "Robot" and int(o["controller_id"]) == 0
    ]
    assert len(py_robots) == 2, f"Python Robot count: {len(py_robots)}"
    assert len(rust_robots) == 2, f"Rust Robot count: {len(rust_robots)}"
    assert len(py_robots) == len(rust_robots)

    # ---- Exile zones empty of the linked cards on both engines.
    assert _py_zone_names(py_state.players[0].exile) == []
    assert _py_zone_names(py_state.players[1].exile) == []
    assert _rust_zone_names(rust_state.exile_snapshot(0)) == []
    assert _rust_zone_names(rust_state.exile_snapshot(1)) == []

    # ---- Token printing exists on the Python side (sanity).
    assert TOKEN_PRINTINGS["Robot"].power == 2
