"""Tests for Squire's Lightblade — ETB attaches to target creature you
control AND grants that creature first strike until end of turn.

The granted-first-strike-UEOT clause was previously documented-as-dropped
in the printing definition; this test file pins the wired behavior so
the rider doesn't silently regress.
"""

from mtg_bot.agents import Agent
from mtg_bot.cards import EOE_CREATURES, SYNTHETIC_CREATURES
from mtg_bot.effects import AttachToTargetCreatureYouControl
from mtg_bot.game import (
    GameState, Player, Zone,
    effective_keywords, effective_power, effective_toughness,
)
from mtg_bot.turn import run_cleanup_step


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# Printing-level baseline (preserve existing behavior)
# -----------------------


def test_printing_has_flash_and_equipment_bonus_unchanged():
    """Restoring the rider must not disturb the printed Flash / +1/+0."""
    c = EOE_CREATURES["Squire's Lightblade"]
    assert "flash" in c.keywords
    # Equipment continuous bonus is unchanged: +1/+0, no granted
    # static keywords on the equipped creature.
    assert c.equipment_bonuses == (1, 0, frozenset())


def test_printing_etb_attaches_via_attach_effect():
    c = EOE_CREATURES["Squire's Lightblade"]
    etbs = [ab for ab in c.triggered_abilities if ab.trigger == "etb"]
    assert len(etbs) == 1
    assert isinstance(etbs[0].effect, AttachToTargetCreatureYouControl)


def test_printing_etb_grants_first_strike_ueot():
    """The dropped 'first strike UEOT' rider is now wired."""
    c = EOE_CREATURES["Squire's Lightblade"]
    etb_effect = next(
        ab.effect for ab in c.triggered_abilities if ab.trigger == "etb"
    )
    assert isinstance(etb_effect, AttachToTargetCreatureYouControl)
    assert etb_effect.granted_keywords_ueot == frozenset({"first strike"})


# -----------------------
# Resolution: ETB grants both attach (+1/+0) and first strike UEOT
# -----------------------


def test_etb_attaches_and_grants_first_strike_until_eot():
    state = _new_state()
    ally = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    blade = _put(state, EOE_CREATURES["Squire's Lightblade"])
    # Sanity: target doesn't have first strike before ETB resolves.
    assert "first strike" not in effective_keywords(state, ally)

    etb = next(
        ab for ab in blade.printing.triggered_abilities
        if ab.trigger == "etb"
    )
    state.resolving_source = blade
    etb.effect.resolve(state, 0, (("creature", ally.id),))

    # Equipment is now attached to the target.
    assert blade.attached_to == ally.id
    # Equipment-attached continuous +1/+0 applies via the Equipment
    # subsystem (Wild Bear is a 2/2 → 3/2).
    assert effective_power(state, ally) == 3
    assert effective_toughness(state, ally) == 2
    # Granted first-strike UEOT is on the target.
    assert "first strike" in effective_keywords(state, ally)


def test_first_strike_clears_at_cleanup_but_attach_and_buff_persist():
    state = _new_state()
    ally = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    blade = _put(state, EOE_CREATURES["Squire's Lightblade"])

    etb = next(
        ab for ab in blade.printing.triggered_abilities
        if ab.trigger == "etb"
    )
    state.resolving_source = blade
    etb.effect.resolve(state, 0, (("creature", ally.id),))
    assert "first strike" in effective_keywords(state, ally)

    run_cleanup_step(state)

    # UEOT first strike wears off at cleanup.
    assert "first strike" not in effective_keywords(state, ally)
    # But the Equipment is still attached, and its +1/+0 still applies.
    assert blade.attached_to == ally.id
    assert effective_power(state, ally) == 3
    assert effective_toughness(state, ally) == 2


def test_etb_does_not_grant_first_strike_to_other_creatures():
    """Only the chosen target gains first strike — not every creature."""
    state = _new_state()
    chosen = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    bystander = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    blade = _put(state, EOE_CREATURES["Squire's Lightblade"])

    etb = next(
        ab for ab in blade.printing.triggered_abilities
        if ab.trigger == "etb"
    )
    state.resolving_source = blade
    etb.effect.resolve(state, 0, (("creature", chosen.id),))

    assert "first strike" in effective_keywords(state, chosen)
    assert "first strike" not in effective_keywords(state, bystander)


# -----------------------
# AttachToTargetCreatureYouControl.granted_keywords_ueot
# (effect-level, decoupled from the Squire's Lightblade printing)
# -----------------------


def test_attach_effect_describe_includes_granted_keyword():
    e = AttachToTargetCreatureYouControl(
        granted_keywords_ueot=frozenset({"first strike"})
    )
    desc = e.describe()
    assert "attach" in desc
    assert "first strike" in desc
    assert "until end of turn" in desc


def test_attach_effect_describe_without_granted_keyword_is_unchanged():
    e = AttachToTargetCreatureYouControl()
    assert e.describe() == "attach this Equipment to target creature you control"
