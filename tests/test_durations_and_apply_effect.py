"""Unit tests for the ``Duration`` value types in
``effects/durations.py`` and the ``ApplyEffect(inner, ends_at)``
combinator in ``effects/combinators.py``.

These split the WHAT (the inner effect's registry writes) from the
WHEN-it-ends (the ``Duration``) so a single primitive (e.g.
``BecomeType``) can be reused across permanent and finite-lifetime
contexts. ``ApplyEffect`` snapshots ``len(state.continuous_effects)``
before the inner resolves, then rewrites every appended entry's
``expires_at`` / ``expires_at_player_id`` from the duration's
translation.
"""

from __future__ import annotations


# ---------- Duration.to_expires translations ----------

def test_permanent_translates_to_none():
    from mtg_bot.effects.durations import Permanent

    assert Permanent().to_expires(controller_id=0) == (None, None)
    assert Permanent().to_expires(controller_id=1) == (None, None)


def test_end_of_turn_translates_to_cleanup():
    from mtg_bot.effects.durations import EndOfTurn

    assert EndOfTurn().to_expires(controller_id=0) == ("cleanup", None)
    # Controller-independent.
    assert EndOfTurn().to_expires(controller_id=42) == ("cleanup", None)


def test_end_of_your_next_turn_carries_controller_id():
    from mtg_bot.effects.durations import EndOfYourNextTurn

    assert EndOfYourNextTurn().to_expires(controller_id=0) == (
        "controller_untap", 0,
    )
    assert EndOfYourNextTurn().to_expires(controller_id=1) == (
        "controller_untap", 1,
    )


def test_end_of_combat_uses_distinct_key():
    """Stub: ``"end_of_combat"`` isn't consumed by any cleanup site
    today. The translation just needs to be stable so wiring later
    is a one-line change."""
    from mtg_bot.effects.durations import EndOfCombat

    assert EndOfCombat().to_expires(controller_id=0) == (
        "end_of_combat", None,
    )


def test_until_source_leaves_is_equivalent_to_permanent_today():
    from mtg_bot.effects.durations import UntilSourceLeaves

    assert UntilSourceLeaves().to_expires(controller_id=0) == (None, None)


def test_durations_describe_strings():
    from mtg_bot.effects.durations import (
        EndOfCombat, EndOfTurn, EndOfYourNextTurn,
        Permanent, UntilSourceLeaves,
    )

    assert "permanent" in Permanent().describe()
    assert "end of turn" in EndOfTurn().describe()
    assert "next turn" in EndOfYourNextTurn().describe()
    assert "combat" in EndOfCombat().describe()
    assert "battlefield" in UntilSourceLeaves().describe()


# ---------- ApplyEffect rewrites lifetimes ----------

def test_apply_effect_with_permanent_default_keeps_none_expiry():
    """Default ``ends_at=Permanent()`` leaves entries with
    ``expires_at=None`` — the same lifetime ``BecomeType`` writes
    natively."""
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import ApplyEffect, BecomeType, Permanent
    from mtg_bot.game import (
        GameObject, GameState, Player, Zone,
    )

    art_pr = make_artifact("Test", "{1}")
    source_obj = GameObject(
        id=10, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[source_obj],
        resolving_source=source_obj,
    )
    ApplyEffect(
        inner=BecomeType(
            types_to_add=("creature",),
            subtypes_to_add=("Spirit",),
            base_pt=(0, 0),
        ),
        ends_at=Permanent(),
    ).resolve(state, controller_id=0, targets=())
    # Three registry entries: add_type creature, add_subtype Spirit,
    # set_base_pt. All permanent.
    assert len(state.continuous_effects) == 3
    assert all(
        ce.expires_at is None and ce.expires_at_player_id is None
        for ce in state.continuous_effects
    )


def test_apply_effect_with_end_of_turn_rewrites_to_cleanup():
    """``ends_at=EndOfTurn()`` rewrites every appended registry entry
    to ``expires_at="cleanup"``."""
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import (
        ApplyEffect, BecomeType, EndOfTurn,
    )
    from mtg_bot.game import (
        GameObject, GameState, Player, Zone,
    )

    art_pr = make_artifact("Test", "{1}")
    source_obj = GameObject(
        id=10, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[source_obj],
        resolving_source=source_obj,
    )
    ApplyEffect(
        inner=BecomeType(
            subtypes_to_add=("Goblin",),
            base_pt=(2, 2),
        ),
        ends_at=EndOfTurn(),
    ).resolve(state, controller_id=0, targets=())
    assert len(state.continuous_effects) == 2
    assert all(
        ce.expires_at == "cleanup" and ce.expires_at_player_id is None
        for ce in state.continuous_effects
    )


def test_apply_effect_with_end_of_your_next_turn_carries_controller_id():
    """``ends_at=EndOfYourNextTurn()`` writes the controller id into
    ``expires_at_player_id`` so the runtime can drop the entry at the
    controller's next untap step."""
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import (
        ApplyEffect, BecomeType, EndOfYourNextTurn,
    )
    from mtg_bot.game import (
        GameObject, GameState, Player, Zone,
    )

    art_pr = make_artifact("Test", "{1}")
    source_obj = GameObject(
        id=10, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[source_obj],
        resolving_source=source_obj,
    )
    ApplyEffect(
        inner=BecomeType(subtypes_to_add=("Spirit",)),
        ends_at=EndOfYourNextTurn(),
    ).resolve(state, controller_id=0, targets=())
    assert len(state.continuous_effects) == 1
    entry = state.continuous_effects[0]
    assert entry.expires_at == "controller_untap"
    assert entry.expires_at_player_id == 0


def test_apply_effect_only_rewrites_entries_added_by_inner():
    """Entries that exist in the registry BEFORE the inner runs are
    not modified — ApplyEffect only rewrites the slice it appended."""
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import (
        ApplyEffect, BecomeType, EndOfTurn,
    )
    from mtg_bot.game import (
        GameObject, GameState, Player, Zone,
    )

    art_pr = make_artifact("Test", "{1}")
    source_obj = GameObject(
        id=10, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[source_obj],
        resolving_source=source_obj,
    )
    # Pre-existing entry — independent of ApplyEffect.
    pre_existing = state.add_continuous_effect(
        source_id=99, layer=4, kind="add_subtype",
        target_id=99, params=("Sliver",),
        expires_at=None,
    )
    ApplyEffect(
        inner=BecomeType(subtypes_to_add=("Spirit",)),
        ends_at=EndOfTurn(),
    ).resolve(state, controller_id=0, targets=())
    # The pre-existing entry stayed Permanent.
    assert state.continuous_effects[0] is pre_existing
    assert state.continuous_effects[0].expires_at is None
    # The ApplyEffect-introduced entry was rewritten to cleanup.
    assert state.continuous_effects[1].expires_at == "cleanup"


def test_apply_effect_describe_combines_inner_and_duration():
    from mtg_bot.effects import (
        ApplyEffect, BecomeType, EndOfTurn,
    )

    desc = ApplyEffect(
        inner=BecomeType(subtypes_to_add=("Spirit",)),
        ends_at=EndOfTurn(),
    ).describe()
    assert "Spirit" in desc
    assert "until end of turn" in desc


def test_apply_effect_forwards_target_metadata_from_inner():
    """``ApplyEffect`` is a transparent wrapper for targeting — it
    delegates ``requires_target`` / ``legal_targets`` /
    ``target_count_range`` to the inner effect so it composes with
    targeted effects without breaking the cast pipeline."""
    from mtg_bot.effects import ApplyEffect, EndOfTurn
    from mtg_bot.effects.base import Effect

    class TargetedStub(Effect):
        def requires_target(self) -> bool:
            return True

        def legal_targets(self, state, controller_id):
            return [("creature", 7)]

        def target_count_range(self) -> tuple[int, int]:
            return (1, 1)

        def resolve(self, state, controller_id, targets=()):
            return None

    inner = TargetedStub()
    wrapper = ApplyEffect(inner=inner, ends_at=EndOfTurn())
    assert wrapper.requires_target() is True
    assert wrapper.target_count_range() == (1, 1)
    assert wrapper.legal_targets(None, 0) == [("creature", 7)]


def test_apply_effect_round_trips_through_cleanup():
    """End-to-end: an ApplyEffect+EndOfTurn entry vanishes from the
    registry at ``run_cleanup_step``. PT and subtype reads (which
    consult the registry) revert as soon as the entry is dropped."""
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import (
        ApplyEffect, BecomeType, EndOfTurn,
    )
    from mtg_bot.game import (
        GameObject, GameState, Player, Zone,
        effective_subtypes, _compute_effective_pt,
    )
    from mtg_bot.turn import run_cleanup_step

    art_pr = make_artifact("Lump", "{1}")
    source_obj = GameObject(
        id=10, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[source_obj],
        resolving_source=source_obj,
    )
    ApplyEffect(
        inner=BecomeType(
            subtypes_to_add=("Goblin",),
            base_pt=(3, 3),
        ),
        ends_at=EndOfTurn(),
    ).resolve(state, controller_id=0, targets=())
    # During the turn: subtype + PT applied.
    assert "Goblin" in effective_subtypes(state, source_obj)
    assert _compute_effective_pt(state, source_obj) == (3, 3)
    # After cleanup: registry entries dropped.
    run_cleanup_step(state)
    assert "Goblin" not in effective_subtypes(state, source_obj)
    # PT reverts when no set_base_pt entry exists; an artifact with no
    # printed P/T resolves to (0, 0).
    assert _compute_effective_pt(state, source_obj) == (0, 0)
