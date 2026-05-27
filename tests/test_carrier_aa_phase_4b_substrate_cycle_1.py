"""**Carrier-AA substrate Phase 4B Cycle 1 (2026-05-26).**

Tests for the Phase 4B Cycle 1 Rust slice landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §3B (Mirrorpool scope) +
§4.1.2 (Rust spec — Option B: CR-707.5 token-creature-copy first) +
§5.4 (Python bridge spec) + §6.2 (test plan, pins #5-13) + §7.2
(cycle plan).

**Option B chosen as the narrower C1 slice per design doc §3B
recommendation.** AA[1]'s ``CreateTokenCopyOfTargetCreatureYouControl``
Effect variant + parse arm + to_pydict arm + resolve arm ALL pre-
exist on the Rust side (the round-28 substrate at
``cards.rs:4448`` / ``cards.rs:13714`` / ``cards.rs:19405`` /
``state_ops_resolve.rs:14828`` landed the unit-variant shape with
deterministic-first-creature target pick). The cross-engine bridge
REVERSE arm exists at ``cross_engine.py:7190``. C1 closes the
remaining four substrate gaps:

  1. **Target fan-out in ``state_ops_legal.rs::activate_ability_dict``**
     — enumerates every Creature on the activator's bf and emits one
     ``ActivateAbility`` per eligible target with
     ``target_creature_id = Some(creature_id)``. Mirrors Python's
     ``CreateTokenCopyOfTargetCreatureYouControl.legal_targets`` at
     ``effects/generic/tokens.py:340-348`` (activator-only — printed
     "you control" rider; differs from the Phase 3C
     ``BecomesCopyOfTargetLand`` arm which walks BOTH bfs).

  2. **Target validation in ``state_ops_actions.rs::ActivateAbility``**
     — re-checks the chosen target id against bf-presence on the
     ACTIVATOR's bf + printed-Creature. Sibling of the Phase 3C / 4C /
     4D target-bearing validation arms; ``target_creature_id`` is
     OPTIONAL on this effect (substrate-fallback path; pre-substrate
     callers preserved).

  3. **Target-aware resolve in ``state_ops_resolve.rs``** — the
     existing resolve arm now consults
     ``current_resolve_payload_target_id`` FIRST; falls back to the
     deterministic-first-creature scan when no payload target is
     seated. Preserves the round-28 round-trip surface byte-equal for
     pre-substrate callers.

  4. **Forward arm in
     ``cross_engine.py::_python_aa_to_safe_dict``** — recognizes
     ``CreateTokenCopyOfTargetCreatureYouControl`` (SPECIFIC
     isinstance) and emits ``{"kind":
     "create_token_copy_of_target_creature_you_control"}``. Honest-
     declines (returns ``None`` for the AA dict) when
     ``additional_subtype is not None`` because Rust's variant is unit
     — the rider's not representable on the wire today. Mirrorpool's
     live AA[1] uses ``additional_subtype=None``, so the decline arm
     is unreachable from production.

ZERO Python admit widen this cycle (the
``_carrier_aa_phase_1_effect_classes`` widen for
``CreateTokenCopyOfTargetCreatureYouControl`` ships C2/C3 per design
doc §5.4; the sibling AA[0]
``CopyTargetInstantOrSorceryYouControl`` substrate ships C2 per
design doc §7.2 row C2 + the Effect-class admit widen for it ships
together with the FLIP).
ZERO per-card probe this cycle (Phase 4B probe per design doc §6.7
ships at the FLIP cycle once both AA[0] + AA[1] substrates land).

Substrate-only invariant — Mirrorpool STAYS DECLINED at the admit
gate post-Cycle-1. The Rust substrate widens (target fan-out,
validation, target-aware resolve) + cross-engine forward arm all
land; the live admit gate still declines Mirrorpool's printing
because (a) ``_carrier_aa_phase_1_effect_classes`` doesn't yet
include ``CreateTokenCopyOfTargetCreatureYouControl`` OR
``CopyTargetInstantOrSorceryYouControl`` AND (b) Mirrorpool's
sibling AA[0] (``CopyTargetInstantOrSorceryYouControl``) has NO
Rust substrate at C1 — C2 ships it. Under Phase 4A's multi-AA all-
or-nothing contract a printing admits only if EVERY AA admits, so
even widening just AA[1]'s Effect class wouldn't FLIP Mirrorpool —
the AA[0] substrate + widen are co-required.

**Verify-first findings (live tree, main ``c1b072f3``):**

  - Mirrorpool printing-level shape: ``card_types=("Land",)``,
    ``subtypes=()``, ``supertypes=()``, ``keywords=frozenset()``,
    ``triggered_abilities=()``, ``static_abilities=()``,
    ``cost_reductions=()``, ``spell_effect=None``, ``n_aa=2``.
  - AA[0]: ``cost=ActivationCost(mana=ManaCost(generic=3, colored=()),
    mana_str='{2}{C}', tap_self=True, sacrifice_self=True)``,
    ``effect=CopyTargetInstantOrSorceryYouControl()``,
    ``is_mana_ability=False``, ``sorcery_speed=False``.
  - AA[1]: ``cost=ActivationCost(mana=ManaCost(generic=5,
    colored=()), mana_str='{4}{C}', tap_self=True,
    sacrifice_self=True)``,
    ``effect=CreateTokenCopyOfTargetCreatureYouControl(additional_
    subtype=None)``, ``is_mana_ability=False``, ``sorcery_speed=False``.
  - Pre-C1 Rust state: ``Effect::CreateTokenCopyOfTargetCreatureYou
    Control`` is a UNIT variant landed round-28; parse +
    to_pydict + resolve arm all in place. ``Effect::CopyTarget
    InstantOrSorceryYouControl`` does NOT exist (C2 ships it).
  - Pre-C1 ``_python_aa_to_safe_dict`` forward arm coverage: NO arm
    for ``CreateTokenCopyOfTargetCreatureYouControl`` — bridge-floor
    falls through to ``effect_dict is None`` decline. C1 adds it.
  - Pre-C1 cross-engine reverse arm coverage: arm EXISTS at
    ``cross_engine.py:7190`` (the round-23 BLOCKED-BRIDGE-ARM slice
    closed the to_dict round-trip surface). Nothing to add.

This is a **substrate-only closure** — the cycle wires the Rust
target-aware activation surface for Mirrorpool's AA[1] +
cross-engine forward emit. Mirrorpool STAYS DECLINED at the
production-deck admit gate post-Cycle-1.
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
    per side. Mirrors the Phase-3A/3B/3C/4C/4D/4E sibling shared
    fixture."""
    return engine.make_synthetic_state()


# ---------------------------------------------------------------------------
# Parser SoT verify-first pins (design doc §6.2 #5)
# ---------------------------------------------------------------------------


def test_python_create_token_copy_of_target_creature_class_exists():
    """**Parser SoT pin.** Python's
    ``CreateTokenCopyOfTargetCreatureYouControl`` class is in
    ``effects.generic.tokens``, a frozen dataclass with one optional
    rider field ``additional_subtype: str | None = None``.
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )

    bare = CreateTokenCopyOfTargetCreatureYouControl()
    assert isinstance(bare, Effect)
    assert bare.additional_subtype is None
    # Two parameterless instances compare equal.
    assert bare == CreateTokenCopyOfTargetCreatureYouControl()

    # The Mirror Room-shape rider, exercised at the bridge-floor
    # honest-decline arm (see below).
    mirror_room = CreateTokenCopyOfTargetCreatureYouControl(
        additional_subtype="Reflection",
    )
    assert mirror_room.additional_subtype == "Reflection"
    same = CreateTokenCopyOfTargetCreatureYouControl(
        additional_subtype="Reflection",
    )
    assert mirror_room == same


def test_mirrorpool_live_aa_shapes_match_design_doc():
    """**Verify-first pin (design doc §2.1 row).** The live Mirrorpool
    parser SoT carries:

      * AA[0]: ``CopyTargetInstantOrSorceryYouControl()`` + cost
        ``{2}{C}, {T}, Sacrifice this land``, ``is_mana_ability=False``,
        ``sorcery_speed=False``.
      * AA[1]: ``CreateTokenCopyOfTargetCreatureYouControl(additional_
        subtype=None)`` + cost ``{4}{C}, {T}, Sacrifice this land``,
        ``is_mana_ability=False``, ``sorcery_speed=False``.

    This pin protects the verify-first finding the C1 substrate is
    built against: a future parser tweak that mutates either AA's
    shape would need to be reconciled here BEFORE later cycles ship
    the admit widens.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.generic.stack_control import (
        CopyTargetInstantOrSorceryYouControl,
    )
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )

    printings = OracleParserCardSource().get_printings()
    assert "Mirrorpool" in printings, (
        "Verify-first invariant: Mirrorpool must be present in the "
        "Oracle parser card source"
    )
    printing = printings["Mirrorpool"]
    assert printing.card_types == ("Land",)
    assert printing.subtypes == ()
    assert printing.supertypes == ()
    assert printing.keywords == frozenset()
    assert printing.triggered_abilities == ()
    assert printing.static_abilities == ()
    assert printing.cost_reductions == ()
    assert printing.spell_effect is None
    assert len(printing.activated_abilities) == 2

    aa0 = printing.activated_abilities[0]
    assert isinstance(aa0.effect, CopyTargetInstantOrSorceryYouControl)
    assert aa0.is_mana_ability is False
    assert aa0.sorcery_speed is False
    assert aa0.cost.tap_self is True
    assert aa0.cost.sacrifice_self is True
    assert aa0.cost.mana is not None
    assert aa0.cost.mana.generic == 3
    assert aa0.cost.mana.colored == ()

    aa1 = printing.activated_abilities[1]
    assert isinstance(aa1.effect, CreateTokenCopyOfTargetCreatureYouControl)
    assert aa1.effect.additional_subtype is None
    assert aa1.is_mana_ability is False
    assert aa1.sorcery_speed is False
    assert aa1.cost.tap_self is True
    assert aa1.cost.sacrifice_self is True
    assert aa1.cost.mana is not None
    assert aa1.cost.mana.generic == 5
    assert aa1.cost.mana.colored == ()


# ---------------------------------------------------------------------------
# Cross-engine bridge reverse-arm pins (dict -> Python) — confirms
# pre-existing arm at ``cross_engine.py:7190``
# ---------------------------------------------------------------------------


def test_bridge_reverse_arm_create_token_copy_unit_variant():
    """**Reverse arm — sanity confirmation.** ``_ta_dict_to_python_
    effect`` constructs ``CreateTokenCopyOfTargetCreatureYouControl()``
    from the unit-variant ``{"kind":
    "create_token_copy_of_target_creature_you_control"}`` dict. The
    arm is pre-existing (round-23 BLOCKED-BRIDGE-ARM slice); pin
    locks it.
    """
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect(
        {"kind": "create_token_copy_of_target_creature_you_control"},
    )
    assert isinstance(back, CreateTokenCopyOfTargetCreatureYouControl)
    # Bare-instance (additional_subtype=None default) ⇒ byte-equal.
    assert back == CreateTokenCopyOfTargetCreatureYouControl()
    assert back.additional_subtype is None


# ---------------------------------------------------------------------------
# Cross-engine bridge forward-arm pins (Python -> dict) — NEW at C1
# (design doc §6.2 #6)
# ---------------------------------------------------------------------------


def test_bridge_forward_arm_create_token_copy_bare():
    """**Forward arm — NEW at Phase 4B C1.** A synthetic Mirrorpool-
    AA[1]-shape ``ActivatedAbility`` serializes through
    ``_python_aa_to_safe_dict`` to a dict carrying:

      * ``cost``: ``{"tap_self": True, "sacrifice_self": True,
        "mana": ...}``
      * ``effect``: ``{"kind":
        "create_token_copy_of_target_creature_you_control"}``

    Cycle-1 substrate-only: the round-trip succeeds at the bridge
    floor for the bare ``additional_subtype=None`` shape (Mirrorpool's
    live AA[1] shape). The admit-gate teeth at C1 are the Effect-
    class gate (the printing-level admit declines Mirrorpool because
    ``_carrier_aa_phase_1_effect_classes`` doesn't include this
    Effect class); the bridge forward arm itself *succeeds*.
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=5),
        ),
        effect=CreateTokenCopyOfTargetCreatureYouControl(),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None, (
        "Mirrorpool AA[1] bare shape must round-trip through the "
        "bridge floor — Cycle 1 widens the forward emit even though "
        "the admit predicate keeps the printing DECLINED."
    )
    assert d["effect"] == {
        "kind": "create_token_copy_of_target_creature_you_control",
    }
    # Reverse round-trip — byte-equal at the dataclass __eq__ surface.
    back = _aa_dict_to_python_activated_ability(d)
    assert back == aa


def test_bridge_forward_arm_create_token_copy_with_additional_subtype_declines():
    """**Forward arm — honest-decline on ``additional_subtype``
    rider.** Rust's ``Effect::CreateTokenCopyOfTargetCreatureYou
    Control`` is a unit variant with no rider slot — the
    ``additional_subtype`` field is not representable on the wire
    today (Rust has no subtype tracking on registry yet, per
    ``cards.rs:4446-4447``). When the Python instance carries
    ``additional_subtype != None`` (the Mirror Room shape per design
    doc §3.10), the forward arm honest-declines by returning ``None``
    so the round-trip stays byte-equal (no silent information loss).

    Mirrorpool's live AA[1] uses ``additional_subtype=None`` per the
    parser SoT, so this decline path is unreachable from production
    today. Mirror Room would be the live consumer.
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=5),
        ),
        effect=CreateTokenCopyOfTargetCreatureYouControl(
            additional_subtype="Reflection",
        ),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is None, (
        "Phase 4B C1 invariant: an AA with additional_subtype != None "
        "must honest-decline at the forward bridge floor — Rust's "
        "variant is unit and cannot carry the rider. Mirrorpool's "
        "live AA[1] uses None so this decline path is unreachable "
        "from production."
    )


# ---------------------------------------------------------------------------
# Cross-engine round-trip pin (design doc §6.2 #6 + #13)
# ---------------------------------------------------------------------------


def test_bridge_round_trip_create_token_copy_bare():
    """**Round-trip pin — Python -> dict -> Python.** The bare
    ``additional_subtype=None`` shape round-trips through the bridge
    twice byte-equal. A second forward emit yields a dict identical
    to the first.
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=5),
        ),
        effect=CreateTokenCopyOfTargetCreatureYouControl(),
    )
    d = _python_aa_to_safe_dict(aa_orig)
    aa_back = _aa_dict_to_python_activated_ability(d)
    assert aa_back == aa_orig
    # A second forward emit yields a byte-equal dict.
    d2 = _python_aa_to_safe_dict(aa_back)
    assert d == d2


def test_mirrorpool_two_aa_list_round_trip_partial_at_c1(synthetic_state):
    """**Design doc §6.2 #13 — Mirrorpool's two AAs round-trip in a
    2-element list.** AT C1: only AA[1] has a Rust-side Effect
    variant; AA[0] (``CopyTargetInstantOrSorceryYouControl``) has NO
    Rust variant yet (C2 ships it). The forward emit therefore
    honest-declines AA[0] at the bridge floor — confirming the C1
    decline mechanism that keeps Mirrorpool's printing DECLINED at
    the admit gate.

    Once C2 ships AA[0]'s Effect variant + forward arm, this pin
    inverts to assert both AAs admit — at which point the printing-
    level admit predicate flips Mirrorpool ADMITTED (combined with
    the C2/C3 ``_carrier_aa_phase_1_effect_classes`` widen for both
    Effect classes).
    """
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict
    from mtg_bot.cards.parser.source import OracleParserCardSource

    printing = OracleParserCardSource().get_printings()["Mirrorpool"]
    assert len(printing.activated_abilities) == 2

    aa0_dict = _python_aa_to_safe_dict(printing.activated_abilities[0])
    aa1_dict = _python_aa_to_safe_dict(printing.activated_abilities[1])

    # C1 invariant: AA[0]'s CopyTargetInstantOrSorceryYouControl has
    # no Rust substrate yet — forward arm declines (returns None).
    assert aa0_dict is None, (
        "C1 invariant: Mirrorpool AA[0] (CopyTargetInstantOrSorcery"
        "YouControl) has NO Rust Effect variant yet (C2 ships it). "
        "Forward arm declines."
    )
    # C1 invariant: AA[1]'s CreateTokenCopyOfTargetCreatureYouControl
    # passes the new C1 forward arm.
    assert aa1_dict is not None, (
        "C1 invariant: Mirrorpool AA[1] (CreateTokenCopyOfTarget"
        "CreatureYouControl, additional_subtype=None) ADMITS at the "
        "C1 bridge-floor forward emit."
    )
    assert aa1_dict["effect"] == {
        "kind": "create_token_copy_of_target_creature_you_control",
    }


# ---------------------------------------------------------------------------
# Substrate-only invariant pin (design doc §6.2 #7)
# ---------------------------------------------------------------------------


def test_mirrorpool_stays_declined_at_admit_gate_post_c2():
    """**Phase 4B C2 partial-widen invariant — Mirrorpool STILL STAYS
    DECLINED at the printing-level admit gate post-Cycle-2 (Option A
    honest-stop).**

    **C2 widen.** The C2 widen at
    :func:`_carrier_aa_phase_1_effect_classes` adds
    ``CreateTokenCopyOfTargetCreatureYouControl`` (Mirrorpool's AA[1]
    pilot Effect class). The per-AA admit predicate
    :func:`_aa_is_phase1_sub_shape_a` now ADMITS AA[1] (the Effect-
    class teeth previously biting at C1 are removed).

    **Honest-stop — AA[0] keeps the printing DECLINED.** Mirrorpool's
    sibling AA[0] ``CopyTargetInstantOrSorceryYouControl`` (CR-707.2
    spell-copy) has NO Rust substrate at C2 (the new
    ``Effect::CopyTargetInstantOrSorceryYouControl`` variant + stack-
    target fan-out + ``StackItem.is_copy`` audit + new push-copy-on-
    stack resolve arm all defer to a future Rust cycle per design doc
    §4.1.1). The Effect-class admit set therefore does NOT include
    ``CopyTargetInstantOrSorceryYouControl`` at C2 (omitting from the
    widen is intentional — the cross-engine bridge floor would honest-
    decline this Effect class anyway because no forward arm exists,
    and the Rust resolve arm would crash on the unknown variant).

    Under the Phase 4A multi-AA all-or-nothing contract
    (per-AA all-admit-or-decline at
    :func:`_printing_is_bridge_simple_carrier_aa_land`),
    Mirrorpool's printing-level admit declines because AA[0] bites on
    the per-AA Effect-class teeth.

    The full Mirrorpool FLIP DECLINED → ADMITTED requires the AA[0]
    Rust slice (one or more future Rust cycles) + a follow-up Python
    Effect-class widen + bridge arms. Refined Phase 4B sequencing in
    the trajectory.py docstring + worklog.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_land,
    )

    printing = OracleParserCardSource().get_printings()["Mirrorpool"]
    aa0 = printing.activated_abilities[0]
    aa1 = printing.activated_abilities[1]
    # Per-AA admit teeth: AA[0] STAYS declined (Effect class not in
    # admit set — Rust substrate gap); AA[1] FLIPS ADMITTED (C2 widen).
    assert not _aa_is_phase1_sub_shape_a(aa0), (
        "Phase 4B C2 invariant: AA[0] (CopyTargetInstantOrSorcery"
        "YouControl) must STAY declined at the per-AA admit predicate "
        "(its Effect class is intentionally NOT in _carrier_aa_phase_1_"
        "effect_classes at C2 — the AA[0] Rust substrate ships in a "
        "future cycle per design doc §4.1.1)."
    )
    assert _aa_is_phase1_sub_shape_a(aa1), (
        "Phase 4B C2 invariant: AA[1] (CreateTokenCopyOfTargetCreature"
        "YouControl) must FLIP ADMITTED at the per-AA admit predicate "
        "(C2 widens _carrier_aa_phase_1_effect_classes to include the "
        "Effect class; the C1 Rust substrate at 434d6aa1/818b4c64 "
        "shipped target fan-out + validation + target-aware resolve + "
        "cross-engine forward + reverse arms)."
    )
    # Printing-level admit (Phase 4A multi-AA all-or-nothing): STILL
    # declines via the Land predicate AND the unified dispatcher
    # because AA[0]'s teeth keep biting.
    assert not _printing_is_bridge_simple_carrier_aa_land(printing), (
        "Phase 4B C2 invariant: Mirrorpool must STAY declined on the "
        "Land admit predicate (AA[0]'s Effect-class teeth bite under "
        "the multi-AA all-or-nothing contract)."
    )
    assert not _printing_is_bridge_simple_carrier_aa_any(printing), (
        "Phase 4B C2 invariant: Mirrorpool must STAY declined on the "
        "unified admit dispatcher (AA[0]'s Effect-class teeth bite "
        "under the multi-AA all-or-nothing contract)."
    )


def test_create_token_copy_effect_class_admit_set_post_c2():
    """**Sentinel pin — the C2 admit-set IS WIDENED to include
    ``CreateTokenCopyOfTargetCreatureYouControl``** but NOT the
    sibling ``CopyTargetInstantOrSorceryYouControl`` (the AA[0]
    half), per Option A's partial-widen contract.

    Pins the C2 admit-set surface exactly so the Phase 4B C3+/C4 FLIP
    cycle has a precise inversion point (C4 ships the AA[0] half).
    Sibling of the Phase 3A/3B/3C/4C/4D/4E admit-set sentinel pins.
    """
    from mtg_bot.effects.generic.stack_control import (
        CopyTargetInstantOrSorceryYouControl,
    )
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )
    from mtg_bot.parity.trajectory import _carrier_aa_phase_1_effect_classes

    admit_set = _carrier_aa_phase_1_effect_classes()
    # C2 ADDS CreateTokenCopyOfTargetCreatureYouControl.
    assert CreateTokenCopyOfTargetCreatureYouControl in admit_set, (
        "Phase 4B C2 invariant: CreateTokenCopyOfTargetCreatureYou"
        "Control must be in _carrier_aa_phase_1_effect_classes "
        "post-Cycle-2 (the C1 Rust substrate at 434d6aa1 shipped the "
        "fan-out + validation + resolve + bridge arms; C2 widens the "
        "admit set)."
    )
    # C2 does NOT add CopyTargetInstantOrSorceryYouControl (Option A
    # honest-stop — AA[0] Rust substrate not yet shipped).
    assert CopyTargetInstantOrSorceryYouControl not in admit_set, (
        "Phase 4B C2 invariant (Option A honest-stop): "
        "CopyTargetInstantOrSorceryYouControl must NOT be in "
        "_carrier_aa_phase_1_effect_classes at C2 — its Rust ``Effect`` "
        "variant + stack-target fan-out + push-copy-on-stack resolve "
        "arm + StackItem.is_copy audit all defer to a future Rust "
        "cycle per design doc §4.1.1. The Python admit widen + bridge "
        "arms ship together with the Rust slice in a future Python "
        "cycle (refined sequencing in trajectory.py docstring)."
    )


# ---------------------------------------------------------------------------
# Rust parse_effect arm pin via Registry.register_printing
# (design doc §6.2 #9 / sanity)
# ---------------------------------------------------------------------------


def _synthetic_mirrorpool_aa1_only_dict():
    """Minimal Mirrorpool-AA[1]-shape Land printing dict for the Rust
    Registry. AA[1] is the bare ``{4}{C}, {T}, Sac: CreateTokenCopy
    OfTargetCreatureYouControl`` shape — modeled at the C1 Rust
    surface as ``{generic=5, tap_self=true, sacrifice_self=true}``
    cost + ``create_token_copy_of_target_creature_you_control`` unit-
    variant effect dict.
    """
    return {
        "name": "Synthetic Mirrorpool AA1",
        "card_types": ["Land"],
        "activated_abilities": [
            {
                "cost": {
                    "tap_self": True,
                    "sacrifice_self": True,
                    "mana": {"generic": 5},
                },
                "effect": {
                    "kind":
                        "create_token_copy_of_target_creature_"
                        "you_control",
                },
            },
        ],
    }


def test_rust_register_printing_with_create_token_copy_aa(engine):
    """**Design doc §6.2 #9 — Rust parse-arm sanity pin.** A synthetic
    Mirrorpool-AA[1]-shape Land printing registers cleanly through
    ``Registry.register_printing``; Rust's ``parse_effect`` accepts
    the unit-variant ``create_token_copy_of_target_creature_you_
    control`` dict — pre-existing parse arm from round-28.
    """
    reg = engine.Registry()
    pid = reg.register_printing(_synthetic_mirrorpool_aa1_only_dict())
    assert reg.get_printing_name(pid) == "Synthetic Mirrorpool AA1"


# ---------------------------------------------------------------------------
# Rust to_pydict round-trip pin (design doc §6.2 #10)
# ---------------------------------------------------------------------------


def test_rust_to_pydict_round_trip_via_bridge_inverse_create_token_copy():
    """**Design doc §6.2 #10 — to_pydict round-trip pin.** Python ->
    forward dict -> reverse Python yields the same instance. Unit
    variant — no rider keys; empty-omit discipline implicit. A second
    forward emit is byte-equal to the first.
    """
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tokens import (
        CreateTokenCopyOfTargetCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=5),
        ),
        effect=CreateTokenCopyOfTargetCreatureYouControl(),
    )
    d = _python_aa_to_safe_dict(aa_orig)
    aa_back = _aa_dict_to_python_activated_ability(d)
    assert aa_back == aa_orig
    d2 = _python_aa_to_safe_dict(aa_back)
    assert d == d2


# ---------------------------------------------------------------------------
# Rust resolve arm — target-aware path (design doc §6.2 #11 happy path)
# ---------------------------------------------------------------------------


def _mirrorpool_aa1_printing_dict():
    """Mirrorpool-AA[1]-shape Land printing dict for the Rust
    Registry. AA[1] is the bare ``{4}{C}, {T}, Sac: CreateTokenCopy
    OfTargetCreatureYouControl`` shape — modeled at the C1 Rust
    surface as ``{generic=5, tap_self=true, sacrifice_self=true}``
    cost + ``create_token_copy_of_target_creature_you_control`` unit-
    variant effect dict.
    """
    return {
        "name": "Synthetic Mirrorpool",
        "card_types": ["Land"],
        "activated_abilities": [
            {
                "cost": {
                    "tap_self": True,
                    "sacrifice_self": True,
                    "mana": {"generic": 5},
                },
                "effect": {
                    "kind":
                        "create_token_copy_of_target_creature_"
                        "you_control",
                },
            },
        ],
    }


def _creature_printing_dict(name, power, toughness):
    """Minimal Creature printing dict for token-copy resolve tests."""
    return {
        "name": name,
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": power,
        "toughness": toughness,
    }


def test_rust_resolve_picks_payload_target_creature(
    engine, synthetic_state,
):
    """**Design doc §6.2 #11 — Rust resolve happy path (target-aware).**
    Set up: a Mirrorpool-AA[1]-shape Land on p0's bf + TWO Creature
    targets on p0's bf. Activate AA[0] targeting the SECOND creature
    (not the deterministic-first), resolve, observe: a new token
    enters p0's bf with ``printing_id`` matching the SECOND creature's
    printing — NOT the round-28 deterministic-first-creature pick.

    This pin confirms the target-aware resolve arm consults
    ``current_resolve_payload_target_id`` BEFORE falling back to the
    deterministic-first scan.
    """
    # Inject Mirrorpool on p0's bf, summoning-sick cleared.
    mp_id = synthetic_state.register_and_inject_object(
        _mirrorpool_aa1_printing_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(mp_id, False)
    # Two distinct Creature printings on p0's bf.
    bear_a_id = synthetic_state.register_and_inject_object(
        _creature_printing_dict("Synthetic Bear A", 2, 2),
        0, ZONE_BATTLEFIELD,
    )
    bear_b_id = synthetic_state.register_and_inject_object(
        _creature_printing_dict("Synthetic Bear B", 3, 3),
        0, ZONE_BATTLEFIELD,
    )

    pre_bf = synthetic_state.battlefield_snapshot()
    pre_p0_ids = {o["id"] for o in pre_bf if o["controller_id"] == 0}

    # Pay {5} mana for AA[0] (Mirrorpool's only AA in this synthetic
    # shape).
    synthetic_state.add_mana(0, "C", 5)
    # Activate AA[0] (= the AA[1]-shape, the synthetic shape's only
    # AA), targeting bear B (NOT bear A which is the deterministic
    # first creature).
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": mp_id,
        "ability_index": 0,
        "target_creature_id": bear_b_id,
    })
    assert synthetic_state.stack_size() == 1
    synthetic_state.resolve_top_of_stack()

    post_bf = synthetic_state.battlefield_snapshot()
    post_p0_ids = {o["id"] for o in post_bf if o["controller_id"] == 0}
    new_ids = post_p0_ids - pre_p0_ids
    # Mirrorpool sac'd itself; net delta = new_token - source -
    # any unrelated. Filter to objects in new_ids.
    new_objs = [o for o in post_bf if o["id"] in new_ids]
    # There should be EXACTLY one new GameObject on p0's bf — the
    # token. Mirrorpool itself sac'd (left the bf).
    assert len(new_objs) == 1, (
        "Phase 4B C1 resolve-arm pin: exactly one new token should "
        f"enter p0's bf post-resolve; got {len(new_objs)} new objects: "
        f"{new_objs}"
    )
    new_token = new_objs[0]
    bear_b_obj = next(o for o in post_bf if o["id"] == bear_b_id)
    # The minted token's printing_id MUST match bear B (the payload
    # target), NOT bear A (the deterministic-first fallback).
    assert new_token["printing_id"] == bear_b_obj["printing_id"], (
        "Phase 4B C1 resolve-arm target-aware pin: the new token's "
        "printing_id must match the PAYLOAD-target bear B's printing, "
        "NOT the deterministic-first bear A pre-substrate pick"
    )


def test_rust_resolve_fallback_to_deterministic_first_creature_when_no_payload(
    engine, synthetic_state,
):
    """**Design doc §6.2 — Rust resolve back-compat pin (substrate-
    fallback path).** Activate Mirrorpool's AA[1] WITHOUT a
    ``target_creature_id`` — the validation arm passes ``None`` (the
    payload is OPTIONAL on this effect per the Phase 4B C1 design).
    The resolve arm's substrate-fallback path then walks the
    activator's bf for the deterministic-first Creature (round-28
    pre-substrate behavior) and mints a token copy.

    Confirms the C1 widen preserves the pre-substrate caller surface
    byte-equal: any callers (direct or synthetic) that built an
    ActivateAbility dict without a ``target_creature_id`` still
    drive the resolve arm through the same first-creature pick.
    """
    # Inject Mirrorpool on p0's bf, summoning-sick cleared.
    mp_id = synthetic_state.register_and_inject_object(
        _mirrorpool_aa1_printing_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(mp_id, False)

    pre_bf = synthetic_state.battlefield_snapshot()
    pre_p0_ids = {o["id"] for o in pre_bf if o["controller_id"] == 0}

    synthetic_state.add_mana(0, "C", 5)
    # Activate the AA with NO target_creature_id (the substrate-
    # fallback path used by direct-callers without a chosen target —
    # exercises the back-compat deterministic-first-creature scan).
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": mp_id,
        "ability_index": 0,
    })
    assert synthetic_state.stack_size() == 1
    synthetic_state.resolve_top_of_stack()

    post_bf = synthetic_state.battlefield_snapshot()
    post_p0_ids = {o["id"] for o in post_bf if o["controller_id"] == 0}
    # Exactly one new object on p0's bf — the token. Mirrorpool itself
    # left bf via sacrifice_self cost.
    delta_added = post_p0_ids - pre_p0_ids
    assert len(delta_added) == 1, (
        "Phase 4B C1 resolve-arm fallback pin: with no payload target "
        "and creatures on p0's bf (synthetic_state seeds 10/side), the "
        "deterministic-first-creature fallback should mint exactly one "
        f"token. Got delta {delta_added}"
    )
    # The minted token's printing should match SOME Creature on p0's
    # bf (the deterministic-first-creature scan walks in vec order;
    # the first match wins). Confirm the token's printing_id is one
    # of the pre-existing creatures' printing_ids, NOT Mirrorpool's.
    new_token_id = next(iter(delta_added))
    new_token = next(o for o in post_bf if o["id"] == new_token_id)
    mirrorpool_printing_id = next(
        o["printing_id"] for o in pre_bf if o["id"] == mp_id
    )
    pre_p0_creature_pids = {
        o["printing_id"]
        for o in pre_bf
        if o["controller_id"] == 0 and o["id"] != mp_id
    }
    assert new_token["printing_id"] != mirrorpool_printing_id, (
        "Phase 4B C1 back-compat pin: the minted token must NOT carry "
        "Mirrorpool's own printing (which is a Land, not a Creature)"
    )
    assert new_token["printing_id"] in pre_p0_creature_pids, (
        "Phase 4B C1 back-compat pin: the minted token's printing_id "
        f"({new_token['printing_id']}) must match SOME pre-existing "
        f"p0-controlled object's printing (pool: {pre_p0_creature_pids})"
    )


def test_rust_target_validation_rejects_opponent_creature(
    engine, synthetic_state,
):
    """**Validation-arm pin — opponent's creature is NOT a legal
    target.** Activate Mirrorpool's AA[1] with
    ``target_creature_id`` set to p1's creature. The Phase 4B C1
    validation arm at
    ``state_ops_actions.rs::ActivateAbility`` MUST raise because the
    target is on the opponent's bf (Mirrorpool's printed text reads
    "target creature you control" — opponent-controlled creatures
    are NOT legal).
    """
    # Inject Mirrorpool on p0's bf.
    mp_id = synthetic_state.register_and_inject_object(
        _mirrorpool_aa1_printing_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(mp_id, False)
    # Inject a Creature on p1's bf (the opponent's).
    opp_bear_id = synthetic_state.register_and_inject_object(
        _creature_printing_dict("Synthetic Opp Bear", 4, 4),
        1, ZONE_BATTLEFIELD,
    )

    synthetic_state.add_mana(0, "C", 5)
    with pytest.raises(Exception):
        synthetic_state.apply_action({
            "kind": "activate_ability",
            "source_id": mp_id,
            "ability_index": 0,
            "target_creature_id": opp_bear_id,
        })
