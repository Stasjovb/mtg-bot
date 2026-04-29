"""Tests for the Duskmourn spells / enchantments batch-5 parser additions.

Each commit in this batch lands one or more cards via a small additive
change to the parser's whole-spell exact-text dispatch table or via a
new bespoke engine class. No existing engine classes are modified
beyond additive flag widenings; the parser's job here is to claim
spells whose printed shapes don't fit the per-clause grammar but DO
admit a clean simplification onto an existing primitive (parser-is-
right precedent: Unravel / Divert Disaster) or a one-off bespoke
engine class (Plasma Bolt / Cut Propulsion precedent).

Cards claimed in this batch:

* **Scorching Dragonfire** ``{1}{R}`` Instant — 3 damage to target
  creature/planeswalker plus a "die-this-turn-exile-instead" rider.
  Whole-spell dispatch simplifies to bare
  ``DealDamageToTargetCreature(amount=3)``; the planeswalker target
  scope and the die-replacement rider are dropped per the parser-is-
  right precedent set by Unravel / Divert Disaster (drop unmodelable
  rider, keep the base mechanic).

* **Unwanted Remake** ``{W}`` Instant — Destroy target creature plus
  a "Its controller manifests dread" rider. Whole-spell dispatch
  simplifies to bare ``DestroyTargetCreature()``; the controller-
  side manifest-dread rider is dropped because the engine's
  ``ManifestDread`` primitive resolves at the resolving controller
  (the spell's caster), not at the destroyed permanent's controller.

* **Jump Scare** ``{W}`` Instant — Pump target creature +2/+2 with
  flying plus a "becomes a Horror enchantment creature in addition
  to its other types" type-change rider. Whole-spell dispatch
  simplifies to bare
  ``PumpTargetCreatureUntilEOT(power=2, toughness=2,
  granted_keywords={"flying"})``; the UEOT type-change rider is
  dropped because the engine doesn't model type-line additions on
  targeted creatures.
"""

from __future__ import annotations

from mtg_bot.cards.parser.source import OracleParserCardSource


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- Scorching Dragonfire ----------

def test_scorching_dragonfire_claimed_by_parser():
    # Scorching Dragonfire ``{1}{R}`` Instant — claimed via the new
    # whole-spell exact-text dispatch entry that simplifies the
    # printed text (3 damage to creature/planeswalker + die-this-
    # turn-exile rider) to bare ``DealDamageToTargetCreature(amount=3)``.
    assert "Scorching Dragonfire" in _claimed_names()


def test_scorching_dragonfire_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified ``DealDamageToTargetCreature(amount=3)`` engine
    # class — base mechanic preserved, planeswalker target widening
    # and die-replacement rider dropped (parser-is-right precedent).
    from mtg_bot.cards.base import DealDamageToTargetCreature

    parser = OracleParserCardSource()
    p = parser.get_printings()["Scorching Dragonfire"]
    assert p.spell_effect == DealDamageToTargetCreature(amount=3)


def test_scorching_dragonfire_is_instant():
    # Type-line carries Instant — not Sorcery — so the spell can be
    # cast in response to an opponent's combat / spell.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Scorching Dragonfire"]
    assert "Instant" in p.card_types


# ---------- Unwanted Remake ----------

def test_unwanted_remake_claimed_by_parser():
    # Unwanted Remake ``{W}`` Instant — claimed via the new
    # whole-spell exact-text dispatch entry that simplifies the
    # printed text (destroy target creature + opp-controller-
    # manifests-dread rider) to bare ``DestroyTargetCreature()``.
    # Reminder text inside the trailing parenthetical is stripped
    # before dispatch.
    assert "Unwanted Remake" in _claimed_names()


def test_unwanted_remake_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified ``DestroyTargetCreature()`` engine class — base
    # mechanic preserved, opp-side manifest-dread rider dropped
    # (parser-is-right precedent).
    from mtg_bot.cards.base import DestroyTargetCreature

    parser = OracleParserCardSource()
    p = parser.get_printings()["Unwanted Remake"]
    assert p.spell_effect == DestroyTargetCreature()


def test_unwanted_remake_is_instant():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Unwanted Remake"]
    assert "Instant" in p.card_types


# ---------- Jump Scare ----------

def test_jump_scare_claimed_by_parser():
    # Jump Scare ``{W}`` Instant — claimed via the new whole-spell
    # exact-text dispatch entry that simplifies the printed text
    # (+2/+2 with flying + becomes-Horror-enchantment-creature
    # type-change rider) to bare ``PumpTargetCreatureUntilEOT(power=
    # 2, toughness=2, granted_keywords={"flying"})``. Type-change
    # rider dropped per parser-is-right precedent.
    assert "Jump Scare" in _claimed_names()


def test_jump_scare_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified pump engine class — power/toughness bonus and
    # flying granted-keyword preserved, type-change rider dropped.
    from mtg_bot.cards.base import PumpTargetCreatureUntilEOT

    parser = OracleParserCardSource()
    p = parser.get_printings()["Jump Scare"]
    assert p.spell_effect == PumpTargetCreatureUntilEOT(
        power_bonus=2,
        toughness_bonus=2,
        granted_keywords=frozenset({"flying"}),
    )


def test_jump_scare_is_instant():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Jump Scare"]
    assert "Instant" in p.card_types


# ---------- VengefulPossessionEffect engine class ----------

def test_vengeful_possession_effect_exists():
    # New bespoke engine class wired in ``mtg_bot.effects.bespoke``
    # next to ``SystemsOverrideEffect``. Imports cleanly and is
    # exposed via ``mtg_bot.effects``.
    from mtg_bot.effects import VengefulPossessionEffect

    eff = VengefulPossessionEffect()
    assert eff.requires_target() is True


def test_vengeful_possession_describe():
    from mtg_bot.effects import VengefulPossessionEffect

    desc = VengefulPossessionEffect().describe()
    assert "gain control" in desc
    assert "untap" in desc
    assert "haste" in desc


def test_vengeful_possession_legal_targets_creatures_only():
    # Vengeful Possession's legal-target pool is creatures only —
    # narrowed from Systems Override's "artifact or creature" scope.
    # Belt-and-suspenders: a non-creature artifact on the battlefield
    # is NOT a legal target for Vengeful Possession (whereas it would
    # be for Systems Override).
    from mtg_bot.cards.base import make_artifact, make_creature
    from mtg_bot.effects import VengefulPossessionEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    bear = GameObject(
        id=1, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    art_pr = make_artifact("Plain Artifact", "{2}")
    art = GameObject(
        id=2, printing=art_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[bear, art],
    )
    legal = VengefulPossessionEffect().legal_targets(state, 0)
    ids = {t[1] for t in legal}
    assert bear.id in ids
    assert art.id not in ids


def test_vengeful_possession_resolves_gain_control_untap_haste():
    # End-to-end resolve sanity: target opponent's tapped creature
    # gets controlled by us, untaps, and gains haste UEOT.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import VengefulPossessionEffect
    from mtg_bot.game import (
        GameObject, GameState, Player, Zone, effective_keywords,
    )

    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    bear = GameObject(
        id=1, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD, tapped=True,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[bear],
    )
    VengefulPossessionEffect().resolve(
        state, controller_id=0, targets=(("creature", bear.id),)
    )
    assert bear.controller_id == 0
    assert bear.tapped is False
    assert "haste" in effective_keywords(state, bear)


def test_vengeful_possession_no_target_noop():
    # Defensive: empty targets tuple resolves without raising.
    from mtg_bot.effects import VengefulPossessionEffect
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    VengefulPossessionEffect().resolve(
        state, controller_id=0, targets=()
    )


def test_vengeful_possession_wrong_kind_noop():
    # Defensive: a non-creature target kind (e.g. ``permanent`` from
    # a Systems-Override-style invocation) resolves without raising
    # — Vengeful Possession only honors ``creature`` targets.
    from mtg_bot.effects import VengefulPossessionEffect
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    VengefulPossessionEffect().resolve(
        state, controller_id=0, targets=(("permanent", 999),)
    )


def test_vengeful_possession_missing_target_noop():
    # Defensive: a target id that doesn't exist on the battlefield
    # (the chosen creature was bounced/destroyed before resolution)
    # resolves without raising.
    from mtg_bot.effects import VengefulPossessionEffect
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    VengefulPossessionEffect().resolve(
        state, controller_id=0, targets=(("creature", 999),)
    )


# ---------- Vengeful Possession parser claim ----------

def test_vengeful_possession_claimed_by_parser():
    # Vengeful Possession ``{2}{R}`` Sorcery — claimed via the new
    # whole-spell exact-text dispatch entry mapping to the new
    # ``VengefulPossessionEffect`` engine class.
    assert "Vengeful Possession" in _claimed_names()


def test_vengeful_possession_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the ``VengefulPossessionEffect`` engine class.
    from mtg_bot.effects import VengefulPossessionEffect

    parser = OracleParserCardSource()
    p = parser.get_printings()["Vengeful Possession"]
    assert p.spell_effect == VengefulPossessionEffect()


def test_vengeful_possession_is_sorcery():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Vengeful Possession"]
    assert "Sorcery" in p.card_types
