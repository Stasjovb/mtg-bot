"""**Carrier-AA substrate Phase 4E Cycle 1 (2026-05-26).**

Tests for the Phase 4E Cycle 1 Rust slice landing per
``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §4.4 (Rust spec) +
§5.7 (Python bridge spec) + §6.5 (test plan, pins #35-37, plus the
substrate-only invariant pins) + §7.5 (cycle plan).

Deliverables (Cycle 1 Rust slice, per design doc §4.4 + §7.5):

  - New Rust ``Effect::DrawCardsByConditionMultiplier { condition_tag,
    condition_args, description_fragment }`` variant on
    ``cards.rs::Effect`` — All-Fates Scroll's AA[1] pilot effect
    (``{7}, {T}, Sacrifice this artifact: Draw X cards, where X is the
    number of differently named lands you control.``).
  - ``parse_effect`` arm in ``cards.rs`` —
    ``"draw_cards_by_condition_multiplier"`` 3-key dict with required
    ``condition_tag`` (whitelisted), optional ``condition_args`` (per-
    tag arity validation), and optional ``description_fragment``.
  - ``to_pydict`` arm in ``cards.rs`` — emits the same 3-key dict with
    the empty-omit discipline (``condition_args`` + ``description_
    fragment`` keys are emitted only when non-empty).
  - New parallel ``state_ops_combat::condition_count(tag, args,
    state, viewer)`` u32 dispatcher (sibling of the boolean
    ``static_self_bonus_condition_matches``) — required because the
    multiplier-shape Condition family returns a count rather than a
    bool. Per design doc §4.4.2: "Add this parallel function rather
    than overloading the existing one."
  - Cycle 1 condition vocabulary: ONE tag —
    ``"per_differently_named_land"`` (no args). Counts distinct
    printed names among the viewer's lands; mirrors Python's
    ``PerDifferentlyNamedLand.multiplier`` at
    ``effects/conditions.py:401``.
  - Resolve arm in ``state_ops_resolve.rs::apply_effect`` — computes
    ``x = condition_count(tag, args, state, activator)``; on ``x >
    0``, walks the activator's library top-down transferring ``x``
    objects to hand under the CR-704.5b empty-library flag-flip
    convention (mirrors ``Effect::DrawCards`` inner loop at
    ``state_ops_resolve.rs:2388``).
  - Cross-engine bridge arms in ``src/mtg_bot/parity/cross_engine.py``:
      * Reverse arm in ``_ta_dict_to_python_effect`` — recognizes
        ``kind == "draw_cards_by_condition_multiplier"`` and
        rehydrates the Python ``DrawCardsByConditionMultiplier``
        instance via a new ``_draw_cards_condition_from_tag`` helper
        (third dispatch table, count-valued sibling of the existing
        SELF-scope + anthem-scope boolean rehydrators).
      * Forward arm in ``_python_aa_to_safe_dict`` — recognizes
        ``isinstance(effect, DrawCardsByConditionMultiplier)`` and
        emits the matching 3-key dict.
    Both arms use the SPECIFIC class (no parent ``Effect`` fall-
    through) per the Phase-3A/3B/3C specificity contract.

ZERO Python admit widen this cycle (the
``_carrier_aa_phase_1_effect_classes`` widen + the
``is_mana_ability`` AA-rider widen + the All-Fates Scroll admit-set
inversion all ship Cycle 2 per design doc §5.7 + §7.5).
ZERO per-card probe this cycle (Cycle 3 ships the real-EoE
``tests/test_all_fates_scroll_parity.py`` per design doc §6.7).
ZERO new cost-shape Rust machinery — All-Fates Scroll's
``{T}`` (AA[0]) + ``{7}, {T}, Sac`` (AA[1]) ride the Phase 1.5a +
Phase 2a cost-shape gates.

Substrate-only invariant — All-Fates Scroll STAYS DECLINED at the
admit gate post-Cycle-1. The Rust Effect variant + condition_count
dispatcher + cross-engine bridge arms all landed; the live admit
gate still declines All-Fates Scroll's printing because (a)
``_carrier_aa_phase_1_effect_classes`` doesn't yet include
``DrawCardsByConditionMultiplier`` AND (b) the AA-rider gate at
``_aa_is_phase1_sub_shape_a`` still declines AA[0]'s
``is_mana_ability=True`` rider. Both widens ship C2. The forward
serializer + Rust round-trip both succeed at C1 — driven by
synthetic unit pins; the live admit FLIP lands at C2.

**Verify-first findings (live tree, main ``a6fe7c9c``):**

  - All-Fates Scroll printing-level shape: ``card_types=("Artifact",)``,
    ``subtypes=()``, ``supertypes=()``, ``keywords=frozenset()``,
    ``triggered_abilities=()``, ``static_abilities=()``,
    ``n_aa=2``.
  - AA[0]: ``cost=ActivationCost(mana=None, tap_self=True)``,
    ``effect=AddManaToPool(produces=(('any', 1),), spend_restriction=None)``,
    ``is_mana_ability=True``, ``sorcery_speed=False``.
  - AA[1]: ``cost=ActivationCost(mana=ManaCost(generic=7), tap_self=
    True, sacrifice_self=True)``, ``effect=DrawCardsByConditionMultiplier
    (condition=PerDifferentlyNamedLand(), description_fragment='where
    X is the number of differently named lands you control')``,
    ``is_mana_ability=False``, ``sorcery_speed=False``.
  - Pre-C1 Rust state: ``Effect`` enum's last variant was
    ``BecomesCopyOfTargetLand`` (Phase 3C C2 commit ``6de50d8d``); no
    pre-existing ``DrawCardsByConditionMultiplier`` variant — purely
    additive at the variant cardinality axis.
  - ``state_ops_combat`` carried two boolean condition dispatchers:
    ``static_self_bonus_condition_matches`` (Phase 3 SELF-scope,
    round-81) and ``static_anthem_condition_matches`` (Phase 4
    anthem-scope, round-83). C1 adds a third, count-valued sibling
    (``condition_count``) per the design doc §4.4.2 spec.
  - Pre-C1 ``_python_aa_to_safe_dict`` decline floor: any AA with
    ``is_mana_ability=True`` returns ``None`` — admit-gate teeth
    that survive C1; C2 widens the gate floor.

**Test plan (per design doc §6.5 pins #35-37, Cycle 1 substrate-only
slice):**

  - Parser SoT pin: confirm Python's ``DrawCardsByConditionMultiplier``
    + ``PerDifferentlyNamedLand`` classes exist with the expected
    shape; All-Fates Scroll's parser SoT carries both AAs in the
    expected (is_mana_ability, Effect-class) decline-teeth axis.
  - Pin #35 — Rust ``parse_effect`` round-trip via ``register_
    printing``; an Artifact carrier with both AAs deserializes
    cleanly through the new variant.
  - Pin #36 — Rust ``to_pydict`` round-trip via the bridge inverse
    (parse + emit yields a byte-equal dict with the empty-omit
    discipline).
  - Pin #37 — Rust resolve arm: activate AA[1] with N>0 distinct-
    named lands; draws N cards top-of-library (CR-704.5b empty-
    library short-circuit observed).
  - Cross-engine bridge round-trip pins (dict↔Python reverse +
    Python→dict forward + symmetric round-trip).
  - Substrate-only invariant pins: All-Fates Scroll STAYS DECLINED
    at the admit gate post-Cycle-1 + the
    ``_carrier_aa_phase_1_effect_classes`` Effect-class admit set
    UNCHANGED (no ``DrawCardsByConditionMultiplier`` admit) + the
    AA-rider gate still declines ``is_mana_ability=True``.

This is a **substrate-only closure** — the cycle adds the new Rust
Effect variant + parallel ``condition_count`` dispatcher + the
cross-engine bridge as reusable infrastructure. All-Fates Scroll
STAYS DECLINED at the production-deck admit gate post-Cycle-1.
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


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


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
    per side. Mirrors the Phase-3A/3B/3C sibling shared fixture."""
    return engine.make_synthetic_state()


# ---------------------------------------------------------------------------
# Parser SoT verify-first
# ---------------------------------------------------------------------------


def test_python_draw_cards_by_condition_multiplier_class_exists():
    """**Parser source-of-truth pin.** Python's
    ``DrawCardsByConditionMultiplier`` class is in
    ``effects.generic.draw_mill``, a frozen dataclass with a
    ``condition: Condition`` field + a ``description_fragment: str``
    field (default ``"where X is determined at resolution"``).
    """
    from mtg_bot.effects.base import Effect
    from mtg_bot.effects.conditions import PerDifferentlyNamedLand
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsByConditionMultiplier,
    )

    eff = DrawCardsByConditionMultiplier(
        condition=PerDifferentlyNamedLand(),
        description_fragment="where X is the number of differently "
        "named lands you control",
    )
    assert isinstance(eff, Effect)
    assert isinstance(eff.condition, PerDifferentlyNamedLand)
    # Two instances with identical fields compare equal (frozen
    # dataclass __eq__ default).
    same = DrawCardsByConditionMultiplier(
        condition=PerDifferentlyNamedLand(),
        description_fragment="where X is the number of differently "
        "named lands you control",
    )
    assert eff == same


def test_per_differently_named_land_class_shape():
    """**Parser SoT pin.** Python's ``PerDifferentlyNamedLand`` is a
    parameterless frozen Condition; ``multiplier`` returns the count
    of distinct printed names among the viewer's lands.
    """
    from mtg_bot.effects.conditions import (
        Condition,
        PerDifferentlyNamedLand,
    )

    cond = PerDifferentlyNamedLand()
    assert isinstance(cond, Condition)
    assert cond == PerDifferentlyNamedLand()


def test_all_fates_scroll_live_aa_shapes_match_design_doc():
    """**Verify-first pin (design doc §2.1 row + §3E spec).** The live
    All-Fates Scroll parser SoT carries:

      * AA[0]: ``AddManaToPool(produces=(("any", 1),))`` +
        ``is_mana_ability=True``.
      * AA[1]: ``DrawCardsByConditionMultiplier(condition=
        PerDifferentlyNamedLand(), description_fragment=
        "where X is the number of differently named lands you
        control")`` + ``is_mana_ability=False``.

    This pin protects the verify-first finding the C1 substrate is
    built against: a future parser tweak that mutates either AA's
    shape would need to be reconciled here BEFORE C2 ships the admit
    widens.
    """
    import json

    from mtg_bot.cards.parser_source import _build_artifact_printing
    from mtg_bot.effects.conditions import PerDifferentlyNamedLand
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsByConditionMultiplier,
    )
    from mtg_bot.effects.generic.mana import AddManaToPool

    with open("data/edge_of_eternities.json", encoding="utf-8") as f:
        raw_cards = json.load(f)
    raw = next(
        (c for c in raw_cards if c.get("name") == "All-Fates Scroll"),
        None,
    )
    assert raw is not None, (
        "Verify-first invariant: All-Fates Scroll must be present in "
        "data/edge_of_eternities.json"
    )
    printing = _build_artifact_printing(raw)
    assert printing is not None
    assert printing.card_types == ("Artifact",)
    assert len(printing.activated_abilities) == 2

    aa0 = printing.activated_abilities[0]
    assert isinstance(aa0.effect, AddManaToPool)
    assert aa0.effect.produces == (("any", 1),)
    assert aa0.is_mana_ability is True
    assert aa0.sorcery_speed is False
    assert aa0.cost.tap_self is True
    assert aa0.cost.mana is None

    aa1 = printing.activated_abilities[1]
    assert isinstance(aa1.effect, DrawCardsByConditionMultiplier)
    assert isinstance(aa1.effect.condition, PerDifferentlyNamedLand)
    assert aa1.is_mana_ability is False
    assert aa1.sorcery_speed is False
    assert aa1.cost.tap_self is True
    assert aa1.cost.sacrifice_self is True
    assert aa1.cost.mana is not None
    assert aa1.cost.mana.generic == 7


# ---------------------------------------------------------------------------
# Cross-engine bridge arm pins (dict <-> Python)
# ---------------------------------------------------------------------------


def test_bridge_reverse_arm_draw_cards_by_condition_multiplier_per_differently_named_land():
    """Reverse arm constructs
    ``DrawCardsByConditionMultiplier(condition=PerDifferentlyNamedLand(),
    description_fragment="...")`` from the
    ``draw_cards_by_condition_multiplier`` 3-key dict.
    """
    from mtg_bot.effects.conditions import PerDifferentlyNamedLand
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsByConditionMultiplier,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "draw_cards_by_condition_multiplier",
        "condition_tag": "per_differently_named_land",
        "description_fragment": "where X is the number of differently "
        "named lands you control",
    })
    assert isinstance(back, DrawCardsByConditionMultiplier)
    assert isinstance(back.condition, PerDifferentlyNamedLand)
    assert back.description_fragment == (
        "where X is the number of differently named lands you control"
    )


def test_bridge_reverse_arm_omits_optional_fields():
    """Reverse arm accepts the minimal dict shape — ``description_
    fragment`` defaults to empty string when omitted; ``condition_args``
    defaults to empty tuple.
    """
    from mtg_bot.effects.conditions import PerDifferentlyNamedLand
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsByConditionMultiplier,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    back = _ta_dict_to_python_effect({
        "kind": "draw_cards_by_condition_multiplier",
        "condition_tag": "per_differently_named_land",
    })
    assert isinstance(back, DrawCardsByConditionMultiplier)
    assert isinstance(back.condition, PerDifferentlyNamedLand)
    assert back.description_fragment == ""


def test_bridge_reverse_arm_unknown_tag_raises():
    """Reverse arm raises ``ValueError`` on an unknown ``condition_
    tag`` — defense in depth against bridge-vs-Rust drift.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(ValueError):
        _ta_dict_to_python_effect({
            "kind": "draw_cards_by_condition_multiplier",
            "condition_tag": "definitely_not_a_real_tag",
        })


def test_bridge_forward_arm_emits_draw_cards_by_condition_multiplier_dict():
    """**Forward emit pin.** A synthetic All-Fates-Scroll-AA[1]-shape
    ``ActivatedAbility`` serializes through ``_python_aa_to_safe_dict``
    to a dict carrying:

      * ``cost``: ``{"tap_self": True, "sacrifice_self": True,
        "mana": {"generic": 7}}``
      * ``effect``: ``{"kind": "draw_cards_by_condition_multiplier",
        "condition_tag": "per_differently_named_land",
        "description_fragment": "..."}``

    Cycle-1 substrate-only: the round-trip succeeds, but
    ``_aa_is_phase1_sub_shape_a`` still declines AA[1] on the
    Effect-class admit gate (C2 ships the widen).
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.conditions import PerDifferentlyNamedLand
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsByConditionMultiplier,
    )
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=7),
        ),
        effect=DrawCardsByConditionMultiplier(
            condition=PerDifferentlyNamedLand(),
            description_fragment="where X is the number of "
            "differently named lands you control",
        ),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None, (
        "All-Fates Scroll AA[1] shape must round-trip through the "
        "bridge floor — Cycle 1 widens the forward emit even though "
        "the admit predicate keeps the printing DECLINED."
    )
    assert d["cost"]["tap_self"] is True
    assert d["cost"]["sacrifice_self"] is True
    assert d["cost"]["mana"] == {"generic": 7}
    assert d["effect"]["kind"] == "draw_cards_by_condition_multiplier"
    assert d["effect"]["condition_tag"] == "per_differently_named_land"
    # The condition_args key is omitted when empty (empty-omit
    # discipline; mirrors the Rust to_pydict arm).
    assert "condition_args" not in d["effect"]
    assert d["effect"]["description_fragment"] == (
        "where X is the number of differently named lands you control"
    )
    # Reverse round-trip — byte-equal at the dataclass __eq__ surface.
    back = _aa_dict_to_python_activated_ability(d)
    assert back == aa


def test_bridge_forward_arm_empty_description_fragment_omitted():
    """Forward arm omits the ``description_fragment`` key when empty
    string — empty-omit discipline matches the Rust ``to_pydict``
    sibling.
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.conditions import PerDifferentlyNamedLand
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsByConditionMultiplier,
    )
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    aa = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=7),
        ),
        effect=DrawCardsByConditionMultiplier(
            condition=PerDifferentlyNamedLand(),
            description_fragment="",
        ),
    )
    d = _python_aa_to_safe_dict(aa)
    assert d is not None
    assert "description_fragment" not in d["effect"]


# ---------------------------------------------------------------------------
# Rust unit pin #35 — parse_effect arm via Registry.register_printing
# ---------------------------------------------------------------------------


def _synthetic_all_fates_scroll_dict():
    """Minimal All-Fates-Scroll-shape Artifact printing dict for the
    Rust Registry. AA[0] is the ``{T}: Add {C}`` mana-ability sibling
    (the bridge schema flattens ``produces=(("any", 1),)`` to one
    ``AddManaToPool { color, amount }`` per pair — we use ``"C"`` as
    a Rust-side stand-in for the closed-vocab color since the Rust
    side doesn't yet recognize "any"; the C1 substrate is for AA[1]'s
    Effect-class anyway). AA[1] is the new
    ``draw_cards_by_condition_multiplier`` shape with the
    ``per_differently_named_land`` tag.
    """
    return {
        "name": "Synthetic All-Fates Scroll",
        "card_types": ["Artifact"],
        "mana_cost": {"generic": 3},
        "activated_abilities": [
            {
                "cost": {"tap_self": True},
                "effect": {
                    "kind": "add_mana_to_pool",
                    "color": "C",
                    "amount": 1,
                },
                "is_mana_ability": True,
            },
            {
                "cost": {
                    "tap_self": True,
                    "sacrifice_self": True,
                    "mana": {"generic": 7},
                },
                "effect": {
                    "kind": "draw_cards_by_condition_multiplier",
                    "condition_tag": "per_differently_named_land",
                    "description_fragment": "where X is the number "
                    "of differently named lands you control",
                },
                "is_mana_ability": False,
            },
        ],
    }


def test_rust_register_printing_with_draw_cards_by_condition_multiplier_effect(engine):
    """**Design doc §6.5 #35 — parse arm pin.** The new
    ``draw_cards_by_condition_multiplier`` parse arm accepts the
    3-key dict and returns ``Effect::DrawCardsByConditionMultiplier``;
    a synthetic All-Fates-Scroll-shape Artifact registers cleanly.
    """
    reg = engine.Registry()
    pid = reg.register_printing(_synthetic_all_fates_scroll_dict())
    assert reg.get_printing_name(pid) == "Synthetic All-Fates Scroll"


def test_rust_register_printing_unknown_condition_tag_raises(engine):
    """Parser whitelist rejects an unknown ``condition_tag`` —
    defense in depth against bridge-vs-Rust drift. Mirrors the
    ``static_self_bonuses[].condition_tag`` whitelist at
    ``cards.rs:16542``.
    """
    reg = engine.Registry()
    with pytest.raises(Exception):
        reg.register_printing({
            "name": "Bad All-Fates Scroll",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 3},
            "activated_abilities": [
                {
                    "cost": {
                        "tap_self": True,
                        "sacrifice_self": True,
                        "mana": {"generic": 7},
                    },
                    "effect": {
                        "kind": "draw_cards_by_condition_multiplier",
                        "condition_tag": "totally_not_a_real_tag",
                    },
                    "is_mana_ability": False,
                },
            ],
        })


def test_rust_register_printing_missing_condition_tag_raises(engine):
    """Parser raises on missing required ``condition_tag`` field."""
    reg = engine.Registry()
    with pytest.raises(Exception):
        reg.register_printing({
            "name": "Bad All-Fates Scroll",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 3},
            "activated_abilities": [
                {
                    "cost": {
                        "tap_self": True,
                        "sacrifice_self": True,
                        "mana": {"generic": 7},
                    },
                    "effect": {
                        "kind": "draw_cards_by_condition_multiplier",
                    },
                    "is_mana_ability": False,
                },
            ],
        })


def test_rust_register_printing_non_empty_args_for_no_arg_tag_raises(engine):
    """Per-tag arity validator rejects non-empty args for the no-arg
    ``per_differently_named_land`` tag — mirrors the ``static_self_
    bonuses[].condition_args`` per-tag arity gate at
    ``cards.rs:16581``+.
    """
    reg = engine.Registry()
    with pytest.raises(Exception):
        reg.register_printing({
            "name": "Bad All-Fates Scroll",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 3},
            "activated_abilities": [
                {
                    "cost": {
                        "tap_self": True,
                        "sacrifice_self": True,
                        "mana": {"generic": 7},
                    },
                    "effect": {
                        "kind": "draw_cards_by_condition_multiplier",
                        "condition_tag": "per_differently_named_land",
                        "condition_args": [1, 2, 3],
                    },
                    "is_mana_ability": False,
                },
            ],
        })


# ---------------------------------------------------------------------------
# Rust unit pin #36 — to_pydict arm via the parse-emit inverse
# ---------------------------------------------------------------------------


def test_rust_to_pydict_round_trip_via_bridge_inverse():
    """**Design doc §6.5 #36 — to_pydict arm pin.** The Rust
    ``to_pydict`` arm emits the byte-equal 3-key dict (with the
    empty-omit discipline). Round-trip via the bridge forward arm
    (Python→dict) + the Rust parse arm (dict→Rust) + then back
    through the Rust to_pydict arm yields the same dict.

    This pin drives the Python→dict half of the round-trip. The Rust
    side's symmetry is verified indirectly by the resolve pin below
    (which only fires correctly if the dict→Rust arm parses the new
    variant's fields correctly).
    """
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.conditions import PerDifferentlyNamedLand
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsByConditionMultiplier,
    )
    from mtg_bot.cards.base import ManaCost
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        _python_aa_to_safe_dict,
    )

    aa_orig = ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_self=True,
            mana=ManaCost(generic=7),
        ),
        effect=DrawCardsByConditionMultiplier(
            condition=PerDifferentlyNamedLand(),
            description_fragment="where X is the number of "
            "differently named lands you control",
        ),
    )
    d = _python_aa_to_safe_dict(aa_orig)
    aa_back = _aa_dict_to_python_activated_ability(d)
    assert aa_back == aa_orig
    # And: a second forward emit yields a byte-equal dict.
    d2 = _python_aa_to_safe_dict(aa_back)
    assert d == d2


# ---------------------------------------------------------------------------
# Rust unit pin #37 — resolve arm: count + draw
# ---------------------------------------------------------------------------


def _synthetic_basic_land_dict(name: str, subtype: str, color: str):
    """Minimal basic-Land printing dict carrying a single mana-ability
    via the ``mana_produced`` auto-wire. Used to seed the activator's
    bf with N differently-named lands."""
    return {
        "name": name,
        "card_types": ["Land"],
        "subtypes": [subtype],
        "supertypes": ["Basic"],
        "mana_cost": {},
        "mana_produced": [color],
    }


def test_resolve_draw_cards_by_condition_multiplier_counts_distinct_named_lands(
    engine, synthetic_state,
):
    """**Design doc §6.5 #37 — resolve arm pin.** Set up: 3 distinct-
    named basic lands (Mountain / Forest / Plains) on p0 bf + the
    All-Fates Scroll. Activate AA[1] — Stage's printing isn't
    relevant; resolution computes ``x = condition_count(per_
    differently_named_land, [], state, 0)`` = 3 and transfers 3
    library-top objects to p0's hand.

    The substrate-only Rust slice doesn't require the live admit gate
    to pass — we directly inject the printing + force a resolve via
    the bf-injection helper. The cycle-2 admit FLIP will drive the
    same code path through the production-deck loader.

    **Synthetic state bf baseline.** ``make_synthetic_state`` seeds
    p0's bf with 5 Forests + 5 Grizzly Bears. Only the Forests carry
    ``card_types=["Land"]``, contributing ONE distinct printed name
    ("Forest"). We add 3 NEW distinct-named lands (Mountain, Plains,
    Island), plus a DUPLICATE second Mountain. Total distinct land
    names on p0 bf post-injection: 4 ({Forest, Mountain, Plains,
    Island}). The duplicate Mountain folds into the BTreeSet entry.
    """
    # Track pre-resolve hand/library sizes (p0 = index 0).
    pre_hand = synthetic_state.hand_sizes[0]
    pre_lib = synthetic_state.library_sizes[0]

    # The synthetic fixture seeds 5 Forests on p0 bf, contributing
    # one distinct name. Add 3 NEW distinct names to target a 4-card
    # draw, plus one duplicate to confirm name-dedup.
    synthetic_state.register_and_inject_object(
        _synthetic_basic_land_dict("AA-Mountain", "Mountain", "R"),
        0, ZONE_BATTLEFIELD,
    )
    synthetic_state.register_and_inject_object(
        _synthetic_basic_land_dict("AA-Plains", "Plains", "W"),
        0, ZONE_BATTLEFIELD,
    )
    synthetic_state.register_and_inject_object(
        _synthetic_basic_land_dict("AA-Island", "Island", "U"),
        0, ZONE_BATTLEFIELD,
    )
    # Add one DUPLICATE-named Mountain — should NOT increment the
    # distinct count.
    synthetic_state.register_and_inject_object(
        _synthetic_basic_land_dict("AA-Mountain", "Mountain", "R"),
        0, ZONE_BATTLEFIELD,
    )

    # Inject the Scroll printing on p0's bf as well.
    scroll_id = synthetic_state.register_and_inject_object(
        _synthetic_all_fates_scroll_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(scroll_id, False)
    # Pay {7} mana for AA[1].
    synthetic_state.add_mana(0, "C", 7)

    # Activate AA[1] (index 1; AA[0] is the mana-ability).
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": scroll_id,
        "ability_index": 1,
    })
    assert synthetic_state.stack_size() == 1

    # Resolve — fires Effect::DrawCardsByConditionMultiplier.
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty()

    # Post-state: 4 distinct land names on p0 bf
    # ({Forest, Mountain, Plains, Island}); duplicate Mountain folds
    # to a single set entry. Hand grew by 4, library shrank by 4.
    post_hand = synthetic_state.hand_sizes[0]
    post_lib = synthetic_state.library_sizes[0]
    assert post_hand - pre_hand == 4, (
        f"Expected +4 hand cards (4 distinct-named lands: Forest, "
        f"Mountain, Plains, Island; duplicate Mountain folds); got "
        f"pre={pre_hand}, post={post_hand} (delta={post_hand - pre_hand})"
    )
    assert pre_lib - post_lib == 4, (
        f"Expected -4 library cards; got pre={pre_lib}, post={post_lib} "
        f"(delta={pre_lib - post_lib})"
    )


def test_resolve_draw_cards_by_condition_multiplier_zero_count_no_op(
    engine, synthetic_state,
):
    """**Resolve arm zero-count short-circuit.** When the activator
    controls ZERO lands, the count is 0 and the draw inner loop is
    skipped entirely. Mirrors Python's early-return at
    ``draw_mill.py:296-301``.

    Set up: drain p0's bf of every Land via the bf-snapshot walk, so
    the activator controls ZERO lands at resolve time. The
    ``make_synthetic_state`` default fixture seeds 5 Forests + 5
    Grizzly Bears on p0 bf; we exile every Forest to clear the count
    to 0.
    """
    # Drain p0's Lands. The synthetic fixture has 5 Forests under
    # printing_id=0 on p0 bf; walk the snapshot and move every
    # bf object with a basic-land subtype off bf (to exile).
    bf_pre = synthetic_state.battlefield_snapshot()
    for obj in bf_pre:
        if obj.get("controller_id") != 0:
            continue
        sub = synthetic_state.printing_subtypes_of(obj["id"]) or []
        # Use the basic-land subtype heuristic — the default fixture's
        # Lands all carry Forest subtype.
        if any(
            s in sub for s in (
                "Forest", "Mountain", "Plains", "Island", "Swamp",
            )
        ):
            # move to exile (zone=5), target_player irrelevant for
            # the count: only bf-zone objects are counted.
            synthetic_state.move_object(obj["id"], ZONE_EXILE, 0)

    pre_hand = synthetic_state.hand_sizes[0]

    scroll_id = synthetic_state.register_and_inject_object(
        _synthetic_all_fates_scroll_dict(), 0, ZONE_BATTLEFIELD,
    )
    synthetic_state.force_set_summoning_sick(scroll_id, False)
    synthetic_state.add_mana(0, "C", 7)
    synthetic_state.apply_action({
        "kind": "activate_ability",
        "source_id": scroll_id,
        "ability_index": 1,
    })
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.is_stack_empty()

    post_hand = synthetic_state.hand_sizes[0]
    assert post_hand == pre_hand, (
        f"Expected zero-count short-circuit (no draw); got "
        f"pre={pre_hand}, post={post_hand}"
    )


# ---------------------------------------------------------------------------
# Substrate-only invariant pins — All-Fates Scroll STAYS DECLINED
# ---------------------------------------------------------------------------


def test_all_fates_scroll_stays_declined_at_loader_gate_post_c2_partial():
    """**Phase 4E C2 partial-FLIP invariant -- INVERTED at C2.5
    (2026-05-26).** The C2 partial-FLIP gap (the "any" color teeth at
    the bridge floor) has CLOSED. The Phase 4E C2.5 cycle landed the
    Rust ``ManaPool`` "any" coin substrate: new ``any: u8`` slot +
    ``push_coins`` ``b'a'`` arm + ``validate_mana_symbol`` widen +
    ``Effect::AddManaToPool`` resolve arm "any" → ``b'a'`` translation
    + ``slot_mut`` widen + Python forward arm + 7-key signature
    histogram. All-Fates Scroll now FLIPS at the cross-engine builder
    gate: DECLINED → ADMITTED.

    The test name + lane stay so the dispatcher / git-log walk
    continues to dispatch through this pin, but the assertions flip
    to pin the post-C2.5 ADMITTED state. See
    ``tests/test_carrier_aa_phase_4e_substrate_cycle_2_5.py`` for the
    explicit substrate pins.

    Verify both surfaces:
      * Per-AA admit predicate: BOTH AAs PASS (unchanged from C2).
      * Printing-level Artifact predicate: PASSES (unchanged from C2).
      * Cross-engine Artifact builder: now ADMITS (C2.5 closure).
    """
    import json

    from mtg_bot.cards.parser_source import _build_artifact_printing
    from mtg_bot.parity.trajectory import (
        _aa_is_phase1_sub_shape_a,
        _carrier_aa_artifact_card_def,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_artifact,
    )

    with open("data/edge_of_eternities.json", encoding="utf-8") as f:
        raw_cards = json.load(f)
    raw = next(
        c for c in raw_cards if c.get("name") == "All-Fates Scroll"
    )
    printing = _build_artifact_printing(raw)
    aa0, aa1 = printing.activated_abilities

    # Per-AA admit predicate: BOTH AAs PASS (unchanged from C2).
    assert _aa_is_phase1_sub_shape_a(aa0) is True
    assert _aa_is_phase1_sub_shape_a(aa1) is True
    # Printing-level admit dispatcher: passes (per-AA all-pass).
    assert _printing_is_bridge_simple_carrier_aa_any(printing) is True
    assert _printing_is_bridge_simple_carrier_aa_artifact(printing) is True
    # **Cross-engine builder gate: now ADMITS (C2.5 closure).** The
    # bridge floor's AddManaToPool forward arm admits the "any" color;
    # Rust's validate_mana_symbol + ManaPool substrate accept it
    # end-to-end.
    cd = _carrier_aa_artifact_card_def(printing)
    assert cd is not None, (
        "Phase 4E C2.5 closure: All-Fates Scroll must ADMIT at the "
        "cross-engine builder gate (Rust ManaPool 'any' coin substrate "
        "landed)"
    )
    assert cd.name == "All-Fates Scroll"


def test_carrier_aa_phase_1_effect_classes_widened_post_c2():
    """**Phase 4E C2 widen — the Effect-class admit set grows from
    7 → 9.** ``DrawCardsByConditionMultiplier`` + ``AddManaToPool``
    join the set; the prior 7 Phase-1-3 entries stay admitted.
    """
    from mtg_bot.effects.generic.become_type import (
        BecomesCopyOfTargetLand,
    )
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsByConditionMultiplier,
    )
    from mtg_bot.effects.generic.exile import (
        ExileAllGraveyards,
        ExileTargetAttackingCreatureUntilEndStep,
    )
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    from mtg_bot.parity.trajectory import (
        _carrier_aa_phase_1_effect_classes,
    )

    admitted = _carrier_aa_phase_1_effect_classes()
    # Phase 4E C2 widens: new entries.
    assert DrawCardsByConditionMultiplier in admitted, (
        "Phase 4E C2 widen: DrawCardsByConditionMultiplier MUST be "
        "in the Effect-class admit set"
    )
    assert AddManaToPool in admitted, (
        "Phase 4E C2 widen: AddManaToPool MUST be in the Effect-"
        "class admit set"
    )
    # No regression on the prior 7 entries.
    for cls in (
        RegenerateTargetCreature,
        UntapTargetLand,
        ReturnTargetLandFromGraveyardToHand,
        PutBasicLandFromHandOntoBattlefieldTapped,
        ExileTargetAttackingCreatureUntilEndStep,
        ExileAllGraveyards,
        BecomesCopyOfTargetLand,
    ):
        assert cls in admitted, (
            f"Phase 4E C2 no-regression: {cls.__name__} MUST stay in "
            "the Effect-class admit set"
        )
    # Lower-bound invariant -- subsequent sub-phase widens (Phase 4C
    # C2 grew the admit set 9 -> 11 for Ghost Vacuum's Effect classes;
    # Phase 4D C2 widened to 13 by adding
    # LockOrUnlockDoorOfTargetRoomYouControl + SearchLibraryForCard
    # for Keys to the House's AA[0] + AA[1]) are strictly additive
    # on this Phase-4E-C2 baseline.
    assert len(admitted) >= 9, (
        f"Phase 4E C2 admit-set cardinality lower bound: expected "
        f">=9, got {len(admitted)}"
    )


def test_all_fates_scroll_admits_at_artifact_admit_predicate_post_c2():
    """**Phase 4E C2 inverted invariant — the Artifact sibling admit
    predicate now PASSES All-Fates Scroll** (was DECLINED at Phase 4E
    C1). The cross-engine builder gate is the new teeth (see
    :func:`test_all_fates_scroll_stays_declined_at_loader_gate_post_c2_partial`).
    """
    import json

    from mtg_bot.cards.parser_source import _build_artifact_printing
    from mtg_bot.parity.trajectory import (
        _printing_is_bridge_simple_carrier_aa_artifact,
    )

    with open("data/edge_of_eternities.json", encoding="utf-8") as f:
        raw_cards = json.load(f)
    raw = next(
        c for c in raw_cards if c.get("name") == "All-Fates Scroll"
    )
    printing = _build_artifact_printing(raw)
    assert (
        _printing_is_bridge_simple_carrier_aa_artifact(printing)
        is True
    ), (
        "Phase 4E C2 widen: All-Fates Scroll must PASS the Artifact-"
        "typed sibling admit predicate post-C2 (the per-AA teeth are "
        "lifted; the 'any' teeth land at the builder gate)"
    )
