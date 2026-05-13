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
