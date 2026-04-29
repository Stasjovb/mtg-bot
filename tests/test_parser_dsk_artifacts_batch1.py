"""Tests for the Duskmourn artifacts / Equipment batch-1 parser
additions.

Each commit in this batch lands one card via a small additive change:
a literal-line entry on an existing builder, a name-keyed dispatch
factory on an existing builder, or a small flag widening on an
existing engine class. New bespoke effect classes are introduced in
``effects.bespoke`` only when no existing primitive captures the
printed body.

Cards newly claimed in this batch:

* **Saw** ``{2}`` Artifact - Equipment - ``Equipped creature gets
  +2/+0`` + ``Whenever equipped creature attacks, you may sacrifice a
  permanent other than that creature or this Equipment. If you do,
  draw a card.`` + ``Equip {2}``. Claimed by extending the
  equipment_builder's literal-trigger-line table with the printed
  attack-trigger line, dispatched to the new
  ``SawAttacksOptionalSacDrawEffect`` engine class. The bespoke
  effect encodes the (sacrifice-other-permanent, draw) combinator
  with the strict "permanent other than equipped creature or this
  Equipment" exclusion. ``IsHost(subject="attacker")`` matches the
  ``Whenever equipped creature attacks`` trigger condition (same
  predicate Atomic Microsizer's bespoke factory uses).
"""

from __future__ import annotations

from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects.predicates import Event


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- Saw: equipped-attacks may-sac-permanent draw ----------

def test_saw_claimed_by_parser():
    # Saw ``{2}`` Artifact - Equipment - claimed via the new literal
    # trigger line in ``equipment_builder``. The bespoke effect class
    # encodes the (optional-sacrifice, draw) combinator with the
    # printed "permanent other than that creature or this Equipment"
    # exclusion.
    assert "Saw" in _claimed_names()


def test_saw_carries_attacks_trigger_with_bespoke_effect():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the equipped-attacks trigger via the bespoke
    # ``SawAttacksOptionalSacDrawEffect`` engine class. The trigger
    # event is ATTACKS gated by ``IsHost(subject="attacker")`` -
    # same shape Atomic Microsizer's bespoke factory wires its
    # equipped-attacks trigger.
    from mtg_bot.effects.bespoke import SawAttacksOptionalSacDrawEffect

    parser = OracleParserCardSource()
    p = parser.get_printings()["Saw"]
    attacks_triggers = [
        t for t in p.triggered_abilities
        if t.event == Event.ATTACKS
    ]
    assert len(attacks_triggers) == 1
    assert isinstance(
        attacks_triggers[0].effect, SawAttacksOptionalSacDrawEffect,
    )


def test_saw_carries_equipment_pump_and_equip_cost():
    # The remaining lines (``Equipped creature gets +2/+0.``,
    # ``Equip {2}``) ride the existing equipment_builder grammar - the
    # +2/+0 lands on ``equipment_bonuses`` and the equip cost lands
    # as an activated ability synthesized by ``make_equipment``.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Saw"]
    assert p.equipment_bonuses == (2, 0, frozenset())
    equip_costs = [
        a.cost.mana_str for a in p.activated_abilities
        if a.cost.mana_str
    ]
    assert "{2}" in equip_costs


# ---------- SawAttacksOptionalSacDrawEffect engine class ----------

def test_saw_effect_describe():
    # Belt-and-suspenders that the describe helper reflects the
    # combined behavior - "may sacrifice a permanent other than that
    # creature or this Equipment; if you do, draw a card."
    from mtg_bot.effects.bespoke import SawAttacksOptionalSacDrawEffect

    desc = SawAttacksOptionalSacDrawEffect().describe()
    assert "sacrifice" in desc
    assert "draw a card" in desc


def test_saw_effect_no_op_with_no_options():
    # When the controller controls only the Equipment and the
    # equipped creature, no permanent is a legal sacrifice target so
    # the effect is a silent no-op (no draw).
    from mtg_bot.cards.base import make_creature, make_equipment
    from mtg_bot.effects.bespoke import SawAttacksOptionalSacDrawEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    eq_pr = make_equipment(
        "Saw", "{2}",
        power_bonus=2, toughness_bonus=0,
        equip_cost="{2}",
    )
    eq_obj = GameObject(
        id=1, printing=eq_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    host = GameObject(
        id=2, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    eq_obj.attached_to = host.id
    p0 = Player(id=0)
    p1 = Player(id=1)
    state = GameState(
        players=[p0, p1],
        battlefield=[eq_obj, host],
        resolving_source=eq_obj,
    )
    # No third permanent → no sacrifice option → silent no-op.
    SawAttacksOptionalSacDrawEffect().resolve(
        state, controller_id=0, targets=()
    )
    assert len(p0.hand) == 0


def test_saw_effect_sacrifices_and_draws():
    # End-to-end resolve sanity: when a third permanent is available
    # the controller's agent can choose to sacrifice it for a card.
    from mtg_bot.cards.base import (
        make_artifact, make_creature, make_equipment,
    )
    from mtg_bot.effects.bespoke import SawAttacksOptionalSacDrawEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    class _AgentAlwaysYes:
        def choose_yes_no(self, state, pid, prompt):
            return True

        def choose_sacrifice(self, state, pid, legal_object_ids):
            return legal_object_ids[0]

    eq_pr = make_equipment(
        "Saw", "{2}",
        power_bonus=2, toughness_bonus=0,
        equip_cost="{2}",
    )
    eq_obj = GameObject(
        id=1, printing=eq_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    host = GameObject(
        id=2, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    eq_obj.attached_to = host.id
    art_pr = make_artifact("Token Art", "{1}")
    other = GameObject(
        id=3, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    # Add a card to the library so the draw lands on a real card.
    library_card = GameObject(
        id=10, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.LIBRARY,
    )
    p0 = Player(id=0, agent=_AgentAlwaysYes(), library=[library_card])
    p1 = Player(id=1)
    state = GameState(
        players=[p0, p1],
        battlefield=[eq_obj, host, other],
        resolving_source=eq_obj,
    )
    SawAttacksOptionalSacDrawEffect().resolve(
        state, controller_id=0, targets=()
    )
    # ``other`` was sacrificed, ``library_card`` was drawn.
    assert other not in state.battlefield
    assert other in p0.graveyard
    assert library_card in p0.hand


def test_saw_effect_decline_skips_sacrifice_and_draw():
    # When the controller's agent declines the optional sacrifice, no
    # permanent is sacrificed and no card is drawn.
    from mtg_bot.cards.base import (
        make_artifact, make_creature, make_equipment,
    )
    from mtg_bot.effects.bespoke import SawAttacksOptionalSacDrawEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    class _AgentDeclines:
        def choose_yes_no(self, state, pid, prompt):
            return False

        def choose_sacrifice(self, state, pid, legal_object_ids):
            # Should never be called when choose_yes_no returns False.
            raise AssertionError("choose_sacrifice should not be called")

    eq_pr = make_equipment(
        "Saw", "{2}",
        power_bonus=2, toughness_bonus=0,
        equip_cost="{2}",
    )
    eq_obj = GameObject(
        id=1, printing=eq_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    host = GameObject(
        id=2, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    eq_obj.attached_to = host.id
    art_pr = make_artifact("Token Art", "{1}")
    other = GameObject(
        id=3, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    library_card = GameObject(
        id=10, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.LIBRARY,
    )
    p0 = Player(id=0, agent=_AgentDeclines(), library=[library_card])
    p1 = Player(id=1)
    state = GameState(
        players=[p0, p1],
        battlefield=[eq_obj, host, other],
        resolving_source=eq_obj,
    )
    SawAttacksOptionalSacDrawEffect().resolve(
        state, controller_id=0, targets=()
    )
    assert other in state.battlefield
    assert library_card not in p0.hand


def test_saw_effect_no_op_without_resolving_source():
    # Defensive: if ``resolving_source`` is None (engine misuse), the
    # effect short-circuits to a silent no-op rather than raising.
    from mtg_bot.effects.bespoke import SawAttacksOptionalSacDrawEffect
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    SawAttacksOptionalSacDrawEffect().resolve(
        state, controller_id=0, targets=()
    )
    # No exception, nothing changed.
    assert len(state.battlefield) == 0


# ---------- Baseball Bat: equipped-attacks tap-up-to-one ----------

def test_baseball_bat_claimed_by_parser():
    # Baseball Bat ``{G}{W}`` Artifact - Equipment - claimed via the
    # new literal trigger line in ``equipment_builder``. The
    # ``Whenever equipped creature attacks, tap up to one target
    # creature.`` body maps to the new generic
    # ``TapUpToOneTargetCreature`` engine class.
    assert "Baseball Bat" in _claimed_names()


def test_baseball_bat_carries_attacks_trigger_with_tap_effect():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the equipped-attacks trigger via the new generic
    # ``TapUpToOneTargetCreature`` engine class. The trigger event is
    # ATTACKS gated by ``IsHost(subject="attacker")``.
    from mtg_bot.effects import TapUpToOneTargetCreature

    parser = OracleParserCardSource()
    p = parser.get_printings()["Baseball Bat"]
    attacks_triggers = [
        t for t in p.triggered_abilities
        if t.event == Event.ATTACKS
    ]
    assert len(attacks_triggers) == 1
    assert isinstance(
        attacks_triggers[0].effect, TapUpToOneTargetCreature,
    )


def test_baseball_bat_carries_etb_attach_and_pump():
    # The ETB ``When this Equipment enters, attach it to target
    # creature you control.`` line lands as an ENTERS trigger, the
    # ``Equipped creature gets +1/+1.`` lands on
    # ``equipment_bonuses``, and the ``Equip {3}`` lands as a
    # synthesized activated ability.
    from mtg_bot.effects import AttachToTargetCreatureYouControl

    parser = OracleParserCardSource()
    p = parser.get_printings()["Baseball Bat"]
    etb_triggers = [
        t for t in p.triggered_abilities
        if t.event == Event.ENTERS
    ]
    assert len(etb_triggers) == 1
    assert isinstance(
        etb_triggers[0].effect, AttachToTargetCreatureYouControl,
    )
    assert p.equipment_bonuses == (1, 1, frozenset())
    equip_costs = [
        a.cost.mana_str for a in p.activated_abilities
        if a.cost.mana_str
    ]
    assert "{3}" in equip_costs


# ---------- TapUpToOneTargetCreature engine class ----------

def test_tap_up_to_one_target_creature_target_range():
    # Up-to-one means 0 or 1 target, distinguishing this from sibling
    # ``TapAnotherTargetCreature`` (strict 1) and
    # ``TapTargetArtifactOrCreature`` (strict 1).
    from mtg_bot.effects import TapUpToOneTargetCreature

    eff = TapUpToOneTargetCreature()
    assert eff.requires_target() is True
    assert eff.target_count_range() == (0, 1)


def test_tap_up_to_one_target_creature_legal_targets_includes_all_creatures():
    # The legal-target pool is ALL creatures on the battlefield
    # (controller-agnostic and source-agnostic) - the printed surface
    # form has no controller restriction.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import TapUpToOneTargetCreature
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    yours = GameObject(
        id=1, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    theirs = GameObject(
        id=2, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[yours, theirs],
    )
    legal = TapUpToOneTargetCreature().legal_targets(state, controller_id=0)
    assert ("creature", 1) in legal
    assert ("creature", 2) in legal


def test_tap_up_to_one_target_creature_taps_chosen():
    # End-to-end resolve: with one target, the chosen creature is
    # tapped via ``turn.tap_permanent``.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import TapUpToOneTargetCreature
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    target = GameObject(
        id=2, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    assert target.tapped is False
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[target],
    )
    TapUpToOneTargetCreature().resolve(
        state, controller_id=0, targets=(("creature", 2),)
    )
    assert target.tapped is True


def test_tap_up_to_one_target_creature_no_targets_is_noop():
    # 0-target resolution is a silent no-op (the controller chose not
    # to target any creature).
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import TapUpToOneTargetCreature
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    target = GameObject(
        id=2, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[target],
    )
    TapUpToOneTargetCreature().resolve(
        state, controller_id=0, targets=()
    )
    assert target.tapped is False


def test_tap_up_to_one_target_creature_describe():
    from mtg_bot.effects import TapUpToOneTargetCreature

    assert TapUpToOneTargetCreature().describe() == (
        "tap up to one target creature"
    )


def test_tap_up_to_one_target_creature_invalid_target_is_noop():
    # Defensive: if the target is non-creature (engine misuse) or no
    # battlefield object matches the id, the effect is a silent no-op
    # rather than raising.
    from mtg_bot.effects import TapUpToOneTargetCreature
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    # Wrong kind.
    TapUpToOneTargetCreature().resolve(
        state, controller_id=0, targets=(("permanent", 999),),
    )
    # Missing object.
    TapUpToOneTargetCreature().resolve(
        state, controller_id=0, targets=(("creature", 999),),
    )
