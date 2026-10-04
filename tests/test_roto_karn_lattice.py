"""Mycosynth Lattice, Karn, the Great Creator and Liquimetal Coating
(CR 613 layers 4 and 5; ``docs/EFFECTIVE_CHARACTERISTICS_DESIGN.md``):
behavioural tests through the real cast / activate / resolve paths, the
Karn + Lattice lock, and smoke games with Magnum Opus's bot-draft deck."""

from __future__ import annotations

import random
from dataclasses import dataclass

import pytest

from mtg_bot.agents import RandomAgent

from mtg_bot.actions import ActivateAbility, CastSpell, can_pay_cost
from dataclasses import replace as _replace

from mtg_bot.cards.base import ManaCost, make_artifact, make_aura
from mtg_bot.effects.base import TriggeredAbility
from mtg_bot.effects.generic.roto_layers import (
    PutCardFromOutsideTheGameOrFaceUpExileIntoHand,
    TargetBecomesTypes,
)
from mtg_bot.effects.object_predicates import IsArtifact
from mtg_bot.effects.predicates import Event, Subject
from mtg_bot.game import (
    Zone,
    effective_card_types,
    effective_colors,
    effective_power,
    effective_toughness,
    is_artifact_now,
    is_creature_now,
)
from mtg_bot.legal import legal_actions
from mtg_bot.turn import run_cleanup_step, run_untap_step, sacrifice

from tests._roto_p5_helpers import (
    activate,
    can_activate,
    cast,
    make_state,
    place,
    printing,
    resolve_all,
    script,
    vanilla,
)

KARN = "Karn, the Great Creator"
LATTICE = "Mycosynth Lattice"
COATING = "Liquimetal Coating"


def _activations(state, pid, source):
    return [
        a for a in legal_actions(state, pid)
        if isinstance(a, ActivateAbility) and a.source_id == source.id
    ]


def _karn(state, pid=0, loyalty=5):
    karn = place(state, pid, KARN)
    karn.loyalty_counters = loyalty
    return karn


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


def test_lattice_karn_and_coating_claim_every_line():
    lattice = printing(LATTICE)
    assert lattice.all_permanents_gain_card_type == "Artifact"
    assert lattice.all_objects_colorless
    assert lattice.mana_spendable_as_any_color
    karn = printing(KARN)
    assert karn.locks_opponents_activated_abilities_of == ("Artifact",)
    assert karn.locks_activated_abilities_of == ()
    plus, minus = karn.activated_abilities
    assert plus.cost.loyalty == -1 and minus.cost.loyalty == 2
    assert isinstance(plus.effect, TargetBecomesTypes)
    assert plus.effect.types_to_add == ("Artifact", "Creature")
    assert plus.effect.pt_equal_to_mana_value
    assert plus.effect.duration.describe() == "until your next turn"
    assert plus.effect.targets[0].count_min == 0  # "up to one"
    assert isinstance(minus.effect, PutCardFromOutsideTheGameOrFaceUpExileIntoHand)
    (coat,) = printing(COATING).activated_abilities
    assert coat.cost.tap_self
    assert coat.effect.types_to_add == ("Artifact",)
    assert coat.effect.duration.describe() == "until end of turn"


# ---------------------------------------------------------------------------
# Mycosynth Lattice: layer 4
# ---------------------------------------------------------------------------


def test_lattice_makes_every_permanent_an_artifact_and_nothing_else():
    state = make_state()
    forest = place(state, 1, "Forest")
    bear = place(state, 1, vanilla(2, 2))
    walker = place(state, 1, "Jace, the Mind Sculptor")
    in_hand = place(state, 1, "Forest", Zone.HAND)
    in_yard = place(state, 1, vanilla(2, 2), Zone.GRAVEYARD)
    assert not any(is_artifact_now(state, o) for o in (forest, bear, walker))
    place(state, 0, LATTICE)
    assert effective_card_types(state, forest) == ("Land", "Artifact")
    assert is_artifact_now(state, bear) and is_creature_now(bear)
    assert effective_card_types(state, walker) == ("Planeswalker", "Artifact")
    # Cards that aren't permanents keep their types.
    assert not is_artifact_now(state, in_hand)
    assert not is_artifact_now(state, in_yard)


def test_artifact_removal_reaches_lands_and_creatures_under_lattice():
    state = make_state()
    vigor = place(state, 0, "Force of Vigor", Zone.HAND)
    forest = place(state, 1, "Forest")
    bear = place(state, 1, vanilla(2, 2))
    effect = vigor.printing.spell_effect
    assert effect.legal_targets(state, 0) == []
    place(state, 0, LATTICE)
    targets = {t[1] for t in effect.legal_targets(state, 0)}
    assert {forest.id, bear.id} <= targets


def test_lattice_leaving_ends_the_type_change():
    from mtg_bot.turn import move_off_battlefield

    state = make_state()
    lattice = place(state, 0, LATTICE)
    forest = place(state, 1, "Forest")
    assert is_artifact_now(state, forest)
    bolt = place(state, 1, "Lightning Bolt", Zone.HAND)
    assert effective_colors(state, bolt) == frozenset()
    move_off_battlefield(state, lattice, destination="graveyard")
    assert not is_artifact_now(state, forest)
    assert effective_colors(state, bolt) == frozenset({"R"})


def test_sacrificed_land_is_an_artifact_for_departure_triggers():
    """CR 603.10a: "whenever you sacrifice an artifact" looks back in time
    -- a land that was an artifact under Lattice was sacrificed as one."""
    from dataclasses import replace

    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.predicates import YOU, Controlled

    watcher_pr = replace(
        make_artifact("Scrap Watcher", "{1}"),
        triggered_abilities=(TriggeredAbility(
            event=Event.IS_SACRIFICED,
            predicate=Subject(slot=None, inner=IsArtifact()) & Controlled(YOU),
            effect=GainLife(amount=1),
        ),),
    )
    state = make_state()
    place(state, 0, watcher_pr)
    land = place(state, 0, "Forest")
    sacrifice(state, land)
    assert not state.stack  # a plain land isn't an artifact
    place(state, 0, LATTICE)
    land2 = place(state, 0, "Forest")
    sacrifice(state, land2)
    assert len(state.stack) == 1
    resolve_all(state)
    assert state.players[0].life == 21
    # In the graveyard it is a land card again (no stale snapshot).
    assert land2.zone == Zone.GRAVEYARD
    assert land2.lki_card_types is None
    assert not is_artifact_now(state, land2)


# ---------------------------------------------------------------------------
# Mycosynth Lattice: layer 5 (colorless everywhere)
# ---------------------------------------------------------------------------


def test_lattice_makes_cards_in_every_zone_colorless():
    state = make_state()
    place(state, 0, LATTICE)
    bolt = place(state, 1, "Lightning Bolt", Zone.HAND)
    library_card = place(state, 1, "Force of Will", Zone.LIBRARY)
    yard_card = place(state, 1, "Brainstorm", Zone.GRAVEYARD)
    bear = place(state, 1, vanilla(2, 2, cost="{1}{G}"))
    for obj in (bolt, library_card, yard_card, bear):
        assert effective_colors(state, obj) == frozenset()


def test_force_of_will_has_no_blue_card_to_pitch_under_lattice():
    from mtg_bot.cards.spell_costs import alternative_cost_payable

    state = make_state()
    fow = place(state, 1, "Force of Will", Zone.HAND)
    place(state, 1, "Brainstorm", Zone.HAND)
    (pitch,) = fow.printing.alternative_costs
    assert alternative_cost_payable(state, 1, fow, pitch)
    place(state, 0, LATTICE)
    assert not alternative_cost_payable(state, 1, fow, pitch)


def test_green_suns_zenith_finds_no_green_creature_under_lattice():
    state = make_state()
    gsz = place(state, 0, "Green Sun's Zenith", Zone.HAND)
    elf = place(state, 0, vanilla(1, 1, cost="{G}"), Zone.LIBRARY)
    place(state, 0, LATTICE)
    for _ in range(3):
        place(state, 0, "Forest")
    state.resolving_x_value = 1
    gsz.printing.spell_effect.resolve(state, 0, ())
    assert elf.zone == Zone.LIBRARY


def test_blue_spell_on_the_stack_is_colorless_under_lattice():
    state = make_state()
    place(state, 0, LATTICE)
    brainstorm = place(state, 0, "Brainstorm", Zone.HAND)
    place(state, 0, "Island")
    cast(state, 0, brainstorm, resolve=False)
    assert effective_colors(state, brainstorm) == frozenset()
    reb = place(state, 1, "Red Elemental Blast", Zone.HAND)
    counter_mode = reb.printing.spell_effect.modes[0]
    assert counter_mode.legal_targets(state, 1) == []


def test_lattice_and_painters_servant_resolve_by_timestamp():
    state = make_state()
    card = place(state, 1, "Lightning Bolt", Zone.HAND)
    painter = place(state, 0, "Painter's Servant")
    painter.painter_chosen_color = "U"
    painter.etb_timestamp = 1
    lattice = place(state, 0, LATTICE)
    lattice.etb_timestamp = 2
    assert effective_colors(state, card) == frozenset()  # Lattice is later
    lattice.etb_timestamp = 0
    # Lattice first (no colors), then Painter's Servant adds blue.
    assert effective_colors(state, card) == frozenset({"U"})


# ---------------------------------------------------------------------------
# Mycosynth Lattice: "spend mana as though it were mana of any color"
# ---------------------------------------------------------------------------


def test_colorless_mana_casts_colored_spells_under_lattice():
    from mtg_bot.game import ManaCoin

    state = make_state()
    state.players[0].mana_pool.append(ManaCoin(color="C"))
    brainstorm = place(state, 0, "Brainstorm", Zone.HAND)
    assert CastSpell(brainstorm.id) not in legal_actions(state, 0)
    place(state, 0, LATTICE)
    cast(state, 0, brainstorm)
    assert brainstorm.zone == Zone.GRAVEYARD
    assert state.players[0].mana_pool == []  # the {C} paid the {U}


def test_lattice_without_abilities_keeps_layers_but_not_the_mana_rule():
    state = make_state()
    lattice = place(state, 0, LATTICE)
    forest = place(state, 1, "Forest")
    place(state, 0, "Ancient Tomb")
    state.add_continuous_effect(
        source_id=lattice.id, layer=6, kind="lose_all_abilities",
        target_id=lattice.id,
    )
    assert is_artifact_now(state, forest)  # layer 4 ran before layer 6
    assert effective_colors(state, forest) == frozenset()
    assert not can_pay_cost(state, 0, ManaCost(colored=(("U", 1),)))


# ---------------------------------------------------------------------------
# Karn, the Great Creator: the static, and the Karn + Lattice lock
# ---------------------------------------------------------------------------


def test_karn_locks_only_opponents_artifacts():
    state = make_state()
    _karn(state, 0)
    mine = place(state, 0, "Sol Ring")
    theirs = place(state, 1, "Sol Ring")
    their_forest = place(state, 1, "Forest")
    assert _activations(state, 0, mine)
    assert not _activations(state, 1, theirs)
    # A land that isn't an artifact still pays.
    assert can_pay_cost(state, 1, ManaCost(colored=(("G", 1),)))
    assert their_forest in state.battlefield


def test_karn_plus_lattice_locks_the_opponents_lands_and_walkers():
    """The famous lock: under Mycosynth Lattice every permanent is an
    artifact, so Karn stops every activated ability of the opponent's
    permanents -- their lands' mana abilities included."""
    state = make_state(step=None)
    from mtg_bot.turn import Step

    state.step = Step.PRECOMBAT_MAIN
    _karn(state, 0)
    place(state, 0, LATTICE)
    place(state, 1, "Forest")
    wasteland = place(state, 1, "Wasteland")
    jace = place(state, 1, "Jace, the Mind Sculptor")
    jace.loyalty_counters = 3
    my_forest = place(state, 0, "Forest")
    state.active_player_idx = 1
    state.priority_player_idx = 1
    assert not can_pay_cost(state, 1, ManaCost(generic=1))
    assert not _activations(state, 1, wasteland)
    assert not _activations(state, 1, jace)
    # Karn's controller is untouched.
    assert can_pay_cost(state, 0, ManaCost(colored=(("G", 1),)))
    assert my_forest.controller_id == 0
    # The lock lifts when Karn leaves.
    from mtg_bot.turn import move_off_battlefield

    karn = next(o for o in state.battlefield if o.printing.name == KARN)
    move_off_battlefield(state, karn, destination="graveyard")
    assert can_pay_cost(state, 1, ManaCost(generic=1))
    assert _activations(state, 1, jace)


# ---------------------------------------------------------------------------
# Karn's +1
# ---------------------------------------------------------------------------


def test_karn_plus_one_animates_until_your_next_turn():
    state = make_state()
    karn = _karn(state, 0)
    ring = place(state, 1, "Sol Ring")
    script(state, 0, "target", ("permanent", ring.id))
    activate(state, 0, karn, 0)
    assert karn.loyalty_counters == 6
    assert is_creature_now(ring) and is_artifact_now(state, ring)
    assert (effective_power(state, ring), effective_toughness(state, ring)) == (1, 1)
    # Survives this cleanup and the opponent's whole turn...
    run_cleanup_step(state)
    state.active_player_idx = 1
    run_untap_step(state)
    assert is_creature_now(ring)
    run_cleanup_step(state)
    # ... and ends as Karn's controller's next turn begins.
    state.active_player_idx = 0
    run_untap_step(state)
    assert not is_creature_now(ring)
    assert effective_card_types(state, ring) == ("Artifact",)


def test_karn_plus_one_on_a_land_under_lattice_kills_it():
    state = make_state()
    karn = _karn(state, 0)
    place(state, 0, LATTICE)
    forest = place(state, 1, "Forest")
    script(state, 0, "target", ("permanent", forest.id))
    activate(state, 0, karn, 0)
    assert forest.zone == Zone.GRAVEYARD  # a 0/0 artifact creature


def test_karn_plus_one_with_no_target_still_adds_loyalty():
    state = make_state()
    karn = _karn(state, 0)
    activate(state, 0, karn, 0)
    assert karn.loyalty_counters == 6


def test_karn_plus_one_makes_a_new_artifact_summoning_sick():
    state = make_state()
    karn = _karn(state, 0)
    ring = place(state, 0, "Sol Ring")
    ring.entered_battlefield_turn = state.turn_number
    ring.summoning_sick = False
    script(state, 0, "target", ("permanent", ring.id))
    activate(state, 0, karn, 0)
    assert ring.summoning_sick


# ---------------------------------------------------------------------------
# Karn's -2
# ---------------------------------------------------------------------------


def test_karn_minus_two_wishes_lattice_from_the_sideboard():
    state = make_state()
    karn = _karn(state, 0)
    state.players[0].sideboard = (printing(LATTICE), printing("Smokestack"))
    script(state, 0, "mode", 0)  # "reveal Mycosynth Lattice ..."
    activate(state, 0, karn, 1)
    assert karn.loyalty_counters == 3
    (card,) = state.players[0].hand
    assert card.printing.name == LATTICE
    assert [p.name for p in state.players[0].sideboard] == ["Smokestack"]


def test_karn_minus_two_takes_a_face_up_artifact_from_exile_not_a_face_down_one():
    state = make_state()
    karn = _karn(state, 0)
    face_up = place(state, 0, "Sol Ring", Zone.EXILE)
    face_down = place(state, 0, "Mox Sapphire", Zone.EXILE)
    face_down.exiled_face_down = True
    place(state, 1, "Black Lotus", Zone.EXILE)  # not owned
    place(state, 0, "Brainstorm", Zone.EXILE)  # not an artifact
    effect = karn.printing.activated_abilities[1].effect
    assert effect._exile_options(state, 0) == [face_up]
    script(state, 0, "mode", 0)  # "take Sol Ring from exile"
    activate(state, 0, karn, 1)
    assert face_up.zone == Zone.HAND and face_up in state.players[0].hand
    assert face_down in state.players[0].exile


def test_karn_minus_two_may_take_nothing():
    state = make_state()
    karn = _karn(state, 0)
    state.players[0].sideboard = (printing(LATTICE),)
    script(state, 0, "mode", 1)  # "nothing"
    activate(state, 0, karn, 1)
    assert state.players[0].hand == []
    assert len(state.players[0].sideboard) == 1


def test_necropotence_cards_are_face_down_until_they_leave_exile():
    state = make_state()
    necro = place(state, 0, "Necropotence")
    place(state, 0, "Sol Ring", Zone.LIBRARY)
    necro.printing.activated_abilities[0].effect.resolve(state, 0, ())
    (exiled,) = state.players[0].exile
    assert exiled.exiled_face_down
    karn_effect = printing(KARN).activated_abilities[1].effect
    assert karn_effect._exile_options(state, 0) == []
    # Its delayed trigger returns it to hand: no longer face down.
    from mtg_bot.turn import run_delayed_end_step_triggers

    state.step = None
    from mtg_bot.turn import Step

    state.step = Step.END
    run_delayed_end_step_triggers(state)
    resolve_all(state)
    assert exiled.zone == Zone.HAND
    assert not exiled.exiled_face_down


# ---------------------------------------------------------------------------
# Liquimetal Coating
# ---------------------------------------------------------------------------


def test_liquimetal_coating_makes_a_land_an_artifact_until_end_of_turn():
    state = make_state()
    coating = place(state, 0, COATING)
    forest = place(state, 1, "Forest")
    script(state, 0, "target", ("permanent", forest.id))
    activate(state, 0, coating, 0)
    assert coating.tapped
    assert is_artifact_now(state, forest)
    vigor = place(state, 0, "Force of Vigor", Zone.HAND)
    assert ("permanent", forest.id) in [
        (k, i) for k, i in vigor.printing.spell_effect.legal_targets(state, 0)
    ] or any(t[1] == forest.id for t in vigor.printing.spell_effect.legal_targets(state, 0))
    run_cleanup_step(state)
    assert not is_artifact_now(state, forest)


def test_liquimetal_coating_plus_karn_shuts_one_land_off():
    state = make_state()
    _karn(state, 0)
    coating = place(state, 0, COATING)
    forest = place(state, 1, "Forest")
    assert can_pay_cost(state, 1, ManaCost(colored=(("G", 1),)))
    script(state, 0, "target", ("permanent", forest.id))
    activate(state, 0, coating, 0)
    assert not can_pay_cost(state, 1, ManaCost(colored=(("G", 1),)))


# ---------------------------------------------------------------------------
# Unable to Scream: its lines and engine support. The card is also a
# Duskmourn printing (the default ``all`` pool), and the roto grammar is
# switched off for EoE-era printings so their claimed set can't move, so it
# stays unclaimed (docs/SEARCH_LIMITATIONS.md); its shapes are pinned here.
# ---------------------------------------------------------------------------


def _unable_to_scream_like():
    from mtg_bot.cards.parser.roto_board import parse_roto_board_line

    fields: dict = {}
    for line in (
        "Enchanted creature loses all abilities and is a Toy artifact "
        "creature with base power and toughness 0/2 in addition to its "
        "other types.",
        "As long as enchanted creature is face down, it can't be turned "
        "face up.",
    ):
        parsed = parse_roto_board_line(line, {"name": "Scream Test"})
        assert parsed is not None
        fields.update(parsed.fields)
    return _replace(make_aura("Scream Test", "{U}"), **fields)


def test_unable_to_scream_lines_parse_to_aura_fields():
    aura = _unable_to_scream_like()
    assert aura.attached_grants_card_types == ("Artifact", "Creature")
    assert aura.attached_grants_subtype == "Toy"
    assert aura.attached_sets_base_pt == (0, 2)
    assert aura.attached_grants_lose_all_abilities
    assert aura.attached_prevents_turning_face_up


def test_attached_card_types_and_face_up_restriction():
    from mtg_bot.actions import TurnFaceUp, apply_aura_static_grants_on_attach
    from mtg_bot.effects.generic.roto_layers import turning_face_up_prevented
    from mtg_bot.game import effective_power, effective_subtypes, effective_toughness
    from mtg_bot.legal import legal_actions
    from mtg_bot.turn import move_off_battlefield

    state = make_state()
    bear = place(state, 1, vanilla(3, 3, cost="{G}"))
    aura = place(state, 0, _unable_to_scream_like())
    aura.attached_to = bear.id
    apply_aura_static_grants_on_attach(state, aura, bear, 0)
    assert effective_card_types(state, bear) == ("Creature", "Artifact")
    assert "Toy" in effective_subtypes(state, bear)
    assert (effective_power(state, bear), effective_toughness(state, bear)) == (0, 2)
    # Face down: can't be turned face up while the Aura is attached.
    assert not turning_face_up_prevented(state, bear)
    bear.face_down = True
    for _ in range(2):
        place(state, 1, "Forest")
    assert turning_face_up_prevented(state, bear)
    state.active_player_idx = state.priority_player_idx = 1
    assert TurnFaceUp(card_id=bear.id) not in legal_actions(state, 1)
    move_off_battlefield(state, aura, destination="graveyard")
    assert not turning_face_up_prevented(state, bear)
    assert TurnFaceUp(card_id=bear.id) in legal_actions(state, 1)


def test_attached_creature_type_entry_sets_and_clears_the_cache():
    from mtg_bot.actions import apply_aura_static_grants_on_attach
    from mtg_bot.turn import move_off_battlefield

    state = make_state()
    ring = place(state, 1, "Sol Ring")
    aura = place(state, 0, _unable_to_scream_like())
    aura.attached_to = ring.id
    apply_aura_static_grants_on_attach(state, aura, ring, 0)
    assert is_creature_now(ring)
    move_off_battlefield(state, aura, destination="graveyard")
    assert not is_creature_now(ring)


# ---------------------------------------------------------------------------
# Smoke games: Magnum Opus's Colorless Workshop Prison deck
# ---------------------------------------------------------------------------

# decks["0"] of the user's roto bot draft (C:\Users\Gregg Keithley\
# roto-bot-draft\state.json), with its sideboard. The deck plays 10
# Wastes, which the roto pool data doesn't contain (only the five basic
# land types are added to data/cube_roto.json) -- the smoke games use
# Island in their place (the deck's spells are colorless, so this only
# changes which basic taps for mana).
_MAGNUM_OPUS_MAIN = [
    "Black Lotus", "Mana Crypt", "Mana Vault", "Basalt Monolith",
    "Coalition Relic", "Coveted Jewel", "Chalice of the Void",
    "Sphere of Resistance", "Thorn of Amethyst", "Trinisphere", "Tangle Wire",
    "Ensnaring Bridge", "Phyrexian Revoker", "Walking Ballista",
    "Lodestone Golem", "Phyrexian Metamorph", "Argentum Masticore",
    "Kaldra Compleat", KARN, "Karn, Scion of Urza", "Tezzeret, Cruel Captain",
    "Ugin, Eye of the Storms", "Ugin, the Spirit Dragon", "Memory Jar",
    "Mystic Forge", "The Mightstone and Weakstone", "Kozilek's Command",
    "Ancient Tomb", "Mishra's Workshop", "City of Traitors", "Inkmoth Nexus",
    "The Tabernacle at Pendrell Vale", "Dark Depths", "Thespian's Stage",
    "Maze of Ith",
] + ["Island"] * 10
_MAGNUM_OPUS_SIDEBOARD = [LATTICE, "Smokestack"]


@pytest.fixture(scope="module")
def roto_source():
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.cards.source import get_active_source, set_active_source

    prior = get_active_source()
    set_active_source(OracleParserCardSource(pool="roto"))
    try:
        yield
    finally:
        set_active_source(prior)


def test_magnum_opus_deck_is_fully_claimed(roto_source):
    from mtg_bot.cards.source import get_active_source

    printings = get_active_source().get_printings()
    missing = sorted(
        {n for n in _MAGNUM_OPUS_MAIN + _MAGNUM_OPUS_SIDEBOARD} - set(printings)
    )
    assert missing == []


@dataclass
class _CappedRandomAgent(RandomAgent):
    """A RandomAgent that passes after `cap` actions in one turn: the deck's
    Basalt Monolith ("{3}: Untap") would otherwise let a random seat tap and
    untap it forever."""

    cap: int = 120
    _turn: int = -1
    _taken: int = 0

    def choose_action(self, state, player_id, legal):
        from mtg_bot.actions import PassPriority

        if state.turn_number != self._turn:
            self._turn, self._taken = state.turn_number, 0
        self._taken += 1
        if self._taken > self.cap:
            return PassPriority()
        return super().choose_action(state, player_id, legal)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_magnum_opus_random_games_run_to_completion(roto_source, seed):
    from mtg_bot.simulate import (
        _advance_to_next_active_player,
        run_turn,
        setup_game,
    )

    opponent = [
        "Lightning Bolt", "Brainstorm", "Force of Will", "Sol Ring",
        "Mox Sapphire", "Wasteland", "Jace, the Mind Sculptor", "Abrade",
        "Force of Vigor", "Pyroblast", "Red Elemental Blast", "Swords to Plowshares",
    ] * 3 + ["Island"] * 12 + ["Mountain"] * 12
    state = setup_game(
        agents=[_CappedRandomAgent(rng=random.Random(seed)),
                _CappedRandomAgent(rng=random.Random(seed + 100))],
        decks=[list(_MAGNUM_OPUS_MAIN), opponent],
        seed=seed, enable_mulligans=False,
        sideboards=[list(_MAGNUM_OPUS_SIDEBOARD), []],
    )
    while not state.is_over() and state.turn_number <= 30:
        run_turn(state)
        if state.is_over():
            break
        state.turn_number += 1
        _advance_to_next_active_player(state)
    assert state.turn_number >= 1


# ---------------------------------------------------------------------------
# Grammar edges and effect edges
# ---------------------------------------------------------------------------


def test_unable_to_scream_stays_unclaimed_behind_the_eoe_era_guard():
    from mtg_bot.cards.parser.creature_rmc_grammar import is_eoe_only_printing
    from mtg_bot.cards.parser.source import build_card_record

    from tests._roto_helpers import roto_card

    assert is_eoe_only_printing("Unable to Scream")
    assert build_card_record(roto_card("Unable to Scream")) is None


def test_layer_line_recognizers_decline_other_shapes():
    from mtg_bot.cards.parser.roto_board import parse_roto_board_line
    from mtg_bot.cards.parser.roto_layers import parse_all_objects_color_line

    card = {"name": "X"}
    for line in (
        "All creatures are artifacts in addition to their other types.",
        "All permanents are lands in addition to their other types.",
        "Enchanted creature is a Toy artifact creature with base power and "
        "toughness 0/2.",
    ):
        assert parse_roto_board_line(line, card) is None
    assert parse_all_objects_color_line(
        "All cards that aren't on the battlefield, spells, and permanents are "
        "the chosen color in addition to their other colors."
    ) == {"paints_all_objects_chosen_color_at_etb": True}
    assert parse_all_objects_color_line("All permanents are colorless.") is None
    creature_only = parse_roto_board_line(
        "Enchanted creature is a Treefolk creature with base power and "
        "toughness 0/4 in addition to its other types.", card,
    )
    assert creature_only.fields == {
        "attached_grants_card_types": ("Creature",),
        "attached_sets_base_pt": (0, 4),
        "attached_grants_subtype": "Treefolk",
    }


def test_layer_effect_grammar_declines_setting_types_and_bad_durations():
    from mtg_bot.cards.parser.roto_layers import parse_roto_layer_effect

    for phrase in (
        # No duration / two durations.
        "target permanent becomes an artifact in addition to its other types",
        "until your next turn, target permanent becomes an artifact in "
        "addition to its other types until end of turn",
        # Without "in addition", the type would be SET (CR 205.1a).
        "target permanent becomes an artifact until end of turn",
        "target land becomes a creature until end of turn",
        # An unparsable noun phrase.
        "target blorp becomes an artifact in addition to its other types "
        "until end of turn",
        # Mismatched descriptors.
        "you may reveal an artifact card you own from outside the game or "
        "choose a face-up creature card you own in exile. Put that card "
        "into your hand",
        "you may reveal a blorp card you own from outside the game or choose "
        "a face-up blorp card you own in exile. Put that card into your hand",
    ):
        assert parse_roto_layer_effect(phrase) is None, phrase
    eff = parse_roto_layer_effect(
        "target creature becomes an artifact creature in addition to its "
        "other types until end of turn"
    )
    assert eff.types_to_add == ("Artifact", "Creature")
    assert "until end of turn" in eff.describe()


def test_target_becomes_types_fizzles_on_an_illegal_target():
    state = make_state()
    karn = _karn(state, 0)
    ring = place(state, 1, "Sol Ring")
    effect = karn.printing.activated_abilities[0].effect
    ring.permanent_is_creature = True  # no longer a noncreature artifact
    effect.resolve(state, 0, (("permanent", ring.id),))
    assert not any(
        ce.kind == "set_base_pt" for ce in state.continuous_effects
    )
    assert "with power and toughness each equal to its mana value" in (
        effect.describe()
    )


def test_karn_minus_two_with_nothing_to_take_or_no_agent():
    state = make_state()
    effect = printing(KARN).activated_abilities[1].effect
    effect.resolve(state, 0, ())
    assert state.players[0].hand == []
    state.players[0].sideboard = (printing(LATTICE),)
    state.players[0].agent = None
    effect.resolve(state, 0, ())
    assert state.players[0].hand == []
    assert "outside the game" in effect.describe()


def test_an_aura_without_its_abilities_doesnt_stop_turning_face_up():
    from mtg_bot.effects.generic.roto_layers import turning_face_up_prevented

    state = make_state()
    bear = place(state, 1, vanilla(2, 2))
    bear.face_down = True
    aura = place(state, 0, _unable_to_scream_like())
    aura.attached_to = bear.id
    assert turning_face_up_prevented(state, bear)
    state.add_continuous_effect(
        source_id=aura.id, layer=6, kind="lose_all_abilities", target_id=aura.id,
    )
    assert not turning_face_up_prevented(state, bear)


def test_magnum_opus_pimc_search_game_completes(roto_source):
    """A heuristic-search seat (clone / determinize / resolution channel)
    with Karn, Lattice and the sideboard in play."""
    from mtg_bot.search import (
        MCTS, PIMC, Budget, MtgGameStateAdapter, RandomChoice,
    )
    from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
    from mtg_bot.search.protocol import CHANCE_PLAYER
    from mtg_bot.simulate import setup_game

    seed = 4
    opponent = ["Lightning Bolt", "Brainstorm", "Sol Ring", "Wasteland",
                "Force of Vigor", "Abrade"] * 4 + ["Island"] * 8 + ["Mountain"] * 8
    state = MtgGameStateAdapter(setup_game(
        [_CappedRandomAgent(rng=random.Random(1)),
         _CappedRandomAgent(rng=random.Random(2))],
        decks=[list(_MAGNUM_OPUS_MAIN), opponent], seed=seed,
        enable_mulligans=False,
        sideboards=[list(_MAGNUM_OPUS_SIDEBOARD), []],
    ))
    pimc = PIMC(
        inner_factory=lambda: MCTS(
            evaluator=MtgHeuristicEvaluator(),
            budget_factory=lambda: Budget(max_nodes=8),
            rng=random.Random(seed + 100),
        ),
        samples=1, rng=random.Random(seed + 200),
    )
    strategies = {0: pimc, 1: RandomChoice(rng=random.Random(7))}
    rng = random.Random(3)
    decisions = 0
    while not state.is_terminal() and decisions < 400:
        active = state.active_player()
        if active == CHANCE_PLAYER:
            outcomes = state.chance_outcomes()
            decision = rng.choices(
                [d for d, _ in outcomes], weights=[w for _, w in outcomes], k=1,
            )[0]
        else:
            decision = strategies[active].choose(state, active)
            assert decision in state.legal_decisions()
        state.apply(decision)
        decisions += 1
    assert decisions > 0
