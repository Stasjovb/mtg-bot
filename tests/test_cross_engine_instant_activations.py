"""Cross-engine parity of instant-speed activations (CR 117.1b / 602.5).

Python ``legal.battlefield_ability_activations`` and Rust
``GameState::push_battlefield_activations`` must offer the same
``ActivateAbility`` set in every priority window: a non-mana,
non-sorcery-speed, non-loyalty ability at any priority; sorcery-speed,
loyalty and mana abilities only in a sorcery window
(``docs/INSTANT_SPEED_ACTIVATIONS_DESIGN.md``). Both engines are built
from the same activated-ability dicts (the Rust registry schema, read
into Python by ``cross_engine._aa_dict_to_python_activated_ability``).
"""

from __future__ import annotations

import importlib.util

import pytest

ZONE_BATTLEFIELD = 2
PHASE_UPKEEP = 1
PHASE_MAIN1 = 3
PHASE_DECLARE_ATTACKERS = 5
PHASE_END_STEP = 10

_INSTANT_AA = {
    "cost": {"mana": {"generic": 1}},
    "effect": {"kind": "gain_life", "amount": 1},
    "is_mana_ability": False,
}
_SORCERY_AA = dict(_INSTANT_AA, sorcery_speed=True)
_TAP_AA = {
    "cost": {"tap_self": True},
    "effect": {"kind": "draw_cards", "count": 1},
    "is_mana_ability": False,
}
_LOYALTY_AA = {
    "cost": {"loyalty": -1},
    "effect": {"kind": "gain_life", "amount": 1},
    "is_mana_ability": False,
}

_OBJECTS = (
    # name, card type, abilities
    ("Instant Pinger", "Creature", (_INSTANT_AA, _TAP_AA)),
    ("Sorcery Pinger", "Creature", (_SORCERY_AA,)),
    ("Loyal Walker", "Planeswalker", (_LOYALTY_AA,)),
)


def _build(*, with_mana: bool):
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        _aa_dict_to_python_activated_ability,
        build_matched_states,
        tiny_synthetic_deckspec,
    )

    py, rs = build_matched_states(tiny_synthetic_deckspec())
    ids: dict[int, str] = {}  # py id -> name
    rs_ids: dict[int, str] = {}  # rust id -> name
    for name, card_type, aas in _OBJECTS:
        is_creature = card_type == "Creature"
        pr = CardPrinting(
            name=name, mana_cost_str="", mana_cost=ManaCost(),
            type_line=card_type, supertypes=(), card_types=(card_type,),
            subtypes=(), power=1 if is_creature else None,
            toughness=1 if is_creature else None, produces=frozenset(),
            activated_abilities=tuple(
                _aa_dict_to_python_activated_ability(d) for d in aas
            ),
        )
        obj = py.new_object(pr, owner_id=0, zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        py.battlefield.append(obj)
        ids[obj.id] = name
        rs_dict = {"name": name, "card_types": [card_type],
                   "activated_abilities": [dict(d) for d in aas]}
        if is_creature:
            rs_dict.update(power=1, toughness=1)
        rid = rs.register_and_inject_object(rs_dict, 0, ZONE_BATTLEFIELD)
        rs.force_set_summoning_sick(rid, False)
        rs_ids[rid] = name
        if card_type == "Planeswalker":
            obj.loyalty_counters = 3
            rs.set_loyalty_counters(rid, 3)
    if with_mana:
        # One {C} in each pool pays the {1} abilities.
        from mtg_bot.game import ManaCoin

        py.players[0].mana_pool.append(ManaCoin(color="C"))
        rs.add_mana(0, "C", 1)
    return py, rs, ids, rs_ids


@pytest.fixture
def matched():
    return _build(with_mana=True)


def _window(py, rs, *, active: int, step, phase: int) -> None:
    py.active_player_idx = active
    py.priority_player_idx = 0
    py.step = step
    rs.set_active_player(active)
    rs.set_phase(phase)
    rs.give_priority_to(0)


def _py_activations(py, ids):
    from mtg_bot.actions import ActivateAbility
    from mtg_bot.legal import legal_actions

    return sorted(
        (ids[a.source_id], a.ability_index)
        for a in legal_actions(py, 0)
        if isinstance(a, ActivateAbility) and a.source_id in ids
    )


def _rs_activations(rs, rs_ids):
    return sorted({
        (rs_ids[d["source_id"]], d["ability_index"])
        for d in rs.legal_decisions(0)
        if d.get("kind") == "activate_ability"
        and d.get("source_id") in rs_ids
    })


def _windows():
    from mtg_bot.turn import Step

    return [
        ("opponent's end step", 1, Step.END, PHASE_END_STEP),
        ("opponent's upkeep", 1, Step.UPKEEP, PHASE_UPKEEP),
        ("own upkeep", 0, Step.UPKEEP, PHASE_UPKEEP),
        ("opponent's declare attackers", 1, Step.DECLARE_ATTACKERS,
         PHASE_DECLARE_ATTACKERS),
    ]


@pytest.mark.parametrize("window", range(4))
def test_instant_window_offers_only_unrestricted_abilities_on_both_engines(
    matched, window,
):
    py, rs, ids, rs_ids = matched
    label, active, step, phase = _windows()[window]
    _window(py, rs, active=active, step=step, phase=phase)
    expected = [("Instant Pinger", 0), ("Instant Pinger", 1)]
    assert _py_activations(py, ids) == expected, label
    assert _rs_activations(rs, rs_ids) == expected, label


def test_sorcery_window_offers_every_ability_on_both_engines(matched):
    from mtg_bot.turn import Step

    py, rs, ids, rs_ids = matched
    _window(py, rs, active=0, step=Step.PRECOMBAT_MAIN, phase=PHASE_MAIN1)
    expected = [
        ("Instant Pinger", 0), ("Instant Pinger", 1),
        ("Loyal Walker", 0), ("Sorcery Pinger", 0),
    ]
    assert _py_activations(py, ids) == expected
    assert _rs_activations(rs, rs_ids) == expected


def test_mana_gate_holds_at_instant_speed_on_both_engines():
    """With no mana, only the free {T} ability is offered (both
    engines), and a tapped source loses that one too."""
    from mtg_bot.turn import Step

    py, rs, ids, rs_ids = _build(with_mana=False)
    _window(py, rs, active=1, step=Step.END, phase=PHASE_END_STEP)
    assert _py_activations(py, ids) == [("Instant Pinger", 1)]
    assert _rs_activations(rs, rs_ids) == [("Instant Pinger", 1)]


def test_bridge_declines_activation_riders_rust_cannot_enforce():
    """A Python AA whose timing / condition rider has no Rust field is
    never bridged (an honest decline instead of a silently dropped
    restriction)."""
    from dataclasses import replace

    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.conditions import HandSizeAtMost
    from mtg_bot.parity.cross_engine import _python_aa_to_safe_dict

    # Deserted Temple's "{1}, {T}: Untap target land." -- a bridged AA.
    temple = get_active_source().get_printings()["Deserted Temple"]
    (base,) = [
        a for a in temple.activated_abilities if not a.is_mana_ability
    ]
    assert _python_aa_to_safe_dict(base) is not None
    for rider in (
        {"activate_only_during_your_turn": True},
        {"activate_only_if": HandSizeAtMost(3)},
        {"exhaust": True},
        {"boast": True},
        {"activate_only_as_instant": True},
    ):
        assert _python_aa_to_safe_dict(replace(base, **rider)) is None, rider
