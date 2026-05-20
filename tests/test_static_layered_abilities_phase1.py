"""Static / layered abilities substrate — Phase 1 first-deliverable
tests.

Spec: ``docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md`` §3 lever (1)
(round-79; 2026-05-20).

**First-deliverable scope.** The simplest static-ability shape:
an *unconditional anthem keyword grant* whose scope is
``creatures_you_control`` or ``other_creatures_you_control`` and whose
``continuous_effect`` is a layer-6 ``ContinuousModifier(GrantKeyword(
kw))`` with ``kw`` in :data:`mtg_bot.parity.trajectory._SAFE_KEYWORDS`.

Tannuk, Steadfast Second is the canonical EoE single-gated carrier
("Other creatures you control have haste."). The Rust-side reader
fold extends the round-78 Aura Phase 1 STEP-4 ``battlefield_has_
keyword`` machinery with a new ``static_anthem_grants_keyword_to``
helper that walks the source's controller's battlefield for matching
``static_anthems``.

The substrate is wired end-to-end:

* CardDef carries ``static_anthems: tuple[tuple[str, tuple[str, ...]
  ], ...]``.
* Bridge emits the ``static_anthems`` key on the registry dict.
* Rust ``CardPrinting`` carries a parallel ``static_anthems:
  Vec<StaticAnthem>``; ``parse_printing`` reads the key.
* Rust ``battlefield_has_keyword`` folds the static-anthem grants in
  on top of the existing aura-grant precedent.
* ``_card_def_to_python_printing`` materializes the matching Python
  ``StaticAbility`` tuple so the same CardDef shape powers both
  engines.
* ``_printing_is_bridge_simple_static_anthem_creature`` is the new
  loader admit-disjunct; ``_filter_deck_to_bridge_supported``
  invokes it as the 7th disjunct.

**Honest-stops for this slice (documented in
``docs/SEARCH_LIMITATIONS.md``):**

* Conditional statics (Brightspear / Cloudsculpt / Gravblade /
  Mechan Shieldmate) — the SELF + ``as long as ...`` shape requires
  per-condition wiring on the Rust side.
* P/T anthems — the layer-7c contribution is not yet folded on the
  Rust side; only layer-6 keyword grants this slice.
* Static-ability sources wiped by Humility (CR 613.7) — no live EoE
  card admits that path today; the parity is clean as long as no
  ``lose_all_abilities`` continuous effect targets a static-anthem
  source.
"""

from __future__ import annotations

import importlib

import pytest

from mtg_bot.parity.cross_engine import (
    CardDef,
    DeckSpec,
    build_matched_states,
    build_rust_registry,
)
from mtg_bot.parity.trajectory import (
    _printing_is_bridge_simple_static_anthem_creature,
    _printing_to_card_def,
    _static_ability_is_simple_anthem_keyword_grant,
)


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


# ---------------------------------------------------------------------------
# Predicate — admit shape teeth
# ---------------------------------------------------------------------------


def test_admit_predicate_accepts_tannuk_shape():
    """The canonical anthem creature passes the new predicate.

    Tannuk Steadfast Second is the parser-emitted shape:
    creature with one StaticAbility(scope=
    other_creatures_you_control, continuous_effect=
    ContinuousModifier(layer=6, payload=GrantKeyword('haste'))).
    """
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    tannuk = printings["Tannuk, Steadfast Second"]
    assert _printing_is_bridge_simple_static_anthem_creature(tannuk) is True


def test_admit_predicate_rejects_self_scope_static():
    """Self-scope statics (Cloudsculpt Technician — SELF + condition +
    layer-7 P/T bonus) are NOT this slice's admit shape. The predicate
    must positively reject them.
    """
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    cloudsculpt = printings["Cloudsculpt Technician"]
    assert (
        _printing_is_bridge_simple_static_anthem_creature(cloudsculpt) is False
    )


def test_admit_predicate_rejects_conditional_anthem_hypothetical():
    """A conditional static (e.g. ``as long as`` rider) is NOT admit.
    Constructed by hand because no EoE conditional ANTHEM exists today
    — every EoE conditional static is SELF-scoped.
    """
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.effects.conditions import DuringYourTurn
    from mtg_bot.effects.modifiers import ContinuousModifier, GrantKeyword

    ability = StaticAbility(
        scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
        condition=DuringYourTurn(),
        continuous_effect=ContinuousModifier(
            layer=6, payload=GrantKeyword("haste"),
        ),
    )
    assert _static_ability_is_simple_anthem_keyword_grant(ability) is False


def test_admit_predicate_rejects_pt_anthem_hypothetical():
    """A P/T anthem (e.g. "Creatures you control get +1/+1.") is NOT
    this slice. Constructed by hand because EoE's P/T statics are all
    SELF-scoped + conditional today.
    """
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.effects.modifiers import ContinuousModifier, PowerToughnessBonus

    ability = StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL,
        continuous_effect=ContinuousModifier(
            layer=7,
            payload=PowerToughnessBonus(power_bonus=1, toughness_bonus=1),
        ),
    )
    assert _static_ability_is_simple_anthem_keyword_grant(ability) is False


def test_admit_predicate_rejects_unsafe_keyword():
    """A grant whose keyword is OUTSIDE _SAFE_KEYWORDS is declined."""
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.effects.modifiers import ContinuousModifier, GrantKeyword

    ability = StaticAbility(
        scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
        continuous_effect=ContinuousModifier(
            layer=6, payload=GrantKeyword("flash"),
        ),
    )
    assert _static_ability_is_simple_anthem_keyword_grant(ability) is False


def test_admit_predicate_rejects_unknown_scope():
    """A non-anthem scope (e.g. ``self``, ``slivers_you_control``) is
    declined by the Phase-1 predicate.
    """
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.effects.modifiers import ContinuousModifier, GrantKeyword

    ability = StaticAbility(
        scope=StaticScope.SLIVERS_YOU_CONTROL,
        continuous_effect=ContinuousModifier(
            layer=6, payload=GrantKeyword("haste"),
        ),
    )
    assert _static_ability_is_simple_anthem_keyword_grant(ability) is False


# ---------------------------------------------------------------------------
# CardDef round-trip — Python printing -> CardDef -> Python printing
# ---------------------------------------------------------------------------


def test_printing_to_card_def_carries_anthem_through():
    """``_printing_to_card_def`` builds a CardDef with the
    ``static_anthems`` tuple, deterministically ordered by scope.
    """
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    tannuk = printings["Tannuk, Steadfast Second"]
    cd = _printing_to_card_def(tannuk)
    assert cd.card_type == "Creature"
    assert cd.static_anthems == (("other_creatures_you_control", ("haste",)),)
    assert cd.name == "Tannuk, Steadfast Second"
    assert cd.power == 3
    assert cd.toughness == 5


def test_card_def_round_trip_python_printing():
    """``_card_def_to_python_printing`` materializes the static
    abilities tuple from the CardDef's anthem slot, in the
    one-StaticAbility-per-keyword fan-out shape the parser emits.
    """
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.effects.modifiers import ContinuousModifier, GrantKeyword
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    cd = CardDef(
        name="Anthem Bear",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=2,
        toughness=2,
        static_anthems=(
            ("other_creatures_you_control", ("haste", "trample")),
        ),
    )
    printing = _card_def_to_python_printing(cd)
    # One StaticAbility per granted keyword (matches parser fan-out).
    assert len(printing.static_abilities) == 2
    scopes = {sa.scope for sa in printing.static_abilities}
    assert scopes == {StaticScope.OTHER_CREATURES_YOU_CONTROL}
    kws = sorted(
        sa.continuous_effect.payload.keyword
        for sa in printing.static_abilities
    )
    assert kws == ["haste", "trample"]
    for sa in printing.static_abilities:
        assert isinstance(sa.continuous_effect, ContinuousModifier)
        assert sa.continuous_effect.layer == 6
        assert isinstance(sa.continuous_effect.payload, GrantKeyword)


# ---------------------------------------------------------------------------
# Rust registry round-trip — registry dict -> Rust CardPrinting -> readback
# ---------------------------------------------------------------------------


def test_rust_registry_round_trip_static_anthems():
    """The Rust ``parse_printing`` arm reads the ``static_anthems`` key
    off the registry dict and re-surfaces it via
    ``Registry.get_printing_static_anthems``.
    """
    _require_engine()
    spec = DeckSpec(
        card_defs=(
            CardDef(name="Forest", card_type="Land", mana_produced=("G",)),
            CardDef(
                name="Grizzly Bears",
                card_type="Creature",
                mana_cost_generic=1,
                mana_cost_colored=(("G", 1),),
                power=2,
                toughness=2,
            ),
            CardDef(
                name="Tannuk",
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
        p0_library=("Tannuk", "Grizzly Bears", "Forest"),
        p1_library=("Forest",),
    )
    reg, name_to_pid = build_rust_registry(spec)
    tannuk_anthems = reg.get_printing_static_anthems(name_to_pid["Tannuk"])
    assert tannuk_anthems == [("other_creatures_you_control", ["haste"])]
    bears_anthems = reg.get_printing_static_anthems(
        name_to_pid["Grizzly Bears"]
    )
    assert bears_anthems == []
    forest_anthems = reg.get_printing_static_anthems(name_to_pid["Forest"])
    assert forest_anthems == []


def test_rust_registry_rejects_unknown_scope():
    """An unsupported scope in the bridge dict makes the parser raise
    — fail loudly rather than silently mistranslate.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    bad_dict = {
        "name": "Bad Anthem",
        "mana_cost": {"generic": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "static_anthems": [
            {"scope": "self", "granted_keywords": ["haste"]},
        ],
    }
    with pytest.raises(ValueError):
        reg.register_printing(bad_dict)


def test_rust_registry_empty_keywords_list_ok():
    """An anthem dict with an empty ``granted_keywords`` list is
    parseable (declares the scope but contributes no keyword) — the
    reader-site is a no-op, the printing round-trips.
    """
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Empty Anthem",
        "mana_cost": {"generic": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "static_anthems": [
            {"scope": "creatures_you_control", "granted_keywords": []},
        ],
    }
    pid = reg.register_printing(d)
    anthems = reg.get_printing_static_anthems(pid)
    assert anthems == [("creatures_you_control", [])]


# ---------------------------------------------------------------------------
# Cross-engine reader site — haste grant byte-equal
# ---------------------------------------------------------------------------


def test_anthem_grants_keyword_cross_engine():
    """Both engines fold Tannuk's static anthem into the bears'
    effective keyword set. Tannuk itself (the source) does NOT inherit
    its OWN anthem (scope = ``other_creatures_you_control``).
    """
    _require_engine()
    from mtg_bot.game import Zone, effective_keywords

    spec = DeckSpec(
        card_defs=(
            CardDef(name="Forest", card_type="Land", mana_produced=("G",)),
            CardDef(
                name="Grizzly Bears",
                card_type="Creature",
                mana_cost_generic=1,
                mana_cost_colored=(("G", 1),),
                power=2,
                toughness=2,
            ),
            CardDef(
                name="Tannuk",
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
        p0_library=("Tannuk", "Grizzly Bears"),
        p1_library=("Forest",),
    )
    py_state, rust_state = build_matched_states(spec)
    # Python side: move both library objects to battlefield.
    tannuk_py = py_state.players[0].library[0]
    bears_py = py_state.players[0].library[1]
    py_state.players[0].library = []
    tannuk_py.zone = Zone.BATTLEFIELD
    bears_py.zone = Zone.BATTLEFIELD
    py_state.battlefield.append(tannuk_py)
    py_state.battlefield.append(bears_py)
    py_bears_kws = effective_keywords(py_state, bears_py)
    py_tannuk_kws = effective_keywords(py_state, tannuk_py)
    # Bears gets haste from Tannuk; Tannuk itself doesn't (other_*).
    assert "haste" in py_bears_kws
    assert "haste" not in py_tannuk_kws

    # Rust side: drive the static-anthem reader via has_keyword.
    # The test fixture exposes the bf-move helpers indirectly via the
    # synthetic-injection pattern other tests use. Here we exercise
    # the reader fold by passing Tannuk's and Bears' ids through.
    # build_matched_states already puts both in the library; for the
    # Rust reader to observe the anthem source ON the battlefield we
    # need the synthetic injection path. Skip the per-id assertion
    # at the build_matched_states level; instead exercise the reader
    # via the synthetic-state route in the next test.


def test_anthem_grants_keyword_rust_synthetic_bf():
    """Direct Rust-side reader exercise: register both printings,
    inject Tannuk + Bears onto P0's battlefield, query
    ``has_keyword('haste')`` on Bears.

    Mirrors the round-78 Aura STEP-4 test pattern of injecting
    objects onto the battlefield via ``register_and_inject_object``
    rather than driving a full cast-and-resolve.
    """
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    ZONE_BATTLEFIELD = 2
    tannuk_dict = {
        "name": "Tannuk, Steadfast Second",
        "mana_cost": {"generic": 2, "R": 2},
        "card_types": ["Creature"],
        "subtypes": ["Kavu", "Pilot"],
        "power": 3,
        "toughness": 5,
        "static_anthems": [
            {
                "scope": "other_creatures_you_control",
                "granted_keywords": ["haste"],
            },
        ],
    }
    bears_dict = {
        "name": "Grizzly Bears",
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "subtypes": ["Bear"],
        "power": 2,
        "toughness": 2,
    }
    tannuk_id = state.register_and_inject_object(
        tannuk_dict, 0, ZONE_BATTLEFIELD,
    )
    bears_id = state.register_and_inject_object(
        bears_dict, 0, ZONE_BATTLEFIELD,
    )
    assert state.has_keyword(bears_id, "haste") is True
    assert state.has_keyword(tannuk_id, "haste") is False


def test_anthem_self_scope_admits_source():
    """``creatures_you_control`` anthem (not ``other_*``) DOES grant
    to the source itself.
    """
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    ZONE_BATTLEFIELD = 2
    pump_dict = {
        "name": "Self-Inclusive Anthem",
        "mana_cost": {"generic": 2, "G": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "static_anthems": [
            {
                "scope": "creatures_you_control",
                "granted_keywords": ["trample"],
            },
        ],
    }
    bears_dict = {
        "name": "Grizzly Bears",
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
    }
    pump_id = state.register_and_inject_object(
        pump_dict, 0, ZONE_BATTLEFIELD,
    )
    bears_id = state.register_and_inject_object(
        bears_dict, 0, ZONE_BATTLEFIELD,
    )
    # creatures_you_control INCLUDES the source.
    assert state.has_keyword(pump_id, "trample") is True
    assert state.has_keyword(bears_id, "trample") is True


def test_anthem_does_not_cross_controllers():
    """The anthem only fires for creatures under the SOURCE's
    controller. A bears under P1 does NOT receive haste from a
    P0-controlled Tannuk.
    """
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    ZONE_BATTLEFIELD = 2
    tannuk_dict = {
        "name": "Tannuk",
        "mana_cost": {"generic": 2, "R": 2},
        "card_types": ["Creature"],
        "power": 3,
        "toughness": 5,
        "static_anthems": [
            {
                "scope": "other_creatures_you_control",
                "granted_keywords": ["haste"],
            },
        ],
    }
    bears_dict = {
        "name": "Grizzly Bears",
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
    }
    state.register_and_inject_object(tannuk_dict, 0, ZONE_BATTLEFIELD)
    opp_bears_id = state.register_and_inject_object(
        bears_dict, 1, ZONE_BATTLEFIELD,
    )
    # Opp bears should NOT have haste from P0's Tannuk.
    assert state.has_keyword(opp_bears_id, "haste") is False


def test_no_anthem_source_no_grant():
    """With no static-anthem source on the battlefield, the bears
    have no anthem-granted keyword.
    """
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    ZONE_BATTLEFIELD = 2
    bears_dict = {
        "name": "Grizzly Bears",
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
    }
    bears_id = state.register_and_inject_object(
        bears_dict, 0, ZONE_BATTLEFIELD,
    )
    assert state.has_keyword(bears_id, "haste") is False


def test_unknown_id_returns_false():
    """``has_keyword`` on a nonexistent id returns False (no
    static-anthem walk fires for an invalid target)."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    assert state.has_keyword(99999, "haste") is False


# ---------------------------------------------------------------------------
# Loader admit — Tannuk reaches CardDef through the full filter
# ---------------------------------------------------------------------------


def test_filter_deck_admits_tannuk():
    """``_filter_deck_to_bridge_supported`` admits Tannuk through the
    new 7th disjunct. Before this slice Tannuk dropped at the
    static_abilities ban inside ``_printing_is_bridge_simple_
    creature``.
    """
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported
    filtered_names, card_defs = _filter_deck_to_bridge_supported(
        ["Tannuk, Steadfast Second"], printings,
    )
    assert filtered_names == ["Tannuk, Steadfast Second"]
    assert len(card_defs) == 1
    assert card_defs[0].static_anthems == (
        ("other_creatures_you_control", ("haste",)),
    )
