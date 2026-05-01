"""Tests for the DSK Haunted Screen parser claim.

Haunted Screen prints three activations:

  1. ``{T}: Add {W} or {B}.`` — mana ability claimed via the unified
     ``add {<c1>} or {<c2>}`` recognizer →
     ``AddNManaOfChosenColor(amount=1, options=("W","B"))`` flagged
     ``is_mana_ability=True``.
  2. ``{T}, Pay 1 life: Add {G}, {U}, or {R}.`` — mana ability claimed
     via the unified ``add {<c1>}, {<c2>}, or {<c3>}`` recognizer →
     ``AddNManaOfChosenColor(amount=1, options=("G","U","R"))`` flagged
     ``is_mana_ability=True``, with ``pay_life=1``.
  3. ``{7}: Put seven +1/+1 counters on this artifact. It becomes a
     0/0 Spirit creature in addition to its other types. Activate
     only once.`` — once-only activation. The body decomposes into
     ``Sequence(PutPlusOneCounterOnSelf(amount=7),
     BecomeCreatureWithSubtypeAndPTPermanently(subtype="Spirit",
     base_p=0, base_t=0))`` via the multi-sentence literal recognizer
     in ``effects.py``. The trailing ``Activate only once.`` rider
     lifts to ``activate_only_once=True`` on the ability via the new
     inline-rider strip in ``activated.py``.

The per-source ``GameObject.has_activated_once_only_ability`` flag is
latched at activation time (in ``_activate_ability`` in ``actions.py``)
and read by ``legal_actions``'s gate (``if ability.activate_only_once
and obj.has_activated_once_only_ability: continue``) so a second
activation — even before the first resolves off the stack — is
filtered out at legality time.
"""

from __future__ import annotations

from mtg_bot.cards.parser.source import OracleParserCardSource


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- Haunted Screen ----------

def test_haunted_screen_claimed_by_parser():
    assert "Haunted Screen" in _claimed_names()


def test_haunted_screen_carries_three_activations():
    from mtg_bot.effects import (
        AddNManaOfChosenColor,
        BecomeCreatureWithSubtypeAndPTPermanently,
        PutPlusOneCounterOnSelf,
        Sequence,
    )

    parser = OracleParserCardSource()
    p = parser.get_printings()["Haunted Screen"]
    assert len(p.activated_abilities) == 3
    mana_abilities = [
        a for a in p.activated_abilities
        if isinstance(a.effect, AddNManaOfChosenColor)
    ]
    assert len(mana_abilities) == 2
    first = next(
        a for a in mana_abilities
        if a.cost.pay_life == 0
    )
    assert first.cost.tap_self is True
    assert first.cost.mana_str == ""
    assert first.is_mana_ability is True
    assert first.effect.options == ("W", "B")
    assert first.effect.amount == 1
    second = next(
        a for a in mana_abilities
        if a.cost.pay_life == 1
    )
    assert second.cost.tap_self is True
    assert second.is_mana_ability is True
    assert second.effect.options == ("G", "U", "R")
    assert second.effect.amount == 1
    third = next(
        a for a in p.activated_abilities
        if isinstance(a.effect, Sequence)
    )
    assert third.cost.mana_str == "{7}"
    assert third.cost.tap_self is False
    assert third.cost.sacrifice_self is False
    assert third.sorcery_speed is False
    assert third.is_mana_ability is False
    assert third.activate_only_once is True
    # Body decomposes into two generic primitives.
    assert len(third.effect.effects) == 2
    counters, become = third.effect.effects
    assert isinstance(counters, PutPlusOneCounterOnSelf)
    assert counters.amount == 7
    assert isinstance(become, BecomeCreatureWithSubtypeAndPTPermanently)
    assert become.subtype == "Spirit"
    assert become.base_p == 0
    assert become.base_t == 0


def test_haunted_screen_has_no_triggers_or_statics():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Haunted Screen"]
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


# ---------- BecomeCreatureWithSubtypeAndPTPermanently engine class ----------

def test_become_creature_with_subtype_describe():
    from mtg_bot.effects import BecomeCreatureWithSubtypeAndPTPermanently

    desc = BecomeCreatureWithSubtypeAndPTPermanently(
        subtype="Spirit", base_p=0, base_t=0,
    ).describe()
    assert "Spirit" in desc
    assert "0/0" in desc
    assert "in addition to its other types" in desc


def test_become_creature_with_subtype_first_resolve_transforms():
    """First resolve writes the layer-4/7 registry entries with
    ``expires_at=None`` plus the ``permanent_is_creature`` cache."""
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import BecomeCreatureWithSubtypeAndPTPermanently
    from mtg_bot.game import (
        GameObject, GameState, Player, Zone,
        effective_subtypes, is_creature_now,
    )

    art_pr = make_artifact("Haunted Screen", "{3}")
    source_obj = GameObject(
        id=10, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[source_obj],
        resolving_source=source_obj,
    )
    BecomeCreatureWithSubtypeAndPTPermanently(
        subtype="Spirit", base_p=0, base_t=0,
    ).resolve(state, controller_id=0, targets=())
    assert source_obj.permanent_is_creature is True
    assert is_creature_now(source_obj)
    assert "Spirit" in effective_subtypes(state, source_obj)


def test_become_creature_with_subtype_no_source_is_noop():
    """``resolving_source`` is None → silent no-op."""
    from mtg_bot.effects import BecomeCreatureWithSubtypeAndPTPermanently
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    BecomeCreatureWithSubtypeAndPTPermanently(
        subtype="Spirit", base_p=0, base_t=0,
    ).resolve(state, controller_id=0, targets=())
    # Nothing to assert beyond "didn't raise".


def test_become_creature_no_subtype_skips_subtype_grant():
    """Empty ``subtype`` skips the layer-4 add_subtype registry entry
    but still writes the layer-4 add_type and layer-7 set_base_pt."""
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import BecomeCreatureWithSubtypeAndPTPermanently
    from mtg_bot.game import (
        GameObject, GameState, Player, Zone,
        is_creature_now,
    )

    art_pr = make_artifact("Some Artifact", "{1}")
    source_obj = GameObject(
        id=10, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[source_obj],
        resolving_source=source_obj,
    )
    BecomeCreatureWithSubtypeAndPTPermanently(
        subtype="", base_p=2, base_t=2,
    ).resolve(state, controller_id=0, targets=())
    assert is_creature_now(source_obj)


# ---------- Once-only activation gating ----------

def test_haunted_screen_once_only_legal_only_once():
    """After the first activation, ``legal_actions`` filters out the
    once-only ability — even before the first resolves off the
    stack."""
    from mtg_bot.actions import _activate_ability, ActivateAbility
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.legal import legal_actions
    from mtg_bot.turn import Step

    parser = OracleParserCardSource()
    haunted = parser.get_printings()["Haunted Screen"]

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    # Give P0 enough mana sources to pay {7}: seven Mountains
    # (any colorless-paying source works since {7} is generic).
    for _ in range(7):
        ml = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(ml)
    # Put Haunted Screen onto the battlefield under P0.
    src = state.new_object(haunted, 0, Zone.BATTLEFIELD)
    state.battlefield.append(src)
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    # Find the once-only ability index on the source (the Sequence body).
    once_only_idx = next(
        i for i, ab in enumerate(haunted.activated_abilities)
        if ab.activate_only_once
    )
    # Before any activation, the once-only ability is legal.
    legal = legal_actions(state, 0)
    activate_actions = [
        a for a in legal
        if isinstance(a, ActivateAbility)
        and a.source_id == src.id
        and a.ability_index == once_only_idx
    ]
    assert len(activate_actions) == 1
    # Activate it once. The flag latches at activation time (before the
    # ability resolves off the stack).
    _activate_ability(state, 0, src.id, once_only_idx)
    assert src.has_activated_once_only_ability is True
    # Now the legality gate filters it out — even though the ability is
    # still on the stack.
    legal = legal_actions(state, 0)
    activate_actions = [
        a for a in legal
        if isinstance(a, ActivateAbility)
        and a.source_id == src.id
        and a.ability_index == once_only_idx
    ]
    assert activate_actions == []
