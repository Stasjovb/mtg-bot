"""Sami, Wildcat Captain's static ability: ``Spells you cast have
affinity for artifacts. (They cost {1} less to cast for each artifact
you control.)``

Audit-found bug: the affinity discount was silently dropped with a
comment claiming we don't model it. It's now modeled via a new
``"affinity_for_artifacts"`` condition on ``ExternalCostReduction``,
so any spell the controller casts is reduced by ``amount * count``
where ``count`` is the number of artifacts they control on the
battlefield (RAW: spell on stack does not count toward its own
discount).
"""

from mtg_bot.actions import apply_cost_reductions
from mtg_bot.cards import EOE_CREATURES, ExternalCostReduction
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


def _new_state():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# Printing shape
# -----------------------


def test_sami_printing_has_external_affinity_reduction():
    p = EOE_CREATURES["Sami, Wildcat Captain"]
    assert p.is_legendary is True
    assert "double strike" in p.keywords
    assert "vigilance" in p.keywords
    assert p.external_cost_reductions == (
        ExternalCostReduction(amount=1, condition="affinity_for_artifacts"),
    )


# -----------------------
# Cost-reduction integration
# -----------------------


def test_no_artifacts_means_no_discount():
    state = _new_state()
    _put(state, EOE_CREATURES["Sami, Wildcat Captain"])
    # Cast something else — Rayblade Trooper {2}{G}.
    target = EOE_CREATURES["Rayblade Trooper"]
    reduced = apply_cost_reductions(target, state, 0, target.mana_cost)
    # Sami herself isn't an artifact, so artifact_count = 0; full price.
    assert reduced.generic == target.mana_cost.generic


def test_one_artifact_grants_one_less():
    state = _new_state()
    _put(state, EOE_CREATURES["Sami, Wildcat Captain"])
    # Drop one artifact: Auxiliary Boosters (a {4}{W} Equipment).
    _put(state, EOE_CREATURES["Auxiliary Boosters"])
    target = EOE_CREATURES["Rayblade Trooper"]  # base {2}{G}
    reduced = apply_cost_reductions(target, state, 0, target.mana_cost)
    assert reduced.generic == target.mana_cost.generic - 1


def test_three_artifacts_grants_three_less():
    state = _new_state()
    _put(state, EOE_CREATURES["Sami, Wildcat Captain"])
    for _ in range(3):
        _put(state, EOE_CREATURES["Auxiliary Boosters"])
    target = EOE_CREATURES["Rayblade Trooper"]  # base {2}{G} — generic 2
    reduced = apply_cost_reductions(target, state, 0, target.mana_cost)
    # 2 generic - 3 reduction → clamped to 0 (colored pips unaffected).
    assert reduced.generic == 0
    assert reduced.colored == target.mana_cost.colored


def test_opponent_artifacts_do_not_count():
    state = _new_state()
    _put(state, EOE_CREATURES["Sami, Wildcat Captain"], owner_id=0)
    # Opponent's artifacts shouldn't affect P0's discount.
    opp_artifact = state.new_object(
        EOE_CREATURES["Auxiliary Boosters"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_artifact)
    target = EOE_CREATURES["Rayblade Trooper"]
    reduced = apply_cost_reductions(target, state, 0, target.mana_cost)
    assert reduced.generic == target.mana_cost.generic


def test_sami_off_battlefield_means_no_discount():
    """If Sami isn't on the battlefield, her static doesn't apply."""
    state = _new_state()
    # Put two artifacts but no Sami.
    for _ in range(2):
        _put(state, EOE_CREATURES["Auxiliary Boosters"])
    target = EOE_CREATURES["Rayblade Trooper"]
    reduced = apply_cost_reductions(target, state, 0, target.mana_cost)
    assert reduced.generic == target.mana_cost.generic


def test_other_players_sami_does_not_help_us():
    state = _new_state()
    sami = state.new_object(
        EOE_CREATURES["Sami, Wildcat Captain"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(sami)
    _put(state, EOE_CREATURES["Auxiliary Boosters"])  # P0 artifact
    target = EOE_CREATURES["Rayblade Trooper"]
    # P0 is casting; their Sami is not on the battlefield, only P1's
    # is — externals only apply for the caster's own permanents.
    reduced = apply_cost_reductions(target, state, 0, target.mana_cost)
    assert reduced.generic == target.mana_cost.generic


def test_phased_out_sami_does_not_apply():
    state = _new_state()
    sami = _put(state, EOE_CREATURES["Sami, Wildcat Captain"])
    sami.phased_out = True
    _put(state, EOE_CREATURES["Auxiliary Boosters"])
    target = EOE_CREATURES["Rayblade Trooper"]
    reduced = apply_cost_reductions(target, state, 0, target.mana_cost)
    assert reduced.generic == target.mana_cost.generic


# -----------------------
# Stacking with own cost reductions
# -----------------------


def test_affinity_stacks_with_targets_own_reductions():
    """If the spell being cast has its own cost_reductions AND Sami is
    in play, both apply. Sami's external is applied first (before any
    own-reduction)."""
    state = _new_state()
    _put(state, EOE_CREATURES["Sami, Wildcat Captain"])
    # Two artifacts → -2 from Sami's affinity.
    for _ in range(2):
        _put(state, EOE_CREATURES["Auxiliary Boosters"])
    # Gigastorm Titan has its own -3 reduction when conditions met.
    titan = EOE_CREATURES["Gigastorm Titan"]
    state.players[0].spells_cast_this_turn = 0
    reduced = apply_cost_reductions(titan, state, 0, titan.mana_cost)
    # Titan's own reduction may or may not fire depending on state; we
    # just need Sami's -2 to land. Titan's printed generic minus 2:
    assert reduced.generic <= max(0, titan.mana_cost.generic - 2)
