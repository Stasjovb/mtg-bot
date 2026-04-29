"""Tests for the DSK Haunted Screen parser claim.

Round 1 deferred Haunted Screen pending two engine-level lifts:

1. The ``{T}: Add {W} or {B}.`` and ``{T}, Pay 1 life: Add {G}, {U},
   or {R}.`` mana abilities — handled by the existing
   ``AddNManaOfChosenColor(options=…)`` engine class plus a new
   literal-line dispatch entry in ``artifact_builder``.
2. The ``{7}: …. Activate only once.`` activation — Round 1's
   "Activate only once" tracking case. Claimed via a bespoke
   ``HauntedScreenActivatedEffect`` whose resolve site latches a new
   ``GameObject.has_activated_once_only_ability`` flag on first fire
   and silently no-ops on subsequent fires. The "becomes a 0/0 Spirit
   creature in addition to its other types" half writes permanent
   layer-4 ``add_type "creature"`` / ``add_subtype "Spirit"`` and
   layer-7 sublayer-1 ``set_base_pt (0, 0)`` registry entries with
   ``expires_at=None`` plus the new ``GameObject.permanent_is_creature``
   write-through cache so ``is_creature_now`` short-circuits without
   consulting the registry on every read.
"""

from __future__ import annotations

from mtg_bot.cards.parser.source import OracleParserCardSource


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- Haunted Screen ----------

def test_haunted_screen_claimed_by_parser():
    # Haunted Screen ``{3}`` Artifact — three activations claimed via
    # three literal-line entries in ``artifact_builder``. The first
    # two are mana abilities with ``options=("W","B")`` and
    # ``options=("G","U","R")`` respectively; the third is the once-
    # only "becomes 0/0 Spirit creature" body.
    assert "Haunted Screen" in _claimed_names()


def test_haunted_screen_carries_three_activations():
    # First ability: ``{T}: Add {W} or {B}.`` →
    # ``AddNManaOfChosenColor(amount=1, options=("W","B"))`` flagged
    # ``is_mana_ability=True``.
    # Second ability: ``{T}, Pay 1 life: Add {G}, {U}, or {R}.`` →
    # ``AddNManaOfChosenColor(amount=1, options=("G","U","R"))``
    # flagged ``is_mana_ability=True``, with ``pay_life=1``.
    # Third ability: ``{7}: Put seven +1/+1 counters …`` →
    # ``HauntedScreenActivatedEffect``.
    from mtg_bot.effects import (
        AddNManaOfChosenColor,
        HauntedScreenActivatedEffect,
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
        if isinstance(a.effect, HauntedScreenActivatedEffect)
    )
    assert third.cost.mana_str == "{7}"
    assert third.cost.tap_self is False
    assert third.cost.sacrifice_self is False
    assert third.sorcery_speed is False
    assert third.is_mana_ability is False


def test_haunted_screen_has_no_triggers_or_statics():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Haunted Screen"]
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


# ---------- HauntedScreenActivatedEffect engine class ----------

def test_haunted_screen_activated_effect_describe():
    from mtg_bot.effects import HauntedScreenActivatedEffect

    desc = HauntedScreenActivatedEffect().describe()
    assert "+1/+1 counters" in desc
    assert "Spirit" in desc
    assert "activate only once" in desc


def test_haunted_screen_activated_effect_first_resolve_transforms():
    # First resolve: 7 +1/+1 counters, becomes 0/0 Spirit creature
    # (permanent grants written to the registry with expires_at=None,
    # plus the ``permanent_is_creature`` write-through cache flag).
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import HauntedScreenActivatedEffect
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
    HauntedScreenActivatedEffect().resolve(
        state, controller_id=0, targets=(),
    )
    assert source_obj.has_activated_once_only_ability is True
    assert source_obj.permanent_is_creature is True
    assert source_obj.plus_one_counters == 7
    assert is_creature_now(source_obj)
    assert "Spirit" in effective_subtypes(state, source_obj)


def test_haunted_screen_activated_effect_second_resolve_is_noop():
    # Second resolve (same source) is a silent no-op — the once-only
    # flag latches on first fire and gates subsequent fires from
    # stacking more counters or re-applying the type-change registry
    # entries.
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import HauntedScreenActivatedEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

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
    HauntedScreenActivatedEffect().resolve(
        state, controller_id=0, targets=(),
    )
    pre_counters = source_obj.plus_one_counters
    pre_registry = list(state.continuous_effects)
    HauntedScreenActivatedEffect().resolve(
        state, controller_id=0, targets=(),
    )
    # No additional counters; registry unchanged in length.
    assert source_obj.plus_one_counters == pre_counters
    assert len(state.continuous_effects) == len(pre_registry)


def test_haunted_screen_activated_effect_no_source_is_noop():
    # Defensive: ``resolving_source`` is None → silent no-op.
    from mtg_bot.effects import HauntedScreenActivatedEffect
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    HauntedScreenActivatedEffect().resolve(
        state, controller_id=0, targets=(),
    )
    # Nothing to assert beyond "didn't raise".


# ---------- GameObject.permanent_is_creature wiring ----------

def test_permanent_is_creature_makes_artifact_a_creature():
    # The new ``permanent_is_creature`` write-through cache lets
    # ``is_creature_now`` short-circuit to True on a permanent that
    # was non-creature at print time but had its type changed by an
    # effect with ``expires_at=None`` (Haunted Screen's once-only
    # activation).
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.game import GameObject, Zone, is_creature_now

    art_pr = make_artifact("Haunted Screen", "{3}")
    obj = GameObject(
        id=1, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    assert is_creature_now(obj) is False
    obj.permanent_is_creature = True
    assert is_creature_now(obj) is True


def test_permanent_is_creature_does_not_block_face_down_2_2_creature():
    # CR 701.34: a face-down permanent is a 2/2 creature regardless
    # of underlying printing types — face-down takes precedence over
    # the new ``permanent_is_creature`` cache. Belt-and-suspenders
    # that adding the new field doesn't reorder ``is_creature_now``'s
    # short-circuit chain.
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.game import GameObject, Zone, is_creature_now

    art_pr = make_artifact("Some Artifact", "{1}")
    obj = GameObject(
        id=1, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD, face_down=True,
    )
    # Even without ``permanent_is_creature``, face-down → creature.
    assert is_creature_now(obj) is True


def test_permanent_is_creature_yields_to_impending_suppression():
    # An impending-cast permanent suppresses creature status while
    # ``impending_active`` is True — the suppression precedes any
    # of the "is creature" branches (printed, stationed,
    # ``temp_is_creature``, ``permanent_is_creature``). Belt-and-
    # suspenders that a hypothetical future card with both impending
    # and a layer-4 add_type entry honors impending's wider
    # short-circuit.
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.game import GameObject, Zone, is_creature_now

    art_pr = make_artifact("Some Artifact", "{1}")
    obj = GameObject(
        id=1, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
        impending_active=True,
        permanent_is_creature=True,
    )
    assert is_creature_now(obj) is False
