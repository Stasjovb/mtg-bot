"""Engine behavior of Shifting Woodland (delirium self-copy of a
graveyard permanent card, until end of turn) and Arena of Glory (exert
cost + haste-rider mana) as claimed by the line-composed land grammar.
"""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    _play_land,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import (
    make_basic_land,
    make_creature,
    make_instant,
    make_sorcery,
)
from mtg_bot.cards.parser.activated import (
    _parse_activate_only_if_condition,
    _parse_activated_ability_line,
)
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.effects.conditions import DeliriumActive
from mtg_bot.game import effective_keywords, is_creature_now
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_cleanup_step, run_untap_step
from tests.test_cube_land_mechanics import (
    _Agent,
    _put,
    _state,
    _zone,
    cube,  # noqa: F401  (module-scoped fixture)
)


FOREST = make_basic_land("Forest", "G")
MOUNTAIN = make_basic_land("Mountain", "R")
BEAST = make_creature("Beast", "{3}{G}", 4, 4)


def _delirium_graveyard(state, player_id=0):
    """Creature + instant + sorcery + land in the graveyard."""
    beast = _zone(state, BEAST, "hand", player_id)
    state.players[player_id].hand.remove(beast)
    state.players[player_id].graveyard.append(beast)
    for printing in (
        make_instant("Zap", "{R}", None),
        make_sorcery("Think", "{U}", None),
        FOREST,
    ):
        obj = _zone(state, printing, "hand", player_id)
        state.players[player_id].hand.remove(obj)
        state.players[player_id].graveyard.append(obj)
    return beast


# --- Shifting Woodland ---------------------------------------------------------


def test_shifting_woodland_claimed(cube):
    from mtg_bot.effects.generic import (
        SourceBecomesCopyOfTargetGraveyardCardUEOT,
    )
    from mtg_bot.effects.conditions import ControlPermanent
    from mtg_bot.effects.object_predicates import HasSubtype

    wood = cube["Shifting Woodland"]
    assert wood.enters_tapped_unless == ControlPermanent(HasSubtype("Forest"))
    assert wood.produces == frozenset({"G"})
    (copy,) = wood.activated_abilities
    assert copy.cost.mana_str == "{2}{G}{G}"
    assert copy.activate_only_if == DeliriumActive()
    assert copy.effect == SourceBecomesCopyOfTargetGraveyardCardUEOT()


def test_shifting_woodland_copies_until_cleanup(cube):
    state = _state()
    wood = _put(state, cube["Shifting Woodland"])
    for _ in range(4):
        _put(state, FOREST)
    beast = _zone(state, BEAST, "hand")
    state.players[0].hand.remove(beast)
    state.players[0].graveyard.append(beast)
    # Only one card type in the graveyard: no delirium.
    assert ActivateAbility(wood.id, 0) not in legal_actions(state, 0)
    _delirium_graveyard(state)
    assert ActivateAbility(wood.id, 0) in legal_actions(state, 0)
    apply_action(state, 0, ActivateAbility(wood.id, 0))
    item = state.stack[-1]
    assert item.targets[0][0] == "graveyard_card"
    target_id = item.targets[0][1]
    resolve_top_of_stack(state)
    copied = next(
        c for c in state.players[0].graveyard if c.id == target_id
    )
    assert wood.printing is copied.printing
    assert wood.original_printing.name == "Shifting Woodland"
    run_cleanup_step(state)
    assert wood.printing.name == "Shifting Woodland"
    assert wood.original_printing is None


def test_shifting_woodland_becomes_a_creature_copy(cube):
    class PickBeast(_Agent):
        def choose_target(self, state, player_id, legal_targets):
            for kind, oid in legal_targets:
                obj = next(
                    (c for c in state.players[0].graveyard if c.id == oid),
                    None,
                )
                if obj is not None and obj.printing.name == "Beast":
                    return (kind, oid)
            return legal_targets[0]

    state = _state(agent=PickBeast())
    wood = _put(state, cube["Shifting Woodland"])
    for _ in range(4):
        _put(state, FOREST)
    _delirium_graveyard(state)
    apply_action(state, 0, ActivateAbility(wood.id, 0))
    resolve_top_of_stack(state)
    assert wood.printing.name == "Beast" and is_creature_now(wood)


def test_shifting_woodland_fizzles_when_target_leaves(cube):
    state = _state()
    wood = _put(state, cube["Shifting Woodland"])
    for _ in range(4):
        _put(state, FOREST)
    _delirium_graveyard(state)
    apply_action(state, 0, ActivateAbility(wood.id, 0))
    target_id = state.stack[-1].targets[0][1]
    gy = state.players[0].graveyard
    gy.remove(next(c for c in gy if c.id == target_id))
    resolve_top_of_stack(state)
    assert wood.printing.name == "Shifting Woodland"


def test_copy_effect_noops_without_source_or_target():
    from mtg_bot.effects.generic import (
        SourceBecomesCopyOfTargetGraveyardCardUEOT,
    )

    e = SourceBecomesCopyOfTargetGraveyardCardUEOT()
    assert e.target_count_range() == (1, 1)
    assert "graveyard" in e.describe()
    state = _state()
    e.resolve(state, 0, (("graveyard_card", 99),))  # no resolving source
    state.resolving_source = _put(state, FOREST)
    e.resolve(state, 0, ())  # no targets


def test_delirium_rider_and_copy_phrase_grammar():
    assert _parse_activate_only_if_condition(
        "there are four or more card types among cards in your graveyard"
    ) == DeliriumActive()
    assert _parse_effect(
        "this land becomes a copy of target permanent card in your "
        "graveyard until end of turn"
    ) is not None


# --- Arena of Glory -----------------------------------------------------------


def test_arena_of_glory_claimed(cube):
    from mtg_bot.effects.conditions import ControlPermanent
    from mtg_bot.effects.generic import AddManaToPool
    from mtg_bot.effects.object_predicates import HasSubtype

    arena = cube["Arena of Glory"]
    assert arena.enters_tapped_unless == ControlPermanent(
        HasSubtype("Mountain"),
    )
    assert arena.produces == frozenset({"R"})
    (exert,) = arena.activated_abilities
    assert exert.is_mana_ability
    assert exert.cost.exert_self and exert.cost.tap_self
    assert "Exert ~" in exert.cost.describe()
    assert exert.effect == AddManaToPool(
        produces=(("R", 2),), grants_haste_to_creature_spell=True,
    )


def test_arena_exert_skips_next_untap_and_mana_grants_haste(cube):
    state = _state()
    arena = _put(state, cube["Arena of Glory"])
    _put(state, MOUNTAIN)
    goblin = _zone(state, make_creature("Goblin", "{1}{R}", 2, 2), "hand")
    apply_action(state, 0, ActivateAbility(arena.id, 0))
    assert arena.tapped and arena.exerted
    pool = state.players[0].mana_pool
    assert [c.color for c in pool] == ["R", "R"]
    assert all(c.grants_haste_to_creature_spell for c in pool)
    assert CastSpell(goblin.id) in legal_actions(state, 0)
    apply_action(state, 0, CastSpell(goblin.id))
    resolve_top_of_stack(state)
    assert goblin in state.battlefield
    assert "haste" in effective_keywords(state, goblin)
    # Exerted: stays tapped through the next untap step, then untaps.
    run_untap_step(state)
    assert arena.tapped and not arena.exerted
    run_untap_step(state)
    assert not arena.tapped


def test_arena_mana_on_noncreature_spell_grants_nothing(cube):
    state = _state()
    arena = _put(state, cube["Arena of Glory"])
    zap = _zone(state, make_instant("Zap", "{R}", None), "hand")
    apply_action(state, 0, ActivateAbility(arena.id, 0))
    before = list(state.continuous_effects)
    state.step = Step.PRECOMBAT_MAIN
    from mtg_bot.actions import _cast_spell

    _cast_spell(state, 0, zap.id)
    assert state.continuous_effects == before


def test_exert_and_haste_rider_grammar():
    a = _parse_activated_ability_line(
        "{R}, {T}, Exert this land: Add {R}{R}. If any of that mana is "
        "spent on a creature spell, it gains haste until end of turn."
    )
    assert a.cost.exert_self and a.is_mana_ability
    # Exert twice is nonsense; a card in hand can't be exerted.
    assert _parse_activated_ability_line(
        "Exert this land, Exert this land: Add {R}."
    ) is None
    assert _parse_activated_ability_line(
        "Exert this creature, Discard this card: Draw a card.",
        from_hand=True,
    ) is None


def test_haste_rider_mana_is_never_folded_into_produces():
    from mtg_bot.cards.parser.land_builder import _build_land_printing

    for text in (
        "{T}: Add {R}. If any of that mana is spent on a creature spell, "
        "it gains haste until end of turn.",
        "{T}: Add {R}{R}. If any of that mana is spent on a creature "
        "spell, it gains haste until end of turn.",
    ):
        p = _build_land_printing(
            {"name": "X", "type_line": "Land", "oracle_text": text}
        )
        assert p.produces == frozenset()
        (ability,) = p.activated_abilities
        assert ability.effect.grants_haste_to_creature_spell
