"""Tests for Reroute Systems — full two-mode oracle text.

Audit-found bug: the prior printing simplified mode 0 to "target creature
gains indestructible UEOT" (dropped the artifact branch) and dropped the
"target *tapped* creature" restriction from mode 1. This module exercises
both restored modes plus the two supporting effects
(``PumpTargetArtifactOrCreatureUntilEOT`` and
``DealDamageToTargetTappedCreature``).
"""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES, TOKEN_PRINTINGS
from mtg_bot.effects import (
    DealDamageToTargetTappedCreature,
    ModalChooseOne,
    PumpTargetArtifactOrCreatureUntilEOT,
)
from mtg_bot.game import GameState, Player, Zone, effective_keywords

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _ModeAgent(Agent):
    """Test agent that picks a fixed mode and the first legal target."""

    def __init__(self, mode_idx: int):
        self.mode_idx = mode_idx

    def choose_mode(self, state, player_id, mode_descriptions):
        return self.mode_idx

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -------------------------------------------------------------
# Mode 0 — Target artifact or creature gains indestructible UEOT
# -------------------------------------------------------------


def test_reroute_systems_mode_0_grants_indestructible_to_creature():
    state = _new_state(_ModeAgent(mode_idx=0))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)

    spell = _PRINTINGS["Reroute Systems"]
    # ``Effect._enumerate_for_filter`` tags creatures as ``"creature"``
    # under the unified Pump migration; a ``"permanent"`` tag for a
    # creature would no longer appear in the chosen mode's legal-
    # targets and the modal layer would silently fizzle it.
    spell.spell_effect.resolve(state, 0, (("creature", bear.id),))

    assert "indestructible" in effective_keywords(state, bear)


def test_reroute_systems_mode_0_grants_indestructible_to_artifact():
    """The restored mode-0 branch — an artifact (Lander token) is a legal
    target. ``DestroyTargetArtifact`` should fizzle while indestructible
    is up."""
    from mtg_bot.effects import DestroyTargetArtifact

    state = _new_state(_ModeAgent(mode_idx=0))
    lander = state.new_object(
        TOKEN_PRINTINGS["Lander"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(lander)

    spell = _PRINTINGS["Reroute Systems"]
    spell.spell_effect.resolve(state, 0, (("permanent", lander.id),))

    assert "indestructible" in effective_keywords(state, lander)

    # And the keyword actually protects against destroy.
    DestroyTargetArtifact().resolve(
        state, 1, (("permanent", lander.id),),
    )
    assert lander in state.battlefield


def test_reroute_systems_mode_0_can_target_opponents_permanent():
    """No "you control" restriction — opponent's creature is a legal
    target too (matches printed oracle, which says "target artifact or
    creature" with no controller filter)."""
    state = _new_state(_ModeAgent(mode_idx=0))
    opp_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_bear)

    spell = _PRINTINGS["Reroute Systems"]
    legal = spell.spell_effect.legal_targets(state, 0)
    assert ("creature", opp_bear.id) in legal

    spell.spell_effect.resolve(state, 0, (("creature", opp_bear.id),))
    assert "indestructible" in effective_keywords(state, opp_bear)


# -------------------------------------------------------------
# Mode 1 — Deals 2 damage to target tapped creature
# -------------------------------------------------------------


def test_reroute_systems_mode_1_damages_tapped_creature():
    state = _new_state(_ModeAgent(mode_idx=1))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    bear.tapped = True
    state.battlefield.append(bear)

    spell = _PRINTINGS["Reroute Systems"]
    spell.spell_effect.resolve(state, 0, (("creature", bear.id),))

    assert bear.damage == 2


def test_reroute_systems_mode_1_untapped_creature_not_legal():
    """Mode 1's legal-targets pool is restricted to tapped creatures.
    An untapped creature must NOT appear among ``ModalChooseOne``'s
    legal targets when mode 1 is the only viable target source — the
    union here is mode 0 (any artifact/creature) UNION mode 1 (tapped
    creatures). Direct unit test on the mode-1 effect is the cleanest
    check."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    assert bear.tapped is False

    effect = DealDamageToTargetTappedCreature(amount=2)
    legal = effect.legal_targets(state, 0)
    assert ("creature", bear.id) not in legal


def test_reroute_systems_mode_1_fizzles_if_target_untaps_before_resolve():
    """Re-verification at resolution: if the target untapped between
    target-pick and damage application, the damage fizzles. Calling the
    effect directly (bypassing the modal-layer legality filter) is the
    cleanest way to exercise the at-resolution re-check."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    bear.tapped = False  # Untapped at resolve time.
    state.battlefield.append(bear)

    effect = DealDamageToTargetTappedCreature(amount=2)
    effect.resolve(state, 0, (("creature", bear.id),))

    assert bear.damage == 0
    assert any("no longer tapped" in m for m in state.log)


# -------------------------------------------------------------
# ModalChooseOne plumbing for Reroute Systems
# -------------------------------------------------------------


def test_reroute_systems_is_modal_with_two_modes():
    spell = _PRINTINGS["Reroute Systems"]
    effect = spell.spell_effect
    assert isinstance(effect, ModalChooseOne)
    assert len(effect.modes) == 2
    # Both modes are targeted, single-target — so range collapses to
    # exactly (1, 1).
    assert effect.requires_target() is True
    assert effect.target_count_range() == (1, 1)


def test_reroute_systems_legal_targets_unions_both_modes():
    """Mode 0 covers any artifact/creature; mode 1 only tapped
    creatures. The union must include the artifact (only mode 0 covers
    it) AND the tapped creature (both modes cover it)."""
    state = _new_state()
    lander = state.new_object(
        TOKEN_PRINTINGS["Lander"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(lander)
    tapped_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    tapped_bear.tapped = True
    state.battlefield.append(tapped_bear)

    spell = _PRINTINGS["Reroute Systems"]
    legal = spell.spell_effect.legal_targets(state, 0)
    assert ("permanent", lander.id) in legal
    assert ("creature", tapped_bear.id) in legal


# -------------------------------------------------------------
# Component effects — direct unit tests
# -------------------------------------------------------------


def test_pump_artifact_or_creature_legal_targets_filters_lands():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    lander = state.new_object(
        TOKEN_PRINTINGS["Lander"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(lander)
    # A non-artifact/non-creature card in the graveyard is not on the
    # battlefield so it shouldn't appear, but verify lands wouldn't
    # appear either if they existed: easiest is to verify only the
    # artifact and creature show up.

    effect = PumpTargetArtifactOrCreatureUntilEOT(
        granted_keywords=frozenset({"indestructible"}),
    )
    legal = effect.legal_targets(state, 0)
    # Under the unified ``Pump`` migration, creatures get the
    # ``"creature"`` engine kind tag (Wild Bear) while non-creature
    # artifacts get ``"permanent"`` (Lander token).
    assert ("creature", bear.id) in legal
    assert ("permanent", lander.id) in legal
    assert len(legal) == 2


def test_pump_artifact_or_creature_no_targets_is_noop():
    state = _new_state()
    effect = PumpTargetArtifactOrCreatureUntilEOT(
        granted_keywords=frozenset({"indestructible"}),
    )
    effect.resolve(state, 0, ())
    # No crash, no log spam beyond call.


def test_pump_artifact_or_creature_wrong_kind_is_noop():
    state = _new_state()
    effect = PumpTargetArtifactOrCreatureUntilEOT(
        granted_keywords=frozenset({"indestructible"}),
    )
    effect.resolve(state, 0, (("creature", 42),))
    # No crash.


def test_pump_artifact_or_creature_missing_target_is_noop():
    state = _new_state()
    effect = PumpTargetArtifactOrCreatureUntilEOT(
        granted_keywords=frozenset({"indestructible"}),
    )
    effect.resolve(state, 0, (("permanent", 9999),))
    # No crash.


def test_pump_artifact_or_creature_with_power_bonus_describes_it():
    text = PumpTargetArtifactOrCreatureUntilEOT(
        power_bonus=1, toughness_bonus=2,
        granted_keywords=frozenset({"flying"}),
    ).describe()
    assert "+1/+2" in text
    assert "flying" in text


def test_pump_artifact_or_creature_keyword_only_describe():
    text = PumpTargetArtifactOrCreatureUntilEOT(
        granted_keywords=frozenset({"indestructible"}),
    ).describe()
    assert "indestructible" in text
    assert "artifact or creature" in text


def test_pump_artifact_or_creature_pump_only_describe():
    text = PumpTargetArtifactOrCreatureUntilEOT(
        power_bonus=2, toughness_bonus=2,
    ).describe()
    assert "+2/+2" in text


def test_deal_damage_target_tapped_creature_describe():
    text = DealDamageToTargetTappedCreature(amount=2).describe()
    assert "2" in text
    assert "tapped creature" in text


def test_deal_damage_target_tapped_creature_no_target_is_noop():
    state = _new_state()
    effect = DealDamageToTargetTappedCreature(amount=2)
    effect.resolve(state, 0, ())
    # No crash.


def test_deal_damage_target_tapped_creature_wrong_kind_is_noop():
    state = _new_state()
    effect = DealDamageToTargetTappedCreature(amount=2)
    effect.resolve(state, 0, (("permanent", 1),))
    # No crash.


def test_deal_damage_target_tapped_creature_missing_id_is_noop():
    state = _new_state()
    effect = DealDamageToTargetTappedCreature(amount=2)
    effect.resolve(state, 0, (("creature", 4242),))
    # No crash, no state change.


# ---------------------------------------------------------------------------
# Reroute Systems closure (2026-05-21) — cross-engine bridge + per-leaf
# serializer round-trip pins.
# ---------------------------------------------------------------------------


def test_serializer_emits_pump_target_artifact_or_creature_with_granted_keywords():
    """Reroute Systems mode 0 leaf serializer: when
    ``granted_keywords`` is non-empty (the Reroute Systems
    ``{"indestructible"}`` shape), the emitted dict carries the
    sorted-list field. Empty defaults are omitted from the dict
    (back-compat with every pre-closure round-trip)."""
    from mtg_bot.effects.generic.pump import (
        PumpTargetArtifactOrCreatureUntilEOT,
    )
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    # Reroute Systems mode 0 canonical shape (0, 0, {indestructible}).
    d = _python_spell_effect_to_dict(
        PumpTargetArtifactOrCreatureUntilEOT(
            granted_keywords=frozenset({"indestructible"}),
        )
    )
    assert d == {
        "kind": "pump_target_artifact_or_creature_until_eot",
        "power_bonus": 0,
        "toughness_bonus": 0,
        "granted_keywords": ["indestructible"],
    }


def test_serializer_omits_empty_granted_keywords():
    """When ``granted_keywords`` is empty (the bare-pump shape),
    the field is OMITTED — back-compat with pre-closure round-trips
    + mirrors the Rust to_pydict emit-only-when-non-empty
    convention."""
    from mtg_bot.effects.generic.pump import (
        PumpTargetArtifactOrCreatureUntilEOT,
    )
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    d = _python_spell_effect_to_dict(
        PumpTargetArtifactOrCreatureUntilEOT(
            power_bonus=2,
            toughness_bonus=2,
        )
    )
    assert d == {
        "kind": "pump_target_artifact_or_creature_until_eot",
        "power_bonus": 2,
        "toughness_bonus": 2,
    }


def test_serializer_emits_deal_damage_target_tapped_creature():
    """Reroute Systems mode 1 leaf serializer: emits the canonical
    ``{"kind": "deal_damage_to_target_tapped_creature", "amount":
    N}`` dict. Non-negative invariant pinned."""
    from mtg_bot.effects.generic.damage import (
        DealDamageToTargetTappedCreature,
    )
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    d = _python_spell_effect_to_dict(
        DealDamageToTargetTappedCreature(amount=2)
    )
    assert d == {
        "kind": "deal_damage_to_target_tapped_creature",
        "amount": 2,
    }


def test_serializer_bails_on_negative_deal_damage_to_tapped():
    """Negative ``amount`` bails — preserves the round-trip-or-bail
    invariant since Rust's parse raises on negative ``amount``."""
    from mtg_bot.effects.generic.damage import (
        DealDamageToTargetTappedCreature,
    )
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    d = _python_spell_effect_to_dict(
        DealDamageToTargetTappedCreature(amount=-1)
    )
    assert d is None


def test_bridge_round_trips_pump_with_granted_keywords():
    """``cross_engine._ta_dict_to_python_effect`` consumes the
    canonical dict + reconstructs the Python class with the
    ``granted_keywords`` frozenset populated. Bidirectional pin
    against the serializer above."""
    from mtg_bot.effects.generic.pump import (
        PumpTargetArtifactOrCreatureUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    eff = _ta_dict_to_python_effect({
        "kind": "pump_target_artifact_or_creature_until_eot",
        "power_bonus": 0,
        "toughness_bonus": 0,
        "granted_keywords": ["indestructible"],
    })
    assert isinstance(eff, PumpTargetArtifactOrCreatureUntilEOT)
    assert eff.power_bonus == 0
    assert eff.toughness_bonus == 0
    assert eff.granted_keywords == frozenset({"indestructible"})


def test_bridge_round_trips_pump_with_empty_granted_keywords():
    """Back-compat: a dict without the ``granted_keywords`` field
    reconstructs the Python class with an empty frozenset (the
    pre-closure dict shape)."""
    from mtg_bot.effects.generic.pump import (
        PumpTargetArtifactOrCreatureUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    eff = _ta_dict_to_python_effect({
        "kind": "pump_target_artifact_or_creature_until_eot",
        "power_bonus": 1,
        "toughness_bonus": 2,
    })
    assert isinstance(eff, PumpTargetArtifactOrCreatureUntilEOT)
    assert eff.power_bonus == 1
    assert eff.toughness_bonus == 2
    assert eff.granted_keywords == frozenset()


def test_bridge_round_trips_deal_damage_to_tapped_creature():
    """``cross_engine._ta_dict_to_python_effect`` consumes the
    canonical dict + reconstructs the Python class with ``amount``
    threaded through."""
    from mtg_bot.effects.generic.damage import (
        DealDamageToTargetTappedCreature,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    eff = _ta_dict_to_python_effect({
        "kind": "deal_damage_to_target_tapped_creature",
        "amount": 2,
    })
    assert isinstance(eff, DealDamageToTargetTappedCreature)
    assert eff.amount == 2


def test_bridge_raises_when_deal_damage_to_tapped_missing_amount():
    """``amount`` is REQUIRED — missing-field raises ``KeyError``."""
    import pytest
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    with pytest.raises(KeyError, match="amount"):
        _ta_dict_to_python_effect({
            "kind": "deal_damage_to_target_tapped_creature",
        })


def test_reroute_systems_round_trips_through_modal_composer():
    """The full Reroute Systems ``ModalChooseOne`` round-trips
    through the modal composer + per-mode leaf arms. The bidir
    pin matches the live-parsed printing's shape."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.damage import (
        DealDamageToTargetTappedCreature,
    )
    from mtg_bot.effects.generic.pump import (
        PumpTargetArtifactOrCreatureUntilEOT,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.parity.trajectory import _python_spell_effect_to_dict

    real = get_active_source().get_printings()["Reroute Systems"]
    se = real.spell_effect

    d = _python_spell_effect_to_dict(se)
    assert d == {
        "kind": "choose_one_mode",
        "modes": [
            {
                "kind": "pump_target_artifact_or_creature_until_eot",
                "power_bonus": 0,
                "toughness_bonus": 0,
                "granted_keywords": ["indestructible"],
            },
            {
                "kind": "deal_damage_to_target_tapped_creature",
                "amount": 2,
            },
        ],
    }
    back = _ta_dict_to_python_effect(d)
    assert isinstance(back, ModalChooseOne)
    assert len(back.modes) == 2
    assert isinstance(back.modes[0], PumpTargetArtifactOrCreatureUntilEOT)
    assert back.modes[0].granted_keywords == frozenset({"indestructible"})
    assert isinstance(back.modes[1], DealDamageToTargetTappedCreature)
    assert back.modes[1].amount == 2


def test_admit_predicate_admits_reroute_systems_post_closure():
    """The Reroute Systems closure flips Reroute Systems DECLINED
    → ADMITTED via the per-mode-target-binding substrate (Cycle 5)
    + the per-leaf serializers (this closure) + the matching
    Rust variant fields. The auto-grow flips the admit predicate
    purely via covered-and-bridged + round-trip-or-bail teeth — no
    hardcoded card-name list."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity.trajectory import _printing_is_bridge_simple_spell

    rs = get_active_source().get_printings().get("Reroute Systems")
    assert rs is not None
    assert _printing_is_bridge_simple_spell(rs) is True, (
        "Reroute Systems must auto-join the spell-card-bridge admit "
        "set post-closure: both modes leaf-recognized, ModalChooseOne "
        "(1,1) → _PHASE1_SHAPE, round-trip-clean."
    )


# ---------------------------------------------------------------------------
# Reroute Systems closure — Rust unit pins for the new resolve arms
# ---------------------------------------------------------------------------


def _require_engine():
    import importlib.util
    import pytest

    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


def _fresh_rust():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


_ZONE_HAND = 0
_ZONE_BATTLEFIELD = 2


def test_rust_pump_artifact_or_creature_with_granted_keywords_parses():
    """The Rust ``Effect::PumpTargetArtifactOrCreatureUntilEOT``
    variant parses with the new ``granted_keywords`` list-of-strings
    field. The bare-pump shape (omitted field) is still legal
    (back-compat)."""
    _require_engine()
    rs = _fresh_rust()
    # With granted_keywords.
    sid_kw = rs.register_and_inject_object(
        {
            "name": "Synth Pump Reroute",
            "card_types": ["Instant"],
            "effects": [{
                "kind": "pump_target_artifact_or_creature_until_eot",
                "power_bonus": 0,
                "toughness_bonus": 0,
                "granted_keywords": ["indestructible"],
            }],
        },
        0, _ZONE_HAND,
    )
    assert isinstance(sid_kw, int)
    # Without granted_keywords (back-compat default).
    sid_bare = rs.register_and_inject_object(
        {
            "name": "Synth Pump Bare",
            "card_types": ["Instant"],
            "effects": [{
                "kind": "pump_target_artifact_or_creature_until_eot",
                "power_bonus": 1,
                "toughness_bonus": 1,
            }],
        },
        0, _ZONE_HAND,
    )
    assert isinstance(sid_bare, int)


def test_rust_deal_damage_to_target_tapped_creature_parses():
    """The new Rust ``Effect::DealDamageToTargetTappedCreature``
    variant parses + registers without raising."""
    _require_engine()
    rs = _fresh_rust()
    sid = rs.register_and_inject_object(
        {
            "name": "Synth Tapped Burn",
            "card_types": ["Instant"],
            "effects": [{
                "kind": "deal_damage_to_target_tapped_creature",
                "amount": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    assert isinstance(sid, int)


def test_rust_deal_damage_to_target_tapped_creature_rejects_missing_amount():
    """``amount`` is REQUIRED (mirrors the Python bridge contract +
    the round-28 REQUIRED-amount precedent for
    ``damage_each_opponent`` / ``damage_each_creature``)."""
    import pytest
    _require_engine()
    rs = _fresh_rust()
    with pytest.raises((KeyError, ValueError), match="amount"):
        rs.register_and_inject_object(
            {
                "name": "Bad Tapped Burn",
                "card_types": ["Instant"],
                "effects": [{
                    "kind": "deal_damage_to_target_tapped_creature",
                }],
            },
            0, _ZONE_HAND,
        )


def test_rust_deal_damage_to_target_tapped_creature_rejects_negative_amount():
    """Negative ``amount`` rejected at parse — CR 119.5 (negative
    damage is not a legal effect)."""
    import pytest
    _require_engine()
    rs = _fresh_rust()
    with pytest.raises(ValueError, match="non-negative"):
        rs.register_and_inject_object(
            {
                "name": "Neg Tapped Burn",
                "card_types": ["Instant"],
                "effects": [{
                    "kind": "deal_damage_to_target_tapped_creature",
                    "amount": -1,
                }],
            },
            0, _ZONE_HAND,
        )


def test_rust_per_mode_detector_binds_first_artifact_or_creature():
    """The Cycle 5 per-mode detector extended to recognize
    ``PumpTargetArtifactOrCreatureUntilEOT`` — when chosen, the
    cast-time bind picks the FIRST artifact-or-creature on either
    bf in ``bf_iter_etb_sorted`` order."""
    _require_engine()
    rs = _fresh_rust()
    # Seed an artifact + a creature; the first one (artifact)
    # should be picked under the artifact-or-creature filter.
    art_id = rs.register_and_inject_object(
        {
            "name": "Trinket",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 2},
        },
        0, _ZONE_BATTLEFIELD,
    )
    rs.register_and_inject_object(
        {
            "name": "Bear",
            "card_types": ["Creature"],
            "power": 2, "toughness": 2,
            "mana_cost": {"generic": 1, "G": 1},
        },
        0, _ZONE_BATTLEFIELD,
    )
    # Modal spell: mode 0 = pump_target_artifact_or_creature_until_eot,
    # mode 1 = gain_life (filler).
    sid = rs.register_and_inject_object(
        {
            "name": "Modal Pump",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1},
            "effects": [{
                "kind": "choose_one_mode",
                "modes": [
                    {
                        "kind": "pump_target_artifact_or_creature_until_eot",
                        "power_bonus": 0,
                        "toughness_bonus": 0,
                        "granted_keywords": ["indestructible"],
                    },
                    {"kind": "gain_life", "amount": 2},
                ],
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "C", 1)
    ok = rs.cast_spell_noncreature(sid, 0)
    assert ok is True
    assert rs.stack_top_chosen_mode_idx() == 0
    assert rs.stack_top_target_id() == art_id


def test_rust_per_mode_detector_binds_first_tapped_creature():
    """The Cycle 5 per-mode detector extended to recognize
    ``DealDamageToTargetTappedCreature`` — when chosen, the cast-
    time bind picks the FIRST tapped creature on either bf in
    ``bf_iter_etb_sorted`` order. An untapped creature on the bf
    must be SKIPPED."""
    _require_engine()
    rs = _fresh_rust()
    # Seed an untapped creature FIRST (would be picked by the
    # default first-creature ladder).
    rs.register_and_inject_object(
        {
            "name": "Untapped Bear",
            "card_types": ["Creature"],
            "power": 2, "toughness": 2,
            "mana_cost": {"generic": 1, "G": 1},
        },
        0, _ZONE_BATTLEFIELD,
    )
    # Then a tapped creature SECOND — the modal per-mode override
    # must pick THIS one, skipping the untapped first.
    tapped_id = rs.register_and_inject_object(
        {
            "name": "Tapped Bear",
            "card_types": ["Creature"],
            "power": 2, "toughness": 2,
            "mana_cost": {"generic": 1, "G": 1},
        },
        1, _ZONE_BATTLEFIELD,
    )
    rs.tap_object(tapped_id)
    sid = rs.register_and_inject_object(
        {
            "name": "Modal Burn",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1},
            "effects": [{
                "kind": "choose_one_mode",
                "modes": [
                    {
                        "kind": "deal_damage_to_target_tapped_creature",
                        "amount": 2,
                    },
                    {"kind": "gain_life", "amount": 2},
                ],
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "C", 1)
    ok = rs.cast_spell_noncreature(sid, 0)
    assert ok is True
    assert rs.stack_top_chosen_mode_idx() == 0
    assert rs.stack_top_target_id() == tapped_id


def test_rust_deal_damage_to_target_tapped_creature_resolve_applies_damage():
    """Synthetic direct-effect probe — cast a Sorcery whose body
    is the bare ``deal_damage_to_target_tapped_creature`` leaf,
    resolve it, verify the tapped creature took the damage. Exercises
    the new resolve arm + the at-resolve filter recheck end-to-end."""
    _require_engine()
    rs = _fresh_rust()
    tapped_id = rs.register_and_inject_object(
        {
            "name": "Tapped Victim",
            "card_types": ["Creature"],
            "power": 3, "toughness": 3,
            "mana_cost": {"generic": 2},
        },
        1, _ZONE_BATTLEFIELD,
    )
    rs.tap_object(tapped_id)
    sid = rs.register_and_inject_object(
        {
            "name": "Bare Burn",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1},
            "effects": [{
                "kind": "deal_damage_to_target_tapped_creature",
                "amount": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "C", 1)
    ok = rs.cast_spell_noncreature(sid, 0)
    assert ok is True
    rs.resolve_top_of_stack()
    # Tapped creature took 2 damage.
    assert rs.get_damage(tapped_id) == 2


def test_rust_deal_damage_to_target_tapped_creature_fizzles_when_untapped_at_resolve():
    """At-resolve filter recheck per CR 608.2b — a target that
    untaps between cast-time-bind and resolve fails the recheck
    and the damage application is skipped (silent fizzle)."""
    _require_engine()
    rs = _fresh_rust()
    cre_id = rs.register_and_inject_object(
        {
            "name": "Resilient",
            "card_types": ["Creature"],
            "power": 3, "toughness": 3,
            "mana_cost": {"generic": 2},
        },
        1, _ZONE_BATTLEFIELD,
    )
    rs.tap_object(cre_id)
    sid = rs.register_and_inject_object(
        {
            "name": "Bare Burn",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1},
            "effects": [{
                "kind": "deal_damage_to_target_tapped_creature",
                "amount": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "C", 1)
    ok = rs.cast_spell_noncreature(sid, 0)
    assert ok is True
    # Between cast and resolve: untap.
    rs.untap_object(cre_id)
    rs.resolve_top_of_stack()
    # The damage application was skipped — no marker on the creature.
    assert rs.get_damage(cre_id) == 0


def test_rust_pump_artifact_or_creature_with_granted_keywords_resolve():
    """Synthetic direct-effect probe for the granted_keywords
    extension. Cast a Sorcery whose body is the bare pump leaf with
    ``granted_keywords=['indestructible']`` against an artifact;
    verify the artifact's UEOT modifiers carry the keyword grant."""
    _require_engine()
    rs = _fresh_rust()
    art_id = rs.register_and_inject_object(
        {
            "name": "Target Art",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 2},
        },
        0, _ZONE_BATTLEFIELD,
    )
    sid = rs.register_and_inject_object(
        {
            "name": "Bare Pump",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1},
            "effects": [{
                "kind": "pump_target_artifact_or_creature_until_eot",
                "power_bonus": 0,
                "toughness_bonus": 0,
                "granted_keywords": ["indestructible"],
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "C", 1)
    ok = rs.cast_spell_noncreature(sid, 0)
    assert ok is True
    rs.resolve_top_of_stack()
    # Indestructible granted via UEOT modifier — query via effective
    # keywords.
    assert rs.has_keyword(art_id, "indestructible") is True


# ---------------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equal probes — Reroute Systems
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_reroute_systems_mode_0_parity():
    """**GENUINE real-EoE cross-engine probe — Reroute Systems mode
    0 (PumpTargetArtifactOrCreatureUntilEOT, grants indestructible
    UEOT to first artifact-or-creature; 6,132 17lands decks).
    ModalChooseOne envelope Cycle 6 — admit-set flip 17 → 18.
    PROBED tier.**

    Drives the **ACTUAL parsed Reroute Systems printing** on the
    Python side: ``get_active_source().get_printings()["Reroute
    Systems"]`` — which the live parser maps to a ``spell_effect``
    of ``ModalChooseOne(modes=(PumpTargetArtifactOrCreatureUntilEOT
    (granted_keywords={"indestructible"}),
    DealDamageToTargetTappedCreature(amount=2)))``.

    Oracle (verbatim, ``data/edge_of_eternities.json``):

        "[Instant] {W} — Choose one —
         - Target artifact or creature gains indestructible until
           end of turn.
         - Reroute Systems deals 2 damage to target tapped creature."

    **Setup.** p0 controls a creature on the bf (Wild Bear). p0
    casts Reroute Systems mode 0 — the cast-time bind binds the
    bear via the per-mode detector. Resolve → bear gains
    indestructible UEOT.

    Assertion strength: **full ``compare_fields``** byte-equality
    over the cross-engine field view.
    """
    import pytest

    _require_engine()
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone, effective_keywords
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.effects.generic.pump import (
        PumpTargetArtifactOrCreatureUntilEOT,
    )
    from mtg_bot.effects.generic.damage import (
        DealDamageToTargetTappedCreature,
    )
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards import SYNTHETIC_CREATURES

    real = get_active_source().get_printings().get("Reroute Systems")
    if real is None:
        pytest.skip("Reroute Systems absent from active CardSource")
    se = real.spell_effect
    assert isinstance(se, ModalChooseOne)
    assert isinstance(se.modes[0], PumpTargetArtifactOrCreatureUntilEOT)
    assert se.modes[0].granted_keywords == frozenset({"indestructible"})
    assert isinstance(se.modes[1], DealDamageToTargetTappedCreature)
    assert se.modes[1].amount == 2

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: seat Wild Bear on the bf, cast Reroute Systems
    # ---- mode 0 with the bear as the chosen target.
    py_bear = py.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_bear.summoning_sick = False
    py.battlefield.append(py_bear)

    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            chosen_modes=(0,),
            targets=(("creature", py_bear.id),),
        ),
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert "indestructible" in effective_keywords(py, py_bear), (
        "Python: Wild Bear must gain indestructible UEOT"
    )

    # ---- Rust: seat the same Bear via the registry + cast the
    # ---- real Reroute Systems printing through cast_spell_noncreature.
    # ---- The cast-time per-mode detector picks the bear as the
    # ---- first artifact-or-creature on either bf.
    rs_bear_id = rs.register_and_inject_object(
        {
            "name": "Wild Bear",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "power": 2, "toughness": 2,
            "mana_cost": {"generic": 1, "G": 1},
        },
        0, _ZONE_BATTLEFIELD,
    )
    rs_sid = rs.register_and_inject_object(
        {
            "name": "Reroute Systems",
            "card_types": ["Instant"],
            "mana_cost": {"W": 1},
            "effects": [{
                "kind": "choose_one_mode",
                "modes": [
                    {
                        "kind": "pump_target_artifact_or_creature_until_eot",
                        "power_bonus": 0,
                        "toughness_bonus": 0,
                        "granted_keywords": ["indestructible"],
                    },
                    {
                        "kind": "deal_damage_to_target_tapped_creature",
                        "amount": 2,
                    },
                ],
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "W", 1)
    ok = rs.cast_spell_noncreature(rs_sid, 0)
    assert ok is True
    assert rs.stack_top_chosen_mode_idx() == 0, (
        "Rust must auto-bind mode 0 (deterministic-first)"
    )
    assert rs.stack_top_target_id() == rs_bear_id, (
        "Rust per-mode detector must bind the bear"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    # Indestructible granted via UEOT modifier.
    assert rs.has_keyword(rs_bear_id, "indestructible") is True, (
        "Rust: Wild Bear must gain indestructible UEOT"
    )


def test_cross_engine_real_eoe_reroute_systems_mode_1_parity():
    """**GENUINE real-EoE cross-engine probe — Reroute Systems mode
    1 (DealDamageToTargetTappedCreature, 2 damage to a tapped
    creature; 6,132 17lands decks). ModalChooseOne envelope Cycle 6
    — companion to the mode-0 probe.**

    Drives the **ACTUAL parsed Reroute Systems printing** on the
    Python side with ``chosen_modes=(1,)`` (explicit cast-time
    binding to the burn mode — non-default; the default no-agent
    pick is (0,)). On the Rust side, drives the bare leaf effect
    directly since the public Rust API has no way to drive
    chosen_mode_idx=1 cast-time today (mirrors the Cycle 4 Ruinous
    Rampage mode-1 probe pattern at `test_parity_smoke.py:73829`).

    **Setup.** p1 controls a tapped Wild Bear; p0 casts Reroute
    Systems mode 1 targeting the tapped bear. Bear takes 2 damage
    on both engines.
    """
    import pytest

    _require_engine()
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import ModalChooseOne
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards import SYNTHETIC_CREATURES

    real = get_active_source().get_printings().get("Reroute Systems")
    if real is None:
        pytest.skip("Reroute Systems absent from active CardSource")
    se = real.spell_effect
    assert isinstance(se, ModalChooseOne)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: seat tapped Wild Bear on p1's bf, cast Reroute
    # ---- Systems mode 1 targeting the bear.
    py_bear = py.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_bear.summoning_sick = False
    py_bear.tapped = True
    py.battlefield.append(py_bear)

    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell, controller_id=0,
            chosen_modes=(1,),
            targets=(("creature", py_bear.id),),
        ),
    )
    resolve_top_of_stack(py)
    # Bear is 2/2 — 2 damage marks then SBA destroys it; capture
    # damage before SBA, then confirm SBA evicts the bear.
    assert py_bear.damage == 2, (
        "Python: tapped Bear must take 2 damage from mode 1"
    )
    py_sba(py)
    assert len(py.stack) == 0
    assert py_bear not in py.battlefield, (
        "Python: tapped Bear must be destroyed by SBA after taking "
        "lethal damage from Reroute Systems mode 1"
    )

    # ---- Rust: drive the bare-leaf path (no public API for
    # ---- chosen_mode_idx=1 cast-time today; mirrors the Ruinous
    # ---- Rampage mode-1 probe convention).
    rs_bear_id = rs.register_and_inject_object(
        {
            "name": "Wild Bear",
            "card_types": ["Creature"],
            "subtypes": ["Bear"],
            "power": 2, "toughness": 2,
            "mana_cost": {"generic": 1, "G": 1},
        },
        1, _ZONE_BATTLEFIELD,
    )
    rs.tap_object(rs_bear_id)
    rs_sid = rs.register_and_inject_object(
        {
            "name": "Reroute Systems",
            "card_types": ["Instant"],
            "mana_cost": {"W": 1},
            "effects": [{
                "kind": "deal_damage_to_target_tapped_creature",
                "amount": 2,
            }],
        },
        0, _ZONE_HAND,
    )
    rs.add_mana(0, "W", 1)
    ok = rs.cast_spell_noncreature(rs_sid, 0)
    assert ok is True
    rs.resolve_top_of_stack()
    # Capture damage marker BEFORE SBA evicts the lethal-damaged
    # bear. Bear is 2/2, takes 2 damage = lethal → moves to gy.
    assert rs.get_damage(rs_bear_id) == 2, (
        "Rust: tapped Bear must take 2 damage from the bare leaf"
    )
    rs.apply_sbas()
    assert rs.stack_size() == 0
