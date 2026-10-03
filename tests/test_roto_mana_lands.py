"""Vintage Roto P3: mana lands -- Simic Growth Chamber (karoo)."""

from __future__ import annotations

from mtg_bot.actions import PlayLand, _activate_ability, apply_action, drain_stack
from mtg_bot.cards.base import make_basic_land
from mtg_bot.cards.parser.roto_mana import parse_roto_mana_effect
from mtg_bot.effects.generic import roto_mana as rm

from tests._roto_helpers import arena, printing, put, to_hand

FOREST = make_basic_land("Forest", "G")


def test_growth_chamber_bounces_a_land_and_taps_for_two_colors():
    s = arena()
    forest = put(s, FOREST, 0)
    chamber = to_hand(s, printing("Simic Growth Chamber"), 0)
    s.players[0].agent.sacrifices = [forest.id]
    apply_action(s, 0, PlayLand(chamber.id))
    assert chamber.tapped  # enters tapped
    drain_stack(s)  # the enters trigger
    assert forest in s.players[0].hand and chamber in s.battlefield
    assert chamber.printing.produces == frozenset({"G", "U"})
    chamber.tapped = False
    _activate_ability(s, 0, chamber.id, 0)
    assert sorted(c.color for c in s.players[0].mana_pool) == ["G", "U"]


def test_growth_chamber_can_return_itself():
    s = arena()
    chamber = to_hand(s, printing("Simic Growth Chamber"), 0)
    apply_action(s, 0, PlayLand(chamber.id))
    drain_stack(s)
    assert chamber in s.players[0].hand


def test_return_your_permanent_effect_paths():
    eff = parse_roto_mana_effect("return a creature you control to its owner's hand")
    assert isinstance(eff, rm.ReturnPermanentYouControlToHand)
    assert "creature" in eff.describe()
    s = arena()
    eff.resolve(s, 0, ())  # nothing to return
    assert parse_roto_mana_effect(
        "return a frob you control to its owner's hand"
    ) is None
    # One-color runs are the base grammar's; this bucket reads mixed ones.
    assert parse_roto_mana_effect("add {G}{G}") is None


def test_shrieking_drake_rides_the_same_untargeted_bounce():
    """The generic recognizer also claims Shrieking Drake (P5's list):
    its enters trigger returns a creature you control, possibly itself."""
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.cards.base import make_creature
    from mtg_bot.game import Zone

    s = arena()
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    drake = s.new_object(printing("Shrieking Drake"), owner_id=0, zone=Zone.STACK)
    s.players[0].agent.sacrifices = [bear.id]
    put_into_battlefield(s, drake, 0)
    drain_stack(s)
    assert bear in s.players[0].hand and drake in s.battlefield


# ---------------------------------------------------------------------------
# Artifact lands
# ---------------------------------------------------------------------------


def test_artifact_land_is_played_as_the_land_drop_and_taps_for_its_color():
    from mtg_bot.actions import CastSpell
    from mtg_bot.legal import legal_actions

    s = arena()
    seat = to_hand(s, printing("Seat of the Synod"), 0)
    other = to_hand(s, printing("Great Furnace"), 0)
    acts = legal_actions(s, 0)
    assert PlayLand(seat.id) in acts
    assert not any(
        isinstance(a, CastSpell) and a.card_id == seat.id for a in acts
    )
    apply_action(s, 0, PlayLand(seat.id))
    assert seat in s.battlefield
    assert seat.printing.is_land and seat.printing.is_artifact
    assert PlayLand(other.id) not in legal_actions(s, 0)  # one land drop
    recall = to_hand(s, printing("Ancestral Recall"), 0)
    s.players[0].agent.targets = [("player", 0)]
    assert CastSpell(recall.id) in legal_actions(s, 0)
    apply_action(s, 0, CastSpell(recall.id))
    assert seat.tapped  # it paid the {U}


def test_artifact_lands_count_as_artifacts():
    from mtg_bot.actions import ActivateAbility
    from mtg_bot.legal import legal_actions

    s = arena()
    spire = put(s, printing("Spire of Industry"), 0)
    idx = next(
        i for i, a in enumerate(spire.printing.activated_abilities)
        if a.activate_only_if is not None
    )
    act = ActivateAbility(source_id=spire.id, ability_index=idx)
    assert act not in legal_actions(s, 0)
    put(s, printing("Vault of Whispers"), 0)
    assert act in legal_actions(s, 0)


def test_darksteel_citadel_is_indestructible():
    from mtg_bot.turn import destroy

    s = arena()
    citadel = put(s, printing("Darksteel Citadel"), 0)
    assert citadel.printing.produces == frozenset({"C"})
    destroy(s, citadel)
    assert citadel in s.battlefield


def test_unparsed_artifact_land_stays_unclaimed():
    from mtg_bot.cards.parser.source import build_card_record
    from tests._roto_helpers import roto_card

    record = dict(roto_card("Seat of the Synod"), oracle_text="Frobnicate.")
    assert build_card_record(record) is None
