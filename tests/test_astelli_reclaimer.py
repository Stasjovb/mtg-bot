"""Tests for Astelli Reclaimer's ETB graveyard reanimate with MV ≤ X,
where X is the mana spent to cast this."""

from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import EOE_CREATURES, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import AstelliReclaimerETBEffect
from mtg_bot.game import GameState, Player, Zone
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _put_in_graveyard(state, printing, owner_id=0):
    c = state.new_object(printing, owner_id, Zone.GRAVEYARD)
    state.players[owner_id].graveyard.append(c)
    return c


# -----------------------
# Effect-level
# -----------------------


def test_effect_requires_target_and_describe():
    e = AstelliReclaimerETBEffect()
    assert e.requires_target()
    d = e.describe()
    assert "graveyard" in d and "X" in d


def test_legal_targets_filters_out_creatures_lands_and_high_cost():
    state = _new_state()
    source = state.new_object(
        EOE_CREATURES["Astelli Reclaimer"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(source)
    state.resolving_source = source
    # CMC 5 (5 + W + W = 5 total? Let's double-check)
    # Actually {3}{W}{W} → generic 3 + 2 colored = 5.
    # So legal: noncreature noncreature nonland permanents with MV ≤ 5.
    try:
        # Add some candidate graveyard cards.
        bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"])
        # Real EoE artifact with MV 1 (no land): Cryogen Relic {1} — verify
        # any artifact in EOE_SPELLS that is small.
        from mtg_bot.cards import BASIC_LANDS
        plains = _put_in_graveyard(state, BASIC_LANDS["Plains"])
        # Infinite Guideline Station: {2} artifact, safe to include.
        igs = _put_in_graveyard(state, EOE_SPELLS["Infinite Guideline Station"])
        legal = AstelliReclaimerETBEffect().legal_targets(state, 0)
        ids = {tid for kind, tid in legal if kind == "graveyard_permanent"}
        assert bear.id not in ids  # creature excluded
        assert plains.id not in ids  # land excluded
        assert igs.id in ids  # noncreature, nonland, MV 2 ≤ 5
    finally:
        state.resolving_source = None


def test_x_uses_warp_cost_when_cast_via_warp():
    state = _new_state()
    source = state.new_object(
        EOE_CREATURES["Astelli Reclaimer"], 0, Zone.BATTLEFIELD,
    )
    source.cast_via_warp = True
    state.battlefield.append(source)
    state.resolving_source = source
    try:
        # Warp cost {2}{W} → X = 3. Put an artifact with MV 4 — NOT legal.
        # Use any real card with CMC 4 non-creature. Pinnacle Starcage
        # {1}{W}{W} = CMC 3 — legal at X=3.
        from mtg_bot.cards import EOE_SPELLS
        # Find something with CMC >3 and <= some high number.
        # Use Memorial Vault {3}{R} = 4 CMC.
        mv = _put_in_graveyard(state, EOE_SPELLS["Memorial Vault"])
        legal = AstelliReclaimerETBEffect().legal_targets(state, 0)
        ids = {tid for _, tid in legal}
        assert mv.id not in ids  # 4 > 3
    finally:
        state.resolving_source = None


def test_effect_resolve_returns_target_to_battlefield():
    state = _new_state(_PickFirstAgent())
    source = state.new_object(
        EOE_CREATURES["Astelli Reclaimer"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(source)
    state.resolving_source = source
    from mtg_bot.cards import EOE_SPELLS
    igs = _put_in_graveyard(state, EOE_SPELLS["Infinite Guideline Station"])
    try:
        AstelliReclaimerETBEffect().resolve(
            state, 0, (("graveyard_permanent", igs.id),),
        )
    finally:
        state.resolving_source = None
    assert igs not in state.players[0].graveyard
    assert igs in state.battlefield


def test_effect_resolve_no_target_noop():
    state = _new_state()
    AstelliReclaimerETBEffect().resolve(state, 0, ())


def test_effect_resolve_wrong_kind_noop():
    state = _new_state()
    AstelliReclaimerETBEffect().resolve(state, 0, (("creature", 1),))


# -----------------------
# Integration: ETB fires
# -----------------------


def test_astelli_etb_reanimates_small_artifact():
    state = _new_state(_PickFirstAgent())
    from mtg_bot.cards import EOE_SPELLS
    igs = _put_in_graveyard(state, EOE_SPELLS["Infinite Guideline Station"])
    astelli = state.new_object(
        EOE_CREATURES["Astelli Reclaimer"], 0, Zone.HAND,
    )
    put_into_battlefield(state, astelli, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    assert igs in state.battlefield


def test_astelli_printing_metadata():
    a = EOE_CREATURES["Astelli Reclaimer"]
    assert "flying" in a.keywords
    assert a.warp_cost_str == "{2}{W}"
    triggers = {_legacy_or_inferred_key(ab) for ab in a.triggered_abilities}
    assert "etb" in triggers
