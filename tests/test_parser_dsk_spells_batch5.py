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


# ---------- ExorciseEffect engine class ----------

def test_exorcise_effect_exists():
    # New bespoke engine class wired in ``mtg_bot.effects.bespoke``
    # and exposed via ``mtg_bot.effects``.
    from mtg_bot.effects import ExorciseEffect

    eff = ExorciseEffect()
    assert eff.requires_target() is True


def test_exorcise_describe():
    from mtg_bot.effects import ExorciseEffect

    desc = ExorciseEffect().describe()
    assert "exile" in desc
    assert "artifact" in desc
    assert "enchantment" in desc
    assert "power 4" in desc


def test_exorcise_legal_targets_include_artifact():
    # Artifacts are unconditionally legal regardless of P/T.
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import ExorciseEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    art_pr = make_artifact("Plain Artifact", "{2}")
    art = GameObject(
        id=1, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[art],
    )
    legal = ExorciseEffect().legal_targets(state, 0)
    ids = {t[1] for t in legal}
    assert art.id in ids


def test_exorcise_legal_targets_include_enchantment():
    # Pure enchantments are unconditionally legal regardless of P/T.
    from mtg_bot.cards.base import make_enchantment
    from mtg_bot.effects import ExorciseEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    ench_pr = make_enchantment("Plain Enchantment", "{1}{W}")
    ench = GameObject(
        id=1, printing=ench_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[ench],
    )
    legal = ExorciseEffect().legal_targets(state, 0)
    ids = {t[1] for t in legal}
    assert ench.id in ids


def test_exorcise_legal_targets_include_4_power_creature():
    # Creatures with power >= 4 are legal; power < 4 creatures aren't.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import ExorciseEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    big_pr = make_creature("Big Bear", "{3}{G}", power=4, toughness=4)
    big = GameObject(
        id=1, printing=big_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    small_pr = make_creature(
        "Small Bear", "{1}{G}", power=2, toughness=2
    )
    small = GameObject(
        id=2, printing=small_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[big, small],
    )
    legal = ExorciseEffect().legal_targets(state, 0)
    ids = {t[1] for t in legal}
    assert big.id in ids
    assert small.id not in ids


def test_exorcise_resolves_exile():
    # End-to-end: resolving against a legal artifact target moves
    # it from battlefield to exile.
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import ExorciseEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    art_pr = make_artifact("Plain Artifact", "{2}")
    art = GameObject(
        id=1, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[art],
    )
    ExorciseEffect().resolve(
        state, controller_id=0, targets=(("permanent", art.id),)
    )
    assert art not in state.battlefield


def test_exorcise_no_target_noop():
    # Defensive: empty targets resolve without raising.
    from mtg_bot.effects import ExorciseEffect
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    ExorciseEffect().resolve(state, controller_id=0, targets=())


def test_exorcise_wrong_kind_noop():
    # Defensive: non-permanent target kind resolves without raising.
    from mtg_bot.effects import ExorciseEffect
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    ExorciseEffect().resolve(
        state, controller_id=0, targets=(("creature", 999),)
    )


def test_exorcise_missing_target_noop():
    # Defensive: a target id that doesn't exist resolves without
    # raising.
    from mtg_bot.effects import ExorciseEffect
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    ExorciseEffect().resolve(
        state, controller_id=0, targets=(("permanent", 999),)
    )


def test_exorcise_recheck_at_resolve_for_debuffed_creature():
    # If a 4-power creature gets debuffed below 4 between cast and
    # resolve, the resolve recheck fizzles the exile rather than
    # silently exiling a no-longer-legal target.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import ExorciseEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    big_pr = make_creature("Big Bear", "{3}{G}", power=4, toughness=4)
    big = GameObject(
        id=1, printing=big_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
        # Simulate a debuff dropping effective_power below 4 mid-stack.
        temp_power_bonus=-2,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[big],
    )
    ExorciseEffect().resolve(
        state, controller_id=0, targets=(("permanent", big.id),)
    )
    # Target stays on battlefield — recheck failed.
    assert big in state.battlefield


# ---------- Exorcise parser claim ----------

def test_exorcise_claimed_by_parser():
    # Exorcise ``{1}{W}`` Sorcery — claimed via the new whole-spell
    # exact-text dispatch entry mapping to the new
    # ``ExorciseEffect`` engine class.
    assert "Exorcise" in _claimed_names()


def test_exorcise_engine_class():
    from mtg_bot.effects import ExorciseEffect

    parser = OracleParserCardSource()
    p = parser.get_printings()["Exorcise"]
    assert p.spell_effect == ExorciseEffect()


def test_exorcise_is_sorcery():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Exorcise"]
    assert "Sorcery" in p.card_types
