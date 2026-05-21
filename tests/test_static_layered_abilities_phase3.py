"""Static / layered abilities substrate — Phase 3 tests
(SELF-scope conditional P/T + keyword grants).

Spec: ``docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md`` §3 lever (1)
(round-81; 2026-05-20).

**Phase 3 scope.** SELF-scope conditional statics — the parser-emitted
shape for cards like:

* **Brightspear Zealot** — "This creature gets +2/+0 as long as
  you've cast two or more spells this turn." (condition tag:
  ``at_least_n_spells_cast_this_turn`` with ``n=2``)
* **Cloudsculpt Technician** — "As long as you control an artifact,
  this creature gets +1/+0." (condition tag:
  ``control_permanent_is_artifact``)
* **Gravblade Heavy** — "As long as you control an artifact, this
  creature gets +1/+0 and has deathtouch." (same tag, with a
  layer-6 keyword grant fan-out)

The substrate is wired end-to-end:

* ``CardDef`` carries ``static_self_bonuses: tuple[
  tuple[condition_tag, condition_args, p_bonus, t_bonus,
  granted_keywords], ...]``.
* Bridge emits the ``static_self_bonuses`` key on the registry dict.
* Rust ``CardPrinting`` carries a parallel ``static_self_bonuses:
  Vec<StaticSelfBonus>``; ``parse_printing`` reads the key.
* Rust ``battlefield_creature_power`` /
  ``battlefield_creature_toughness`` fold in the layer-7c P/T
  contribution; ``battlefield_has_keyword`` folds in the layer-6
  keyword grants.
* ``_card_def_to_python_printing`` materializes the matching Python
  ``StaticAbility`` tuple so the same CardDef shape powers both
  engines.
* ``_printing_is_bridge_simple_static_self_conditional_creature`` is
  the new loader admit-disjunct (9th in
  ``_filter_deck_to_bridge_supported``).

**Honest-stops for this slice (documented in
``docs/SEARCH_LIMITATIONS.md``):**

* Mechan Shieldmate — ``ControlledArtifactEnteredThisTurn`` +
  ``RemoveKeyword(defender)`` payload (the Rust reader doesn't fold
  layer-6 keyword-removal yet, and the Condition isn't in this
  slice's two-tag table).
* Rampaging Soulrager — ``UnlockedDoorsAmongRoomsAtLeast(2)`` (no
  EoE data snapshot today).
* Wildfire Wickerfolk — ``DeliriumActive`` (no EoE data snapshot
  today).
"""

from __future__ import annotations

import importlib

import pytest

from mtg_bot.parity.cross_engine import (
    CardDef,
    DeckSpec,
    _card_def_to_python_printing,
    _static_self_bonus_condition_from_tag,
    build_matched_states,
    build_rust_registry,
)
from mtg_bot.parity.trajectory import (
    _printing_is_bridge_simple_static_self_conditional_creature,
    _printing_to_card_def,
    _static_ability_to_self_conditional_bonus,
)


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


# ---------------------------------------------------------------------------
# Predicate — admit shape teeth
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Brightspear Zealot",
        "Cloudsculpt Technician",
        "Gravblade Heavy",
        # Round-82 (2026-05-20, Mechan Shieldmate closure): joins
        # the admit set via the third condition tag
        # `"controlled_artifact_entered_this_turn"` + a
        # RemoveKeyword payload arm in
        # `_static_ability_to_self_conditional_bonus`. Its
        # Artifact-Creature dual-type is the first
        # ``extra_card_types=("Artifact",)`` shape this predicate
        # admits.
        "Mechan Shieldmate",
    ],
)
def test_admit_predicate_accepts_four_phase3_carriers(name):
    """All four EoE SELF-scope conditional carriers pass the
    predicate. Round-82: Mechan Shieldmate joined the set."""
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    p = printings[name]
    assert (
        _printing_is_bridge_simple_static_self_conditional_creature(p)
        is True
    )


def test_admit_predicate_rejects_anthem_shape():
    """An anthem-shape static (Tannuk's "Other creatures you control
    have haste.") is NOT this slice's admit shape — different scope
    (other_creatures_you_control, not SELF). The Phase-1 anthem arm
    handles it; the Phase-3 predicate declines."""
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    tannuk = printings["Tannuk, Steadfast Second"]
    assert (
        _printing_is_bridge_simple_static_self_conditional_creature(
            tannuk,
        )
        is False
    )


def test_admit_predicate_rejects_uncounterable_shape():
    """Frenzied Baloth's ``grants_creature_spells_uncounterable``
    sentinel is NOT this slice — the Phase-2 arm handles it; the
    Phase-3 predicate declines."""
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    baloth = printings["Frenzied Baloth"]
    assert (
        _printing_is_bridge_simple_static_self_conditional_creature(
            baloth,
        )
        is False
    )


def test_ability_to_bonus_rejects_unknown_condition():
    """An unsupported Condition (e.g. DuringYourTurn) is not in the
    Phase-3 dispatch table — ``_static_ability_to_self_conditional_
    bonus`` returns None."""
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.effects.conditions import DuringYourTurn
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, PowerToughnessBonus,
    )

    ability = StaticAbility(
        scope=StaticScope.SELF,
        condition=DuringYourTurn(),
        continuous_effect=ContinuousModifier(
            layer=7,
            payload=PowerToughnessBonus(power_bonus=1, toughness_bonus=0),
        ),
    )
    assert _static_ability_to_self_conditional_bonus(ability) is None


def test_ability_to_bonus_rejects_no_condition():
    """An unconditional SELF-scope static (synthetic — no EoE card
    today) is not in the Phase-3 admit shape; the condition slot
    must be populated for the conditional-bonus arm."""
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, PowerToughnessBonus,
    )

    ability = StaticAbility(
        scope=StaticScope.SELF,
        condition=None,
        continuous_effect=ContinuousModifier(
            layer=7,
            payload=PowerToughnessBonus(power_bonus=1, toughness_bonus=0),
        ),
    )
    assert _static_ability_to_self_conditional_bonus(ability) is None


def test_ability_to_bonus_pt_brightspear_shape():
    """The Brightspear Zealot ability shape rehydrates to the
    expected (tag, args, p, t, keywords) tuple."""
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.effects.conditions import AtLeastNSpellsCastThisTurn
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, PowerToughnessBonus,
    )

    ability = StaticAbility(
        scope=StaticScope.SELF,
        condition=AtLeastNSpellsCastThisTurn(2),
        continuous_effect=ContinuousModifier(
            layer=7,
            payload=PowerToughnessBonus(power_bonus=2, toughness_bonus=0),
        ),
    )
    bonus = _static_ability_to_self_conditional_bonus(ability)
    assert bonus == (
        "at_least_n_spells_cast_this_turn", (2,), 2, 0, (), (),
    )


def test_ability_to_bonus_keyword_gravblade_shape():
    """The Gravblade keyword-grant half rehydrates to a keyword-only
    tuple with zero P/T."""
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.effects.conditions import ControlPermanent
    from mtg_bot.effects.modifiers import ContinuousModifier, GrantKeyword
    from mtg_bot.effects.object_predicates import IsArtifact

    ability = StaticAbility(
        scope=StaticScope.SELF,
        condition=ControlPermanent(IsArtifact()),
        continuous_effect=ContinuousModifier(
            layer=6, payload=GrantKeyword("deathtouch"),
        ),
    )
    bonus = _static_ability_to_self_conditional_bonus(ability)
    assert bonus == (
        "control_permanent_is_artifact", (), 0, 0, ("deathtouch",), (),
    )


# ---------------------------------------------------------------------------
# Condition rehydration round-trip
# ---------------------------------------------------------------------------


def test_condition_from_tag_artifact():
    """Bridge tag → Python Condition round-trip."""
    from mtg_bot.effects.conditions import ControlPermanent
    from mtg_bot.effects.object_predicates import IsArtifact

    cond = _static_self_bonus_condition_from_tag(
        "control_permanent_is_artifact", (),
    )
    assert isinstance(cond, ControlPermanent)
    assert isinstance(cond.filter, IsArtifact)


def test_condition_from_tag_spells_cast():
    from mtg_bot.effects.conditions import AtLeastNSpellsCastThisTurn

    cond = _static_self_bonus_condition_from_tag(
        "at_least_n_spells_cast_this_turn", (3,),
    )
    assert isinstance(cond, AtLeastNSpellsCastThisTurn)
    assert cond.n == 3


def test_condition_from_tag_unknown_raises():
    with pytest.raises(ValueError, match="unknown SELF-scope"):
        _static_self_bonus_condition_from_tag("never_heard_of_it", ())


def test_condition_from_tag_artifact_extra_args_raises():
    with pytest.raises(ValueError, match="takes no args"):
        _static_self_bonus_condition_from_tag(
            "control_permanent_is_artifact", (1,),
        )


def test_condition_from_tag_spells_cast_wrong_arity_raises():
    with pytest.raises(ValueError, match="takes 1 arg"):
        _static_self_bonus_condition_from_tag(
            "at_least_n_spells_cast_this_turn", (1, 2),
        )


# ---------------------------------------------------------------------------
# CardDef round-trip (Python printing -> CardDef -> Python printing)
# ---------------------------------------------------------------------------


def test_printing_to_card_def_brightspear():
    """Brightspear Zealot's CardDef carries the AtLeastN spells
    bonus, in the (tag, args, p, t, kws) tuple shape."""
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    cd = _printing_to_card_def(printings["Brightspear Zealot"])
    assert cd.card_type == "Creature"
    assert cd.power == 2
    assert cd.toughness == 4
    assert cd.static_self_bonuses == (
        ("at_least_n_spells_cast_this_turn", (2,), 2, 0, (), ()),
    )
    assert "vigilance" in cd.keywords


def test_printing_to_card_def_cloudsculpt():
    """Cloudsculpt Technician's CardDef carries the
    control_permanent_is_artifact bonus."""
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    cd = _printing_to_card_def(printings["Cloudsculpt Technician"])
    assert cd.static_self_bonuses == (
        ("control_permanent_is_artifact", (), 1, 0, (), ()),
    )
    assert "flying" in cd.keywords


def test_printing_to_card_def_gravblade_coalesces():
    """Gravblade Heavy's parser-emitted TWO StaticAbilities (one P/T,
    one keyword — both sharing ``control_permanent_is_artifact``)
    coalesce into ONE bridge entry carrying both the P/T and the
    keyword."""
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    cd = _printing_to_card_def(printings["Gravblade Heavy"])
    assert cd.static_self_bonuses == (
        ("control_permanent_is_artifact", (), 1, 0, ("deathtouch",), ()),
    )


def test_card_def_round_trip_python_printing_brightspear():
    """``_card_def_to_python_printing`` materializes the StaticAbility
    tuple from the CardDef's static_self_bonuses slot."""
    from mtg_bot.cards.base import StaticScope
    from mtg_bot.effects.conditions import AtLeastNSpellsCastThisTurn
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, PowerToughnessBonus,
    )

    cd = CardDef(
        name="Brightspear",
        card_type="Creature",
        mana_cost_generic=2,
        mana_cost_colored=(("W", 1),),
        power=2,
        toughness=4,
        keywords=("vigilance",),
        static_self_bonuses=(
            ("at_least_n_spells_cast_this_turn", (2,), 2, 0, (), ()),
        ),
    )
    printing = _card_def_to_python_printing(cd)
    assert len(printing.static_abilities) == 1
    sa = printing.static_abilities[0]
    assert sa.scope == StaticScope.SELF
    assert isinstance(sa.condition, AtLeastNSpellsCastThisTurn)
    assert sa.condition.n == 2
    assert isinstance(sa.continuous_effect, ContinuousModifier)
    assert sa.continuous_effect.layer == 7
    assert isinstance(sa.continuous_effect.payload, PowerToughnessBonus)
    assert sa.continuous_effect.payload.power_bonus == 2
    assert sa.continuous_effect.payload.toughness_bonus == 0


def test_card_def_round_trip_python_printing_gravblade_fanout():
    """The Gravblade coalesced entry materializes BACK into two
    StaticAbility instances — one P/T, one keyword grant — mirroring
    the parser fan-out."""
    from mtg_bot.cards.base import StaticScope
    from mtg_bot.effects.conditions import ControlPermanent
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, GrantKeyword, PowerToughnessBonus,
    )
    from mtg_bot.effects.object_predicates import IsArtifact

    cd = CardDef(
        name="Gravblade",
        card_type="Creature",
        mana_cost_generic=3,
        mana_cost_colored=(("B", 1),),
        power=3,
        toughness=4,
        static_self_bonuses=(
            (
                "control_permanent_is_artifact", (), 1, 0,
                ("deathtouch",), (),
            ),
        ),
    )
    printing = _card_def_to_python_printing(cd)
    assert len(printing.static_abilities) == 2
    payloads = sorted(
        type(sa.continuous_effect.payload).__name__
        for sa in printing.static_abilities
    )
    assert payloads == ["GrantKeyword", "PowerToughnessBonus"]
    for sa in printing.static_abilities:
        assert sa.scope == StaticScope.SELF
        assert isinstance(sa.condition, ControlPermanent)
        assert isinstance(sa.condition.filter, IsArtifact)


# ---------------------------------------------------------------------------
# Rust registry round-trip
# ---------------------------------------------------------------------------


def test_rust_registry_round_trip_static_self_bonuses():
    """The Rust ``parse_printing`` arm reads the
    ``static_self_bonuses`` key off the registry dict and re-surfaces
    it via ``Registry.get_printing_static_self_bonuses``."""
    _require_engine()
    spec = DeckSpec(
        card_defs=(
            CardDef(name="Forest", card_type="Land", mana_produced=("G",)),
            CardDef(
                name="Brightspear",
                card_type="Creature",
                mana_cost_generic=2,
                mana_cost_colored=(("W", 1),),
                power=2,
                toughness=4,
                keywords=("vigilance",),
                static_self_bonuses=(
                    (
                        "at_least_n_spells_cast_this_turn", (2,), 2, 0,
                        (), (),
                    ),
                ),
            ),
        ),
        p0_library=("Brightspear", "Forest"),
        p1_library=("Forest",),
    )
    reg, name_to_pid = build_rust_registry(spec)
    bonuses = reg.get_printing_static_self_bonuses(
        name_to_pid["Brightspear"],
    )
    assert bonuses == [
        ("at_least_n_spells_cast_this_turn", [2], 2, 0, [], []),
    ]
    forest_bonuses = reg.get_printing_static_self_bonuses(
        name_to_pid["Forest"],
    )
    assert forest_bonuses == []


def test_rust_registry_rejects_unknown_tag():
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    bad_dict = {
        "name": "Bad",
        "mana_cost": {"generic": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "static_self_bonuses": [
            {
                "condition_tag": "no_such_tag",
                "condition_args": [],
                "power_bonus": 1,
                "toughness_bonus": 0,
                "granted_keywords": [],
            },
        ],
    }
    # Match the round-82 widened error message (now three valid tags).
    with pytest.raises(ValueError, match="condition_tag must be"):
        reg.register_printing(bad_dict)


def test_rust_registry_rejects_wrong_arity():
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    bad_dict = {
        "name": "Bad",
        "mana_cost": {"generic": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "static_self_bonuses": [
            {
                "condition_tag": "at_least_n_spells_cast_this_turn",
                "condition_args": [],
                "power_bonus": 1,
                "toughness_bonus": 0,
                "granted_keywords": [],
            },
        ],
    }
    with pytest.raises(ValueError, match="exactly 1 int"):
        reg.register_printing(bad_dict)


def test_rust_registry_artifact_tag_with_args_rejected():
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    bad_dict = {
        "name": "Bad",
        "mana_cost": {"generic": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
        "static_self_bonuses": [
            {
                "condition_tag": "control_permanent_is_artifact",
                "condition_args": [99],
                "power_bonus": 1,
                "toughness_bonus": 0,
                "granted_keywords": [],
            },
        ],
    }
    with pytest.raises(ValueError, match="must be empty"):
        reg.register_printing(bad_dict)


def test_rust_registry_pre_substrate_default_empty():
    """A registry dict without the ``static_self_bonuses`` key
    parses to an empty list (back-compat default)."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "Bears",
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
    }
    pid = reg.register_printing(d)
    assert reg.get_printing_static_self_bonuses(pid) == []


# ---------------------------------------------------------------------------
# Cross-engine reader site — P/T fold byte-equal
# ---------------------------------------------------------------------------


def _inject_bf(state, dct, player, zone=2):
    return state.register_and_inject_object(dct, player, zone)


def test_rust_brightspear_pt_fires_when_two_spells_cast():
    """Brightspear's +2/+0 fires once
    ``player.spells_cast_this_turn`` clears 2."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    bs_dict = {
        "name": "Brightspear Zealot",
        "mana_cost": {"generic": 2, "W": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 4,
        "keywords": ["vigilance"],
        "static_self_bonuses": [
            {
                "condition_tag": "at_least_n_spells_cast_this_turn",
                "condition_args": [2],
                "power_bonus": 2,
                "toughness_bonus": 0,
                "granted_keywords": [],
            },
        ],
    }
    bs_id = _inject_bf(state, bs_dict, 0)
    # 0 spells cast: condition fails, base 2/4.
    assert state.effective_power(bs_id) == 2
    assert state.effective_toughness(bs_id) == 4
    # 1 spell: still under threshold.
    state.set_spells_cast_this_turn(0, 1)
    assert state.effective_power(bs_id) == 2
    # 2 spells: condition fires, +2/+0 -> 4/4.
    state.set_spells_cast_this_turn(0, 2)
    assert state.effective_power(bs_id) == 4
    assert state.effective_toughness(bs_id) == 4


def test_rust_cloudsculpt_pt_fires_with_artifact():
    """Cloudsculpt Technician's +1/+0 fires while the controller
    controls an artifact."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    cs_dict = {
        "name": "Cloudsculpt Technician",
        "mana_cost": {"generic": 2, "U": 1},
        "card_types": ["Creature"],
        "power": 1,
        "toughness": 4,
        "keywords": ["flying"],
        "static_self_bonuses": [
            {
                "condition_tag": "control_permanent_is_artifact",
                "condition_args": [],
                "power_bonus": 1,
                "toughness_bonus": 0,
                "granted_keywords": [],
            },
        ],
    }
    artifact_dict = {
        "name": "Stone",
        "mana_cost": {"generic": 1},
        "card_types": ["Artifact"],
    }
    cs_id = _inject_bf(state, cs_dict, 0)
    # No artifact yet → base 1/4.
    assert state.effective_power(cs_id) == 1
    assert state.effective_toughness(cs_id) == 4
    # Put an artifact onto the same battlefield → +1/+0 → 2/4.
    _inject_bf(state, artifact_dict, 0)
    assert state.effective_power(cs_id) == 2
    assert state.effective_toughness(cs_id) == 4


def test_rust_gravblade_pt_and_keyword_fire_together():
    """Gravblade Heavy's +1/+0 AND deathtouch grant fire while the
    controller controls an artifact."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    gb_dict = {
        "name": "Gravblade Heavy",
        "mana_cost": {"generic": 3, "B": 1},
        "card_types": ["Creature"],
        "power": 3,
        "toughness": 4,
        "static_self_bonuses": [
            {
                "condition_tag": "control_permanent_is_artifact",
                "condition_args": [],
                "power_bonus": 1,
                "toughness_bonus": 0,
                "granted_keywords": ["deathtouch"],
            },
        ],
    }
    artifact_dict = {
        "name": "Stone",
        "mana_cost": {"generic": 1},
        "card_types": ["Artifact"],
    }
    gb_id = _inject_bf(state, gb_dict, 0)
    # No artifact: base 3/4, no deathtouch.
    assert state.effective_power(gb_id) == 3
    assert state.has_keyword(gb_id, "deathtouch") is False
    # Add artifact: +1/+0 (4/4) + deathtouch.
    _inject_bf(state, artifact_dict, 0)
    assert state.effective_power(gb_id) == 4
    assert state.has_keyword(gb_id, "deathtouch") is True


def test_rust_condition_does_not_cross_controllers():
    """An artifact under the OPPONENT does NOT satisfy
    ``control_permanent_is_artifact`` for the source's controller."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    cs_dict = {
        "name": "Cloudsculpt Technician",
        "mana_cost": {"generic": 2, "U": 1},
        "card_types": ["Creature"],
        "power": 1,
        "toughness": 4,
        "static_self_bonuses": [
            {
                "condition_tag": "control_permanent_is_artifact",
                "condition_args": [],
                "power_bonus": 1,
                "toughness_bonus": 0,
                "granted_keywords": [],
            },
        ],
    }
    artifact_dict = {
        "name": "Stone",
        "mana_cost": {"generic": 1},
        "card_types": ["Artifact"],
    }
    cs_id = _inject_bf(state, cs_dict, 0)
    # Artifact under P1, not P0 — condition fails for the P0-
    # controlled Cloudsculpt.
    _inject_bf(state, artifact_dict, 1)
    assert state.effective_power(cs_id) == 1


# ---------------------------------------------------------------------------
# Loader admit — all three carriers reach CardDef through the full filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        (
            "Brightspear Zealot",
            (
                (
                    "at_least_n_spells_cast_this_turn", (2,), 2, 0,
                    (), (),
                ),
            ),
        ),
        (
            "Cloudsculpt Technician",
            (("control_permanent_is_artifact", (), 1, 0, (), ()),),
        ),
        (
            "Gravblade Heavy",
            (
                (
                    "control_permanent_is_artifact", (), 1, 0,
                    ("deathtouch",), (),
                ),
            ),
        ),
        # Round-82 (2026-05-20): Mechan Shieldmate joins the
        # admit set with the round-82 third tag +
        # removed_keywords payload.
        (
            "Mechan Shieldmate",
            (
                (
                    "controlled_artifact_entered_this_turn", (),
                    0, 0, (), ("defender",),
                ),
            ),
        ),
    ],
)
def test_filter_deck_admits_phase3_carriers(name, expected):
    """``_filter_deck_to_bridge_supported`` admits each Phase-3
    carrier through the new 9th disjunct."""
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    from mtg_bot.parity.trajectory import _filter_deck_to_bridge_supported
    filtered_names, card_defs = _filter_deck_to_bridge_supported(
        [name], printings,
    )
    assert filtered_names == [name]
    assert len(card_defs) == 1
    assert card_defs[0].static_self_bonuses == expected


# ---------------------------------------------------------------------------
# Real EoE byte-equal probe — Python vs Rust effective_power agreement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "card_name",
    [
        "Brightspear Zealot",
        "Cloudsculpt Technician",
        "Gravblade Heavy",
    ],
)
def test_real_eoe_byte_equal_effective_pt_match(card_name):
    """End-to-end real-EoE probe: load the actual EoE printing, build
    matched states, manually inject a battlefield copy of the card on
    P0, and verify Python's ``effective_power`` /
    ``effective_toughness`` agrees with Rust's at every gate state
    (condition off and on).
    """
    _require_engine()
    from mtg_bot.game import (
        Zone, effective_power, effective_toughness,
    )
    from mtg_bot.parity.cross_engine import build_python_state
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    target = printings[card_name]
    cd_target = _printing_to_card_def(target)
    artifact_cd = CardDef(
        name="Stone",
        card_type="Artifact",
        mana_cost_generic=1,
    )
    forest_cd = CardDef(
        name="Forest", card_type="Land", mana_produced=("G",),
    )
    spec = DeckSpec(
        card_defs=(forest_cd, artifact_cd, cd_target),
        p0_library=(cd_target.name, "Forest"),
        p1_library=("Forest",),
    )
    py_state, rust_state = build_matched_states(spec)
    # On the Python side: inject the target object onto P0's
    # battlefield. The library currently has the target as the first
    # card.
    tgt_py = py_state.players[0].library[0]
    py_state.players[0].library = []
    tgt_py.zone = Zone.BATTLEFIELD
    py_state.battlefield.append(tgt_py)
    # Pre-condition state: condition NOT met → base P/T.
    py_pt0 = (
        effective_power(py_state, tgt_py),
        effective_toughness(py_state, tgt_py),
    )
    # On the Rust side: inject the same printing on P0's battlefield.
    # Use the registry pid via name_to_pid.
    _reg_handle, name_to_pid = build_rust_registry(spec)
    tgt_dict_rust = {}  # unused — we'll go via register_and_inject_object
    # Build a fresh synthetic state for the Rust readback at the same
    # config — round-trip the bridge dict for the target.
    import mtg_bot_engine
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict
    rs2 = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    target_dict = _spec_card_to_printing_dict(cd_target)
    artifact_dict_r = _spec_card_to_printing_dict(artifact_cd)
    tgt_id_r = rs2.register_and_inject_object(target_dict, 0, 2)
    rs_pt0 = (rs2.effective_power(tgt_id_r), rs2.effective_toughness(tgt_id_r))
    assert py_pt0 == rs_pt0, (
        f"pre-condition P/T differs: py={py_pt0} rs={rs_pt0}"
    )
    # Drive the condition into TRUE.
    if cd_target.static_self_bonuses[0][0] == "control_permanent_is_artifact":
        # Put an artifact under P0 on both engines. ``state.battlefield``
        # is the shared zone — every battlefield permanent has a
        # ``controller_id`` field that determines who controls it.
        from mtg_bot.parity.cross_engine import _card_def_to_python_printing
        artifact_py = _card_def_to_python_printing(artifact_cd)
        from mtg_bot.game import GameObject
        gob_id = max(
            (o.id for o in py_state.battlefield),
            default=0,
        ) + 1
        gob = GameObject(
            id=gob_id, printing=artifact_py, controller_id=0,
            owner_id=0, zone=Zone.BATTLEFIELD,
        )
        py_state.battlefield.append(gob)
        rs2.register_and_inject_object(artifact_dict_r, 0, 2)
    elif cd_target.static_self_bonuses[0][0] == "at_least_n_spells_cast_this_turn":
        n = cd_target.static_self_bonuses[0][1][0]
        py_state.players[0].spells_cast_this_turn = n
        rs2.set_spells_cast_this_turn(0, n)
    else:
        pytest.skip(
            f"unhandled tag {cd_target.static_self_bonuses[0][0]} in probe"
        )
    py_pt1 = (
        effective_power(py_state, tgt_py),
        effective_toughness(py_state, tgt_py),
    )
    rs_pt1 = (rs2.effective_power(tgt_id_r), rs2.effective_toughness(tgt_id_r))
    assert py_pt1 == rs_pt1, (
        f"post-condition P/T differs: py={py_pt1} rs={rs_pt1}"
    )
    # And the condition-on P/T must be DIFFERENT from condition-off
    # (verifies the bonus actually fired).
    assert py_pt1 != py_pt0


# ---------------------------------------------------------------------------
# Round-82 (2026-05-20) — Mechan Shieldmate closure
# ---------------------------------------------------------------------------


def test_condition_from_tag_controlled_artifact_entered():
    """Round-82: the third recognized tag rehydrates to the
    ``ControlledArtifactEnteredThisTurn`` Condition."""
    from mtg_bot.effects.conditions import ControlledArtifactEnteredThisTurn

    cond = _static_self_bonus_condition_from_tag(
        "controlled_artifact_entered_this_turn", (),
    )
    assert isinstance(cond, ControlledArtifactEnteredThisTurn)


def test_condition_from_tag_controlled_artifact_extra_args_raises():
    """Arg-less tag rejects non-empty args (mirrors the
    ``control_permanent_is_artifact`` arity contract)."""
    with pytest.raises(ValueError, match="takes no"):
        _static_self_bonus_condition_from_tag(
            "controlled_artifact_entered_this_turn", (1,),
        )


def test_ability_to_bonus_remove_keyword_mechan_shape():
    """Round-82: the Mechan-shape (RemoveKeyword payload + new tag)
    rehydrates to a removed_keywords-only tuple with zero P/T and no
    granted_keywords."""
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.effects.conditions import ControlledArtifactEnteredThisTurn
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, RemoveKeyword,
    )

    ability = StaticAbility(
        scope=StaticScope.SELF,
        condition=ControlledArtifactEnteredThisTurn(),
        continuous_effect=ContinuousModifier(
            layer=6, payload=RemoveKeyword("defender"),
        ),
    )
    bonus = _static_ability_to_self_conditional_bonus(ability)
    assert bonus == (
        "controlled_artifact_entered_this_turn", (), 0, 0,
        (), ("defender",),
    )


def test_ability_to_bonus_remove_keyword_unsafe_keyword_rejected():
    """A RemoveKeyword payload whose keyword is outside
    ``_SAFE_KEYWORDS`` is rejected by the admit shape."""
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.effects.conditions import ControlledArtifactEnteredThisTurn
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, RemoveKeyword,
    )

    ability = StaticAbility(
        scope=StaticScope.SELF,
        condition=ControlledArtifactEnteredThisTurn(),
        continuous_effect=ContinuousModifier(
            layer=6, payload=RemoveKeyword("ward"),
        ),
    )
    assert _static_ability_to_self_conditional_bonus(ability) is None


def test_printing_to_card_def_mechan_shieldmate():
    """Mechan Shieldmate's CardDef carries the controlled-artifact-
    entered tag with a single ``("defender",)`` removed_keywords
    entry AND its Artifact-Creature dual-type via
    ``extra_card_types``."""
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    cd = _printing_to_card_def(printings["Mechan Shieldmate"])
    assert cd.card_type == "Creature"
    assert cd.extra_card_types == ("Artifact",)
    assert cd.power == 3
    assert cd.toughness == 2
    assert "defender" in cd.keywords
    assert cd.static_self_bonuses == (
        (
            "controlled_artifact_entered_this_turn", (),
            0, 0, (), ("defender",),
        ),
    )


def test_card_def_round_trip_python_printing_mechan():
    """The Mechan-shape CardDef materializes BACK into a SELF-scope
    StaticAbility whose payload is RemoveKeyword and whose Condition
    is ControlledArtifactEnteredThisTurn."""
    from mtg_bot.cards.base import StaticScope
    from mtg_bot.effects.conditions import ControlledArtifactEnteredThisTurn
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, RemoveKeyword,
    )
    from mtg_bot.parity.cross_engine import _card_def_to_python_printing

    cd = CardDef(
        name="Mechan",
        card_type="Creature",
        extra_card_types=("Artifact",),
        mana_cost_generic=1,
        mana_cost_colored=(("U", 1),),
        power=3,
        toughness=2,
        keywords=("defender",),
        static_self_bonuses=(
            (
                "controlled_artifact_entered_this_turn", (),
                0, 0, (), ("defender",),
            ),
        ),
    )
    printing = _card_def_to_python_printing(cd)
    assert len(printing.static_abilities) == 1
    sa = printing.static_abilities[0]
    assert sa.scope == StaticScope.SELF
    assert isinstance(sa.condition, ControlledArtifactEnteredThisTurn)
    assert isinstance(sa.continuous_effect, ContinuousModifier)
    assert sa.continuous_effect.layer == 6
    assert isinstance(sa.continuous_effect.payload, RemoveKeyword)
    assert sa.continuous_effect.payload.keyword == "defender"
    # Mechan's Artifact-Creature dual-type round-trips on the Python
    # printing's card_types tuple in (primary, *extras) order.
    assert "Creature" in printing.card_types
    assert "Artifact" in printing.card_types


def test_rust_registry_round_trip_mechan_remove_keyword():
    """Round-82: a registry dict carrying ``removed_keywords``
    round-trips through Rust's parse + getter back to a 6-tuple
    with the removed keyword present."""
    _require_engine()
    spec = DeckSpec(
        card_defs=(
            CardDef(name="Forest", card_type="Land", mana_produced=("G",)),
            CardDef(
                name="Mechan",
                card_type="Creature",
                extra_card_types=("Artifact",),
                mana_cost_generic=1,
                mana_cost_colored=(("U", 1),),
                power=3,
                toughness=2,
                keywords=("defender",),
                static_self_bonuses=(
                    (
                        "controlled_artifact_entered_this_turn", (),
                        0, 0, (), ("defender",),
                    ),
                ),
            ),
        ),
        p0_library=("Mechan", "Forest"),
        p1_library=("Forest",),
    )
    reg, name_to_pid = build_rust_registry(spec)
    bonuses = reg.get_printing_static_self_bonuses(
        name_to_pid["Mechan"],
    )
    assert bonuses == [
        (
            "controlled_artifact_entered_this_turn", [], 0, 0, [],
            ["defender"],
        ),
    ]


def test_rust_registry_rejects_unknown_arity_for_controlled_artifact():
    """The Rust parse arm rejects non-empty args for the new tag."""
    _require_engine()
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    bad_dict = {
        "name": "BadMechan",
        "mana_cost": {"generic": 1},
        "card_types": ["Creature", "Artifact"],
        "power": 3,
        "toughness": 2,
        "static_self_bonuses": [
            {
                "condition_tag": "controlled_artifact_entered_this_turn",
                "condition_args": [9],
                "power_bonus": 0,
                "toughness_bonus": 0,
                "granted_keywords": [],
                "removed_keywords": ["defender"],
            },
        ],
    }
    with pytest.raises(ValueError, match="must be empty"):
        reg.register_printing(bad_dict)


def test_rust_mechan_defender_active_when_no_artifact_entered():
    """Mechan starts with `defender` as a printed keyword and the
    REMOVE fold is inactive when the artifact-entered counter is 0
    (`condition` is false). We reset the counter to 0 BEFORE the
    keyword query — `register_and_inject_object` routes through
    `drain_pending_etb_dispatches`, and Mechan IS an artifact, so
    its own ETB bumps the counter; this probe scopes the assertion
    to the gate semantics, not the ETB pipeline (covered separately
    by ``test_rust_drain_pending_etb_bumps_artifact_counter``)."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    mechan_dict = {
        "name": "Mechan Shieldmate",
        "mana_cost": {"generic": 1, "U": 1},
        "card_types": ["Creature", "Artifact"],
        "power": 3,
        "toughness": 2,
        "keywords": ["defender"],
        "static_self_bonuses": [
            {
                "condition_tag": "controlled_artifact_entered_this_turn",
                "condition_args": [],
                "power_bonus": 0,
                "toughness_bonus": 0,
                "granted_keywords": [],
                "removed_keywords": ["defender"],
            },
        ],
    }
    mid = _inject_bf(state, mechan_dict, 0)
    state.set_artifacts_entered_under_your_control_this_turn(0, 0)
    # Counter explicitly 0 → defender stays printed (REMOVE fold
    # condition fails).
    assert state.has_keyword(mid, "defender") is True


def test_rust_mechan_defender_removed_when_artifact_entered():
    """Mechan loses `defender` once the per-controller artifact-
    entered counter advances above 0."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    mechan_dict = {
        "name": "Mechan Shieldmate",
        "mana_cost": {"generic": 1, "U": 1},
        "card_types": ["Creature", "Artifact"],
        "power": 3,
        "toughness": 2,
        "keywords": ["defender"],
        "static_self_bonuses": [
            {
                "condition_tag": "controlled_artifact_entered_this_turn",
                "condition_args": [],
                "power_bonus": 0,
                "toughness_bonus": 0,
                "granted_keywords": [],
                "removed_keywords": ["defender"],
            },
        ],
    }
    mid = _inject_bf(state, mechan_dict, 0)
    state.set_artifacts_entered_under_your_control_this_turn(0, 1)
    assert state.has_keyword(mid, "defender") is False


def test_rust_mechan_condition_does_not_cross_controllers():
    """An artifact that entered under the OPPONENT's control does
    not satisfy the gate for the SOURCE's controller — the counter
    is per-Player, not shared."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    mechan_dict = {
        "name": "Mechan Shieldmate",
        "mana_cost": {"generic": 1, "U": 1},
        "card_types": ["Creature", "Artifact"],
        "power": 3,
        "toughness": 2,
        "keywords": ["defender"],
        "static_self_bonuses": [
            {
                "condition_tag": "controlled_artifact_entered_this_turn",
                "condition_args": [],
                "power_bonus": 0,
                "toughness_bonus": 0,
                "granted_keywords": [],
                "removed_keywords": ["defender"],
            },
        ],
    }
    mid = _inject_bf(state, mechan_dict, 0)
    # Reset P0's counter (Mechan's own ETB bumped it via the
    # drain hook; see the test above for the scoping rationale).
    state.set_artifacts_entered_under_your_control_this_turn(0, 0)
    # Bump P1's counter — should NOT remove defender from P0's Mechan.
    state.set_artifacts_entered_under_your_control_this_turn(1, 5)
    assert state.has_keyword(mid, "defender") is True
    # Bump P0's counter — now defender drops.
    state.set_artifacts_entered_under_your_control_this_turn(0, 1)
    assert state.has_keyword(mid, "defender") is False


def test_rust_drain_pending_etb_bumps_artifact_counter():
    """Live integration: an artifact entering via the centralized
    bf-entry path (`register_and_inject_object` → ENTERS drain)
    bumps the per-controller counter. Verifies the
    `drain_pending_etb_dispatches` hook routes correctly."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    artifact_dict = {
        "name": "Stone",
        "mana_cost": {"generic": 1},
        "card_types": ["Artifact"],
    }
    # Pre-bf-entry: counter is 0.
    assert (
        state.get_artifacts_entered_under_your_control_this_turn(0) == 0
    )
    _inject_bf(state, artifact_dict, 0)
    # After artifact ETB: counter advanced.
    assert (
        state.get_artifacts_entered_under_your_control_this_turn(0) == 1
    )
    # P1's counter stayed at 0 — per-controller scope.
    assert (
        state.get_artifacts_entered_under_your_control_this_turn(1) == 0
    )


def test_rust_non_artifact_etb_does_not_bump_counter():
    """A non-artifact creature ETB does NOT bump the counter."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    creature_dict = {
        "name": "Bears",
        "mana_cost": {"generic": 1, "G": 1},
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 2,
    }
    _inject_bf(state, creature_dict, 0)
    assert (
        state.get_artifacts_entered_under_your_control_this_turn(0) == 0
    )


def test_rust_artifact_creature_etb_bumps_counter():
    """An Artifact Creature ETB DOES bump the counter (CR 301 — an
    artifact creature is an artifact)."""
    _require_engine()
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    art_creature_dict = {
        "name": "Bronze Bear",
        "mana_cost": {"generic": 2},
        "card_types": ["Artifact", "Creature"],
        "power": 2,
        "toughness": 2,
    }
    _inject_bf(state, art_creature_dict, 0)
    assert (
        state.get_artifacts_entered_under_your_control_this_turn(0) == 1
    )


def test_real_eoe_mechan_byte_equal_defender_removal():
    """End-to-end real-EoE probe: load the actual Mechan Shieldmate
    printing, build matched states, inject Mechan onto P0's
    battlefield, and verify Python's ``effective_keywords`` /
    Rust's ``has_keyword`` agree byte-equal across the
    counter-off / counter-on transition.

    **Mechan-on-Mechan semantics.** When the parity-bridge ETB
    pipeline routes Mechan through the bf-entry chokepoint, the
    artifact-bf-entry counter advances to 1 — Mechan IS an artifact,
    and an artifact entered under its controller this turn (it
    just did). For this isolation probe we manipulate the counter
    directly to drive the condition off → on without re-routing
    through a synthesized ETB; the round-82 closure of the
    drain-pending counter is independently covered by
    :func:`test_rust_drain_pending_etb_bumps_artifact_counter` /
    :func:`test_rust_artifact_creature_etb_bumps_counter`.
    """
    _require_engine()
    from mtg_bot.game import Zone, effective_keywords
    from mtg_bot.parity.cross_engine import (
        _spec_card_to_printing_dict,
    )
    src_mod = importlib.import_module("mtg_bot.cards.parser_source")
    src = src_mod.OracleParserCardSource()
    printings = src.get_printings()
    mechan = printings["Mechan Shieldmate"]
    cd = _printing_to_card_def(mechan)
    forest_cd = CardDef(
        name="Forest", card_type="Land", mana_produced=("G",),
    )
    spec = DeckSpec(
        card_defs=(forest_cd, cd),
        p0_library=(cd.name, "Forest"),
        p1_library=("Forest",),
    )
    py_state, _rust_state = build_matched_states(spec)
    # Move Mechan onto Python's P0 battlefield WITHOUT firing the
    # bf-entry inline counter bump (mirroring the Rust-side
    # register_and_inject_object path, which routes through the
    # drain hook). The counter is driven explicitly below.
    tgt_py = py_state.players[0].library[0]
    py_state.players[0].library = []
    tgt_py.zone = Zone.BATTLEFIELD
    py_state.battlefield.append(tgt_py)
    # Reset Python's counter in case the build_python_state path
    # touched it (Forest pad shouldn't, but stay deterministic).
    py_state.players[0].artifacts_entered_under_your_control_this_turn = 0
    # Rust-side: build a fresh synthetic state for the readback.
    import mtg_bot_engine
    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    mechan_dict = _spec_card_to_printing_dict(cd)
    rs_id = rs.register_and_inject_object(mechan_dict, 0, 2)
    # The drainer-side bump fired on the Rust register_and_inject:
    # reset to 0 to align with the Python-side reset above (this
    # probe gates on the counter, not the ETB pipeline; the
    # pipeline is covered separately).
    rs.set_artifacts_entered_under_your_control_this_turn(0, 0)
    # Counter at 0: defender ACTIVE on both engines (printed kw,
    # remove fold inactive).
    py_def0 = "defender" in effective_keywords(py_state, tgt_py)
    rs_def0 = rs.has_keyword(rs_id, "defender")
    assert py_def0 is True and rs_def0 is True, (
        f"pre-condition defender state differs/wrong: "
        f"py={py_def0} rs={rs_def0}"
    )
    # Drive the gate: bump P0's artifact-entered counter on both.
    py_state.players[0].artifacts_entered_under_your_control_this_turn = 1
    rs.set_artifacts_entered_under_your_control_this_turn(0, 1)
    py_def1 = "defender" in effective_keywords(py_state, tgt_py)
    rs_def1 = rs.has_keyword(rs_id, "defender")
    assert py_def1 is False and rs_def1 is False, (
        f"post-condition defender state differs/wrong: "
        f"py={py_def1} rs={rs_def1}"
    )
    # And the keyword state actually flipped (catches a probe that
    # silently asserted False/False on both gates).
    assert py_def0 != py_def1
