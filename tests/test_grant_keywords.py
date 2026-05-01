"""Unit tests for the ``GrantKeywords`` Effect primitive.

``GrantKeywords`` is the keyword-side sibling of ``BecomeType``: it
writes layer-6 ``grant_keyword`` registry entries with
``expires_at=None`` and is composed with
``ApplyEffect(GrantKeywords(...), EndOfTurn())`` for the common UEOT
shape. The legacy ``state.grant_keywords_ueot`` helper has been
retired in favour of this primitive.
"""

from __future__ import annotations


def _new_state(source_obj):
    from mtg_bot.game import GameState, Player

    return GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[source_obj],
        resolving_source=source_obj,
    )


def _make_obj(printing, obj_id=10, controller_id=0):
    from mtg_bot.game import GameObject, Zone

    return GameObject(
        id=obj_id, printing=printing, owner_id=controller_id,
        controller_id=controller_id, zone=Zone.BATTLEFIELD,
    )


# ---------- Self-target: writes registry entries ----------


def test_grant_keywords_self_target_writes_one_entry_per_keyword():
    """With no ``targets`` tuple, ``GrantKeywords`` falls back to
    self-target: registry entries are written with ``source_id ==
    target_id == state.resolving_source.id`` and one entry per
    keyword."""
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import GrantKeywords

    source_obj = _make_obj(make_artifact("Test", "{1}"))
    state = _new_state(source_obj)
    GrantKeywords(
        keywords=frozenset({"haste", "flying"}),
    ).resolve(state, controller_id=0, targets=())
    assert len(state.continuous_effects) == 2
    # Sorted by keyword to be deterministic for the description.
    entries = sorted(
        state.continuous_effects, key=lambda ce: ce.params[0],
    )
    assert entries[0].params == ("flying",)
    assert entries[1].params == ("haste",)
    for ce in entries:
        assert ce.layer == 6
        assert ce.kind == "grant_keyword"
        assert ce.source_id == source_obj.id
        assert ce.target_id == source_obj.id
        # Default ``expires_at=None`` (Permanent); ApplyEffect rewrites
        # for finite durations.
        assert ce.expires_at is None
        assert ce.expires_at_player_id is None


def test_grant_keywords_self_target_visible_via_effective_keywords():
    """Sanity check: the registry write is observable through
    ``effective_keywords`` without touching ``temp_keywords``."""
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import GrantKeywords
    from mtg_bot.game import effective_keywords

    source_obj = _make_obj(make_artifact("Test", "{1}"))
    state = _new_state(source_obj)
    GrantKeywords(
        keywords=frozenset({"haste"}),
    ).resolve(state, controller_id=0, targets=())
    assert "haste" in effective_keywords(state, source_obj)
    # ``temp_keywords`` was NOT mirrored.
    assert source_obj.temp_keywords == frozenset()


# ---------- Explicit target ----------


def test_grant_keywords_explicit_target_writes_against_target_id():
    """When a target tuple is passed, the entry's ``target_id`` is the
    chosen target; ``source_id`` is the resolving source so the entry
    is dropped when the source leaves play."""
    from mtg_bot.cards.base import make_artifact, make_creature
    from mtg_bot.effects import GrantKeywords
    from mtg_bot.game import effective_keywords

    src_obj = _make_obj(make_artifact("Source", "{1}"), obj_id=10)
    tgt_obj = _make_obj(
        make_creature("Bear", "{1}{G}", 2, 2), obj_id=20,
    )
    from mtg_bot.game import GameState, Player

    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[src_obj, tgt_obj],
        resolving_source=src_obj,
    )
    GrantKeywords(
        keywords=frozenset({"trample"}),
    ).resolve(
        state, controller_id=0, targets=(("creature", tgt_obj.id),),
    )
    assert len(state.continuous_effects) == 1
    ce = state.continuous_effects[0]
    assert ce.source_id == src_obj.id
    assert ce.target_id == tgt_obj.id
    assert ce.params == ("trample",)
    assert "trample" in effective_keywords(state, tgt_obj)
    assert "trample" not in effective_keywords(state, src_obj)


def test_grant_keywords_no_resolving_source_falls_back_to_target_id():
    """If there is no ``state.resolving_source`` (e.g., a test setup
    that resolves the effect outside a stack frame), the registry
    ``source_id`` falls back to the target's id — matching
    ``BecomeType``'s shape."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import GrantKeywords
    from mtg_bot.game import GameState, Player

    tgt_obj = _make_obj(
        make_creature("Bear", "{1}{G}", 2, 2), obj_id=20,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[tgt_obj],
        resolving_source=None,
    )
    GrantKeywords(
        keywords=frozenset({"haste"}),
    ).resolve(
        state, controller_id=0, targets=(("creature", tgt_obj.id),),
    )
    assert len(state.continuous_effects) == 1
    ce = state.continuous_effects[0]
    assert ce.source_id == tgt_obj.id
    assert ce.target_id == tgt_obj.id


# ---------- Edge cases ----------


def test_grant_keywords_empty_keyword_set_is_noop():
    """No keywords => no registry writes, no log spam."""
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import GrantKeywords

    source_obj = _make_obj(make_artifact("Test", "{1}"))
    state = _new_state(source_obj)
    GrantKeywords(keywords=frozenset()).resolve(
        state, controller_id=0, targets=(),
    )
    assert state.continuous_effects == []


def test_grant_keywords_missing_target_is_noop():
    """If neither ``targets`` nor ``state.resolving_source`` resolves
    to a battlefield object, the effect is a silent no-op."""
    from mtg_bot.effects import GrantKeywords
    from mtg_bot.game import GameState, Player

    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[],
        resolving_source=None,
    )
    GrantKeywords(
        keywords=frozenset({"haste"}),
    ).resolve(state, controller_id=0, targets=())
    assert state.continuous_effects == []


def test_grant_keywords_describe_lists_keywords_sorted():
    from mtg_bot.effects import GrantKeywords

    desc = GrantKeywords(
        keywords=frozenset({"trample", "haste"}),
    ).describe()
    # Sorted ordering is stable for description output.
    assert "haste" in desc
    assert "trample" in desc
    assert desc.index("haste") < desc.index("trample")


def test_grant_keywords_describe_empty_keyword_set():
    from mtg_bot.effects import GrantKeywords

    assert "no keywords" in GrantKeywords().describe()


# ---------- Composition with ApplyEffect ----------


def test_apply_effect_end_of_turn_rewrites_grant_keyword_lifetimes():
    """``ApplyEffect(GrantKeywords(...), EndOfTurn())`` rewrites every
    appended entry's lifetime to ``expires_at="cleanup"``."""
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import (
        ApplyEffect, EndOfTurn, GrantKeywords,
    )

    source_obj = _make_obj(make_artifact("Test", "{1}"))
    state = _new_state(source_obj)
    ApplyEffect(
        inner=GrantKeywords(
            keywords=frozenset({"haste", "trample"}),
        ),
        ends_at=EndOfTurn(),
    ).resolve(state, controller_id=0, targets=())
    assert len(state.continuous_effects) == 2
    for ce in state.continuous_effects:
        assert ce.layer == 6
        assert ce.kind == "grant_keyword"
        assert ce.expires_at == "cleanup"
        assert ce.expires_at_player_id is None


def test_apply_effect_end_of_turn_grants_round_trip_through_cleanup():
    """End-to-end: ``ApplyEffect(GrantKeywords, EndOfTurn)`` grants
    are visible via ``effective_keywords`` during the turn and gone
    from the registry after cleanup."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import (
        ApplyEffect, EndOfTurn, GrantKeywords,
    )
    from mtg_bot.game import effective_keywords
    from mtg_bot.turn import run_cleanup_step

    bear = _make_obj(
        make_creature("Bear", "{1}{G}", 2, 2), obj_id=20,
    )
    state = _new_state(bear)
    ApplyEffect(
        inner=GrantKeywords(
            keywords=frozenset({"flying"}),
        ),
        ends_at=EndOfTurn(),
    ).resolve(state, controller_id=0, targets=())
    assert "flying" in effective_keywords(state, bear)
    run_cleanup_step(state)
    assert "flying" not in effective_keywords(state, bear)
    # Registry entry was dropped at cleanup.
    assert all(
        ce.kind != "grant_keyword"
        for ce in state.continuous_effects
    )


def test_apply_effect_permanent_grant_survives_cleanup():
    """A bare ``GrantKeywords`` without ``ApplyEffect`` (or with
    ``ApplyEffect(..., Permanent())``) writes a permanent registry
    entry — the grant survives cleanup, mirroring ``BecomeType``'s
    permanent vs. UEOT distinction."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import GrantKeywords
    from mtg_bot.game import effective_keywords
    from mtg_bot.turn import run_cleanup_step

    bear = _make_obj(
        make_creature("Bear", "{1}{G}", 2, 2), obj_id=20,
    )
    state = _new_state(bear)
    GrantKeywords(
        keywords=frozenset({"flying"}),
    ).resolve(state, controller_id=0, targets=())
    assert "flying" in effective_keywords(state, bear)
    run_cleanup_step(state)
    # Registry entry persisted; the keyword is still in effect.
    assert "flying" in effective_keywords(state, bear)


def test_apply_effect_explicit_target_rewrites_lifetime():
    """``ApplyEffect(GrantKeywords, EndOfTurn)`` works with explicit
    ``targets`` — combat-trick shape ("target creature gains haste
    UEOT")."""
    from mtg_bot.cards.base import make_artifact, make_creature
    from mtg_bot.effects import (
        ApplyEffect, EndOfTurn, GrantKeywords,
    )
    from mtg_bot.game import GameState, Player, effective_keywords

    src_obj = _make_obj(make_artifact("Spell", "{1}"), obj_id=10)
    tgt_obj = _make_obj(
        make_creature("Bear", "{1}{G}", 2, 2), obj_id=20,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[src_obj, tgt_obj],
        resolving_source=src_obj,
    )
    ApplyEffect(
        inner=GrantKeywords(
            keywords=frozenset({"haste"}),
        ),
        ends_at=EndOfTurn(),
    ).resolve(
        state, controller_id=0, targets=(("creature", tgt_obj.id),),
    )
    assert len(state.continuous_effects) == 1
    ce = state.continuous_effects[0]
    assert ce.source_id == src_obj.id
    assert ce.target_id == tgt_obj.id
    assert ce.expires_at == "cleanup"
    assert "haste" in effective_keywords(state, tgt_obj)
