"""Haunted Screen -- HONEST-STOP diagnosis pin (stays BLOCKED).

**Outcome (2026-05-31): honest-stop, NOT flipped.** Haunted Screen is a
``{3}`` Artifact (DSK) carrying THREE activated abilities. A full
BLOCKED -> PROBED flip is gated by the Carrier-AA multi-AA *all-or-
nothing* admit contract: every AA must independently pass
``_aa_is_phase1_sub_shape_a``. Verify-first dump of the actual parsed
printing (``get_active_source().get_printings()["Haunted Screen"]``)
found THREE independent substrate walls, two of which require sprawling
new Rust machinery that cannot be made byte-equal-representable without a
broad refactor. Per the campaign honest-stop policy, this slice does NOT
force a fragile flip and does NOT widen any shared admit predicate.

The three AAs (verified shapes):

  * **AA[0]** -- ``{T}: Add {W} or {B}.``
        cost   = tap_self=True, no mana
        effect = ``AddNManaOfChosenColor(amount=1, options=("W","B"))``
        is_mana_ability = True
    -> **ALREADY ADMITS** at the per-AA gate. ``AddNManaOfChosenColor``
       is in the Carrier-AA Effect-class admit set; the bare-``{T}``
       mana-ability cost + ``is_mana_ability=True`` rider both clear
       the per-AA gate (Phase 4E C2 lifted ``is_mana_ability``).

  * **AA[1]** -- ``{T}, Pay 1 life: Add {G}, {U}, or {R}.``
        cost   = tap_self=True, pay_life=1, no mana
        effect = ``AddNManaOfChosenColor(amount=1, options=("G","U","R"))``
        is_mana_ability = True
    -> **WALL #1: ``pay_life`` AA-cost component.** The per-AA cost gate
       ``_aa_is_phase1_sub_shape_a`` honest-declines ``cost.pay_life !=
       0`` (the ``if cost.pay_life: return False`` arm). The Rust
       ``ActivationCost`` struct (``rust/src/cards.rs:11437``) has NO
       ``pay_life`` field at all -- only ``mana`` / ``tap_self`` /
       ``sacrifice_self`` / ``sacrifice_a_desert`` -- and
       ``parse_activation_cost`` (``cards.rs:18850``) accepts only those
       keys. The Rust AA legal-emit (``state_ops_legal.rs``) and cost-
       pay (``state_ops_actions.rs``) carry NO life-payment leg for
       activated abilities (the ``pay_life_cost`` helper at
       ``state_ops_life.rs:108`` exists but is unwired to AA activation).
       Closing WALL #1 needs: a new ``ActivationCost.pay_life: i32``
       field + parse arm + a legal-emit life-availability gate + a
       cost-pay life-deduction commit + a cross-engine AA-cost
       serializer/deserializer arm. Substantial new Rust cost-shape
       machinery.

  * **AA[2]** -- ``{7}: Put seven +1/+1 counters on this artifact. It
       becomes a 0/0 Spirit creature in addition to its other types.
       Activate only once.``
        cost   = mana={7}, tap_self=False
        effect = ``Sequence(PutPlusOneCounterOnSelf(amount=7),
                  BecomeType(types_to_add=("creature",),
                  subtypes_to_add=("Spirit",), base_pt=(0, 0)))``
        activate_only_once = True
    -> **WALL #2: permanent ``BecomeType`` type-layer.** The Rust engine
       has NO permanent per-object type-change substrate. ``Effect::
       BecomeType`` does not exist (the parser rejects the
       ``"become_type"`` kind -- ``unknown effect kind``). Rust's
       ``is_creature_now`` (``state_ops_combat.rs:319``) reads ONLY the
       object's *printing* ``card_types`` (+ station threshold); there
       is no added-types / added-subtypes / base-PT override registry an
       effect could write. The ONE existing "becomes a creature" path
       (``Effect::BecomeLandCreatureUEOT`` ->
       ``UeotModifier::BecomesLandCreature``) is **UEOT only** -- it
       auto-expires at the next cleanup via the CR 514.3 clear pass.
       Haunted Screen's ``BecomeType`` is **permanent**
       (``expires_at=None`` -- persists until the artifact leaves
       play), which has no Rust analogue. Worse, the cross-engine
       ``battlefield_snapshot`` (``state_ops_snapshot.rs``) does not
       even surface ``subtypes`` / ``card_types`` / ``is_creature``, so
       a "became a Spirit creature" change is NOT byte-equal-observable
       on the current snapshot surface at all. Closing WALL #2 needs:
       new permanent per-object ``added_types`` / ``added_subtypes`` /
       ``base_pt_override`` fields + every ``is_creature_now`` /
       subtype-reader / effective-P/T reader consulting them + a leave-
       play reset + a new snapshot surface for byte-equal observability
       + a new ``Effect::BecomeType`` variant (parse / to_pydict /
       resolve / bridge arms). This is exactly the "sprawling type-layer
       machinery that can't byte-equal" the honest-stop policy names.

    -> **WALL #3: ``activate_only_once`` AA rider.** The per-AA rider
       gate ``_aa_is_phase1_sub_shape_a`` honest-declines
       ``aa.activate_only_once`` (the ``if aa.activate_only_once:
       return False`` arm). The Rust ``ActivatedAbility`` struct carries
       NO ``activate_only_once`` slot (``cards.rs:11431`` /
       ``cards.rs:11871`` explicitly defer it), so there is no
       round-tripping field, no per-object once-only latch
       (Python's ``has_activated_once_only_ability``), and no legal-emit
       gate filtering the second activation. Closing WALL #3 needs:
       a new ``ActivatedAbility.activate_only_once: bool`` field +
       parse / round-trip + a per-object latch + a legal-emit gate +
       cross-engine bridge arms.

**Why no admit-set widen this slice.** The one tractable amortizing
piece -- adding ``PutPlusOneCounterOnSelf`` to the Carrier-AA Effect-
class admit set (its Rust ``Effect::PutPlusOneCounterOnSelf`` variant +
parse + to_pydict + resolve + reverse bridge arm ALL already live on
main; it is observable byte-equal via the ``counters`` snapshot field)
-- CANNOT flip Haunted Screen alone (AA[1]'s ``pay_life`` and AA[2]'s
``BecomeType`` + ``activate_only_once`` still bite under the all-or-
nothing contract). AND landing it in isolation would silently change
the loader-admit *path* of an already-covered card: **Intrepid
Tenderfoot** (single-type Creature, fixed 2/2, single ``{3}`` no-tap
``PutPlusOneCounterOnSelf`` AA, no other riders) would newly pass
``_printing_is_bridge_simple_carrier_aa_creature`` and admit through the
Carrier-AA path it does not use today. (Rust Harvester stays declined --
its Sequence's second leaf ``DealDamageEqualToSourcePowerAnyTarget`` is
not in the admit set.) Perturbing an already-PROBED card's admit path
without a probe verifying the new path is byte-equal is the silent
auto-grow the campaign discipline forbids, so the widen is deferred.

These tests pin the verified diagnosis so the BLOCKED characterization
is regression-tested. This file is deliberately NOT a ``*_parity.py``
credit-eligible probe and is NOT registered in
``scripts/measure_pool_parity.py`` ``PROBE_MODULES`` (mirrors the
``atomic_microsizer`` honest-stop attribution-pin precedent) -- Haunted
Screen remains in the BLOCKED -- subsystem-gated / Effect-uncovered
tier; this slice grants ZERO free PROBED flips.
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


# ---------------------------------------------------------------------------
# (1) Verify-first: the actual parsed printing shape.
# ---------------------------------------------------------------------------


def test_haunted_screen_claimed_and_artifact():
    assert "Haunted Screen" in _PRINTINGS
    p = _PRINTINGS["Haunted Screen"]
    assert p.card_types == ("Artifact",)
    assert p.power is None and p.toughness is None
    assert len(p.activated_abilities) == 3


def test_haunted_screen_aa_shapes():
    """Pins the three AAs' verified cost + effect shapes."""
    from mtg_bot.effects import (
        AddNManaOfChosenColor,
        BecomeType,
        PutPlusOneCounterOnSelf,
        Sequence,
    )

    p = _PRINTINGS["Haunted Screen"]
    aa0, aa1, aa2 = p.activated_abilities

    # AA[0]: {T}: Add W or B.
    assert aa0.cost.tap_self is True
    assert aa0.cost.pay_life == 0
    assert aa0.cost.mana is None
    assert aa0.is_mana_ability is True
    assert isinstance(aa0.effect, AddNManaOfChosenColor)
    assert aa0.effect.options == ("W", "B")

    # AA[1]: {T}, Pay 1 life: Add G, U, or R.
    assert aa1.cost.tap_self is True
    assert aa1.cost.pay_life == 1
    assert aa1.is_mana_ability is True
    assert isinstance(aa1.effect, AddNManaOfChosenColor)
    assert aa1.effect.options == ("G", "U", "R")

    # AA[2]: {7}: Sequence(+7 counters, BecomeType 0/0 Spirit creature).
    assert aa2.cost.mana_str == "{7}"
    assert aa2.cost.tap_self is False
    assert aa2.activate_only_once is True
    assert isinstance(aa2.effect, Sequence)
    counters, become = aa2.effect.effects
    assert isinstance(counters, PutPlusOneCounterOnSelf)
    assert counters.amount == 7
    assert isinstance(become, BecomeType)
    assert become.types_to_add == ("creature",)
    assert become.subtypes_to_add == ("Spirit",)
    assert become.base_pt == (0, 0)


# ---------------------------------------------------------------------------
# (2) The three walls -- per-AA admit predicate diagnosis.
# ---------------------------------------------------------------------------


def test_haunted_screen_aa0_admits():
    """AA[0] (mana W/B) ALREADY passes the per-AA gate."""
    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa0 = _PRINTINGS["Haunted Screen"].activated_abilities[0]
    assert _aa_is_phase1_sub_shape_a(aa0) is True


def test_haunted_screen_aa1_declines_on_pay_life():
    """WALL #1: AA[1] declines purely on the ``pay_life`` cost component.

    Proven by isolating the variable: the same AA with ``pay_life``
    cleared to 0 ADMITS, so ``pay_life`` is the sole per-AA blocker.
    """
    import dataclasses

    from mtg_bot.parity.trajectory import _aa_is_phase1_sub_shape_a

    aa1 = _PRINTINGS["Haunted Screen"].activated_abilities[1]
    assert aa1.cost.pay_life == 1
    assert _aa_is_phase1_sub_shape_a(aa1) is False

    # Clear pay_life -> the AA now admits (every other field already
    # clears: bare {T} mana-ability, no other riders).
    no_life_cost = dataclasses.replace(aa1.cost, pay_life=0)
    no_life_aa = dataclasses.replace(aa1, cost=no_life_cost)
    assert _aa_is_phase1_sub_shape_a(no_life_aa) is True


def test_haunted_screen_aa2_declines_on_effect_and_once_rider():
    """WALL #2 + #3: AA[2] declines on BOTH the Sequence Effect-class
    teeth (``BecomeType`` not admitted) AND the ``activate_only_once``
    rider."""
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _carrier_aa_effect_class_admitted,
    )

    aa2 = _PRINTINGS["Haunted Screen"].activated_abilities[2]
    assert aa2.activate_only_once is True
    assert _aa_is_phase1_sub_shape_a(aa2) is False
    # The Sequence's BecomeType leaf is NOT in the admit set -> the
    # whole Sequence declines at the Effect-class gate.
    assert _carrier_aa_effect_class_admitted(aa2.effect) is False


def test_haunted_screen_becometype_not_in_admit_set():
    """``BecomeType`` is the genuinely-uncovered Effect class -- it is
    NOT in the Carrier-AA Phase-1 Effect-class admit set (no Rust
    variant)."""
    from mtg_bot.effects import BecomeType
    from mtg_bot.parity.trajectory import _carrier_aa_phase_1_effect_classes

    assert BecomeType not in _carrier_aa_phase_1_effect_classes()


def test_haunted_screen_stays_blocked_at_loader_admit_gate():
    """**The honest-stop invariant.** Haunted Screen does NOT admit at
    the loader admit gate -- it remains BLOCKED."""
    from mtg_bot.parity.trajectory import (
        _filter_deck_to_bridge_supported,
        _printing_is_bridge_simple_carrier_aa_any,
    )

    p = _PRINTINGS["Haunted Screen"]
    assert _printing_is_bridge_simple_carrier_aa_any(p) is False
    filt, defs = _filter_deck_to_bridge_supported(["Haunted Screen"], _PRINTINGS)
    assert filt == []
    assert defs == []


# ---------------------------------------------------------------------------
# (3) WALL #2 substrate-absence pin -- Rust rejects the BecomeType kind.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_rejects_become_type_effect_kind():
    """Pins the Rust substrate gap: ``Effect::BecomeType`` does not
    exist; ``register_printing`` rejects the ``"become_type"`` effect
    kind. This is the load-bearing WALL #2 fact."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    with pytest.raises(Exception) as excinfo:
        reg.register_printing(
            {
                "name": "X",
                "card_types": ["Artifact"],
                "mana_cost": {"generic": 3},
                "activated_abilities": [
                    {
                        "cost": {"mana": {"generic": 7}},
                        "effect": {
                            "kind": "become_type",
                            "types_to_add": ["creature"],
                            "subtypes_to_add": ["Spirit"],
                            "base_pt": [0, 0],
                        },
                        "is_mana_ability": False,
                    }
                ],
            }
        )
    assert "become_type" in str(excinfo.value)
    assert "unknown effect kind" in str(excinfo.value)
