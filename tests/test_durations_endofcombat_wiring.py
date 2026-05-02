"""End-to-end tests for the ``EndOfCombat`` Duration wiring.

The ``EndOfCombat`` Duration translates to ``expires_at=
"end_of_combat"``. ``clear_combat_state`` (called at the
end-of-combat step in ``run_step``) drops every registry entry
tagged with that key via
``state.expire_continuous_effects("end_of_combat")``.

No production card uses this duration today; these tests exercise
the wiring directly so a future card with ``until end of combat``
oracle text can route through ``ApplyEffect(<inner>, EndOfCombat())``
and rely on the cleanup hook to drop its registry writes at the
right moment.
"""

from __future__ import annotations


def _make_obj(printing, obj_id=10, controller_id=0):
    from mtg_bot.game import GameObject, Zone

    return GameObject(
        id=obj_id, printing=printing, owner_id=controller_id,
        controller_id=controller_id, zone=Zone.BATTLEFIELD,
    )


def _new_state(source_obj):
    from mtg_bot.game import GameState, Player

    return GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[source_obj],
        resolving_source=source_obj,
    )


# ---------- Direct registry-write path ----------


def test_clear_combat_state_drops_end_of_combat_entries():
    """Manually-written ``expires_at="end_of_combat"`` entries are
    dropped by ``clear_combat_state``."""
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.combat import clear_combat_state

    source_obj = _make_obj(make_artifact("Source", "{1}"))
    state = _new_state(source_obj)
    state.add_continuous_effect(
        source_id=source_obj.id, layer=6, kind="grant_keyword",
        target_id=source_obj.id, params=("flying",),
        expires_at="end_of_combat",
    )
    assert len(state.continuous_effects) == 1
    clear_combat_state(state)
    assert state.continuous_effects == []


def test_clear_combat_state_keeps_other_lifetimes():
    """``clear_combat_state`` only drops entries with
    ``expires_at="end_of_combat"``; cleanup-scoped, controller_untap-
    scoped, and permanent entries all survive."""
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.combat import clear_combat_state

    source_obj = _make_obj(make_artifact("Source", "{1}"))
    state = _new_state(source_obj)
    permanent_entry = state.add_continuous_effect(
        source_id=source_obj.id, layer=6, kind="grant_keyword",
        target_id=source_obj.id, params=("trample",),
        expires_at=None,
    )
    cleanup_entry = state.add_continuous_effect(
        source_id=source_obj.id, layer=6, kind="grant_keyword",
        target_id=source_obj.id, params=("haste",),
        expires_at="cleanup",
    )
    untap_entry = state.add_continuous_effect(
        source_id=source_obj.id, layer=6, kind="grant_keyword",
        target_id=source_obj.id, params=("vigilance",),
        expires_at="controller_untap", expires_at_player_id=0,
    )
    eoc_entry = state.add_continuous_effect(
        source_id=source_obj.id, layer=6, kind="grant_keyword",
        target_id=source_obj.id, params=("flying",),
        expires_at="end_of_combat",
    )
    assert len(state.continuous_effects) == 4
    clear_combat_state(state)
    surviving = state.continuous_effects
    assert permanent_entry in surviving
    assert cleanup_entry in surviving
    assert untap_entry in surviving
    assert eoc_entry not in surviving


def test_clear_combat_state_no_op_when_no_end_of_combat_entries():
    """Existing combat-state teardown semantics (attacking flags,
    pending sacrifices) still work when no end-of-combat registry
    entries exist."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.combat import clear_combat_state

    attacker = _make_obj(
        make_creature("Bear", "{1}{G}", 2, 2), obj_id=10,
    )
    attacker.attacking = True
    state = _new_state(attacker)
    clear_combat_state(state)
    assert attacker.attacking is False
    assert state.continuous_effects == []


# ---------- ApplyEffect(GrantKeywords, EndOfCombat()) end-to-end ----------


def test_apply_effect_grant_keywords_until_end_of_combat_round_trip():
    """``ApplyEffect(GrantKeywords(...), EndOfCombat())`` writes
    layer-6 ``grant_keyword`` entries with
    ``expires_at="end_of_combat"``; ``effective_keywords`` sees the
    grant during the combat-step window; ``clear_combat_state`` drops
    the entry and the keyword goes away."""
    from mtg_bot.cards.base import make_artifact, make_creature
    from mtg_bot.combat import clear_combat_state
    from mtg_bot.effects import (
        ApplyEffect, EndOfCombat, GrantKeywords,
    )
    from mtg_bot.game import GameState, Player, effective_keywords

    src_obj = _make_obj(make_artifact("Source", "{1}"), obj_id=10)
    tgt_obj = _make_obj(
        make_creature("Bear", "{1}{G}", 2, 2), obj_id=20,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[src_obj, tgt_obj],
        resolving_source=src_obj,
    )
    ApplyEffect(
        inner=GrantKeywords(keywords=frozenset({"flying"})),
        ends_at=EndOfCombat(),
    ).resolve(
        state, controller_id=0, targets=(("creature", tgt_obj.id),),
    )
    # During the combat-step window: keyword granted.
    assert len(state.continuous_effects) == 1
    entry = state.continuous_effects[0]
    assert entry.layer == 6
    assert entry.kind == "grant_keyword"
    assert entry.target_id == tgt_obj.id
    assert entry.params == ("flying",)
    assert entry.expires_at == "end_of_combat"
    assert entry.expires_at_player_id is None
    assert "flying" in effective_keywords(state, tgt_obj)
    # End of combat: registry entry dropped, keyword gone.
    clear_combat_state(state)
    assert state.continuous_effects == []
    assert "flying" not in effective_keywords(state, tgt_obj)


def test_grant_keywords_self_target_with_end_of_combat_duration():
    """Self-target variant: ``ApplyEffect(GrantKeywords(...),
    EndOfCombat())`` with no explicit target falls back to
    ``state.resolving_source`` for the grant target. The
    ``end_of_combat`` lifetime still flows through correctly."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.combat import clear_combat_state
    from mtg_bot.effects import (
        ApplyEffect, EndOfCombat, GrantKeywords,
    )
    from mtg_bot.game import effective_keywords

    source_obj = _make_obj(
        make_creature("Self", "{1}{G}", 2, 2), obj_id=10,
    )
    state = _new_state(source_obj)
    ApplyEffect(
        inner=GrantKeywords(keywords=frozenset({"trample"})),
        ends_at=EndOfCombat(),
    ).resolve(state, controller_id=0, targets=())
    assert "trample" in effective_keywords(state, source_obj)
    entry = state.continuous_effects[0]
    assert entry.source_id == source_obj.id
    assert entry.target_id == source_obj.id
    assert entry.expires_at == "end_of_combat"
    clear_combat_state(state)
    assert state.continuous_effects == []
    assert "trample" not in effective_keywords(state, source_obj)
