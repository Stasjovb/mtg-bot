"""Parity tests for artifact-creature-batch22 bespoke dispatch additions.

Each test asserts that the oracle parser produces a ``CardPrinting``
for one of the 13 non-legendary Artifact Creatures originally in the
bespoke table.

Migrated OUT of ``_BESPOKE_ARTIFACT_CREATURES`` (claimed by grammar):
  - Pinnacle Emissary — warp cost ``{U/R}`` (hybrid mana support).
  - Tapestry Warden — vigilance + toughness-as-damage + toughness-as-station.
  - Virulent Silencer — predicate-dispatch poison trigger.
  - Gene Pollinator — ``{T}, Tap an untapped permanent you control`` cost
    atoms both classified; mana-ability grammar claims the effect.
    Migrated in bespoke-creature-wave7.
  - Rust Harvester — three-atom cost + ``, then it deals damage equal to
    its power to any target`` compound now parses after adding ``(?:it )?``
    to ``_DEAL_DAMAGE_EQUAL_TO_SOURCE_POWER_ANY_TARGET``.
    Migrated in bespoke-creature-wave7.
  - Selfcraft Mechan — new ``_OPTIONAL_SAC_ARTIFACT_WHEN_YOU_DO_EFFECT``
    recognizer in ``effects.py`` matches "you may sacrifice an artifact.
    When you do, <inner>" → ``OptionalSacArtifactForEffect(inner)``;
    ``OptionalSacArtifactForEffect`` updated to forward ``requires_target``
    / ``legal_targets`` / ``targets`` from the inner effect.
    Migrated in bespoke-artifact-misc.
  - Attack-in-the-Box — literal trigger-line dispatch in
    ``_BESPOKE_TRIGGER_LINES`` routes the attack trigger to
    ``AttackInTheBoxAttackEffect``; all other oracle lines parse via the
    unified grammar. Migrated in bespoke-delirium.
  - Osseous Sticktwister — literal trigger-line dispatch in
    ``_BESPOKE_TRIGGER_LINES`` routes the Delirium end-step trigger to
    ``OsseousSticktwisterEndStepEffect``; ``Lifelink`` keyword parses
    via the standard keyword line. Migrated in bespoke-delirium.
  - Wickerfolk Thresher — literal trigger-line dispatch in
    ``_BESPOKE_TRIGGER_LINES`` routes the Delirium attack trigger to
    ``WickerfolkThresherAttackEffect``; all other oracle lines parse
    via the unified grammar. Migrated in bespoke-delirium.

Migrated to grammar in engine-kavaron-elevator:
  - Kavaron Harrier — ``_CREATE_CREATURE_TOKEN`` extended with
    ``(?: that's tapped and attacking)?`` qualifier; literal multi-
    sentence recognizer in ``_parse_effect`` for the two-sentence
    "create ... that's tapped and attacking. Sacrifice that token at
    end of combat." phrase → ``CreateToken(attacking=True,
    schedule_end_of_combat_sacrifice=True)``. ``CreateToken`` gains
    ``attacking`` and ``schedule_end_of_combat_sacrifice`` fields that
    wire the engine behavior faithfully (tapped+attacking entry, pending
    end-of-combat sac schedule). The trigger fires via the unified
    ``_YOU_MAY_PAY_THEN_EFFECT`` grammar.

Remaining bespoke cards (still in ``_BESPOKE_ARTIFACT_CREATURES``):
  1. Emissary Escort — dynamic P/T formula (emissary_escort)
  2. Interceptor Mechan — flying + ETB return + void end-step counter
  3. Mechan Shieldmate — defender + ControlledArtifactEnteredThisTurn ContinuousModifier
  4. Monoist Circuit-Feeder — dual-target +X/-X ETB (MonoistCircuitFeederETBEffect)
  5. Roving Actuator — void ETB exile-from-graveyard+copy+free-cast (RovingActuatorETBEffect)
  6. Survey Mechan — flying + hexproof (large activated body dropped; X cost-reduction not modeled)
  7. Splitskin Doll — draw + source-relative conditional discard (DSK)
"""

from __future__ import annotations

from mtg_bot.cards.parser.source import OracleParserCardSource

_PARSER = OracleParserCardSource()
_PARSER_PRINTINGS = _PARSER.get_printings()


def _parser(name: str):
    return _PARSER_PRINTINGS[name]




def test_emissary_escort_claimed_by_parser():
    assert "Emissary Escort" in _PARSER_PRINTINGS




def test_gene_pollinator_claimed_by_parser():
    assert "Gene Pollinator" in _PARSER_PRINTINGS


def test_gene_pollinator_grammar_structure():
    """Grammar-claimed Gene Pollinator has the mana ability with the
    correct two-atom cost and oracle-faithful subtypes (Robot, Insect)."""
    gp = _parser("Gene Pollinator")
    assert gp.is_artifact
    assert len(gp.activated_abilities) == 1
    ab = gp.activated_abilities[0]
    assert ab.cost.tap_self is True
    assert ab.cost.tap_permanent_you_control is True
    assert ab.is_mana_ability is True
    # Oracle-faithful subtypes — bespoke entry incorrectly dropped these
    assert "Robot" in gp.subtypes
    assert "Insect" in gp.subtypes




def test_interceptor_mechan_claimed_by_parser():
    assert "Interceptor Mechan" in _PARSER_PRINTINGS




def test_kavaron_harrier_claimed_by_parser():
    assert "Kavaron Harrier" in _PARSER_PRINTINGS


def test_kavaron_harrier_grammar_structure():
    """Grammar-claimed Kavaron Harrier has the attack trigger wired via
    OptionalManaCostThenEffect → CreateToken(attacking=True,
    schedule_end_of_combat_sacrifice=True).

    Migration from bespoke ``KavaronHarrierAttackEffect`` to the unified
    grammar: the trigger body "you may pay {2}. If you do, create a 2/2
    colorless Robot artifact creature token that's tapped and attacking.
    Sacrifice that token at end of combat." parses via the
    ``_YOU_MAY_PAY_THEN_EFFECT`` recognizer + literal multi-sentence inner
    recognizer → ``OptionalManaCostThenEffect("{2}", CreateToken(...))``.
    """
    from mtg_bot.effects.combinators import OptionalManaCostThenEffect
    from mtg_bot.effects.generic import CreateToken
    from mtg_bot.effects.predicates import Event

    kh = _parser("Kavaron Harrier")
    assert kh.is_artifact
    assert kh.power == 2
    assert kh.toughness == 1
    # Exactly one triggered ability: the attacks trigger.
    assert len(kh.triggered_abilities) == 1
    ta = kh.triggered_abilities[0]
    assert ta.event == Event.ATTACKS
    # Effect is the OptionalManaCostThenEffect wrapper.
    assert isinstance(ta.effect, OptionalManaCostThenEffect)
    assert ta.effect.cost_str == "{2}"
    inner = ta.effect.inner_effect
    assert isinstance(inner, CreateToken)
    assert inner.tapped is True
    assert inner.attacking is True
    assert inner.schedule_end_of_combat_sacrifice is True
    assert inner.token_printing.name == "Robot"




def test_mechan_shieldmate_claimed_by_parser():
    assert "Mechan Shieldmate" in _PARSER_PRINTINGS




def test_monoist_circuit_feeder_claimed_by_parser():
    assert "Monoist Circuit-Feeder" in _PARSER_PRINTINGS




def test_pinnacle_emissary_claimed_by_parser():
    assert "Pinnacle Emissary" in _PARSER_PRINTINGS




def test_roving_actuator_claimed_by_parser():
    assert "Roving Actuator" in _PARSER_PRINTINGS




def test_rust_harvester_claimed_by_parser():
    assert "Rust Harvester" in _PARSER_PRINTINGS


def test_rust_harvester_grammar_structure():
    """Grammar-claimed Rust Harvester has menace + full activated ability
    (three-atom cost, Sequence effect) and oracle-faithful artifact type."""
    rh = _parser("Rust Harvester")
    assert rh.is_artifact
    assert "menace" in rh.keywords
    assert "Robot" in rh.subtypes
    assert len(rh.activated_abilities) == 1
    ab = rh.activated_abilities[0]
    assert ab.cost.mana_str == "{2}"
    assert ab.cost.tap_self is True
    assert ab.cost.exile_artifact_from_graveyard is True
    from mtg_bot.cards.base import Sequence, PutPlusOneCounterOnSelf, DealDamageEqualToSourcePowerAnyTarget
    assert isinstance(ab.effect, Sequence)
    assert len(ab.effect.effects) == 2
    assert isinstance(ab.effect.effects[0], PutPlusOneCounterOnSelf)
    assert isinstance(ab.effect.effects[1], DealDamageEqualToSourcePowerAnyTarget)




def test_selfcraft_mechan_claimed_by_parser():
    assert "Selfcraft Mechan" in _PARSER_PRINTINGS


def test_selfcraft_mechan_grammar_structure():
    """Grammar-claimed Selfcraft Mechan carries an ETB trigger whose
    effect is ``OptionalSacArtifactForEffect`` wrapping a ``Sequence``
    of ``PutPlusOneCounterOnTargetCreature`` and ``DrawCards`` — the
    oracle-faithful shape for "you may sacrifice an artifact. When you
    do, put a +1/+1 counter on target creature and draw a card."
    """
    from mtg_bot.effects.combinators import OptionalSacArtifactForEffect, Sequence
    from mtg_bot.effects.predicates import Event

    sm = _parser("Selfcraft Mechan")
    assert sm.is_artifact
    etb = [t for t in sm.triggered_abilities if t.event == Event.ENTERS]
    assert len(etb) == 1
    eff = etb[0].effect
    assert isinstance(eff, OptionalSacArtifactForEffect)
    assert isinstance(eff.inner_effect, Sequence)
    assert eff.requires_target()




def test_survey_mechan_claimed_by_parser():
    assert "Survey Mechan" in _PARSER_PRINTINGS




def test_tapestry_warden_claimed_by_parser():
    assert "Tapestry Warden" in _PARSER_PRINTINGS




def test_virulent_silencer_claimed_by_parser():
    assert "Virulent Silencer" in _PARSER_PRINTINGS


