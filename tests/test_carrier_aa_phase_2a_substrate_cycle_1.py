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


def test_petrified_field_stays_declined_post_cycle_1():
    """**Substrate-only invariant pin — Phase 2a Cycle 1.** Petrified
    Field's live printing STAYS DECLINED at the production-deck admit
    gate post-Cycle-1. The Rust substrate widen + bridge round-trip
    extension don't widen the admit predicate
    ``_aa_is_phase1_sub_shape_a`` — it still declines
    ``sacrifice_self=True`` on the cost-gate clause at
    ``trajectory.py:8549``.

    Cycle 2 will INVERT this pin to
    ``test_petrified_field_now_admits_at_admit_gate_post_phase_2a`` —
    same shape as Phase-1 Cycle-2's Swarmyard inversion and Phase-1.5a's
    Deserted Temple inversion.

    Verifies:
      (a) No ``_printing_is_bridge_*`` sibling predicate admits Petrified
          Field (the substrate-only floor — admit set unchanged).
      (b) The Carrier-AA disjunct
          ``_printing_is_bridge_simple_carrier_aa_land`` specifically
          DECLINES Petrified Field — the cost-gate teeth bite.
      (c) The cost-axis clause is the load-bearing decline: confirm
          the live AA's cost shape (verify-first) includes
          ``sacrifice_self=True``.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity import trajectory as traj

    ps = OracleParserCardSource().get_printings()
    pf = ps["Petrified Field"]

    # (b) Carrier-AA disjunct declines.
    assert traj._printing_is_bridge_simple_carrier_aa_land(pf) is False, (
        "Petrified Field MUST stay declined at the Carrier-AA "
        "admit gate post-Cycle-1 — Cycle 2 widens the cost gate. "
        "This invariant pin is the load-bearing substrate-only "
        "guarantee."
    )

    # (a) No sibling bridge predicate admits. Walk every
    # ``_printing_is_bridge_*`` predicate.
    candidate_predicates = [
        (name, getattr(traj, name))
        for name in dir(traj)
        if name.startswith("_printing_is_bridge_")
    ]
    admits = [
        name
        for name, pred in candidate_predicates
        if callable(pred) and pred(pf)
    ]
    assert admits == [], (
        f"Petrified Field unexpectedly admits at predicate(s) "
        f"{admits} — Cycle 1 substrate must not change the admit "
        f"surface."
    )

    # (c) Verify-first load-bearing-clause anchor: the cost-gate
    # decline is on ``sacrifice_self``. Walk the carrier AA's cost.
    non_mana_aas = [
        aa for aa in (pf.activated_abilities or ())
        if not aa.is_mana_ability
    ]
    assert len(non_mana_aas) == 1
    aa = non_mana_aas[0]
    assert aa.cost.sacrifice_self is True, (
        "The load-bearing decline is on cost.sacrifice_self — if "
        "Petrified Field's parsed shape changes, the C2 widen target "
        "may need updating."
    )

    # The admit predicate explicitly declines on this clause.
    assert traj._aa_is_phase1_sub_shape_a(aa) is False, (
        "Admit predicate ``_aa_is_phase1_sub_shape_a`` must decline "
        "Petrified Field's AA shape post-Cycle-1 (cost-gate clause "
        "rejects ``sacrifice_self=True``). Cycle 2 inverts."
    )


def test_petrified_field_stays_declined_at_loader_filter():
    """**Loader-side invariant pin.** Walking Petrified Field through
    ``_filter_deck_to_bridge_supported`` with
    ``on_non_admitted=LoaderAdmitPolicy.RAISE`` raises (Petrified Field
    is not on the admit roster post-Cycle-1).

    This is the same shape as the loader-side pins for other
    substrate-only invariants — pins what production code observes,
    not just the predicate floor.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.parity.trajectory import (
        LoaderAdmitPolicy,
        NonAdmittedCardError,
        _filter_deck_to_bridge_supported,
    )

    # Ensure Petrified Field exists in the parser source.
    ps = OracleParserCardSource().get_printings()
    assert "Petrified Field" in ps

    # Walk Petrified Field through the loader filter on RAISE policy.
    with pytest.raises(NonAdmittedCardError) as excinfo:
        _filter_deck_to_bridge_supported(
            ["Petrified Field"],
            ps,
            on_non_admitted=LoaderAdmitPolicy.RAISE,
        )
    # The exception message confirms Petrified Field is the rejected
    # card.
    assert "Petrified Field" in str(excinfo.value)
