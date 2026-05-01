"""Tests for the per-opponent independent-choice primitives in
``effects/generic.py``: ``EachOpponentExilesOwnCreature`` and
``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage``.

Behavioral coverage:
- exile branch fires for each opponent in turn-order
- linkage to ``state.resolving_source`` via ``exiled_by_source``
- skip-on-no-creature / skip-on-no-agent / skip-controller / skip-lost
- Osseous Sticktwister body: each branch (sac / discard / decline) and
  the conditional source-power damage to non-compliers
"""

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.base import make_creature
from mtg_bot.effects import (
    EachOpponentExilesOwnCreature,
    EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage,
)
from mtg_bot.game import GameObject, GameState, Player, Zone


class _PickFirst:
    """Minimal agent stub: picks first option for every prompt."""

    def choose_sacrifice(self, state, pid, legal_ids):
        return legal_ids[0] if legal_ids else None

    def choose_discard(self, state, pid, hand_ids):
        return hand_ids[0] if hand_ids else None

    def choose_mode(self, state, pid, modes):
        return 0


# ---------- EachOpponentExilesOwnCreature ----------


def test_each_opponent_exiles_own_creature_skips_controller():
    """The controller's creature is NOT exiled — only opponents'."""
    src_pr = make_creature("Source", "{B}", 1, 1)
    src = GameObject(
        id=1, printing=src_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    own_pr = SYNTHETIC_CREATURES["Wild Bear"]
    own = GameObject(
        id=2, printing=own_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1, agent=_PickFirst())],
        battlefield=[src, own],
        resolving_source=src,
    )
    EachOpponentExilesOwnCreature().resolve(
        state, controller_id=0, targets=(),
    )
    # Controller's creature untouched; opponent had no creatures so
    # nothing was exiled either.
    assert own in state.battlefield


def test_each_opponent_exiles_own_creature_link_to_source_tags_exiled_by_source():
    """``link_to_source=True`` tags the exiled object with
    ``exiled_by_source = source.id`` so a sibling ability on the same
    source can later locate it (Sothera's recall pattern)."""
    src_pr = make_creature("Source", "{B}", 1, 1)
    src = GameObject(
        id=1, printing=src_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    enemy = GameObject(
        id=2, printing=SYNTHETIC_CREATURES["Wild Bear"],
        owner_id=1, controller_id=1, zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1, agent=_PickFirst())],
        battlefield=[src, enemy],
        resolving_source=src,
    )
    EachOpponentExilesOwnCreature(link_to_source=True).resolve(
        state, controller_id=0, targets=(),
    )
    assert enemy not in state.battlefield
    assert enemy in state.players[1].exile
    assert enemy.exiled_by_source == src.id


def test_each_opponent_exiles_own_creature_no_link_when_link_false():
    """``link_to_source=False`` (default) leaves ``exiled_by_source``
    unset — a plain zone change with no source-link bookkeeping."""
    src_pr = make_creature("Source", "{B}", 1, 1)
    src = GameObject(
        id=1, printing=src_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    enemy = GameObject(
        id=2, printing=SYNTHETIC_CREATURES["Wild Bear"],
        owner_id=1, controller_id=1, zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1, agent=_PickFirst())],
        battlefield=[src, enemy],
        resolving_source=src,
    )
    EachOpponentExilesOwnCreature(link_to_source=False).resolve(
        state, controller_id=0, targets=(),
    )
    assert enemy not in state.battlefield
    assert enemy.exiled_by_source is None


def test_each_opponent_exiles_own_creature_skips_lost_player():
    """Players who've already lost are skipped (consistent with
    other ``EachOpponent*`` primitives)."""
    src_pr = make_creature("Source", "{B}", 1, 1)
    src = GameObject(
        id=1, printing=src_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    enemy = GameObject(
        id=2, printing=SYNTHETIC_CREATURES["Wild Bear"],
        owner_id=1, controller_id=1, zone=Zone.BATTLEFIELD,
    )
    p1 = Player(id=1, agent=_PickFirst())
    p1.has_lost = True
    state = GameState(
        players=[Player(id=0), p1],
        battlefield=[src, enemy],
        resolving_source=src,
    )
    EachOpponentExilesOwnCreature().resolve(
        state, controller_id=0, targets=(),
    )
    assert enemy in state.battlefield


def test_each_opponent_exiles_own_creature_skips_opponent_without_creatures():
    """An opponent who controls no creatures is silently skipped."""
    src_pr = make_creature("Source", "{B}", 1, 1)
    src = GameObject(
        id=1, printing=src_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1, agent=_PickFirst())],
        battlefield=[src],
        resolving_source=src,
    )
    # Should not raise.
    EachOpponentExilesOwnCreature().resolve(
        state, controller_id=0, targets=(),
    )


def test_each_opponent_exiles_own_creature_short_circuits_when_link_requested_but_no_source():
    """When ``link_to_source=True`` and ``state.resolving_source`` is
    None, the primitive short-circuits rather than producing exiled
    cards with no link (which downstream effects can't find)."""
    enemy = GameObject(
        id=2, printing=SYNTHETIC_CREATURES["Wild Bear"],
        owner_id=1, controller_id=1, zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1, agent=_PickFirst())],
        battlefield=[enemy],
        resolving_source=None,
    )
    EachOpponentExilesOwnCreature(link_to_source=True).resolve(
        state, controller_id=0, targets=(),
    )
    # No exile, no crash.
    assert enemy in state.battlefield


def test_each_opponent_exiles_own_creature_describe():
    d = EachOpponentExilesOwnCreature().describe()
    assert "opponent" in d and "exile" in d


# ---------- EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage ----------


def _make_osseous_state(opp_agent):
    """Helper: build a state with Osseous-like 2/2 source on P0, P1 is
    the opponent with the supplied agent."""
    src_pr = make_creature(
        "Osseous Sticktwister", "{1}{B}", 2, 2,
        artifact=True, subtypes=("Scarecrow",),
        keywords={"lifelink"},
    )
    src = GameObject(
        id=1, printing=src_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    p0 = Player(id=0, life=20)
    p1 = Player(id=1, agent=opp_agent, life=20)
    state = GameState(
        players=[p0, p1],
        battlefield=[src],
        resolving_source=src,
    )
    return state, src


def test_osseous_primitive_decline_takes_source_power_damage():
    """Opponent picks decline (last mode) → takes source-power damage."""
    class _Decline:
        def choose_mode(self, state, pid, modes):
            # Decline is always the last option.
            return len(modes) - 1

    state, _ = _make_osseous_state(_Decline())
    EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage().resolve(
        state, controller_id=0, targets=(),
    )
    assert state.players[1].life == 18


def test_osseous_primitive_sac_skips_damage():
    """Opponent picks sacrifice (mode 0 when sac available) → no damage."""
    class _PickSac:
        def choose_mode(self, state, pid, modes):
            return 0  # sac is mode 0 when available

        def choose_sacrifice(self, state, pid, legal_ids):
            return legal_ids[0]

    state, _ = _make_osseous_state(_PickSac())
    bear = GameObject(
        id=2, printing=SYNTHETIC_CREATURES["Wild Bear"],
        owner_id=1, controller_id=1, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage().resolve(
        state, controller_id=0, targets=(),
    )
    # Bear was sacrificed; opponent took no damage.
    assert bear not in state.battlefield
    assert state.players[1].life == 20


def test_osseous_primitive_discard_skips_damage():
    """Opponent picks discard (mode 0 when no sac) → no damage."""
    class _PickDiscard:
        def choose_mode(self, state, pid, modes):
            return 0  # discard is mode 0 when no sac is available

        def choose_discard(self, state, pid, hand_ids):
            return hand_ids[0]

    state, _ = _make_osseous_state(_PickDiscard())
    # Give P1 a card in hand, no battlefield permanents.
    card = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.HAND,
    )
    state.players[1].hand.append(card)
    EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage().resolve(
        state, controller_id=0, targets=(),
    )
    assert card in state.players[1].graveyard
    assert state.players[1].life == 20


def test_osseous_primitive_no_options_means_decline():
    """Opponent has no permanents AND no hand → only mode is decline,
    they take damage."""
    class _PickAny:
        def choose_mode(self, state, pid, modes):
            return 0  # only decline is offered

    state, _ = _make_osseous_state(_PickAny())
    EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage().resolve(
        state, controller_id=0, targets=(),
    )
    assert state.players[1].life == 18


def test_osseous_primitive_skips_controller_and_lost_players():
    """Each-opponent primitives never affect the controller or lost
    players."""
    class _PickAny:
        def choose_mode(self, state, pid, modes):
            return len(modes) - 1  # decline

    state, _ = _make_osseous_state(_PickAny())
    # Add a third player who has lost.
    lost_p = Player(id=2, agent=_PickAny(), life=20)
    lost_p.has_lost = True
    state.players.append(lost_p)
    EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage().resolve(
        state, controller_id=0, targets=(),
    )
    assert state.players[0].life == 20  # controller
    assert state.players[1].life == 18  # opponent declined → 2 damage
    assert state.players[2].life == 20  # lost player skipped


def test_osseous_primitive_missing_agent_counts_as_decline():
    """Defensive: an opponent with no agent counts as decline (takes
    source-power damage) — mirrors the bespoke behavior."""
    state, _ = _make_osseous_state(opp_agent=None)
    EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage().resolve(
        state, controller_id=0, targets=(),
    )
    assert state.players[1].life == 18


def test_osseous_primitive_zero_power_no_damage():
    """If the source's effective power is 0, the damage step is a
    no-op even when opponents declined."""
    class _Decline:
        def choose_mode(self, state, pid, modes):
            return len(modes) - 1

    src_pr = make_creature(
        "Zero", "{1}{B}", 0, 1, artifact=True,
    )
    src = GameObject(
        id=1, printing=src_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1, agent=_Decline(), life=20)],
        battlefield=[src],
        resolving_source=src,
    )
    EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage().resolve(
        state, controller_id=0, targets=(),
    )
    assert state.players[1].life == 20


def test_osseous_primitive_no_op_without_resolving_source():
    """Defensive: missing source → silent no-op."""
    state = GameState(players=[Player(id=0), Player(id=1)])
    EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage().resolve(
        state, controller_id=0, targets=(),
    )


def test_osseous_primitive_describe():
    d = EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage().describe()
    assert "sacrifice" in d
    assert "discard" in d
    assert "damage" in d
