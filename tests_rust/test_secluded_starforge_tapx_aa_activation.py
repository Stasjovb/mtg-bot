"""Rust-engine pins for Secluded Starforge's AA2 tap-X-untapped-artifacts
ACTIVATION COST driven by the GENUINE ``ActivateAbility`` cost path
(mana ``{2}`` + tap-self + tap-X-untapped-artifacts), NOT a pre-seated
``current_resolve_x_value``.

These pins exercise the Rust ``Action::ActivateAbility`` arm
(``state_ops_actions.rs`` Phase 5a-X) end-to-end for the
``PumpTargetCreatureUntilEOT { power_bonus_from_x: true }`` payoff:

- Phase 4 (mana pay): ``auto_tap_pay_for_cost`` debits ``{2}``.
- Phase 5 (tap_self): the source taps.
- Phase 5a-X (tap-X cost): the activator's untapped artifacts (excluding
  the source) are gathered lowest-id-first and tapped; X = the full
  untapped-artifact count (deterministic-first no-agent convention,
  matching Python's agent returning the upper bound). X is seated onto
  the pushed StackItem's ``x_value``.
- Phase 6: a ``new_trigger`` StackItem carrying the pump effect + X is
  pushed; ``resolve_top_of_stack`` swaps X into ``current_resolve_x_value``
  and the pump arm gives the deterministically-picked first creature on
  the controller's bf +X/+0.

The new Rust cost atom is
``ActivationCost.tap_x_untapped_artifacts_you_control`` (cards.rs) +
the Phase 5a-X commit + the trigger-path ``x_value`` swap
(state_ops_resolve.rs). These pins lock the activation-side
byte-equality the cross-engine probe in
``tests/test_secluded_starforge_parity.py`` asserts against Python.

Companion: ``tests/test_secluded_starforge_parity.py`` (cross-engine
probe), ``docs/SEARCH_LIMITATIONS.md`` (Secluded Starforge entry).
"""

from __future__ import annotations

import pytest


ZONE_BATTLEFIELD = 2

_PUMP_KIND = "pump_target_creature_until_eot"


def _starforge_aa2_source_dict():
    """A Secluded-Starforge-shaped Land carrying the AA2 tap-X pump at
    index 0: cost ``{2}`` mana + tap-self + tap-X-untapped-artifacts,
    effect = +X/+0 UEOT (``power_bonus_from_x=True``)."""
    return {
        "name": "Secluded Starforge",
        "card_types": ["Land"],
        "activated_abilities": [
            {
                "cost": {
                    "mana": {"generic": 2},
                    "tap_self": True,
                    "tap_x_untapped_artifacts_you_control": True,
                },
                "effect": {
                    "kind": _PUMP_KIND,
                    "power_bonus": 0,
                    "toughness_bonus": 0,
                    "power_bonus_from_x": True,
                },
                "is_mana_ability": False,
            },
        ],
    }


def _artifact_dict(name="Trinket"):
    return {"name": name, "card_types": ["Artifact"]}


def _bear_dict(power=2, toughness=2):
    return {
        "name": "Bear",
        "card_types": ["Creature"],
        "power": power,
        "toughness": toughness,
    }


def _build(rs, *, n_artifacts, bear_power=2):
    """Seat a bear (the deterministic pump target), ``n_artifacts``
    untapped artifacts, the Starforge source, and {2} of pool mana on
    p0's battlefield. Returns ``(src, bear, artifact_ids)``."""
    bear = rs.register_and_inject_object(
        _bear_dict(power=bear_power), 0, ZONE_BATTLEFIELD
    )
    artifact_ids = [
        rs.register_and_inject_object(_artifact_dict(), 0, ZONE_BATTLEFIELD)
        for _ in range(n_artifacts)
    ]
    src = rs.register_and_inject_object(
        _starforge_aa2_source_dict(), 0, ZONE_BATTLEFIELD
    )
    rs.add_mana(0, "C", 2)
    return src, bear, artifact_ids


def test_tapx_aa_pays_cost_taps_all_artifacts_and_seats_x(synthetic_state):
    """Activating AA2 with 2 untapped artifacts: ``{2}`` debited, source
    tapped, both artifacts tapped, X=2 seated on the pushed StackItem,
    pump NOT yet resolved."""
    rs = synthetic_state
    src, _bear, arts = _build(rs, n_artifacts=2)

    stack_before = rs.stack_size()
    rs.apply_action(
        {"kind": "activate_ability", "source_id": src, "ability_index": 0}
    )

    # {2} debited.
    assert rs.get_mana_pool(0)["C"] == 0
    # Source + both artifacts tapped.
    assert rs.is_tapped(src) is True
    assert all(rs.is_tapped(a) for a in arts)
    # Exactly one new StackItem (the pump), carrying X=2.
    assert rs.stack_size() == stack_before + 1
    assert rs.stack_top_x_value() == 2


def test_tapx_aa_resolves_pump_by_x(synthetic_state):
    """Full real-AA drive on an empty-creature board: with 3 untapped
    artifacts, X=3, and the bear (only creature) gets +3/+0 → power 5."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    # Empty deck so the only creature is the injected bear (the pump arm
    # picks the deterministic first creature on the controller's bf).
    rs = build_rust_state(DeckSpec(card_defs=(), p0_library=(), p1_library=()))
    src, bear, arts = _build(rs, n_artifacts=3)

    assert rs.effective_power(bear) == 2
    rs.apply_action(
        {"kind": "activate_ability", "source_id": src, "ability_index": 0}
    )
    assert rs.stack_top_x_value() == 3
    assert all(rs.is_tapped(a) for a in arts)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0
    assert rs.effective_power(bear) == 5, "+X/+0 with X=3 → power 5"
    assert rs.effective_toughness(bear) == 2, "+X/+0 leaves toughness"


def test_tapx_aa_excludes_pretapped_artifacts(synthetic_state):
    """A pre-tapped artifact is NOT counted toward X and NOT re-tapped.
    With 3 artifacts, one pre-tapped, X=2 (the untapped count) and the
    bear gets +2/+0 → power 4. Pins the lowest-id-first untapped-only
    selection that byte-mirrors Python's choose_x upper-bound."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(DeckSpec(card_defs=(), p0_library=(), p1_library=()))
    src, bear, arts = _build(rs, n_artifacts=3)
    # Pre-tap the highest-id artifact so the two lowest-id ones are the
    # untapped set that gets tapped.
    rs.tap_object(arts[-1])

    rs.apply_action(
        {"kind": "activate_ability", "source_id": src, "ability_index": 0}
    )
    assert rs.stack_top_x_value() == 2, "only the 2 untapped artifacts count"
    # The two lowest-id artifacts tapped, the pre-tapped one stays tapped.
    assert rs.is_tapped(arts[0]) is True
    assert rs.is_tapped(arts[1]) is True
    assert rs.is_tapped(arts[2]) is True  # was already tapped
    rs.resolve_top_of_stack()
    assert rs.effective_power(bear) == 4, "+X/+0 with X=2 → power 4"


def test_tapx_aa_zero_untapped_artifacts_is_x_zero_noop(synthetic_state):
    """With NO untapped artifacts, X=0: nothing extra tapped, the pump
    is a silent no-op (power unchanged). The source still taps + {2}
    still pays (the rest of the cost is unconditional)."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(DeckSpec(card_defs=(), p0_library=(), p1_library=()))
    src, bear, _arts = _build(rs, n_artifacts=0)

    rs.apply_action(
        {"kind": "activate_ability", "source_id": src, "ability_index": 0}
    )
    assert rs.is_tapped(src) is True
    assert rs.get_mana_pool(0)["C"] == 0
    assert rs.stack_top_x_value() == 0
    rs.resolve_top_of_stack()
    assert rs.effective_power(bear) == 2, "X=0 → no pump"
    assert rs.effective_toughness(bear) == 2


def test_tapx_aa_does_not_tap_opponent_or_nonartifact(synthetic_state):
    """X counts only the activator's own untapped ARTIFACTS: an opponent
    artifact + the activator's own non-artifact creature are NOT tapped
    and NOT counted. With 1 own untapped artifact, X=1 → bear +1/+0."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(DeckSpec(card_defs=(), p0_library=(), p1_library=()))
    src, bear, arts = _build(rs, n_artifacts=1)
    # Opponent's untapped artifact (must NOT be tapped / counted).
    opp_art = rs.register_and_inject_object(
        _artifact_dict("Opp Trinket"), 1, ZONE_BATTLEFIELD
    )
    # The bear is the activator's own non-artifact creature (untapped).
    rs.apply_action(
        {"kind": "activate_ability", "source_id": src, "ability_index": 0}
    )
    assert rs.stack_top_x_value() == 1, "only own untapped artifacts count"
    assert rs.is_tapped(arts[0]) is True
    assert rs.is_tapped(opp_art) is False, "opponent artifact untouched"
    assert rs.is_tapped(bear) is False, "own non-artifact creature untouched"
    rs.resolve_top_of_stack()
    assert rs.effective_power(bear) == 3, "+X/+0 with X=1 → power 3"
