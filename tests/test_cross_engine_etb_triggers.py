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


# === PHASE5_BRIDGE_PIN_TESTS_INSERT_ABOVE_THIS_LINE ===
# New bridge-arm pin tests go IMMEDIATELY ABOVE this marker.
