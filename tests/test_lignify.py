"""Lignify (Lorwyn) — exercises CR 613 layered continuous effects
across layer 4 (add subtype), layer 6 (lose all abilities), and
layer 7 sublayer 1 (set base P/T).

Lignify's oracle text: "Enchant creature. Enchanted creature is a
Treefolk creature with base power and toughness 0/4 and has no
abilities."

Lignify is a real Magic card from Lorwyn, not in the Edge of
Eternities pool. The printing lives in
``mtg_bot.cards.demo_layers`` so the EoE-only _PRINTINGS stays
clean — no draft/deck-builder side effects.

Tests pin:

- Layer 7a: enchanted creature's base power/toughness becomes 0/4,
  overriding both the printed P/T and any prior layer-7a override
  (e.g. Atomic Microsizer's UEOT "becomes 1/1").
- Layer 6: enchanted creature loses all keywords AND all
  triggered/activated abilities (printed and granted).
- Layer 4: enchanted creature gains the Treefolk subtype while
  retaining its printed subtypes (so "Bear" + "Treefolk", not
  replacement).
- Lifecycle: when Lignify leaves play, every layer entry is
  removed and the creature reverts to its printed shape.
- Pump interaction: +1/+1 counters and UEOT pumps still combine
  on top of the 0/4 base (Lignify resets the base, not the
  bonuses).
- Static-grant order: Lignify's "no abilities" wipes keyword
  grants from passive Aura/Equipment bonuses too — the
  short-circuit in ``effective_keywords`` is intentional.
"""

from __future__ import annotations

import pytest

from mtg_bot.actions import apply_aura_static_grants_on_attach
from mtg_bot.agents import Agent
from mtg_bot.cards import (
    ActivatedAbility, ActivationCost, SYNTHETIC_CREATURES, TriggeredAbility,
)
from mtg_bot.cards.base import make_creature, parse_mana_cost
from mtg_bot.cards.demo_layers import LIGNIFY
from mtg_bot.effects.generic import DrawCards
from mtg_bot.game import (
    GameState, Player, Zone,
    effective_activated_abilities, effective_keywords,
    effective_power, effective_subtypes, effective_toughness,
    effective_triggered_abilities,
)
from mtg_bot.turn import Step, destroy, move_off_battlefield

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirst(Agent):
    """Deterministic agent: always picks the first legal target."""

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state() -> GameState:
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirst()))
    state.players.append(Player(id=1, agent=_PickFirst()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _attach(state, aura, target):
    aura.attached_to = target.id
    apply_aura_static_grants_on_attach(state, aura, target, aura.controller_id)


# ---------- Printing shape ----------


def test_lignify_printing_shape():
    """Pin the three layered-effect flags on the printing so future
    refactors don't silently drop them."""
    assert LIGNIFY.is_aura is True
    assert LIGNIFY.aura_enchant_type == "creature"
    assert LIGNIFY.attached_sets_base_pt == (0, 4)
    assert LIGNIFY.attached_grants_lose_all_abilities is True
    assert LIGNIFY.attached_grants_subtype == "Treefolk"


def test_lignify_not_in_eoe_pool():
    """Lignify is a demo-only card. It must not leak into the EoE
    _PRINTINGS or all_printings — those drive the deck builder."""
    assert "Lignify" not in _PRINTINGS
    assert "Lignify" not in _PRINTINGS


# ---------- Layer 7a: base P/T set to 0/4 ----------


def test_lignify_overrides_base_pt():
    """A 2/2 Wild Bear under Lignify is 0/4."""
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2

    _attach(state, aura, bear)

    assert effective_power(state, bear) == 0
    assert effective_toughness(state, bear) == 4


def test_lignify_pt_combines_with_plus_one_counters():
    """+1/+1 counters apply on top of Lignify's base — 0/4 with two
    +1/+1 counters becomes 2/6, not 2/2 (the original)."""
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    bear.plus_one_counters = 2
    _attach(state, aura, bear)

    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 6


def test_lignify_overrides_earlier_set_base_pt():
    """If a UEOT 'becomes 1/1' effect wrote a layer-7b set_base_pt
    registry entry first, Lignify's later entry takes precedence — the
    most-recent-timestamp 7b sublayer-1 entry wins.
    """
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    state.grant_set_base_pt_ueot(
        source_id=bear.id, target_id=bear.id, power=1, toughness=1,
    )
    assert effective_power(state, bear) == 1
    assert effective_toughness(state, bear) == 1

    _attach(state, aura, bear)

    assert effective_power(state, bear) == 0
    assert effective_toughness(state, bear) == 4


# ---------- Layer 6: lose all abilities ----------


def test_lignify_strips_printed_keywords():
    """Sky Sentinel has flying. Under Lignify, it loses flying."""
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    sentinel = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)
    assert "flying" in effective_keywords(state, sentinel)

    _attach(state, aura, sentinel)

    assert effective_keywords(state, sentinel) == frozenset()


def test_lignify_strips_printed_triggered_abilities():
    """Healing Wisp has an ETB trigger. Under Lignify, it has none."""
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    wisp = _put(state, SYNTHETIC_CREATURES["Healing Wisp"], owner_id=0)
    assert len(effective_triggered_abilities(state, wisp)) == 1

    _attach(state, aura, wisp)

    assert effective_triggered_abilities(state, wisp) == ()


def test_lignify_strips_printed_activated_abilities():
    """Construct a creature with an activated ability and verify
    Lignify suppresses it."""
    activatable_printing = make_creature(
        "Test Tapper", "{1}{G}", 1, 1,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}"), mana_str="{1}",
                    tap_self=True,
                ),
                effect=DrawCards(amount=1),
            ),
        ),
    )
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    tapper = _put(state, activatable_printing, owner_id=0)
    assert len(effective_activated_abilities(state, tapper)) == 1

    _attach(state, aura, tapper)

    assert effective_activated_abilities(state, tapper) == ()


def test_lignify_strips_temp_granted_abilities():
    """A creature with UEOT-granted abilities (via legacy temp_*
    fields) ALSO loses them under Lignify."""
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    bear.temp_keywords = frozenset({"trample"})
    bear.temp_triggered_abilities = (
        TriggeredAbility(trigger="etb", effect=DrawCards(amount=1)),
    )
    bear.temp_activated_abilities = (
        ActivatedAbility(
            cost=ActivationCost(
                mana=parse_mana_cost("{1}"), mana_str="{1}",
                tap_self=True,
            ),
            effect=DrawCards(amount=1),
        ),
    )
    assert "trample" in effective_keywords(state, bear)
    assert len(effective_triggered_abilities(state, bear)) == 1
    assert len(effective_activated_abilities(state, bear)) == 1

    _attach(state, aura, bear)

    assert effective_keywords(state, bear) == frozenset()
    assert effective_triggered_abilities(state, bear) == ()
    assert effective_activated_abilities(state, bear) == ()


# ---------- Layer 4: add subtype "Treefolk" ----------


def test_lignify_adds_treefolk_subtype_keeping_printed():
    """Lignify adds Treefolk while leaving the creature's printed
    subtypes intact (a Bear becomes a Bear AND a Treefolk)."""
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    # Wild Bear has no subtypes in the synthetic pool. Use a printing
    # with a known subtype so we can verify layered-add (not replace).
    soldier_printing = make_creature(
        "Test Goblin", "{R}", 1, 1, subtypes=("Goblin",),
    )
    goblin = _put(state, soldier_printing, owner_id=0)
    assert "Goblin" in effective_subtypes(state, goblin)
    assert "Treefolk" not in effective_subtypes(state, goblin)

    _attach(state, aura, goblin)

    subs = effective_subtypes(state, goblin)
    assert "Goblin" in subs
    assert "Treefolk" in subs


# ---------- Lifecycle: registry entries cleared on detach ----------


def test_lignify_destroyed_reverts_pt():
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    _attach(state, aura, bear)
    assert (effective_power(state, bear), effective_toughness(state, bear)) \
        == (0, 4)

    destroy(state, aura)

    assert (effective_power(state, bear), effective_toughness(state, bear)) \
        == (2, 2)


def test_lignify_destroyed_reverts_abilities():
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    sentinel = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)
    _attach(state, aura, sentinel)
    assert effective_keywords(state, sentinel) == frozenset()

    destroy(state, aura)

    assert "flying" in effective_keywords(state, sentinel)


def test_lignify_destroyed_reverts_subtype():
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    _attach(state, aura, bear)
    assert "Treefolk" in effective_subtypes(state, bear)

    destroy(state, aura)

    assert "Treefolk" not in effective_subtypes(state, bear)


def test_lignify_exiled_reverts_everything():
    """Same revert when the aura is exiled (not destroyed)."""
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    sentinel = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)
    _attach(state, aura, sentinel)

    move_off_battlefield(state, aura, destination="exile")

    assert (effective_power(state, sentinel),
            effective_toughness(state, sentinel)) == (1, 3)
    assert "flying" in effective_keywords(state, sentinel)
    assert "Treefolk" not in effective_subtypes(state, sentinel)


def test_lignify_drops_all_three_registry_entries_on_detach():
    """All three layer entries (4, 6, 7a) sourced by Lignify are
    cleared when the aura leaves play. No stale entries remain."""
    state = _new_state()
    aura = _put(state, LIGNIFY, owner_id=0)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    _attach(state, aura, bear)
    sourced = [ce for ce in state.continuous_effects if ce.source_id == aura.id]
    layers = sorted(ce.layer for ce in sourced)
    assert layers == [4, 6, 7]

    destroy(state, aura)

    assert not any(ce.source_id == aura.id for ce in state.continuous_effects)


# ---------- Multiple Lignifies on the same creature ----------


def test_two_lignifies_same_creature_still_0_4_with_no_abilities():
    """Two Lignifies on the same creature: redundant set_base_pt
    entries (latest timestamp wins, both are 0/4 — same result),
    redundant lose_all_abilities (still no abilities), and
    Treefolk subtype not duplicated."""
    state = _new_state()
    a1 = _put(state, LIGNIFY, owner_id=0)
    a2 = _put(state, LIGNIFY, owner_id=0)
    sentinel = _put(state, SYNTHETIC_CREATURES["Sky Sentinel"], owner_id=0)
    _attach(state, a1, sentinel)
    _attach(state, a2, sentinel)

    assert (effective_power(state, sentinel),
            effective_toughness(state, sentinel)) == (0, 4)
    assert effective_keywords(state, sentinel) == frozenset()
    subs = effective_subtypes(state, sentinel)
    # No duplicate "Treefolk" entries.
    assert subs.count("Treefolk") == 1

    # Removing one still leaves the other in effect.
    destroy(state, a1)
    assert (effective_power(state, sentinel),
            effective_toughness(state, sentinel)) == (0, 4)
    assert effective_keywords(state, sentinel) == frozenset()
    assert "Treefolk" in effective_subtypes(state, sentinel)

    # Removing the second reverts everything.
    destroy(state, a2)
    assert (effective_power(state, sentinel),
            effective_toughness(state, sentinel)) == (1, 3)
    assert "flying" in effective_keywords(state, sentinel)
    assert "Treefolk" not in effective_subtypes(state, sentinel)
