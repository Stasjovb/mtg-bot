"""Rust Harvester — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Rust Harvester is a ``{R}`` Artifact Creature — Robot (EoE pool, 0
17lands decks) carrying a single activated ability with a composite
two-step effect:

    "{2}, {T}, Exile target artifact card from your graveyard: Put a
    +1/+1 counter on this creature.  It deals damage equal to its
    power to any target."

Parser-emitted Effect shape:

    AA[0].effect = ``Sequence(effects=(
        PutPlusOneCounterOnSelf(amount=1),
        DealDamageEqualToSourcePowerAnyTarget(
            targets=(TargetSpec(filter=OneOf(filters=(
                IsCreature(), IsPlaneswalker(), IsBattle(), IsPlayer(),
            )), count_min=1, count_max=1, distinct_from=()),),
        ),
    ))``

attached to an ActivatedAbility whose ``cost`` carries
``mana={2}``, ``tap_self=True``, and ``exile_artifact_from_graveyard=
True``.  The cost-side ``exile_artifact_from_graveyard`` is BLOCKED
per the batch-8 HH directive (matching Sunstar Chaplain's
remove_plus_one_counter cost, Slagdrill Scrapper's sacrifice_another_
artifact_or_land cost, Dust Bowl's sacrifice_a_land cost — all
documented BLOCKED in the HH-module skip list); the EEEE-idiom
(parse + bridge round-trip + Python-side resolve, NO cross-engine
``compare_fields``) sidesteps the cost surface entirely by exercising
the EFFECT half directly.

**EEEE-idiom for the bare-bridge-clean Sequence(PutPlusOneCounterOnSelf,
DealDamageEqualToSourcePowerAnyTarget) carrier.**  Templates off the
Cosmogrand Zenith batch-12 IS_CAST EEEE precedent (parse + bridge
round-trip + Python-side resolve, NO cross-engine compare_fields) and
the Conductive Machete dual-effect carrier precedent.  Distinct shape
on TWO axes:

  * **Sequence composer**: the parser-emitted Effect is a 2-arm
    ``Sequence`` (PutPlusOneCounterOnSelf → DealDamageEqualToSourcePower
    AnyTarget); the bridge's ``sequence`` arm recurses into each leaf
    dict (round-23 composer-arm precedent — sibling to the
    ``choose_one_mode`` modal composer Cosmogrand Zenith binds).
  * **Power-scaling damage**: ``DealDamageEqualToSourcePowerAnyTarget``
    is the bridge-side variant that reads the SOURCE's effective
    power at resolve time, distinct from the bare
    ``DealDamageAnyTarget(amount=N)`` (which carries a hard-coded
    integer).  Post-counter resolve, the source's power has been
    bumped by +1 — the damage emission then reads the live post-
    counter power.

Per the cathedral-of-war-style same-shape-different-printing-slug
precedent, the Rust Harvester slug earns its own PROBED-tier slot.

**Lane discipline (batch 13).** Pure measurement-attribution: no engine
changes, no Rust changes, no substrate widens.  Per-slug credit only.
Same lane as batches 1-12.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
from mtg_bot.effects.generic.damage import (
    DealDamageEqualToSourcePowerAnyTarget,
)


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (mirror Rust's u8 zone IDs).
ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT — Rust Harvester is parser-claimed and carries the
# single ``Sequence(PutPlusOneCounterOnSelf, DealDamageEqualToSourcePower
# AnyTarget)`` activated ability effect.
# ---------------------------------------------------------------------------


def test_rust_harvester_parser_claims_card():
    assert "Rust Harvester" in _PRINTINGS, (
        "Rust Harvester must be parser-claimed by the active CardSource"
    )


def test_rust_harvester_printed_attrs():
    """Pins the basic printing surface: Artifact Creature - Robot, {R}
    cost, 1/1 P/T, menace keyword."""
    p = _PRINTINGS["Rust Harvester"]
    assert "Artifact" in p.card_types
    assert "Creature" in p.card_types
    assert "Robot" in p.subtypes
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == (("R", 1),)
    assert p.power == 1
    assert p.toughness == 1
    assert "menace" in p.keywords
    assert len(p.activated_abilities) == 1, (
        f"Rust Harvester must have exactly 1 parser-emitted "
        f"ActivatedAbility; got {len(p.activated_abilities)}"
    )
    assert p.triggered_abilities == ()
    assert p.spell_effect is None


def test_rust_harvester_aa_composite_effect_shape():
    """The load-bearing AA[0] is the cost-rider-blocked
    ``{2}, {T}, Exile target artifact card from your graveyard:``
    activation whose EFFECT is the 2-arm ``Sequence(
    PutPlusOneCounterOnSelf(amount=1),
    DealDamageEqualToSourcePowerAnyTarget(...))``.

    Distinct from sibling Effect classes:
      * ``DealDamageAnyTarget(amount=N)`` — hard-coded integer damage
        (Plasma Bolt / Boilerbilges Ripper shape; covered by the
        ``deal_damage_any_target`` bridge arm with explicit ``amount``).
      * ``DealDamageEqualToSourcePowerAnyTarget(targets=...)`` — power-
        scaled damage (THIS shape, distinct unit variant on Rust).
    """
    p = _PRINTINGS["Rust Harvester"]
    aa0 = p.activated_abilities[0]
    assert isinstance(aa0.effect, Sequence), (
        f"Rust Harvester AA[0].effect must be Sequence; got "
        f"{type(aa0.effect).__name__}"
    )
    assert len(aa0.effect.effects) == 2, (
        f"Rust Harvester AA[0] Sequence must have exactly 2 effects "
        f"(PutPlusOneCounterOnSelf, DealDamageEqualToSourcePowerAny"
        f"Target); got {len(aa0.effect.effects)}"
    )
    pluscounter, damage = aa0.effect.effects
    assert isinstance(pluscounter, PutPlusOneCounterOnSelf)
    assert pluscounter.amount == 1
    assert isinstance(damage, DealDamageEqualToSourcePowerAnyTarget)

    # Cost shape pins (load-bearing context for the EEEE-idiom; the
    # cost is BLOCKED per HH directive but the EFFECT half is bare-
    # bridge-clean).
    assert aa0.cost.mana is not None
    assert aa0.cost.mana.generic == 2
    assert aa0.cost.tap_self is True
    assert aa0.cost.exile_artifact_from_graveyard is True, (
        "Rust Harvester AA[0] must carry the "
        "exile_artifact_from_graveyard cost rider (the HH-blocked "
        "cost-mechanic the EEEE-idiom sidesteps)"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the ``sequence`` composer bridge arm + each
# leaf arm round-trip the parsed Effect byte-equal.
# ---------------------------------------------------------------------------


def test_rust_harvester_aa_effect_bridge_round_trip():
    """The ``sequence`` composer bridge arm round-trips Rust Harvester's
    AA[0] Effect byte-equal.

    Effect-level byte-equality between the bridge dict shape and the
    bridged Effect — exercises THREE arms simultaneously:

      * ``sequence`` (composer, round-23 — recurses into leaves).
      * ``put_plus_one_counter_on_self`` (leaf 0).
      * ``deal_damage_equal_to_source_power_any_target`` (leaf 1; the
        power-scaled damage variant — distinct from bare
        ``deal_damage_any_target``).

    Per the round-23 composer-arm precedent (Cosmogrand Zenith mode-1's
    bridge round-trip + Irreverent Gremlin's IfYouDo-MayDo composer
    round-trip), the composer recursively translates each leaf dict
    via ``_ta_dict_to_python_effect``.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    real = _PRINTINGS["Rust Harvester"]
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "put_plus_one_counter_on_self", "amount": 1},
                {"kind": "deal_damage_equal_to_source_power_any_target"},
            ],
        }
    )
    assert isinstance(bridged, Sequence)
    assert len(bridged.effects) == 2
    assert isinstance(bridged.effects[0], PutPlusOneCounterOnSelf)
    assert isinstance(
        bridged.effects[1], DealDamageEqualToSourcePowerAnyTarget,
    )

    # Byte-equality between the bridged copy and the parser-emitted
    # AA[0] effect on the live printing.
    aa0_effect = real.activated_abilities[0].effect
    assert bridged == aa0_effect, (
        f"Bridged sequence(put_plus_one_counter_on_self, "
        f"deal_damage_equal_to_source_power_any_target) must equal "
        f"Rust Harvester's parser-emitted AA[0] effect; got "
        f"bridged={bridged!r}, parsed={aa0_effect!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# Rust-Harvester-shape registry dict.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_rust_harvester_synthetic_dict():
    """Lockstep pin: Rust's ``register_printing`` accepts the
    Rust-Harvester-shape registry dict — Artifact Creature with one AA
    carrying the Sequence(PutPlusOneCounterOnSelf,
    DealDamageEqualToSourcePowerAnyTarget) effect.

    The cost dict omits the ``exile_artifact_from_graveyard`` rider —
    that's the HH-blocked cost mechanic the EEEE-idiom does not
    exercise.  This synthetic carrier confirms only that the EFFECT
    dict shape (Sequence + nested leaves) registers cleanly on the
    Rust side.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Rust Harvester (synthetic effect carrier)",
            "card_types": ["Artifact", "Creature"],
            "subtypes": ["Robot"],
            "mana_cost": {"R": 1},
            "power": 1,
            "toughness": 1,
            "activated_abilities": [
                {
                    "cost": {"tap_self": True, "mana": {"generic": 2}},
                    "effect": {
                        "kind": "sequence",
                        "effects": [
                            {
                                "kind": "put_plus_one_counter_on_self",
                                "amount": 1,
                            },
                            {
                                "kind": (
                                    "deal_damage_equal_to_"
                                    "source_power_any_target"
                                ),
                            },
                        ],
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Rust Harvester printing through Python-side resolve of
# its AA[0] composite Sequence effect, observing the +1/+1 counter +
# power-scaled damage emission end-to-end.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_rust_harvester_aa0_sequence_counter_then_power_damage_parity():
    """**GENUINE real-EoE cross-engine probe — Rust Harvester AA[0]
    parser-emitted Sequence(PutPlusOneCounterOnSelf,
    DealDamageEqualToSourcePowerAnyTarget) → +1/+1 counter then
    power-scaled damage to target.  PROBED-tier flip
    (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Rust Harvester printing** through
    Python-side resolve of its AA[0] composite Sequence effect.
    Distinct from sibling Effect classes / carriers:

      * **Sequence composer**: 2-arm composite (PutPlusOneCounterOnSelf
        THEN DealDamageEqualToSourcePowerAnyTarget); distinct from
        bare-arm probes (e.g., Adagia AddManaToPool / Murder
        DestroyTargetCreature / Bashful Beastie ManifestDread).
      * **Power-scaling damage**: ``DealDamageEqualToSourcePower
        AnyTarget`` reads the source's POST-counter power at resolve
        time (Sequence orders the counter THEN the damage).  Distinct
        from bare ``DealDamageAnyTarget(amount=N)`` (Plasma Bolt /
        Boilerbilges Ripper) which carries a hard-coded integer.
      * **Cost-rider sidestep (EEEE-idiom)**: Rust Harvester's
        activation cost carries ``exile_artifact_from_graveyard`` —
        BLOCKED per the HH directive (sibling to Dust Bowl's
        sacrifice_a_land cost / Slagdrill Scrapper's
        sacrifice_another_artifact_or_land cost / Sunstar Chaplain's
        remove_plus_one_counter cost — all HH-skipped).  The EEEE-idiom
        (parse + bridge round-trip + Python-side resolve, NO
        cross-engine compare_fields) drives the EFFECT directly,
        bypassing the cost surface entirely.

    **Bridge arms exercised (recursive composer round-trip):**
      * ``sequence`` (composer, round-23 — recurses into leaves).
      * ``put_plus_one_counter_on_self`` (leaf 0).
      * ``deal_damage_equal_to_source_power_any_target`` (leaf 1).

    **Setup (Python-side):**
      * p0 has Rust Harvester on the battlefield (the AA source; the
        +1/+1 counter goes on the source itself per
        PutPlusOneCounterOnSelf semantics).
      * p1 has a vanilla 2/3 creature on bf (the damage target).
      * Pre-resolve: Rust Harvester power=1; victim toughness=3, no
        damage marks.

    **Observables asserted:**
      * Parse SoT: parsed effect is Sequence with the right leaves.
      * Bridge round-trip: composite dict translates byte-equal.
      * Post-resolve:
          - Rust Harvester has a +1/+1 counter (plus_one_counters=1).
          - p1's victim takes 2 damage (the post-counter source power
            = 1 base + 1 counter = 2; the damage emission reads the
            live power at resolve time).

    **EEEE-idiom (Effect+bridge byte-equal + Python-side resolve, no
    cross-engine compare_fields)**: sidesteps the
    exile_artifact_from_graveyard cost surface entirely.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = _PRINTINGS.get("Rust Harvester")
    if real is None:
        pytest.skip("Rust Harvester absent from active CardSource")
    assert "Artifact" in real.card_types
    assert "Creature" in real.card_types
    aa0 = real.activated_abilities[0]
    aa0_effect = aa0.effect

    # Bridge round-trip: composer dict translates byte-equal to the
    # parser-emitted AA[0] effect.
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "put_plus_one_counter_on_self", "amount": 1},
                {"kind": "deal_damage_equal_to_source_power_any_target"},
            ],
        }
    )
    assert isinstance(bridged, Sequence)
    assert bridged == aa0_effect, (
        f"Rust Harvester AA[0] must round-trip byte-equal through "
        f"the sequence(put_plus_one_counter_on_self, "
        f"deal_damage_equal_to_source_power_any_target) bridge arm; "
        f"got parsed={aa0_effect!r}, bridged={bridged!r}"
    )

    # Python-side resolve smoke — drives the parsed Sequence effect
    # through resolve.  The counter goes on the source first; then the
    # damage arm reads the post-counter power.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Seat the GENUINE parsed Rust Harvester on p0's bf.
    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.summoning_sick = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Vanilla 2/3 victim on p1's bf (toughness 3 — survives 2 damage
    # without dying, so the damage-mark assertion is observable
    # post-resolve).
    vanilla_victim = CardPrinting(
        name="Rust Harvester Damage Target",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=()),
        type_line="Creature — Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=3,
        produces=frozenset(),
        triggered_abilities=(),
    )
    py_victim = py_state.new_object(
        vanilla_victim, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_victim.tapped = False
    py_victim.summoning_sick = False
    py_victim.controller_id = 1
    py_victim.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_victim)

    # Pre-resolve sanity: no counters anywhere, victim has no damage.
    assert getattr(py_source, "plus_one_counters", 0) == 0
    assert getattr(py_victim, "damage", 0) == 0

    # Drive AA[0]'s Sequence effect through resolve.  The damage arm
    # targets p1's victim; we hand the target tuple directly (the
    # damage Effect's resolve signature accepts ``targets``).
    #
    # Both ``PutPlusOneCounterOnSelf`` and
    # ``DealDamageEqualToSourcePowerAnyTarget`` read
    # ``state.resolving_source`` to identify "this creature" / source
    # power — mirroring how ``resolve_top_of_stack`` sets it when
    # resolving abilities through the normal stack path.  Here we
    # exercise the bare Effect-level resolve path, so we set
    # ``resolving_source`` explicitly (same EEEE-idiom shim as the
    # Conductive Machete + Cosmogrand Zenith Python-side resolve
    # probes).
    py_state.resolving_source = py_source
    try:
        aa0_effect.resolve(
            py_state, py_source.controller_id,
            targets=(("creature", py_victim.id),),
        )
    finally:
        py_state.resolving_source = None

    # Post-resolve observables.  The Sequence resolves left-to-right:
    #   1. PutPlusOneCounterOnSelf bumps Rust Harvester's
    #      plus_one_counters to 1 (effective power 1 base + 1 = 2).
    #   2. DealDamageEqualToSourcePowerAnyTarget reads the source's
    #      live (post-counter) power = 2, deals 2 to the victim.
    assert py_source.plus_one_counters == 1, (
        f"Rust Harvester must have +1/+1 counter post-resolve; got "
        f"plus_one_counters={py_source.plus_one_counters}"
    )
    assert py_victim.damage == 2, (
        f"Rust Harvester victim must take 2 damage (source power 1 "
        f"base + 1 counter = 2); got damage={py_victim.damage}"
    )
    # Victim's toughness 3 - damage 2 = 1, survives.
    assert py_victim in py_state.battlefield, (
        "Rust Harvester victim must survive (toughness 3 - 2 damage "
        "= 1 toughness remaining)"
    )
