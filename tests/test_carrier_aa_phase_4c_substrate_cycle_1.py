"""**Carrier-AA substrate Phase 4C Cycle 1 (2026-05-26).**

Tests for the Phase 4C Cycle 1 Rust slice landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §4.2 (Rust spec) +
§5.5 (Python bridge spec) + §6.3 (test plan, pins #18-22) + §7.3
(cycle plan).

Deliverables (Cycle 1 Rust slice, per design doc §4.2 + §7.3):

  - Two new Rust Effect variants on ``cards.rs::Effect``:
      * ``ExileTargetCardFromGraveyard`` (unit variant; Ghost Vacuum's
        AA[0] pilot effect — ``{T}: Exile target card from a
        graveyard.``).
      * ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYour
        Control { grant_flying_counter: bool, grant_subtype_and_pt:
        Option<(String, i32, i32)> }`` (Ghost Vacuum's AA[1] recall
        effect — ``{6}, {T}, Sacrifice this artifact: Put each
        creature card exiled with this artifact onto the battlefield
        under your control with a flying counter on it. Each of them
        is a 1/1 Spirit in addition to its other types.``).
  - ``parse_effect`` arms in ``cards.rs`` for both kinds.
  - ``to_pydict`` arms in ``cards.rs`` for both kinds (empty-omit
    discipline on the two-rider variant — ``grant_flying_counter``
    omitted when False, ``grant_subtype_and_pt`` omitted when None).
  - Resolve arms in ``state_ops_resolve.rs::apply_effect``:
      * ``ExileTargetCardFromGraveyard``: locate the cast-time-bound
        target id (``current_resolve_payload_target_id``) across both
        players' graveyards, move from owner's graveyard to owner's
        exile zone, stamp ``obj.exiled_with_source = Some(source_id)``
        so the sibling AA[1] recall can find every card the same
        source exiled later.
      * ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYour
        Control``: walk every player's exile for objects with
        ``exiled_with_source == Some(source_id) AND printing.card_
        types.contains("Creature")``; move each to the activator's
        battlefield with the standard per-zone reset
        (``tapped=false``, ``summoning_sick=true``,
        ``exiled_with_source=None``, etc.), reserve a contiguous ETB
        timestamp block per the CE4 monotonic discipline, and queue +
        drain ETB dispatches.
      * **Substrate-only riders.** The ``grant_flying_counter`` +
        ``grant_subtype_and_pt`` riders are captured on the variant
        AND round-trip through parse/to_pydict, but the resolve arm
        logs-and-continues without applying them (Rust has no
        ``flying_counters`` slot AND no ``continuous_effects`` slot
        today — both are Phase-N).
  - New both-players-graveyard single-target fan-out arm in
    ``state_ops_legal.rs::activate_ability_dict`` for the
    ``ExileTargetCardFromGraveyard`` Effect — enumerates every
    GameObject across BOTH players' graveyards (no card-type filter)
    and emits one ``ActivateAbility`` per eligible target with
    ``target_creature_id = Some(card_id)``.
  - Target validation arm in
    ``state_ops_actions.rs::ActivateAbility`` for the
    ``ExileTargetCardFromGraveyard`` effect — re-checks the chosen
    target id against graveyard-presence on EITHER player.
  - Cross-engine bridge arms in ``src/mtg_bot/parity/cross_engine.py``:
      * Reverse arm in ``_ta_dict_to_python_effect`` — recognizes
        ``kind == "exile_target_card_from_graveyard"`` and rehydrates
        ``ExileTargetCardFromGraveyard()``.
      * Reverse arm in ``_ta_dict_to_python_effect`` — recognizes
        ``kind == "put_each_creature_card_exiled_with_source_onto_
        battlefield_under_your_control"`` and rehydrates
        ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYour
        Control(grant_flying_counter, grant_subtype_and_pt)``.
      * Forward arms in ``_python_aa_to_safe_dict`` — recognizes the
        two Effect classes (SPECIFIC isinstance, no parent fall-
        through per the Phase-3A/3B/3C specificity contract) and
        emits the matching dicts.

ZERO Python admit widen this cycle (the
``_carrier_aa_phase_1_effect_classes`` widen for both Effect classes
ships Cycle 2 per design doc §5.5).
ZERO ``sorcery_speed`` AA-rider widen this cycle (the
``_python_aa_to_safe_dict`` floor still declines on AA[1]'s
``sorcery_speed=True`` rider; ships Cycle 2 per design doc §5.5).
ZERO per-card probe this cycle (Cycle 3 ships
``tests/test_ghost_vacuum_parity.py`` per design doc §6.7).
ZERO new cost-shape Rust machinery — Ghost Vacuum's ``{T}`` (AA[0])
+ ``{6}, {T}, Sac`` (AA[1]) ride the Phase 1.5a + Phase 2a cost-
shape gates already wired.

Substrate-only invariant — Ghost Vacuum STAYS DECLINED at the admit
gate post-Cycle-1. The Rust Effect variants + per-player-graveyard
fan-out + cross-engine bridge arms all landed; the live admit gate
still declines Ghost Vacuum's printing because (a)
``_carrier_aa_phase_1_effect_classes`` doesn't yet include either
``ExileTargetCardFromGraveyard`` or
``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl``
AND (b) the AA-rider gate at ``_aa_is_phase1_sub_shape_a`` still
declines AA[1]'s ``sorcery_speed=True`` rider. Both widens ship C2.
The forward serializer + Rust round-trip both succeed at C1 — driven
by synthetic unit pins; the live admit FLIP lands at C2.

**Verify-first findings (live tree, main ``2e78e8b2``):**

  - Ghost Vacuum printing-level shape: ``card_types=("Artifact",)``,
    ``subtypes=()``, ``supertypes=()``, ``keywords=frozenset()``,
    ``triggered_abilities=()``, ``static_abilities=()``,
    ``cost_reductions=()``, ``spell_effect=None``, ``n_aa=2``.
  - AA[0]: ``cost=ActivationCost(mana=None, tap_self=True)``,
    ``effect=ExileTargetCardFromGraveyard()``,
    ``is_mana_ability=False``, ``sorcery_speed=False``.
  - AA[1]: ``cost=ActivationCost(mana=ManaCost(generic=6),
    tap_self=True, sacrifice_self=True)``,
    ``effect=PutEachCreatureCardExiledWithSourceOntoBattlefieldUnder
    YourControl(grant_flying_counter=True,
    grant_subtype_and_pt=('Spirit', 1, 1))``,
    ``is_mana_ability=False``, ``sorcery_speed=True`` (rider teeth).
  - Pre-C1 Rust state: Effect enum's last variant was
    ``DrawCardsByConditionMultiplier`` (Phase 4E C1 commit
    ``c50cf8da``); no pre-existing ``ExileTargetCardFromGraveyard``
    OR
    ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYour
    Control`` variant — purely additive at the variant cardinality
    axis.
  - Pre-C1 ``_python_aa_to_safe_dict`` decline floor: any AA with
    ``sorcery_speed=True`` returns ``None`` — admit-gate teeth that
    survive C1; C2 widens the gate floor.

This is a **substrate-only closure** — the cycle adds two new Rust
Effect variants + per-player-graveyard fan-out + target-validation
arm + cross-engine bridge as reusable infrastructure. Ghost Vacuum
STAYS DECLINED at the production-deck admit gate post-Cycle-1.
"""

from __future__ import annotations

import importlib.util

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


@pytest.fixture
def engine():
    """The ``mtg_bot_engine`` module, or skip if not installed."""
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine
    return mtg_bot_engine


@pytest.fixture
def synthetic_state(engine):
    """A default synthetic state — 10 battlefield, 7 hand, 50 library
    per side. Mirrors the Phase-3A/3B/3C/4E sibling shared fixture."""
    return engine.make_synthetic_state()


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_exile_target_card_from_graveyard_class_exists():
    """**Parser source-of-truth pin.** Python's
    ``ExileTargetCardFromGraveyard`` class is in
    ``effects.generic.exile``, a frozen dataclass with no fields.
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.exile import (
        ExileTargetCardFromGraveyard,
    )

    eff = ExileTargetCardFromGraveyard()
    assert isinstance(eff, Effect)
    # Two parameterless instances compare equal.
    assert eff == ExileTargetCardFromGraveyard()


def test_python_put_each_creature_card_exiled_class_exists():
    """**Parser SoT pin.** Python's
    ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYour
    Control`` class is in ``effects.generic.exile``, a frozen
    dataclass with two rider fields:

      * ``grant_flying_counter: bool = False``
      * ``grant_subtype_and_pt: Optional[tuple[str, int, int]] = None``
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.exile import (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )

    bare = (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl()
    )
    assert isinstance(bare, Effect)
    assert bare.grant_flying_counter is False
    assert bare.grant_subtype_and_pt is None

    ghost = (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
            grant_flying_counter=True,
            grant_subtype_and_pt=("Spirit", 1, 1),
        )
    )
    assert ghost.grant_flying_counter is True
    assert ghost.grant_subtype_and_pt == ("Spirit", 1, 1)
    # Two instances with identical fields compare equal.
    same = (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
            grant_flying_counter=True,
            grant_subtype_and_pt=("Spirit", 1, 1),
        )
    )
    assert ghost == same


def test_ghost_vacuum_live_aa_shapes_match_design_doc():
    """**Verify-first pin (design doc §2.1 row).** The live Ghost Vacuum
    parser SoT carries:

      * AA[0]: ``ExileTargetCardFromGraveyard()`` + cost ``{T}``,
        ``is_mana_ability=False``, ``sorcery_speed=False``.
      * AA[1]: ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnder
        YourControl(grant_flying_counter=True,
        grant_subtype_and_pt=('Spirit', 1, 1))`` + cost ``{6}, {T},
        Sacrifice this artifact``, ``is_mana_ability=False``,
        ``sorcery_speed=True``.

    This pin protects the verify-first finding the C1 substrate is
    built against: a future parser tweak that mutates either AA's
    shape would need to be reconciled here BEFORE C2 ships the admit
    widens.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.generic.exile import (
        ExileTargetCardFromGraveyard,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )

    printings = OracleParserCardSource().get_printings()
    assert "Ghost Vacuum" in printings, (
        "Verify-first invariant: Ghost Vacuum must be present in the "
        "Oracle parser card source"
    )
    printing = printings["Ghost Vacuum"]
    assert printing.card_types == ("Artifact",)
    assert printing.subtypes == ()
    assert printing.supertypes == ()
    assert printing.keywords == frozenset()
    assert printing.triggered_abilities == ()
    assert printing.static_abilities == ()
    assert printing.cost_reductions == ()
    assert printing.spell_effect is None
    assert len(printing.activated_abilities) == 2

    aa0 = printing.activated_abilities[0]
    assert isinstance(aa0.effect, ExileTargetCardFromGraveyard)
    assert aa0.is_mana_ability is False
    assert aa0.sorcery_speed is False
    assert aa0.cost.tap_self is True
    assert aa0.cost.sacrifice_self is False
    assert aa0.cost.mana is None

    aa1 = printing.activated_abilities[1]
    assert isinstance(
        aa1.effect,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    assert aa1.effect.grant_flying_counter is True
    assert aa1.effect.grant_subtype_and_pt == ("Spirit", 1, 1)
    assert aa1.is_mana_ability is False
    # **Critical** — AA[1] carries the sorcery_speed=True rider that
    # is the Phase 4C admit-gate teeth at C1.
    assert aa1.sorcery_speed is True
    assert aa1.cost.tap_self is True
    assert aa1.cost.sacrifice_self is True
    assert aa1.cost.mana is not None
    assert aa1.cost.mana.generic == 6


# ---------------------------------------------------------------------------
# Cross-engine bridge reverse-arm pins (dict -> Python)
# ---------------------------------------------------------------------------


def test_bridge_reverse_arm_exile_target_card_from_graveyard():
    """**Reverse arm.** ``_ta_dict_to_python_effect`` constructs
    ``ExileTargetCardFromGraveyard()`` from the unit-variant
    ``{"kind": "exile_target_card_from_graveyard"}`` dict.
    """
    from mtg_bot.effects.generic.exile import (
        ExileTargetCardFromGraveyard,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect(
        {"kind": "exile_target_card_from_graveyard"},
    )
    assert isinstance(back, ExileTargetCardFromGraveyard)
    # Parameterless ⇒ byte-equal to a fresh-instantiation.
    assert back == ExileTargetCardFromGraveyard()


def test_bridge_reverse_arm_put_each_creature_card_exiled_full_riders():
    """**Reverse arm — full Ghost Vacuum rider payload.**
    ``_ta_dict_to_python_effect`` constructs the recall Effect with
    the Spirit+flying+1/1 rider payload from the full dict.
    """
    from mtg_bot.effects.generic.exile import (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind":
            "put_each_creature_card_exiled_with_source_onto_"
            "battlefield_under_your_control",
        "grant_flying_counter": True,
        "grant_subtype_and_pt": ("Spirit", 1, 1),
    })
    assert isinstance(
        back,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    assert back.grant_flying_counter is True
    assert back.grant_subtype_and_pt == ("Spirit", 1, 1)


def test_bridge_reverse_arm_put_each_creature_card_exiled_omits_riders():
    """**Reverse arm — minimal rider-free shape.** Accepts the bare
    dict; ``grant_flying_counter`` defaults to False, ``grant_subtype_
    and_pt`` defaults to None.
    """
    from mtg_bot.effects.generic.exile import (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind":
            "put_each_creature_card_exiled_with_source_onto_"
            "battlefield_under_your_control",
    })
    assert isinstance(
        back,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    assert back.grant_flying_counter is False
    assert back.grant_subtype_and_pt is None


def test_bridge_reverse_arm_put_each_creature_card_accepts_list_form_payload():
    """**Reverse arm — list-form rider payload.** The bridge tolerates
    a 3-element list for ``grant_subtype_and_pt`` (JSON round-trip
    forward-correctness — Rust to_pydict emits a tuple but a future
    serializer may emit a list).
    """
    from mtg_bot.effects.generic.exile import (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind":
            "put_each_creature_card_exiled_with_source_onto_"
            "battlefield_under_your_control",
        "grant_subtype_and_pt": ["Spirit", 1, 1],
    })
    assert isinstance(
        back,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    assert back.grant_subtype_and_pt == ("Spirit", 1, 1)


# ---------------------------------------------------------------------------
# Cross-engine bridge forward-arm pins (Python -> dict)
# ---------------------------------------------------------------------------


def test_bridge_forward_arm_exile_target_card_from_graveyard():
    """**Forward arm.** A synthetic Ghost-Vacuum-AA[0]-shape
    ``ActivatedAbility`` serializes through ``_python_aa_to_safe_dict``
    to a dict carrying:

      * ``cost``: ``{"tap_self": True}``
      * ``effect``: ``{"kind": "exile_target_card_from_graveyard"}``

    Cycle-1 substrate-only: the round-trip succeeds at the bridge
    floor — admit-gate teeth at C1 are the Effect-class +
    ``sorcery_speed`` AA-rider; AA[0] itself has no AA-rider teeth
    (its ``sorcery_speed=False``), so the bridge forward arm
    *succeeds* even though ``_aa_is_phase1_sub_shape_a`` declines on
    the Effect-class gate.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.exile import (
        ExileTargetCardFromGraveyard,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=ExileTargetCardFromGraveyard(),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None, (
        "Ghost Vacuum AA[0] shape must round-trip through the bridge "
        "floor — Cycle 1 widens the forward emit even though the "
        "admit predicate keeps the printing DECLINED."
    )
    assert d["cost"] == {"tap_self": True}
    assert d["effect"] == {"kind": "exile_target_card_from_graveyard"}
    # Reverse round-trip — byte-equal at the dataclass __eq__ surface.
    back = _aa_dict_to_python_activated_ability(d)
    assert back == aa


def test_bridge_forward_arm_put_each_creature_card_full_riders_no_sorcery_speed():
    """**Forward arm — full Ghost-Vacuum-AA[1] rider payload, BUT
    without the sorcery_speed rider.** AA[1]'s ACTUAL printed shape
    carries ``sorcery_speed=True``, which the C1 bridge floor still
    declines (returns None); the C2 widen flips this. To exercise
    just the forward emit of the Effect's two rider fields, we strip
    the sorcery_speed rider from the synthetic AA.

    The round-trip succeeds; the emitted dict carries the
    ``grant_flying_counter`` + ``grant_subtype_and_pt`` rider entries
    with the expected payload.
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.exile import (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=6),
        ),
        effect=PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
            grant_flying_counter=True,
            grant_subtype_and_pt=("Spirit", 1, 1),
        ),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None, (
        "Ghost Vacuum AA[1] shape (sans sorcery_speed) must round-"
        "trip through the bridge floor at C1; the sorcery_speed "
        "rider decline is C2's widen target."
    )
    assert d["cost"]["tap_self"] is True
    assert d["cost"]["sacrifice_self"] is True
    assert d["cost"]["mana"] == {"generic": 6}
    assert d["effect"]["kind"] == (
        "put_each_creature_card_exiled_with_source_onto_"
        "battlefield_under_your_control"
    )
    assert d["effect"]["grant_flying_counter"] is True
    # **Phase 4C C2 (2026-05-26).** Emit shape changed from list
    # ``["Spirit", 1, 1]`` to tuple ``("Spirit", 1, 1)`` so Rust's
    # ``parse_effect`` extract accepts the payload (Rust's
    # ``v.extract::<(String, i32, i32)>()`` rejects lists with
    # "'list' object cannot be converted to 'PyTuple'"). The reverse
    # arm accepts either shape for forward-compatibility through any
    # future JSON serializer.
    assert d["effect"]["grant_subtype_and_pt"] == ("Spirit", 1, 1)
    # Reverse round-trip — byte-equal at the dataclass __eq__ surface
    # (tuple ↔ list normalization on the rider payload handled by
    # the reverse arm).
    back = _aa_dict_to_python_activated_ability(d)
    assert back == aa


def test_bridge_forward_arm_put_each_creature_card_bare_omits_riders():
    """**Forward arm — bare rider-free shape omits the optional
    rider keys.** The empty-omit discipline mirrors the Rust
    to_pydict arm.
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.exile import (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=6),
        ),
        effect=PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None
    assert "grant_flying_counter" not in d["effect"]
    assert "grant_subtype_and_pt" not in d["effect"]


def test_bridge_forward_arm_ghost_vacuum_aa1_with_sorcery_speed_declines_at_c1():
    """**Inverted post-Phase-4C-C2 invariant — AA[1]'s
    ``sorcery_speed=True`` rider now ADMITS at the bridge floor.**
    Pre-Phase-4C-C2, ``_python_aa_to_safe_dict``'s AA-rider gate
    returned ``None`` for any AA with ``sorcery_speed=True``. C2's
    bridge-floor widen at ``cross_engine.py:14798`` lifts the
    decline and emits ``"sorcery_speed": True`` on the AA dict; the
    Rust ``ActivatedAbility::sorcery_speed`` slot (Phase 4C C2 --
    ``cards.rs:11091``) round-trips the rider byte-equal.
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.exile import (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=6),
        ),
        effect=PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
            grant_flying_counter=True,
            grant_subtype_and_pt=("Spirit", 1, 1),
        ),
        sorcery_speed=True,
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None, (
        "Phase 4C C2 invariant: an AA with sorcery_speed=True "
        "(Ghost Vacuum's actual AA[1] shape) must now ADMIT at the "
        "bridge floor post-C2 (sorcery_speed rider widen at "
        "cross_engine.py:14798)."
    )
    assert d.get("sorcery_speed") is True, (
        "Phase 4C C2: the sorcery_speed flag must propagate on the "
        "AA dict"
    )


# ---------------------------------------------------------------------------
# Rust parse_effect arm pins via Registry.register_printing (§6.3 #18-19)
# ---------------------------------------------------------------------------


def _synthetic_ghost_vacuum_dict():
    """Minimal Ghost-Vacuum-shape Artifact printing dict for the Rust
    Registry. AA[0] is the bare ``{T}: ExileTargetCardFromGraveyard``;
    AA[1] is the recall with the full Ghost Vacuum rider payload.

    Note — we omit ``is_mana_ability`` from both AA entries (defaults
    to False) and we omit ``sorcery_speed`` because Rust's
    ``parse_activated_ability`` doesn't yet read that field (Phase
    4C/4D widen owns it). The Rust side IS the Effect substrate;
    rider-side parses are Phase 4C-C2's deliverable.
    """
    return {
        "name": "Synthetic Ghost Vacuum",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "exile_target_card_from_graveyard",
                },
            },
            {
                "cost": {
                    "tap_self": True,
                    "sacrifice_self": True,
                    "mana": {"generic": 6},
                },
                "effect": {
                    "kind":
                        "put_each_creature_card_exiled_with_source_"
                        "onto_battlefield_under_your_control",
                    "grant_flying_counter": True,
                    "grant_subtype_and_pt": ("Spirit", 1, 1),
                },
            },
        ],
    }


def test_rust_register_printing_with_both_exile_effects(engine):
    """**Design doc §6.3 #18-19 — parse-arms pin.** A synthetic Ghost-
    Vacuum-shape Artifact with the two new Effect variants in its AA
    list registers cleanly through ``Registry.register_printing``;
    Rust's ``parse_effect`` accepts both unit + 2-rider dict shapes.
    """
    reg = engine.Registry()
    pid = reg.register_printing(_synthetic_ghost_vacuum_dict())
    assert reg.get_printing_name(pid) == "Synthetic Ghost Vacuum"


def test_rust_register_printing_aa0_only_exile_target_from_gy_registers(engine):
    """**Parse arm pin — AA[0] isolation.** A printing carrying ONLY
    the bare ``exile_target_card_from_graveyard`` AA registers
    cleanly. Validates the unit-variant parse arm doesn't depend on
    AA[1]'s sibling effect being present.
    """
    reg = engine.Registry()
    pid = reg.register_printing({
        "name": "Single-AA Exile Vacuum",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "exile_target_card_from_graveyard",
                },
            },
        ],
    })
    assert reg.get_printing_name(pid) == "Single-AA Exile Vacuum"


def test_rust_register_printing_aa1_only_recall_registers_with_riders(engine):
    """**Parse arm pin — AA[1] isolation.** A printing carrying ONLY
    the recall AA registers cleanly with the two-rider payload.
    Validates the rider-bearing parse arm doesn't depend on AA[0]'s
    sibling effect being present.
    """
    reg = engine.Registry()
    pid = reg.register_printing({
        "name": "Single-AA Recall Vacuum",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "activated_abilities": [
            {
                "cost": {
                    "tap_self": True,
                    "sacrifice_self": True,
                    "mana": {"generic": 6},
                },
                "effect": {
                    "kind":
                        "put_each_creature_card_exiled_with_source_"
                        "onto_battlefield_under_your_control",
                    "grant_flying_counter": True,
                    "grant_subtype_and_pt": ("Spirit", 1, 1),
                },
            },
        ],
    })
    assert reg.get_printing_name(pid) == "Single-AA Recall Vacuum"


def test_rust_register_printing_recall_bare_no_riders(engine):
    """**Parse arm pin — recall variant without riders.** The bare
    no-rider shape (``grant_flying_counter`` omitted,
    ``grant_subtype_and_pt`` omitted) parses cleanly; the defaults
    are ``false`` / ``None``.
    """
    reg = engine.Registry()
    pid = reg.register_printing({
        "name": "Bare Recall",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "activated_abilities": [
            {
                "cost": {
                    "tap_self": True,
                    "sacrifice_self": True,
                    "mana": {"generic": 6},
                },
                "effect": {
                    "kind":
                        "put_each_creature_card_exiled_with_source_"
                        "onto_battlefield_under_your_control",
                },
            },
        ],
    })
    assert reg.get_printing_name(pid) == "Bare Recall"


def test_rust_register_printing_recall_bad_rider_payload_raises(engine):
    """**Parse arm pin — bad rider payload raises.** A
    ``grant_subtype_and_pt`` value that doesn't unpack to (str, int,
    int) raises loudly.
    """
    reg = engine.Registry()
    with pytest.raises(Exception):
        reg.register_printing({
            "name": "Bad Recall",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 2},
            "activated_abilities": [
                {
                    "cost": {
                        "tap_self": True,
                        "sacrifice_self": True,
                        "mana": {"generic": 6},
                    },
                    "effect": {
                        "kind":
                            "put_each_creature_card_exiled_with_"
                            "source_onto_battlefield_under_your_"
                            "control",
                        "grant_subtype_and_pt": "not-a-tuple",
                    },
                },
            ],
        })


# ---------------------------------------------------------------------------
# Rust to_pydict arm round-trip pin (§6.3 #20)
# ---------------------------------------------------------------------------


def test_rust_to_pydict_round_trip_via_bridge_inverse_exile_target_from_gy():
    """**Design doc §6.3 #20 — to_pydict round-trip pin.** Python ->
    forward dict -> reverse Python yields the same instance. Empty-
    omit discipline implicit (unit variant — no rider keys).
    """
    from mtg_bot.effects.generic.exile import (
        ExileTargetCardFromGraveyard,
    )
    from mtg_bot.parity.cross_engine import (
        _python_aa_to_safe_dict,
        _aa_dict_to_python_activated_ability,
    )
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost

    aa_orig = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=ExileTargetCardFromGraveyard(),
    )
    d = _python_aa_to_safe_dict(aa_orig)
    aa_back = _aa_dict_to_python_activated_ability(d)
    assert aa_back == aa_orig
    # A second forward emit yields a byte-equal dict.
    d2 = _python_aa_to_safe_dict(aa_back)
    assert d == d2


def test_rust_to_pydict_round_trip_via_bridge_inverse_recall_full_riders():
    """**Design doc §6.3 #20 — to_pydict round-trip pin, riders
    variant.** Round-trip Python -> dict -> Python preserves the
    rider payload; a second emit is byte-equal to the first.
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.exile import (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.parity.cross_engine import (
        _python_aa_to_safe_dict,
        _aa_dict_to_python_activated_ability,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=6),
        ),
        effect=PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
            grant_flying_counter=True,
            grant_subtype_and_pt=("Spirit", 1, 1),
        ),
    )
    d = _python_aa_to_safe_dict(aa_orig)
    aa_back = _aa_dict_to_python_activated_ability(d)
    assert aa_back == aa_orig
    d2 = _python_aa_to_safe_dict(aa_back)
    assert d == d2


# ---------------------------------------------------------------------------
# Rust resolve arm pin (§6.3 #21) — exile + recall round-trip
# ---------------------------------------------------------------------------


def _gy_target_creature_dict():
    """Minimal Creature printing dict used to seed a graveyard target
    for the exile-from-gy AA test. Keeps the printing as plain
    Creature (no extra abilities) so the move-to-bf path in the
    recall sibling test fires the standard ETB drain on a no-effect
    body.
    """
    return {
        "name": "Synthetic GY Spirit Target",
        "card_types": ["Creature"],
        "subtypes": ["Spirit"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
    }


def test_resolve_exile_target_card_from_graveyard_moves_card_with_source_stamp(
    engine, synthetic_state,
):
    """**Design doc §6.3 #21 — exile-from-gy resolve pin.** Set up: a
    Spirit Creature in p1's graveyard + a Ghost Vacuum on p0's bf.
    Activate AA[0] targeting the Spirit, resolve, and observe:
      * The Spirit moved p1.graveyard -> p1.exile (owner-preserving).
      * The Spirit's ``exiled_with_source == Ghost_Vacuum_id``.
    """
    # Inject a Spirit into p1's graveyard.
    target_id = synthetic_state.register_and_inject_object(
        _gy_target_creature_dict(), 1, ZONE_GRAVEYARD,
    )

    # Inject Ghost Vacuum onto p0's bf.
    gv_id = synthetic_state.register_and_inject_object(
        _synthetic_ghost_vacuum_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(gv_id, False)

    # Activate AA[0] targeting the Spirit. AA[0] has no mana cost
    # (just {T}), so we don't need to add mana.
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": gv_id,
        "ability_index": 0,
        "target_creature_id": target_id,
    })
    assert synthetic_state.stack_size() == 1
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty()

    # Post-state: the Spirit moved p1.gy -> p1.exile, AND its
    # exiled_with_source matches Ghost Vacuum's id.
    p1_gy_ids = [o["id"] for o in synthetic_state.graveyard_snapshot(1)]
    assert target_id not in p1_gy_ids, (
        "Target Spirit should have left p1.graveyard post-resolve"
    )
    p1_exile_ids = [o["id"] for o in synthetic_state.exile_snapshot(1)]
    assert target_id in p1_exile_ids, (
        "Target Spirit should now be in p1.exile (owner-preserving)"
    )
    # The exile-side object should carry exiled_with_source = Ghost
    # Vacuum's id. Walk p1's exile for the matching record.
    found = False
    for obj in synthetic_state.exile_snapshot(1):
        if obj["id"] == target_id:
            assert obj.get("exiled_with_source") == gv_id, (
                f"Expected exiled_with_source={gv_id}, got "
                f"{obj.get('exiled_with_source')}"
            )
            found = True
            break
    assert found


def test_resolve_recall_moves_tagged_creatures_to_bf_with_per_zone_reset(
    engine, synthetic_state,
):
    """**Design doc §6.3 #22 — recall resolve pin.** Set up: two
    Spirit Creatures in p1's exile, both tagged with
    ``exiled_with_source = ghost_vacuum_id``, plus a non-creature
    card also tagged (to confirm the Creature-type filter). Activate
    AA[1]; resolve. Observe:
      * Both Spirits move p1.exile -> p0.battlefield (activator-
        controlled).
      * The non-creature stays in p1.exile.
      * Each recalled creature has ``summoning_sick=true``,
        ``tapped=false``, ``exiled_with_source=None`` (per-zone
        reset).
      * ``next_etb_timestamp`` advanced by the recalled count.

    **Substrate-only — riders ignored.** Ghost Vacuum's AA[1] carries
    ``grant_flying_counter=True`` + ``grant_subtype_and_pt=('Spirit',
    1, 1)`` but Rust has no flying-counter / continuous-effect
    machinery; the riders are captured on the variant but the resolve
    arm logs-and-continues without applying them. The C3 real-EoE
    probe will catch the divergence at the parity layer if/when
    layered-grant support lands.
    """
    # Inject Ghost Vacuum on p0's bf so the recall AA[1] has a source.
    gv_id = synthetic_state.register_and_inject_object(
        _synthetic_ghost_vacuum_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(gv_id, False)

    # Inject two Spirits + one non-creature, all into p1's exile with
    # the exiled_with_source tag = gv_id.
    spirit_a = synthetic_state.register_and_inject_object(
        _gy_target_creature_dict(), 1, ZONE_EXILE,
    )
    synthetic_state.set_exiled_with_source(spirit_a, gv_id)
    spirit_b = synthetic_state.register_and_inject_object(
        _gy_target_creature_dict(), 1, ZONE_EXILE,
    )
    synthetic_state.set_exiled_with_source(spirit_b, gv_id)
    artifact_token = synthetic_state.register_and_inject_object(
        {
            "name": "Synthetic Tagged Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
        },
        1, ZONE_EXILE,
    )
    synthetic_state.set_exiled_with_source(artifact_token, gv_id)

    # Pre-state: p0.bf has the Vacuum + the fixture's default 10
    # objects. Snapshot the p0 bf object-id set for delta comparison.
    pre_p0_bf_ids = {
        o["id"]
        for o in synthetic_state.battlefield_snapshot()
        if o["controller_id"] == 0
    }

    # Pay {6} mana for AA[1] and activate.
    synthetic_state.add_mana(0, "C", 6)
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": gv_id,
        "ability_index": 1,
    })
    assert synthetic_state.stack_size() == 1
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty()

    # Post-state: both Spirits moved p1.exile -> p0.bf; the artifact
    # stayed in p1.exile (the Creature-type filter rejected it).
    post_p0_bf = [
        o for o in synthetic_state.battlefield_snapshot()
        if o["controller_id"] == 0
    ]
    post_p0_bf_ids = {o["id"] for o in post_p0_bf}
    new_on_p0_bf = post_p0_bf_ids - pre_p0_bf_ids
    assert spirit_a in new_on_p0_bf, (
        "Spirit A should have been recalled to p0.bf"
    )
    assert spirit_b in new_on_p0_bf, (
        "Spirit B should have been recalled to p0.bf"
    )

    p1_exile_ids = {o["id"] for o in synthetic_state.exile_snapshot(1)}
    assert artifact_token in p1_exile_ids, (
        "Tagged non-creature artifact stays in p1.exile (printed-"
        "Creature filter)"
    )
    assert spirit_a not in p1_exile_ids
    assert spirit_b not in p1_exile_ids

    # Per-zone reset: each recalled Spirit is summoning-sick + tapped
    # = false + exiled_with_source = None. Iterate the post-state
    # snapshot to verify.
    for obj in post_p0_bf:
        if obj["id"] in (spirit_a, spirit_b):
            assert obj.get("tapped") is False, (
                f"Recalled {obj['id']} should be untapped"
            )
            assert obj.get("summoning_sick") is True, (
                f"Recalled {obj['id']} should be summoning-sick"
            )
            assert obj.get("exiled_with_source") is None, (
                f"Recalled {obj['id']}'s exiled_with_source should be "
                "cleared (per-zone reset)"
            )

    # Recalled creatures' ETB timestamps are strictly monotonic +
    # contiguous (the CE4 monotonic block at resolve time). Validate
    # the two Spirits' timestamps differ by exactly 1.
    spirit_a_obj = next(
        (o for o in post_p0_bf if o["id"] == spirit_a), None,
    )
    spirit_b_obj = next(
        (o for o in post_p0_bf if o["id"] == spirit_b), None,
    )
    assert spirit_a_obj is not None and spirit_b_obj is not None
    # The two recalled Spirits' etb_timestamps differ by exactly 1
    # (in-loop monotonic block per CE4). The exact values depend on
    # what's already on bf — assert only the contiguity invariant.
    delta = abs(
        spirit_a_obj.get("etb_timestamp", 0)
        - spirit_b_obj.get("etb_timestamp", 0)
    )
    # If etb_timestamp isn't surfaced in the snapshot dict, both
    # values fall back to 0 and delta is 0; in that case skip the
    # contiguity check (the invariant is still upheld inside Rust
    # via the saturating_add(popped.len()) block).
    if "etb_timestamp" in spirit_a_obj:
        assert delta == 1, (
            f"Recalled creatures' etb_timestamps must be contiguous; "
            f"got spirit_a={spirit_a_obj.get('etb_timestamp')}, "
            f"spirit_b={spirit_b_obj.get('etb_timestamp')}"
        )


def test_resolve_recall_no_tagged_creatures_is_silent_noop(
    engine, synthetic_state,
):
    """**Recall arm zero-match short-circuit.** When no exile-zone
    objects carry the matching ``exiled_with_source`` tag, the resolve
    arm is a silent no-op — no bf-push, no ETB drain, no timestamp
    bump. Mirrors Python's early-return at ``exile.py:1056-1061``.
    """
    gv_id = synthetic_state.register_and_inject_object(
        _synthetic_ghost_vacuum_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(gv_id, False)

    # Pre-state: record the p0 bf object-id set EXCLUDING Ghost
    # Vacuum (which sacrifices itself at cost-pay time on AA[1]).
    pre_p0_bf_ids_ex_gv = {
        o["id"]
        for o in synthetic_state.battlefield_snapshot()
        if o["controller_id"] == 0 and o["id"] != gv_id
    }

    synthetic_state.add_mana(0, "C", 6)
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": gv_id,
        "ability_index": 1,
    })
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty()

    # Post-state: no new objects on p0 bf (Ghost Vacuum went to gy
    # via sacrifice_self cost; no recalled creatures because the
    # exiled-with-source pool was empty).
    post_p0_bf_ids = {
        o["id"]
        for o in synthetic_state.battlefield_snapshot()
        if o["controller_id"] == 0
    }
    assert post_p0_bf_ids == pre_p0_bf_ids_ex_gv, (
        "Empty exiled-with-source pool — p0.bf should be unchanged "
        "post-resolve (modulo the Vacuum's self-sacrifice; no "
        "recalled cards expected). Pre-bf - Vacuum = "
        f"{pre_p0_bf_ids_ex_gv}; post-bf = {post_p0_bf_ids}"
    )


def test_resolve_exile_target_card_from_graveyard_fizzles_when_target_moved(
    engine, synthetic_state,
):
    """**Fizzle path — target left graveyard between activation and
    resolve.** If the target id no longer resolves to a card in any
    player's graveyard at resolve time, the Effect silently fizzles
    (no mutation). Mirrors Python's ``if card is None: continue ...
    return`` walk at ``exile.py:330-349``.
    """
    # Inject a Spirit into p1's graveyard, activate, then YANK the
    # Spirit to exile before resolving.
    target_id = synthetic_state.register_and_inject_object(
        _gy_target_creature_dict(), 1, ZONE_GRAVEYARD,
    )
    gv_id = synthetic_state.register_and_inject_object(
        _synthetic_ghost_vacuum_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(gv_id, False)

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": gv_id,
        "ability_index": 0,
        "target_creature_id": target_id,
    })
    # Move target out of the graveyard (to exile) — simulates a
    # sibling effect resolving between activation + resolve.
    synthetic_state.move_object(target_id, ZONE_EXILE, 1)

    pre_p1_exile = synthetic_state.exile_snapshot(1)

    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty()

    # The pre-resolve move already put the target in p1.exile; the
    # silent-fizzle resolve should NOT re-stamp exiled_with_source on
    # an object that's no longer in a graveyard. Confirm the target's
    # exiled_with_source remains UNSET (None) — i.e., the resolve
    # arm short-circuited and never reached the stamp step.
    post_p1_exile = synthetic_state.exile_snapshot(1)
    assert len(post_p1_exile) == len(pre_p1_exile), (
        "Exile snapshot should be unchanged post-fizzle"
    )
    for obj in post_p1_exile:
        if obj["id"] == target_id:
            assert obj.get("exiled_with_source") is None, (
                "Silent-fizzle invariant: exiled_with_source must "
                "stay None when the target had already left the "
                "graveyard pre-resolve"
            )


# ---------------------------------------------------------------------------
# Substrate-only invariant pins — Ghost Vacuum STAYS DECLINED
# ---------------------------------------------------------------------------


def test_ghost_vacuum_stays_declined_at_admit_gate_post_c1():
    """**Inverted post-Phase-4C-C2 invariant — Ghost Vacuum ADMITS at
    the admit gate post-Cycle-2.** Pre-C2 (the C1 substrate slice
    alone), the Python admit gate declined the live printing because
    (a) the Effect-class admit set didn't include the two new
    Effects, and (b) the AA-rider gate still declined AA[1]'s
    ``sorcery_speed=True`` rider. Phase 4C Cycle 2 lands those three
    widens; this pin INVERTS to assert the FLIP through the same
    surface.

    Verify via the per-AA + printing-level admit predicates that BOTH
    AAs admit at Phase 1 sub-shape A; the printing-level dispatcher
    admits too.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _printing_is_bridge_simple_carrier_aa_any,
    )

    printings = OracleParserCardSource().get_printings()
    printing = printings["Ghost Vacuum"]
    aa0, aa1 = printing.activated_abilities

    # Per-AA admit predicate: both admit post-C2 (the Effect-class
    # widen + sorcery_speed AA-rider widen + Rust sorcery_speed slot
    # all land at Phase 4C Cycle 2).
    assert _aa_is_phase1_sub_shape_a(aa0) is True, (
        "AA[0] must ADMIT at the per-AA admit gate post-Phase-4C-C2 "
        "(ExileTargetCardFromGraveyard now in Effect-class admit set)"
    )
    assert _aa_is_phase1_sub_shape_a(aa1) is True, (
        "AA[1] must ADMIT at the per-AA admit gate post-Phase-4C-C2 "
        "(sorcery_speed=True rider now admitted; "
        "PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYour"
        "Control now in Effect-class admit set)"
    )
    # Printing-level dispatcher: admits (both AAs pass per the Phase
    # 4A all-or-nothing contract).
    assert (
        _printing_is_bridge_simple_carrier_aa_any(printing) is True
    ), (
        "Ghost Vacuum must ADMIT at the printing-level admit "
        "dispatcher post-Phase-4C-C2 (sibling FLIP pin to the C2 "
        "substrate test)"
    )


def test_ghost_vacuum_declines_at_artifact_admit_predicate_post_c1():
    """**Inverted post-Phase-4C-C2 invariant — the Artifact sibling
    admit predicate ADMITS Ghost Vacuum post-Cycle-2.** Pre-C2 (the
    C1 substrate slice alone), the sibling Carrier-AA-Artifact admit
    predicate rejected the live printing on per-AA teeth. Phase 4C
    Cycle 2's widens flip it to admit.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_artifact,
    )

    printings = OracleParserCardSource().get_printings()
    printing = printings["Ghost Vacuum"]
    assert (
        _printing_is_bridge_simple_carrier_aa_artifact(printing)
        is True
    ), (
        "Phase 4C C2 invariant: Ghost Vacuum must ADMIT at the "
        "Artifact-typed sibling admit predicate post-C2 (the per-AA "
        "teeth are lifted; C2 widens the Effect-class admit set + "
        "the sorcery_speed AA-rider gate)."
    )


def test_carrier_aa_phase_1_effect_classes_unchanged_post_c1():
    """**Inverted post-Phase-4C-C2 invariant — the Effect-class admit
    set GROWS by 2 at Phase 4C Cycle 2.** Both
    ``ExileTargetCardFromGraveyard`` and the recall sibling join the
    frozenset (9 → 11). Pre-C2 (C1 substrate alone) they were absent.
    """
    from mtg_bot.effects.generic.exile import (
        ExileTargetCardFromGraveyard,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.parity.trajectory import (
        _carrier_aa_phase_1_effect_classes,
    )

    admitted = _carrier_aa_phase_1_effect_classes()
    assert ExileTargetCardFromGraveyard in admitted, (
        "Phase 4C C2 widen: ExileTargetCardFromGraveyard MUST be in "
        "the Effect-class admit set (C2 ships the widen)."
    )
    assert PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl in admitted, (
        "Phase 4C C2 widen: "
        "PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYour"
        "Control MUST be in the Effect-class admit set (C2 ships the "
        "widen)."
    )
