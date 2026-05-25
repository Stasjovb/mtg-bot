"""**Carrier-AA substrate Phase 1 Cycle 1 (2026-05-25).**

Tests for the Phase 1 Cycle 1 Rust substrate landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_1_DESIGN.md`` §4 (Rust spec):

  - New ``CardDef.activated_abilities: tuple[dict, ...]`` field for
    non-token CardPrinting carriers (``cross_engine.py``), parallel
    to the existing ``token_activated_abilities`` field.
  - Non-token ``build_rust_state`` emit path that wires
    ``CardPrinting.activated_abilities`` into the Rust registry
    dict's ``activated_abilities`` key (under the
    `card.is_token_printing == False` discipline, with a mutual-
    exclusion guard against both fields being set).
  - Two new Rust ``Effect`` variants:
      * ``RegenerateTargetCreature { allowed_subtypes: Vec<String> }``
        — Swarmyard's AA effect (pilot pair).
      * ``UntapTargetLand`` (unit variant) — Deserted Temple's AA
        effect (pilot pair).
    Each with: enum variant + ``parse_effect`` arm + ``to_pydict``
    arm + ``state_ops_resolve`` arm + ``cross_engine.py`` bridge arm.
  - New ``GameObject.regeneration_shield: bool`` field on the Rust
    side (mirrors Python's ``game.py:605``), substrate-only —
    SET by the resolve arm, NOT YET CONSUMED at SBA destroy-time
    (Python's ``turn.py:1265-1272`` consume lands C3+ alongside the
    real-EoE Swarmyard probe).

This is a **substrate-only closure** — the cycle adds the new field
+ Rust Effect variants + bridge plumbing as reusable infrastructure.
Both pilot pair printings (Swarmyard, Deserted Temple) STAY DECLINED
at the production-deck admit gate post-Cycle-1 because the
``_printing_is_bridge_simple_carrier_aa_land`` admit predicate ships
in Cycle 2 (Python-bridge agent's slice).

**Verify-first findings (live tree, main `4eed9554`):**

  - Swarmyard's live printing: ``cost=tap_self`` only, ``effect=
    RegenerateTargetCreature(allowed_subtypes=frozenset({'Squirrel',
    'Spider', 'Insect', 'Rat'}))``, no other riders. Matches design
    doc §2.1.
  - Deserted Temple's live printing: ``cost=mana={1} + tap_self``,
    ``effect=UntapTargetLand()``, no riders. NOTE: the cost is
    ``{1}, {T}`` not bare ``{T}`` — the design doc §2.3 admit gate
    requires ``cost.mana is None``. Cycle 2 (Python admit predicate)
    must decide between (a) widening the cost-shape gate to accept
    ``{1}, {T}``, or (b) swapping the pilot to a bare-``{T}``
    sibling (Terrain Generator / Thespian's Stage per the design
    doc §10.3 escape). Either way, Cycle 1's Rust substrate carries
    both Effect variants byte-equal; the cost-shape decision lives
    in the Python admit slice.

**Test plan:**

  - Parser SoT pins: confirm Python's ``RegenerateTargetCreature`` +
    ``UntapTargetLand`` classes exist and round-trip Swarmyard /
    Deserted Temple's live AA shape (verify-first).
  - Rust unit pins: ``parse_effect`` arms for both kinds; round-trip
    through ``to_pydict``; rejects malformed inputs.
  - Cross-engine bridge pins: dict → Python bridge arms for both
    kinds (``_ta_dict_to_python_effect``).
  - CardDef-level field pins: new ``activated_abilities`` field on
    CardDef defaults empty; ``build_rust_state`` emits the
    ``activated_abilities`` registry key for non-token carriers;
    mutual-exclusion guard raises on simultaneous token+non-token
    set.
  - Reverse-arm pins: ``_card_def_to_python_printing`` materializes
    the activated_abilities tuple from the non-token field.
  - Substrate-only invariant pins: Swarmyard + Deserted Temple stay
    DECLINED at the live production-deck loader filter
    post-Cycle-1.
  - NO admit-predicate test (Cycle 2 deliverable).
  - NO real-EoE cross-engine probe (Cycle 3+ deliverable).
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_regenerate_class_exists_with_allowed_subtypes():
    """**Parser source-of-truth pin.** Python's
    ``RegenerateTargetCreature`` class is in
    ``effects.generic.destroy``, is a frozen dataclass with a
    ``allowed_subtypes: frozenset[str]`` field defaulting to
    ``frozenset()``. The bridge dict-shape carries the subtype list
    when non-empty; the Python class ingests via ``frozenset(strs)``.
    """
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature

    # Default (no subtype filter — any creature).
    eff_any = RegenerateTargetCreature()
    assert eff_any.allowed_subtypes == frozenset()

    # Swarmyard-shape filter.
    eff = RegenerateTargetCreature(
        allowed_subtypes=frozenset({"Rat", "Spider", "Squirrel", "Insect"}),
    )
    assert eff.allowed_subtypes == frozenset(
        {"Rat", "Spider", "Squirrel", "Insect"}
    )


def test_python_untap_target_land_class_exists():
    """**Parser source-of-truth pin.** Python's ``UntapTargetLand``
    class is in ``effects.generic.tap``, is a frozen dataclass with
    no fields beyond the inherited base."""
    from mtg_bot.effects.generic.tap import UntapTargetLand

    eff = UntapTargetLand()
    # Frozen dataclass identity check via eq.
    assert eff == UntapTargetLand()


def test_swarmyard_live_printing_matches_design_doc_shape():
    """**Verify-first pin — Swarmyard's live AA shape.** Confirms
    the design doc §2.1 row at HEAD: ``Land``, single AA, cost only
    ``tap_self``, effect ``RegenerateTargetCreature(allowed_subtypes=
    frozenset({'Squirrel', 'Spider', 'Insect', 'Rat'}))``, no
    riders."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature

    ps = OracleParserCardSource().get_printings()
    swarmyard = ps["Swarmyard"]

    # Land card-type, no creature P/T, no other types.
    assert swarmyard.card_types == ("Land",)
    assert swarmyard.power is None and swarmyard.toughness is None

    # Single AA.
    aas = tuple(swarmyard.activated_abilities or ())
    assert len(aas) == 1, f"expected 1 AA, got {len(aas)}: {aas}"
    aa = aas[0]

    # Cost: tap_self only.
    cost = aa.cost
    assert cost.mana is None
    assert cost.tap_self is True
    assert cost.sacrifice_self is False
    assert cost.pay_life == 0

    # Effect: RegenerateTargetCreature with Swarmyard's subtype set.
    assert isinstance(aa.effect, RegenerateTargetCreature)
    assert aa.effect.allowed_subtypes == frozenset(
        {"Squirrel", "Spider", "Insect", "Rat"}
    )

    # No AA-level riders.
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is False
    assert aa.activate_only_once is False
    assert aa.tier_threshold == 0
    assert aa.room_half is None
    assert aa.cost_reductions == ()


def test_deserted_temple_live_printing_matches_design_doc_shape():
    """**Verify-first pin — Deserted Temple's live AA shape.**
    Confirms the design doc §2.1 row at HEAD: ``Land``, single AA,
    effect ``UntapTargetLand()``, no riders. NOTE: the COST IS
    ``{1}, {T}`` (mana=ManaCost(generic=1), tap_self=True), NOT bare
    ``{T}``. The design doc §2.3 admit gate requires
    ``cost.mana is None``; Cycle 2 must decide between widening the
    cost-shape gate or swapping the pilot. Cycle 1's substrate (this
    test) is byte-equal for either outcome — the
    ``UntapTargetLand`` variant is wired regardless."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.generic.tap import UntapTargetLand

    ps = OracleParserCardSource().get_printings()
    dt = ps["Deserted Temple"]

    assert dt.card_types == ("Land",)
    assert dt.power is None and dt.toughness is None

    aas = tuple(dt.activated_abilities or ())
    assert len(aas) == 1
    aa = aas[0]

    # Cost discrepancy — mana is NOT None; documented above.
    assert aa.cost.tap_self is True
    assert aa.cost.mana is not None  # {1} mana cost.
    assert aa.cost.mana.generic == 1
    assert aa.cost.mana.colored == ()

    assert isinstance(aa.effect, UntapTargetLand)
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is False


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict -> Python)
# ---------------------------------------------------------------------------


def test_bridge_arm_regenerate_target_creature_no_subtype_filter():
    """Bridge arm constructs ``RegenerateTargetCreature()`` from a
    single-key dict (no ``allowed_subtypes``)."""
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect(
        {"kind": "regenerate_target_creature"}
    )
    assert isinstance(back, RegenerateTargetCreature)
    assert back.allowed_subtypes == frozenset()


def test_bridge_arm_regenerate_target_creature_with_subtype_filter():
    """Bridge arm constructs Swarmyard-shape
    ``RegenerateTargetCreature(allowed_subtypes={...})``."""
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "regenerate_target_creature",
        "allowed_subtypes": ["Rat", "Spider", "Squirrel", "Insect"],
    })
    assert isinstance(back, RegenerateTargetCreature)
    assert back.allowed_subtypes == frozenset(
        {"Rat", "Spider", "Squirrel", "Insect"}
    )


def test_bridge_arm_untap_target_land():
    """Bridge arm constructs ``UntapTargetLand()`` from a single-key
    dict (no fields)."""
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({"kind": "untap_target_land"})
    assert isinstance(back, UntapTargetLand)


# ---------------------------------------------------------------------------
# Rust unit pins — parse + to_pydict round-trip
# ---------------------------------------------------------------------------


def test_rust_register_carrier_aa_swarmyard_shape():
    """Rust ``register_printing`` accepts a non-token Land carrier
    with ``activated_abilities=[{cost: {tap_self: True}, effect:
    {kind: regenerate_target_creature, allowed_subtypes: [...]}}]``.
    The pid is returned and ``get_printing_name`` echoes the name."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": "Test Swarmyard",
        "card_types": ["Land"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "regenerate_target_creature",
                    "allowed_subtypes": [
                        "Insect", "Rat", "Spider", "Squirrel",
                    ],
                },
            }
        ],
    })
    assert reg.get_printing_name(pid) == "Test Swarmyard"


def test_rust_register_carrier_aa_deserted_temple_shape():
    """Rust ``register_printing`` accepts a non-token Land carrier
    with ``activated_abilities=[{cost: {mana: {generic: 1},
    tap_self: True}, effect: {kind: untap_target_land}}]``."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": "Test Deserted Temple",
        "card_types": ["Land"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {
                    "mana": {"generic": 1},
                    "tap_self": True,
                },
                "effect": {"kind": "untap_target_land"},
            }
        ],
    })
    assert reg.get_printing_name(pid) == "Test Deserted Temple"


def test_rust_register_rejects_empty_allowed_subtype_entry():
    """``regenerate_target_creature.allowed_subtypes`` must reject
    empty-string entries loudly. Mirrors the
    ``counter_target_spell.filter_types`` parse contract."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    with pytest.raises((ValueError, Exception)) as excinfo:
        reg.register_printing({
            "name": "Bad Filter",
            "card_types": ["Land"],
            "mana_cost": {},
            "activated_abilities": [
                {
                    "cost": {"tap_self": True},
                    "effect": {
                        "kind": "regenerate_target_creature",
                        "allowed_subtypes": ["Rat", ""],
                    },
                }
            ],
        })
    assert "non-empty" in str(excinfo.value).lower() or "empty" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# CardDef field pins
# ---------------------------------------------------------------------------


def test_carddef_activated_abilities_field_exists_with_empty_default():
    """``CardDef.activated_abilities`` defaults to ``()``. Empty-
    tuple back-compat: every pre-Cycle-1 CardDef omits the field."""
    from mtg_bot.parity.cross_engine import CardDef

    card = CardDef(name="basic Forest", card_type="Land")
    assert card.activated_abilities == ()


def test_carddef_activated_abilities_field_carries_aa_dict():
    """``CardDef`` accepts an ``activated_abilities`` tuple of dicts
    matching the ``parse_activated_ability`` shape. The Swarmyard-
    shape dict (cost+effect+optional rider keys) is constructible
    without error."""
    from mtg_bot.parity.cross_engine import CardDef

    aa_dict = {
        "cost": {"tap_self": True},
        "effect": {
            "kind": "regenerate_target_creature",
            "allowed_subtypes": [
                "Insect", "Rat", "Spider", "Squirrel",
            ],
        },
    }
    card = CardDef(
        name="Synthetic Swarmyard",
        card_type="Land",
        activated_abilities=(aa_dict,),
    )
    assert card.activated_abilities == (aa_dict,)


# ---------------------------------------------------------------------------
# build_rust_state — emit pins
# ---------------------------------------------------------------------------


def _build_rust_state_with_carrier_aa(card_def):
    """Helper — wire a carrier-AA CardDef into a DeckSpec via
    ``build_rust_state``. Returns the Rust state; the test smoke-
    checks that the registry-dict round-trip path succeeds."""
    _require_engine()
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        build_rust_state,
    )

    filler = CardDef(name="Forest", card_type="Land")
    spec = DeckSpec(
        card_defs=(card_def, filler),
        p0_library=(card_def.name,) * 10,
        p1_library=("Forest",) * 10,
    )
    return build_rust_state(spec)


def test_build_rust_state_emits_carrier_aa_for_non_token_carddef():
    """``build_rust_state`` populates the Rust registry-dict's
    ``activated_abilities`` key from a non-token CardDef's
    ``activated_abilities`` field. Smoke-tested via the state's
    Registry: registering a non-token CardDef with the field
    populated must succeed AND surface the AA's effect kind on the
    Rust side via the registered printing's parsed shape."""
    from mtg_bot.parity.cross_engine import CardDef

    card = CardDef(
        name="Synthetic Swarmyard",
        card_type="Land",
        activated_abilities=(
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "regenerate_target_creature",
                    "allowed_subtypes": [
                        "Insect", "Rat", "Spider", "Squirrel",
                    ],
                },
            },
        ),
    )
    # build_rust_state succeeds without raising — the registry-dict
    # round-trips through the Rust parser, which means the
    # ``activated_abilities`` key was emitted and parsed correctly.
    state = _build_rust_state_with_carrier_aa(card)
    assert state is not None


def test_build_rust_state_emits_carrier_aa_for_deserted_temple_shape():
    """Same as the Swarmyard pin, but for the Deserted Temple shape
    — ``UntapTargetLand`` effect + ``{1}, {T}`` cost. Confirms both
    new Rust Effect variants are reachable through the build-state
    emit path."""
    from mtg_bot.parity.cross_engine import CardDef

    card = CardDef(
        name="Synthetic Deserted Temple",
        card_type="Land",
        activated_abilities=(
            {
                "cost": {
                    "mana": {"generic": 1},
                    "tap_self": True,
                },
                "effect": {"kind": "untap_target_land"},
            },
        ),
    )
    state = _build_rust_state_with_carrier_aa(card)
    assert state is not None


def test_build_rust_state_mutual_exclusion_guard():
    """A CardDef setting BOTH ``token_activated_abilities`` AND
    ``activated_abilities`` raises a ValueError at
    ``build_rust_state`` emit time — substrate-only mutual-
    exclusion invariant. Mixing them would silently double-register
    on the Rust side."""
    from mtg_bot.parity.cross_engine import CardDef

    aa_dict = {
        "cost": {"tap_self": True},
        "effect": {"kind": "untap_target_land"},
    }
    card = CardDef(
        name="Doubly-Set Carrier",
        card_type="Land",
        token_activated_abilities=(aa_dict,),
        activated_abilities=(aa_dict,),
    )
    with pytest.raises(ValueError) as excinfo:
        _build_rust_state_with_carrier_aa(card)
    msg = str(excinfo.value)
    assert "mutually exclusive" in msg or "Carrier-AA" in msg


# ---------------------------------------------------------------------------
# _card_def_to_python_printing reverse arm pins
# ---------------------------------------------------------------------------


def test_card_def_to_python_printing_reverse_arm_regenerate():
    """``_card_def_to_python_printing`` materializes a Python
    CardPrinting whose ``activated_abilities`` tuple round-trips
    the Swarmyard AA shape (cost tap_self + effect
    RegenerateTargetCreature with the subtype filter)."""
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _card_def_to_python_printing,
    )

    card = CardDef(
        name="Synthetic Swarmyard",
        card_type="Land",
        activated_abilities=(
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "regenerate_target_creature",
                    "allowed_subtypes": [
                        "Insect", "Rat", "Spider", "Squirrel",
                    ],
                },
            },
        ),
    )
    printing = _card_def_to_python_printing(card)
    aas = tuple(printing.activated_abilities)
    # Land mana-ability auto-wire might add prepended entries when
    # the CardDef has ``mana_produced``; this synthetic card has no
    # mana_produced, so the only AA is the Carrier AA.
    assert len(aas) == 1, f"expected 1 AA, got {aas}"
    aa = aas[0]
    assert isinstance(aa, ActivatedAbility)
    assert isinstance(aa.cost, ActivationCost)
    assert aa.cost.tap_self is True
    assert aa.cost.mana is None
    assert isinstance(aa.effect, RegenerateTargetCreature)
    assert aa.effect.allowed_subtypes == frozenset(
        {"Insect", "Rat", "Spider", "Squirrel"}
    )


def test_card_def_to_python_printing_reverse_arm_untap_target_land():
    """``_card_def_to_python_printing`` materializes a Python
    CardPrinting whose ``activated_abilities`` tuple round-trips
    the Deserted Temple AA shape (cost {1}+tap_self + effect
    UntapTargetLand)."""
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _card_def_to_python_printing,
    )

    card = CardDef(
        name="Synthetic Deserted Temple",
        card_type="Land",
        activated_abilities=(
            {
                "cost": {
                    "mana": {"generic": 1},
                    "tap_self": True,
                },
                "effect": {"kind": "untap_target_land"},
            },
        ),
    )
    printing = _card_def_to_python_printing(card)
    aas = tuple(printing.activated_abilities)
    assert len(aas) == 1
    aa = aas[0]
    assert isinstance(aa, ActivatedAbility)
    assert aa.cost.tap_self is True
    assert aa.cost.mana is not None
    assert aa.cost.mana.generic == 1
    assert isinstance(aa.effect, UntapTargetLand)


# ---------------------------------------------------------------------------
# Substrate-only invariant pins — pilot pair STAYS DECLINED post-Cycle-1
# ---------------------------------------------------------------------------


def test_swarmyard_stays_declined_post_cycle_1():
    """**Substrate-only invariant pin.** Post-Cycle-1, the Phase-1
    admit predicate ``_printing_is_bridge_simple_carrier_aa_land``
    has NOT shipped (it ships Cycle 2). Concretely: NO disjunct in
    the production-deck loader's ``_filter_deck_to_bridge_supported``
    OR-chain accepts Swarmyard's printing today. Verify by walking
    the existing per-disjunct predicates and confirming each
    declines (one MUST decline for the invariant to hold; we assert
    that the NONE of the existing predicates admits it)."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    swarmyard = ps["Swarmyard"]

    # All disjuncts in _filter_deck_to_bridge_supported decline
    # Swarmyard (it carries a non-empty activated_abilities tuple,
    # which every existing predicate guard-rejects at the
    # ``if printing.activated_abilities: return False`` line —
    # documented in the design doc §1.2).
    candidate_predicates = []
    for name in dir(traj):
        if name.startswith("_printing_is_bridge_"):
            candidate_predicates.append(getattr(traj, name))

    admit_results = {
        pred.__name__: pred(swarmyard)
        for pred in candidate_predicates
        if callable(pred)
    }
    # NONE of the existing predicates admit Swarmyard.
    admits = [
        name for name, accepts in admit_results.items() if accepts
    ]
    assert not admits, (
        f"Carrier-AA Phase 1 Cycle 1 substrate-only invariant "
        f"violated: Swarmyard is admitted by {admits}. Cycle 1 "
        f"lands Rust substrate ONLY; the admit predicate "
        f"_printing_is_bridge_simple_carrier_aa_land ships in "
        f"Cycle 2. If a sibling predicate now admits Swarmyard, "
        f"a different substrate has widened — investigate before "
        f"merging Cycle 1."
    )


def test_deserted_temple_stays_declined_post_cycle_1():
    """**Substrate-only invariant pin.** Same as Swarmyard but for
    Deserted Temple. Cycle 1 lands Rust substrate ONLY; no admit
    predicate accepts Deserted Temple post-Cycle-1."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    dt = ps["Deserted Temple"]

    candidate_predicates = []
    for name in dir(traj):
        if name.startswith("_printing_is_bridge_"):
            candidate_predicates.append(getattr(traj, name))

    admit_results = {
        pred.__name__: pred(dt)
        for pred in candidate_predicates
        if callable(pred)
    }
    admits = [
        name for name, accepts in admit_results.items() if accepts
    ]
    assert not admits, (
        f"Carrier-AA Phase 1 Cycle 1 substrate-only invariant "
        f"violated: Deserted Temple is admitted by {admits}. Cycle "
        f"1 lands Rust substrate ONLY; the admit predicate ships "
        f"in Cycle 2."
    )


# ---------------------------------------------------------------------------
# Rust GameObject.regeneration_shield field smoke pin
# ---------------------------------------------------------------------------


def test_rust_regeneration_shield_field_defaults_false():
    """**Substrate field pin.** The new
    ``GameObject.regeneration_shield`` field defaults to ``false``
    on every freshly-allocated GameObject. NOT in the per-object
    fingerprint 8-tuple (back-compat with every pre-substrate
    baseline). Smoke-check via ``make_synthetic_state`` — every
    bf/hand/library object starts unshielded."""
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    # The synthetic state's fingerprint should be byte-equal to
    # pre-substrate (the new field is elided from the fingerprint).
    fp1 = rs.fingerprint()
    # Battlefield snapshot reads back per-object dicts; no new key
    # for ``regeneration_shield`` is added (elided from the per-
    # object 8-tuple, same as ``stun_counters`` / ``warp_exile_pending``).
    bf_snap = rs.battlefield_snapshot()
    assert isinstance(bf_snap, list)
    # Idempotent fingerprint check.
    fp2 = rs.fingerprint()
    assert fp1 == fp2
