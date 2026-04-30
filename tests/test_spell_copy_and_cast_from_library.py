"""Tests for Roving Actuator (spell copy from graveyard) and
Mm'menon, the Right Hand (cast artifact spells from top of library)."""

from mtg_bot import legal_moves
from mtg_bot.actions import CastSpell, apply_action, put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects import RovingActuatorETBEffect
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None

    def choose_x(self, state, player_id, card_name, upper_bound):
        return upper_bound


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _put_in_graveyard(state, printing, owner_id=0):
    c = state.new_object(printing, owner_id, Zone.GRAVEYARD)
    state.players[owner_id].graveyard.append(c)
    return c


# -----------------------
# RovingActuatorETBEffect
# -----------------------


def test_effect_legal_targets_are_low_mv_spells():
    state = _new_state()
    # Plasma Bolt ({R}) — MV 1, instant, legal.
    bolt = _put_in_graveyard(state, _PRINTINGS["Plasma Bolt"])
    # Close Encounter ({R}{G}) — MV 2, sorcery, legal.
    ce = _put_in_graveyard(state, _PRINTINGS["Close Encounter"])
    # Hymn of the Faller ({2}) — MV 2 sorcery, legal.
    hymn = _put_in_graveyard(state, _PRINTINGS["Hymn of the Faller"])
    # Wild Bear (creature) — not an instant/sorcery.
    bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"])
    targets = RovingActuatorETBEffect().legal_targets(state, 0)
    ids = {tid for kind, tid in targets if kind == "graveyard_spell"}
    assert bolt.id in ids
    assert ce.id in ids
    assert hymn.id in ids
    assert bear.id not in ids


def test_effect_exiles_and_resolves_spell_copy():
    state = _new_state()
    # Plasma Bolt deals 2 to any target.
    bolt = _put_in_graveyard(state, _PRINTINGS["Plasma Bolt"])
    p0_life_before = state.players[0].life
    p1_life_before = state.players[1].life
    RovingActuatorETBEffect().resolve(
        state, 0, (("graveyard_spell", bolt.id),),
    )
    # Bolt moved from graveyard to exile.
    assert bolt not in state.players[0].graveyard
    assert bolt in state.players[0].exile
    # Copy resolved — some player/creature took 2 damage (PickFirst
    # picks the first legal target, which could be P0).
    total_life_loss = (
        (p0_life_before - state.players[0].life)
        + (p1_life_before - state.players[1].life)
    )
    assert total_life_loss == 2


def test_effect_no_target_is_noop():
    state = _new_state()
    RovingActuatorETBEffect().resolve(state, 0, ())


def test_effect_wrong_kind_is_noop():
    state = _new_state()
    RovingActuatorETBEffect().resolve(state, 0, (("creature", 1),))


def test_effect_describe():
    d = RovingActuatorETBEffect().describe()
    assert "instant or sorcery" in d and "copy" in d


# -----------------------
# Roving Actuator integration
# -----------------------


def test_roving_actuator_etb_requires_void():
    state = _new_state()
    # Void inactive — actuator's ETB should NOT fire even with a
    # valid graveyard target.
    _put_in_graveyard(state, _PRINTINGS["Plasma Bolt"])
    ra = state.new_object(_PRINTINGS["Roving Actuator"], 0, Zone.HAND)
    put_into_battlefield(state, ra, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # P1 life unchanged — no Void → no trigger → no copy.
    assert state.players[1].life == 20


def test_roving_actuator_etb_fires_with_void_active():
    state = _new_state()
    # Void activation: mark permanent-left-battlefield.
    state.permanent_left_battlefield_this_turn = True
    bolt = _put_in_graveyard(state, _PRINTINGS["Plasma Bolt"])
    ra = state.new_object(_PRINTINGS["Roving Actuator"], 0, Zone.HAND)
    put_into_battlefield(state, ra, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # Plasma Bolt exiled by Actuator (proves the ETB fired).
    assert bolt in state.players[0].exile


def test_roving_actuator_printing_has_void_gated_etb():
    from mtg_bot.effects.predicates import Event

    # Oracle text has no Warp line; the former bespoke entry carried a
    # spurious warp="{1}{R}" not in the printed text. The grammar-claimed
    # printing faithfully omits warp (oracle-text fidelity per CLAUDE.md).
    ra = _PRINTINGS["Roving Actuator"]
    assert ra.warp_cost_str == ""
    # Grammar path: the trigger has event=ENTERS and the Void gate is encoded
    # as a composed predicate (IsSelf() & StateBound(VoidActive())) rather
    # than the ``requires_void`` flag used by the former static bespoke entry.
    # Check by event directly — ``_matches_legacy_key`` doesn't handle the
    # gated IsSelf() & StateBound() predicate shape today.
    etb_abilities = [
        a for a in ra.triggered_abilities if a.event == Event.ENTERS
    ]
    assert len(etb_abilities) == 1
    assert "VoidActive" in repr(etb_abilities[0].predicate)


# -----------------------
# Mm'menon: cast artifact from top of library
# -----------------------


def test_mmenon_offers_cast_for_top_artifact_in_library():
    state = _new_state()
    _put(state, _PRINTINGS["Mm'menon, the Right Hand"])
    # Mana for a {1} artifact.
    _put(state, BASIC_LANDS["Island"])
    # Top of library: Nutrient Block ({1}, artifact).
    block = state.new_object(_PRINTINGS["Nutrient Block"], 0, Zone.LIBRARY)
    state.players[0].library.insert(0, block)
    actions = legal_moves(state)
    assert any(
        isinstance(a, CastSpell) and a.card_id == block.id for a in actions
    )


def test_mmenon_does_not_offer_non_artifact_top():
    state = _new_state()
    _put(state, _PRINTINGS["Mm'menon, the Right Hand"])
    _put(state, BASIC_LANDS["Island"])
    # Top of library: Wild Bear (creature, non-artifact) → not offered.
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.LIBRARY)
    state.players[0].library.insert(0, bear)
    actions = legal_moves(state)
    assert not any(
        isinstance(a, CastSpell) and a.card_id == bear.id for a in actions
    )


def test_mmenon_not_offered_without_controller():
    state = _new_state()
    # No Mm'menon on bf — top-of-library casting not granted.
    _put(state, BASIC_LANDS["Island"])
    block = state.new_object(_PRINTINGS["Nutrient Block"], 0, Zone.LIBRARY)
    state.players[0].library.insert(0, block)
    actions = legal_moves(state)
    assert not any(
        isinstance(a, CastSpell) and a.card_id == block.id for a in actions
    )


def test_mmenon_cast_from_library_actually_resolves():
    state = _new_state()
    _put(state, _PRINTINGS["Mm'menon, the Right Hand"])
    _put(state, BASIC_LANDS["Island"])
    block = state.new_object(_PRINTINGS["Nutrient Block"], 0, Zone.LIBRARY)
    state.players[0].library.insert(0, block)
    apply_action(state, 0, CastSpell(block.id))
    # Resolve the stack — Nutrient Block is a permanent, lands on bf.
    while state.stack:
        resolve_top_of_stack(state)
    assert block in state.battlefield
    assert block not in state.players[0].library


def test_mmenon_printing_has_flag():
    m = _PRINTINGS["Mm'menon, the Right Hand"]
    assert m.grants_cast_artifact_from_top_of_library is True
    assert "flying" in m.keywords
    assert "Legendary" in m.supertypes
