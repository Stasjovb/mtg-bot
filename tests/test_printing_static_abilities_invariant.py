"""Regression tests for the ``static_abilities`` shape invariant.

Background — the production crash this locks down
-------------------------------------------------
A self-play worker dropped a game with::

    TypeError: 'ContinuousModifier' object is not iterable
      training/state_tokenizer.py:415  _fill_permanent_v2_scalars
      game.py:2278                     effective_power
      game.py:993                      _static_bonuses
      effects/modifiers.py:615         walk_continuous_modifiers
          for static in getattr(source.printing, "static_abilities", ()) or ():

i.e. some battlefield permanent's ``printing.static_abilities`` held a
BARE ``ContinuousModifier`` — the payload that belongs *inside* a
``StaticAbility`` — instead of the declared
``tuple[StaticAbility, ...]``. Nothing validated the slot, so the bad
printing survived construction and only blew up later, at an unrelated
layered read, deep inside MCTS, with no trace back to the builder that
produced it.

These tests pin the two halves of the fix:

1. ``CardPrinting`` / ``RoomHalf`` validate the slot in
   ``__post_init__``, so the failure is raised AT the construction site
   (including the ``dataclasses.replace`` copy/token rewrites) and names
   the card plus the offending type.
2. The static surface has ONE accessor
   (``effects.modifiers.active_static_abilities``); the CR 613 / CR 614
   dispatchers no longer read the slot raw, so every walk sees the same
   Room-half gating and fails identically.
"""

from __future__ import annotations

import dataclasses as _dc

import pytest

from mtg_bot.cards.base import (
    CardPrinting,
    ManaCost,
    RoomHalf,
    StaticAbility,
    make_room,
    make_token_creature,
)
from mtg_bot.effects.base import StaticScope
from mtg_bot.effects.modifiers import (
    ContinuousModifier,
    GrantKeyword,
    PowerToughnessBonus,
    active_static_abilities,
    walk_continuous_modifiers,
)
from mtg_bot.game import GameState, Player, Zone, effective_power
import mtg_bot.game as game_mod


def _cm_pt(power: int = 1, toughness: int = 1) -> ContinuousModifier:
    return ContinuousModifier(
        layer=7,
        payload=PowerToughnessBonus(
            power_bonus=power, toughness_bonus=toughness,
        ),
    )


def _bare_printing(**kwargs) -> CardPrinting:
    base = dict(
        name="Probe Creature",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature — Robot",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Robot",),
        power=2,
        toughness=2,
    )
    base.update(kwargs)
    return CardPrinting(**base)


# ── 1. construction-time validation ────────────────────────────────


def test_bare_continuous_modifier_rejected_at_construction():
    """The exact production shape: a lone ContinuousModifier in the
    static_abilities slot. Must fail loudly, here, naming the card."""
    with pytest.raises(TypeError) as excinfo:
        _bare_printing(static_abilities=_cm_pt())
    msg = str(excinfo.value)
    assert "Probe Creature" in msg
    assert "ContinuousModifier" in msg
    assert "tuple of StaticAbility" in msg


def test_bare_static_ability_rejected_at_construction():
    with pytest.raises(TypeError) as excinfo:
        _bare_printing(
            static_abilities=StaticAbility(scope=StaticScope.SELF),
        )
    assert "StaticAbility" in str(excinfo.value)


def test_list_of_static_abilities_rejected_at_construction():
    """A list is iterable, so it would NOT have raised at the read —
    it would have silently worked until something hashed or compared
    the printing. Still a shape violation; reject it."""
    with pytest.raises(TypeError) as excinfo:
        _bare_printing(
            static_abilities=[StaticAbility(scope=StaticScope.SELF)],
        )
    assert "got list" in str(excinfo.value)


def test_non_static_ability_element_rejected_with_index():
    with pytest.raises(TypeError) as excinfo:
        _bare_printing(
            static_abilities=(
                StaticAbility(scope=StaticScope.SELF),
                _cm_pt(),
            ),
        )
    msg = str(excinfo.value)
    assert "static_abilities[1]" in msg
    assert "ContinuousModifier" in msg


def test_dataclasses_replace_is_validated_too():
    """The runtime copy/token printing rewrites (``actions`` clone,
    ``effects.generic.tokens`` token-copy, ``become_type``) all go
    through ``dataclasses.replace`` — the invariant must hold there."""
    good = make_token_creature("Good", 2, 2)
    with pytest.raises(TypeError) as excinfo:
        _dc.replace(good, static_abilities=_cm_pt())
    assert "Good" in str(excinfo.value)


def test_room_half_is_validated():
    with pytest.raises(TypeError) as excinfo:
        RoomHalf(
            name="Bad Half",
            mana_cost_str="{1}",
            mana_cost=ManaCost(generic=1),
            static_abilities=_cm_pt(),
        )
    assert "Bad Half" in str(excinfo.value)


def test_well_formed_printing_still_constructs():
    printing = _bare_printing(
        static_abilities=(
            StaticAbility(
                scope=StaticScope.SELF, continuous_effect=_cm_pt(),
            ),
        ),
    )
    assert isinstance(printing.static_abilities, tuple)
    assert len(printing.static_abilities) == 1


# ── 2. the crash path itself ───────────────────────────────────────


def _two_player_state() -> GameState:
    from mtg_bot.agents import RandomAgent

    return GameState(
        players=[
            Player(id=0, agent=RandomAgent()),
            Player(id=1, agent=RandomAgent()),
        ],
    )


def test_effective_power_no_longer_reachable_with_malformed_printing():
    """Reproduction of the dropped-game crash, inverted.

    Before the fix this sequence produced
    ``TypeError: 'ContinuousModifier' object is not iterable`` from the
    battlefield walk inside ``effective_power``. Now the malformed
    printing cannot be built at all, so the read path is unreachable.
    """
    state = _two_player_state()
    good = make_token_creature("Good", 2, 2)
    obj = state.new_object(good, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(obj)

    # The read path is healthy for a well-formed board...
    assert effective_power(state, obj) == 2

    # ...and the only way to get a malformed source onto the
    # battlefield now fails at the construction site instead.
    with pytest.raises(TypeError):
        _dc.replace(good, static_abilities=_cm_pt())


# ── 3. one accessor, one gating rule ───────────────────────────────


def test_game_uses_the_single_static_accessor():
    assert game_mod._active_static_abilities is active_static_abilities


def _room_with_anthem_on_half_b() -> CardPrinting:
    grant = StaticAbility(
        scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
        continuous_effect=ContinuousModifier(
            layer=6, payload=GrantKeyword("flying"),
        ),
    )
    return make_room(
        RoomHalf(
            name="Quiet Study",
            mana_cost_str="{1}{W}",
            mana_cost=ManaCost(generic=1, colored=(("W", 1),)),
        ),
        RoomHalf(
            name="Loud Lecture",
            mana_cost_str="{2}{W}",
            mana_cost=ManaCost(generic=2, colored=(("W", 1),)),
            static_abilities=(grant,),
        ),
    )


def test_locked_room_half_static_is_inert_for_the_cr613_dispatcher():
    """``walk_continuous_modifiers`` used to read the raw
    ``static_abilities`` tuple, so a LOCKED Room half's continuous
    modifier still applied — the layer-6 grant walk (which went through
    the gated helper) and the CR 613 dispatcher disagreed. Both route
    through ``active_static_abilities`` now."""
    state = _two_player_state()
    room_printing = _room_with_anthem_on_half_b()
    room = state.new_object(room_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    room.unlocked_halves = frozenset({"Quiet Study"})  # locked: Loud Lecture
    state.battlefield.append(room)

    creature = state.new_object(
        make_token_creature("Bystander", 1, 1), owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(creature)

    assert active_static_abilities(room) == ()
    assert walk_continuous_modifiers(state, creature) == []

    # Unlock the other half and the modifier becomes live.
    room.unlocked_halves = frozenset({"Quiet Study", "Loud Lecture"})
    assert len(active_static_abilities(room)) == 1
    found = walk_continuous_modifiers(state, creature)
    assert [src_id for src_id, _ in found] == [room.id]
    assert isinstance(found[0][1].payload, GrantKeyword)
