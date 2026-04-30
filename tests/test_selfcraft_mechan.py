"""Tests for Selfcraft Mechan's may-sac-artifact → +1/+1 counter + draw
ETB.

Selfcraft Mechan was migrated from the bespoke ``SelfcraftMechanETBEffect``
engine class to the oracle-text grammar in bespoke-artifact-misc.  The
grammar path produces an ``OptionalSacArtifactForEffect`` wrapping a
``Sequence`` of ``PutPlusOneCounterOnTargetCreature`` and ``DrawCards(1)``
— the same observable behavior as the bespoke class.

Effect-level tests now exercise the grammar-produced effect; integration
tests remain unchanged because they drive through ``_PRINTINGS`` (which
resolves via the oracle parser).
"""

from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects.combinators import OptionalSacArtifactForEffect
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic import DrawCards, PutPlusOneCounterOnTargetCreature
from mtg_bot.game import GameState, Player, Zone
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_sacrifice(self, state, player_id, legal_ids):
        return legal_ids[0] if legal_ids else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _stock_library(state, player_id, n):
    p = state.players[player_id]
    for _ in range(n):
        c = state.new_object(BASIC_LANDS["Plains"], player_id, Zone.LIBRARY)
        p.library.append(c)


# -----------------------
# Grammar-path effect structure
# -----------------------


def test_grammar_printing_has_optional_sac_artifact_effect():
    """The grammar-produced ETB trigger carries an
    ``OptionalSacArtifactForEffect`` wrapping a ``Sequence``."""
    from mtg_bot.effects.predicates import Event

    m = _PRINTINGS["Selfcraft Mechan"]
    etb = [t for t in m.triggered_abilities if t.event == Event.ENTERS]
    assert len(etb) == 1
    eff = etb[0].effect
    assert isinstance(eff, OptionalSacArtifactForEffect)
    assert isinstance(eff.inner_effect, Sequence)


def test_grammar_effect_requires_target_and_describe():
    """The grammar-produced effect requires a target (delegated from the
    inner ``PutPlusOneCounterOnTargetCreature``) and its describe
    string mentions sacrifice, +1/+1 counter, and draw."""
    m = _PRINTINGS["Selfcraft Mechan"]
    from mtg_bot.effects.predicates import Event

    etb = [t for t in m.triggered_abilities if t.event == Event.ENTERS]
    eff = etb[0].effect
    assert eff.requires_target()
    d = eff.describe()
    assert "sacrifice" in d and "+1/+1" in d and "draw" in d


def test_grammar_effect_legal_targets_includes_all_creatures():
    """legal_targets on the grammar-produced effect returns all creatures
    on the battlefield (same as the former bespoke class)."""
    state = _new_state()
    own = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(own)
    enemy = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy)
    m = _PRINTINGS["Selfcraft Mechan"]
    from mtg_bot.effects.predicates import Event

    etb = [t for t in m.triggered_abilities if t.event == Event.ENTERS]
    eff = etb[0].effect
    legal = eff.legal_targets(state, 0)
    ids = {tid for _, tid in legal}
    assert own.id in ids and enemy.id in ids


# -----------------------
# Integration
# -----------------------


def test_selfcraft_etb_sacs_artifact_puts_counter_draws():
    state = _new_state(_PickFirstAgent())
    _stock_library(state, 0, 3)
    # Target creature (non-artifact) to receive counter.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    # Cast Selfcraft — it itself becomes an artifact on the bf and is a
    # candidate to sacrifice. PickFirst selects the first artifact it
    # sees, which is Selfcraft Mechan (only artifact). Mechan gets
    # sac'd, Bear gets the counter.
    mechan = state.new_object(
        _PRINTINGS["Selfcraft Mechan"], 0, Zone.HAND,
    )
    put_into_battlefield(state, mechan, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # Mechan is gone, Bear has a counter, one card drawn.
    assert mechan not in state.battlefield
    assert bear.plus_one_counters == 1
    # Drew exactly one card — hand now has 1 Plains.
    assert len(state.players[0].hand) == 1


def test_selfcraft_etb_fizzles_when_no_artifact_can_be_sacrificed():
    state = _new_state(_PickFirstAgent())
    _stock_library(state, 0, 3)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    # Resolve the grammar-produced effect directly (not via ETB) so
    # Mechan isn't on the battlefield as a candidate artifact —
    # simulating a scenario where no artifact is available. No artifact
    # → the optional sac has no legal options → silent no-op.
    from mtg_bot.effects.predicates import Event
    m = _PRINTINGS["Selfcraft Mechan"]
    eff = next(t for t in m.triggered_abilities if t.event == Event.ENTERS).effect
    eff.resolve(state, 0, (("creature", bear.id),))
    assert bear.plus_one_counters == 0
    assert len(state.players[0].hand) == 0


def test_selfcraft_printing_has_etb():
    m = _PRINTINGS["Selfcraft Mechan"]
    triggers = {_legacy_or_inferred_key(ab) for ab in m.triggered_abilities}
    assert "etb" in triggers
    assert m.is_artifact


# -----------------------
# may-decision (choose_yes_no)
# -----------------------


class _NoSacAgent(Agent):
    """Declines the optional sacrifice but still picks first target."""

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_sacrifice(self, state, player_id, legal_ids):
        return legal_ids[0] if legal_ids else None

    def choose_yes_no(self, state, player_id, prompt):
        return False


def test_selfcraft_etb_declined_by_yes_no_agent():
    """When the controller's agent declines via choose_yes_no, no
    artifact is sacrificed, no counter is placed, and no card is drawn.
    """
    state = _new_state(_NoSacAgent())
    _stock_library(state, 0, 3)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    mechan = state.new_object(
        _PRINTINGS["Selfcraft Mechan"], 0, Zone.HAND,
    )
    put_into_battlefield(state, mechan, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # Mechan is still on the battlefield (not sacrificed).
    assert mechan in state.battlefield
    # Bear got no counter, no card drawn.
    assert bear.plus_one_counters == 0
    assert len(state.players[0].hand) == 0


def test_selfcraft_default_agent_says_yes():
    """Default ``Agent.choose_yes_no`` returns True, so an agent that
    doesn't override it preserves the legacy "may → always yes"
    behavior — sacrifice happens, counter applied, card drawn."""
    # _PickFirstAgent inherits the base True default.
    state = _new_state(_PickFirstAgent())
    _stock_library(state, 0, 3)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    mechan = state.new_object(
        _PRINTINGS["Selfcraft Mechan"], 0, Zone.HAND,
    )
    put_into_battlefield(state, mechan, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # Mechan got sacrificed — same printing-level invariant as the
    # original behavior.
    assert mechan not in state.battlefield
    assert bear.plus_one_counters == 1
    assert len(state.players[0].hand) == 1
