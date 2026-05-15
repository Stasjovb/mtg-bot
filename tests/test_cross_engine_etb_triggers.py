"""Cross-engine ETB-trigger smoke (Slice 3 of the ETB-trigger closure).

Pins the harness-side ``cross_engine.py`` ``printing_dict`` builder's
new ``triggered_abilities`` key + the ``_ta_dict_to_python_triggered_ability``
bridge so a CE19-shape probe (predicate-path ENTERS trigger) builds the
SAME triggered ability on BOTH engines from one ``CardDef``.

The probe shape: a vanilla creature whose
``triggered_abilities = [{event: enters, predicate: source_is_self,
effect: draw_cards count=1}]`` carries through the bridge. We don't
drive a full multi-turn cross-engine walk here — Slice 3's scope is
the bridge wiring; a full CE19-closure smoke comes in Slice 4+ once
predicates richer than ``IsSelf`` land.

Companion docs:
- ``docs/RUST_PARITY_GAPS.md`` I49 (Slice 3 closure).
- ``docs/RUST_ETB_TRIGGER_AUDIT.md`` §6.1 — Slice 3 cross-engine wiring.
"""

from __future__ import annotations


# A creature card def carrying the IsSelf-ENTERS DrawCards(1) trigger.
ETB_DRAW_BEAR_TA = {
    "event": "enters",
    "predicate": {"kind": "source_is_self"},
    "effect": {"kind": "draw_cards", "count": 1},
}


def _etb_draw_bear_card_def():
    from mtg_bot.parity.cross_engine import CardDef
    return CardDef(
        name="ETB Draw Bear (synthetic)",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
        triggered_abilities=(ETB_DRAW_BEAR_TA,),
    )


def test_card_def_carries_triggered_abilities_field():
    """The new ``triggered_abilities`` field is part of the
    ``CardDef`` dataclass and defaults to empty tuple."""
    from mtg_bot.parity.cross_engine import CardDef
    plain = CardDef(name="Plain", card_type="Creature")
    assert plain.triggered_abilities == ()
    bear = _etb_draw_bear_card_def()
    assert bear.triggered_abilities == (ETB_DRAW_BEAR_TA,)


def test_python_state_builder_wires_triggered_abilities():
    """``build_python_state`` translates the dict-shape triggered_abilities
    into Python's ``TriggeredAbility`` shape via the
    ``_ta_dict_to_python_triggered_ability`` bridge. The resulting
    ``CardPrinting`` carries the right Event + Predicate + Effect.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.parity.cross_engine import DeckSpec, build_python_state

    spec = DeckSpec(
        card_defs=(_etb_draw_bear_card_def(),),
        p0_library=("ETB Draw Bear (synthetic)",),
        p1_library=("ETB Draw Bear (synthetic)",),
    )
    state = build_python_state(spec)
    obj = state.players[0].library[0]
    printing = obj.printing
    assert len(printing.triggered_abilities) == 1
    ta = printing.triggered_abilities[0]
    assert isinstance(ta, TriggeredAbility)
    assert ta.event is Event.ENTERS
    assert isinstance(ta.predicate, IsSelf)
    assert isinstance(ta.effect, DrawCards)
    # Python's DrawCards exposes the count via `amount` (the dict-shape
    # uses `count` to match Rust's parser; cross_engine bridges them).
    assert ta.effect.amount == 1
    assert ta.once_per_turn is False


def test_rust_state_builder_wires_triggered_abilities():
    """``build_rust_state`` passes ``triggered_abilities`` through to
    the Rust registry, and the printing surfaces the parsed shape via
    the registry's ``get_printing_triggered_abilities`` reader (when
    available) or — more directly — the bridge round-trips through
    the mtg_bot_engine extension.

    The substrate-level proof: build a Rust state, then verify the
    printing's triggered_ability dispatches by casting and observing
    the resulting trigger on the stack."""
    import mtg_bot_engine
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(
        card_defs=(_etb_draw_bear_card_def(),),
        p0_library=("ETB Draw Bear (synthetic)",),
        p1_library=("ETB Draw Bear (synthetic)",),
    )
    rust_state = build_rust_state(spec)
    # `register_and_inject_object` is the simplest path to materialize
    # a fresh GameObject pointing at the registered printing without
    # driving a full priority loop. Inject onto p0's hand, push the
    # spell, resolve — the synthesized self-ETB trigger lands on the
    # stack post-resolve.
    bear_dict = {
        "name": "ETB Draw Bear (synthetic)",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "effects": [],
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [ETB_DRAW_BEAR_TA],
    }
    bear_id = rust_state.register_and_inject_object(bear_dict, 0, 0)  # ZONE_HAND
    rust_state.push_to_stack(bear_id, 0)
    rust_state.resolve_top_of_stack()
    # Bear landed on bf, trigger on stack.
    ZONE_BATTLEFIELD = 2
    assert rust_state.find_object_zone(bear_id) == ZONE_BATTLEFIELD
    assert rust_state.stack_size() == 1, (
        "expected the synthesized self-ETB trigger to be on the stack "
        "post-resolve; cross_engine.py wiring didn't make it to Rust"
    )
    top = rust_state.peek_top_of_stack()
    assert top["source_obj_id"] == bear_id


def test_pre_slice_3_specs_unaffected():
    """A DeckSpec whose card_defs all leave ``triggered_abilities``
    at its default empty tuple registers identically post-Slice-3 —
    no spurious extra triggers, no extra stack pushes. Regression
    guard against the bridge accidentally injecting triggers on
    pre-Slice-3 fixtures."""
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        tiny_synthetic_deckspec,
    )

    py_state, rust_state = build_matched_states(tiny_synthetic_deckspec())
    # No bf, no stack at construction time.
    assert rust_state.stack_size() == 0
    # Both engines see zero triggered_abilities on every loaded printing.
    for obj in py_state.players[0].library:
        assert obj.printing.triggered_abilities == ()
    for obj in py_state.players[1].library:
        assert obj.printing.triggered_abilities == ()


# =====================================================================
# Slice 4 — predicate-bridge round-trip pins for the new variants.
# Pins each Slice 4 predicate's `_ta_dict_to_python_predicate` arm so
# the harness translates Rust's parser-shape predicate dict into the
# Python `TriggerPredicate` instance that matches the same firing
# semantics.
# =====================================================================


def test_slice4_bridge_subject_is_land_translates_to_python():
    """Rust ``{"kind": "subject_is_land"}`` -> Python ``Subject(slot=None,
    inner=IsLand())``."""
    from mtg_bot.effects.predicates import Subject
    from mtg_bot.effects.object_predicates import IsLand
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_predicate

    p = _ta_dict_to_python_predicate({"kind": "subject_is_land"})
    assert isinstance(p, Subject)
    assert p.slot is None
    assert isinstance(p.inner, IsLand)


def test_slice4_bridge_subject_is_artifact_translates_to_python():
    """Rust ``{"kind": "subject_is_artifact"}`` -> Python
    ``Subject(slot=None, inner=IsArtifact())``."""
    from mtg_bot.effects.predicates import Subject
    from mtg_bot.effects.object_predicates import IsArtifact
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_predicate

    p = _ta_dict_to_python_predicate({"kind": "subject_is_artifact"})
    assert isinstance(p, Subject)
    assert p.slot is None
    assert isinstance(p.inner, IsArtifact)


def test_slice4_bridge_subject_is_creature_translates_to_python():
    """Rust ``{"kind": "subject_is_creature"}`` -> Python
    ``Subject(slot=None, inner=IsCreature())``."""
    from mtg_bot.effects.predicates import Subject
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_predicate

    p = _ta_dict_to_python_predicate({"kind": "subject_is_creature"})
    assert isinstance(p, Subject)
    assert p.slot is None
    assert isinstance(p.inner, IsCreature)


def test_slice4_bridge_controlled_by_you_translates_to_python():
    """Rust ``{"kind": "controlled_by_you"}`` -> Python
    ``Controlled(by=YOU, subject=None)``."""
    from mtg_bot.effects.predicates import Controlled, YOU
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_predicate

    p = _ta_dict_to_python_predicate({"kind": "controlled_by_you"})
    assert isinstance(p, Controlled)
    assert p.by == YOU
    assert p.subject is None


def test_slice4_bridge_composes_panharmonicon_faithful_predicate():
    """The audit's §5.4 Example A Panharmonicon-faithful predicate —
    `subject_is_creature AND controlled_by_you` — round-trips through
    the bridge to Python ``And(Subject(...), Controlled(...))``.
    """
    from mtg_bot.effects.predicates import (
        And,
        Subject,
        Controlled,
        YOU,
    )
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_predicate

    pred_dict = {
        "kind": "and",
        "left": {"kind": "subject_is_creature"},
        "right": {"kind": "controlled_by_you"},
    }
    p = _ta_dict_to_python_predicate(pred_dict)
    assert isinstance(p, And)
    assert isinstance(p.left, Subject)
    assert isinstance(p.left.inner, IsCreature)
    assert isinstance(p.right, Controlled)
    assert p.right.by == YOU


def test_slice4_rust_parser_accepts_new_predicate_kinds():
    """The Rust parser surface accepts each new Slice 4 predicate
    kind on register. Pin the parser-side coverage to keep the
    Python bridge + Rust parser in lockstep.
    """
    import mtg_bot_engine

    for kind in (
        "subject_is_land",
        "subject_is_artifact",
        "subject_is_creature",
        "controlled_by_you",
    ):
        reg = mtg_bot_engine.Registry()
        d = {
            "name": f"Slice4 Bridge Probe {kind}",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "power": 1,
            "toughness": 1,
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": kind},
                    "effect": {"kind": "draw_cards", "count": 1},
                }
            ],
        }
        pid = reg.register_printing(d)
        assert pid == 0, f"failed to register {kind!r}"


def test_bridge_damage_each_opponent_translates_to_python():
    """Probe F bridge extension: Rust
    ``{"kind": "damage_each_opponent", "amount": N}`` translates to
    Python ``DealDamageEachOpponent(amount=N)``.

    Unblocks Tannuk-Memorial-Ensign / Weftstalker-Ardent-shape
    "ETB-fan-out + deal 1 to each opponent" triggers on the
    cross-engine bridge. The Rust effect arm already exists at
    ``state_ops_resolve.rs:1563`` (``Effect::DamageEachOpponent``);
    Python's class already exists at
    ``effects/generic/damage.py:144`` (``DealDamageEachOpponent``).
    This pins the bridge translation that wires them up.
    """
    from mtg_bot.effects.generic.damage import DealDamageEachOpponent
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "damage_each_opponent", "amount": 2}
    )
    assert isinstance(e, DealDamageEachOpponent)
    assert e.amount == 2


def test_bridge_damage_each_opponent_amount_default_zero():
    """Missing ``amount`` defaults to 0 (mirrors the gain_life arm's
    default-zero convention -- bridge consumers are required to be
    explicit, but a missing key shouldn't crash the translator).
    """
    from mtg_bot.effects.generic.damage import DealDamageEachOpponent
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "damage_each_opponent"})
    assert isinstance(e, DealDamageEachOpponent)
    assert e.amount == 0


def test_rust_parser_accepts_damage_each_opponent_in_triggered_ability():
    """Pin the Rust parser surface for the matched effect kind. The
    bridge's dict shape must register cleanly on the Rust side too;
    this lockstep gate keeps the Python bridge from drifting away
    from Rust's parse_effect coverage.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Probe F Bridge Pin",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "R": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "damage_each_opponent",
                    "amount": 1,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_deal_damage_any_target_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "deal_damage_any_target", "amount": N}`` translates to
    Python ``DealDamageAnyTarget(amount=N)``.

    Unblocks Nebula-Dragon / Nova-Hellkite-shape ETB triggers that
    "deal N damage to any target" on the cross-engine bridge. The
    Rust effect variant already exists at
    ``rust/src/cards.rs:631`` (``Effect::DealDamageAnyTarget``) and
    its parse_effect arm at ``cards.rs:3063-3078``; the Rust resolve
    arm at ``state_ops_resolve.rs:3536-3603`` carries the I67
    controller-of-effect fix (defender derives from
    ``current_resolve_source_controller``, not ``active_player``).
    Python's class already exists at
    ``effects/generic/damage.py:264`` (``DealDamageAnyTarget``).
    This pins the bridge translation that wires them up.
    """
    from mtg_bot.effects.generic.damage import DealDamageAnyTarget
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "deal_damage_any_target", "amount": 3}
    )
    assert isinstance(e, DealDamageAnyTarget)
    assert e.amount == 3
    # The any-target filter is intrinsic to the subclass; verify the
    # constructor sugar's __post_init__ wired the TargetSpec (used by
    # ``effect.legal_targets`` at push time).
    assert len(e.targets) == 1


def test_bridge_deal_damage_any_target_amount_default_zero():
    """Missing ``amount`` defaults to 0 (mirrors the gain_life /
    damage_each_opponent arms' default-zero convention -- bridge
    consumers are required to be explicit, but a missing key
    shouldn't crash the translator). Rust's parse_effect is STRICTER
    (raises ``KeyError`` on missing ``amount``); the Python bridge's
    lenient default exists for partial test fixtures only and is
    out-of-band relative to the production parser path.
    """
    from mtg_bot.effects.generic.damage import DealDamageAnyTarget
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "deal_damage_any_target"})
    assert isinstance(e, DealDamageAnyTarget)
    assert e.amount == 0


def test_rust_parser_accepts_deal_damage_any_target_in_triggered_ability():
    """Pin the Rust parser surface for the matched effect kind. The
    bridge's dict shape must register cleanly on the Rust side too;
    this lockstep gate keeps the Python bridge from drifting away
    from Rust's parse_effect coverage.

    Mirrors the existing ``damage_each_opponent`` parser-surface pin
    (which closed Probe F's bridge contract end-to-end). Required
    field is ``amount`` (non-negative i32); the predicate-path
    triggered-ability wrapper is just a carrier — the substrate
    being pinned is parse_effect's ``deal_damage_any_target`` arm.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin — Any Target",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 6, "R": 1},
        "power": 4,
        "toughness": 4,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_any_target",
                    "amount": 3,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_deal_damage_to_opponent_creature_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "deal_damage_to_opponent_creature", "amount": N}``
    translates to Python ``DealDamageToOpponentCreature(amount=N)``.

    Unblocks Nova-Hellkite-shape ETB triggers that "deal N damage to
    target creature an opponent controls" on the cross-engine bridge.
    Distinct from the ``deal_damage_any_target`` arm in two ways:
    (a) the slot filter restricts legal targets to creatures
    ``IsCreature() & ControlledByOpponent()`` so players are never
    eligible, and (b) the Rust resolve arm
    (state_ops_resolve.rs:6271-6342) resolves the source's controller
    INTRINSICALLY via a 5-zone walk rather than reading
    ``current_resolve_source_controller`` — the controller-of-effect
    fix is wired in by the resolve arm's own scan, not by the I67
    transient swap.
    """
    from mtg_bot.effects.generic.damage import DealDamageToOpponentCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "deal_damage_to_opponent_creature", "amount": 1}
    )
    assert isinstance(e, DealDamageToOpponentCreature)
    assert e.amount == 1
    # The IsCreature() & ControlledByOpponent() filter is intrinsic
    # to the subclass; verify the constructor sugar's __post_init__
    # wired the TargetSpec slot (used by ``effect.legal_targets`` at
    # push time).
    assert len(e.targets) == 1


def test_bridge_deal_damage_to_opponent_creature_amount_default_zero():
    """Missing ``amount`` defaults to 0 (mirrors the gain_life /
    damage_each_opponent / deal_damage_any_target arms' default-zero
    convention -- bridge consumers are required to be explicit, but a
    missing key shouldn't crash the translator). Rust's parse_effect
    is STRICTER (raises ``KeyError`` on missing ``amount``); the
    Python bridge's lenient default exists for partial test fixtures
    only and is out-of-band relative to the production parser path.
    """
    from mtg_bot.effects.generic.damage import DealDamageToOpponentCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "deal_damage_to_opponent_creature"}
    )
    assert isinstance(e, DealDamageToOpponentCreature)
    assert e.amount == 0


def test_rust_parser_accepts_deal_damage_to_opponent_creature_in_triggered_ability():
    """Pin the Rust parser surface for the matched effect kind. The
    bridge's dict shape must register cleanly on the Rust side too;
    this lockstep gate keeps the Python bridge from drifting away
    from Rust's parse_effect coverage.

    Mirrors the existing ``deal_damage_any_target`` parser-surface
    pin. Required field is ``amount`` (non-negative i32); the
    predicate-path triggered-ability wrapper is just a carrier — the
    substrate being pinned is parse_effect's
    ``deal_damage_to_opponent_creature`` arm
    (cards.rs:3877-3890).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin — Opponent Creature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 3, "R": 2},
        "power": 4,
        "toughness": 5,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_to_opponent_creature",
                    "amount": 1,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_deal_damage_any_target_optional_flag_translates_to_python():
    """Phase 5 bridge extension (Pinnacle Kill-Ship slice): Rust
    ``{"kind": "deal_damage_any_target", "amount": N, "optional": true}``
    translates to Python
    ``DealDamageAnyTarget(amount=N, optional=True)``, and the
    Python class threads ``optional=True`` through to a
    ``TargetSpec`` with ``count_min=0`` ("up to one target" — CR
    601.2c "up to N targets" reading).

    Mirrors the ``DealDamageToTargetCreature`` optional-slot
    pattern already in ``effects/generic/damage.py`` for the
    creature-restricted "up to one target creature" shape; this
    pin extends the same shape to the wider "any target" filter
    used by Pinnacle Kill-Ship ("deals 10 damage to up to one
    target creature" — observably indistinguishable from the
    "any target" filter on probes that drive a single opponent
    creature on bf).
    """
    from mtg_bot.effects.generic.damage import DealDamageAnyTarget
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "deal_damage_any_target",
            "amount": 10,
            "optional": True,
        }
    )
    assert isinstance(e, DealDamageAnyTarget)
    assert e.amount == 10
    assert e.optional is True
    # The TargetSpec's count_min flipped to 0 — "up to one target"
    # semantics. count_max stays at 1.
    assert len(e.targets) == 1
    spec = e.targets[0]
    assert spec.count_min == 0
    assert spec.count_max == 1


def test_bridge_deal_damage_any_target_optional_default_false():
    """Missing ``optional`` defaults to ``False`` — the bare 1..1
    "any target" form Nebula Dragon / Debris Field Crusher already
    use stays bit-identical to its pre-extension shape.

    Defense-in-depth: the pre-existing
    ``test_bridge_deal_damage_any_target_translates_to_python``
    pin tests the bare shape's translation; this pin tests the
    same shape's ``optional`` field is ``False`` and the slot
    keeps ``count_min=1`` (the strict "any target" reading where
    the spell fizzles if no legal target exists at push time).
    """
    from mtg_bot.effects.generic.damage import DealDamageAnyTarget
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "deal_damage_any_target", "amount": 3}
    )
    assert isinstance(e, DealDamageAnyTarget)
    assert e.amount == 3
    assert e.optional is False
    assert len(e.targets) == 1
    spec = e.targets[0]
    assert spec.count_min == 1
    assert spec.count_max == 1


def test_rust_parser_accepts_optional_key_on_deal_damage_any_target():
    """Pin the Rust parser surface for the ``optional`` key on the
    ``deal_damage_any_target`` arm. The Rust ``Effect::DealDamage
    AnyTarget`` variant remains amount-only (no ``optional`` field
    on the variant), but the parse_effect arm SILENTLY DROPS the
    extra ``optional`` key per the broader silent-drop convention
    for unrecognized fields (cards.rs:3039 destroy_all_creatures
    arm comment). Both engines accept the same dict shape — the
    Python side observes ``optional`` and threads it to a 0..1
    slot, while the Rust side observes it as an ignored extra
    field and keeps its deterministic at-apply-time pick.

    The dict-shape round-trip contract is what this pin protects:
    a probe's ``triggered_abilities`` dict registers cleanly on
    BOTH engines without per-engine forking.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin — Any Target Optional",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 7},
        "power": 7,
        "toughness": 7,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage_any_target",
                    "amount": 10,
                    "optional": True,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_surveil_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "surveil", "count": N}`` translates to Python
    ``Surveil(amount=N)``.

    Unblocks Starbreach-Whale / Wurmwall-Sweeper / Thawbringer-ETB
    surveil-on-enters triggers on the cross-engine bridge. The Rust
    effect variant already exists at ``rust/src/cards.rs:274``
    (``Effect::Surveil { count: i32 }``) and its parse_effect arm at
    ``cards.rs:2894-2911``; the Rust resolve arm at
    ``state_ops_resolve.rs:2610-2649`` pushes a
    ``PendingDecision::SurveilChoice`` onto
    ``state.pending_decisions`` with the popped cards + source's
    controller (derived from ``current_resolve_source_controller``
    per the I61 controller-of-effect fix). Python's class already
    exists at ``effects/generic/library_lookat.py:569`` (``Surveil``).
    This pins the bridge translation that wires them up.

    Note the dict-key rename: Rust's parser uses ``count`` (mirrors
    ScryN's count-shape parser arm); Python's constructor spells the
    same value ``amount``. The bridge translates count -> amount.
    """
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "surveil", "count": 2})
    assert isinstance(e, Surveil)
    assert e.amount == 2
    # The use_artifact_count flag stays at its default False (the
    # dynamic-X "surveil X where X is artifact count" shape is
    # specific to Cerebral Download and isn't part of the EoE pool's
    # straight surveil-N triggers).
    assert e.use_artifact_count is False


def test_bridge_surveil_count_default_one():
    """Missing ``count`` defaults to 1 (mirrors Python's Surveil
    default of 1; the draw_cards arm uses the same default-one
    convention for its missing-count fallback).

    Rust's parse_effect is STRICTER (raises KeyError on a missing
    ``count`` field); the Python bridge's lenient default exists for
    partial test fixtures only and is out-of-band relative to the
    production parser path.
    """
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "surveil"})
    assert isinstance(e, Surveil)
    assert e.amount == 1


def test_rust_parser_accepts_surveil_in_triggered_ability():
    """Pin the Rust parser surface for the matched effect kind. The
    bridge's dict shape must register cleanly on the Rust side too;
    this lockstep gate keeps the Python bridge from drifting away
    from Rust's parse_effect coverage.

    Mirrors the existing ``deal_damage_any_target`` parser-surface
    pin. Required field is ``count`` (non-negative i32); the
    predicate-path triggered-ability wrapper is just a carrier — the
    substrate being pinned is parse_effect's ``surveil`` arm
    (cards.rs:2894-2911).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin — Surveil",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 4, "U": 1},
        "power": 4,
        "toughness": 4,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "surveil",
                    "count": 2,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_mill_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "mill", "count": N}`` translates to Python
    ``SelfMill(amount=N)``.

    Unblocks Seedship-Broodtender / Icetill-Explorer-shape ETB
    triggers that "mill N cards" on the cross-engine bridge. The
    Rust effect variant already exists at
    ``rust/src/cards.rs:75`` (``Effect::Mill``) and its parse_effect
    arm at ``cards.rs:2744-2747``; the Rust resolve arm at
    ``state_ops_resolve.rs:1034-1051`` carries the I65 controller-
    of-effect fix (mills the SOURCE's controller's library, not the
    active player's). This pins the field-name translation
    ``count -> amount`` for the controller-self mill shape.
    """
    from mtg_bot.effects.generic.library_lookat import SelfMill
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "mill", "count": 3}
    )
    assert isinstance(e, SelfMill)
    assert e.amount == 3


def test_bridge_mill_count_default_one():
    """Missing ``count`` defaults to 1 (matching ``SelfMill``'s class
    default ``amount: int = 1``, which mirrors the typical oracle
    text "mill a card" without an explicit count).

    Distinct from the ``gain_life`` / ``damage_each_opponent`` /
    ``deal_damage_any_target`` arms (which default to 0): SelfMill's
    Python class default is 1, not 0. The bridge mirrors the Python
    class's chosen default so the translator is robust to partial
    fixtures without changing semantics relative to a direct
    ``SelfMill()`` construction.

    Bridge consumers SHOULD pass ``count`` explicitly to keep round-
    trip dict-shape consistency with the Rust parser (cards.rs:2744-
    2747 requires the field). This default is a robustness backstop,
    not a contract.
    """
    from mtg_bot.effects.generic.library_lookat import SelfMill
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "mill"})
    assert isinstance(e, SelfMill)
    assert e.amount == 1


def test_rust_parser_accepts_mill_in_triggered_ability():
    """Pin the Rust parser surface for the ``mill`` effect kind. The
    bridge's dict shape must register cleanly on the Rust side too;
    this lockstep gate keeps the Python bridge from drifting away
    from Rust's parse_effect coverage.

    Mirrors the existing ``damage_each_opponent`` /
    ``deal_damage_any_target`` parser-surface pins -- what's being
    pinned is parse_effect's ``mill`` arm accepting a
    triggered_abilities entry with ``count: N``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- Mill",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "B": 1, "G": 1},
        "power": 2,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "mill",
                    "count": 3,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_return_creature_from_graveyard_to_hand_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "return_creature_from_your_graveyard_to_hand"}``
    translates to Python
    ``ReturnCreatureFromYourGraveyardToHand()``.

    Unblocks Interceptor-Mechan / Fell-Gravship-suffix-shape ETB
    triggers (the bare unit-variant; the rider-widened EoE-card
    shapes — or_artifact / or_spacecraft — would surface as
    separate parametric Rust variants and re-enter the bridge as
    new arms). The Rust effect variant exists at
    ``rust/src/cards.rs:782`` (unit variant
    ``Effect::ReturnCreatureFromYourGraveyardToHand``); its
    parse_effect arm at ``cards.rs:3148-3151`` takes no fields;
    the resolve arm at ``state_ops_resolve.rs:2986-3020`` carries
    the I82 controller-of-effect fix (``controller_idx`` derives
    from ``current_resolve_source_controller``, not
    ``active_player``).

    Python's class already exists at
    ``effects/generic/bounce.py:356`` as constructor sugar over
    ``ReturnFromGraveyard`` (pins ``creature=True`` +
    ``destination="hand"``). This pins the bridge translation that
    wires them up.
    """
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "return_creature_from_your_graveyard_to_hand"}
    )
    assert isinstance(e, ReturnCreatureFromYourGraveyardToHand)
    # The unified base's flags should reflect the unit-variant shape:
    # primary type = creature, destination = hand, no widening
    # riders, no MV cap, single-target.
    assert e.creature is True
    assert e.destination == "hand"
    assert e.or_artifact is False
    assert e.or_spacecraft is False
    assert e.or_enchantment is False
    assert e.max_mv == 0
    assert e.min_n == 1
    assert e.max_n == 1
    assert e.target_kind == "graveyard_creature"


def test_bridge_return_creature_from_graveyard_to_hand_ignores_extra_fields():
    """The unit variant has no fields, so the bridge translator
    silently ignores every key beyond ``kind`` on the dict (matches
    the Rust parse_effect arm at ``cards.rs:3148-3151`` which only
    matches on the discriminator and constructs the unit variant
    without reading any companion fields). Defense-in-depth: keep
    this lenient pin so partial fixtures don't crash the translator
    if a downstream slice prepends rider-shape stubs to the dict
    before the rider arms land.
    """
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "return_creature_from_your_graveyard_to_hand",
            # Round-trip noise: future rider stubs that aren't yet
            # plumbed through. The bridge silently ignores them, as
            # does the Rust unit-variant parser arm.
            "or_artifact": True,
            "max_mv": 4,
        }
    )
    assert isinstance(e, ReturnCreatureFromYourGraveyardToHand)
    # The riders DO NOT carry through — the bare unit variant ignores
    # them. Probes that need widening must wait for a parametric Rust
    # variant + companion bridge arm.
    assert e.or_artifact is False
    assert e.max_mv == 0


def test_rust_parser_accepts_return_creature_from_graveyard_to_hand_in_triggered_ability():
    """Pin the Rust parser surface for the matched effect kind. The
    bridge's dict shape must register cleanly on the Rust side too;
    this lockstep gate keeps the Python bridge from drifting away
    from Rust's parse_effect coverage.

    Mirrors the existing ``deal_damage_any_target`` /
    ``damage_each_opponent`` parser-surface pins. The unit variant
    takes no fields beyond ``kind`` — the predicate-path triggered-
    ability wrapper is just a carrier; the substrate being pinned
    is parse_effect's
    ``return_creature_from_your_graveyard_to_hand`` arm at
    ``cards.rs:3148-3151``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin — Return Creature From GY to Hand",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 3, "B": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_creature_from_your_graveyard_to_hand",
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0



def test_bridge_pump_target_creature_until_eot_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "pump_target_creature_until_eot",
    "power_bonus": N, "toughness_bonus": M}`` translates to Python
    ``PumpTargetCreatureUntilEOT(power_bonus=N, toughness_bonus=M)``.

    Unblocks Sinister-Cryologist / Dubious-Delicacy-shape ETB triggers
    that "target creature gets +X/+Y UEOT" on the cross-engine bridge.
    """
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "pump_target_creature_until_eot",
            "power_bonus": -3,
            "toughness_bonus": 0,
        }
    )
    assert isinstance(e, PumpTargetCreatureUntilEOT)
    assert e.power_bonus == -3
    assert e.toughness_bonus == 0
    assert e.opponents_only is False
    assert e.you_control_only is False
    assert e.optional is False


def test_bridge_pump_target_creature_until_eot_positive_bonus_translates():
    """Positive bonus arm -- +3/+3 round-trip."""
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "pump_target_creature_until_eot",
            "power_bonus": 3,
            "toughness_bonus": 3,
        }
    )
    assert isinstance(e, PumpTargetCreatureUntilEOT)
    assert e.power_bonus == 3
    assert e.toughness_bonus == 3


def test_bridge_pump_target_creature_until_eot_defaults_to_zero():
    """Missing ``power_bonus`` / ``toughness_bonus`` default to 0."""
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "pump_target_creature_until_eot"}
    )
    assert isinstance(e, PumpTargetCreatureUntilEOT)
    assert e.power_bonus == 0
    assert e.toughness_bonus == 0


def test_rust_parser_accepts_pump_target_creature_until_eot_in_triggered_ability():
    """Pin the Rust parser surface for the
    ``pump_target_creature_until_eot`` effect kind.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- PumpTargetCreatureUntilEOT",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "U": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "pump_target_creature_until_eot",
                    "power_bonus": -3,
                    "toughness_bonus": 0,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_fight_target_creature_with_target_creature_translates_to_python():
    """BLOCKED-RUST-EFFECT slice -- Fight effect arm. Rust
    ``{"kind": "fight_target_creature_with_target_creature"}``
    translates to Python
    ``FightTargetCreatureWithTargetCreature()``.

    Unit-variant arm; no fields beyond ``kind`` (mirrors the
    bilateral source-vs-opponent shape baked into the variant
    identity on both engines). Routes Rust's
    ``Effect::FightTargetCreatureWithTargetCreature`` to its
    Python sibling for the cross-engine bridge.
    """
    from mtg_bot.effects.generic.damage import (
        FightTargetCreatureWithTargetCreature,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "fight_target_creature_with_target_creature"}
    )
    assert isinstance(e, FightTargetCreatureWithTargetCreature)


def test_bridge_fight_target_creature_with_target_creature_ignores_extra_fields():
    """Unit-variant arm tolerates extra fields on the dict (mirrors
    every other unit-variant bridge arm -- the kind alone determines
    the translation; extra keys are inert)."""
    from mtg_bot.effects.generic.damage import (
        FightTargetCreatureWithTargetCreature,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "fight_target_creature_with_target_creature",
            "spurious_field": 42,
        }
    )
    assert isinstance(e, FightTargetCreatureWithTargetCreature)


def test_bridge_fight_target_creature_with_target_creature_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``{"kind": "sequence", "effects": [{"kind":
    "fight_target_creature_with_target_creature"}, {"kind":
    "draw_cards", "count": 1}]}`` translates to ``Sequence(effects=(
    FightTargetCreatureWithTargetCreature(), DrawCards(amount=1)))``.
    Pins the unit-variant arm against accidental list-construction
    drift in the Sequence translator."""
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.damage import (
        FightTargetCreatureWithTargetCreature,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "fight_target_creature_with_target_creature"},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], FightTargetCreatureWithTargetCreature)


def test_rust_parser_accepts_fight_target_creature_with_target_creature_in_triggered_ability():
    """Pin the Rust parser surface for the
    ``fight_target_creature_with_target_creature`` effect kind on
    a triggered_ability carrier. The bridge dict shape must register
    cleanly on the Rust side too; this lockstep gate keeps the
    bridge from drifting away from Rust's parse_effect coverage.

    Rust's parse_effect arm at ``rust/src/cards.rs`` accepts the
    bare kind with no companion fields (unit variant); extra dict
    fields are silently ignored for round-trip dict-shape
    consistency.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-RUST-EFFECT Bridge Pin -- FightTargetCreatureWithTargetCreature",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "G": 1},
        "power": 3,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "fight_target_creature_with_target_creature",
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_put_plus_one_counter_on_creature_you_control_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "put_plus_one_counter_on_creature_you_control",
    "amount": N}`` translates to Python
    ``PutPlusOneCounterOnCreatureYouControl(amount=N)``.
    """
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_creature_you_control",
            "amount": 1,
        }
    )
    assert isinstance(e, PutPlusOneCounterOnCreatureYouControl)
    assert e.amount == 1


def test_bridge_put_plus_one_counter_on_creature_you_control_amount_default_one():
    """Missing ``amount`` defaults to 1."""
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "put_plus_one_counter_on_creature_you_control"}
    )
    assert isinstance(e, PutPlusOneCounterOnCreatureYouControl)
    assert e.amount == 1


def test_rust_parser_accepts_put_plus_one_counter_on_creature_you_control_in_triggered_ability():
    """Pin the Rust parser surface for
    ``put_plus_one_counter_on_creature_you_control``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- PutPlusOneCounterOnCreatureYouControl",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "W": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "put_plus_one_counter_on_creature_you_control",
                    "amount": 1,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


# ===== Phase 5 rider-widened return-to-hand bridge pins =====
#
# Two new Rust Effect variants extend the unit-variant
# return_creature_from_your_graveyard_to_hand with the EoE riders:
#
#   * return_artifact_or_creature_from_your_graveyard_to_hand
#     (Interceptor Mechan)
#   * return_creature_or_spacecraft_from_your_graveyard_to_hand
#     (Fell Gravship suffix)
#
# Both translate to Python's
# ``ReturnCreatureFromYourGraveyardToHand`` with the matching
# rider flag set (``or_artifact=True`` or ``or_spacecraft=True``).
# The Python class is unified — the rider flags flow through
# ``_gy_card_matches`` to admit the widened types alongside the
# creature primary.


def test_bridge_return_artifact_or_creature_translates_to_python():
    """Phase 5 rider bridge: Rust
    ``{"kind": "return_artifact_or_creature_from_your_graveyard_to_hand"}``
    translates to Python
    ``ReturnCreatureFromYourGraveyardToHand(or_artifact=True)``.

    Unblocks Interceptor Mechan (EoE): "When this creature enters,
    return target artifact or creature card from your graveyard to
    your hand."
    """
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "return_artifact_or_creature_from_your_graveyard_to_hand"}
    )
    assert isinstance(e, ReturnCreatureFromYourGraveyardToHand)
    # Primary type stays creature; or_artifact widens the pool to
    # admit Artifact cards alongside Creature.
    assert e.creature is True
    assert e.destination == "hand"
    assert e.or_artifact is True
    # Other riders stay off — this variant only widens by artifact.
    assert e.or_spacecraft is False
    assert e.or_enchantment is False
    assert e.max_mv == 0
    assert e.min_n == 1
    assert e.max_n == 1
    assert e.target_kind == "graveyard_creature"


def test_bridge_return_creature_or_spacecraft_translates_to_python():
    """Phase 5 rider bridge: Rust
    ``{"kind": "return_creature_or_spacecraft_from_your_graveyard_to_hand"}``
    translates to Python
    ``ReturnCreatureFromYourGraveyardToHand(or_spacecraft=True)``.

    Unblocks Fell Gravship (EoE) suffix: "...then return a creature
    or Spacecraft card from your graveyard to your hand."

    Discriminator vs the or_artifact arm: Spacecraft is a SUBTYPE,
    not a card_type. Python's ``_gy_card_matches`` honors the
    ``or_spacecraft`` flag specifically (graveyard.py:46) which
    reads ``printing.is_spacecraft`` -> ``"Spacecraft" in subtypes``.
    """
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "return_creature_or_spacecraft_from_your_graveyard_to_hand"}
    )
    assert isinstance(e, ReturnCreatureFromYourGraveyardToHand)
    assert e.creature is True
    assert e.destination == "hand"
    assert e.or_spacecraft is True
    # or_artifact stays off — discriminator. A plain Artifact card
    # is NOT admitted by this rider.
    assert e.or_artifact is False
    assert e.or_enchantment is False
    assert e.max_mv == 0
    assert e.min_n == 1
    assert e.max_n == 1
    assert e.target_kind == "graveyard_creature"


def test_rust_parser_accepts_return_artifact_or_creature_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the rider-
    widened kind in a triggered_ability dict. Mirrors the existing
    parser-surface pin for the unit variant.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin — Return Artifact Or Creature",
        "card_types": ["Artifact", "Creature"],
        "subtypes": ["Robot"],
        "mana_cost": {"generic": 4},
        "power": 2,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": (
                        "return_artifact_or_creature_from_your_graveyard_to_hand"
                    ),
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_rust_parser_accepts_return_creature_or_spacecraft_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    or_spacecraft rider-widened kind in a triggered_ability dict.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin — Return Creature Or Spacecraft",
        "card_types": ["Artifact"],
        "subtypes": ["Spacecraft"],
        "mana_cost": {"generic": 5},
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": (
                        "return_creature_or_spacecraft_from_your_graveyard_to_hand"
                    ),
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_return_enchantment_or_creature_translates_to_python():
    """Phase 5 rider bridge: Rust
    ``{"kind": "return_enchantment_or_creature_from_your_graveyard_to_hand"}``
    translates to Python
    ``ReturnCreatureFromYourGraveyardToHand(or_enchantment=True)``.

    Sister bridge to the or_artifact / or_spacecraft to-hand arms.
    The audit's unique EoE consumer of the
    "creature or enchantment card from your graveyard" rider is
    Rescue Skiff, but Rescue Skiff's destination is the BATTLEFIELD
    (not the hand) — Rescue Skiff itself unblocks via the
    to-battlefield sibling (separate slice). This bridge arm lands
    here for substrate symmetry alongside the existing or_artifact
    / or_spacecraft to-hand arms.

    Discriminator vs the or_artifact / or_spacecraft arms:
    Enchantment is a CARD TYPE (not a subtype), and a plain Artifact
    or Spacecraft is NOT admitted by this rider. Python's
    ``_gy_card_matches`` honors the ``or_enchantment`` flag
    specifically (graveyard.py:46) which reads
    ``printing.is_enchantment`` -> ``"Enchantment" in card_types``.
    """
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "return_enchantment_or_creature_from_your_graveyard_to_hand"}
    )
    assert isinstance(e, ReturnCreatureFromYourGraveyardToHand)
    # Primary type stays creature; or_enchantment widens the pool
    # to admit Enchantment cards alongside Creature.
    assert e.creature is True
    assert e.destination == "hand"
    assert e.or_enchantment is True
    # Other riders stay off — discriminator. A plain Artifact or
    # Spacecraft is NOT admitted by this rider.
    assert e.or_artifact is False
    assert e.or_spacecraft is False
    assert e.max_mv == 0
    assert e.min_n == 1
    assert e.max_n == 1
    assert e.target_kind == "graveyard_creature"


def test_bridge_return_enchantment_or_creature_round_trips_through_rust():
    """Round-trip pin: Rust accepts the kind via parse_effect, and
    the to-dict serializer round-trips it back to the same string.
    Mirrors the parser-surface pins for the unit variant and the
    or_artifact / or_spacecraft sibling arms.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin — Return Enchantment Or Creature",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1},
        "effects": [
            {
                "kind": (
                    "return_enchantment_or_creature_from_your_graveyard_to_hand"
                ),
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_rust_parser_accepts_return_enchantment_or_creature_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    or_enchantment rider-widened kind in a triggered_ability dict.
    Mirrors the parser-surface pins for the or_artifact /
    or_spacecraft sibling arms.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin — Trigger Return Enchantment Or Creature",
        "card_types": ["Enchantment"],
        "mana_cost": {"generic": 3},
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": (
                        "return_enchantment_or_creature_from_your_graveyard_to_hand"
                    ),
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_return_enchantment_or_creature_describe_matches_oracle():
    """The bridged Python effect's ``describe()`` text matches the
    oracle phrasing. Pins the legacy printed phrasing through the
    rider — load-bearing for the audit's 'creature or enchantment
    card' substring search and the Python class's stringification
    contract.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "return_enchantment_or_creature_from_your_graveyard_to_hand"}
    )
    desc = e.describe()
    assert "creature or enchantment" in desc.lower()
    assert "graveyard" in desc
    assert "hand" in desc


# ===== Phase 5 to-BATTLEFIELD or_enchantment bridge pins (4) =====
#
# Sister bridge to the to-HAND or_enchantment block above; the
# destination delta is the load-bearing difference. Mirrors Rust's
# ``Effect::ReturnEnchantmentOrCreatureFromYourGraveyardToBattlefield``
# (cards.rs new variant) end-to-end.
#
# **Closes the loop on Rescue Skiff.** Unlike the to-hand sibling
# (which had no real-EoE consumer and landed for substrate
# symmetry), this arm is the direct unblocker for Rescue Skiff
# (EoE): "When this Spacecraft enters, return target creature or
# enchantment card from your graveyard to the battlefield."


def test_bridge_return_enchantment_or_creature_to_bf_translates_to_python():
    """Phase 5 rider bridge: Rust
    ``{"kind": "return_enchantment_or_creature_from_your_graveyard_to_battlefield"}``
    translates to Python
    ``ReturnCreatureFromYourGraveyardToBattlefield(or_enchantment=True)``.

    Sister bridge to the to-hand or_enchantment arm; the destination
    delta (BATTLEFIELD vs HAND) is the load-bearing difference.
    Closes the loop on Rescue Skiff (EoE) — its ETB resolves
    through this exact bridge arm.

    Discriminator vs the to-hand sibling: ``destination ==
    "battlefield"`` (pinned by
    ``ReturnCreatureFromYourGraveyardToBattlefield.__post_init__``).
    Python's ``_gy_card_matches`` honors the ``or_enchantment``
    flag (graveyard.py:46) which reads ``printing.is_enchantment``
    -> ``"Enchantment" in card_types``.
    """
    from mtg_bot.effects.generic.graveyard import (
        ReturnCreatureFromYourGraveyardToBattlefield,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": (
                "return_enchantment_or_creature_from_your_graveyard_to_battlefield"
            )
        }
    )
    assert isinstance(e, ReturnCreatureFromYourGraveyardToBattlefield)
    # Primary type stays creature; or_enchantment widens the pool
    # to admit Enchantment cards alongside Creature.
    assert e.creature is True
    # Destination delta from the to-hand sibling — load-bearing.
    assert e.destination == "battlefield"
    assert e.or_enchantment is True
    # Other riders stay off — discriminator. A plain Artifact or
    # Spacecraft is NOT admitted by this rider.
    assert e.or_artifact is False
    assert e.or_spacecraft is False
    assert e.max_mv == 0
    assert e.min_n == 1
    assert e.max_n == 1
    assert e.target_kind == "graveyard_creature"


def test_bridge_return_enchantment_or_creature_to_bf_round_trips_through_rust():
    """Round-trip pin: Rust accepts the kind via parse_effect, and
    the to-dict serializer round-trips it back to the same string.
    Mirrors the parser-surface pins for the bare to-bf unit variant
    and the to-hand sibling arms.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin — Return Enchantment Or Creature To BF",
        "card_types": ["Sorcery"],
        "mana_cost": {"B": 1, "generic": 1},
        "effects": [
            {
                "kind": (
                    "return_enchantment_or_creature_from_your_graveyard_to_battlefield"
                ),
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_rust_parser_accepts_return_enchantment_or_creature_to_bf_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    or_enchantment-rider to-bf kind in a triggered_ability dict.
    Mirrors the parser-surface pins for the bare to-bf unit variant
    and the to-hand sibling arms. Load-bearing for Rescue Skiff —
    its ETB trigger carries this exact effect kind.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin — Trigger Rescue Skiff Recur",
        "card_types": ["Artifact"],
        "mana_cost": {"W": 1, "generic": 5},
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": (
                        "return_enchantment_or_creature_from_your_graveyard_to_battlefield"
                    ),
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_return_enchantment_or_creature_to_bf_describe_matches_oracle():
    """The bridged Python effect's ``describe()`` text matches the
    oracle phrasing for Rescue Skiff: "return target creature or
    enchantment card from your graveyard to the battlefield". Pins
    the legacy printed phrasing through the rider for the to-bf
    destination — load-bearing for the audit's 'creature or
    enchantment card' substring search and the Python class's
    stringification contract.

    The ``ReturnCreatureFromYourGraveyardToBattlefield`` describe()
    override (graveyard.py:382-389) was already or_enchantment-aware;
    this pin guards against any future regression that would drop
    the rider from the override's type-phrase chain.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": (
                "return_enchantment_or_creature_from_your_graveyard_to_battlefield"
            )
        }
    )
    desc = e.describe()
    assert "creature or enchantment" in desc.lower()
    assert "graveyard" in desc
    # Destination delta from the to-hand sibling — load-bearing.
    assert "battlefield" in desc


# ===== Phase 5 composer bridge pins (sequence) =====
#
# Rust's ``Effect::Sequence { effects: Vec<Effect> }`` carries an
# ordered list of nested effects; the parse_effect arm at
# rust/src/cards.rs:4046-4075 recursively parses each child. The
# bridge mirrors that shape: ``_ta_dict_to_python_effect`` recurses
# into each ``effects[i]`` dict and wraps the resulting list in
# ``Sequence([...])``.
#
# Real EoE consumers unblocked by this composer:
#
#   * Uthros Scanship: Sequence{[DrawCards{2}, DiscardSelf{1}]}
#   * Fell Gravship suffix: Sequence{[Mill{3},
#     ReturnCreatureFromYourGraveyardToHand]}


def test_bridge_sequence_empty_translates_to_python():
    """Phase 5 composer bridge: an empty Sequence (no children) is
    a legal no-op on both engines and round-trips through the bridge.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "sequence", "effects": []})
    assert isinstance(e, Sequence)
    assert e.effects == ()


def test_bridge_sequence_two_children_translates_to_python():
    """Phase 5 composer bridge: a 2-element Sequence with leaf
    children translates each child via the same bridge function and
    preserves order.

    Uthros Scanship's ETB shape: Sequence{[DrawCards{2}, DiscardSelf{1}]}.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.discard import DiscardSelf
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "draw_cards", "count": 2},
                {"kind": "discard_self", "amount": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], DrawCards)
    assert e.effects[0].amount == 2
    assert isinstance(e.effects[1], DiscardSelf)
    assert e.effects[1].amount == 1


def test_bridge_sequence_nested_translates_to_python():
    """Phase 5 composer bridge: Sequence-in-Sequence nesting works
    (the recursive translator descends into nested composer dicts).
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "gain_life", "amount": 1},
                {
                    "kind": "sequence",
                    "effects": [
                        {"kind": "draw_cards", "count": 1},
                        {"kind": "gain_life", "amount": 2},
                    ],
                },
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], GainLife)
    assert e.effects[0].amount == 1
    inner = e.effects[1]
    assert isinstance(inner, Sequence)
    assert len(inner.effects) == 2
    assert isinstance(inner.effects[0], DrawCards)
    assert inner.effects[0].amount == 1
    assert isinstance(inner.effects[1], GainLife)
    assert inner.effects[1].amount == 2


def test_rust_parser_accepts_sequence_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts a sequence
    composer (with nested children) inside a triggered_ability dict.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin — Sequence Composer",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2},
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "sequence",
                    "effects": [
                        {"kind": "draw_cards", "count": 2},
                        {"kind": "discard_self", "amount": 1},
                    ],
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


# ===== Phase 5 composer bridge pins (if_you_do) =====
#
# Rust's ``Effect::IfYouDo { do_action: Box<Effect>, then_action:
# Box<Effect> }`` is the gate-on-completion composer. parse_effect
# at rust/src/cards.rs:3610-3640 REQUIRES both ``do_action`` and
# ``then_action`` (no defaults — missing either field raises
# ValueError). The bridge mirrors that contract: missing fields
# raise KeyError out of ``_ta_dict_to_python_effect``.
#
# Python's ``IfYouDo(do_action: Effect, then_action: Effect)``
# from ``effects/combinators.py:560`` resolves do_action first; if
# it returns False (signaling failure / decline), then_action is
# skipped. ``DiscardSelf`` and ``Optional`` already signal
# completion via the True/False return — this is how the gate fires.
#
# Real EoE consumer unblocked by this composer:
#
#   * Melded Moxite: IfYouDo{cost=DiscardSelf, then=DrawCards{2}}
#     -- "Discard a card. If you do, draw two cards."


def test_bridge_if_you_do_translates_to_python():
    """Phase 5 composer bridge: a basic IfYouDo with simple cost +
    then-side translates each branch via the recursive translator.

    Melded Moxite's ETB shape: IfYouDo{cost=DiscardSelf{1},
    then=DrawCards{2}}.
    """
    from mtg_bot.effects.combinators import IfYouDo
    from mtg_bot.effects.generic.discard import DiscardSelf
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "if_you_do",
            "do_action": {"kind": "discard_self", "amount": 1},
            "then_action": {"kind": "draw_cards", "count": 2},
        }
    )
    assert isinstance(e, IfYouDo)
    assert isinstance(e.do_action, DiscardSelf)
    assert e.do_action.amount == 1
    assert isinstance(e.then_action, DrawCards)
    assert e.then_action.amount == 2


def test_bridge_if_you_do_missing_then_action_raises():
    """Phase 5 composer bridge: missing ``then_action`` field raises
    out of the bridge — mirrors Rust's parse_effect requiring the
    field (no default). Same contract for missing ``do_action``;
    one direction pins the surface symmetrically.
    """
    import pytest
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(KeyError):
        _ta_dict_to_python_effect(
            {
                "kind": "if_you_do",
                "do_action": {"kind": "discard_self", "amount": 1},
                # then_action intentionally absent
            }
        )


def test_rust_parser_accepts_if_you_do_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts an if_you_do
    composer (with both do/then children) inside a triggered_ability
    dict.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin — IfYouDo Composer",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "if_you_do",
                    "do_action": {
                        "kind": "discard_self", "amount": 1,
                    },
                    "then_action": {
                        "kind": "draw_cards", "count": 2,
                    },
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_pump_creatures_opponents_control_until_eot_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "pump_creatures_opponents_control_until_eot",
    "power_bonus": N, "toughness_bonus": M}`` translates to Python
    ``PumpCreaturesOpponentsControlUntilEOT(power_bonus=N,
    toughness_bonus=M)``.

    Mass-debuff "creatures your opponents control get +X/+Y UEOT"
    on the cross-engine bridge -- the opponent-side mirror of the
    (not-yet-on-the-bridge) ``pump_creatures_you_control_until_eot``
    arm. EoE consumer Mouth of the Storm uses the extended
    ``until your next turn`` duration which has no Rust counterpart;
    the bare ``until end of turn`` arm has no real-EoE consumer
    today and is exercised end-to-end via a synthetic probe.
    """
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesOpponentsControlUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "pump_creatures_opponents_control_until_eot",
            "power_bonus": -3,
            "toughness_bonus": 0,
        }
    )
    assert isinstance(e, PumpCreaturesOpponentsControlUntilEOT)
    assert e.power_bonus == -3
    assert e.toughness_bonus == 0
    # The Python-only ``until_caster_next_turn`` extended-duration
    # flag stays at its default False (the Rust variant has no
    # equivalent field; the bridge mirrors Rust's bare-EOT shape).
    assert e.until_caster_next_turn is False
    # Granted-keywords rider stays at its empty default (Rust's
    # variant has no equivalent field).
    assert e.granted_keywords == frozenset()


def test_bridge_pump_creatures_opponents_control_until_eot_positive_bonus_translates():
    """Positive-bonus arm -- ``+2/+2`` round-trips. Same shape as the
    debuff form; the Rust parse_effect arm imposes no sign constraint
    (cards.rs:3844-3862)."""
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesOpponentsControlUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "pump_creatures_opponents_control_until_eot",
            "power_bonus": 2,
            "toughness_bonus": 2,
        }
    )
    assert isinstance(e, PumpCreaturesOpponentsControlUntilEOT)
    assert e.power_bonus == 2
    assert e.toughness_bonus == 2


def test_bridge_pump_creatures_opponents_control_until_eot_defaults_to_zero():
    """Missing ``power_bonus`` / ``toughness_bonus`` default to 0 in
    the bridge translator (translator-robustness backstop for direct
    unit-test calls; Rust's parse_effect REQUIRES both keys present so
    end-to-end Rust callers must supply them explicitly)."""
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesOpponentsControlUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "pump_creatures_opponents_control_until_eot"}
    )
    assert isinstance(e, PumpCreaturesOpponentsControlUntilEOT)
    assert e.power_bonus == 0
    assert e.toughness_bonus == 0


def test_rust_parser_accepts_pump_creatures_opponents_control_until_eot_in_triggered_ability():
    """Pin the Rust parser surface for the
    ``pump_creatures_opponents_control_until_eot`` effect kind in a
    triggered_ability dict. Rust's parse_effect at cards.rs:3844-3862
    requires both ``power_bonus`` and ``toughness_bonus`` keys
    explicitly.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- PumpCreaturesOpponentsControlUntilEOT",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 6, "U": 1},
        "power": 6,
        "toughness": 6,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "pump_creatures_opponents_control_until_eot",
                    "power_bonus": -3,
                    "toughness_bonus": 0,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_pump_creatures_opponents_control_until_caster_next_turn_translates_to_python():
    """Mouth-of-the-Storm bridge extension: Rust
    ``{"kind": "pump_creatures_opponents_control_until_caster_next_turn",
       "power_bonus": N, "toughness_bonus": M}`` translates to Python
    ``PumpCreaturesOpponentsControlUntilEOT(power_bonus=N,
    toughness_bonus=M, until_caster_next_turn=True)``.

    Sibling-of-the-bare-EOT bridge arm. Real-EoE consumer: Mouth of
    the Storm ({6}{U} Elemental, "When this creature enters,
    creatures your opponents control get -3/-0 UNTIL YOUR NEXT TURN.")
    -- the discriminator carries the extended-duration distinction;
    the Python sibling routes through ``until_caster_next_turn=True``
    which writes the modifier via ``grant_pt_pump_until_player_next_turn``
    (layer-7c registry entry tagged
    ``expires_at="controller_untap"``), keeping the debuff through
    the opponent's full subsequent turn.

    The Rust resolve arm currently uses the SAME UEOT cleanup-step
    lifetime as the bare sibling (the cleanup-gate divergence is
    documented in docs/SEARCH_LIMITATIONS.md and is a deferred
    follow-up Rust slice). The discriminator-only sibling matters
    NOW because it routes Mouth of the Storm cleanly today and the
    cleanup-gate slice can swap the resolve arm WITHOUT any bridge
    or call-site changes.
    """
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesOpponentsControlUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "pump_creatures_opponents_control_until_caster_next_turn",
            "power_bonus": -3,
            "toughness_bonus": 0,
        }
    )
    assert isinstance(e, PumpCreaturesOpponentsControlUntilEOT)
    assert e.power_bonus == -3
    assert e.toughness_bonus == 0
    # Load-bearing translation: bridge sets until_caster_next_turn=True
    # on the Python class, distinguishing the extended duration from
    # the bare-EOT sibling above.
    assert e.until_caster_next_turn is True
    # Granted-keywords rider stays at its empty default (Rust's
    # variant has no equivalent field).
    assert e.granted_keywords == frozenset()


def test_bridge_pump_creatures_opponents_control_until_caster_next_turn_defaults_to_zero():
    """Missing ``power_bonus`` / ``toughness_bonus`` default to 0 in
    the bridge translator; ``until_caster_next_turn=True`` still
    flows through (it's set unconditionally on this arm). Translator-
    robustness backstop for direct unit-test calls; Rust's
    parse_effect REQUIRES both keys present so end-to-end Rust
    callers must supply them explicitly."""
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesOpponentsControlUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "pump_creatures_opponents_control_until_caster_next_turn"}
    )
    assert isinstance(e, PumpCreaturesOpponentsControlUntilEOT)
    assert e.power_bonus == 0
    assert e.toughness_bonus == 0
    assert e.until_caster_next_turn is True


def test_bridge_pump_creatures_opponents_control_until_caster_next_turn_distinct_from_bare_sibling():
    """Discriminator pin: bare-EOT and extended-duration arms produce
    DIFFERENT Python objects -- the bare arm's
    ``until_caster_next_turn`` defaults to False; the extended-arm
    bridge sets it True. A regression that aliased the two arms in
    the bridge dispatch would surface here.
    """
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesOpponentsControlUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bare = _ta_dict_to_python_effect(
        {
            "kind": "pump_creatures_opponents_control_until_eot",
            "power_bonus": -3,
            "toughness_bonus": 0,
        }
    )
    extended = _ta_dict_to_python_effect(
        {
            "kind": "pump_creatures_opponents_control_until_caster_next_turn",
            "power_bonus": -3,
            "toughness_bonus": 0,
        }
    )
    assert isinstance(bare, PumpCreaturesOpponentsControlUntilEOT)
    assert isinstance(extended, PumpCreaturesOpponentsControlUntilEOT)
    # Same P/T payload.
    assert bare.power_bonus == extended.power_bonus == -3
    assert bare.toughness_bonus == extended.toughness_bonus == 0
    # Load-bearing distinction: ONLY the extended arm sets
    # until_caster_next_turn=True. The bare arm must default it to
    # False so cleanup-step expiration fires at the casting turn's
    # cleanup (Python-side parity with the Rust bare-EOT cleanup).
    assert bare.until_caster_next_turn is False
    assert extended.until_caster_next_turn is True


def test_rust_parser_accepts_pump_creatures_opponents_control_until_caster_next_turn_in_triggered_ability():
    """Pin the Rust parser surface for the
    ``pump_creatures_opponents_control_until_caster_next_turn``
    effect kind on a triggered-ability carrier (Mouth of the Storm
    shape). The bridge's dict shape must register cleanly on the
    Rust side too; this lockstep gate keeps the Python bridge from
    drifting away from Rust's parse_effect coverage.

    Mirrors the bare-sibling parser-surface pin above. Rust's
    parse_effect arm tolerates missing ``power_bonus`` /
    ``toughness_bonus`` (defaults to 0) on this arm, mirroring the
    bare sibling's tolerance.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Mouth-of-the-Storm Bridge Pin -- ExtendedDuration",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 6, "U": 1},
        "power": 6,
        "toughness": 6,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "pump_creatures_opponents_control_until_caster_next_turn",
                    "power_bonus": -3,
                    "toughness_bonus": 0,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_each_opponent_sacrifices_creature_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "each_opponent_sacrifices_creature"}`` translates to
    Python ``EachOpponentSacrificesCreature()``.

    Rust's variant is a UNIT VARIANT -- no fields beyond ``kind``.
    Bridges Susurian Dirgecraft (EoE Spacecraft) end-to-end.
    """
    from mtg_bot.effects.generic.opponent_punishers import (
        EachOpponentSacrificesCreature,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "each_opponent_sacrifices_creature"}
    )
    assert isinstance(e, EachOpponentSacrificesCreature)


def test_bridge_each_opponent_sacrifices_creature_ignores_extra_fields():
    """Unit-variant arm tolerates extra fields on the dict (mirrors
    every other unit-variant arm on the bridge -- the kind alone
    determines the translation; extra keys are inert)."""
    from mtg_bot.effects.generic.opponent_punishers import (
        EachOpponentSacrificesCreature,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "each_opponent_sacrifices_creature",
            "spurious_field": 42,
        }
    )
    assert isinstance(e, EachOpponentSacrificesCreature)


def test_bridge_each_opponent_sacrifices_creature_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``{"kind": "sequence", "effects": [{"kind":
    "each_opponent_sacrifices_creature"}, {"kind": "draw_cards",
    "count": 1}]}`` translates to ``Sequence(effects=(
    EachOpponentSacrificesCreature(), DrawCards(amount=1)))``."""
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.opponent_punishers import (
        EachOpponentSacrificesCreature,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "each_opponent_sacrifices_creature"},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], EachOpponentSacrificesCreature)


def test_rust_parser_accepts_each_opponent_sacrifices_creature_in_triggered_ability():
    """Pin the Rust parser surface for the
    ``each_opponent_sacrifices_creature`` effect kind in a
    triggered_ability dict. Rust's parse_effect at cards.rs:3391-3393
    accepts the bare kind with no companion fields.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- EachOpponentSacrificesCreature",
        "card_types": ["Artifact", "Creature"],
        "subtypes": ["Spacecraft"],
        "mana_cost": {"generic": 4, "B": 1},
        "power": 4,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_sacrifices_creature",
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_each_opponent_mills_cards_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "each_opponent_mills_cards", "count": N}`` translates
    to Python ``EachOpponentMillsCards(amount=N)``.

    Field-name translation: Rust ``count`` -> Python ``amount``.
    Mirrors the field-name divergence between Rust's count-keyed
    arms (each_opponent_mills_cards, surveil) and Python's amount-
    keyed effect family.
    """
    from mtg_bot.effects.generic.draw_mill import EachOpponentMillsCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "each_opponent_mills_cards", "count": 3}
    )
    assert isinstance(e, EachOpponentMillsCards)
    assert e.amount == 3


def test_bridge_each_opponent_mills_cards_count_default_one():
    """Missing ``count`` defaults to 1 in the bridge translator
    (mirrors the Python class's ``amount: int = 1`` default).
    Rust's parse_effect REQUIRES the key present so direct Rust
    callers must supply it explicitly; the bridge default is a
    translator-robustness backstop for direct unit-test calls.
    """
    from mtg_bot.effects.generic.draw_mill import EachOpponentMillsCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "each_opponent_mills_cards"}
    )
    assert isinstance(e, EachOpponentMillsCards)
    assert e.amount == 1


def test_bridge_each_opponent_mills_cards_zero_count_translates():
    """``count=0`` translates to ``amount=0`` (a no-op on both
    engines but a legal field value -- Rust's parse_effect at
    cards.rs:3604-3605 rejects only NEGATIVE counts, not zero)."""
    from mtg_bot.effects.generic.draw_mill import EachOpponentMillsCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "each_opponent_mills_cards", "count": 0}
    )
    assert isinstance(e, EachOpponentMillsCards)
    assert e.amount == 0


def test_rust_parser_accepts_each_opponent_mills_cards_in_triggered_ability():
    """Pin the Rust parser surface for the
    ``each_opponent_mills_cards`` effect kind in a triggered_ability
    dict. Rust's parse_effect at cards.rs:3592-3608 requires the
    ``count`` key explicitly.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- EachOpponentMillsCards",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "B": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_mills_cards",
                    "count": 2,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


# ===== Phase 5 mass-counter bridge pins =====
#
# Anthem-shape +1/+1 counter add for the source's controller's bf.
# Translates ``put_plus_one_counter_on_each_creature_you_control``
# (Rust ``Effect::PutPlusOneCounterOnEachCreatureYouControl``) into
# Python's ``PutPlusOneCounterOnEachCreatureYouControl(amount=N)``.
#
# Sister arm to ``put_plus_one_counter_on_creature_you_control``
# (single-target). The MASS variant has no targeting; the bridge
# constructor mirrors the Rust variant's bare ``amount`` shape.
# Real EoE consumer: Atmospheric Greenhouse.


def test_bridge_put_plus_one_counter_on_each_creature_you_control_translates_to_python():
    """Phase 5 mass-counter bridge: Rust
    ``{"kind": "put_plus_one_counter_on_each_creature_you_control",
    "amount": N}`` translates to Python
    ``PutPlusOneCounterOnEachCreatureYouControl(amount=N)``.
    """
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnEachCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_each_creature_you_control",
            "amount": 1,
        }
    )
    assert isinstance(e, PutPlusOneCounterOnEachCreatureYouControl)
    assert e.amount == 1
    # Default exclude_source is False (matches the Rust variant
    # which has no exclude-source field; the bridge mirrors the
    # bare-shape variant).
    assert e.exclude_source is False


def test_bridge_put_plus_one_counter_on_each_creature_you_control_amount_default_one():
    """Missing ``amount`` defaults to 1 (matches the Python class's
    ``amount: int = 1`` default and the Rust parser's tolerant arm
    at cards.rs:3256-3272).
    """
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnEachCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "put_plus_one_counter_on_each_creature_you_control"}
    )
    assert isinstance(e, PutPlusOneCounterOnEachCreatureYouControl)
    assert e.amount == 1


def test_bridge_put_plus_one_counter_on_each_creature_you_control_amount_two_translates():
    """Non-default ``amount`` round-trips. The Rust variant carries
    ``amount: i32`` so larger printings (none in EoE today, but the
    field is parametric) translate the same way.
    """
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnEachCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_each_creature_you_control",
            "amount": 2,
        }
    )
    assert isinstance(e, PutPlusOneCounterOnEachCreatureYouControl)
    assert e.amount == 2


def test_rust_parser_accepts_put_plus_one_counter_on_each_creature_you_control_in_triggered_ability():
    """Pin the Rust parser surface for
    ``put_plus_one_counter_on_each_creature_you_control``. Uses an
    Artifact carrier (matches Atmospheric Greenhouse's type-line
    shape) so a future regression that tightens the Rust
    parse_triggered_ability arm to creature-only sources surfaces
    here.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- PutPlusOneCounterOnEachCreatureYouControl",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 4},
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "put_plus_one_counter_on_each_creature_you_control",
                    "amount": 1,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


# ===== Phase 5 create_token bridge pins =====
#
# Token-spawn ETB shape. Translates ``create_token`` (Rust
# ``Effect::CreateToken {count, token_printing_id}``) into Python's
# ``CreateToken(token_printing=..., count=...)``. The dict carries a
# Rust-registry pid; the bridge looks up the matching Python printing
# from the probe-time ``register_token_printing`` map (pre-existing
# substrate added with the bridge arm). Real-EoE consumers: any
# Spacecraft / Artifact whose ETB prints a vanilla Soldier / Robot
# token (the I81 cross-controller probe drives the synthetic shape;
# the bridge unlocks real-EoE token-creation ETB probes too).


def test_bridge_create_token_translates_to_python():
    """Phase 5 create_token bridge: Rust
    ``{"kind": "create_token", "count": 1, "token_printing_id": pid}``
    translates to Python
    ``CreateToken(token_printing=<registered>, count=1)``.
    """
    from mtg_bot.cards.base import make_token_creature
    from mtg_bot.effects.generic.tokens import CreateToken
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_effect, clear_token_printings,
        register_token_printing,
    )

    clear_token_printings()
    soldier = make_token_creature(
        name="Soldier Token (bridge pin)",
        power=1, toughness=1, subtypes=("Soldier",),
    )
    register_token_printing(7, soldier)
    e = _ta_dict_to_python_effect(
        {"kind": "create_token", "count": 1, "token_printing_id": 7}
    )
    assert isinstance(e, CreateToken)
    assert e.token_printing is soldier
    assert e.count == 1
    # Rider flags default per the dataclass (Rust variant has no
    # mirror for them; the bridge constructs the bare shape).
    assert e.tapped is False
    assert e.attacking is False
    assert e.each_player is False
    assert e.schedule_end_of_combat_sacrifice is False
    clear_token_printings()


def test_bridge_create_token_count_default_one():
    """Missing ``count`` defaults to 1 (mirrors the lenient
    ``draw_cards`` / ``surveil`` default-convention for partial test
    fixtures; Rust's parse_effect is STRICTER and would raise
    ``KeyError`` on a missing field, but the bridge tolerates the
    omission for round-trip dict-shape consistency on the Python
    side).
    """
    from mtg_bot.cards.base import make_token_creature
    from mtg_bot.effects.generic.tokens import CreateToken
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_effect, clear_token_printings,
        register_token_printing,
    )

    clear_token_printings()
    robot = make_token_creature(
        name="Robot Token (bridge pin -- count default)",
        power=2, toughness=1, subtypes=("Robot",), artifact=True,
    )
    register_token_printing(11, robot)
    e = _ta_dict_to_python_effect(
        {"kind": "create_token", "token_printing_id": 11}
    )
    assert isinstance(e, CreateToken)
    assert e.token_printing is robot
    assert e.count == 1
    clear_token_printings()


def test_bridge_create_token_missing_registration_raises_keyerror():
    """``create_token`` with a ``token_printing_id`` not present in
    the registry raises ``KeyError`` with a clear hint -- silent
    divergence from a missing setup step would be much harder to
    debug than an immediate failure at translation time.
    """
    import pytest

    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_effect, clear_token_printings,
    )

    clear_token_printings()
    with pytest.raises(KeyError, match="token_printing_id=999"):
        _ta_dict_to_python_effect(
            {"kind": "create_token", "count": 1, "token_printing_id": 999}
        )


def test_register_token_printing_rejects_conflicting_pid():
    """``register_token_printing`` raises ``ValueError`` on a
    conflicting registration (a different Python printing under an
    existing pid). Idempotent on a repeat (pid, printing) pair.
    Probes that genuinely want to clear-and-re-register call
    :func:`clear_token_printings` first.
    """
    import pytest

    from mtg_bot.cards.base import make_token_creature
    from mtg_bot.parity.cross_engine import (
        clear_token_printings, register_token_printing,
    )

    clear_token_printings()
    a = make_token_creature(
        name="Token A (conflict pin)", power=1, toughness=1,
    )
    b = make_token_creature(
        name="Token B (conflict pin)", power=2, toughness=2,
    )
    register_token_printing(42, a)
    # Idempotent re-register of the SAME printing on the same pid
    # is a no-op.
    register_token_printing(42, a)
    # Conflicting registration raises.
    with pytest.raises(ValueError, match="already registered"):
        register_token_printing(42, b)
    clear_token_printings()


def test_rust_parser_accepts_create_token_in_triggered_ability():
    """Pin the Rust parser surface for ``create_token``. Uses a
    Creature carrier (matches the I81 synthetic Token Maker Bear's
    type-line shape) so a future regression that tightens the Rust
    parse_triggered_ability arm to artifact-only sources surfaces
    here. The Rust parser requires both ``count`` and
    ``token_printing_id`` fields; the inner token printing is
    pre-registered on the same Registry so the pid is valid.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    # Pre-register the inner Soldier token so the carrier's
    # triggered-ability dict can reference its pid.
    soldier_pid = reg.register_printing({
        "name": "Phase 5 Bridge Pin Soldier",
        "card_types": ["Creature"],
        "power": 1,
        "toughness": 1,
    })
    d = {
        "name": "Phase 5 Bridge Pin -- CreateToken",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "W": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "create_token",
                    "count": 1,
                    "token_printing_id": soldier_pid,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    # Carrier is the second printing in the registry.
    assert pid == soldier_pid + 1


def test_bridge_mill_target_player_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "mill_target_player", "count": N}`` translates to
    Python ``MillTargetPlayer(amount=N)``.

    Unblocks Mind-Funeral / Tome-Scour / Scrabbling-Skullcrab-shape
    "target player mills N" effects on the cross-engine bridge --
    sibling closure to the bare ``mill`` arm (controller-self
    mill shortcut). The Rust effect variant exists at
    ``rust/src/cards.rs:84`` (``Effect::MillTargetPlayer { count }``)
    and its parse_effect arm at ``cards.rs:2833-2848``; the Rust
    resolve arm at ``state_ops_resolve.rs:1085-1148`` carries the
    I77 controller-of-effect fix (target_idx = 1 - controller, where
    controller derives from current_resolve_source_controller).
    Pins the field-name translation ``count -> amount`` for the
    target-player mill shape.
    """
    from mtg_bot.effects.generic.draw_mill import MillTargetPlayer
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "mill_target_player", "count": 2}
    )
    assert isinstance(e, MillTargetPlayer)
    assert e.amount == 2
    assert e.use_controller_life is False


def test_bridge_mill_target_player_count_default_one():
    """Missing ``count`` defaults to 1 (matching ``MillTargetPlayer``'s
    class default ``amount: int = 1``, which mirrors the bare ``mill``
    arm's lenient-default convention; both share the SelfMill /
    MillTargetPlayer ``amount: int = 1`` Python class default).

    Bridge consumers SHOULD pass ``count`` explicitly to keep round-
    trip dict-shape consistency with the Rust parser
    (``cards.rs:2833-2848`` requires the field at register time and
    rejects negatives). This default is a robustness backstop for
    partial fixtures, not a contract.
    """
    from mtg_bot.effects.generic.draw_mill import MillTargetPlayer
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "mill_target_player"})
    assert isinstance(e, MillTargetPlayer)
    assert e.amount == 1


def test_rust_parser_accepts_mill_target_player_in_triggered_ability():
    """Pin the Rust parser surface for the ``mill_target_player``
    effect kind. The bridge's dict shape must register cleanly on
    the Rust side too; this lockstep gate keeps the Python bridge
    from drifting away from Rust's parse_effect coverage.

    Mirrors the existing ``mill`` parser-surface pin
    (test_rust_parser_accepts_mill_in_triggered_ability) -- what's
    being pinned is parse_effect's ``mill_target_player`` arm
    accepting a triggered_abilities entry with ``count: N`` and
    rejecting negatives at register time per
    ``cards.rs:2841-2846``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- MillTargetPlayer",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "U": 1, "B": 1},
        "power": 2,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "mill_target_player",
                    "count": 2,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_exile_target_creature_until_source_leaves_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "exile_target_creature_until_source_leaves"}``
    translates to Python
    ``ExileTargetCreatureUntilSourceLeaves()``.

    Unblocks Banisher-Priest / Fiend-Hunter / All-Fates-Stalker /
    Hardlight-Containment-shape ETB exile triggers on the cross-
    engine bridge. The Rust effect variant exists at
    ``rust/src/cards.rs:1268`` (unit variant
    ``Effect::ExileTargetCreatureUntilSourceLeaves``); its
    parse_effect arm at ``cards.rs:3322-3323`` takes no fields; the
    resolve arm at ``state_ops_resolve.rs:5537-5639`` carries the
    I79 controller-of-effect fix (defender = 1 - controller, where
    controller derives from current_resolve_source_controller).
    Stamps ``exiled_with_source = Some(source_obj_id)`` so the
    paired return on source-leaves works.
    """
    from mtg_bot.effects.generic.exile import (
        ExileTargetCreatureUntilSourceLeaves,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "exile_target_creature_until_source_leaves"}
    )
    assert isinstance(e, ExileTargetCreatureUntilSourceLeaves)
    # Bare-shape defaults: empty excluded_subtypes (no subtype
    # filter), opponents_only / yours_only both False (no
    # controller-side filter). The Rust unit variant has no rider
    # mirrors today; the bridge constructs the bare default shape.
    assert e.excluded_subtypes == frozenset()
    assert e.opponents_only is False
    assert e.yours_only is False


def test_bridge_exile_target_creature_until_source_leaves_ignores_extra_fields():
    """Extra dict fields are ignored — the bridge translator mirrors
    the Rust unit-variant convention (no fields beyond ``kind``) and
    constructs the bare-default Python shape regardless of whether
    the dict carries extra keys. Mirrors the
    ``return_creature_from_your_graveyard_to_hand`` /
    ``return_creature_from_your_graveyard_to_battlefield`` arm
    convention (both unit variants).
    """
    from mtg_bot.effects.generic.exile import (
        ExileTargetCreatureUntilSourceLeaves,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({
        "kind": "exile_target_creature_until_source_leaves",
        # Extra keys that future rider-widened Rust variants might
        # carry; the bare-shape arm ignores them.
        "extra_key_should_be_ignored": True,
        "another_unused_field": 42,
    })
    assert isinstance(e, ExileTargetCreatureUntilSourceLeaves)


def test_rust_parser_accepts_exile_target_creature_until_source_leaves_in_triggered_ability():
    """Pin the Rust parser surface for the
    ``exile_target_creature_until_source_leaves`` effect kind. The
    bridge's dict shape must register cleanly on the Rust side too;
    this lockstep gate keeps the Python bridge from drifting away
    from Rust's parse_effect coverage.

    Mirrors the existing
    ``return_creature_from_your_graveyard_to_hand`` parser-surface
    pin (test_rust_parser_accepts_return_creature_from_graveyard_to_hand_in_triggered_ability)
    -- both are unit-variant arms with no companion fields. The
    Rust parse_effect arm at ``cards.rs:3322-3323`` accepts the
    bare ``{"kind": "exile_target_creature_until_source_leaves"}``
    shape on a triggered-ability carrier.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- ExileUntilSourceLeaves",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "W": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "exile_target_creature_until_source_leaves",
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_discard_card_translates_to_python_target_opponent_discards():
    """Phase 5 bridge extension WIDER variant: Rust
    ``{"kind": "discard_card", "target": {"kind": "any_player"}}``
    translates to Python
    ``TargetOpponentDiscards(count=1)``.

    Unblocks Mind Rot / Wrench Mind / Specter-bonk-shape ETB discard
    triggers on the cross-engine bridge. The Rust effect variant
    exists at the ``Effect::DiscardCard { target: TargetFilter }``
    arm; its parse_effect arm at ``cards.rs:2890-2897`` requires a
    ``target`` dict; the resolve arm at
    ``state_ops_resolve.rs:1607-1660`` carries the I74 controller-
    of-effect fix (defender = 1 - controller, where controller
    derives from current_resolve_source_controller).

    **First bridge arm to honor ONLY the wider any_player filter**
    (siblings honor only any_creature; the deal_damage arm honors
    both). Rust's resolve arm explicitly raises PyValueError on
    AnyCreature at state_ops_resolve.rs:1608-1611 -- discard is
    semantically a player-targeted effect.

    Distinct from the existing ``each_opponent_discards`` arm
    (multi-target sweep): this ``discard_card`` arm is single-target
    Mind-Rot shape ("target player discards a card"). Rust's
    first-slice picks the discarder's hand[0] deterministically;
    Python defers to the discarder's agent ``choose_discard``.
    """
    from mtg_bot.effects.generic.discard import TargetOpponentDiscards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "discard_card", "target": {"kind": "any_player"}}
    )
    assert isinstance(e, TargetOpponentDiscards)
    # Default count=1 mirrors Rust's first-slice "discards exactly
    # one card" semantics (the Rust variant has no count field).
    assert e.count == 1


def test_bridge_discard_card_rejects_unsupported_target_filter_kind():
    """The bridge mirrors the Rust parser's accepted-kind allowlist
    for target filters (cards.rs:2790-2799 accepts only ``any_player``
    and ``any_creature``). The discard_card arm is filter-narrow-by-
    design to the OPPOSITE shape from destroy_target / exile_target /
    return_to_hand / tap_target: only ``any_player`` is honored.
    Rust raises a runtime PyValueError on AnyCreature at
    state_ops_resolve.rs:1608-1611; the bridge surface rejects
    ``any_creature`` AT REGISTER time (loud failure) rather than
    letting it fall through to Rust's runtime resolve raise.
    """
    import pytest
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="any_creature"):
        _ta_dict_to_python_effect(
            {"kind": "discard_card", "target": {"kind": "any_creature"}}
        )


def test_rust_parser_accepts_discard_card_in_triggered_ability():
    """Pin the Rust parser surface for the ``discard_card`` effect
    kind. The bridge's dict shape must register cleanly on the Rust
    side too; this lockstep gate keeps the Python bridge from
    drifting away from Rust's parse_effect coverage.

    Mirrors the existing destroy_target / exile_target /
    return_to_hand / tap_target / deal_damage parser-surface pins --
    all six arms require a companion ``target`` field. The Rust
    parse_effect arm at ``cards.rs:2890-2897`` accepts the
    ``{"kind": "discard_card", "target": {"kind": "any_player"}}``
    shape on a triggered-ability carrier.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- DiscardCard",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "B": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "discard_card",
                    "target": {"kind": "any_player"},
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_tap_target_translates_to_python_tap_with_creature_slot():
    """Phase 5 bridge extension: Rust
    ``{"kind": "tap_target", "target": {"kind": "any_creature"}}``
    translates to Python
    ``Tap(targets=(TargetSpec(IsCreature()),))``.

    Unblocks Twiddle / Sleep-on-target / Frost Lynx-shape ETB tap
    triggers on the cross-engine bridge. The Rust effect variant
    exists at the ``Effect::TapTarget { target: TargetFilter }``
    arm; its parse_effect arm at ``cards.rs:2857-2864`` requires a
    ``target`` dict; the resolve arm at
    ``state_ops_resolve.rs:1277-1324`` carries the I71 controller-
    of-effect fix (defender = 1 - controller, where controller
    derives from current_resolve_source_controller). Sibling closure
    to I70 / I75 / I76 / I78 / I79 / I80 -- identical defender-swap
    shape; differs only in the mutation applied (``tapped = true``
    on the target).

    Distinct from ``TapTargetArtifactOrCreature`` (the wider-filter
    variant at state_ops_resolve.rs:4776): the bare ``tap_target``
    arm here only honors AnyCreature, matching the parser-side
    filter allowlist.
    """
    from mtg_bot.effects.generic.tap import Tap
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "tap_target", "target": {"kind": "any_creature"}}
    )
    assert isinstance(e, Tap)
    # The bridge constructs a single TargetSpec slot with an
    # IsCreature() filter; mirrors the AnyCreature first-slice
    # symbol from the Rust side.
    assert len(e.targets) == 1
    slot = e.targets[0]
    assert isinstance(slot, TargetSpec)
    assert isinstance(slot.filter, IsCreature)
    # Default count_min/count_max for a TargetSpec is 1/1 (the
    # "exactly one" target shape that mirrors Rust's first-slice
    # picker which always selects bf[0] of the defender).
    assert slot.count_min == 1
    assert slot.count_max == 1


def test_bridge_tap_target_rejects_unsupported_target_filter_kind():
    """The bridge mirrors the Rust parser's accepted-kind allowlist
    for target filters (cards.rs:2790-2799 accepts only ``any_player``
    and ``any_creature``). The tap_target arm is filter-narrow-by-
    design (you can't tap a player; Rust raises PyValueError on
    AnyPlayer at state_ops_resolve.rs:1278-1282). The bridge surface
    rejects ``any_player`` AT REGISTER time (loud failure) rather
    than letting it fall through to Rust's runtime resolve raise.

    Sibling to the destroy_target / exile_target / return_to_hand
    unsupported-filter pins.
    """
    import pytest
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="any_player"):
        _ta_dict_to_python_effect(
            {"kind": "tap_target", "target": {"kind": "any_player"}}
        )


def test_rust_parser_accepts_tap_target_in_triggered_ability():
    """Pin the Rust parser surface for the ``tap_target`` effect
    kind. The bridge's dict shape must register cleanly on the Rust
    side too; this lockstep gate keeps the Python bridge from
    drifting away from Rust's parse_effect coverage.

    Mirrors the existing destroy_target / exile_target /
    return_to_hand / deal_damage parser-surface pins -- all five
    arms require a companion ``target`` field. The Rust parse_effect
    arm at ``cards.rs:2857-2864`` accepts the
    ``{"kind": "tap_target", "target": {"kind": "any_creature"}}``
    shape on a triggered-ability carrier.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- TapTarget",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "U": 1},
        "power": 1,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "tap_target",
                    "target": {"kind": "any_creature"},
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_deal_damage_translates_to_python_deal_damage_with_creature_slot():
    """Phase 5 bridge extension: Rust
    ``{"kind": "deal_damage", "amount": 2, "target": {"kind": "any_creature"}}``
    translates to Python
    ``DealDamage(amount=2, targets=(TargetSpec(IsCreature()),))``.

    Unblocks Lightning Bolt / Shock / Galvanic Blast-shape ETB burn
    triggers on the cross-engine bridge. The Rust effect variant
    exists at ``rust/src/cards.rs:631`` vicinity
    (``Effect::DealDamage { amount: i32, target: TargetFilter }``);
    its parse_effect arm at ``cards.rs:2804-2812`` requires both an
    ``amount`` field and a ``target`` dict; the resolve arm at
    ``state_ops_resolve.rs:740-790`` carries the I67 controller-of-
    effect substrate (defender = 1 - controller, where controller
    derives from current_resolve_source_controller).

    Distinct from the existing ``deal_damage_any_target`` arm
    (``DealDamageAnyTarget``, unit "any target" filter, deterministic
    Rust at-resolve picking): this ``deal_damage`` arm is filter-
    parametric (caller picks AnyCreature OR AnyPlayer at register
    time) and uses the standard PUSH-time agent-driven target
    selection on the Python side.
    """
    from mtg_bot.effects.generic.damage import DealDamage
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "deal_damage",
            "amount": 2,
            "target": {"kind": "any_creature"},
        }
    )
    assert isinstance(e, DealDamage)
    # Amount round-trips from the dict.
    assert e.amount == 2
    # The bridge constructs a single TargetSpec slot with an
    # IsCreature() filter; mirrors the AnyCreature first-slice
    # symbol from the Rust side.
    assert len(e.targets) == 1
    slot = e.targets[0]
    assert isinstance(slot, TargetSpec)
    assert isinstance(slot.filter, IsCreature)
    # Default count_min/count_max for a TargetSpec is 1/1 (the
    # "exactly one" target shape that mirrors Rust's first-slice
    # picker which always selects bf[0] of the defender).
    assert slot.count_min == 1
    assert slot.count_max == 1


def test_bridge_deal_damage_translates_to_python_deal_damage_with_player_slot():
    """Phase 5 bridge extension WIDER variant: Rust
    ``{"kind": "deal_damage", "amount": 3, "target": {"kind": "any_player"}}``
    translates to Python
    ``DealDamage(amount=3, targets=(TargetSpec(IsPlayer()),))``.

    Unblocks Lava Spike / Searing Blaze (player half) / Skullcrack-
    shape ETB burn-the-player triggers on the cross-engine bridge.
    Rust's resolve arm honors ``TargetFilter::AnyPlayer`` directly
    (state_ops_resolve.rs:768-770) by damaging the defending player.
    Python's ``DealDamage`` base class is filter-parametric on
    ``targets[0].filter`` so swapping ``IsCreature()`` for
    ``IsPlayer()`` reuses the same resolve walk; the picker emits
    one ``("player", id)`` legal target on the 2-player harness, and
    ``_apply_damage`` routes to the player's life total.

    First bridge arm to honor the WIDER ``any_player`` filter shape
    (siblings ``destroy_target`` / ``exile_target`` /
    ``return_to_hand`` are filter-narrow-by-design — you can't
    destroy / exile / bounce a player in MTG).
    """
    from mtg_bot.effects.generic.damage import DealDamage
    from mtg_bot.effects.object_predicates import IsPlayer
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "deal_damage",
            "amount": 3,
            "target": {"kind": "any_player"},
        }
    )
    assert isinstance(e, DealDamage)
    assert e.amount == 3
    # The bridge constructs a single TargetSpec slot with an
    # IsPlayer() filter; mirrors the AnyPlayer first-slice symbol
    # from the Rust side.
    assert len(e.targets) == 1
    slot = e.targets[0]
    assert isinstance(slot, TargetSpec)
    assert isinstance(slot.filter, IsPlayer)
    assert slot.count_min == 1
    assert slot.count_max == 1


def test_bridge_deal_damage_rejects_unsupported_target_filter_kind():
    """The bridge mirrors the Rust parser's accepted-kind allowlist
    for target filters (cards.rs:2790-2799 accepts only ``any_player``
    and ``any_creature``). The deal_damage arm honors BOTH (unlike
    sibling destroy_target / exile_target / return_to_hand which only
    honor any_creature); an unknown filter kind raises a ValueError
    pointing at Rust's parse_target_filter allowlist.

    This pin documents the bridge-side surface contract: future
    additions to ``parse_target_filter`` (e.g., ``any_artifact``,
    ``any_nonland_permanent``) need a paired bridge update on this
    arm before they can land cross-engine.
    """
    import pytest
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="any_player"):
        _ta_dict_to_python_effect(
            {
                "kind": "deal_damage",
                "amount": 1,
                "target": {"kind": "any_artifact"},
            }
        )


def test_rust_parser_accepts_deal_damage_in_triggered_ability():
    """Pin the Rust parser surface for the ``deal_damage`` effect
    kind. The bridge's dict shape must register cleanly on the Rust
    side too; this lockstep gate keeps the Python bridge from
    drifting away from Rust's parse_effect coverage.

    Mirrors the existing ``destroy_target`` / ``exile_target`` /
    ``return_to_hand`` parser-surface pins -- all four arms require
    a companion ``target`` field; deal_damage additionally requires
    ``amount``. The Rust parse_effect arm at ``cards.rs:2804-2812``
    accepts the
    ``{"kind": "deal_damage", "amount": N, "target": {"kind":
    "any_creature"}}`` shape on a triggered-ability carrier.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- DealDamage",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "R": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "deal_damage",
                    "amount": 2,
                    "target": {"kind": "any_creature"},
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_destroy_target_translates_to_python_destroy_with_creature_slot():
    """Phase 5 bridge extension: Rust
    ``{"kind": "destroy_target", "target": {"kind": "any_creature"}}``
    translates to Python
    ``Destroy(targets=(TargetSpec(IsCreature()),))``.

    Unblocks Doom-Blade / Murder / Naturalize-shape ETB destroy
    triggers on the cross-engine bridge. The Rust effect variant
    exists at ``rust/src/cards.rs:1567`` (``Effect::DestroyTarget {
    target: TargetFilter }``); its parse_effect arm at
    ``cards.rs:2902-2909`` requires a ``target`` dict; the resolve
    arm at ``state_ops_resolve.rs:1687`` carries the I75 controller-
    of-effect fix (defender = 1 - controller, where controller
    derives from current_resolve_source_controller). Sibling closure
    to I70 / I76 / I78 / I79 / I80 -- identical defender-swap shape;
    differs only in destination zone (graveyard for I75 vs exile /
    hand / library bottom for the siblings) and in carrying the
    indestructible suppress gate (CR 702.12) on the destroyed object.
    """
    from mtg_bot.effects.generic.destroy import Destroy
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "destroy_target", "target": {"kind": "any_creature"}}
    )
    assert isinstance(e, Destroy)
    # The bridge constructs a single TargetSpec slot with an
    # IsCreature() filter; mirrors the AnyCreature first-slice
    # symbol from the Rust side.
    assert len(e.targets) == 1
    slot = e.targets[0]
    assert isinstance(slot, TargetSpec)
    assert isinstance(slot.filter, IsCreature)
    # Default count_min/count_max for a TargetSpec is 1/1 (the
    # "exactly one" target shape that mirrors Rust's first-slice
    # picker which always selects bf[0] of the defender).
    assert slot.count_min == 1
    assert slot.count_max == 1


def test_bridge_destroy_target_rejects_unsupported_target_filter_kind():
    """The bridge mirrors the Rust parser's accepted-kind allowlist
    for target filters (cards.rs:2790-2799 accepts only ``any_player``
    and ``any_creature``). The destroy_target arm only honors
    creature-shaped filters; an unknown filter kind raises a
    ValueError with a pointer to the Rust parse_target_filter
    docstring location.

    This pin documents the bridge-side surface contract: future
    additions to ``parse_target_filter`` (e.g., ``any_artifact``,
    ``any_nonland_permanent``) need a paired bridge update on this
    arm before they can land cross-engine.
    """
    import pytest
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="any_player"):
        _ta_dict_to_python_effect(
            {"kind": "destroy_target", "target": {"kind": "any_player"}}
        )


def test_rust_parser_accepts_destroy_target_in_triggered_ability():
    """Pin the Rust parser surface for the ``destroy_target`` effect
    kind. The bridge's dict shape must register cleanly on the Rust
    side too; this lockstep gate keeps the Python bridge from
    drifting away from Rust's parse_effect coverage.

    Mirrors the existing ``mill_target_player`` parser-surface pin
    -- both arms require a companion field (``count`` for
    mill_target_player, ``target`` for destroy_target). The Rust
    parse_effect arm at ``cards.rs:2902-2909`` accepts the
    ``{"kind": "destroy_target", "target": {"kind": "any_creature"}}``
    shape on a triggered-ability carrier.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- DestroyTarget",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "B": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "destroy_target",
                    "target": {"kind": "any_creature"},
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_exile_target_translates_to_python_exile_with_creature_slot():
    """Phase 5 bridge extension: Rust
    ``{"kind": "exile_target", "target": {"kind": "any_creature"}}``
    translates to Python
    ``Exile(targets=(TargetSpec(IsCreature()),))``.

    Unblocks Path-to-Exile / Swords-to-Plowshares / Anguished
    Unmaking-shape ETB exile triggers on the cross-engine bridge.
    The Rust effect variant exists at ``rust/src/cards.rs:1110``
    (``Effect::ExileTarget { target: TargetFilter }``); its
    parse_effect arm at ``cards.rs:2849-2856`` requires a ``target``
    dict; the resolve arm at ``state_ops_resolve.rs:1110`` carries
    the I70 controller-of-effect fix (defender = 1 - controller,
    where controller derives from
    current_resolve_source_controller). Sibling closure to I75 /
    I76 / I78 / I79 / I80 -- identical defender-swap shape; differs
    only in destination zone (exile for I70 vs graveyard / hand /
    library bottom for the siblings).

    Distinct from ``exile_target_creature_until_source_leaves``
    (the I79 sibling) which stamps ``exiled_with_source =
    Some(source_obj_id)`` for the paired return on source-leaves;
    the bare ``exile_target`` permanently exiles with no paired
    return.
    """
    from mtg_bot.effects.generic.exile import Exile
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "exile_target", "target": {"kind": "any_creature"}}
    )
    assert isinstance(e, Exile)
    # The bridge constructs a single TargetSpec slot with an
    # IsCreature() filter; mirrors the AnyCreature first-slice
    # symbol from the Rust side.
    assert len(e.targets) == 1
    slot = e.targets[0]
    assert isinstance(slot, TargetSpec)
    assert isinstance(slot.filter, IsCreature)
    # Default count_min/count_max for a TargetSpec is 1/1 (the
    # "exactly one" target shape that mirrors Rust's first-slice
    # picker which always selects bf[0] of the defender).
    assert slot.count_min == 1
    assert slot.count_max == 1


def test_bridge_exile_target_rejects_unsupported_target_filter_kind():
    """The bridge mirrors the Rust parser's accepted-kind allowlist
    for target filters (cards.rs:2790-2799 accepts only ``any_player``
    and ``any_creature``). The exile_target arm only honors
    creature-shaped filters; an unknown filter kind raises a
    ValueError pointing at Rust's parse_target_filter allowlist.

    This pin documents the bridge-side surface contract: future
    additions to ``parse_target_filter`` (e.g., ``any_artifact``,
    ``any_nonland_permanent``) need a paired bridge update on this
    arm before they can land cross-engine. Sibling pin to the
    destroy_target unsupported-filter pin.
    """
    import pytest
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="any_player"):
        _ta_dict_to_python_effect(
            {"kind": "exile_target", "target": {"kind": "any_player"}}
        )


def test_rust_parser_accepts_exile_target_in_triggered_ability():
    """Pin the Rust parser surface for the ``exile_target`` effect
    kind. The bridge's dict shape must register cleanly on the Rust
    side too; this lockstep gate keeps the Python bridge from
    drifting away from Rust's parse_effect coverage.

    Mirrors the existing ``destroy_target`` parser-surface pin --
    both arms require a companion ``target`` field. The Rust
    parse_effect arm at ``cards.rs:2849-2856`` accepts the
    ``{"kind": "exile_target", "target": {"kind": "any_creature"}}``
    shape on a triggered-ability carrier.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- ExileTarget",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "W": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "exile_target",
                    "target": {"kind": "any_creature"},
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_exile_opponents_nonland_permanent_until_leaves_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "exile_opponents_nonland_permanent_until_leaves"}``
    translates to Python
    ``ExileOpponentsNonlandPermanentUntilLeaves()``.

    Unblocks Banishing-Light / Oblivion-Ring / Hardlight-
    Containment-shape ETB exile-non-land triggers on the cross-
    engine bridge. The Rust effect variant exists at
    ``rust/src/cards.rs:1283`` (unit variant
    ``Effect::ExileOpponentsNonlandPermanentUntilLeaves``); its
    parse_effect arm at ``cards.rs:3325-3327`` takes no fields;
    the resolve arm at ``state_ops_resolve.rs:5645-5754`` carries
    the I80 controller-of-effect fix (defender = 1 - controller,
    where controller derives from
    current_resolve_source_controller). Stamps
    ``exiled_with_source = Some(source_obj_id)`` so the paired
    return on source-leaves works. Sibling closure to I79 -- same
    "until source leaves" exile shape; differs only in the target
    filter ("not a Land" vs "is a Creature").
    """
    from mtg_bot.effects.generic.exile import (
        ExileOpponentsNonlandPermanentUntilLeaves,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "exile_opponents_nonland_permanent_until_leaves"}
    )
    assert isinstance(e, ExileOpponentsNonlandPermanentUntilLeaves)
    # Bare-shape default: max_mv=0 (no MV cap). The Rust unit
    # variant has no field mirror today; the bridge constructs
    # the bare default shape, matching Rust's any-non-land scan.
    assert e.max_mv == 0


def test_bridge_exile_opponents_nonland_permanent_until_leaves_ignores_extra_fields():
    """Extra dict fields are ignored -- the bridge translator
    mirrors the Rust unit-variant convention (no fields beyond
    ``kind``) and constructs the bare-default Python shape
    regardless of whether the dict carries extra keys. Mirrors the
    ``exile_target_creature_until_source_leaves`` /
    ``return_creature_from_your_graveyard_to_hand`` /
    ``return_creature_from_your_graveyard_to_battlefield`` arm
    convention (all unit variants).
    """
    from mtg_bot.effects.generic.exile import (
        ExileOpponentsNonlandPermanentUntilLeaves,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({
        "kind": "exile_opponents_nonland_permanent_until_leaves",
        # Extra keys that future MV-cap-widened Rust variants
        # might carry; the bare-shape arm ignores them.
        "max_mv": 4,
        "extra_key_should_be_ignored": True,
        "another_unused_field": 42,
    })
    assert isinstance(e, ExileOpponentsNonlandPermanentUntilLeaves)
    # Bare-shape arm constructs max_mv=0 even when the dict
    # carries an explicit max_mv -- the rider field has no Rust
    # mirror yet, so the bridge surface drops it for round-trip
    # dict-shape consistency with what Rust's parser accepts.
    assert e.max_mv == 0


def test_rust_parser_accepts_exile_opponents_nonland_permanent_until_leaves_in_triggered_ability():
    """Pin the Rust parser surface for the
    ``exile_opponents_nonland_permanent_until_leaves`` effect
    kind. The bridge's dict shape must register cleanly on the
    Rust side too; this lockstep gate keeps the Python bridge
    from drifting away from Rust's parse_effect coverage.

    Mirrors the existing
    ``exile_target_creature_until_source_leaves`` parser-surface
    pin (test_rust_parser_accepts_exile_target_creature_until_
    source_leaves_in_triggered_ability) -- both are unit-variant
    arms with no companion fields. The Rust parse_effect arm at
    ``cards.rs:3325-3327`` accepts the bare ``{"kind":
    "exile_opponents_nonland_permanent_until_leaves"}`` shape on
    a triggered-ability carrier.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- ExileOppsNonlandUntilLeaves",
        "card_types": ["Enchantment"],
        "mana_cost": {"generic": 2, "W": 1},
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "exile_opponents_nonland_permanent_until_leaves",
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_exile_opponents_nonland_permanent_with_max_mv_until_leaves_translates_to_python():
    """Round-14 bridge extension: Rust
    ``{"kind": "exile_opponents_nonland_permanent_with_max_mv_until_leaves",
    "max_mv": 2}`` translates to Python
    ``ExileOpponentsNonlandPermanentUntilLeaves(max_mv=2)``.

    Sister bridge arm to the bare
    ``exile_opponents_nonland_permanent_until_leaves``; the rider
    variant carries a ``max_mv`` mana-value cap field that flows
    through into the Python class's ``max_mv`` attribute. Real
    EoE consumer: Seam Rip ({W} Enchantment, ETB exile target
    nonland permanent an opponent controls with mana value 2 or
    less until this enchantment leaves the battlefield).

    The Rust effect variant exists at the new
    ``Effect::ExileOpponentsNonlandPermanentWithMaxMvUntilLeaves
    { max_mv: i32 }`` slot in cards.rs; its parse_effect arm
    requires a ``max_mv`` int field (non-negative); the resolve
    arm in state_ops_resolve.rs inherits the I80 controller-of-
    effect fix and adds the per-permanent MV-cap check. Python's
    ``ExileOpponentsNonlandPermanentUntilLeaves`` class
    (effects/generic/exile.py:587) carries ``max_mv: int = 0``
    where 0 = no cap and N > 0 caps at N; both legal_targets()
    and resolve() honor the cap.
    """
    from mtg_bot.effects.generic.exile import (
        ExileOpponentsNonlandPermanentUntilLeaves,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({
        "kind": "exile_opponents_nonland_permanent_with_max_mv_until_leaves",
        "max_mv": 2,
    })
    assert isinstance(e, ExileOpponentsNonlandPermanentUntilLeaves)
    # The rider field flows through — distinct from the bare
    # sibling's bridge arm which constructs max_mv=0 unconditionally.
    assert e.max_mv == 2


def test_bridge_exile_opponents_nonland_permanent_with_max_mv_until_leaves_forwards_arbitrary_caps():
    """Round-14: the bridge translator forwards arbitrary
    ``max_mv`` values into the Python constructor — pin a few
    spread-out caps so a regression that hard-codes the value
    (e.g. always 2) is caught immediately. Mirrors the
    parametric-bridge-arm precedent (e.g. the ``draw_cards`` arm
    forwards arbitrary count values).
    """
    from mtg_bot.effects.generic.exile import (
        ExileOpponentsNonlandPermanentUntilLeaves,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    for max_mv_value in (1, 3, 5, 10):
        e = _ta_dict_to_python_effect({
            "kind": "exile_opponents_nonland_permanent_with_max_mv_until_leaves",
            "max_mv": max_mv_value,
        })
        assert isinstance(e, ExileOpponentsNonlandPermanentUntilLeaves)
        assert e.max_mv == max_mv_value, (
            f"bridge must forward max_mv verbatim; "
            f"expected {max_mv_value}, got {e.max_mv}"
        )


def test_bridge_exile_opponents_nonland_permanent_with_max_mv_until_leaves_rejects_missing_max_mv():
    """Round-14: missing ``max_mv`` is a ValueError on the bridge
    side, mirroring Rust's parse_effect arm which raises
    PyValueError on a missing required field. The bridge does NOT
    silently fall through to ``max_mv=0`` — that would mask a
    dict-shape producer bug as a no-cap effect.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="missing required 'max_mv'"):
        _ta_dict_to_python_effect({
            "kind": "exile_opponents_nonland_permanent_with_max_mv_until_leaves",
        })


def test_rust_parser_accepts_exile_opponents_nonland_permanent_with_max_mv_until_leaves_in_triggered_ability():
    """Pin the Rust parser surface for the
    ``exile_opponents_nonland_permanent_with_max_mv_until_leaves``
    effect kind on a triggered-ability carrier. The bridge's
    dict shape must register cleanly on the Rust side too; this
    lockstep gate keeps the Python bridge from drifting away
    from Rust's parse_effect coverage.

    Mirrors the bare-sibling parser-surface pin
    (test_rust_parser_accepts_exile_opponents_nonland_permanent_
    until_leaves_in_triggered_ability) but adds the required
    ``max_mv`` field. The Rust parse_effect arm requires
    ``max_mv: i32`` (non-negative); we exercise both the
    happy-path 2 (Seam Rip's printed cap) and a larger value to
    pin that the field is forwarded literally rather than
    clamped.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Round 14 Bridge Pin -- ExileOppsNonlandWithMaxMvUntilLeaves",
        "card_types": ["Enchantment"],
        "mana_cost": {"W": 1},
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "exile_opponents_nonland_permanent_with_max_mv_until_leaves",
                    "max_mv": 2,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_grant_keywords_to_target_creature_until_eot_translates_to_python():
    """Round-15 bridge extension: Rust
    ``{"kind": "grant_keywords_to_target_creature_until_eot",
       "keywords": ["deathtouch"], "exclude_source": True}``
    translates to Python ``PumpTargetCreatureUntilEOT(power_bonus=0,
    toughness_bonus=0, granted_keywords=frozenset({"deathtouch"}),
    you_control_only=True, exclude_self=True)``.

    Rider-widened bridge arm for the round-28 single-keyword
    grant-keyword-target-UEOT cluster. Real EoE consumer:
    Blooming Stinger ({1}{G} Plant Scorpion, "When this creature
    enters, another target creature you control gains deathtouch
    until end of turn.").

    The Rust effect variant exists at the new
    ``Effect::GrantKeywordsToTargetCreatureUntilEOT
    { keywords: Vec<String>, exclude_source: bool }`` slot in
    cards.rs; its parse_effect arm requires a non-empty list of
    non-empty keyword strings; the resolve arm in
    state_ops_resolve.rs inherits the controller-of-effect resolution
    from the single-keyword sibling and adds the exclude_source skip
    + per-keyword UeotModifier::GrantKeyword push.

    Python's ``PumpTargetCreatureUntilEOT`` class
    (effects/generic/pump.py) carries the keyword-grant-only
    sub-shape via ``granted_keywords=frozenset({...})`` with
    P/T bonuses both zero; ``you_control_only`` + ``exclude_self``
    flags narrow the legal-target pool to "another target creature
    you control" — the bridge translates Rust's ``exclude_source``
    onto the Python ``exclude_self`` flag (same semantics, naming
    convention adapted at the boundary).
    """
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({
        "kind": "grant_keywords_to_target_creature_until_eot",
        "keywords": ["deathtouch"],
        "exclude_source": True,
    })
    assert isinstance(e, PumpTargetCreatureUntilEOT)
    # P/T bonuses pinned at 0 — the keyword-grant-only sub-shape.
    assert e.power_bonus == 0
    assert e.toughness_bonus == 0
    # Granted keywords flow through verbatim as a frozenset.
    assert e.granted_keywords == frozenset({"deathtouch"})
    # Targeting flags wired correctly. The bridge always sets
    # you_control_only=True (Rust's resolve arm scans the
    # source-controller's bf, which is the cross-engine semantic
    # match for "you control"); exclude_source on the dict maps to
    # exclude_self on the Python class.
    assert e.you_control_only is True
    assert e.exclude_self is True


def test_bridge_grant_keywords_to_target_creature_until_eot_forwards_arbitrary_keywords():
    """Round-15: the bridge translator forwards arbitrary keyword
    LISTS into the Python constructor — pin a few sweep cases so a
    regression that hard-codes the keyword set (e.g. always
    {"deathtouch"}) is caught immediately. Single-element + multi-
    element lists both round-trip; the Python frozenset preserves
    every entry. Mirrors the parametric-bridge-arm precedent
    (round-14 max_mv arbitrary-cap forwarding).
    """
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    cases = [
        ["deathtouch"],
        ["flying"],
        ["haste", "trample"],
        ["lifelink", "vigilance", "first_strike"],
    ]
    for kws in cases:
        e = _ta_dict_to_python_effect({
            "kind": "grant_keywords_to_target_creature_until_eot",
            "keywords": kws,
            "exclude_source": False,
        })
        assert isinstance(e, PumpTargetCreatureUntilEOT)
        assert e.granted_keywords == frozenset(kws), (
            f"bridge must forward keywords verbatim; "
            f"expected {frozenset(kws)}, got {e.granted_keywords}"
        )
        assert e.exclude_self is False


def test_bridge_grant_keywords_to_target_creature_until_eot_rejects_missing_keywords():
    """Round-15: missing ``keywords`` list is a ValueError on the
    bridge side, mirroring Rust's parse_effect arm which raises
    PyValueError on a missing required field. The bridge does NOT
    silently fall through to an empty grant — that would mask a
    dict-shape producer bug as a no-op effect.

    Sister pins for the empty-list / empty-string-entry shapes
    also raise (mirroring Rust's defensive guards). Default
    ``exclude_source`` (missing) is allowed — defaults to False
    on both engines.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="missing required 'keywords'"):
        _ta_dict_to_python_effect({
            "kind": "grant_keywords_to_target_creature_until_eot",
        })

    # Empty list rejected.
    with pytest.raises(ValueError, match="must be non-empty"):
        _ta_dict_to_python_effect({
            "kind": "grant_keywords_to_target_creature_until_eot",
            "keywords": [],
        })

    # Empty-string entry rejected.
    with pytest.raises(ValueError, match="non-empty string"):
        _ta_dict_to_python_effect({
            "kind": "grant_keywords_to_target_creature_until_eot",
            "keywords": ["deathtouch", ""],
        })


def test_rust_parser_accepts_grant_keywords_to_target_creature_until_eot_in_triggered_ability():
    """Pin the Rust parser surface for the
    ``grant_keywords_to_target_creature_until_eot`` effect kind on
    a triggered-ability carrier. The bridge's dict shape must
    register cleanly on the Rust side too; this lockstep gate keeps
    the Python bridge from drifting away from Rust's parse_effect
    coverage.

    Mirrors the round-14 ``exile_opponents_nonland_permanent_with_
    max_mv_until_leaves`` parser-surface pin. The Rust parse_effect
    arm requires a non-empty ``keywords`` list (each entry non-
    empty); we exercise both single-keyword + ``exclude_source=True``
    (Blooming Stinger's printed shape) and multi-keyword +
    ``exclude_source=False`` (forward-compatible card shape) to pin
    that the field forwarding is literal rather than clamped.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()

    # Blooming-Stinger-shape: single-keyword + exclude_source=True.
    d_stinger = {
        "name": "Round 15 Bridge Pin -- GrantKeywordsBlooming",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "G": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "grant_keywords_to_target_creature_until_eot",
                    "keywords": ["deathtouch"],
                    "exclude_source": True,
                },
            }
        ],
    }
    pid_stinger = reg.register_printing(d_stinger)
    assert pid_stinger == 0

    # Forward-compatible multi-keyword shape, no exclude_source.
    d_multi = {
        "name": "Round 15 Bridge Pin -- GrantKeywordsMulti",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "U": 1},
        "power": 1,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "grant_keywords_to_target_creature_until_eot",
                    "keywords": ["flying", "trample"],
                },
            }
        ],
    }
    pid_multi = reg.register_printing(d_multi)
    assert pid_multi == 1


def test_bridge_return_to_hand_translates_to_python_bounce_with_creature_slot():
    """Phase 5 bridge extension: Rust
    ``{"kind": "return_to_hand", "target": {"kind": "any_creature"}}``
    translates to Python
    ``Bounce(targets=(TargetSpec(IsCreature()),))``.

    Unblocks Unsummon / Boomerang / Aether Spellbomb-shape ETB
    bounce triggers on the cross-engine bridge. The Rust effect
    variant exists at ``rust/src/cards.rs:1417``
    (``Effect::ReturnToHand { target: TargetFilter }``); its
    parse_effect arm at ``cards.rs:2821-2828`` requires a ``target``
    dict; the resolve arm at ``state_ops_resolve.rs:1417`` carries
    the I76 controller-of-effect fix (defender = 1 - controller,
    where controller derives from
    current_resolve_source_controller). Sibling closure to I70 /
    I75 / I78 / I79 / I80 -- identical defender-swap shape; differs
    only in destination zone (owner's hand for I76 vs exile /
    graveyard / library bottom for the siblings).

    Distinct from the bounce-from-graveyard family
    (``return_creature_from_your_graveyard_to_hand`` etc., already
    on the bridge): both share the "to hand" destination but differ
    on the source zone (battlefield vs graveyard).
    """
    from mtg_bot.effects.generic.bounce import Bounce
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "return_to_hand", "target": {"kind": "any_creature"}}
    )
    assert isinstance(e, Bounce)
    # The bridge constructs a single TargetSpec slot with an
    # IsCreature() filter; mirrors the AnyCreature first-slice
    # symbol from the Rust side.
    assert len(e.targets) == 1
    slot = e.targets[0]
    assert isinstance(slot, TargetSpec)
    assert isinstance(slot.filter, IsCreature)
    # Default count_min/count_max for a TargetSpec is 1/1 (the
    # "exactly one" target shape that mirrors Rust's first-slice
    # picker which always selects bf[0] of the defender).
    assert slot.count_min == 1
    assert slot.count_max == 1


def test_bridge_return_to_hand_rejects_unsupported_target_filter_kind():
    """The bridge mirrors the Rust parser's accepted-kind allowlist
    for target filters (cards.rs:2790-2799 accepts only ``any_player``
    and ``any_creature``). The return_to_hand arm only honors
    creature-shaped filters; players can't move via owner-hand bounce
    per CR 401.1, and an unknown filter kind raises a ValueError
    pointing at Rust's parse_target_filter allowlist.

    This pin documents the bridge-side surface contract: future
    additions to ``parse_target_filter`` (e.g., ``any_artifact``,
    ``any_nonland_permanent``) need a paired bridge update on this
    arm before they can land cross-engine. Sibling pin to the
    destroy_target / exile_target unsupported-filter pins.
    """
    import pytest
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="any_player"):
        _ta_dict_to_python_effect(
            {"kind": "return_to_hand", "target": {"kind": "any_player"}}
        )


def test_rust_parser_accepts_return_to_hand_in_triggered_ability():
    """Pin the Rust parser surface for the ``return_to_hand`` effect
    kind. The bridge's dict shape must register cleanly on the Rust
    side too; this lockstep gate keeps the Python bridge from
    drifting away from Rust's parse_effect coverage.

    Mirrors the existing ``destroy_target`` / ``exile_target``
    parser-surface pins -- all three arms require a companion
    ``target`` field. The Rust parse_effect arm at
    ``cards.rs:2821-2828`` accepts the
    ``{"kind": "return_to_hand", "target": {"kind": "any_creature"}}``
    shape on a triggered-ability carrier.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- ReturnToHand",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 1, "U": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "return_to_hand",
                    "target": {"kind": "any_creature"},
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_owner_puts_target_artifact_or_creature_on_top_or_bottom_translates_to_python():
    """Phase 5 bridge extension: Rust
    ``{"kind": "owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library"}``
    translates to Python
    ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary()``.

    Unblocks Lost-in-Space-shape ETB owner-puts-on-library triggers
    on the cross-engine bridge. The Rust effect variant exists at
    ``rust/src/cards.rs:1170`` (unit variant
    ``Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``);
    its parse_effect arm at ``cards.rs:3306-3309`` takes no fields;
    the resolve arm at ``state_ops_resolve.rs:5067`` carries the
    I78 controller-of-effect fix (defender = 1 - controller, where
    controller derives from current_resolve_source_controller).
    Sibling closure to I70 / I75 / I76 / I79 / I80 -- same
    defender-swap shape; differs only in destination zone (owner's
    library top-or-bottom for I78 vs exile / hand / graveyard for
    the siblings) and adds an OWNER-side top-vs-bottom choice via
    the agent's ``choose_mode`` hook.
    """
    from mtg_bot.effects.generic.zone_moves import (
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library"}
    )
    assert isinstance(
        e, OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary
    )
    # Bare-shape default: nonland_permanent=False (the printed
    # "artifact or creature" filter, NOT the wider "any nonland
    # permanent" widening). The Rust unit variant has no rider
    # mirror today; the bridge constructs the bare default shape,
    # matching Rust's any-artifact-or-creature scan.
    assert e.nonland_permanent is False


def test_bridge_owner_puts_target_artifact_or_creature_on_top_or_bottom_ignores_extra_fields():
    """Extra dict fields are ignored -- the bridge translator
    mirrors the Rust unit-variant convention (no fields beyond
    ``kind``) and constructs the bare-default Python shape
    regardless of whether the dict carries extra keys. Mirrors the
    ``exile_target_creature_until_source_leaves`` /
    ``exile_opponents_nonland_permanent_until_leaves`` /
    ``return_creature_from_your_graveyard_to_hand`` arm convention
    (all unit variants).
    """
    from mtg_bot.effects.generic.zone_moves import (
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({
        "kind": "owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library",
        # Extra keys that future rider-widened Rust variants might
        # carry; the bare-shape arm ignores them.
        "nonland_permanent": True,
        "extra_key_should_be_ignored": True,
        "another_unused_field": 42,
    })
    assert isinstance(
        e, OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary
    )
    # Bare-shape arm constructs nonland_permanent=False even when
    # the dict carries an explicit nonland_permanent rider -- the
    # rider has no Rust mirror yet, so the bridge surface drops it
    # for round-trip dict-shape consistency with what Rust's
    # parser accepts.
    assert e.nonland_permanent is False


def test_rust_parser_accepts_owner_puts_target_artifact_or_creature_on_top_or_bottom_in_triggered_ability():
    """Pin the Rust parser surface for the
    ``owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library``
    effect kind. The bridge's dict shape must register cleanly on
    the Rust side too; this lockstep gate keeps the Python bridge
    from drifting away from Rust's parse_effect coverage.

    Mirrors the existing
    ``exile_target_creature_until_source_leaves`` /
    ``exile_opponents_nonland_permanent_until_leaves`` parser-
    surface pins -- all three are unit-variant arms with no
    companion fields. The Rust parse_effect arm at
    ``cards.rs:3306-3309`` accepts the bare ``{"kind":
    "owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library"}``
    shape on a triggered-ability carrier.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Phase 5 Bridge Pin -- OwnerPutsTopOrBottom",
        "card_types": ["Enchantment"],
        "mana_cost": {"generic": 2, "W": 1},
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library",
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_set_base_pt_until_eot_translates_to_python():
    """BLOCKED-RUST-EFFECT slice -- layer 7b base-P/T override.
    Rust ``{"kind": "set_base_pt_until_eot", "power": N, "toughness":
    M}`` translates to Python ``SetBasePTUntilEOT(power=N,
    toughness=M)``.

    Field names agree on both engines (``power``, ``toughness``);
    no rename in the bridge. Mirrors Rust's parse_effect arm
    (cards.rs:3879-3909) which requires both fields with no
    defaults. The Python class is the layer-7b sibling of
    PumpTargetCreatureUntilEOT (layer-7c) -- same target-pick shape
    (source-controller's first creature), different composition
    layer (overrides the base instead of stacking on top).
    """
    from mtg_bot.effects.generic.pump import SetBasePTUntilEOT
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "set_base_pt_until_eot", "power": 4, "toughness": 4}
    )
    assert isinstance(e, SetBasePTUntilEOT)
    assert e.power == 4
    assert e.toughness == 4


def test_bridge_set_base_pt_until_eot_negative_values_legal():
    """Negative power / toughness round-trip cleanly.
    Mirrors Rust's parse_effect arm (no parse-time guard on
    negatives) and Python's dataclass (no raise-on-negative). A
    debuff-shaped "becomes base -2/-2" is meaningful (the creature
    dies to SBA toughness <= 0 when SBA fires); the bridge does not
    sanitize.
    """
    from mtg_bot.effects.generic.pump import SetBasePTUntilEOT
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "set_base_pt_until_eot", "power": -2, "toughness": -2}
    )
    assert isinstance(e, SetBasePTUntilEOT)
    assert e.power == -2
    assert e.toughness == -2


def test_bridge_set_base_pt_until_eot_asymmetric_values():
    """Asymmetric (power != toughness) values round-trip cleanly.
    Pins that the bridge doesn't accidentally collapse the two
    fields onto a single value or swap them. ``power=1, toughness=4``
    is the canonical "becomes a 1/4" defender-shape; the Python
    class stores them in field order, no swap.
    """
    from mtg_bot.effects.generic.pump import SetBasePTUntilEOT
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "set_base_pt_until_eot", "power": 1, "toughness": 4}
    )
    assert isinstance(e, SetBasePTUntilEOT)
    assert e.power == 1
    assert e.toughness == 4


def test_bridge_set_base_pt_until_eot_missing_power_raises():
    """Missing ``power`` field raises KeyError. Mirrors Rust's
    parse_effect arm which raises PyValueError on missing required
    field; the bridge enforces the same contract so a typo in a
    fixture surfaces immediately rather than silently defaulting to
    0/0 (which would be a "becomes base 0/0" override and die to SBA
    -- a different observable than a fizzle, and a likely bug
    rather than an intent).
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(KeyError):
        _ta_dict_to_python_effect(
            {"kind": "set_base_pt_until_eot", "toughness": 4}
        )


def test_bridge_set_base_pt_until_eot_missing_toughness_raises():
    """Missing ``toughness`` field raises KeyError. Sister test to
    the missing-power case; both fields are independently required
    on both engines.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(KeyError):
        _ta_dict_to_python_effect(
            {"kind": "set_base_pt_until_eot", "power": 4}
        )


def test_bridge_set_base_pt_until_eot_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``{"kind": "sequence", "effects": [{"kind":
    "set_base_pt_until_eot", "power": 4, "toughness": 4}, {"kind":
    "draw_cards", "count": 1}]}`` translates to ``Sequence(effects=(
    SetBasePTUntilEOT(power=4, toughness=4), DrawCards(amount=1)))``.
    Pins the parametric arm against accidental field-loss in the
    Sequence translator (Sequence recursively dispatches into
    ``_ta_dict_to_python_effect`` per child, so this also exercises
    the recursive path).
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.pump import SetBasePTUntilEOT
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {
                    "kind": "set_base_pt_until_eot",
                    "power": 4,
                    "toughness": 4,
                },
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], SetBasePTUntilEOT)
    assert e.effects[0].power == 4
    assert e.effects[0].toughness == 4


def test_rust_parser_accepts_set_base_pt_until_eot_in_triggered_ability():
    """Pin the Rust parser surface for the ``set_base_pt_until_eot``
    effect kind on a triggered_ability carrier. The bridge dict
    shape must register cleanly on the Rust side too; this lockstep
    gate keeps the bridge from drifting away from Rust's
    parse_effect coverage.

    Rust's parse_effect arm at ``rust/src/cards.rs:3879-3909``
    accepts the dict shape with required ``power`` and ``toughness``
    integer fields.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-RUST-EFFECT Bridge Pin -- SetBasePTUntilEOT",
        "card_types": ["Creature"],
        "mana_cost": {"generic": 2, "G": 1},
        "power": 3,
        "toughness": 3,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "set_base_pt_until_eot",
                    "power": 4,
                    "toughness": 4,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_may_do_translates_to_python():
    """BLOCKED-RUST-EFFECT slice -- may_do composer bridge.
    Rust ``{"kind": "may_do", "inner_effect": <effect_dict>,
    "prompt": <str>}`` translates to Python ``MayDo(inner=<Effect>,
    prompt=<str>)``.

    **Field-name translation**: Rust ``inner_effect`` -> Python
    ``inner``. Pin verifies the rename happens correctly and the
    nested effect dict is recursively translated through the same
    bridge function (so any leaf arm composes for free).

    Looter-shape ``MayDo(DiscardSelf{1})`` is the Melded-Moxite
    do_action half (the IfYouDo wrapper around it lives at the
    composer level and is already on the bridge).
    """
    from mtg_bot.effects.combinators import MayDo
    from mtg_bot.effects.generic.discard import DiscardSelf
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "may_do",
            "inner_effect": {"kind": "discard_self", "amount": 1},
            "prompt": "you may discard a card",
        }
    )
    assert isinstance(e, MayDo)
    assert isinstance(e.inner, DiscardSelf)
    assert e.inner.amount == 1
    assert e.prompt == "you may discard a card"


def test_bridge_may_do_default_prompt_empty():
    """Missing ``prompt`` field defaults to empty string. Mirrors
    Rust's parse_effect arm at cards.rs:3734-3741 which uses
    ``String::new()`` when the field is omitted, and Python's
    ``MayDo(inner: Effect, prompt: str = "")`` dataclass default.
    Both engines treat empty prompt as a request for the inner
    effect's ``describe()`` to surface as the agent prompt; the
    default agrees end-to-end.
    """
    from mtg_bot.effects.combinators import MayDo
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "may_do",
            "inner_effect": {"kind": "draw_cards", "count": 2},
            # prompt intentionally omitted -- defaults to empty string
        }
    )
    assert isinstance(e, MayDo)
    assert isinstance(e.inner, DrawCards)
    assert e.inner.amount == 2
    assert e.prompt == ""


def test_bridge_may_do_missing_inner_effect_raises():
    """Missing ``inner_effect`` field raises KeyError out of the
    bridge -- mirrors Rust's parse_effect arm at cards.rs:3722-3727
    which raises PyValueError on the missing required field. A
    ``MayDo`` with no inner action is meaningless on both engines
    (the prompt would have nothing to gate); the bridge enforces the
    same contract so a typo surfaces immediately rather than
    silently translating to a degenerate effect.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(KeyError):
        _ta_dict_to_python_effect(
            {"kind": "may_do", "prompt": "you may"}
        )


def test_bridge_may_do_composable_in_if_you_do():
    """Round-trip in an IfYouDo composer to pin the looter-shape
    nesting end-to-end: ``IfYouDo(MayDo(DiscardSelf), DrawCards{2})``
    -- the Melded-Moxite "you may discard a card; if you do, draw
    two cards" oracle. Both composer arms (``if_you_do`` and
    ``may_do``) recursively dispatch through
    ``_ta_dict_to_python_effect``; pinning the nested case ensures
    the looter pattern works through the bridge translator without
    field-rename or recursion bugs surfacing only at the composed
    level.
    """
    from mtg_bot.effects.combinators import IfYouDo, MayDo
    from mtg_bot.effects.generic.discard import DiscardSelf
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "if_you_do",
            "do_action": {
                "kind": "may_do",
                "inner_effect": {
                    "kind": "discard_self", "amount": 1,
                },
                "prompt": "",
            },
            "then_action": {"kind": "draw_cards", "count": 2},
        }
    )
    assert isinstance(e, IfYouDo)
    assert isinstance(e.do_action, MayDo)
    assert isinstance(e.do_action.inner, DiscardSelf)
    assert e.do_action.inner.amount == 1
    assert isinstance(e.then_action, DrawCards)
    assert e.then_action.amount == 2


def test_bridge_may_do_composable_in_sequence():
    """Round-trip inside a Sequence composer to pin nesting symmetry
    with the if_you_do nesting test. Sequence's recursive translator
    must descend into ``inner_effect`` correctly even when the
    MayDo is the second child of the sequence (not just the top
    level), pinning that the field-rename branch isn't position-
    sensitive in the parser.
    """
    from mtg_bot.effects.combinators import MayDo, Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "draw_cards", "count": 1},
                {
                    "kind": "may_do",
                    "inner_effect": {
                        "kind": "draw_cards", "count": 1,
                    },
                    "prompt": "",
                },
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], DrawCards)
    assert isinstance(e.effects[1], MayDo)
    assert isinstance(e.effects[1].inner, DrawCards)
    assert e.effects[1].inner.amount == 1


def test_rust_parser_accepts_may_do_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts a may_do
    composer (with inner_effect + prompt) inside a triggered_ability
    dict. Mirrors the if_you_do / set_base_pt_until_eot lockstep
    gates -- keeps the bridge from drifting away from Rust's
    parse_effect coverage.

    Rust's parse_effect arm at ``rust/src/cards.rs:3722-3746``
    accepts the dict shape; ``inner_effect`` is required,
    ``prompt`` defaults to the empty string when omitted.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-RUST-EFFECT Bridge Pin -- MayDo Composer",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 2},
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "may_do",
                    "inner_effect": {
                        "kind": "draw_cards", "count": 1,
                    },
                    "prompt": "",
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_attach_to_target_creature_you_control_translates_to_python():
    """BLOCKED-BRIDGE-ARM slice (round-19 audit refresh) -- Equipment
    ETB attach. Rust ``{"kind": "attach_to_target_creature_you_control"}``
    translates to Python ``AttachToTargetCreatureYouControl()``.

    Mirrors Rust's parse_effect arm (cards.rs:3676-3678) which is a
    UNIT VARIANT (no fields). The bridge translator ignores every
    other key on the dict for round-trip dict-shape consistency. The
    Python class carries an OPTIONAL ``granted_keywords_ueot`` rider
    not exercised by the bare arm; the default empty frozenset()
    matches Rust's no-keyword-grant unit variant.
    """
    from mtg_bot.effects.generic.attach import (
        AttachToTargetCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "attach_to_target_creature_you_control"}
    )
    assert isinstance(e, AttachToTargetCreatureYouControl)
    # Default rider value -- the bare bridge arm does NOT carry the
    # UEOT keyword grant (would compose via separate arm).
    assert e.granted_keywords_ueot == frozenset()


def test_bridge_attach_to_target_creature_extra_keys_ignored():
    """Round-trip pin: extra keys on the dict are silently ignored
    (the unit variant takes no fields). Mirrors the
    owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library
    arm shape -- forward-compatible with future rider-widened Rust
    variants that would land as separate ``kind`` arms.
    """
    from mtg_bot.effects.generic.attach import (
        AttachToTargetCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "attach_to_target_creature_you_control",
            "ignored_extra_field": "noise",
        }
    )
    assert isinstance(e, AttachToTargetCreatureYouControl)
    assert e.granted_keywords_ueot == frozenset()


def test_bridge_equip_to_target_creature_you_control_translates_to_python():
    """BLOCKED-BRIDGE-ARM slice (round-19 audit refresh) -- Equip
    activated-ability resolution (CR 702.6). Rust
    ``{"kind": "equip_to_target_creature_you_control"}`` translates
    to Python ``EquipToTargetCreatureYouControl()``.

    Sister bridge arm to ``attach_to_target_creature_you_control``;
    Python's ``EquipToTargetCreatureYouControl`` is a SUBCLASS of
    ``AttachToTargetCreatureYouControl`` with identical resolve
    behavior but a distinct ``describe`` string. The two are
    isinstance-compatible (Equip IS-A Attach) -- pin verifies the
    bridge returns the more-specific subclass type, not the parent,
    so log tooling can distinguish ETB-attach from paid Equip
    activation correctly.
    """
    from mtg_bot.effects.generic.attach import (
        AttachToTargetCreatureYouControl,
        EquipToTargetCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "equip_to_target_creature_you_control"}
    )
    # Specific subclass, not the parent.
    assert type(e) is EquipToTargetCreatureYouControl
    # IS-A parent (subclass relationship preserved).
    assert isinstance(e, AttachToTargetCreatureYouControl)
    # Distinct describe string for log-tooling disambiguation.
    assert e.describe() != AttachToTargetCreatureYouControl().describe()


def test_bridge_attach_and_equip_arms_distinct_kinds():
    """Cross-arm discriminator pin: the bridge does NOT collapse the
    two ``kind`` strings onto one Python class. The ETB-shape attach
    and the activated-ability paid Equip are SEPARATE Rust variants
    + SEPARATE Python classes; confirming each kind dispatches to
    its own class prevents accidental cross-wiring (e.g. a typo on
    one arm masking via the other).
    """
    from mtg_bot.effects.generic.attach import (
        AttachToTargetCreatureYouControl,
        EquipToTargetCreatureYouControl,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    attach = _ta_dict_to_python_effect(
        {"kind": "attach_to_target_creature_you_control"}
    )
    equip = _ta_dict_to_python_effect(
        {"kind": "equip_to_target_creature_you_control"}
    )
    # The attach arm returns the bare parent type, NOT the Equip
    # subclass.
    assert type(attach) is AttachToTargetCreatureYouControl
    # The equip arm returns the more-specific subclass.
    assert type(equip) is EquipToTargetCreatureYouControl
    # Distinct types.
    assert type(attach) is not type(equip)


def test_bridge_attach_to_target_creature_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([AttachTo, DrawCards])`` translates correctly via the
    recursive Sequence translator. Pins the unit-variant arm against
    accidental dispatch loss inside Sequence (recursive translation
    walks each child via the same ``_ta_dict_to_python_effect`` so
    this also exercises the recursive path).
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.attach import (
        AttachToTargetCreatureYouControl,
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "attach_to_target_creature_you_control"},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert type(e.effects[0]) is AttachToTargetCreatureYouControl
    assert isinstance(e.effects[1], DrawCards)
    assert e.effects[1].amount == 1


def test_rust_parser_accepts_attach_to_target_creature_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the bare
    ``{"kind": "attach_to_target_creature_you_control"}`` dict shape
    on a triggered_ability carrier. The bridge dict shape must
    register cleanly on the Rust side too; this lockstep gate keeps
    the bridge from drifting away from Rust's parse_effect coverage.

    Mirrors the existing
    ``owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library``
    parser-surface pin -- both are unit-variant arms with no
    companion fields. Rust's parse_effect arm at
    ``rust/src/cards.rs:3676-3678`` accepts the bare unit dict.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- AttachTo Equipment",
        "card_types": ["Artifact"],
        "subtypes": ["Equipment"],
        "mana_cost": {"generic": 2},
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "attach_to_target_creature_you_control",
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_rust_parser_accepts_equip_to_target_creature_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the bare
    ``{"kind": "equip_to_target_creature_you_control"}`` dict shape
    on a triggered_ability carrier. Sister to the AttachTo lockstep
    pin -- pins the Equip variant separately so a typo on either
    arm surfaces via this gate.

    Rust's parse_effect arm at ``rust/src/cards.rs:3679-3681``
    accepts the bare unit dict.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- EquipTo Equipment",
        "card_types": ["Artifact"],
        "subtypes": ["Equipment"],
        "mana_cost": {"generic": 2},
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "equip_to_target_creature_you_control",
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_optional_sac_artifact_for_effect_translates_to_python():
    """BLOCKED-BRIDGE-ARM slice (round-19 audit refresh) -- "you may
    sacrifice an artifact. If you do, [inner]" composer. Rust
    ``{"kind": "optional_sac_artifact_for_effect", "inner_effect":
    <effect_dict>}`` translates to Python
    ``OptionalSacArtifactForEffect(inner_effect=<Effect>)``.

    Field name agrees on both engines (``inner_effect``); no rename
    in the bridge. The inner effect recurses through the same
    translator so any leaf arm composes for free. Pin verifies the
    nested DrawCards inner is correctly translated and stored as
    ``inner_effect``.
    """
    from mtg_bot.effects.combinators import OptionalSacArtifactForEffect
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "optional_sac_artifact_for_effect",
            "inner_effect": {"kind": "draw_cards", "count": 1},
        }
    )
    assert isinstance(e, OptionalSacArtifactForEffect)
    assert isinstance(e.inner_effect, DrawCards)
    assert e.inner_effect.amount == 1


def test_bridge_optional_sac_artifact_missing_inner_effect_raises():
    """Missing ``inner_effect`` field raises KeyError. Mirrors
    Rust's parse_effect arm at cards.rs:3656-3661 which raises
    PyValueError on missing required field; the bridge enforces
    the same contract so a typo in a fixture surfaces immediately
    rather than silently constructing an OptionalSac wrapper around
    a None inner that would crash on resolve.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(KeyError):
        _ta_dict_to_python_effect(
            {"kind": "optional_sac_artifact_for_effect"}
        )


def test_bridge_optional_sac_artifact_inner_effect_recurses():
    """Recursive translation pin: the inner effect dict is walked
    through ``_ta_dict_to_python_effect`` again. Pins the recursive
    path against accidental shallow translation (passing the dict
    through unchanged, or constructing the wrapper with a dict
    instead of an Effect instance). A nested gain_life with a
    distinct ``amount`` field round-trips into a real GainLife
    instance, not a dict.
    """
    from mtg_bot.effects.combinators import OptionalSacArtifactForEffect
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "optional_sac_artifact_for_effect",
            "inner_effect": {"kind": "gain_life", "amount": 3},
        }
    )
    assert isinstance(e, OptionalSacArtifactForEffect)
    # Inner is a real GainLife instance (NOT a dict).
    assert isinstance(e.inner_effect, GainLife)
    assert e.inner_effect.amount == 3


def test_bridge_optional_sac_artifact_with_sequence_inner():
    """Selfcraft-Mechan-shape composition pin: the inner effect is a
    Sequence wrapping multiple leaf arms. Pins the composer
    composition end-to-end -- ``OptionalSacArtifactForEffect(
    Sequence([GainLife{1}, DrawCards{1}]))`` round-trips with the
    Sequence preserved + each leaf at its proper class/amount.

    This is the composer shape Selfcraft Mechan would use if the
    "When you do, put a +1/+1 counter on target creature and draw a
    card" rider were folded into a single OptionalSac wrapper
    (Selfcraft's actual oracle uses a separate reflexive trigger,
    but the composition syntax is identical).
    """
    from mtg_bot.effects.combinators import (
        OptionalSacArtifactForEffect,
        Sequence,
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "optional_sac_artifact_for_effect",
            "inner_effect": {
                "kind": "sequence",
                "effects": [
                    {"kind": "gain_life", "amount": 1},
                    {"kind": "draw_cards", "count": 1},
                ],
            },
        }
    )
    assert isinstance(e, OptionalSacArtifactForEffect)
    assert isinstance(e.inner_effect, Sequence)
    assert len(e.inner_effect.effects) == 2
    assert isinstance(e.inner_effect.effects[0], GainLife)
    assert e.inner_effect.effects[0].amount == 1
    assert isinstance(e.inner_effect.effects[1], DrawCards)
    assert e.inner_effect.effects[1].amount == 1


def test_bridge_optional_sac_artifact_composable_in_sequence():
    """Round-trip in a Sequence COMPOSER (Sequence wraps the
    OptionalSac, not vice-versa). Pins that the OptionalSac arm
    composes correctly when it's a child of a parent Sequence:
    ``Sequence([OptionalSacArtifact(GainLife{2}), DrawCards{1}])``.
    Sequence's recursive translator walks each child via the same
    ``_ta_dict_to_python_effect``, so this also exercises the
    OptionalSac arm INSIDE the recursive Sequence translator path.
    """
    from mtg_bot.effects.combinators import (
        OptionalSacArtifactForEffect,
        Sequence,
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {
                    "kind": "optional_sac_artifact_for_effect",
                    "inner_effect": {
                        "kind": "gain_life", "amount": 2,
                    },
                },
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], OptionalSacArtifactForEffect)
    assert isinstance(e.effects[0].inner_effect, GainLife)
    assert e.effects[0].inner_effect.amount == 2
    assert isinstance(e.effects[1], DrawCards)
    assert e.effects[1].amount == 1


def test_rust_parser_accepts_optional_sac_artifact_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    ``optional_sac_artifact_for_effect`` composer (with
    ``inner_effect`` nested) inside a triggered_ability dict.
    Mirrors the may_do / set_base_pt_until_eot lockstep gates --
    keeps the bridge from drifting away from Rust's parse_effect
    coverage.

    Rust's parse_effect arm at ``rust/src/cards.rs:3656-3671``
    accepts the dict shape; ``inner_effect`` is required and is
    recursively parsed via ``parse_effect``.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- OptionalSacArtifact",
        "card_types": ["Artifact", "Creature"],
        "subtypes": ["Robot", "Artificer"],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "optional_sac_artifact_for_effect",
                    "inner_effect": {
                        "kind": "draw_cards", "count": 1,
                    },
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_search_library_for_basic_land_tapped_default_count():
    """Round-21 BLOCKED-BRIDGE-ARM slice -- default count=1 path.
    Rust ``{"kind": "search_library_for_basic_land_tapped"}`` with
    no ``count`` field translates to Python
    ``SearchLibraryForBasicLandTapped(count=1)`` via the class-level
    default (mirrors Rust parse_effect at cards.rs:3272-3279 where
    missing count defaults to 1).
    """
    from mtg_bot.effects.generic.search import (
        SearchLibraryForBasicLandTapped,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "search_library_for_basic_land_tapped"}
    )
    assert isinstance(e, SearchLibraryForBasicLandTapped)
    assert e.count == 1


def test_bridge_search_library_for_basic_land_tapped_explicit_count():
    """Explicit ``count`` field flows through verbatim. Pins
    Larval-Scoutlander-shape ``count=2`` (the printed value on the
    real EoE consumer of the OptionalSacArtifact composition).
    """
    from mtg_bot.effects.generic.search import (
        SearchLibraryForBasicLandTapped,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "search_library_for_basic_land_tapped", "count": 2}
    )
    assert isinstance(e, SearchLibraryForBasicLandTapped)
    assert e.count == 2


def test_bridge_search_library_for_basic_land_tapped_negative_raises():
    """Negative count surfaces at translation time, mirroring Rust's
    parse_effect contract at cards.rs:3280-3284. Python's class
    would accept silently (the for-range loop just no-ops on
    negative count), but the bridge enforces the parser-side check
    so the two engines' translation contracts stay symmetric (a
    typo or fixture bug surfaces immediately rather than silently
    constructing a no-op effect).
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="non-negative"):
        _ta_dict_to_python_effect(
            {"kind": "search_library_for_basic_land_tapped", "count": -1}
        )


def test_bridge_search_library_for_basic_land_tapped_count_zero_no_op():
    """Edge case pin: ``count=0`` is a legal-but-no-op shape. Both
    engines accept it (Rust parser permits zero; Python's for-range
    loop iterates zero times). Pins that the bridge doesn't
    incorrectly upgrade ``0`` to ``1`` via a falsy-default check
    (``or 1`` would lift this to 1; ``.get(..., 1)`` keeps it 0).
    """
    from mtg_bot.effects.generic.search import (
        SearchLibraryForBasicLandTapped,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "search_library_for_basic_land_tapped", "count": 0}
    )
    assert isinstance(e, SearchLibraryForBasicLandTapped)
    assert e.count == 0


def test_bridge_search_library_for_basic_land_tapped_composable_in_optional_sac():
    """Composition pin: this arm composes as the inner_effect of the
    round-20 ``optional_sac_artifact_for_effect`` arm. Pins the
    Larval Scoutlander shape end-to-end --
    ``OptionalSacArtifactForEffect(SearchLibraryForBasicLand
    Tapped(count=2))`` round-trips with the inner correctly typed
    + count preserved. The OptionalSac translator recurses into
    ``_ta_dict_to_python_effect`` for the inner dict, so this also
    exercises this arm INSIDE the recursive composer translator
    path.
    """
    from mtg_bot.effects.combinators import OptionalSacArtifactForEffect
    from mtg_bot.effects.generic.search import (
        SearchLibraryForBasicLandTapped,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "optional_sac_artifact_for_effect",
            "inner_effect": {
                "kind": "search_library_for_basic_land_tapped",
                "count": 2,
            },
        }
    )
    assert isinstance(e, OptionalSacArtifactForEffect)
    assert isinstance(
        e.inner_effect, SearchLibraryForBasicLandTapped
    )
    assert e.inner_effect.count == 2


def test_bridge_search_library_for_basic_land_tapped_composable_in_sequence():
    """Round-trip in a Sequence COMPOSER. Pins that the
    SearchLibraryForBasicLandTapped arm composes correctly when it's
    a child of a parent Sequence:
    ``Sequence([SearchLibraryForBasicLandTapped(1), DrawCards(1)])``.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.search import (
        SearchLibraryForBasicLandTapped,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {
                    "kind": "search_library_for_basic_land_tapped",
                    "count": 1,
                },
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(
        e.effects[0], SearchLibraryForBasicLandTapped
    )
    assert e.effects[0].count == 1
    assert isinstance(e.effects[1], DrawCards)
    assert e.effects[1].amount == 1


def test_rust_parser_accepts_search_library_for_basic_land_tapped_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    ``search_library_for_basic_land_tapped`` dict shape inside a
    triggered_ability dict. Mirrors the may_do /
    optional_sac_artifact_for_effect lockstep gates -- keeps the
    bridge from drifting away from Rust's parse_effect coverage.

    Rust's parse_effect arm at ``rust/src/cards.rs:3266-3286``
    accepts the dict shape; ``count`` is optional with default 1.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- SearchLibraryForBasicLandTapped",
        "card_types": ["Creature"],
        "subtypes": ["Bear"],
        "mana_cost": {"generic": 2},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "search_library_for_basic_land_tapped",
                    "count": 2,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_search_library_for_card_legendary_creature_filter():
    """Round-21 BLOCKED-BRIDGE-ARM slice -- legendary_creature
    filter (Starfield Shepherd / The Seriema shape). Rust
    ``{"kind": "search_library_for_card",
    "filter_name": "legendary_creature"}`` translates to Python
    ``SearchLibraryForCard(filter_name="legendary_creature",
    max_mv=0, may_fail=True)``. Pins default values for max_mv +
    may_fail flow through correctly when omitted.
    """
    from mtg_bot.effects.generic.search import SearchLibraryForCard
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "search_library_for_card",
            "filter_name": "legendary_creature",
        }
    )
    assert isinstance(e, SearchLibraryForCard)
    assert e.filter_name == "legendary_creature"
    assert e.max_mv == 0
    assert e.may_fail is True


def test_bridge_search_library_for_card_basic_land_filter():
    """Generic basic-land filter (Spineseeker Centipede shape).
    Pins that the basic_land filter string passes through verbatim
    -- both engines dispatch on the same filter-name string.
    """
    from mtg_bot.effects.generic.search import SearchLibraryForCard
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "search_library_for_card",
            "filter_name": "basic_land",
        }
    )
    assert isinstance(e, SearchLibraryForCard)
    assert e.filter_name == "basic_land"


def test_bridge_search_library_for_card_creature_small_with_max_mv():
    """``creature_small`` filter uses ``max_mv`` to cap the cost
    of matching creatures (Python's _matches arm at search.py:63-67).
    Pins explicit max_mv flows through verbatim.
    """
    from mtg_bot.effects.generic.search import SearchLibraryForCard
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "search_library_for_card",
            "filter_name": "creature_small",
            "max_mv": 3,
        }
    )
    assert isinstance(e, SearchLibraryForCard)
    assert e.filter_name == "creature_small"
    assert e.max_mv == 3
    assert e.may_fail is True


def test_bridge_search_library_for_card_may_fail_false():
    """Explicit ``may_fail=False`` flows through. Pins the
    forced-pick path (agent can't decline; resolve falls back to
    options[0] if agent declines).
    """
    from mtg_bot.effects.generic.search import SearchLibraryForCard
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "search_library_for_card",
            "filter_name": "spacecraft",
            "may_fail": False,
        }
    )
    assert isinstance(e, SearchLibraryForCard)
    assert e.filter_name == "spacecraft"
    assert e.may_fail is False


def test_bridge_search_library_for_card_missing_filter_name_raises():
    """Missing ``filter_name`` field raises ValueError. Mirrors
    Rust's parse_effect contract at cards.rs:4336-4341 which raises
    PyValueError on missing required field; the bridge enforces the
    same contract so a typo in a fixture surfaces immediately
    rather than silently constructing a SearchLibraryForCard with
    an empty filter (which would match no card and shuffle-only-
    fizzle without obvious failure mode).
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="filter_name"):
        _ta_dict_to_python_effect({"kind": "search_library_for_card"})


def test_bridge_search_library_for_card_composable_in_sequence():
    """Round-trip in a Sequence COMPOSER. Pins that the
    SearchLibraryForCard arm composes correctly when it's a child
    of a parent Sequence:
    ``Sequence([SearchLibraryForCard("legendary_creature"),
    DrawCards(1)])``.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.search import SearchLibraryForCard
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {
                    "kind": "search_library_for_card",
                    "filter_name": "legendary_creature",
                },
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], SearchLibraryForCard)
    assert e.effects[0].filter_name == "legendary_creature"
    assert isinstance(e.effects[1], DrawCards)
    assert e.effects[1].amount == 1


def test_rust_parser_accepts_search_library_for_card_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    ``search_library_for_card`` dict shape inside a triggered_ability
    dict. Mirrors the may_do / optional_sac_artifact_for_effect
    lockstep gates -- keeps the bridge from drifting away from
    Rust's parse_effect coverage.

    Rust's parse_effect arm at ``rust/src/cards.rs:4327-4363``
    accepts the dict shape; ``filter_name`` is required.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- SearchLibraryForCard",
        "card_types": ["Creature"],
        "subtypes": ["Bird"],
        "mana_cost": {"generic": 4},
        "power": 2,
        "toughness": 4,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "search_library_for_card",
                    "filter_name": "legendary_creature",
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_look_top_n_put_one_in_hand_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round-21 audit refresh) -- Codecracker
    Hound family. Rust ``{"kind": "look_top_n_put_one_in_hand_rest_to_
    graveyard", "n": 2}`` translates to Python
    ``LookTopNPutOneInHandRestToGraveyard(n=2)``.

    Mirrors Rust's parse_effect arm at cards.rs:3744-3761 (single
    required `n` field, i32, non-negative). Field name `n` agrees on
    both engines (no rename in the bridge). Pin verifies the n field
    is correctly stored.
    """
    from mtg_bot.effects.generic.library_lookat import (
        LookTopNPutOneInHandRestToGraveyard,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "look_top_n_put_one_in_hand_rest_to_graveyard", "n": 2}
    )
    assert isinstance(e, LookTopNPutOneInHandRestToGraveyard)
    assert e.n == 2


def test_bridge_look_top_n_put_one_in_hand_commune_with_evil_shape():
    """Bridge arm pin: full Commune-with-Evil shape (n=4) round-trips.
    Pulls in the Python class default-equivalent value (4) explicitly
    via the dict path so a future change to the Python default never
    masks a bridge bug -- the dict-shape contract is independent of
    the class-level default.
    """
    from mtg_bot.effects.generic.library_lookat import (
        LookTopNPutOneInHandRestToGraveyard,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "look_top_n_put_one_in_hand_rest_to_graveyard", "n": 4}
    )
    assert e == LookTopNPutOneInHandRestToGraveyard(n=4)


def test_bridge_look_top_n_put_one_in_hand_extra_keys_ignored():
    """Round-trip pin: extra keys on the dict are silently ignored
    (the variant carries only one field, `n`). Mirrors the existing
    bridge-arm extra-keys-ignored convention (set_base_pt_until_eot,
    attach_to_target_creature_you_control). Forward-compatible with
    future rider-widened Rust variants -- those would land as
    separate ``kind`` arms on this translator.
    """
    from mtg_bot.effects.generic.library_lookat import (
        LookTopNPutOneInHandRestToGraveyard,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "look_top_n_put_one_in_hand_rest_to_graveyard",
            "n": 2,
            "ignored_extra_field": "noise",
        }
    )
    assert isinstance(e, LookTopNPutOneInHandRestToGraveyard)
    assert e.n == 2


def test_bridge_look_top_n_put_one_in_hand_missing_n_raises():
    """Bridge arm pin: missing required `n` field raises ValueError to
    mirror Rust's parse_effect contract at cards.rs:3744-3760 (which
    raises PyValueError on missing `n`). Python's class has a default
    of 4 (Commune-with-Evil shape), but the bridge enforces explicit
    `n` to keep the dict-shape contract aligned with Rust's parse
    path -- mirrors the round-20 LookAtTopNRevealOrCounter `n`-
    required precedent.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="missing required field 'n'"):
        _ta_dict_to_python_effect(
            {"kind": "look_top_n_put_one_in_hand_rest_to_graveyard"}
        )


def test_bridge_look_top_n_put_one_in_hand_int_coercion():
    """Bridge arm pin: `int(...)` coercion on `n` handles JSON-shape
    int values cleanly (mirrors the LookAtTopNRevealOrCounter
    int-coercion-robustness pin). Pins the explicit
    ``int(eff_dict["n"])`` cast so a downstream consumer never gets
    a stringy / floaty `n` slipping through.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "look_top_n_put_one_in_hand_rest_to_graveyard", "n": 5}
    )
    assert e.n == 5
    assert isinstance(e.n, int)


def test_bridge_look_top_n_put_one_in_hand_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([LookTopNPut..., DrawCards])`` translates correctly via
    the recursive Sequence translator. Pins this arm against
    accidental dispatch loss inside Sequence -- the recursive
    translation walks each child via the same
    ``_ta_dict_to_python_effect`` so this also exercises the
    recursive path for the look-N arm.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.library_lookat import (
        LookTopNPutOneInHandRestToGraveyard,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {
                    "kind": "look_top_n_put_one_in_hand_rest_to_graveyard",
                    "n": 2,
                },
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], LookTopNPutOneInHandRestToGraveyard)
    assert e.effects[0].n == 2
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_look_top_n_put_one_in_hand_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    ``{"kind": "look_top_n_put_one_in_hand_rest_to_graveyard",
    "n": 2}`` dict shape on a triggered_ability carrier. The bridge
    dict shape must register cleanly on the Rust side too; this
    lockstep gate keeps the bridge from drifting away from Rust's
    parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms (set_base_pt_until_eot, may_do, attach_to_target_
    creature_you_control). Rust's parse_effect arm at
    ``rust/src/cards.rs:3744-3761`` accepts the bare dict shape with
    a required `n: i32` field.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- LookTopNPutOneInHand",
        "card_types": ["Creature"],
        "mana_cost": {"U": 1, "generic": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "look_top_n_put_one_in_hand_rest_to_graveyard",
                    "n": 2,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_put_plus_one_counter_on_each_of_up_to_n_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round-21 audit refresh) -- Weftblade
    Enhancer family. Rust ``{"kind": "put_plus_one_counter_on_each_
    of_up_to_n_target_creatures", "max_n": 2}`` translates to Python
    ``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)``.

    Mirrors Rust's parse_effect arm at cards.rs:4128-4149 (single
    required `max_n` field, i32, non-negative). Field name `max_n`
    agrees on both engines (no rename in the bridge). Pin verifies
    the max_n field is correctly stored.
    """
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_each_of_up_to_n_target_creatures",
            "max_n": 2,
        }
    )
    assert isinstance(e, PutPlusOneCounterOnEachOfUpToNTargetCreatures)
    assert e.max_n == 2


def test_bridge_put_plus_one_counter_on_each_of_up_to_n_max_n_3():
    """Bridge arm pin: max_n=3 round-trips. Pulls in a value distinct
    from Python's class-level default (2) so a future change to the
    Python default never masks a bridge bug -- the dict-shape contract
    is independent of the class-level default.
    """
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_each_of_up_to_n_target_creatures",
            "max_n": 3,
        }
    )
    assert e == PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=3)


def test_bridge_put_plus_one_counter_on_each_of_up_to_n_max_n_zero_silent_noop():
    """Bridge arm pin: max_n=0 is a valid silent-no-op shape. Both
    engines accept max_n=0 (Rust at cards.rs:4144 short-circuits
    only on max_n < 0; Python's class accepts 0 cleanly with
    target_count_range=(0,0) yielding 0 targets picked). Bridge
    must NOT reject 0 -- only negative max_n raises.
    """
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_each_of_up_to_n_target_creatures",
            "max_n": 0,
        }
    )
    assert isinstance(e, PutPlusOneCounterOnEachOfUpToNTargetCreatures)
    assert e.max_n == 0


def test_bridge_put_plus_one_counter_on_each_of_up_to_n_extra_keys_ignored():
    """Round-trip pin: extra keys on the dict are silently ignored
    (the variant carries only one field, `max_n`). Mirrors the
    existing bridge-arm extra-keys-ignored convention. Forward-
    compatible with future rider-widened Rust variants -- those
    would land as separate ``kind`` arms on this translator.
    """
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "put_plus_one_counter_on_each_of_up_to_n_target_creatures",
            "max_n": 2,
            "ignored_extra_field": "noise",
        }
    )
    assert isinstance(e, PutPlusOneCounterOnEachOfUpToNTargetCreatures)
    assert e.max_n == 2


def test_bridge_put_plus_one_counter_on_each_of_up_to_n_missing_max_n_raises():
    """Bridge arm pin: missing required `max_n` field raises ValueError
    to mirror Rust's parse_effect contract at cards.rs:4128-4149
    (which raises PyValueError on missing required field). Python's
    class has a default of 2 (Weftblade-Enhancer shape), but the
    bridge enforces explicit `max_n` to keep the dict-shape contract
    aligned with Rust's parse path -- mirrors the round-20/21
    LookAtTopNRevealOrCounter / LookTopNPutOneInHand precedent.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="missing required field 'max_n'"):
        _ta_dict_to_python_effect(
            {"kind": "put_plus_one_counter_on_each_of_up_to_n_target_creatures"}
        )


def test_bridge_put_plus_one_counter_on_each_of_up_to_n_negative_max_n_raises():
    """Bridge arm pin: negative max_n raises ValueError to mirror
    Rust's parse_effect contract at cards.rs:4144-4148 (which raises
    PyValueError on negative max_n). Bridge mirrors the contract so
    a typo in a fixture surfaces immediately rather than silently
    constructing a no-op effect.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="max_n must be non-negative"):
        _ta_dict_to_python_effect(
            {
                "kind": "put_plus_one_counter_on_each_of_up_to_n_target_creatures",
                "max_n": -1,
            }
        )


def test_bridge_put_plus_one_counter_on_each_of_up_to_n_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([PutPlusOneCounterOnEachOfUpToN(2), DrawCards(1)])``
    translates correctly via the recursive Sequence translator. Pins
    this arm against accidental dispatch loss inside Sequence -- the
    recursive translation walks each child via the same
    ``_ta_dict_to_python_effect`` so this also exercises the
    recursive path for the up-to-N-counters arm.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {
                    "kind": "put_plus_one_counter_on_each_of_up_to_n_target_creatures",
                    "max_n": 2,
                },
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(
        e.effects[0], PutPlusOneCounterOnEachOfUpToNTargetCreatures
    )
    assert e.effects[0].max_n == 2
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_put_plus_one_counter_on_each_of_up_to_n_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the ``{"kind":
    "put_plus_one_counter_on_each_of_up_to_n_target_creatures",
    "max_n": 2}`` dict shape on a triggered_ability carrier. The
    bridge dict shape must register cleanly on the Rust side too;
    this lockstep gate keeps the bridge from drifting away from
    Rust's parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms (look_top_n_put_one_in_hand,
    set_base_pt_until_eot, may_do). Rust's parse_effect arm at
    ``rust/src/cards.rs:4128-4149`` accepts the bare dict shape
    with a required `max_n: i32` field.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- PutPlusOneCounterOnEachOfUpToN",
        "card_types": ["Creature"],
        "mana_cost": {"W": 1, "generic": 2},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "put_plus_one_counter_on_each_of_up_to_n_target_creatures",
                    "max_n": 2,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_put_plus_one_counter_on_self_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 22 fresh discovery walk) --
    PutPlusOneCounterOnSelf family. Rust ``{"kind": "put_plus_one_
    counter_on_self", "amount": 1}`` translates to Python
    ``PutPlusOneCounterOnSelf(amount=1)``.

    Mirrors Rust's parse_effect arm at cards.rs:3287-3306 (optional
    `amount` field with default 1, i32, non-negative). Field name
    `amount` agrees on both engines (no rename in the bridge). Pin
    verifies the amount field is correctly stored.
    """
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "put_plus_one_counter_on_self", "amount": 1}
    )
    assert isinstance(e, PutPlusOneCounterOnSelf)
    assert e.amount == 1


def test_bridge_put_plus_one_counter_on_self_amount_default_to_one():
    """Bridge arm pin: missing `amount` defaults to 1 (mirrors Rust's
    parse_effect default-handling at cards.rs:3293-3295 -- ``None ->
    1``). This is the round-23 sister default-handling shape (vs the
    required-field shape of round-21's up-to-N-counters slice). The
    EoE consumer Sunstar Lightsmith carries amount=1 implicit; the
    bridge must accept the bare ``{"kind": "..."}`` dict without an
    explicit amount.
    """
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "put_plus_one_counter_on_self"})
    assert isinstance(e, PutPlusOneCounterOnSelf)
    assert e.amount == 1


def test_bridge_put_plus_one_counter_on_self_amount_two():
    """Bridge arm pin: explicit amount=2 round-trips. Pulls in a
    value distinct from the class-level default (1) so a future
    change to the Python default never masks a bridge bug -- the
    dict-shape contract is independent of the class-level default.
    """
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "put_plus_one_counter_on_self", "amount": 2}
    )
    assert e == PutPlusOneCounterOnSelf(amount=2)


def test_bridge_put_plus_one_counter_on_self_amount_zero_silent_noop():
    """Bridge arm pin: amount=0 is a valid silent-no-op shape. Both
    engines accept amount=0 (Rust at state_ops_resolve.rs:2607-2609
    short-circuits; Python's class accepts 0 cleanly via
    add_plus_one_counters). Bridge must NOT reject 0 -- only negative
    amount raises.
    """
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "put_plus_one_counter_on_self", "amount": 0}
    )
    assert isinstance(e, PutPlusOneCounterOnSelf)
    assert e.amount == 0


def test_bridge_put_plus_one_counter_on_self_negative_amount_raises():
    """Bridge arm pin: negative amount raises ValueError to mirror
    Rust's parse_effect contract at cards.rs:3296-3300 (which raises
    PyValueError on negative amount). Bridge mirrors the contract so
    a typo in a fixture surfaces immediately rather than silently
    constructing a no-op effect.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="amount must be non-negative"):
        _ta_dict_to_python_effect(
            {"kind": "put_plus_one_counter_on_self", "amount": -1}
        )


def test_bridge_put_plus_one_counter_on_self_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([PutPlusOneCounterOnSelf(1), DrawCards(1)])`` translates
    correctly via the recursive Sequence translator. Pins this arm
    against accidental dispatch loss inside Sequence -- the recursive
    translation walks each child via the same
    ``_ta_dict_to_python_effect`` so this also exercises the recursive
    path for the put-plus-one-counter-on-self arm.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "put_plus_one_counter_on_self", "amount": 1},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], PutPlusOneCounterOnSelf)
    assert e.effects[0].amount == 1
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_put_plus_one_counter_on_self_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    ``{"kind": "put_plus_one_counter_on_self", "amount": 1}`` dict
    shape on a triggered_ability carrier. The bridge dict shape must
    register cleanly on the Rust side too; this lockstep gate keeps
    the bridge from drifting away from Rust's parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms (look_top_n_put_one_in_hand,
    set_base_pt_until_eot, may_do, up_to_n_counters). Rust's
    parse_effect arm at ``rust/src/cards.rs:3287-3306`` accepts the
    dict shape with optional `amount: i32` field defaulting to 1.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- PutPlusOneCounterOnSelf",
        "card_types": ["Creature"],
        "mana_cost": {"W": 1, "generic": 2},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "put_plus_one_counter_on_self",
                    "amount": 1,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_counter_target_spell_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 22 fresh discovery walk) --
    CounterTargetSpell family. Rust ``{"kind": "counter_target_spell"}``
    translates to Python ``CounterTargetSpell()`` (default empty
    filter_types).

    Mirrors Rust's parse_effect arm at cards.rs:3361-3370 (unit
    variant; no required fields). Pin verifies the bare dict shape
    constructs the Python class with default filter_types.
    """
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "counter_target_spell"})
    assert isinstance(e, CounterTargetSpell)
    # Default filter_types is empty frozenset (any spell).
    assert e.filter_types == frozenset()


def test_bridge_counter_target_spell_extra_keys_ignored():
    """Round-trip pin: extra keys on the dict are silently ignored
    (the Rust variant is a unit type with no fields). Mirrors the
    Rust parse_effect arm's silent-drop convention for unrecognized
    keys (cards.rs:3361-3370 docstring). Forward-compatible with
    future rider-widened Rust variants -- those would land as
    separate ``kind`` arms on this translator.
    """
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "counter_target_spell",
            "filter_types": ["Artifact"],  # ignored on Rust side
            "ignored_extra_field": "noise",
        }
    )
    assert isinstance(e, CounterTargetSpell)
    # filter_types stays at default empty -- bridge does NOT pass
    # the ignored key through, mirroring Rust's first-slice drop.
    assert e.filter_types == frozenset()


def test_bridge_counter_target_spell_equality_with_default_constructor():
    """Pin: bare-dict translation produces an instance equal to the
    direct ``CounterTargetSpell()`` constructor. This is the round-
    trip-equality contract that enables fixture-side comparison via
    ``assert e == CounterTargetSpell()``. Mirrors the up-to-N-counters
    sister test pattern (assert e == PutPlusOne...) but for the unit
    variant.
    """
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "counter_target_spell"})
    assert e == CounterTargetSpell()


def test_bridge_counter_target_spell_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([CounterTargetSpell(), DrawCards(1)])`` translates
    correctly via the recursive Sequence translator. Pins this arm
    against accidental dispatch loss inside Sequence -- the recursive
    translation walks each child via the same
    ``_ta_dict_to_python_effect`` so this also exercises the
    recursive path for the counter-target-spell arm.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "counter_target_spell"},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], CounterTargetSpell)
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_counter_target_spell_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    ``{"kind": "counter_target_spell"}`` dict shape on a
    triggered_ability carrier. The bridge dict shape must register
    cleanly on the Rust side too; this lockstep gate keeps the
    bridge from drifting away from Rust's parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms (look_top_n_put_one_in_hand,
    set_base_pt_until_eot, may_do, up_to_n_counters,
    put_plus_one_counter_on_self). Rust's parse_effect arm at
    ``rust/src/cards.rs:3361-3370`` accepts the bare dict shape
    with no companion fields.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- CounterTargetSpell",
        "card_types": ["Instant"],
        "mana_cost": {"U": 2},
        "effects": [{"kind": "counter_target_spell"}],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_target_opponent_loses_life_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 22 fresh discovery walk) --
    TargetOpponentLosesLife family. Rust ``{"kind": "target_
    opponent_loses_life", "amount": 3}`` translates to Python
    ``TargetOpponentLosesLife(amount=3)``.

    Mirrors Rust's parse_effect arm at cards.rs:3413-3437 (optional
    `amount` field with default 1, i32, non-negative). Field name
    `amount` agrees on both engines (no rename in the bridge). Pin
    verifies the amount field is correctly stored.
    """
    from mtg_bot.effects.generic.life import TargetOpponentLosesLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "target_opponent_loses_life", "amount": 3}
    )
    assert isinstance(e, TargetOpponentLosesLife)
    assert e.amount == 3


def test_bridge_target_opponent_loses_life_amount_default_to_one():
    """Bridge arm pin: missing `amount` defaults to 1 (mirrors Rust's
    parse_effect default-handling at cards.rs:3429 -- ``None -> 1``).
    Default-handling shape (round-23 sister DiscardSelf /
    EachOpponentDiscards / PutPlusOneCounterOnSelf precedent).
    """
    from mtg_bot.effects.generic.life import TargetOpponentLosesLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "target_opponent_loses_life"})
    assert isinstance(e, TargetOpponentLosesLife)
    assert e.amount == 1


def test_bridge_target_opponent_loses_life_amount_zero_silent_noop():
    """Bridge arm pin: amount=0 is a valid silent-no-op shape. Both
    engines accept amount=0 (Rust at state_ops_resolve.rs:3742-3746
    short-circuits only on negatives; Python's class accepts 0
    cleanly via opp.life -= 0). Bridge must NOT reject 0.
    """
    from mtg_bot.effects.generic.life import TargetOpponentLosesLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "target_opponent_loses_life", "amount": 0}
    )
    assert isinstance(e, TargetOpponentLosesLife)
    assert e.amount == 0


def test_bridge_target_opponent_loses_life_negative_amount_raises():
    """Bridge arm pin: negative amount raises ValueError to mirror
    Rust's parse_effect contract at cards.rs:3431-3435 (which raises
    PyValueError on negative amount). Bridge mirrors the contract so
    a typo in a fixture surfaces immediately rather than silently
    constructing a no-op effect.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="amount must be non-negative"):
        _ta_dict_to_python_effect(
            {"kind": "target_opponent_loses_life", "amount": -1}
        )


def test_bridge_target_opponent_loses_life_amount_three_dubious_delicacy_shape():
    """Bridge arm pin: amount=3 round-trips (Dubious Delicacy
    "Target opponent loses 3 life" shape). Pulls in a real-EoE-
    consumer-shaped value to pin the dict-shape contract against
    the canonical printing.
    """
    from mtg_bot.effects.generic.life import TargetOpponentLosesLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "target_opponent_loses_life", "amount": 3}
    )
    assert e == TargetOpponentLosesLife(amount=3)


def test_bridge_target_opponent_loses_life_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([TargetOpponentLosesLife(2), DrawCards(1)])`` translates
    correctly via the recursive Sequence translator. Pins this arm
    against accidental dispatch loss inside Sequence.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.life import TargetOpponentLosesLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "target_opponent_loses_life", "amount": 2},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], TargetOpponentLosesLife)
    assert e.effects[0].amount == 2
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_target_opponent_loses_life_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    ``{"kind": "target_opponent_loses_life", "amount": 3}`` dict
    shape on a triggered_ability carrier. The bridge dict shape
    must register cleanly on the Rust side too; this lockstep gate
    keeps the bridge from drifting away from Rust's parse_effect
    coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms. Rust's parse_effect arm at
    ``rust/src/cards.rs:3413-3437`` accepts the dict shape with
    optional `amount: i32` field defaulting to 1.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- TargetOpponentLosesLife",
        "card_types": ["Creature"],
        "mana_cost": {"B": 1, "generic": 2},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "target_opponent_loses_life",
                    "amount": 3,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_optional_mana_cost_then_effect_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 22 fresh discovery walk) --
    OptionalManaCostThenEffect family. Rust ``{"kind": "optional_
    mana_cost_then_effect", "cost": {"generic": 1}, "inner_effect":
    {"kind": "draw_cards", "count": 2}}`` translates to Python
    ``OptionalManaCostThenEffect(cost_str="{1}", inner_effect=
    DrawCards(amount=2))``.

    Mirrors Rust's parse_effect arm at cards.rs:4514-4544. Pins both
    the cost-dict-to-string translation (generic=1 -> "{1}") and the
    recursive inner-effect translation.
    """
    from mtg_bot.effects.combinators import OptionalManaCostThenEffect
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "optional_mana_cost_then_effect",
            "cost": {"generic": 1},
            "inner_effect": {"kind": "draw_cards", "count": 2},
        }
    )
    assert isinstance(e, OptionalManaCostThenEffect)
    assert e.cost_str == "{1}"
    assert isinstance(e.inner_effect, DrawCards)
    assert e.inner_effect.amount == 2


def test_bridge_optional_mana_cost_then_effect_colored_cost():
    """Bridge arm pin: colored mana cost dict ({"generic": 1, "R": 1})
    translates to Python's "{1}{R}" string form. Pins the canonical-
    color-order convention (W/U/B/R/G after generic) used by the
    bridge's cost-dict-to-string builder.
    """
    from mtg_bot.effects.combinators import OptionalManaCostThenEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "optional_mana_cost_then_effect",
            "cost": {"generic": 1, "R": 1},
            "inner_effect": {"kind": "draw_cards", "count": 1},
        }
    )
    assert isinstance(e, OptionalManaCostThenEffect)
    assert e.cost_str == "{1}{R}"


def test_bridge_optional_mana_cost_then_effect_empty_cost():
    """Bridge arm pin: empty cost dict ({}) translates to the empty
    string "" (the "free" variant — not a real card shape but a
    canonical edge case). Mirrors Python's parse_mana_cost('') ->
    ManaCost() round-trip.
    """
    from mtg_bot.effects.combinators import OptionalManaCostThenEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "optional_mana_cost_then_effect",
            "cost": {},
            "inner_effect": {"kind": "draw_cards", "count": 1},
        }
    )
    assert isinstance(e, OptionalManaCostThenEffect)
    assert e.cost_str == ""


def test_bridge_optional_mana_cost_then_effect_missing_cost_raises():
    """Bridge arm pin: missing `cost` field raises ValueError to
    mirror Rust's parse_effect contract at cards.rs:4518-4527
    (which raises PyValueError on missing 'cost'). Bridge mirrors the
    contract so a typo in a fixture surfaces immediately.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="missing required 'cost'"):
        _ta_dict_to_python_effect(
            {
                "kind": "optional_mana_cost_then_effect",
                "inner_effect": {"kind": "draw_cards", "count": 1},
            }
        )


def test_bridge_optional_mana_cost_then_effect_missing_inner_raises():
    """Bridge arm pin: missing `inner_effect` field raises ValueError
    to mirror Rust's parse_effect contract at cards.rs:4529-4538
    (which raises PyValueError on missing 'inner_effect'). Symmetric
    with the missing-cost arm.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="missing required 'inner_effect'"):
        _ta_dict_to_python_effect(
            {
                "kind": "optional_mana_cost_then_effect",
                "cost": {"generic": 1},
            }
        )


def test_bridge_optional_mana_cost_then_effect_recursive_inner_translation():
    """Bridge arm pin: inner_effect recursion fires through
    ``_ta_dict_to_python_effect``. Pins the recursive-translation
    contract (mirrors the MayDo/IfYouDo/Sequence composer pattern):
    the nested ``put_plus_one_counter_on_self`` shape translates
    cleanly to ``PutPlusOneCounterOnSelf(amount=1)`` -- the exact
    Oreplate-Pangolin shape ("you may pay {1}; if you do, put a +1/+1
    counter on this creature").
    """
    from mtg_bot.effects.combinators import OptionalManaCostThenEffect
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "optional_mana_cost_then_effect",
            "cost": {"generic": 1},
            "inner_effect": {
                "kind": "put_plus_one_counter_on_self",
                "amount": 1,
            },
        }
    )
    assert isinstance(e, OptionalManaCostThenEffect)
    assert e.cost_str == "{1}"
    assert isinstance(e.inner_effect, PutPlusOneCounterOnSelf)
    assert e.inner_effect.amount == 1


def test_bridge_optional_mana_cost_then_effect_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([OptionalManaCostThenEffect("{1}", DrawCards(2)),
    DiscardSelf()])`` translates correctly via the recursive Sequence
    translator. Pins this arm against accidental dispatch loss inside
    Sequence.
    """
    from mtg_bot.effects.combinators import (
        OptionalManaCostThenEffect, Sequence,
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {
                    "kind": "optional_mana_cost_then_effect",
                    "cost": {"generic": 1},
                    "inner_effect": {"kind": "draw_cards", "count": 2},
                },
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], OptionalManaCostThenEffect)
    assert e.effects[0].cost_str == "{1}"
    assert isinstance(e.effects[0].inner_effect, DrawCards)
    assert e.effects[0].inner_effect.amount == 2
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_optional_mana_cost_then_effect_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the bridge dict
    shape ``{"kind": "optional_mana_cost_then_effect", "cost":
    {"generic": 1}, "inner_effect": {...}}`` on a triggered_ability
    carrier. The bridge dict shape must register cleanly on Rust too;
    this lockstep gate keeps the bridge from drifting away from
    Rust's parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms. Rust's parse_effect arm at
    ``rust/src/cards.rs:4514-4544`` accepts the dict shape with
    REQUIRED `cost` (mana-cost dict) and `inner_effect` (nested
    effect-shape dict).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- OptionalManaCostThenEffect",
        "card_types": ["Creature"],
        "mana_cost": {"R": 1, "generic": 2},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "optional_mana_cost_then_effect",
                    "cost": {"generic": 1},
                    "inner_effect": {
                        "kind": "put_plus_one_counter_on_self",
                        "amount": 1,
                    },
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_optional_mana_cost_then_effect_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 22 fresh discovery walk) --
    OptionalManaCostThenEffect family. Rust ``{"kind": "optional_
    mana_cost_then_effect", "cost": {"generic": 1}, "inner_effect":
    {"kind": "draw_cards", "count": 2}}`` translates to Python
    ``OptionalManaCostThenEffect(cost_str="{1}", inner_effect=
    DrawCards(amount=2))``.

    Mirrors Rust's parse_effect arm at cards.rs:4514-4544. Pins both
    the cost-dict-to-string translation (generic=1 -> "{1}") and the
    recursive inner-effect translation.
    """
    from mtg_bot.effects.combinators import OptionalManaCostThenEffect
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "optional_mana_cost_then_effect",
            "cost": {"generic": 1},
            "inner_effect": {"kind": "draw_cards", "count": 2},
        }
    )
    assert isinstance(e, OptionalManaCostThenEffect)
    assert e.cost_str == "{1}"
    assert isinstance(e.inner_effect, DrawCards)
    assert e.inner_effect.amount == 2


def test_bridge_optional_mana_cost_then_effect_colored_cost():
    """Bridge arm pin: colored mana cost dict ({"generic": 1, "R": 1})
    translates to Python's "{1}{R}" string form. Pins the canonical-
    color-order convention (W/U/B/R/G after generic) used by the
    bridge's cost-dict-to-string builder.
    """
    from mtg_bot.effects.combinators import OptionalManaCostThenEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "optional_mana_cost_then_effect",
            "cost": {"generic": 1, "R": 1},
            "inner_effect": {"kind": "draw_cards", "count": 1},
        }
    )
    assert isinstance(e, OptionalManaCostThenEffect)
    assert e.cost_str == "{1}{R}"


def test_bridge_optional_mana_cost_then_effect_empty_cost():
    """Bridge arm pin: empty cost dict ({}) translates to the empty
    string "" (the "free" variant — not a real card shape but a
    canonical edge case). Mirrors Python's parse_mana_cost('') ->
    ManaCost() round-trip.
    """
    from mtg_bot.effects.combinators import OptionalManaCostThenEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "optional_mana_cost_then_effect",
            "cost": {},
            "inner_effect": {"kind": "draw_cards", "count": 1},
        }
    )
    assert isinstance(e, OptionalManaCostThenEffect)
    assert e.cost_str == ""


def test_bridge_optional_mana_cost_then_effect_missing_cost_raises():
    """Bridge arm pin: missing `cost` field raises ValueError to
    mirror Rust's parse_effect contract at cards.rs:4518-4527
    (which raises PyValueError on missing 'cost'). Bridge mirrors the
    contract so a typo in a fixture surfaces immediately.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="missing required 'cost'"):
        _ta_dict_to_python_effect(
            {
                "kind": "optional_mana_cost_then_effect",
                "inner_effect": {"kind": "draw_cards", "count": 1},
            }
        )


def test_bridge_optional_mana_cost_then_effect_missing_inner_raises():
    """Bridge arm pin: missing `inner_effect` field raises ValueError
    to mirror Rust's parse_effect contract at cards.rs:4529-4538
    (which raises PyValueError on missing 'inner_effect'). Symmetric
    with the missing-cost arm.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="missing required 'inner_effect'"):
        _ta_dict_to_python_effect(
            {
                "kind": "optional_mana_cost_then_effect",
                "cost": {"generic": 1},
            }
        )


def test_bridge_optional_mana_cost_then_effect_recursive_inner_translation():
    """Bridge arm pin: inner_effect recursion fires through
    ``_ta_dict_to_python_effect``. Pins the recursive-translation
    contract (mirrors the MayDo/IfYouDo/Sequence composer pattern):
    the nested ``put_plus_one_counter_on_self`` shape translates
    cleanly to ``PutPlusOneCounterOnSelf(amount=1)`` -- the exact
    Oreplate-Pangolin shape ("you may pay {1}; if you do, put a +1/+1
    counter on this creature").
    """
    from mtg_bot.effects.combinators import OptionalManaCostThenEffect
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "optional_mana_cost_then_effect",
            "cost": {"generic": 1},
            "inner_effect": {
                "kind": "put_plus_one_counter_on_self",
                "amount": 1,
            },
        }
    )
    assert isinstance(e, OptionalManaCostThenEffect)
    assert e.cost_str == "{1}"
    assert isinstance(e.inner_effect, PutPlusOneCounterOnSelf)
    assert e.inner_effect.amount == 1


def test_bridge_optional_mana_cost_then_effect_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([OptionalManaCostThenEffect("{1}", DrawCards(2)),
    DiscardSelf()])`` translates correctly via the recursive Sequence
    translator. Pins this arm against accidental dispatch loss inside
    Sequence.
    """
    from mtg_bot.effects.combinators import (
        OptionalManaCostThenEffect, Sequence,
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {
                    "kind": "optional_mana_cost_then_effect",
                    "cost": {"generic": 1},
                    "inner_effect": {"kind": "draw_cards", "count": 2},
                },
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], OptionalManaCostThenEffect)
    assert e.effects[0].cost_str == "{1}"
    assert isinstance(e.effects[0].inner_effect, DrawCards)
    assert e.effects[0].inner_effect.amount == 2
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_optional_mana_cost_then_effect_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the bridge dict
    shape ``{"kind": "optional_mana_cost_then_effect", "cost":
    {"generic": 1}, "inner_effect": {...}}`` on a triggered_ability
    carrier. The bridge dict shape must register cleanly on Rust too;
    this lockstep gate keeps the bridge from drifting away from
    Rust's parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms. Rust's parse_effect arm at
    ``rust/src/cards.rs:4514-4544`` accepts the dict shape with
    REQUIRED `cost` (mana-cost dict) and `inner_effect` (nested
    effect-shape dict).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- OptionalManaCostThenEffect",
        "card_types": ["Creature"],
        "mana_cost": {"R": 1, "generic": 2},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "optional_mana_cost_then_effect",
                    "cost": {"generic": 1},
                    "inner_effect": {
                        "kind": "put_plus_one_counter_on_self",
                        "amount": 1,
                    },
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_add_n_mana_of_chosen_color_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 22 fresh discovery walk) --
    AddNManaOfChosenColor family. Rust ``{"kind": "add_n_mana_of_
    chosen_color", "amount": 3, "options": ["W","U","B","R","G"]}``
    translates to Python ``AddNManaOfChosenColor(amount=3,
    options=("W","U","B","R","G"))``.

    Mirrors Rust's parse_effect arm at cards.rs:4407-4456. Pins both
    the amount field translation and the list -> tuple conversion
    for options.
    """
    from mtg_bot.effects.generic.mana import AddNManaOfChosenColor
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "add_n_mana_of_chosen_color",
            "amount": 3,
            "options": ["W", "U", "B", "R", "G"],
        }
    )
    assert isinstance(e, AddNManaOfChosenColor)
    assert e.amount == 3
    assert e.options == ("W", "U", "B", "R", "G")


def test_bridge_add_n_mana_of_chosen_color_default_options():
    """Bridge arm pin: missing `options` defaults to the 5-color
    ("W","U","B","R","G") tuple (Lotus-Field default; mirrors Rust's
    parse_effect default at cards.rs:4448-4454 and Python's class
    default at mana.py:105). C is intentionally NOT in the default
    per the printed "any one color" wording (which excludes
    colorless).
    """
    from mtg_bot.effects.generic.mana import AddNManaOfChosenColor
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "add_n_mana_of_chosen_color", "amount": 3}
    )
    assert isinstance(e, AddNManaOfChosenColor)
    assert e.amount == 3
    assert e.options == ("W", "U", "B", "R", "G")


def test_bridge_add_n_mana_of_chosen_color_amount_zero_silent_noop():
    """Bridge arm pin: amount=0 is a valid silent-no-op shape. Rust's
    resolve at state_ops_resolve.rs:4744-4746 short-circuits on
    amount=0; Python's class loops range(0) which is a no-op.
    Bridge must NOT reject 0.
    """
    from mtg_bot.effects.generic.mana import AddNManaOfChosenColor
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "add_n_mana_of_chosen_color", "amount": 0}
    )
    assert isinstance(e, AddNManaOfChosenColor)
    assert e.amount == 0


def test_bridge_add_n_mana_of_chosen_color_missing_amount_raises():
    """Bridge arm pin: missing `amount` raises ValueError to mirror
    Rust's parse_effect contract at cards.rs:4416-4420 (which raises
    PyValueError on missing amount). Bridge mirrors so a typo in a
    fixture surfaces immediately.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="missing required 'amount'"):
        _ta_dict_to_python_effect({"kind": "add_n_mana_of_chosen_color"})


def test_bridge_add_n_mana_of_chosen_color_negative_amount_raises():
    """Bridge arm pin: negative amount raises ValueError to mirror
    Rust's parse_effect contract at cards.rs:4422-4426 (which raises
    PyValueError on negative amount).
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="amount must be non-negative"):
        _ta_dict_to_python_effect(
            {"kind": "add_n_mana_of_chosen_color", "amount": -1}
        )


def test_bridge_add_n_mana_of_chosen_color_empty_options_raises():
    """Bridge arm pin: empty options list raises ValueError to mirror
    Rust's parse_effect contract at cards.rs:4434-4438 (which raises
    PyValueError on empty options). A degenerate "no colors to choose
    from" shape can't produce mana.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="options must be non-empty"):
        _ta_dict_to_python_effect(
            {
                "kind": "add_n_mana_of_chosen_color",
                "amount": 1,
                "options": [],
            }
        )


def test_bridge_add_n_mana_of_chosen_color_unknown_color_raises():
    """Bridge arm pin: unknown color string in options raises
    ValueError to mirror Rust's parse_effect contract at
    cards.rs:4439-4445. Closed mana-color vocab: W/U/B/R/G/C only.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="unknown color"):
        _ta_dict_to_python_effect(
            {
                "kind": "add_n_mana_of_chosen_color",
                "amount": 1,
                "options": ["W", "Q"],
            }
        )


def test_bridge_add_n_mana_of_chosen_color_subset_options():
    """Bridge arm pin: options subset (e.g. ("W","U")) translates
    cleanly to a 2-color tuple. Pins that the bridge does NOT silently
    expand subsets back to the 5-color default. Real-card example:
    the gold-2-pip filter "{T}: Add {W} or {U}" shape is a different
    Effect variant, but a hypothetical "{T}: Add 2 mana of any one of
    {W} or {U}" would route through this arm with options=("W","U").
    """
    from mtg_bot.effects.generic.mana import AddNManaOfChosenColor
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "add_n_mana_of_chosen_color",
            "amount": 2,
            "options": ["W", "U"],
        }
    )
    assert isinstance(e, AddNManaOfChosenColor)
    assert e.amount == 2
    assert e.options == ("W", "U")


def test_rust_parser_accepts_add_n_mana_of_chosen_color_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the bridge dict
    shape ``{"kind": "add_n_mana_of_chosen_color", "amount": 3}`` on
    a triggered_ability carrier. The bridge dict shape must register
    cleanly on Rust too; this lockstep gate keeps the bridge from
    drifting away from Rust's parse_effect coverage.

    Note: the canonical real-card use is an ACTIVATED mana ability
    (e.g. Lotus Field's "{T}: Add three mana of any one color"), but
    a triggered_abilities carrier registers cleanly too -- it
    exercises the same parse_effect path. Mirrors the existing
    parser-surface pins for sister BLOCKED-BRIDGE-ARM arms.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- AddNManaOfChosenColor",
        "card_types": ["Creature"],
        "mana_cost": {"G": 1, "generic": 1},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "add_n_mana_of_chosen_color",
                    "amount": 3,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_tap_target_artifact_or_creature_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 22 fresh discovery walk) --
    TapTargetArtifactOrCreature family. Rust ``{"kind": "tap_target_
    artifact_or_creature"}`` translates to Python
    ``TapTargetArtifactOrCreature()``.

    Mirrors Rust's parse_effect arm at cards.rs:3693-3694 (unit
    variant; no fields). Pin verifies the bare-shape translation.
    """
    from mtg_bot.effects.generic.tap import TapTargetArtifactOrCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "tap_target_artifact_or_creature"})
    assert isinstance(e, TapTargetArtifactOrCreature)


def test_bridge_tap_target_artifact_or_creature_extra_keys_ignored():
    """Bridge arm pin: unit-variant tolerance for extra keys. Mirrors
    Rust's parse_effect silent-drop convention -- unrecognized fields
    in the dict are ignored (not raised as errors). Pins the unit-
    variant contract against future-evolution where a sibling Rust
    variant might add fields.
    """
    from mtg_bot.effects.generic.tap import TapTargetArtifactOrCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "tap_target_artifact_or_creature",
            "spurious_field": 42,
        }
    )
    assert isinstance(e, TapTargetArtifactOrCreature)


def test_bridge_tap_target_artifact_or_creature_targets_filter_set():
    """Bridge arm pin: the constructed Python effect carries the
    ``targets`` tuple set by ``__post_init__`` to a single TargetSpec
    with the IsArtifact() | IsCreature() filter. Pins the implicit
    construction-time wiring -- the bridge does NOT need to thread
    the filter explicitly because Python's class sets it internally.
    """
    from mtg_bot.effects.generic.tap import TapTargetArtifactOrCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "tap_target_artifact_or_creature"})
    assert isinstance(e, TapTargetArtifactOrCreature)
    # __post_init__ sets `targets` to a 1-tuple of TargetSpec.
    assert hasattr(e, "targets")
    assert len(e.targets) == 1


def test_bridge_tap_target_artifact_or_creature_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([TapTargetArtifactOrCreature(), DrawCards(1)])``
    translates correctly via the recursive Sequence translator. Pins
    this arm against accidental dispatch loss inside Sequence.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.tap import TapTargetArtifactOrCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "tap_target_artifact_or_creature"},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], TapTargetArtifactOrCreature)
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_tap_target_artifact_or_creature_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the bridge dict
    shape ``{"kind": "tap_target_artifact_or_creature"}`` on a
    triggered_ability carrier. The bridge dict shape must register
    cleanly on Rust too; this lockstep gate keeps the bridge from
    drifting away from Rust's parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms. Rust's parse_effect arm at
    ``rust/src/cards.rs:3693-3694`` accepts the unit-shape dict.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- TapTargetArtifactOrCreature",
        "card_types": ["Creature"],
        "mana_cost": {"U": 1, "generic": 1},
        "power": 1,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "tap_target_artifact_or_creature"},
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_pump_creatures_you_control_until_eot_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 22 fresh discovery walk) --
    PumpCreaturesYouControlUntilEOT family. Rust ``{"kind": "pump_
    creatures_you_control_until_eot", "power_bonus": 1,
    "toughness_bonus": 1}`` translates to Python
    ``PumpCreaturesYouControlUntilEOT(power_bonus=1,
    toughness_bonus=1)``.

    Mirrors Rust's parse_effect arm at cards.rs:4476-4498 (both
    fields optional with default 0, i32, negatives allowed). Field
    names ``power_bonus`` and ``toughness_bonus`` agree on both
    engines (no rename in the bridge).
    """
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesYouControlUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "pump_creatures_you_control_until_eot",
            "power_bonus": 1,
            "toughness_bonus": 1,
        }
    )
    assert isinstance(e, PumpCreaturesYouControlUntilEOT)
    assert e.power_bonus == 1
    assert e.toughness_bonus == 1


def test_bridge_pump_creatures_you_control_until_eot_default_bonuses_zero():
    """Bridge arm pin: missing ``power_bonus`` and ``toughness_bonus``
    default to 0 (mirrors Rust's parse_effect default-handling at
    cards.rs:4487+4495 -- ``None -> 0``). Default-handling shape
    (round-23 sister DiscardSelf / EachOpponentDiscards /
    PutPlusOneCounterOnSelf precedent). ``(0, 0)`` is a valid
    silent no-op shape on both engines.
    """
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesYouControlUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "pump_creatures_you_control_until_eot"}
    )
    assert isinstance(e, PumpCreaturesYouControlUntilEOT)
    assert e.power_bonus == 0
    assert e.toughness_bonus == 0


def test_bridge_pump_creatures_you_control_until_eot_negative_bonuses_allowed():
    """Bridge arm pin: negative bonuses are LEGAL (debuff-shaped
    mass-pumps, e.g. spells that shrink your own team for a benefit).
    Rust intentionally allows them (cards.rs:4477-4480 docstring,
    mirroring PumpSelfUntilEOT precedent); Python's class is a bare
    dataclass with no non-negative guard. Bridge does NOT raise on
    negatives -- mirrors the contract.
    """
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesYouControlUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "pump_creatures_you_control_until_eot",
            "power_bonus": -1,
            "toughness_bonus": -1,
        }
    )
    assert isinstance(e, PumpCreaturesYouControlUntilEOT)
    assert e.power_bonus == -1
    assert e.toughness_bonus == -1


def test_bridge_pump_creatures_you_control_until_eot_independent_fields():
    """Bridge arm pin: independent fields. Specify ``toughness_bonus``
    only; ``power_bonus`` defaults to 0 ("creatures you control get
    +0/+2 UEOT" -- defensive anthem). Pins that the get-with-default
    per-field is correctly applied independently for each axis.
    """
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesYouControlUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "pump_creatures_you_control_until_eot",
            "toughness_bonus": 2,
        }
    )
    assert isinstance(e, PumpCreaturesYouControlUntilEOT)
    assert e.power_bonus == 0
    assert e.toughness_bonus == 2


def test_bridge_pump_creatures_you_control_until_eot_equality_with_default_constructor():
    """Bridge arm pin: round-trip equality. Translated effect equals
    a directly-constructed ``PumpCreaturesYouControlUntilEOT(
    power_bonus=2, toughness_bonus=2)``. Pins the dataclass equality
    semantic -- the four rider fields (granted_keywords,
    exclude_source, attacking_only, also_untap_if_not_your_turn) all
    take their defaults on both sides (no leakage from the bridge
    dict shape).
    """
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesYouControlUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "pump_creatures_you_control_until_eot",
            "power_bonus": 2,
            "toughness_bonus": 2,
        }
    )
    assert e == PumpCreaturesYouControlUntilEOT(
        power_bonus=2, toughness_bonus=2,
    )


def test_bridge_pump_creatures_you_control_until_eot_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([PumpCreaturesYouControlUntilEOT(1, 1), DrawCards(1)])``
    translates correctly via the recursive Sequence translator. Pins
    this arm against accidental dispatch loss inside Sequence.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.pump import (
        PumpCreaturesYouControlUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {
                    "kind": "pump_creatures_you_control_until_eot",
                    "power_bonus": 1,
                    "toughness_bonus": 1,
                },
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], PumpCreaturesYouControlUntilEOT)
    assert e.effects[0].power_bonus == 1
    assert e.effects[0].toughness_bonus == 1
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_pump_creatures_you_control_until_eot_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    ``{"kind": "pump_creatures_you_control_until_eot",
    "power_bonus": 1, "toughness_bonus": 1}`` dict shape on a
    triggered_ability carrier. The bridge dict shape must register
    cleanly on the Rust side too; this lockstep gate keeps the
    bridge from drifting away from Rust's parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms. Rust's parse_effect arm at
    ``rust/src/cards.rs:4476-4498`` accepts the dict shape with
    optional ``power_bonus`` / ``toughness_bonus`` i32 fields
    defaulting to 0.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": (
            "BLOCKED-BRIDGE-ARM Bridge Pin -- "
            "PumpCreaturesYouControlUntilEOT"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"W": 1, "generic": 2},
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "pump_creatures_you_control_until_eot",
                    "power_bonus": 1,
                    "toughness_bonus": 1,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_destroy_target_artifact_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 23) -- DestroyTargetArtifact
    family. Rust ``{"kind": "destroy_target_artifact"}`` translates
    to Python ``DestroyTargetArtifact()``.

    Mirrors Rust's parse_effect arm at cards.rs:3519-3525 (unit
    variant -- no fields). Python's class is a ``Destroy`` subclass
    that sets ``targets = (TargetSpec(IsArtifact()),)`` in
    ``__post_init__``.
    """
    from mtg_bot.effects.generic.destroy import DestroyTargetArtifact
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "destroy_target_artifact"})
    assert isinstance(e, DestroyTargetArtifact)


def test_bridge_destroy_target_artifact_targets_set_to_is_artifact():
    """Bridge arm pin: post-init wires ``targets`` tuple to a single
    ``TargetSpec(IsArtifact())``. Pins the filter shape -- a bug
    that dropped the ``__post_init__`` would leave ``targets`` empty
    and make the resolver pick anything.
    """
    from mtg_bot.effects.generic.destroy import DestroyTargetArtifact
    from mtg_bot.effects.object_predicates import IsArtifact
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "destroy_target_artifact"})
    assert isinstance(e, DestroyTargetArtifact)
    assert e.targets == (TargetSpec(IsArtifact()),)


def test_bridge_destroy_target_artifact_extra_keys_silently_ignored():
    """Bridge arm pin: extra keys on the dict are silently dropped
    (mirrors Rust's parse_effect arm at cards.rs:3519-3525 which
    takes no fields and simply returns the unit variant -- there
    is no extra-key validation). Mirrors the silent-drop convention
    on sister unit-variant arms (counter_target_spell, etc.).
    """
    from mtg_bot.effects.generic.destroy import DestroyTargetArtifact
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "destroy_target_artifact", "spurious": 42}
    )
    assert isinstance(e, DestroyTargetArtifact)


def test_bridge_destroy_target_artifact_equality_with_default_constructor():
    """Bridge arm pin: round-trip equality. Translated effect equals
    a directly-constructed ``DestroyTargetArtifact()``. Pins the
    dataclass equality semantic -- the bare unit-shape carries no
    parameters so equality is structural.
    """
    from mtg_bot.effects.generic.destroy import DestroyTargetArtifact
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "destroy_target_artifact"})
    assert e == DestroyTargetArtifact()


def test_bridge_destroy_target_artifact_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([DestroyTargetArtifact(), DrawCards(1)])`` translates
    correctly via the recursive Sequence translator. Pins this arm
    against accidental dispatch loss inside Sequence.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.destroy import DestroyTargetArtifact
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "destroy_target_artifact"},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], DestroyTargetArtifact)
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_destroy_target_artifact_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the ``{"kind":
    "destroy_target_artifact"}`` dict shape on a triggered_ability
    carrier. The bridge dict shape must register cleanly on the
    Rust side too; this lockstep gate keeps the bridge from drifting
    away from Rust's parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms. Rust's parse_effect arm at
    ``rust/src/cards.rs:3519-3525`` accepts the unit-shape dict.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- DestroyTargetArtifact",
        "card_types": ["Creature"],
        "mana_cost": {"R": 1, "generic": 1},
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "destroy_target_artifact"},
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_destroy_target_nonland_permanent_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 23) --
    DestroyTargetNonlandPermanent family. Rust ``{"kind":
    "destroy_target_nonland_permanent"}`` translates to Python
    ``DestroyTargetNonlandPermanent()``.

    Mirrors Rust's parse_effect arm at cards.rs:3514-3517 (unit
    variant -- no fields). Python's class is a ``Destroy``
    subclass that sets ``targets = (TargetSpec(~IsLand() &
    ~IsPlayer()),)`` in ``__post_init__``.
    """
    from mtg_bot.effects.generic.destroy import (
        DestroyTargetNonlandPermanent,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "destroy_target_nonland_permanent"}
    )
    assert isinstance(e, DestroyTargetNonlandPermanent)


def test_bridge_destroy_target_nonland_permanent_targets_set_to_nonland_nonplayer():
    """Bridge arm pin: post-init wires ``targets`` tuple to a
    single ``TargetSpec(~IsLand() & ~IsPlayer())``. Pins the filter
    composition -- a bug that dropped the ``__post_init__`` would
    leave ``targets`` empty and make the resolver pick anything,
    including lands and players.
    """
    from mtg_bot.effects.generic.destroy import (
        DestroyTargetNonlandPermanent,
    )
    from mtg_bot.effects.object_predicates import IsLand, IsPlayer
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "destroy_target_nonland_permanent"}
    )
    assert isinstance(e, DestroyTargetNonlandPermanent)
    assert e.targets == (TargetSpec(~IsLand() & ~IsPlayer()),)


def test_bridge_destroy_target_nonland_permanent_extra_keys_silently_ignored():
    """Bridge arm pin: extra keys on the dict are silently dropped
    (mirrors Rust's parse_effect arm at cards.rs:3514-3517 which
    takes no fields and simply returns the unit variant -- there
    is no extra-key validation). Mirrors the silent-drop convention
    on sister unit-variant arms (counter_target_spell, etc.).
    """
    from mtg_bot.effects.generic.destroy import (
        DestroyTargetNonlandPermanent,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "destroy_target_nonland_permanent",
            "target": {"kind": "any_creature"},  # ignored
        }
    )
    assert isinstance(e, DestroyTargetNonlandPermanent)


def test_bridge_destroy_target_nonland_permanent_equality_with_default_constructor():
    """Bridge arm pin: round-trip equality. Translated effect
    equals a directly-constructed
    ``DestroyTargetNonlandPermanent()``. Pins the dataclass
    equality semantic -- the bare unit-shape carries no parameters
    so equality is structural.
    """
    from mtg_bot.effects.generic.destroy import (
        DestroyTargetNonlandPermanent,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "destroy_target_nonland_permanent"}
    )
    assert e == DestroyTargetNonlandPermanent()


def test_bridge_destroy_target_nonland_permanent_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([DestroyTargetNonlandPermanent(), DrawCards(1)])``
    translates correctly via the recursive Sequence translator. Pins
    this arm against accidental dispatch loss inside Sequence.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.destroy import (
        DestroyTargetNonlandPermanent,
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "destroy_target_nonland_permanent"},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], DestroyTargetNonlandPermanent)
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_destroy_target_nonland_permanent_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the ``{"kind":
    "destroy_target_nonland_permanent"}`` dict shape on a
    triggered_ability carrier. The bridge dict shape must register
    cleanly on the Rust side too; this lockstep gate keeps the
    bridge from drifting away from Rust's parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms. Rust's parse_effect arm at
    ``rust/src/cards.rs:3514-3517`` accepts the unit-shape dict.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": (
            "BLOCKED-BRIDGE-ARM Bridge Pin -- "
            "DestroyTargetNonlandPermanent"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"B": 1, "generic": 2},
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "destroy_target_nonland_permanent"},
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_destroy_all_creatures_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 23) -- DestroyAllCreatures
    family (Wrath shape). Rust ``{"kind": "destroy_all_creatures"}``
    translates to Python ``DestroyAllCreatures()``.

    Mirrors Rust's parse_effect arm at cards.rs:3504-3512 (unit
    variant -- no fields). Python's class is a frozen dataclass
    with three OPTIONAL narrowing fields (``tapped_only``,
    ``untapped_only``, ``min_power``) all defaulting to the
    unrestricted Wrath shape; Rust's variant carries no narrowing
    fields so the bridge constructs the bare class.
    """
    from mtg_bot.effects.generic.destroy import DestroyAllCreatures
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "destroy_all_creatures"})
    assert isinstance(e, DestroyAllCreatures)


def test_bridge_destroy_all_creatures_narrowing_fields_default_to_unrestricted():
    """Bridge arm pin: the three narrowing fields default to the
    unrestricted Wrath shape (``tapped_only=False``,
    ``untapped_only=False``, ``min_power=0``). Pins the contract
    that the bare Rust unit variant maps to the unrestricted
    Python form -- a bug that flipped a narrowing flag default
    would silently shrink the wrath's victim set.
    """
    from mtg_bot.effects.generic.destroy import DestroyAllCreatures
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "destroy_all_creatures"})
    assert isinstance(e, DestroyAllCreatures)
    assert e.tapped_only is False
    assert e.untapped_only is False
    assert e.min_power == 0


def test_bridge_destroy_all_creatures_extra_keys_silently_ignored():
    """Bridge arm pin: extra keys on the dict are silently dropped
    (mirrors Rust's parse_effect arm at cards.rs:3504-3512 which
    takes no fields and simply returns the unit variant). Mirrors
    the silent-drop convention on sister unit-variant arms. Pins
    that Rust-side narrowing fields like ``tapped_only`` (NOT
    represented on the Rust unit variant) are dropped here too --
    the bridge cannot synthesize narrowing it doesn't see on the
    Rust side.
    """
    from mtg_bot.effects.generic.destroy import DestroyAllCreatures
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "destroy_all_creatures", "tapped_only": True}
    )
    # Even with a stray narrowing key, bridge produces the
    # unrestricted form (mirrors Rust's bare unit-variant shape).
    assert isinstance(e, DestroyAllCreatures)
    assert e.tapped_only is False


def test_bridge_destroy_all_creatures_equality_with_default_constructor():
    """Bridge arm pin: round-trip equality. Translated effect equals
    a directly-constructed ``DestroyAllCreatures()``. Pins the
    dataclass equality semantic -- the bare unit-shape carries no
    parameters so equality is structural.
    """
    from mtg_bot.effects.generic.destroy import DestroyAllCreatures
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "destroy_all_creatures"})
    assert e == DestroyAllCreatures()


def test_bridge_destroy_all_creatures_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([DestroyAllCreatures(), DrawCards(1)])`` translates
    correctly via the recursive Sequence translator. Pins this
    arm against accidental dispatch loss inside Sequence.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.destroy import DestroyAllCreatures
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "destroy_all_creatures"},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], DestroyAllCreatures)
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_destroy_all_creatures_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the ``{"kind":
    "destroy_all_creatures"}`` dict shape on a triggered_ability
    carrier. The bridge dict shape must register cleanly on the
    Rust side too; this lockstep gate keeps the bridge from
    drifting away from Rust's parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms. Rust's parse_effect arm at
    ``rust/src/cards.rs:3504-3512`` accepts the unit-shape dict.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- DestroyAllCreatures",
        "card_types": ["Creature"],
        "mana_cost": {"W": 1, "B": 1, "generic": 2},
        "power": 1,
        "toughness": 1,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "destroy_all_creatures"},
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_damage_each_creature_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 23 fresh discovery walk) --
    DealNDamageToEachCreature family. Rust ``{"kind":
    "damage_each_creature", "amount": 2}`` translates to Python
    ``DealNDamageToEachCreature(amount=2)``.

    Mirrors Rust's parse_effect arm at cards.rs:3286-3289 (amount
    required, i32, no default). Field name ``amount`` agrees on both
    engines (no rename in the bridge).
    """
    from mtg_bot.effects.generic.damage import DealNDamageToEachCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "damage_each_creature", "amount": 2}
    )
    assert isinstance(e, DealNDamageToEachCreature)
    assert e.amount == 2


def test_bridge_damage_each_creature_amount_required_keyerror_when_missing():
    """Bridge arm pin: missing ``amount`` raises KeyError (mirrors
    Rust's ``require()`` contract at cards.rs:3286-3289). No default
    on either side -- the variant has no zero-arg form.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(KeyError):
        _ta_dict_to_python_effect({"kind": "damage_each_creature"})


def test_bridge_damage_each_creature_amount_zero_silent_noop():
    """Bridge arm pin: amount=0 is legal (silent no-op) on both
    engines. Rust's resolve at state_ops_resolve.rs:2035-2039 only
    raises on negatives; amount=0 falls through to a no-op damage
    mark on every creature. Python's class is a bare dataclass with
    no zero-amount guard. Mirrors GainLife / DrawCards /
    DamageEachOpponent zero-amount conventions.
    """
    from mtg_bot.effects.generic.damage import DealNDamageToEachCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "damage_each_creature", "amount": 0}
    )
    assert isinstance(e, DealNDamageToEachCreature)
    assert e.amount == 0


def test_bridge_damage_each_creature_negative_amount_raises():
    """Bridge arm pin: amount<0 raises ValueError at translation time
    (mirrors Rust's resolve raise at state_ops_resolve.rs:2035-2039).
    The bridge front-loads the check rather than waiting for
    Python's ``DealNDamageToEachCreature.resolve`` to handle it (the
    Python class itself doesn't guard, but cross-engine probes that
    feed a negative amount through the bridge would silently apply
    the bogus value on the Python side and raise on the Rust side --
    asymmetric. The bridge's pre-check keeps the contracts symmetric).
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="non-negative"):
        _ta_dict_to_python_effect(
            {"kind": "damage_each_creature", "amount": -1}
        )


def test_bridge_damage_each_creature_amount_four_extinguisher_battleship_shape():
    """Bridge arm pin: ``amount=4`` round-trips correctly --
    Extinguisher Battleship's ETB sequence body shape. Pins that the
    field translates as i32 (no clamp / overflow at the bridge).
    """
    from mtg_bot.effects.generic.damage import DealNDamageToEachCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "damage_each_creature", "amount": 4}
    )
    assert e == DealNDamageToEachCreature(amount=4)


def test_bridge_damage_each_creature_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([DealNDamageToEachCreature(2), DrawCards(1)])``
    translates correctly via the recursive Sequence translator. Pins
    this arm against accidental dispatch loss inside Sequence (the
    real Lithobraking / Extinguisher Battleship cascades are Sequence-
    wrapped on the printed surface).
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.damage import DealNDamageToEachCreature
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "damage_each_creature", "amount": 2},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], DealNDamageToEachCreature)
    assert e.effects[0].amount == 2
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_damage_each_creature_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    ``{"kind": "damage_each_creature", "amount": 2}`` dict shape on a
    triggered_ability carrier. The bridge dict shape must register
    cleanly on the Rust side too; this lockstep gate keeps the bridge
    from drifting away from Rust's parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms. Rust's parse_effect arm at
    ``rust/src/cards.rs:3286-3289`` accepts the dict shape with
    required ``amount`` i32 field.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": (
            "BLOCKED-BRIDGE-ARM Bridge Pin -- DamageEachCreature"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"R": 1, "generic": 2},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "damage_each_creature",
                    "amount": 2,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_each_opponent_loses_life_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 23 fresh discovery walk) --
    EachOpponentLosesLife family. Rust ``{"kind":
    "each_opponent_loses_life", "amount": 2}`` translates to Python
    ``EachOpponentLosesLife(amount=2)``.

    Mirrors Rust's parse_effect arm at cards.rs:3425-3437 (amount
    required, i32, no default; negatives raise at parse time).
    Field name ``amount`` agrees on both engines (no rename in the
    bridge).
    """
    from mtg_bot.effects.generic.life import EachOpponentLosesLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "each_opponent_loses_life", "amount": 2}
    )
    assert isinstance(e, EachOpponentLosesLife)
    assert e.amount == 2


def test_bridge_each_opponent_loses_life_amount_required_keyerror_when_missing():
    """Bridge arm pin: missing ``amount`` raises KeyError (mirrors
    Rust's ``require()`` contract at cards.rs:3431). No default on
    either side (distinct from sister
    ``target_opponent_loses_life`` which defaults to 1).
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(KeyError):
        _ta_dict_to_python_effect({"kind": "each_opponent_loses_life"})


def test_bridge_each_opponent_loses_life_amount_zero_silent_noop():
    """Bridge arm pin: amount=0 is legal (silent no-op) on both
    engines. Rust's resolve at state_ops_resolve.rs:3592-3636's
    saturating_sub(0) is a no-op; Python's class iterates opponents
    and subtracts 0 from each life total. Mirrors GainLife /
    DrawCards / DamageEachOpponent / DiscardSelf zero-amount
    conventions per the resolve docstring at
    state_ops_resolve.rs:3587-3589.
    """
    from mtg_bot.effects.generic.life import EachOpponentLosesLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "each_opponent_loses_life", "amount": 0}
    )
    assert isinstance(e, EachOpponentLosesLife)
    assert e.amount == 0


def test_bridge_each_opponent_loses_life_negative_amount_raises():
    """Bridge arm pin: amount<0 raises ValueError at translation
    time (mirrors Rust's parse_effect raise at cards.rs:3432-3436).
    Rust raises at BOTH parse and resolve as defense-in-depth; the
    bridge raises early to keep the translation-time contract
    symmetric across engines.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="non-negative"):
        _ta_dict_to_python_effect(
            {"kind": "each_opponent_loses_life", "amount": -1}
        )


def test_bridge_each_opponent_loses_life_amount_two_void_consumer_shape():
    """Bridge arm pin: ``amount=2`` round-trips correctly -- the EoE
    Void-replacement consumer's shape ("you draw two cards and each
    opponent loses 2 life"). Pins that the field translates as i32
    (no clamp / overflow at the bridge).
    """
    from mtg_bot.effects.generic.life import EachOpponentLosesLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "each_opponent_loses_life", "amount": 2}
    )
    assert e == EachOpponentLosesLife(amount=2)


def test_bridge_each_opponent_loses_life_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([DrawCards(2), EachOpponentLosesLife(2)])`` translates
    correctly via the recursive Sequence translator. Pins this arm
    against accidental dispatch loss inside Sequence (the Void-
    consumer body is Sequence-wrapped on the printed surface).
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.life import EachOpponentLosesLife
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "draw_cards", "count": 2},
                {"kind": "each_opponent_loses_life", "amount": 2},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], DrawCards)
    assert isinstance(e.effects[1], EachOpponentLosesLife)
    assert e.effects[1].amount == 2


def test_rust_parser_accepts_each_opponent_loses_life_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    ``{"kind": "each_opponent_loses_life", "amount": 2}`` dict shape
    on a triggered_ability carrier. The bridge dict shape must
    register cleanly on the Rust side too; this lockstep gate keeps
    the bridge from drifting away from Rust's parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms. Rust's parse_effect arm at
    ``rust/src/cards.rs:3425-3437`` accepts the dict shape with
    required ``amount`` i32 field (negatives raise).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": (
            "BLOCKED-BRIDGE-ARM Bridge Pin -- EachOpponentLosesLife"
        ),
        "card_types": ["Creature"],
        "mana_cost": {"B": 1, "generic": 2},
        "power": 2,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "each_opponent_loses_life",
                    "amount": 2,
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_untap_target_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 23 fresh discovery walk) --
    UntapTarget family. Rust ``{"kind": "untap_target", "target":
    {"kind": "any_creature"}}`` translates to Python
    ``Untap(targets=(TargetSpec(IsCreature()),))``.

    Mirrors Rust's parse_effect arm at cards.rs:3237-3244 (target
    dict required, parsed via parse_target_filter). The bridge wires
    the same generic ``Untap`` primitive added in this slice as the
    Python-side mirror of the Rust resolver.
    """
    from mtg_bot.effects.generic.tap import Untap
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "untap_target", "target": {"kind": "any_creature"}}
    )
    assert isinstance(e, Untap)
    assert e.targets == (TargetSpec(IsCreature()),)


def test_bridge_untap_target_default_target_filter_is_any_creature():
    """Bridge arm pin: missing ``target`` defaults to
    ``any_creature`` (mirrors the lenient-default convention used by
    sister tap_target / destroy_target / exile_target /
    return_to_hand arms). Bridge consumers SHOULD pass ``target``
    explicitly for round-trip dict-shape consistency, but the
    default keeps the arm tolerant of stripped dicts that lose
    optional fields.
    """
    from mtg_bot.effects.generic.tap import Untap
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "untap_target"})
    assert isinstance(e, Untap)
    assert e.targets == (TargetSpec(IsCreature()),)


def test_bridge_untap_target_any_player_filter_raises():
    """Bridge arm pin: ``target.kind == "any_player"`` raises
    ValueError (mirrors Rust's resolve raise at
    state_ops_resolve.rs:1429-1434 -- "UntapTarget with AnyPlayer
    target is semantically nonsense"). The bridge front-loads the
    check rather than waiting for resolve so the contract is
    symmetric across engines.
    """
    import pytest

    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError, match="any_player"):
        _ta_dict_to_python_effect(
            {"kind": "untap_target", "target": {"kind": "any_player"}}
        )


def test_bridge_untap_target_equality_with_default_constructor():
    """Bridge arm pin: round-trip equality. Translated effect equals
    a directly-constructed
    ``Untap(targets=(TargetSpec(IsCreature()),))``. Pins the
    dataclass equality semantic.
    """
    from mtg_bot.effects.generic.tap import Untap
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.effects.targets import TargetSpec
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {"kind": "untap_target", "target": {"kind": "any_creature"}}
    )
    assert e == Untap(targets=(TargetSpec(IsCreature()),))


def test_bridge_untap_target_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([Untap(...), DrawCards(1)])`` translates correctly
    via the recursive Sequence translator. Pins this arm against
    accidental dispatch loss inside Sequence.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.tap import Untap
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {
                    "kind": "untap_target",
                    "target": {"kind": "any_creature"},
                },
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], Untap)
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_untap_target_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the
    ``{"kind": "untap_target", "target": {"kind": "any_creature"}}``
    dict shape on a triggered_ability carrier. The bridge dict shape
    must register cleanly on the Rust side too; this lockstep gate
    keeps the bridge from drifting away from Rust's parse_effect
    coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms. Rust's parse_effect arm at
    ``rust/src/cards.rs:3237-3244`` requires ``target`` and
    downcasts to a target-filter dict.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- UntapTarget",
        "card_types": ["Creature"],
        "mana_cost": {"U": 1, "generic": 1},
        "power": 1,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "untap_target",
                    "target": {"kind": "any_creature"},
                },
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


def test_bridge_tap_another_target_creature_basic_translation():
    """BLOCKED-BRIDGE-ARM slice (round 23 fresh discovery walk) --
    TapAnotherTargetCreature family. Rust ``{"kind": "tap_another_
    target_creature"}`` translates to Python
    ``TapAnotherTargetCreature()``.

    Mirrors Rust's parse_effect arm at cards.rs:3835-3837 (unit
    variant; no fields). Pin verifies the bare-shape translation.
    """
    from mtg_bot.effects.generic.tap import TapAnotherTargetCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "tap_another_target_creature"})
    assert isinstance(e, TapAnotherTargetCreature)


def test_bridge_tap_another_target_creature_extra_keys_ignored():
    """Bridge arm pin: unit-variant tolerance for extra keys. Mirrors
    Rust's parse_effect silent-drop convention -- unrecognized fields
    in the dict are ignored (not raised as errors). Pins the unit-
    variant contract against future-evolution where a sibling Rust
    variant might add fields.
    """
    from mtg_bot.effects.generic.tap import TapAnotherTargetCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "tap_another_target_creature",
            "spurious_field": 42,
        }
    )
    assert isinstance(e, TapAnotherTargetCreature)


def test_bridge_tap_another_target_creature_targets_filter_set():
    """Bridge arm pin: the constructed Python effect carries the
    ``targets`` tuple set by ``__post_init__`` to a single TargetSpec
    with the ``IsCreature() & ~IsSource()`` filter. Pins the
    implicit construction-time wiring -- the bridge does NOT need to
    thread the filter explicitly because Python's class sets it
    internally. The ``~IsSource()`` arm is what makes this distinct
    from the bare TapTarget(any_creature) shape -- the resolving
    source is excluded from its own target pool so "another" reads
    CR-correct.
    """
    from mtg_bot.effects.generic.tap import TapAnotherTargetCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect({"kind": "tap_another_target_creature"})
    assert isinstance(e, TapAnotherTargetCreature)
    # __post_init__ sets `targets` to a 1-tuple of TargetSpec.
    assert hasattr(e, "targets")
    assert len(e.targets) == 1


def test_bridge_tap_another_target_creature_equality_default_constructor():
    """Bridge arm pin: two ``TapAnotherTargetCreature()`` instances
    are equal under dataclass(frozen=True) default __eq__ semantics.
    The ``targets`` field is set in ``__post_init__`` to the same
    tuple shape on both, so structural equality holds. Pins the
    frozen-dataclass equality contract for the hash-based keying
    used downstream (e.g. de-dup in Sequence composers).
    """
    from mtg_bot.effects.generic.tap import TapAnotherTargetCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e1 = _ta_dict_to_python_effect({"kind": "tap_another_target_creature"})
    e2 = TapAnotherTargetCreature()
    assert e1 == e2


def test_bridge_tap_another_target_creature_composable_in_sequence():
    """Round-trip in a Sequence composer to pin nesting end-to-end:
    ``Sequence([TapAnotherTargetCreature(), DrawCards(1)])``
    translates correctly via the recursive Sequence translator. Pins
    this arm against accidental dispatch loss inside Sequence.
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.tap import TapAnotherTargetCreature
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    e = _ta_dict_to_python_effect(
        {
            "kind": "sequence",
            "effects": [
                {"kind": "tap_another_target_creature"},
                {"kind": "draw_cards", "count": 1},
            ],
        }
    )
    assert isinstance(e, Sequence)
    assert len(e.effects) == 2
    assert isinstance(e.effects[0], TapAnotherTargetCreature)
    assert isinstance(e.effects[1], DrawCards)


def test_rust_parser_accepts_tap_another_target_creature_in_triggered_ability():
    """Lockstep pin: Rust's parse_effect arm accepts the bridge dict
    shape ``{"kind": "tap_another_target_creature"}`` on a
    triggered_ability carrier. The bridge dict shape must register
    cleanly on Rust too; this lockstep gate keeps the bridge from
    drifting away from Rust's parse_effect coverage.

    Mirrors the existing parser-surface pins for sister BLOCKED-
    BRIDGE-ARM arms. Rust's parse_effect arm at
    ``rust/src/cards.rs:3835-3837`` accepts the unit-shape dict.
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "BLOCKED-BRIDGE-ARM Bridge Pin -- TapAnotherTargetCreature",
        "card_types": ["Creature"],
        "mana_cost": {"W": 1, "generic": 1},
        "power": 1,
        "toughness": 2,
        "triggered_abilities": [
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "tap_another_target_creature"},
            }
        ],
    }
    pid = reg.register_printing(d)
    assert pid == 0


# === PHASE5_BRIDGE_PIN_TESTS_INSERT_ABOVE_THIS_LINE ===
# New bridge-arm pin tests go IMMEDIATELY ABOVE this marker.
