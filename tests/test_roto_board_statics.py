"""Edge cases of ``mtg_bot.roto_board_statics`` (Vintage Roto P5 board
rules) not reached by the per-card tests: self-only rules, timestamp
interactions of granted triggers with "loses all abilities", the combat
event dispatchers' empty paths, and the untap / hexproof helpers."""

from __future__ import annotations

from mtg_bot.cards.demo_layers import HUMILITY
from mtg_bot.roto_board_statics import (
    CantAttack,
    GRANT_MARK,
    _registry_granted,
    _wiped_after,
    fire_becomes_blocked,
    fire_combat_damage_dealt,
    player_hexproof_from_source,
    untap_step_held,
)

from tests._roto_p5_helpers import make_state, place, printing, vanilla


def test_self_only_rule_spares_other_creatures():
    state = make_state()
    source = place(state, 0, vanilla(1, 1, name="Source"))
    other = place(state, 0, vanilla(1, 1, name="Other"))
    rule = CantAttack(self_only=True)
    assert rule.applies(state, source, source)
    assert not rule.applies(state, source, other)
    assert rule.describe() == "This creature can't attack."


def test_wiped_after_reads_registry_and_humility_timestamps():
    state = make_state()
    bear = place(state, 0, vanilla(2, 2))
    assert not _wiped_after(state, bear, 0)
    state.add_continuous_effect(
        source_id=-1, layer=6, kind="lose_all_abilities", target_id=bear.id,
    )
    entry_ts = state.continuous_effects[-1].timestamp
    assert _wiped_after(state, bear, entry_ts - 1)
    assert not _wiped_after(state, bear, entry_ts)
    state.continuous_effects.clear()
    humility = place(state, 1, HUMILITY)
    humility.etb_timestamp = 50
    assert _wiped_after(state, bear, 10)
    assert not _wiped_after(state, bear, 60)


def _thief_grant(state, obj, ts_shift=0):
    ability = printing("Thief of Existence").triggered_abilities[0].effect.ability
    state.add_continuous_effect(
        source_id=-1, layer=6, kind="grant_triggered_ability",
        target_id=obj.id, params=(ability, GRANT_MARK),
    )
    return ability


def test_registry_grants_respect_later_wipes():
    state = make_state()
    bear = place(state, 0, vanilla(2, 2))
    ability = _thief_grant(state, bear)
    assert _registry_granted(state, [bear]) == [(bear, ability)]
    # A later registry wipe removes it from the effective abilities.
    state.add_continuous_effect(
        source_id=-1, layer=6, kind="lose_all_abilities", target_id=bear.id,
    )
    assert _registry_granted(state, [bear]) == []
    # A later Humility-style wipe does too.
    state.continuous_effects.pop()
    humility = place(state, 1, HUMILITY)
    humility.etb_timestamp = 10_000
    assert _registry_granted(state, [bear]) == []
    # Unmarked grants and grants for other objects are ignored.
    other = place(state, 0, vanilla(1, 1, name="Other"))
    assert _registry_granted(state, [other]) == []


def test_combat_dispatchers_skip_missing_objects():
    state = make_state()
    place(state, 0, "Umezawa's Jitte")          # an observer exists
    myr = place(state, 0, "Ichorclaw Myr")      # a becomes-blocked observer
    fire_combat_damage_dealt(state, [(999, 1, 2), (myr.id, 1, 0)])
    assert not state.stack
    fire_becomes_blocked(state, {1: 999})
    fire_becomes_blocked(state, {1: myr.id})   # attacker not blocked
    assert not state.stack
    fire_combat_damage_dealt(state, [])
    fire_becomes_blocked(state, {})


def test_hexproof_helper_with_unknown_player():
    state = make_state()
    src = place(state, 1, vanilla(1, 1, cost="{U}"))
    assert not player_hexproof_from_source(state, 7, src, 1)


def test_untap_step_held_without_rules_or_candidates():
    state = make_state()
    land = place(state, 0, "Island", tapped=True)
    assert untap_step_held(state, 0, set()) == set()
    place(state, 1, "Winter Orb")
    land.tapped = False
    assert untap_step_held(state, 0, set()) == set()
