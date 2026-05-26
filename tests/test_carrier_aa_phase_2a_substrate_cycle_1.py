"""**Carrier-AA substrate Phase 2a Cycle 1 (2026-05-25).**

Tests for the Phase 2a Cycle 1 Rust substrate landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_2_DESIGN.md`` §4 (Rust spec).

Deliverables (Cycle 1 Rust slice, per design doc Section 4):

  - New Rust ``Effect`` variant on ``cards.rs::Effect``:
      * ``ReturnTargetLandFromGraveyardToHand`` (unit variant) —
        Petrified Field's AA effect (pilot card).
    With: enum variant + ``parse_effect`` arm + ``to_pydict`` arm
    + ``state_ops_resolve`` resolve arm + ``cross_engine.py`` bridge
    dict->Python arm (``_ta_dict_to_python_effect``) + forward
    Python->dict arm (``_python_aa_to_safe_dict``).
  - ZERO new Rust cost-shape machinery — Lander's ``{2}, Sac:``
    token-AA precedent already wired ``ActivationCost.sacrifice_self``
    + parse arm + cost-pay commit at ``state_ops_actions.rs:1300-1391``
    (Phase 5b sacrifice_self commit).

This is a **substrate-only closure** — the cycle adds the new Rust
Effect variant + bridge plumbing as reusable infrastructure. The
pilot card (Petrified Field) STAYS DECLINED at the production-deck
admit gate post-Cycle-1 because the Python admit predicate
``_aa_is_phase1_sub_shape_a`` cost-gate still declines
``sacrifice_self=True`` (Cycle 2 ships that widen).

**Verify-first findings (live tree, main `62e10ff9`):**

  - Petrified Field's live oracle text (Stellar Sights set):
    ``{T}: Add {C}.`` then ``{T}, Sacrifice this land: Return
    target land card from your graveyard to your hand.``
    Parser body whitelist at
    ``src/mtg_bot/cards/parser/land_builder.py:1130-1134`` maps the
    second line to ``ReturnTargetLandFromGraveyardToHand()`` with
    ``ActivationCost(tap_self=True, sacrifice_self=True)`` —
    matches design doc §2.1.
  - Lander precedent for ``sacrifice_self`` cost: confirmed in
    ``rust/src/state_ops_actions.rs:1344-1391`` (Phase 5b commit
    path) — sacs source to controller's graveyard, drains
    pending_leaves, ZERO new cost-shape machinery needed.
  - No existing ``Effect::Return*LandFromGraveyard*`` Rust variant
    (``rust/src/cards.rs``) — confirmed via grep on
    ``Land.*Graveyard|Graveyard.*Land``. ``ReturnUpToNNonlandPermanent
    CardsFromGraveyardToHand`` exists (Pull Through the Weft) but
    targets nonland permanents specifically; orthogonal.

**Test plan:**

  - Parser SoT pin: confirm Python's ``ReturnTargetLandFromGraveyardToHand``
    class exists in ``effects.generic.bounce`` and round-trips byte-
    equal.
  - Verify-first pin: confirm Petrified Field's live AA shape
    (``{T}, Sac:`` cost + ``ReturnTargetLandFromGraveyardToHand``
    effect, no riders).
  - Rust unit pins: ``parse_effect`` arm via ``register_printing``
    round-trip; ``to_pydict`` arm via the bridge inverse.
  - Cross-engine bridge pins: dict -> Python bridge arm
    (``_ta_dict_to_python_effect``), Python -> dict forward arm
    (``_python_aa_to_safe_dict``).
  - Resolve arm pin: synthetic state with Petrified-Field-shape
    source + pre-staged Forest in controller's graveyard; apply
    ``activate_ability`` action; resolve_top_of_stack moves the
    Forest from graveyard to hand (source already sac'd by Phase
    5b cost-pay path).
  - Substrate-only invariant pin: Petrified Field STAYS DECLINED at
    the live production-deck loader filter post-Cycle-1 (the cost
    gate ``_aa_is_phase1_sub_shape_a`` declines
    ``sacrifice_self=True``; Cycle 2 ships the widen).
"""

from __future__ import annotations

import importlib.util

import pytest


# Zone constants — mirror ``rust/src/state_ops_zones.rs``.
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


@pytest.fixture
def engine():
    """The ``mtg_bot_engine`` module, or skip if not installed.

    Local fixture — ``tests_rust/`` has a sibling fixture in
    ``conftest.py`` but ``tests/`` doesn't share that conftest.
    """
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    import mtg_bot_engine
    return mtg_bot_engine


@pytest.fixture
def synthetic_state(engine):
    """A default synthetic state — 10 battlefield, 7 hand, 50 library
    per side. Mirrors ``tests_rust/conftest.py``'s shared fixture for
    the AA resolve-arm pins that need a populated state."""
    return engine.make_synthetic_state()


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_return_target_land_from_graveyard_to_hand_class_exists():
    """**Parser source-of-truth pin.** Python's
    ``ReturnTargetLandFromGraveyardToHand`` class is in
    ``effects.generic.bounce`` (a ``ReturnFromGraveyard`` subclass),
    is a frozen dataclass with no constructor args; ``__post_init__``
    stamps ``land=True``, ``destination='hand'``,
    ``target_kind='graveyard_land'``, ``log_suffix='(Petrified Field)'``.
    """
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard

    eff = ReturnTargetLandFromGraveyardToHand()
    # Subclass invariant.
    assert isinstance(eff, ReturnFromGraveyard)
    # Frozen-dataclass identity check.
    assert eff == ReturnTargetLandFromGraveyardToHand()
    # __post_init__ field stamps — design doc §4.1 contract.
    assert eff.land is True
    assert eff.destination == "hand"
    assert eff.target_kind == "graveyard_land"
    assert eff.log_suffix == "(Petrified Field)"


def test_petrified_field_live_printing_matches_design_doc_shape():
    """**Verify-first pin — Petrified Field's live AA shape.**
    Confirms the design doc §2.1 row at HEAD: ``Land``, single AA,
    cost ``tap_self=True`` AND ``sacrifice_self=True`` (no mana,
    no other cost riders), effect
    ``ReturnTargetLandFromGraveyardToHand``, no AA-level riders.

    NOTE: this shape contains the ``{T}, Sac:`` cost — the Cycle-1
    admit predicate ``_aa_is_phase1_sub_shape_a`` still DECLINES
    ``sacrifice_self=True`` (Cycle 2 ships the widen). Substrate-only
    invariant: Petrified Field stays DECLINED at the loader filter
    post-Cycle-1.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )

    ps = OracleParserCardSource().get_printings()
    pf = ps["Petrified Field"]

    # Land card-type, no creature P/T.
    assert pf.card_types == ("Land",)
    assert pf.power is None and pf.toughness is None

    # Single AA on the carrier surface. Petrified Field's parsed
    # printing also carries the leading ``{T}: Add {C}.`` mana ability
    # as a SECOND AA via the parser's two-line builder
    # (``land_builder.py``). The Phase-1/1.5a admit predicate gates on
    # ``n_aa != 1`` AND on mana-ability flag — here, find the Carrier
    # AA by filtering ``is_mana_ability=False``.
    aas = [
        aa for aa in (pf.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    assert len(aas) == 1, (
        f"expected 1 non-mana AA on Petrified Field, got {len(aas)}: "
        f"{aas}"
    )
    aa = aas[0]

    # Cost: tap_self + sacrifice_self, no mana.
    cost = aa.cost
    assert cost.tap_self is True
    assert cost.sacrifice_self is True
    assert cost.mana is None
    # Other cost fields default.
    assert cost.pay_life == 0
    assert cost.exile_self is False
    assert cost.sacrifice_a_land is False
    assert cost.sacrifice_a_desert is False
    assert cost.sacrifice_another_creature_or_artifact is False

    # Effect: ReturnTargetLandFromGraveyardToHand.
    assert isinstance(aa.effect, ReturnTargetLandFromGraveyardToHand)

    # No AA-level riders (verify-first contract).
    assert aa.is_mana_ability is False
    assert aa.sorcery_speed is False
    assert aa.activate_only_once is False
    assert aa.tier_threshold == 0
    assert aa.room_half is None
    assert aa.cost_reductions == ()


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict -> Python)
# ---------------------------------------------------------------------------


def test_bridge_arm_return_target_land_from_graveyard_to_hand():
    """Bridge arm constructs ``ReturnTargetLandFromGraveyardToHand()``
    from a single-key dict (no fields)."""
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect(
        {"kind": "return_target_land_from_graveyard_to_hand"}
    )
    assert isinstance(back, ReturnTargetLandFromGraveyardToHand)
    # Post-init flags survive the round-trip (since the class stamps
    # them in __post_init__, every fresh instance has them set).
    assert back.land is True
    assert back.destination == "hand"
    assert back.target_kind == "graveyard_land"


def test_python_aa_to_safe_dict_forward_arm_round_trips_petrified_shape():
    """**Forward emit pin.** A synthetic Petrified-Field-shape
    ``ActivatedAbility`` serializes through ``_python_aa_to_safe_dict``
    to a dict carrying:

      * ``cost``: ``{"tap_self": True, "sacrifice_self": True}``
      * ``effect``: ``{"kind": "return_target_land_from_graveyard_to_hand"}``

    Round-trip invariant: feeding the dict back into
    ``_aa_dict_to_python_activated_ability`` produces a byte-equal
    AA at the dataclass ``__eq__`` surface (no missing fields,
    no spurious fields).

    Cycle-1 substrate-only: this round-trip succeeds, but
    ``_aa_is_phase1_sub_shape_a`` (admit predicate) still declines
    Petrified Field on the ``sacrifice_self`` cost-gate clause —
    Cycle 2 ships the widen.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True, sacrifice_self=True),
        effect=ReturnTargetLandFromGraveyardToHand(),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None, (
        "Petrified Field AA shape must round-trip through the bridge "
        "floor — Cycle 1 widens the forward emit even though the "
        "admit predicate keeps it DECLINED."
    )
    assert d["cost"] == {"tap_self": True, "sacrifice_self": True}
    assert d["effect"] == {
        "kind": "return_target_land_from_graveyard_to_hand",
    }
    # Reverse round-trip — byte-equal at the dataclass __eq__ surface.
    back = _aa_dict_to_python_activated_ability(d)
    assert back == aa


def test_python_aa_to_safe_dict_declines_non_admitted_returnfromgraveyard():
    """**isinstance-specificity pin.** The forward emit arm matches
    SPECIFICALLY on ``ReturnTargetLandFromGraveyardToHand``, NOT on
    the parent ``ReturnFromGraveyard``. A sibling subclass (e.g.
    ``ReturnUpToNNonlandPermanentCardsFromGraveyardToHand`` at
    ``bounce.py:441``) must DECLINE — emitting it under
    ``return_target_land_from_graveyard_to_hand`` would silently
    widen the admit set to non-Phase-2a effects.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.bounce import (
        ReturnUpToNNonlandPermanentCardsFromGraveyardToHand,
    )
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    # Sibling subclass — also a ReturnFromGraveyard, but NOT in the
    # Phase-2a Cycle-1 admit set. Must decline.
    aa = ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=ReturnUpToNNonlandPermanentCardsFromGraveyardToHand(
            min_n=0, max_n=2,
        ),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is None, (
        "Sibling ReturnFromGraveyard subclass must decline the "
        "forward emit — Phase-2a admit set is specifically the "
        "target-land single-card variant."
    )


# ---------------------------------------------------------------------------
# Rust unit pins — parse + to_pydict round-trip
# ---------------------------------------------------------------------------


def test_rust_register_carrier_aa_petrified_field_shape():
    """**Rust parse arm pin.** ``register_printing`` accepts a non-token
    Land carrier with ``activated_abilities=[{cost: {tap_self: True,
    sacrifice_self: True}, effect: {kind:
    return_target_land_from_graveyard_to_hand}}]``. The pid is
    returned and ``get_printing_name`` echoes the name. The parse
    arm round-trips the new ``ReturnTargetLandFromGraveyardToHand``
    Effect variant.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({
        "name": "Test Petrified Field",
        "card_types": ["Land"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {"tap_self": True, "sacrifice_self": True},
                "effect": {
                    "kind": "return_target_land_from_graveyard_to_hand",
                },
            }
        ],
    })
    assert reg.get_printing_name(pid) == "Test Petrified Field"


def test_rust_register_carrier_aa_extra_dict_keys_silently_dropped():
    """Unit-variant contract: ``return_target_land_from_graveyard_to_hand``
    parse arm silently drops extra dict keys (no field validation).
    Mirrors the ``untap_target_land`` sibling at
    ``cards.rs:12586-12588`` (unit variants accept-and-ignore extras).
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    # Extra key ``spurious_field`` shouldn't raise — unit variant
    # contract per design doc §4.1.
    pid = reg.register_printing({
        "name": "Test Petrified With Extras",
        "card_types": ["Land"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {"tap_self": True, "sacrifice_self": True},
                "effect": {
                    "kind": "return_target_land_from_graveyard_to_hand",
                    "spurious_field": 42,
                },
            }
        ],
    })
    assert reg.get_printing_name(pid) == "Test Petrified With Extras"


# ---------------------------------------------------------------------------
# CardDef + build_rust_state — emit pins
# ---------------------------------------------------------------------------


def _build_rust_state_with_carrier_aa(card_def):
    """Helper — wire a carrier-AA CardDef into a DeckSpec via
    ``build_rust_state``. Returns the Rust state."""
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


def test_build_rust_state_emits_carrier_aa_for_petrified_field_shape():
    """``build_rust_state`` populates the Rust registry-dict's
    ``activated_abilities`` key from a non-token CardDef carrying
    a ``ReturnTargetLandFromGraveyardToHand`` AA dict. Confirms the
    new Rust Effect variant is reachable through the build-state
    emit path."""
    from mtg_bot.parity.cross_engine import CardDef

    card = CardDef(
        name="Synthetic Petrified Field",
        card_type="Land",
        activated_abilities=(
            {
                "cost": {"tap_self": True, "sacrifice_self": True},
                "effect": {
                    "kind": "return_target_land_from_graveyard_to_hand",
                },
            },
        ),
    )
    state = _build_rust_state_with_carrier_aa(card)
    assert state is not None


def test_card_def_to_python_printing_reverse_arm_petrified_field():
    """``_card_def_to_python_printing`` materializes a Python
    CardPrinting whose ``activated_abilities`` tuple round-trips the
    Petrified Field AA shape (cost tap_self + sacrifice_self + effect
    ReturnTargetLandFromGraveyardToHand)."""
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _card_def_to_python_printing,
    )

    card = CardDef(
        name="Synthetic Petrified Field",
        card_type="Land",
        activated_abilities=(
            {
                "cost": {"tap_self": True, "sacrifice_self": True},
                "effect": {
                    "kind": "return_target_land_from_graveyard_to_hand",
                },
            },
        ),
    )
    printing = _card_def_to_python_printing(card)
    aas = tuple(printing.activated_abilities)
    # Synthetic card has no ``mana_produced``, so only the carrier AA
    # is materialized (no mana-ability auto-prepend).
    assert len(aas) == 1, f"expected 1 AA, got {aas}"
    aa = aas[0]
    assert isinstance(aa, ActivatedAbility)
    assert isinstance(aa.cost, ActivationCost)
    assert aa.cost.tap_self is True
    assert aa.cost.sacrifice_self is True
    assert aa.cost.mana is None
    assert isinstance(aa.effect, ReturnTargetLandFromGraveyardToHand)


# ---------------------------------------------------------------------------
# Rust resolve arm pin — end-to-end activation drives the new resolve arm
# ---------------------------------------------------------------------------


def _synthetic_petrified_field_dict():
    """Minimal Petrified-Field-shape printing dict for the Rust
    Registry. Land card-type, single AA carrying the
    ``{T}, Sac:`` cost + ``ReturnTargetLandFromGraveyardToHand`` effect.

    No ``mana_produced`` (so the parser's mana-ability auto-prepend
    doesn't fire). The carrier AA sits at ability_index=0.

    Mirrors the design doc §4.1 Rust shape exactly.
    """
    return {
        "name": "Synthetic Petrified Field",
        "card_types": ["Land"],
        "mana_cost": {},
        "activated_abilities": [
            {
                "cost": {"tap_self": True, "sacrifice_self": True},
                "effect": {
                    "kind": "return_target_land_from_graveyard_to_hand",
                },
                "is_mana_ability": False,
            }
        ],
    }


def _forest_dict():
    """Minimal Forest-shape Land printing — Land card-type, no AA.
    Used as the target Land card pre-staged in the controller's
    graveyard for the resolve arm pin.
    """
    return {
        "name": "Test Forest",
        "card_types": ["Land"],
        "mana_cost": {},
    }


def test_resolve_return_target_land_moves_first_land_from_graveyard_to_hand(
    synthetic_state,
):
    """**Resolve arm pin — substrate end-to-end.** A synthetic
    Petrified-Field-shape source on player-0's battlefield + a Forest
    pre-staged in player-0's graveyard. Activating the AA via
    ``apply_action`` then resolving the stack moves the Forest from
    graveyard to hand and the source (Petrified Field) sits in the
    graveyard (Phase 5b sacrifice_self cost-pay committed before the
    effect fires).

    **Substrate-fallback path.** The action shape carries no
    explicit graveyard-target key (the legal-emit fan-out for
    graveyard-Land targets is C2 follow-up, per design doc §4.1.2
    deferral and Phase 1 C1 precedent). The resolve arm's
    substrate-fallback walks the source-controller's graveyard
    front-to-back for the first Land match — under this test setup,
    that's the pre-staged Forest.

    **Cycle 1 substrate-only invariant.** This test exercises a
    SYNTHETIC printing — Petrified Field's REAL printing stays
    DECLINED at the production loader gate post-Cycle-1 (admit
    predicate cost-gate still rejects ``sacrifice_self=True``).
    """
    # Inject the Petrified-Field-shape source onto p0's bf and a
    # Forest into p0's graveyard.
    pf_id = synthetic_state.register_and_inject_object(
        _synthetic_petrified_field_dict(),
        0,  # controller
        ZONE_BATTLEFIELD,
    )
    forest_id = synthetic_state.register_and_inject_object(
        _forest_dict(),
        0,  # controller
        ZONE_GRAVEYARD,
    )
    # Non-creature lands are not summoning-sick (CR 302.1 only applies
    # to creatures), but force-set False defensively to match the
    # tap-and-sac precedent pattern.
    synthetic_state.force_set_summoning_sick(pf_id, False)

    # Snapshot pre-state.
    gy_before = synthetic_state.graveyard_sizes[0]
    hand_before = synthetic_state.hand_sizes[0]
    bf_before = synthetic_state.battlefield_sizes[0]

    # Activate the AA. The cost path: Phase 5 taps the source (tap_self),
    # Phase 5b sacrifices the source to the controller's graveyard
    # (sacrifice_self). Then a StackItem is pushed (is_mana_ability=False).
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pf_id,
        "ability_index": 0,
    })

    # Source is now in p0's graveyard; bf shrunk by 1; gy grew by 1
    # (the sac'd source). The Forest is still in p0's gy (pre-resolve).
    bf_post_sac = synthetic_state.battlefield_snapshot()
    assert not any(o["id"] == pf_id for o in bf_post_sac), (
        "Petrified Field source should be off bf after Phase 5b "
        "sacrifice_self commit"
    )
    assert synthetic_state.battlefield_sizes[0] == bf_before - 1
    assert synthetic_state.graveyard_sizes[0] == gy_before + 1
    # Stack carries the queued effect resolution.
    assert synthetic_state.stack_size() == 1

    # Resolve the stack — the resolve arm scans p0's graveyard front-
    # to-back for the first Land. The Forest was injected BEFORE the
    # source sac'd (front of the graveyard); the source is at the back.
    # Substrate-fallback picks the front = the Forest.
    synthetic_state.resolve_top_of_stack()

    # The Forest is now in p0's hand. The source stays in p0's gy
    # (Petrified Field doesn't return ITSELF — it returns a DIFFERENT
    # land card from the graveyard).
    hand_post = synthetic_state.hand_snapshot(0)
    assert any(o["id"] == forest_id for o in hand_post), (
        f"Forest (id={forest_id}) should be in p0's hand after resolve; "
        f"got hand={hand_post}"
    )
    # Net zone deltas: gy=gy_before+1-1=gy_before (source IN, forest OUT),
    # hand=hand_before+1.
    assert synthetic_state.hand_sizes[0] == hand_before + 1
    assert synthetic_state.graveyard_sizes[0] == gy_before
    # Source remains in p0's gy after resolve.
    gy_post = synthetic_state.graveyard_snapshot(0)
    assert any(o["id"] == pf_id for o in gy_post), (
        "Petrified Field source should remain in p0's graveyard "
        "(sac'd by cost-pay, NOT moved by the effect — the effect "
        "moves a DIFFERENT Land card to hand)."
    )
    # Stack empty after resolve.
    assert synthetic_state.is_stack_empty()


def test_resolve_return_target_land_silent_fizzle_on_empty_graveyard(
    synthetic_state,
):
    """**Resolve arm — silent fizzle pin.** A synthetic Petrified-Field-
    shape source activates with NO Land card pre-staged in the
    controller's graveyard (only the just-sac'd source). The resolve
    arm's substrate-fallback picks the source itself (it's now a Land
    in the gy), AND moves the SOURCE to the hand — a degenerate
    "Petrified Field returns itself" scenario that's pathological at
    production scale (legal-emit fan-out at C2 will exclude
    self-as-target) but well-defined under Cycle-1 substrate-fallback
    semantics.

    **Cycle-1 invariant pin.** Documents the substrate-fallback
    behavior so the C2 fan-out widen has a clear baseline. C2's
    target-list-snapshotted-at-activation-time semantics (emit BEFORE
    pay cost) will exclude the source from the target pool, so this
    pathological scenario disappears in production.
    """
    pf_id = synthetic_state.register_and_inject_object(
        _synthetic_petrified_field_dict(),
        0,
        ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(pf_id, False)

    hand_before = synthetic_state.hand_sizes[0]
    gy_before = synthetic_state.graveyard_sizes[0]

    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": pf_id,
        "ability_index": 0,
    })
    # Resolve the stack — the resolve arm's substrate-fallback scans
    # p0's gy and picks the source itself (only Land present).
    synthetic_state.resolve_top_of_stack()

    # The source moved gy -> hand. Net: gy=gy_before+1-1=gy_before;
    # hand=hand_before+1.
    assert synthetic_state.hand_sizes[0] == hand_before + 1
    assert synthetic_state.graveyard_sizes[0] == gy_before
    hand_post = synthetic_state.hand_snapshot(0)
    assert any(o["id"] == pf_id for o in hand_post)
    assert synthetic_state.is_stack_empty()


def test_resolve_return_target_land_silent_fizzle_when_no_land_in_graveyard(
    engine,
):
    """**Resolve arm — true silent fizzle pin.** A synthetic
    Petrified-Field-shape source + a NON-Land card pre-staged in the
    controller's graveyard. The resolve arm's substrate-fallback
    walks the gy, finds the sac'd source as a Land (which it returns
    to hand). The pre-staged NON-Land card stays in the gy
    untouched.

    Validates the predicate ``card_types.contains("Land")`` is honored
    — non-Land graveyard cards are not eligible.
    """
    state = engine.make_synthetic_state(0, 0, 1)
    # Inject a non-Land card into p0's graveyard (a creature).
    creature_dict = {
        "name": "Test Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
    }
    creature_id = state.register_and_inject_object(
        creature_dict, 0, ZONE_GRAVEYARD,
    )
    pf_id = state.register_and_inject_object(
        _synthetic_petrified_field_dict(), 0, ZONE_BATTLEFIELD,
    )
    state.force_set_summoning_sick(pf_id, False)

    state.apply_action({
        "kind": "activate_ability",
        "source_id": pf_id,
        "ability_index": 0,
    })
    state.resolve_top_of_stack()
    # The sac'd source is in p0's gy; the creature was already there.
    # Substrate-fallback picks the FIRST Land — that's the sac'd
    # source (creature was injected first, but it's NOT a Land, so
    # it's skipped). Source moves to hand; creature stays in gy.
    hand_post = state.hand_snapshot(0)
    gy_post = state.graveyard_snapshot(0)
    assert any(o["id"] == pf_id for o in hand_post)
    assert any(o["id"] == creature_id for o in gy_post)
    # Creature was NOT moved — non-Land filter held.
    assert not any(o["id"] == creature_id for o in hand_post)


# ---------------------------------------------------------------------------
# Substrate-only invariant pin — Petrified Field STAYS DECLINED post-Cycle-1
# ---------------------------------------------------------------------------


def test_petrified_field_now_admits_at_admit_gate_post_phase_2a():
    """**Phase 2a INVERSION admit pin (Petrified Field's live printing).**
    Petrified Field's live ``OracleParserCardSource`` printing now
    PASSES :func:`_printing_is_bridge_simple_carrier_aa_land` post-
    Phase-2a cost-gate widen (cost-gate at ``trajectory.py:8549``
    widened to admit ``sacrifice_self=True``) + Effect-class admit-
    set widen (``_carrier_aa_phase_1_effect_classes`` now includes
    ``ReturnTargetLandFromGraveyardToHand``).

    Inverts the C1 pin
    ``test_petrified_field_stays_declined_post_cycle_1``. Same shape
    as Phase-1 Cycle-2's Swarmyard inversion and Phase-1.5a's
    Deserted Temple inversion.

    Verifies:
      (a) The Carrier-AA disjunct
          ``_printing_is_bridge_simple_carrier_aa_land`` now ADMITS
          Petrified Field — the cost-gate widen + Effect-class widen
          land in lockstep.
      (b) Verify-first load-bearing-clause anchor: the live AA's
          cost shape carries ``sacrifice_self=True`` AND the Effect
          is ``ReturnTargetLandFromGraveyardToHand`` — the two
          previously-load-bearing-decline axes now both admit.
      (c) The admit predicate ``_aa_is_phase1_sub_shape_a`` returns
          True on the AA shape.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    pf = ps["Petrified Field"]

    # (a) Carrier-AA disjunct admits.
    assert traj._printing_is_bridge_simple_carrier_aa_land(pf) is True, (
        "Petrified Field MUST now ADMIT at the Carrier-AA admit gate "
        "post-Phase-2a — the cost-gate widen (admits "
        "``sacrifice_self=True``) + Effect-class widen (admits "
        "``ReturnTargetLandFromGraveyardToHand``) land the FLIP."
    )

    # (b) Verify-first anchor: the two previously-load-bearing-decline
    # axes both admit now. Walk the carrier AA's cost + effect.
    non_mana_aas = [
        aa for aa in (pf.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) == 1
    aa = non_mana_aas[0]
    assert aa.cost.sacrifice_self is True, (
        "The previously-load-bearing decline axis is "
        "cost.sacrifice_self — Phase 2a admits this shape."
    )
    assert isinstance(aa.effect, ReturnTargetLandFromGraveyardToHand), (
        "Petrified Field's AA effect must be "
        "ReturnTargetLandFromGraveyardToHand (the C1-substrate-shipped "
        "Effect class now in the Carrier-AA Phase-2a admit set)."
    )

    # (c) The admit predicate explicitly admits on this clause.
    assert traj._aa_is_phase1_sub_shape_a(aa) is True, (
        "Admit predicate ``_aa_is_phase1_sub_shape_a`` must ADMIT "
        "Petrified Field's AA shape post-Phase-2a (cost-gate widen +"
        " Effect-class widen). Phase 2a Cycle 2 FLIP."
    )


def test_petrified_field_now_passes_loader_filter():
    """**Phase 2a INVERSION wiring pin.** The loader ADMITS Petrified
    Field end-to-end post-Phase-2a — the Carrier-AA disjunct fires
    under the widened cost gate + widened Effect-class admit set. The
    returned CardDef carries the Carrier-AA builder's output for the
    ``ReturnTargetLandFromGraveyardToHand`` Effect.

    Inverts the C1 pin
    ``test_petrified_field_stays_declined_at_loader_filter``. Same
    shape as Phase-1.5a's Deserted Temple inversion pin
    ``test_filter_deck_to_bridge_supported_admits_deserted_temple``.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported

    ps = OracleParserCardSource().get_printings()
    assert "Petrified Field" in ps

    filtered, card_defs = _filter_deck_to_bridge_supported(
        ["Petrified Field"], ps,
    )
    assert filtered == ["Petrified Field"]
    assert len(card_defs) == 1
    card_def = card_defs[0]
    assert card_def.name == "Petrified Field"
    assert card_def.card_type == "Land"
    aas = card_def.activated_abilities
    assert len(aas) == 1
    aa_dict = aas[0]
    # Cost is `{T}, Sac:` (no mana — Petrified Field's printed cost).
    assert aa_dict["cost"] == {
        "tap_self": True,
        "sacrifice_self": True,
    }
    assert aa_dict["effect"] == {
        "kind": "return_target_land_from_graveyard_to_hand",
    }


# ---------------------------------------------------------------------------
# Phase 2a Cycle 2 — Rust legal-emit fan-out arm pins (graveyard-Land
# target enumeration). The new fan-out arm at
# ``state_ops_legal.rs::activate_ability_dict`` (sibling of the
# Equipment / sacrifice-target fan-out arms) walks the activator's
# graveyard for Land cards and emits one ``ActivateAbility`` dict per
# eligible target. The dict's ``target_creature_id`` slot carries the
# chosen graveyard-Land card id; the apply-time validation arm at
# ``state_ops_actions.rs`` accepts it under the new Phase-2a branch
# (the ``is_return_land_from_gy_effect`` branch — gates on Effect
# variant ``Effect::ReturnTargetLandFromGraveyardToHand``).
# ---------------------------------------------------------------------------


# Phase enum index for PRECOMBAT_MAIN — matches the Rust state enum
# discriminant. Mirrors the constant exported in tests_rust/test_legal.py:48.
PHASE_MAIN1 = 3


def _build_pf_petrified_field_state(engine_module, gy_dicts):
    """Helper — build a synthetic state with Petrified Field on p0's bf
    (untapped, not summoning-sick) and the provided objects in p0's
    graveyard. Returns ``(state, pf_id, gy_ids)``.

    ``gy_dicts`` is a list of registry-dict shapes — each gets injected
    into p0's graveyard in order. Common shapes:

    * ``_forest_dict()`` — Land card-type (eligible target).
    * a Creature dict (non-Land — declines under the graveyard-Land
      filter).
    """
    state = engine_module.make_synthetic_state(0, 0, 0)
    pf_id = state.register_and_inject_object(
        _synthetic_petrified_field_dict(),
        0,
        ZONE_BATTLEFIELD,
    )
    state.force_set_summoning_sick(pf_id, False)
    gy_ids = []
    for d in gy_dicts:
        gy_ids.append(
            state.register_and_inject_object(d, 0, ZONE_GRAVEYARD)
        )
    state.set_phase(PHASE_MAIN1)
    state.give_priority_to(0)
    return state, pf_id, gy_ids


def test_rust_legal_emit_fan_out_one_aa_per_eligible_graveyard_land(engine):
    """**Phase 2a C2 legal-emit pin — fan-out cardinality (1 Land
    target).** With Petrified Field on bf + one Forest in p0's
    graveyard, ``legal_decisions(0)`` emits exactly ONE
    ``ActivateAbility`` dict for the Petrified Field source, carrying
    ``target_creature_id = forest_id`` (the generic single-target
    object-id slot — see the apply-time
    ``is_return_land_from_gy_effect`` branch at
    ``state_ops_actions.rs``).
    """
    state, pf_id, gy_ids = _build_pf_petrified_field_state(
        engine, [_forest_dict()],
    )
    forest_id = gy_ids[0]

    decisions = state.legal_decisions(0)
    aa_decisions = [
        d for d in decisions
        if d.get("kind") == "activate_ability"
        and d.get("source_id") == pf_id
    ]
    assert len(aa_decisions) == 1, (
        f"Expected 1 ActivateAbility emit on Petrified Field with one "
        f"eligible graveyard Land; got {len(aa_decisions)}: "
        f"{aa_decisions}"
    )
    aa = aa_decisions[0]
    assert aa["target_creature_id"] == forest_id, (
        f"target_creature_id slot must carry the eligible graveyard-"
        f"Land id ({forest_id}); got {aa['target_creature_id']}"
    )
    assert aa["ability_index"] == 0
    assert aa["sacrifice_target_id"] is None


def test_rust_legal_emit_fan_out_multiple_eligible_graveyard_lands(engine):
    """**Phase 2a C2 legal-emit pin — fan-out cardinality (N=3
    Lands).** With Petrified Field on bf + THREE Forests in p0's
    graveyard, the fan-out emits THREE ``ActivateAbility`` dicts
    (one per eligible target). Mirrors the existing
    ``sacrifice_a_land`` fan-out cardinality contract at
    ``state_ops_legal.rs::legal_decisions``.
    """
    state, pf_id, gy_ids = _build_pf_petrified_field_state(
        engine,
        [_forest_dict(), _forest_dict(), _forest_dict()],
    )

    decisions = state.legal_decisions(0)
    aa_decisions = [
        d for d in decisions
        if d.get("kind") == "activate_ability"
        and d.get("source_id") == pf_id
    ]
    assert len(aa_decisions) == 3, (
        f"Expected 3 ActivateAbility emits (one per eligible "
        f"graveyard Land); got {len(aa_decisions)}: {aa_decisions}"
    )
    emit_target_ids = sorted(d["target_creature_id"] for d in aa_decisions)
    assert emit_target_ids == sorted(gy_ids), (
        f"Each emit must carry a distinct gy-Land id; got "
        f"target_creature_ids = {emit_target_ids}, expected {sorted(gy_ids)}"
    )


def test_rust_legal_emit_fan_out_silent_no_emit_on_empty_graveyard(engine):
    """**Phase 2a C2 legal-emit pin — silent no-emit on no legal
    target.** With Petrified Field on bf + EMPTY graveyard, the
    fan-out emits ZERO ``ActivateAbility`` dicts (mirrors CR 601.2c
    — a player can't begin to activate an ability without legal
    targets). The activation is honestly silently unavailable, NOT
    emitted-then-fizzled on resolve.
    """
    state, pf_id, _gy_ids = _build_pf_petrified_field_state(engine, [])

    decisions = state.legal_decisions(0)
    aa_decisions = [
        d for d in decisions
        if d.get("kind") == "activate_ability"
        and d.get("source_id") == pf_id
    ]
    assert aa_decisions == [], (
        f"Expected 0 ActivateAbility emits on Petrified Field with "
        f"empty graveyard; got {aa_decisions}"
    )


def test_rust_legal_emit_fan_out_skips_non_land_graveyard_cards(engine):
    """**Phase 2a C2 legal-emit pin — non-Land graveyard cards are
    skipped.** With Petrified Field on bf + a Creature in p0's
    graveyard (not a Land), the fan-out filters out the Creature and
    emits ZERO ``ActivateAbility`` dicts. The graveyard-Land filter
    is symmetric to the bf-Creature filter on the
    ``requires_target_creature_you_control`` arm — non-matching
    card-types decline silently.
    """
    creature_dict = {
        "name": "Test Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1},
        "power": 1,
        "toughness": 1,
    }
    state, pf_id, _gy_ids = _build_pf_petrified_field_state(
        engine, [creature_dict],
    )

    decisions = state.legal_decisions(0)
    aa_decisions = [
        d for d in decisions
        if d.get("kind") == "activate_ability"
        and d.get("source_id") == pf_id
    ]
    assert aa_decisions == [], (
        f"Expected 0 ActivateAbility emits on Petrified Field with a "
        f"non-Land in graveyard (the gy-Land filter excludes it); "
        f"got {aa_decisions}"
    )


def test_rust_legal_emit_fan_out_end_to_end_apply_and_resolve(engine):
    """**Phase 2a C2 end-to-end pin — emit + apply + resolve.** The
    fan-out emits an ``ActivateAbility`` dict; ``apply_action``
    accepts it (apply-time graveyard-Land target validation passes
    under the ``is_return_land_from_gy_effect`` branch); the source
    sacs to graveyard via Phase 5b cost-pay; the stack carries the
    ``ReturnTargetLandFromGraveyardToHand`` resolve payload;
    ``resolve_top_of_stack`` honors the cast-time-bound target
    (``current_resolve_payload_target_id``) and moves the Forest
    from graveyard to hand. Byte-equal end-to-end with the
    cast-time-bound target path (NOT the substrate-fallback path —
    this validates the new C2 fan-out wiring drives the bound-target
    branch of the resolve arm).
    """
    state, pf_id, gy_ids = _build_pf_petrified_field_state(
        engine, [_forest_dict()],
    )
    forest_id = gy_ids[0]

    decisions = state.legal_decisions(0)
    aa_decisions = [
        d for d in decisions
        if d.get("kind") == "activate_ability"
        and d.get("source_id") == pf_id
    ]
    assert len(aa_decisions) == 1
    chosen = aa_decisions[0]
    assert chosen["target_creature_id"] == forest_id

    state.apply_action(chosen)
    # Source sac'd to gy (Phase 5b sacrifice_self), Forest still in gy
    # (resolve hasn't fired yet), stack has the trigger.
    assert state.stack_size() == 1
    assert state.battlefield_sizes[0] == 0
    bf_snap = state.battlefield_snapshot()
    assert not any(o["id"] == pf_id for o in bf_snap)
    gy_post_sac = state.graveyard_snapshot(0)
    assert any(o["id"] == pf_id for o in gy_post_sac)
    assert any(o["id"] == forest_id for o in gy_post_sac)

    # Resolve the stack — the resolve arm reads
    # ``current_resolve_payload_target_id`` (set from the StackItem's
    # target_id payload — bound via the cast-time-bound target path,
    # NOT the substrate-fallback walk). Forest moves gy → hand.
    state.resolve_top_of_stack()
    hand_post = state.hand_snapshot(0)
    gy_post = state.graveyard_snapshot(0)
    assert any(o["id"] == forest_id for o in hand_post), (
        f"Forest (id={forest_id}) must move to hand on resolve; got "
        f"hand={hand_post}"
    )
    # Source stays in graveyard (Petrified Field doesn't return
    # ITSELF — it returns the bound target).
    assert any(o["id"] == pf_id for o in gy_post)
    assert not any(o["id"] == pf_id for o in hand_post)
    assert state.is_stack_empty()


def test_rust_apply_action_raises_on_illegal_graveyard_target(engine):
    """**Phase 2a C2 apply-time validation pin — illegal target
    raises.** A malformed direct-caller-built dict with a
    ``target_creature_id`` that doesn't resolve to a Land card in the
    activator's graveyard raises ``ValueError`` BEFORE any state
    mutation. Same symmetric-error-shape contract as the existing
    Equipment / sacrifice-target validation arms (raise pre-commit).

    The legal-emit fan-out pre-filters to legal targets, so this
    raise only fires on direct callers (test / synthetic path); the
    pin guards against silent target-id corruption in those paths.
    """
    state, pf_id, _gy_ids = _build_pf_petrified_field_state(
        engine, [_forest_dict()],
    )
    # Build a malformed dict — points at a non-existent id (99999).
    with pytest.raises(ValueError, match="not a legal graveyard-Land target"):
        state.apply_action({
            "kind": "activate_ability",
            "source_id": pf_id,
            "ability_index": 0,
            "target_creature_id": 99999,
        })


def test_rust_apply_action_accepts_none_target_for_substrate_fallback(engine):
    """**Phase 2a C2 apply-time validation pin — None target accepted
    (substrate-fallback path).** An ``ActivateAbility`` dict with
    ``target_creature_id = None`` is accepted under the
    ``is_return_land_from_gy_effect`` branch (the resolve arm's
    substrate-fallback path handles target selection). The legal-
    emit fan-out NEVER produces this shape post-C2 (it always emits
    a specific target id), but direct-callers / synthetic tests rely
    on the substrate-fallback path that pre-dates the fan-out.
    Confirms back-compat with the C1 substrate resolve-arm tests.
    """
    state, pf_id, _gy_ids = _build_pf_petrified_field_state(
        engine, [_forest_dict()],
    )
    # No target_creature_id (None) — substrate-fallback path.
    state.apply_action({
        "kind": "activate_ability",
        "source_id": pf_id,
        "ability_index": 0,
    })
    # Source sac'd; stack has the trigger; resolve picks the Forest
    # via substrate-fallback (first Land in gy after the sac'd source).
    assert state.stack_size() == 1
    state.resolve_top_of_stack()
    hand_post = state.hand_snapshot(0)
    # Substrate-fallback walks gy front-to-back; the pre-staged Forest
    # was injected BEFORE the sac'd source, so it's at the front and
    # gets picked. Confirms the C1 substrate-fallback path still
    # works alongside the new C2 cast-time-bound path.
    assert any(o["printing_name"] == "Test Forest" for o in hand_post)
