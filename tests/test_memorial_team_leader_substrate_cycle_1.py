"""**Memorial Team Leader Cycle 1 substrate (2026-05-24).**

Tests for the new Phase-4 anthem-shape substrate:

* Extended ``StaticAnthem`` Rust struct carrying ``power_bonus`` /
  ``toughness_bonus`` / ``condition_tag`` / ``condition_args`` next to
  the existing Phase-1 scope + granted_keywords fields.
* New ``static_anthem_pt_bonus_for`` Rust reader-fold helper called
  from ``battlefield_creature_power`` / ``_toughness``.
* New ``"during_your_turn"`` condition tag dispatched by
  ``static_anthem_condition_matches``.
* Cross-engine bridge: ``_spec_card_to_printing_dict`` emits the
  6-tuple shape; ``_card_def_to_python_printing`` rehydrates the
  Python ``StaticAbility(condition=DuringYourTurn(),
  continuous_effect=ContinuousModifier(layer=7, payload=
  PowerToughnessBonus(...)))`` AND/OR layer-6 keyword grants.
* Sibling helper ``_static_anthem_condition_from_tag`` invertible to
  the Rust dispatch table.

This is a **substrate-only closure** — the cycle adds the
infrastructure for Memorial Team Leader's "During your turn, other
creatures you control get +1/+0." static ability + Warp {1}{R}.
Memorial Team Leader itself stays DECLINED at the loader admit gate
because BOTH the Phase-1 anthem-keyword predicate
(:func:`_static_ability_is_simple_anthem_keyword_grant` —
``power_bonus or toughness_bonus`` rejects) AND the pure-warp creature
predicate (:func:`_printing_is_bridge_pure_warp_creature` —
``static_abilities`` rejects) decline it. The substrate is wired
through the bridge round-trip + Rust reader fold so the Cycle-2
admit-set widen ships against an already-correct engine path.

**Cycle 2 deliverable shape** (per scout + this Cycle 1 verify-first
walk):

  * New admit predicate
    ``_printing_is_bridge_static_anthem_pt_conditional_warp_creature``
    that admits a creature whose every static_ability is the Phase-4
    layer-7-P/T-anthem shape under ``other_creatures_you_control``
    scope + ``DuringYourTurn`` condition AND which carries
    ``warp_cost`` (Memorial Team Leader's composition signature).
  * New trajectory.py arm in
    ``_printing_to_card_def`` that emits the 6-tuple bridge shape
    for the Phase-4 carriers (sibling to today's Phase-3
    ``static_self_bonuses`` arm).
  * New 11th disjunct in ``_filter_deck_to_bridge_supported``.
  * Admit-set pin bump in
    ``tests/test_cross_engine_etb_triggers.py`` (and other admit
    pins downstream) — Memorial Team Leader removed from the decline
    set + per-card real-EoE warp-cast-then-anthem probe.
  * Per-card real-EoE probe driving the actual parsed MTL printing
    through both engines byte-equal — warp-cast the card, verify
    anthem fires under DuringYourTurn (active-player gate), verify
    end-step exile + re-cast lifecycle.

**Test plan (this cycle):**

  * Parser SoT: Memorial Team Leader's static ability parses to the
    documented ``StaticAbility(scope=OTHER_CREATURES_YOU_CONTROL,
    condition=DuringYourTurn(), continuous_effect=ContinuousModifier(
    layer=7, payload=PowerToughnessBonus(1, 0)))`` shape with
    warp_cost ``{1}{R}``.
  * Bridge round-trip: ``_spec_card_to_printing_dict`` of a CardDef
    carrying the 6-tuple shape emits the expected dict; the inverse
    ``_card_def_to_python_printing`` materializes the expected
    Python ``StaticAbility``. Legacy 2-tuple Tannuk-shape entries
    round-trip bit-identical (back-compat).
  * Rust round-trip: registry build + ``get_printing_static_anthems_full``
    surfaces the full 6-tuple readback byte-equal to the input;
    ``get_printing_static_anthems`` (Phase-1 narrow shape) still
    works for back-compat.
  * Rust reader fold: a synthetic battlefield with a Phase-4-shape
    anthem source + other creature folds +1/+0 onto the other
    creature's effective power under ``state.active_player ==
    source.controller``; folds 0 when it isn't the source's turn.
    The source itself does NOT receive the bonus (``other_``-scope).
  * Condition dispatcher: ``_static_anthem_condition_from_tag``
    round-trips ``("during_your_turn", ())`` → ``DuringYourTurn()``
    and ``("", ())`` → ``None``; raises on unknown tags.
  * Covered-set membership: the new shape is wired into the bridge
    emit/parse + Rust reader path.
  * **Substrate-only invariant pin** (LOAD-BEARING): Memorial Team
    Leader's live ``CardPrinting`` STAYS DECLINED at every admit
    predicate disjunct after this cycle. If this pin fails — i.e.
    MTL starts admitting on this branch — the substrate-only
    invariant has been violated and the cross-engine probe would
    run BEFORE the Cycle-2 warp-cast lifecycle is wired, producing
    wrong byte-equal claims for the warp-cast path. Catch the drift
    here. Cycle 2 is what flips this pin.
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


_ZONE_HAND = 0
_ZONE_BATTLEFIELD = 2


def _fresh_rust():
    """Synthetic two-player state with both players at 20 life."""
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_real_eoe_memorial_team_leader_static_ability_shape():
    """**Parser source-of-truth pin.** Memorial Team Leader's live
    parsed ``CardPrinting`` carries exactly ONE StaticAbility whose
    shape is the Phase-4 carrier: ``OTHER_CREATURES_YOU_CONTROL``
    scope, ``DuringYourTurn`` condition, layer-7 ContinuousModifier
    with PowerToughnessBonus(1, 0). It ALSO carries warp_cost
    ``{1}{R}``. Pins today's Python shape so any parser drift
    surfaces before the substrate's bridge/serializer get out of
    sync."""
    from mtg_bot.cards.base import StaticScope
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import DuringYourTurn
    from mtg_bot.effects.modifiers import (
        ContinuousModifier,
        PowerToughnessBonus,
    )

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    assert len(mtl.static_abilities) == 1
    sa = mtl.static_abilities[0]
    assert sa.scope == StaticScope.OTHER_CREATURES_YOU_CONTROL
    assert sa.condition == DuringYourTurn()
    assert isinstance(sa.continuous_effect, ContinuousModifier)
    assert sa.continuous_effect.layer == 7
    assert sa.continuous_effect.payload == PowerToughnessBonus(
        power_bonus=1, toughness_bonus=0,
    )
    assert mtl.warp_cost is not None
    assert mtl.warp_cost.generic == 1
    # `colored` is a tuple of (color, count) pairs; MTL is {1}{R}.
    assert ("R", 1) in mtl.warp_cost.colored


# ---------------------------------------------------------------------------
# Condition dispatcher round-trip
# ---------------------------------------------------------------------------


def test_static_anthem_condition_from_tag_empty_returns_none():
    """Empty tag = Phase-1 unconditional default → ``None``. The
    bridge 2-tuple shape (legacy Tannuk) emits an empty tag through
    the rehydrator and gets back ``None``; the materialized
    StaticAbility carries ``condition=None`` and the
    ``applies_to`` walk doesn't gate."""
    from mtg_bot.parity.cross_engine import (
        _static_anthem_condition_from_tag,
    )

    assert _static_anthem_condition_from_tag("", ()) is None


def test_static_anthem_condition_from_tag_during_your_turn():
    """The ``"during_your_turn"`` tag rehydrates to
    ``DuringYourTurn()`` — the Condition Memorial Team Leader's
    static ability carries. The Python ``StaticAbility.applies_to``
    walk evaluates this Condition against ``state.active_player``."""
    from mtg_bot.effects.conditions import DuringYourTurn
    from mtg_bot.parity.cross_engine import (
        _static_anthem_condition_from_tag,
    )

    assert _static_anthem_condition_from_tag(
        "during_your_turn", (),
    ) == DuringYourTurn()


def test_static_anthem_condition_from_tag_unknown_raises():
    """An unknown tag must raise loudly — the Rust parser's whitelist
    is the source of truth for which tags reach this function, and a
    tag arriving here that isn't in the table is a bridge-vs-
    materializer disagreement that would silently mis-route a gate."""
    from mtg_bot.parity.cross_engine import (
        _static_anthem_condition_from_tag,
    )

    with pytest.raises(ValueError, match="unknown anthem-scope"):
        _static_anthem_condition_from_tag("never_your_turn", ())


def test_static_anthem_condition_from_tag_rejects_self_scope_tags():
    """The Phase-3 SELF-scope condition vocabulary (e.g.
    ``"control_permanent_is_artifact"``) is intentionally NOT
    recognized by the anthem rehydrator — conflating the two dispatch
    tables would silently mis-route a tag if a future slice added
    the same surface form to both scopes. The anthem helper raises
    on Phase-3 tags."""
    from mtg_bot.parity.cross_engine import (
        _static_anthem_condition_from_tag,
    )

    with pytest.raises(ValueError, match="unknown anthem-scope"):
        _static_anthem_condition_from_tag(
            "control_permanent_is_artifact", (),
        )


def test_static_anthem_condition_from_tag_args_rejected():
    """``during_your_turn`` takes no args — a non-empty ``cond_args``
    is a bridge encoding bug; raise rather than silently ignore."""
    from mtg_bot.parity.cross_engine import (
        _static_anthem_condition_from_tag,
    )

    with pytest.raises(ValueError, match="takes no args"):
        _static_anthem_condition_from_tag("during_your_turn", (5,))
    with pytest.raises(ValueError, match="takes no args"):
        _static_anthem_condition_from_tag("", (5,))


# ---------------------------------------------------------------------------
# Bridge round-trip — CardDef -> printing dict
# ---------------------------------------------------------------------------


def test_bridge_emit_phase1_two_tuple_anthem_byte_equal():
    """The legacy 2-tuple Phase-1 Tannuk-shape anthem entry emits the
    pre-Phase-4 dict shape (no P/T or condition keys) — every Phase-1
    anthem's registry dict stays byte-identical to before Cycle 1.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _spec_card_to_printing_dict,
    )

    cd = CardDef(
        name="Tannuk-Probe",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("R", 2),),
        power=3,
        toughness=5,
        static_anthems=(
            ("other_creatures_you_control", ("haste",)),
        ),
    )
    d = _spec_card_to_printing_dict(cd)
    assert "static_anthems" in d
    [entry] = d["static_anthems"]
    assert entry == {
        "scope": "other_creatures_you_control",
        "granted_keywords": ["haste"],
    }


def test_bridge_emit_phase4_six_tuple_anthem_carries_pt_and_condition():
    """The 6-tuple Phase-4 shape emits a dict with the
    ``power_bonus`` + ``condition_tag`` + ``condition_args`` keys."""
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _spec_card_to_printing_dict,
    )

    cd = CardDef(
        name="MTL-Probe",
        card_type="Creature",
        mana_cost_generic=3,
        mana_cost_colored=(("R", 1),),
        power=4,
        toughness=3,
        static_anthems=(
            (
                "other_creatures_you_control",
                (),
                1,
                0,
                "during_your_turn",
                (),
            ),
        ),
    )
    d = _spec_card_to_printing_dict(cd)
    [entry] = d["static_anthems"]
    assert entry == {
        "scope": "other_creatures_you_control",
        "granted_keywords": [],
        "power_bonus": 1,
        "condition_tag": "during_your_turn",
        "condition_args": [],
    }


def test_bridge_emit_phase4_zero_pt_omits_keys():
    """A 6-tuple entry whose ``power_bonus`` and ``toughness_bonus``
    are both zero omits those keys (keeping the registry dict
    minimal). The condition_tag still emits when non-empty."""
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _spec_card_to_printing_dict,
    )

    cd = CardDef(
        name="Zero-PT-Conditional-Anthem",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("R", 1),),
        power=2,
        toughness=2,
        static_anthems=(
            (
                "other_creatures_you_control",
                ("haste",),
                0,
                0,
                "during_your_turn",
                (),
            ),
        ),
    )
    d = _spec_card_to_printing_dict(cd)
    [entry] = d["static_anthems"]
    assert "power_bonus" not in entry
    assert "toughness_bonus" not in entry
    assert entry["condition_tag"] == "during_your_turn"


def test_bridge_emit_rejects_bad_tuple_length():
    """A tuple length that isn't 2 or 6 is a CardDef construction bug;
    raise loudly rather than emit an under-specified dict."""
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _spec_card_to_printing_dict,
    )

    cd = CardDef(
        name="Bad-Anthem",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("R", 1),),
        power=2,
        toughness=2,
        static_anthems=(
            ("other_creatures_you_control", ("haste",), 1),  # 3-tuple
        ),
    )
    with pytest.raises(ValueError, match="2-tuple or 6-tuple"):
        _spec_card_to_printing_dict(cd)


# ---------------------------------------------------------------------------
# Bridge round-trip — CardDef -> Python printing materialization
# ---------------------------------------------------------------------------


def test_card_def_to_python_phase4_anthem_materializes_static_ability():
    """The 6-tuple Phase-4 shape materializes into a Python
    ``StaticAbility(condition=DuringYourTurn(),
    continuous_effect=ContinuousModifier(layer=7,
    payload=PowerToughnessBonus(1, 0)))`` — the exact shape the
    parser emits for MTL's oracle line."""
    from mtg_bot.cards.base import StaticScope
    from mtg_bot.effects.conditions import DuringYourTurn
    from mtg_bot.effects.modifiers import (
        ContinuousModifier,
        PowerToughnessBonus,
    )
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _card_def_to_python_printing,
    )

    cd = CardDef(
        name="MTL-Probe",
        card_type="Creature",
        mana_cost_generic=3,
        mana_cost_colored=(("R", 1),),
        power=4,
        toughness=3,
        static_anthems=(
            (
                "other_creatures_you_control",
                (),
                1,
                0,
                "during_your_turn",
                (),
            ),
        ),
    )
    printing = _card_def_to_python_printing(cd)
    [sa] = printing.static_abilities
    assert sa.scope == "other_creatures_you_control"
    assert sa.condition == DuringYourTurn()
    assert isinstance(sa.continuous_effect, ContinuousModifier)
    assert sa.continuous_effect.layer == 7
    assert sa.continuous_effect.payload == PowerToughnessBonus(
        power_bonus=1, toughness_bonus=0,
    )


def test_card_def_to_python_phase4_anthem_fans_pt_and_keywords_separately():
    """A 6-tuple entry with BOTH non-zero P/T AND a keyword grant fans
    out into TWO StaticAbility instances — one carrying the layer-7
    PT payload, one carrying the layer-6 GrantKeyword — both sharing
    the same condition. Mirrors the parser fan-out for compound P/T+
    keyword anthems (``... get +N/+M and have <keyword>``)."""
    from mtg_bot.effects.conditions import DuringYourTurn
    from mtg_bot.effects.modifiers import (
        ContinuousModifier,
        GrantKeyword,
        PowerToughnessBonus,
    )
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _card_def_to_python_printing,
    )

    cd = CardDef(
        name="PT-Plus-KW-Anthem",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("R", 2),),
        power=3,
        toughness=3,
        static_anthems=(
            (
                "other_creatures_you_control",
                ("haste",),
                1,
                1,
                "during_your_turn",
                (),
            ),
        ),
    )
    printing = _card_def_to_python_printing(cd)
    assert len(printing.static_abilities) == 2
    # Find the P/T arm and the keyword arm.
    pt_sa = next(
        sa for sa in printing.static_abilities
        if isinstance(sa.continuous_effect.payload, PowerToughnessBonus)
    )
    kw_sa = next(
        sa for sa in printing.static_abilities
        if isinstance(sa.continuous_effect.payload, GrantKeyword)
    )
    assert pt_sa.condition == DuringYourTurn()
    assert kw_sa.condition == DuringYourTurn()
    assert pt_sa.continuous_effect.layer == 7
    assert kw_sa.continuous_effect.layer == 6


def test_card_def_to_python_phase1_two_tuple_back_compat():
    """The legacy 2-tuple Tannuk shape still materializes as a
    layer-6 keyword-only StaticAbility with ``condition=None``.
    Back-compat byte-identical to pre-Phase-4."""
    from mtg_bot.effects.modifiers import ContinuousModifier, GrantKeyword
    from mtg_bot.parity.cross_engine import (
        CardDef,
        _card_def_to_python_printing,
    )

    cd = CardDef(
        name="Tannuk-Probe",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("R", 2),),
        power=3,
        toughness=5,
        static_anthems=(
            ("other_creatures_you_control", ("haste",)),
        ),
    )
    printing = _card_def_to_python_printing(cd)
    [sa] = printing.static_abilities
    assert sa.condition is None
    assert isinstance(sa.continuous_effect, ContinuousModifier)
    assert sa.continuous_effect.layer == 6
    assert isinstance(sa.continuous_effect.payload, GrantKeyword)


# ---------------------------------------------------------------------------
# Rust round-trip — registry build + readback
# ---------------------------------------------------------------------------


def test_rust_registry_round_trip_phase4_anthem_full_shape():
    """Rust's ``parse_printing`` reads the 6-tuple registry dict and
    surfaces it byte-equal via the new
    ``get_printing_static_anthems_full`` accessor."""
    _require_engine()
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        build_rust_registry,
    )

    spec = DeckSpec(
        card_defs=(
            CardDef(name="Forest", card_type="Land", mana_produced=("G",)),
            CardDef(
                name="MTL-Probe",
                card_type="Creature",
                mana_cost_generic=3,
                mana_cost_colored=(("R", 1),),
                power=4,
                toughness=3,
                static_anthems=(
                    (
                        "other_creatures_you_control",
                        (),
                        1,
                        0,
                        "during_your_turn",
                        (),
                    ),
                ),
            ),
        ),
        p0_library=("MTL-Probe", "Forest"),
        p1_library=("Forest",),
    )
    reg, name_to_pid = build_rust_registry(spec)
    mtl_full = reg.get_printing_static_anthems_full(name_to_pid["MTL-Probe"])
    assert mtl_full == [
        (
            "other_creatures_you_control",
            [],
            1,
            0,
            "during_your_turn",
            [],
        ),
    ]


def test_rust_registry_round_trip_phase1_narrow_back_compat():
    """The Phase-1 narrow ``get_printing_static_anthems`` accessor
    keeps surfacing the scope + granted_keywords pair byte-identical
    to pre-Phase-4 — every existing test that calls the Phase-1
    accessor stays green."""
    _require_engine()
    from mtg_bot.parity.cross_engine import (
        CardDef,
        DeckSpec,
        build_rust_registry,
    )

    spec = DeckSpec(
        card_defs=(
            CardDef(name="Forest", card_type="Land", mana_produced=("G",)),
            CardDef(
                name="Tannuk-Probe",
                card_type="Creature",
                mana_cost_generic=2,
                mana_cost_colored=(("R", 2),),
                power=3,
                toughness=5,
                static_anthems=(
                    ("other_creatures_you_control", ("haste",)),
                ),
            ),
        ),
        p0_library=("Tannuk-Probe", "Forest"),
        p1_library=("Forest",),
    )
    reg, name_to_pid = build_rust_registry(spec)
    tannuk_narrow = reg.get_printing_static_anthems(name_to_pid["Tannuk-Probe"])
    assert tannuk_narrow == [("other_creatures_you_control", ["haste"])]
    # The full accessor reads back the zero defaults for power_bonus
    # / toughness_bonus and the empty condition_tag — round-trip the
    # back-compat zero/empty shape.
    tannuk_full = reg.get_printing_static_anthems_full(
        name_to_pid["Tannuk-Probe"]
    )
    assert tannuk_full == [
        ("other_creatures_you_control", ["haste"], 0, 0, "", []),
    ]


def test_rust_registry_rejects_unknown_anthem_condition_tag():
    """A registry dict carrying a condition_tag that isn't in the Rust
    whitelist must fail loudly at parse time. Mirrors the Phase-1
    scope-whitelist precedent at ``cards.rs::parse_printing``."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="condition_tag must be"):
        reg.register_printing({
            "name": "Bad-Anthem",
            "card_types": ["Creature"],
            "mana_cost": {"R": 1},
            "power": 2,
            "toughness": 2,
            "static_anthems": [
                {
                    "scope": "other_creatures_you_control",
                    "granted_keywords": [],
                    "power_bonus": 1,
                    "condition_tag": "never_your_turn",
                    "condition_args": [],
                },
            ],
        })


# ---------------------------------------------------------------------------
# Rust reader fold — synthetic battlefield
# ---------------------------------------------------------------------------


def _phase4_anthem_source(rs, owner, *, power=4, toughness=3):
    """Inject a Phase-4-shape anthem source on owner's battlefield —
    a 4/3 'MTL Probe' creature carrying ``StaticAnthem`` with +1/+0
    P/T contribution + ``during_your_turn`` condition."""
    return rs.register_and_inject_object(
        {
            "name": "MTL Probe",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 3, "R": 1},
            "power": power,
            "toughness": toughness,
            "static_anthems": [
                {
                    "scope": "other_creatures_you_control",
                    "granted_keywords": [],
                    "power_bonus": 1,
                    "condition_tag": "during_your_turn",
                    "condition_args": [],
                },
            ],
        },
        owner,
        _ZONE_BATTLEFIELD,
    )


def _vanilla_creature(rs, owner, *, power=2, toughness=2):
    """Inject a vanilla 2/2 creature on owner's battlefield — the
    target whose effective power the anthem fold contributes to."""
    return rs.register_and_inject_object(
        {
            "name": "Vanilla Bear",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1, "G": 1},
            "power": power,
            "toughness": toughness,
        },
        owner,
        _ZONE_BATTLEFIELD,
    )


def test_rust_anthem_pt_fold_during_your_turn_adds_one_power():
    """On the source's controller's turn, a Phase-4 anthem source
    contributes +1/+0 to OTHER creatures the controller controls.
    The active_player gate flips the fold on; the source itself does
    NOT receive the bonus (other_-scope)."""
    _require_engine()
    rs = _fresh_rust()
    # P0 controls a Phase-4 anthem source + a vanilla bear.
    src_id = _phase4_anthem_source(rs, owner=0)
    bear_id = _vanilla_creature(rs, owner=0)
    rs.set_active_player(0)
    # The bear is a 2/2 — anthem adds +1/+0 → 3/2.
    assert rs.effective_power(bear_id) == 3
    assert rs.effective_toughness(bear_id) == 2
    # The source itself is excluded (other_-scope) — stays 4/3.
    assert rs.effective_power(src_id) == 4
    assert rs.effective_toughness(src_id) == 3


def test_rust_anthem_pt_fold_off_turn_contributes_zero():
    """When it's NOT the source's controller's turn, the
    ``during_your_turn`` condition gate closes and the anthem
    contributes zero. The bear stays at its printed 2/2."""
    _require_engine()
    rs = _fresh_rust()
    _phase4_anthem_source(rs, owner=0)
    bear_id = _vanilla_creature(rs, owner=0)
    # P1 is the active player → P0's during_your_turn anthem gate is
    # closed.
    rs.set_active_player(1)
    assert rs.effective_power(bear_id) == 2
    assert rs.effective_toughness(bear_id) == 2


def test_rust_anthem_pt_fold_cross_controller_does_not_fire():
    """An anthem on P0's battlefield does NOT contribute to a
    creature on P1's battlefield — the scope is "you control",
    which restricts the walk to permanents under the SAME controller
    as the anthem source. Even on P0's turn the P1 bear stays
    printed-baseline."""
    _require_engine()
    rs = _fresh_rust()
    _phase4_anthem_source(rs, owner=0)
    bear_id = _vanilla_creature(rs, owner=1)
    rs.set_active_player(0)
    assert rs.effective_power(bear_id) == 2
    assert rs.effective_toughness(bear_id) == 2


def test_rust_anthem_pt_fold_unconditional_phase1_anthem_zero_pt():
    """A Phase-1 keyword-only anthem source (back-compat 2-tuple
    bridge shape; no P/T fields) contributes 0/0 P/T regardless of
    the active player. The Phase-1 path stays bit-identical to
    pre-Phase-4."""
    _require_engine()
    rs = _fresh_rust()
    # Tannuk-shape: keyword-only anthem with NO P/T fields.
    rs.register_and_inject_object(
        {
            "name": "Tannuk Probe",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 2, "R": 2},
            "power": 3,
            "toughness": 5,
            "static_anthems": [
                {
                    "scope": "other_creatures_you_control",
                    "granted_keywords": ["haste"],
                },
            ],
        },
        0, _ZONE_BATTLEFIELD,
    )
    bear_id = _vanilla_creature(rs, owner=0)
    rs.set_active_player(0)
    # Power stays at 2 — the Phase-1 anthem contributes only a
    # keyword (haste); zero P/T.
    assert rs.effective_power(bear_id) == 2
    assert rs.effective_toughness(bear_id) == 2


# ---------------------------------------------------------------------------
# Covered-set + substrate-only invariant pin (LOAD-BEARING)
# ---------------------------------------------------------------------------


def test_memorial_team_leader_now_admits_at_admit_gate_post_cycle_2():
    """**LOAD-BEARING Cycle 2 FLIP marker.** Memorial Team Leader's
    live ``CardPrinting`` ADMITS post-Cycle-2 via the new Phase-4
    ``_printing_is_bridge_static_anthem_pt_conditional_warp_creature``
    disjunct. The Cycle 1 substrate invariant pin (this test's
    predecessor — ``test_memorial_team_leader_stays_declined_at_admit_
    gate``) has been INVERTED here: the same five Cycle 1 disjuncts
    still REJECT (their gates haven't widened — the Phase-4 admit
    rides its own dedicated arm, not a relaxation of any prior
    predicate), and the new Cycle-2 arm POSITIVELY admits. If this
    pin fails, MTL has started declining OR auto-grown OFF the
    dedicated Phase-4 disjunct — both shapes are regressions Cycle 2
    must not introduce. Catch the drift here.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    mtl = src.get("Memorial Team Leader")
    if mtl is None:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    # The five Cycle-1 disjuncts STAY rejecting — the Phase-4 admit
    # is a new dedicated arm, NOT a relaxation of any prior gate.

    # Phase 1 anthem-keyword predicate STILL rejects MTL (P/T anthem
    # carrier; the Phase-1 narrow predicate gates ``if ability.power_
    # bonus or ability.toughness_bonus: return False`` AND requires
    # ``condition is None`` — MTL has a layer-7 PowerToughnessBonus
    # under DuringYourTurn so it's positively rejected here).
    assert trajectory._printing_is_bridge_simple_static_anthem_creature(
        mtl,
    ) is False

    # Phase 3 SELF-scope conditional still rejects MTL (anthem scope,
    # not SELF).
    assert (
        trajectory._printing_is_bridge_simple_static_self_conditional_creature(
            mtl,
        ) is False
    )

    # Phase 2 uncounterable predicate still rejects MTL (no
    # uncounterable flag).
    assert (
        trajectory._printing_is_bridge_simple_uncounterable_creature(mtl)
        is False
    )

    # Pure-warp creature predicate still rejects MTL (has
    # static_abilities — the pure-warp arm's positive ban is
    # unchanged).
    assert trajectory._printing_is_bridge_pure_warp_creature(mtl) is False

    # Plain simple-creature predicate still rejects MTL (has both
    # warp_cost AND static_abilities).
    assert trajectory._printing_is_bridge_simple_creature(mtl) is False

    # **The Cycle 2 FLIP marker.** The new Phase-4 disjunct
    # POSITIVELY admits MTL — the load-bearing closure for ~6,229
    # 17lands decks.
    assert (
        trajectory._printing_is_bridge_static_anthem_pt_conditional_warp_creature(
            mtl,
        )
        is True
    ), (
        "Cycle 2 FLIP marker: MTL must positively admit via the "
        "Phase-4 conditional-P/T-anthem + warp disjunct."
    )


def test_memorial_team_leader_admits_through_loader_filter_post_cycle_2():
    """The end-to-end loader filter
    :func:`_filter_deck_to_bridge_supported` ADMITS Memorial Team
    Leader from a deck containing it post-Cycle 2 — the
    ``not_bridged_sink`` stays empty and the produced
    ``filtered_names`` preserves every copy. The Cycle 1 invariant
    pin (predecessor: ``test_memorial_team_leader_drops_at_loader_
    filter``) has been INVERTED: MTL is now bridge-supported end-to-
    end via the new Phase-4 disjunct, the bridge round-trip threads
    the 6-tuple ``static_anthems`` shape Cycle 1 wired, and the
    resulting CardDef carries ``has_warp=True`` + the Phase-4
    ``static_anthems`` entry.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source().get_printings()
    if "Memorial Team Leader" not in src:
        pytest.skip("Memorial Team Leader absent from active CardSource")

    not_bridged: list[str] = []
    filtered, card_defs = trajectory._filter_deck_to_bridge_supported(
        ["Memorial Team Leader"] * 4 + ["Forest"] * 36,
        src,
        not_bridged_sink=not_bridged,
    )
    # 4x MTL admit + 36x Forest admit; `not_bridged` empty.
    assert filtered == ["Memorial Team Leader"] * 4 + ["Forest"] * 36
    assert not_bridged == []
    # Exactly two CardDefs (deduplicated by name) — MTL + Forest.
    cd_by_name = {cd.name: cd for cd in card_defs}
    assert set(cd_by_name) == {"Memorial Team Leader", "Forest"}
    mtl_cd = cd_by_name["Memorial Team Leader"]
    assert mtl_cd.card_type == "Creature"
    assert mtl_cd.power == 4
    assert mtl_cd.toughness == 3
    assert mtl_cd.has_warp is True
    # The 6-tuple Phase-4 ``static_anthems`` entry threaded byte-
    # equal: scope=other_creatures_you_control, empty
    # granted_keywords, power_bonus=1, toughness_bonus=0,
    # condition_tag=during_your_turn, no args.
    assert mtl_cd.static_anthems == (
        (
            "other_creatures_you_control",
            (),
            1,
            0,
            "during_your_turn",
            (),
        ),
    )
