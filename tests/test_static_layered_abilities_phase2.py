"""Static / layered abilities substrate — Phase 2 tests.

Spec: ``docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md`` §3 lever (1)
(round-80; 2026-05-20). Phase 1 (round-79) shipped the anthem keyword-
grant sub-shape and closed Tannuk Steadfast Second; Phase 2 closes
Frenzied Baloth — the canonical EoE single-gated carrier of
``grants_creature_spells_uncounterable``.

Phase 2 substrate scope:

* CardDef carries ``spell_is_uncounterable: bool`` and
  ``grants_creature_spells_uncounterable: bool``.
* Bridge emits both as top-level registry-dict bools (omitted when
  False — back-compat).
* Rust ``CardPrinting`` carries parallel ``spell_is_uncounterable: bool``
  and ``grants_creature_spells_uncounterable: bool``.
* Rust ``Effect::CounterTargetSpell`` resolve arm + the round-7
  ``counter_spell`` primitive both gate on the two flags. CR 101.2
  ("an uncounterable spell can't be countered") — both gates skip the
  uncounterable target; if no admissible target remains, silent fizzle.
* Python materialization appends a sentinel
  ``StaticAbility(scope="self", grants_creature_spells_uncounterable=
  True)`` to ``CardPrinting.static_abilities`` when the CardDef flag is
  True — matches the parser-emitted shape and feeds Python's
  ``CounterTargetSpell._is_uncounterable`` walk.
* New loader admit predicate
  ``_printing_is_bridge_simple_uncounterable_creature`` — the 8th
  disjunct of ``_filter_deck_to_bridge_supported``.

**Honest-stops carried forward to a later slice.** Six of the original
seven Phase-1 honest-stops remain blocked: Brightspear / Cloudsculpt /
Gravblade / Mechan Shieldmate / Rampaging Soulrager / Wildfire
Wickerfolk — each needs per-Condition Rust ports + a SELF-scope
reader-site walk for layer-7c P/T or layer-6 keyword grants. The
Phase-2 uncounterable substrate is a separate sub-shape (no Condition
substrate, no continuous_effect on the static).
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
    _printing_is_bridge_simple_uncounterable_creature,
    _printing_to_card_def,
    _static_ability_is_simple_uncounterable_grant,
)


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


# ---------------------------------------------------------------------------
# Predicate — admit shape teeth
# ---------------------------------------------------------------------------


def test_admit_predicate_accepts_frenzied_baloth_shape():
    """The canonical uncounterable creature passes the new predicate."""
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    baloth = printings["Frenzied Baloth"]
    assert _printing_is_bridge_simple_uncounterable_creature(baloth) is True


def test_admit_predicate_rejects_plain_vanilla_creature():
    """A bare vanilla creature without either flag falls through this
    predicate (the plain-simple-creature arm handles it)."""
    from mtg_bot.cards.base import CardPrinting, ManaCost

    bears = CardPrinting(
        name="Grizzly Bears",
        mana_cost_str="{1}{G}",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature - Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
    )
    assert _printing_is_bridge_simple_uncounterable_creature(bears) is False


def test_admit_predicate_accepts_cast_flag_only():
    """A creature whose printing carries only ``spell_is_uncounterable``
    (no battlefield-static rider) is admitted. Hypothetical — Frenzied
    Baloth has both, but a future card with only the cast-side flag
    should still admit."""
    from mtg_bot.cards.base import CardPrinting, ManaCost

    p = CardPrinting(
        name="Hypothetical Uncounterable Bear",
        mana_cost_str="{1}{G}",
        mana_cost=ManaCost(generic=1, colored=(("G", 1),)),
        type_line="Creature - Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        spell_is_uncounterable=True,
    )
    assert _printing_is_bridge_simple_uncounterable_creature(p) is True


def test_admit_predicate_rejects_other_static_shape():
    """A SELF-scope static with a continuous_effect (e.g. Cloudsculpt
    Technician's conditional P/T pump) is NOT this slice's admit
    shape. The Phase-2 predicate must positively reject it."""
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    cloudsculpt = printings["Cloudsculpt Technician"]
    assert (
        _printing_is_bridge_simple_uncounterable_creature(cloudsculpt) is False
    )


def test_static_ability_predicate_rejects_continuous_effect():
    """A static-ability with a continuous_effect set is not the
    Phase-2 uncounterable-grant sentinel shape."""
    from mtg_bot.cards.base import StaticAbility
    from mtg_bot.effects.modifiers import ContinuousModifier, GrantKeyword

    ability = StaticAbility(
        scope="self",
        grants_creature_spells_uncounterable=True,
        continuous_effect=ContinuousModifier(
            layer=6, payload=GrantKeyword("haste"),
        ),
    )
    assert _static_ability_is_simple_uncounterable_grant(ability) is False


def test_static_ability_predicate_rejects_condition():
    """A conditional uncounterable grant is honest-stopped to a later
    slice (no Condition substrate this slice)."""
    from mtg_bot.cards.base import StaticAbility
    from mtg_bot.effects.conditions import DuringYourTurn

    ability = StaticAbility(
        scope="self",
        grants_creature_spells_uncounterable=True,
        condition=DuringYourTurn(),
    )
    assert _static_ability_is_simple_uncounterable_grant(ability) is False


def test_static_ability_predicate_rejects_wrong_scope():
    """A non-SELF-scope grant is not the Phase-2 sentinel shape."""
    from mtg_bot.cards.base import StaticAbility, StaticScope

    ability = StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL,
        grants_creature_spells_uncounterable=True,
    )
    assert _static_ability_is_simple_uncounterable_grant(ability) is False


# ---------------------------------------------------------------------------
# CardDef round-trip — Python printing -> CardDef -> Python printing
# ---------------------------------------------------------------------------


def test_printing_to_card_def_carries_uncounterable_flags():
    """``_printing_to_card_def`` builds a CardDef with both flags set."""
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    baloth = printings["Frenzied Baloth"]
    cd = _printing_to_card_def(baloth)
    assert cd.card_type == "Creature"
    assert cd.spell_is_uncounterable is True
    assert cd.grants_creature_spells_uncounterable is True
    assert cd.power == 3
    assert cd.toughness == 2
    # haste + trample (sorted)
    assert cd.keywords == ("haste", "trample")


def test_card_def_round_trip_python_printing():
    """``_card_def_to_python_printing`` materializes both flags."""
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    cd = CardDef(
        name="Frenzied Baloth",
        card_type="Creature",
        mana_cost_generic=0,
        mana_cost_colored=(("G", 2),),
        power=3,
        toughness=2,
        keywords=("haste", "trample"),
        spell_is_uncounterable=True,
        grants_creature_spells_uncounterable=True,
    )
    printing = _card_def_to_python_printing(cd)
    assert printing.spell_is_uncounterable is True
    # One sentinel StaticAbility carrying the grant flag.
    assert len(printing.static_abilities) == 1
    sa = printing.static_abilities[0]
    assert sa.grants_creature_spells_uncounterable is True
    assert sa.continuous_effect is None
    assert sa.condition is None


# ---------------------------------------------------------------------------
# Rust registry round-trip
# ---------------------------------------------------------------------------


def test_rust_registry_round_trip_uncounterable_flags():
    """Rust ``parse_printing`` reads both keys; getters re-surface
    them for round-trip pin tests."""
    _require_engine()
    spec = DeckSpec(
        card_defs=(
            CardDef(name="Forest", card_type="Land", mana_produced=("G",)),
            CardDef(
                name="Frenzied Baloth",
                card_type="Creature",
                mana_cost_generic=0,
                mana_cost_colored=(("G", 2),),
                power=3,
                toughness=2,
                keywords=("haste", "trample"),
                spell_is_uncounterable=True,
                grants_creature_spells_uncounterable=True,
            ),
            CardDef(
                name="Grizzly Bears",
                card_type="Creature",
                mana_cost_generic=1,
                mana_cost_colored=(("G", 1),),
                power=2,
                toughness=2,
            ),
        ),
        p0_library=("Frenzied Baloth", "Grizzly Bears", "Forest"),
        p1_library=("Forest",),
    )
    reg, name_to_pid = build_rust_registry(spec)
    baloth_pid = name_to_pid["Frenzied Baloth"]
    bears_pid = name_to_pid["Grizzly Bears"]
    forest_pid = name_to_pid["Forest"]
    assert reg.get_printing_spell_is_uncounterable(baloth_pid) is True
    assert (
        reg.get_printing_grants_creature_spells_uncounterable(baloth_pid)
        is True
    )
    assert reg.get_printing_spell_is_uncounterable(bears_pid) is False
    assert (
        reg.get_printing_grants_creature_spells_uncounterable(bears_pid)
        is False
    )
    assert reg.get_printing_spell_is_uncounterable(forest_pid) is False
    assert (
        reg.get_printing_grants_creature_spells_uncounterable(forest_pid)
        is False
    )


def test_rust_registry_rejects_non_bool_flag():
    """A non-bool ``spell_is_uncounterable`` raises at parse-time."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    bad = {
        "name": "Bad",
        "mana_cost": {"generic": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "spell_is_uncounterable": "yes",  # wrong type
    }
    with pytest.raises(ValueError):
        reg.register_printing(bad)


def test_rust_registry_empty_default_for_pre_substrate():
    """A pre-substrate registry dict (no flags) defaults both to
    False — back-compat with every existing card."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Vanilla Bear",
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
    }
    pid = reg.register_printing(d)
    assert reg.get_printing_spell_is_uncounterable(pid) is False
    assert (
        reg.get_printing_grants_creature_spells_uncounterable(pid) is False
    )


# ---------------------------------------------------------------------------
# Rust-side counter-spell gate — CR 101.2 enforcement
# ---------------------------------------------------------------------------


def test_rust_counter_spell_skips_uncounterable_spell():
    """A spell with ``spell_is_uncounterable=true`` on its printing
    cannot be countered by the ``counter_spell`` primitive."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    ZONE_STACK_OBJECT = 100  # arbitrary; the test path uses register_and_inject_object_on_stack
    baloth_dict = {
        "name": "Frenzied Baloth",
        "mana_cost": {"generic": 0, "G": 2},
        "card_types": ["Creature"],
        "power": 3,
        "toughness": 2,
        "spell_is_uncounterable": True,
    }
    # Register Frenzied Baloth and inject it as a stack item.
    baloth_id = state.register_and_inject_stack_spell(baloth_dict, 0)
    # Confirm counter_spell returns False (the gate fires).
    assert state.counter_spell(baloth_id) is False


def test_rust_counter_spell_skips_creature_under_grant_static():
    """A creature spell on the stack is uncounterable when its
    controller has a permanent carrying
    ``grants_creature_spells_uncounterable=true`` on the
    battlefield."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    ZONE_BATTLEFIELD = 2
    # Put Frenzied Baloth on P0's battlefield (the grant source).
    baloth_dict = {
        "name": "Frenzied Baloth",
        "mana_cost": {"generic": 0, "G": 2},
        "card_types": ["Creature"],
        "power": 3,
        "toughness": 2,
        "grants_creature_spells_uncounterable": True,
    }
    state.register_and_inject_object(baloth_dict, 0, ZONE_BATTLEFIELD)
    # Push a Grizzly Bears creature spell controlled by P0 onto the
    # stack.
    bears_dict = {
        "name": "Grizzly Bears",
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
    }
    bears_id = state.register_and_inject_stack_spell(bears_dict, 0)
    # Counter attempt fizzles.
    assert state.counter_spell(bears_id) is False


def test_rust_counter_spell_targets_normal_spell():
    """A normal (counterable) creature spell can still be countered."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    bears_dict = {
        "name": "Grizzly Bears",
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
    }
    bears_id = state.register_and_inject_stack_spell(bears_dict, 0)
    assert state.counter_spell(bears_id) is True


def test_rust_counter_spell_grant_does_not_cross_controllers():
    """The grant static only protects creature spells under the
    grant source's controller. Opponent's creature spells are still
    counterable."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    ZONE_BATTLEFIELD = 2
    # P0 has the grant source.
    baloth_dict = {
        "name": "Frenzied Baloth",
        "mana_cost": {"generic": 0, "G": 2},
        "card_types": ["Creature"],
        "power": 3,
        "toughness": 2,
        "grants_creature_spells_uncounterable": True,
    }
    state.register_and_inject_object(baloth_dict, 0, ZONE_BATTLEFIELD)
    # P1 casts a creature spell.
    bears_dict = {
        "name": "Grizzly Bears",
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
    }
    bears_id = state.register_and_inject_stack_spell(bears_dict, 1)
    # P1's spell IS counterable — P0's grant doesn't reach it.
    assert state.counter_spell(bears_id) is True


def test_rust_counter_spell_grant_skips_noncreature_spells():
    """The grant only protects CREATURE spells; non-creature spells
    are counterable even when the controller has a grant source."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    ZONE_BATTLEFIELD = 2
    baloth_dict = {
        "name": "Frenzied Baloth",
        "mana_cost": {"generic": 0, "G": 2},
        "card_types": ["Creature"],
        "power": 3,
        "toughness": 2,
        "grants_creature_spells_uncounterable": True,
    }
    state.register_and_inject_object(baloth_dict, 0, ZONE_BATTLEFIELD)
    instant_dict = {
        "name": "Lightning Bolt",
        "mana_cost": {"generic": 0, "R": 1},
        "card_types": ["Instant"],
    }
    instant_id = state.register_and_inject_stack_spell(instant_dict, 0)
    assert state.counter_spell(instant_id) is True


# ---------------------------------------------------------------------------
# Loader admit — Frenzied Baloth reaches CardDef through the full filter
# ---------------------------------------------------------------------------


def test_filter_deck_admits_frenzied_baloth():
    """``_filter_deck_to_bridge_supported`` admits Frenzied Baloth
    through the new 8th disjunct."""
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported
    filtered_names, card_defs = _filter_deck_to_bridge_supported(
        ["Frenzied Baloth"], printings,
    )
    assert filtered_names == ["Frenzied Baloth"]
    assert len(card_defs) == 1
    cd = card_defs[0]
    assert cd.spell_is_uncounterable is True
    assert cd.grants_creature_spells_uncounterable is True


def test_filter_still_rejects_phase1_honest_stops():
    """The six Phase-1 honest-stops stay honest-stopped — Cloudsculpt
    Technician, Gravblade Heavy, Brightspear Zealot, Mechan
    Shieldmate. (Rampaging Soulrager / Wildfire Wickerfolk are not
    in the current EoE data snapshot; they'd be honest-stopped via
    the same path.)"""
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported
    for name in (
        "Cloudsculpt Technician",
        "Gravblade Heavy",
        "Brightspear Zealot",
        "Mechan Shieldmate",
    ):
        filtered_names, _ = _filter_deck_to_bridge_supported(
            [name], printings,
        )
        assert filtered_names == [], (
            f"{name} should be honest-stopped (per-Condition substrate "
            "deferred to next slice)"
        )
