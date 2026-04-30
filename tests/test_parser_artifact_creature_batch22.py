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

Remaining bespoke cards (still in ``_BESPOKE_ARTIFACT_CREATURES``):
  1. Emissary Escort — dynamic P/T formula (emissary_escort)
  2. Interceptor Mechan — flying + ETB return + void end-step counter
  3. Kavaron Harrier — attack trigger (KavaronHarrierAttackEffect);
     "that's tapped and attacking" token + end-of-combat delayed sac
  4. Mechan Shieldmate — defender + ControlledArtifactEnteredThisTurn ContinuousModifier
  5. Monoist Circuit-Feeder — dual-target +X/-X ETB (MonoistCircuitFeederETBEffect)
  6. Roving Actuator — void ETB exile-from-graveyard+copy+free-cast (RovingActuatorETBEffect)
  7. Survey Mechan — flying only (simplified; large activated body dropped)
  8. Splitskin Doll — draw + source-relative conditional discard (DSK)
  9. Attack-in-the-Box — optional pump + delayed end-step sac (DSK)
 10. Osseous Sticktwister — Delirium end-step per-opponent choice (DSK)
 11. Wickerfolk Thresher — Delirium attack peek-top-then-branch (DSK)
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


