"""Vintage Roto P5: untap & upkeep prison -- Smokestack, Tangle Wire
(Fading on an artifact), The Tabernacle at Pendrell Vale (a triggered
ability granted to every creature), Back to Basics and Winter Orb."""

from __future__ import annotations

import pytest

from mtg_bot.actions import put_into_battlefield
from mtg_bot.cards.demo_layers import HUMILITY
from mtg_bot.cards.parser.roto_board import (
    apply_board_fields,
    parse_roto_board_effect,
    parse_roto_board_line,
)
from mtg_bot.effects.generic.roto_board import (
    DestroySourceUnlessPay,
    EventPlayerActsPerSourceCounter,
)
from mtg_bot.effects.value_predicates import IsPermanent
from mtg_bot.game import Zone, counter_count, set_named_counters
from mtg_bot.roto_board_statics import (
    DoesntUntap,
    GrantsTriggerToCreatures,
    UntapLimit,
    granted_triggers,
)
from mtg_bot.turn import (
    Step,
    run_beginning_of_upkeep_triggers,
    run_untap_step,
)

from tests._roto_p5_helpers import (
    lands,
    make_state,
    place,
    printing,
    resolve_all,
    script,
    vanilla,
)


def _upkeep(state, active: int) -> None:
    state.active_player_idx = active
    state.priority_player_idx = active
    state.step = Step.UPKEEP
    run_beginning_of_upkeep_triggers(state)
    resolve_all(state)


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


def test_event_player_phrases():
    sac = parse_roto_board_effect(
        "that player sacrifices a permanent of their choice for each soot "
        "counter on this artifact"
    )
    assert sac == EventPlayerActsPerSourceCounter(
        action="sacrifice", kind="soot", permanent_filter=IsPermanent(),
        label="permanent",
    )
    tap = parse_roto_board_effect(
        "that player taps an untapped artifact, creature, or land they "
        "control for each fade counter on this artifact"
    )
    assert tap.action == "tap" and tap.kind == "fade"
    assert "taps an untapped" in tap.describe()
    assert "sacrifices a permanent" in sac.describe()
    assert parse_roto_board_effect(
        "that player sacrifices a gizmo of their choice for each soot "
        "counter on this artifact"
    ) is None
    assert parse_roto_board_effect(
        "destroy this creature unless you pay {1}"
    ) == DestroySourceUnlessPay(cost="{1}")
    assert parse_roto_board_effect(
        "destroy this creature unless you pay {Q}"
    ) is None
    with pytest.raises(ValueError):
        EventPlayerActsPerSourceCounter(
            action="exile", kind="x", permanent_filter=IsPermanent(),
        )


def test_untap_rule_lines():
    b2b = parse_roto_board_line(
        "Nonbasic lands don't untap during their controllers' untap steps.",
        {"name": "Back to Basics"},
    )
    (rule,) = b2b.fields["board_rules"]
    assert isinstance(rule, DoesntUntap) and "untap steps" in rule.describe()
    orb = parse_roto_board_line(
        "As long as this artifact is untapped, players can't untap more "
        "than one land during their untap steps.",
        {"name": "Winter Orb"},
    )
    (rule,) = orb.fields["board_rules"]
    assert rule == UntapLimit(
        permanent_filter=rule.permanent_filter, limit=1,
        while_source_untapped=True, label="land",
    )
    assert rule.describe().startswith("As long as")
    assert parse_roto_board_line(
        "Players can't untap more than two lands during their untap steps.",
        {"name": "X"},
    ).fields["board_rules"][0].limit == 2
    assert parse_roto_board_line(
        "Gizmos don't untap during their controllers' untap steps.",
        {"name": "X"},
    ) is None
    assert parse_roto_board_line(
        "Players can't untap more than one gizmo during their untap steps.",
        {"name": "X"},
    ) is None


def test_granted_trigger_line_requires_a_triggered_ability():
    assert parse_roto_board_line(
        'All creatures have "Flying."', {"name": "X"},
    ) is None
    tab = parse_roto_board_line(
        'All creatures have "At the beginning of your upkeep, destroy this '
        'creature unless you pay {1}."',
        {"name": "The Tabernacle at Pendrell Vale"},
    )
    (rule,) = tab.fields["board_rules"]
    assert isinstance(rule, GrantsTriggerToCreatures)
    assert "destroy this creature" in rule.describe()


def test_fading_line_and_field_accumulation():
    from dataclasses import replace

    line = parse_roto_board_line("Fading 4", {"name": "Tangle Wire"})
    assert line.fields == {"enters_with_named_counters": (("fade", 4),)}
    base = replace(printing("Tangle Wire"), enters_with_named_counters=(
        ("oil", 1),
    ))
    merged = apply_board_fields(base, line.fields)
    assert merged.enters_with_named_counters == (("oil", 1), ("fade", 4))
    assert apply_board_fields(base, {}) is base


# ---------------------------------------------------------------------------
# Smokestack
# ---------------------------------------------------------------------------


def test_smokestack_grows_and_taxes_each_player():
    state = make_state()
    stack = place(state, 0, "Smokestack")
    _upkeep(state, 0)
    # Both triggers fire in the controller's upkeep; the engine's fixed
    # order (CR 603.3b choice not offered) resolves the sacrifice first,
    # with no soot counter yet.
    assert counter_count(stack, "soot") == 1
    assert stack in state.battlefield
    opp = place(state, 1, vanilla(1, 1, name="Opp"))
    _upkeep(state, 1)
    assert opp in state.players[1].graveyard
    _upkeep(state, 0)
    # One soot counter: the controller sacrifices their only permanent.
    assert stack in state.players[0].graveyard


def test_smokestack_each_player_sacrifices_per_soot_counter():
    state = make_state()
    stack = place(state, 0, "Smokestack")
    set_named_counters(stack, "soot", 2)
    a, b, c = (place(state, 1, vanilla(1, 1, name=f"Opp {i}")) for i in range(3))
    script(state, 1, "sacrifice", c.id, a.id)
    _upkeep(state, 1)
    assert a in state.players[1].graveyard and c in state.players[1].graveyard
    assert b in state.battlefield
    assert stack in state.battlefield  # nothing of player 0's is touched


def test_smokestack_controller_may_decline_a_counter():
    state = make_state()
    stack = place(state, 0, "Smokestack")
    lands(state, 0, "Island", 2)
    script(state, 0, "yes_no", False)
    _upkeep(state, 0)
    assert counter_count(stack, "soot") == 0
    assert stack in state.battlefield


# ---------------------------------------------------------------------------
# Tangle Wire
# ---------------------------------------------------------------------------


def test_tangle_wire_enters_with_fade_counters_and_taps_permanents():
    state = make_state()
    wire = state.new_object(printing("Tangle Wire"), owner_id=0, zone=Zone.HAND)
    put_into_battlefield(state, wire, 0)
    assert counter_count(wire, "fade") == 4
    opp_lands = lands(state, 1, "Mountain", 3)
    bear = place(state, 1, vanilla(2, 2))
    _upkeep(state, 1)
    tapped = [o for o in opp_lands + [bear] if o.tapped]
    assert len(tapped) == 4
    assert not wire.tapped


def test_tangle_wire_fades_on_its_controllers_upkeep_then_dies():
    state = make_state()
    wire = place(state, 0, "Tangle Wire")
    set_named_counters(wire, "fade", 1)
    island = place(state, 0, "Island")
    _upkeep(state, 0)
    assert counter_count(wire, "fade") == 0
    island.tapped = False
    wire.tapped = False
    _upkeep(state, 0)
    assert wire in state.players[0].graveyard


def test_tangle_wire_taps_only_untapped_permanents_of_that_player():
    state = make_state()
    wire = place(state, 0, "Tangle Wire")
    set_named_counters(wire, "fade", 3)
    land = place(state, 1, "Island", tapped=True)
    bear = place(state, 1, vanilla(2, 2))
    mine = place(state, 0, "Island")
    _upkeep(state, 1)
    assert bear.tapped and land.tapped
    assert not mine.tapped


# ---------------------------------------------------------------------------
# The Tabernacle at Pendrell Vale
# ---------------------------------------------------------------------------


def test_tabernacle_taxes_each_creature_on_its_controllers_upkeep():
    state = make_state()
    place(state, 1, "The Tabernacle at Pendrell Vale")
    kept = place(state, 0, vanilla(2, 2, name="Kept"))
    lost = place(state, 0, vanilla(3, 3, name="Lost"))
    theirs = place(state, 1, vanilla(1, 1, name="Theirs"))
    lands(state, 0, "Plains", 1)
    _upkeep(state, 0)
    # One {1} available: the first trigger to resolve is paid, the other
    # creature is destroyed. The opponent's creature isn't asked.
    survivors = [o for o in (kept, lost) if o in state.battlefield]
    assert len(survivors) == 1
    assert theirs in state.battlefield


def test_tabernacle_declining_destroys_the_creature():
    state = make_state()
    place(state, 0, "The Tabernacle at Pendrell Vale")
    bear = place(state, 0, vanilla(2, 2))
    lands(state, 0, "Plains", 1)
    script(state, 0, "yes_no", False)
    _upkeep(state, 0)
    assert bear in state.players[0].graveyard


def test_tabernacle_grant_and_humility_follow_timestamps():
    state = make_state()
    tab = place(state, 0, "The Tabernacle at Pendrell Vale")
    bear = place(state, 1, vanilla(2, 2))
    tab.etb_timestamp, bear.etb_timestamp = 1, 2
    assert granted_triggers(state) == [
        (bear, tab.printing.board_rules[0].ability),
    ]
    humility = place(state, 1, HUMILITY)
    humility.etb_timestamp = 3        # later wipe removes the grant
    assert granted_triggers(state) == []
    humility.etb_timestamp = 0        # earlier wipe doesn't
    assert len(granted_triggers(state)) == 1


def test_tabernacle_unless_pay_noop_when_creature_gone():
    state = make_state()
    eff = DestroySourceUnlessPay(cost="{1}")
    bear = place(state, 0, vanilla(2, 2))
    state.battlefield.remove(bear)
    state.resolving_source = bear
    eff.resolve(state, 0)
    state.resolving_source = None
    assert eff.describe() == "destroy this creature unless you pay {1}"


# ---------------------------------------------------------------------------
# Back to Basics / Winter Orb
# ---------------------------------------------------------------------------


def _untap(state, active):
    state.active_player_idx = active
    state.step = Step.UNTAP
    run_untap_step(state)


def test_back_to_basics_holds_nonbasic_lands():
    state = make_state()
    place(state, 1, "Back to Basics")
    sea = place(state, 0, "Underground Sea", tapped=True)
    island = place(state, 0, "Island", tapped=True)
    bear = place(state, 0, vanilla(2, 2), tapped=True, sick=True)
    _untap(state, 0)
    assert sea.tapped
    assert not island.tapped and not bear.tapped
    assert not bear.summoning_sick


def test_winter_orb_lets_one_land_untap_of_the_players_choice():
    state = make_state()
    place(state, 1, "Winter Orb")
    l1, l2, l3 = lands(state, 0, "Island", 3)
    for land in (l1, l2, l3):
        land.tapped = True
    bear = place(state, 0, vanilla(2, 2), tapped=True)
    script(state, 0, "target", ("permanent", l2.id))
    _untap(state, 0)
    assert [l.tapped for l in (l1, l2, l3)] == [True, False, True]
    assert not bear.tapped


def test_winter_orb_is_off_while_tapped():
    state = make_state()
    orb = place(state, 1, "Winter Orb", tapped=True)
    l1, l2 = lands(state, 0, "Island", 2)
    l1.tapped = l2.tapped = True
    _untap(state, 0)
    assert not l1.tapped and not l2.tapped
    assert orb.tapped  # the opponent's untap step hasn't come


def test_winter_orb_and_back_to_basics_together():
    state = make_state()
    place(state, 1, "Winter Orb")
    place(state, 1, "Back to Basics")
    sea = place(state, 0, "Underground Sea", tapped=True)
    island = place(state, 0, "Island", tapped=True)
    _untap(state, 0)
    # The nonbasic can't untap; the one allowed untap goes to the Island.
    assert sea.tapped and not island.tapped


def test_untap_rules_skip_stunned_permanents():
    state = make_state()
    place(state, 1, "Winter Orb")
    stunned, plain = lands(state, 0, "Island", 2)
    stunned.tapped = plain.tapped = True
    stunned.stun_counters = 1
    _untap(state, 0)
    assert not plain.tapped
    assert stunned.tapped and stunned.stun_counters == 0
