"""Tests for the parser ETB-non-token-effect cluster.

Each new effect-grammar entry covers a creature whose only triggered
ability is a ``"When this creature enters, …"`` line whose effect was
previously not in the unified ``_parse_effect`` dispatcher. The cluster:

* ``deals N damage to target creature an opponent controls`` →
  ``DealDamageToOpponentCreature(amount=N)``. Surfaces on Nova
  Hellkite's ETB.
* ``put a +1/+1 counter on target creature you control`` →
  ``PutPlusOneCounterOnCreatureYouControl(amount=1)``. Restricted-
  controller variant of the bare ``put a +1/+1 counter on target
  creature`` primitive. Surfaces on Rayblade Trooper.
* ``target creature an opponent controls gets ±N/±M until end of
  turn`` → ``PumpTargetCreatureUntilEOT(opponents_only=True)``.
  Sinister Cryologist's ETB debuff.
* ``creatures your opponents control get ±N/±M until end of turn`` /
  ``... until your next turn`` →
  ``PumpCreaturesOpponentsControlUntilEOT(power_bonus=N,
  toughness_bonus=M, until_caster_next_turn=...)``. Mass debuff/pump on
  every creature an opponent controls; the ``until your next turn``
  tail flips ``until_caster_next_turn=True`` (Mouth of the Storm).
* ``look at the top two cards of your library. Put one into your hand
  and the other into your graveyard`` →
  ``LookAtTopTwoSplitHandGraveyard()``. Codecracker Hound's ETB; the
  embedded period sits inside the effect phrase rather than terminating
  it (compound splitting doesn't apply because the second sentence
  isn't a standalone effect).
* ``return up to one other target permanent you control to its
  owner's hand`` → ``ReturnTargetPermanentYouControlToOwnersHand(
  optional=True, exclude_self=True)``. Exosuit Savior's ETB.

Each primitive is exercised via ``_parse_effect`` (normalized) and via
``_parse_effect_phrase`` (creature-trigger surface form) where the
``it`` source-subject pronoun applies. Negative cases pin the regex
boundaries — the bare-target / non-restricted variants must still
produce the unrestricted engine class so the new restricted variants
don't accidentally claim the bare surface.

Card-claim tests confirm the parser end-to-end-claims the EoE creatures
unlocked by this batch: Sinister Cryologist, Mouth of the Storm,
Codecracker Hound, Exosuit Savior, Rayblade Trooper.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    DealDamageToOpponentCreature,
    DealDamageToTargetCreature,
    LookAtTopTwoSplitHandGraveyard,
    PumpCreaturesOpponentsControlUntilEOT,
    PumpTargetCreatureUntilEOT,
    PutPlusOneCounterOnCreatureYouControl,
    PutPlusOneCounterOnTargetCreature,
    ReturnTargetPermanentYouControlToOwnersHand,
)
from mtg_bot.cards.parser.effects import (
    _parse_effect,
    _parse_effect_phrase,
)
from mtg_bot.cards.parser.source import OracleParserCardSource


# ---------- deals N damage to target creature an opponent controls ----------

def test_parse_effect_recognizes_damage_target_opponent_creature():
    # Nova Hellkite's ETB — 1 damage to a target creature an opponent
    # controls. Maps to the engine class with the captured int.
    assert _parse_effect(
        "deals 1 damage to target creature an opponent controls"
    ) == DealDamageToOpponentCreature(amount=1)


def test_parse_effect_recognizes_damage_target_opponent_creature_larger():
    # Forward-symmetric larger-amount form. The regex captures any
    # digit, so a future card with the same surface but higher
    # amount parses without further grammar work.
    assert _parse_effect(
        "deals 5 damage to target creature an opponent controls"
    ) == DealDamageToOpponentCreature(amount=5)


def test_parse_effect_phrase_recognizes_damage_target_opponent_creature():
    # Creature-trigger surface form — the ``it`` source-subject prefix
    # is stripped by ``_normalize_creature_effect_phrase`` before the
    # regex match.
    assert _parse_effect_phrase(
        "it deals 1 damage to target creature an opponent controls"
    ) == DealDamageToOpponentCreature(amount=1)


def test_parse_effect_does_not_collide_with_bare_target_creature_damage():
    # The bare ``deals N damage to target creature`` regex (which
    # produces ``DealDamageToTargetCreature``) shouldn't accidentally
    # fire on the opponent-controlled variant. The bare regex's ``$``
    # anchor means it only matches phrases that END at ``creature``
    # with no qualifier; the opponent-only form has more text after
    # ``creature``, so the two surface shapes are disjoint.
    bare = _parse_effect("deals 1 damage to target creature")
    opp = _parse_effect("deals 1 damage to target creature an opponent controls")
    assert isinstance(bare, DealDamageToTargetCreature)
    assert isinstance(opp, DealDamageToOpponentCreature)


# ---------- put a +1/+1 counter on target creature you control ----------

def test_parse_effect_recognizes_counter_on_target_creature_you_control():
    # Rayblade Trooper's ETB. Maps to the restricted engine class
    # whose ``legal_targets`` filters to creatures the resolving
    # controller controls.
    assert _parse_effect(
        "put a +1/+1 counter on target creature you control"
    ) == PutPlusOneCounterOnCreatureYouControl(amount=1)


def test_parse_effect_phrase_recognizes_counter_on_target_creature_you_control():
    # Creature-trigger surface form — no source-subject pronoun on
    # this phrase (the verb ``put`` starts the clause), so the
    # phrase passes through to ``_parse_effect`` unchanged.
    assert _parse_effect_phrase(
        "put a +1/+1 counter on target creature you control"
    ) == PutPlusOneCounterOnCreatureYouControl(amount=1)


def test_parse_effect_does_not_collide_with_bare_counter_on_target_creature():
    # The bare ``put a +1/+1 counter on target creature`` regex
    # (which produces ``PutPlusOneCounterOnTargetCreature``)
    # shouldn't accidentally fire on the ``you control`` variant.
    # The bare regex's ``$`` anchor means it only matches phrases
    # that END at ``creature`` with no qualifier; the restricted form
    # has ``you control`` after ``creature``, so the two surface
    # shapes are disjoint and produce different engine classes.
    bare = _parse_effect("put a +1/+1 counter on target creature")
    restricted = _parse_effect(
        "put a +1/+1 counter on target creature you control"
    )
    assert isinstance(bare, PutPlusOneCounterOnTargetCreature)
    assert isinstance(restricted, PutPlusOneCounterOnCreatureYouControl)


# ---------- target creature an opponent controls gets ±N/±M UEOT ----------

def test_parse_effect_recognizes_pump_target_opponent_creature_debuff():
    # Sinister Cryologist's ETB — -3/-0 debuff on a target creature an
    # opponent controls. ``opponents_only=True`` flag flips so the
    # engine's ``legal_targets`` filter excludes creatures the
    # resolving controller controls.
    assert _parse_effect(
        "target creature an opponent controls gets -3/-0 until end of turn"
    ) == PumpTargetCreatureUntilEOT(
        power_bonus=-3, toughness_bonus=0, opponents_only=True,
    )


def test_parse_effect_recognizes_pump_target_opponent_creature_positive():
    # Forward-symmetric positive form. No EoE card prints a positive
    # opponent-only pump today, but the regex accepts both signs so a
    # future card lands without further grammar work — symmetric with
    # the bare-pump regex's both-signs convention.
    assert _parse_effect(
        "target creature an opponent controls gets +1/+1 until end of turn"
    ) == PumpTargetCreatureUntilEOT(
        power_bonus=1, toughness_bonus=1, opponents_only=True,
    )


def test_parse_effect_does_not_collide_with_bare_pump_target_creature():
    # The bare ``target creature gets ±N/±M until end of turn`` regex
    # (which produces ``PumpTargetCreatureUntilEOT(opponents_only=
    # False)``) shouldn't fire on the opponent-only variant. The
    # surfaces are disjoint because the bare regex anchors on
    # ``target creature gets``, with no opponent-controls qualifier
    # in between.
    bare = _parse_effect(
        "target creature gets -3/-0 until end of turn"
    )
    opp = _parse_effect(
        "target creature an opponent controls gets -3/-0 until end of turn"
    )
    assert isinstance(bare, PumpTargetCreatureUntilEOT)
    assert isinstance(opp, PumpTargetCreatureUntilEOT)
    assert bare.opponents_only is False
    assert opp.opponents_only is True


# ---------- creatures your opponents control get ±N/±M UEOT ----------

def test_parse_effect_recognizes_mass_pump_opponents_until_eot():
    # Forward-looking ``until end of turn`` tail. No EoE card prints
    # this exact shape today (Mouth of the Storm uses the longer
    # ``until your next turn`` tail), but the regex accepts both
    # tails so a future printing parses without further grammar
    # work. The shorter tail flips ``until_caster_next_turn=False``
    # which clears the bonus at the casting turn's cleanup.
    assert _parse_effect(
        "creatures your opponents control get -2/-0 until end of turn"
    ) == PumpCreaturesOpponentsControlUntilEOT(
        power_bonus=-2, toughness_bonus=0, until_caster_next_turn=False,
    )


def test_parse_effect_recognizes_mass_pump_opponents_until_your_next_turn():
    # Mouth of the Storm's ETB — -3/-0 debuff on every creature an
    # opponent controls, surviving past the casting turn's cleanup.
    # The longer tail flips ``until_caster_next_turn=True`` which
    # routes the bonus through the engine's extended-temp pump path
    # (clears at the start of the resolving controller's NEXT turn).
    assert _parse_effect(
        "creatures your opponents control get -3/-0 until your next turn"
    ) == PumpCreaturesOpponentsControlUntilEOT(
        power_bonus=-3, toughness_bonus=0, until_caster_next_turn=True,
    )


def test_parse_effect_returns_none_for_mass_pump_with_other_tail():
    # An unrecognized tail ("until end of combat" etc.) doesn't match
    # — the regex accepts only the two literal tails. Sanity-check the
    # regex stays narrow.
    assert _parse_effect(
        "creatures your opponents control get -3/-0 until end of combat"
    ) is None


# ---------- look at top two; one to hand, one to graveyard ----------

def test_parse_effect_recognizes_look_at_top_two_split():
    # Codecracker Hound's ETB. The two-sentence surface form (with an
    # embedded period between sentences) matches as a single
    # primitive — ``_parse_compound_effect``'s all-or-nothing rule
    # rejects the split because the second sentence isn't a
    # standalone effect, so we fall through to this regex.
    assert _parse_effect(
        "look at the top two cards of your library. "
        "Put one into your hand and the other into your graveyard"
    ) == LookAtTopTwoSplitHandGraveyard()


def test_parse_effect_phrase_recognizes_look_at_top_two_split():
    # Creature-trigger surface form — no source-subject pronoun on
    # this phrase (the verb ``look`` starts the clause).
    assert _parse_effect_phrase(
        "look at the top two cards of your library. "
        "Put one into your hand and the other into your graveyard"
    ) == LookAtTopTwoSplitHandGraveyard()


def test_parse_effect_returns_none_for_look_at_top_two_wrong_pile():
    # A surface form with reversed piles or wrong count doesn't match
    # — the regex is a literal phrase. Sanity-check the regex stays
    # narrow.
    assert _parse_effect(
        "look at the top two cards of your library. "
        "Put one into your graveyard and the other into your hand"
    ) is None


# ---------- return up to one other permanent you control to hand ----------

def test_parse_effect_recognizes_return_up_to_one_other_permanent():
    # Exosuit Savior's ETB. The ``up to one other`` fragment combines
    # the optionality (``optional=True``) with the self-exclusion
    # (``exclude_self=True``).
    assert _parse_effect(
        "return up to one other target permanent you control "
        "to its owner's hand"
    ) == ReturnTargetPermanentYouControlToOwnersHand(
        optional=True, exclude_self=True,
    )


def test_parse_effect_phrase_recognizes_return_up_to_one_other_permanent():
    # Creature-trigger surface form — no source-subject pronoun on
    # this phrase.
    assert _parse_effect_phrase(
        "return up to one other target permanent you control "
        "to its owner's hand"
    ) == ReturnTargetPermanentYouControlToOwnersHand(
        optional=True, exclude_self=True,
    )


def test_parse_effect_returns_none_for_return_without_other():
    # Without the ``other`` qualifier we don't claim the surface — the
    # regex is anchored on the full ``up to one other`` phrase.
    assert _parse_effect(
        "return up to one target permanent you control to its owner's hand"
    ) is None


# ---------- end-to-end card claims ----------

def _claimed_names() -> set[str]:
    return set(OracleParserCardSource().claimed_names)


def test_sinister_cryologist_claimed_by_parser():
    # Sinister Cryologist `{2}{U}` 2/3 Creature — Jellyfish Wizard.
    # Warp `{U}`. ETB: target creature an opponent controls gets
    # -3/-0 UEOT. Unlocked by the new opponent-controlled-pump
    # primitive.
    assert "Sinister Cryologist" in _claimed_names()


def test_mouth_of_the_storm_claimed_by_parser():
    # Mouth of the Storm `{6}{U}` 6/6 Elemental — Flying, Ward {2}.
    # ETB: creatures your opponents control get -3/-0 until your
    # next turn. Unlocked by the new mass-opponent-pump primitive
    # whose ``until_caster_next_turn`` flag flips on the longer
    # ``until your next turn`` tail.
    assert "Mouth of the Storm" in _claimed_names()


def test_codecracker_hound_claimed_by_parser():
    # Codecracker Hound `{2}{U}` 2/1 Dog. Warp `{2}{U}`. ETB: look
    # at the top two cards of your library; one to hand, one to
    # graveyard. Unlocked by the new look-at-top-two split-pile
    # primitive.
    assert "Codecracker Hound" in _claimed_names()


def test_exosuit_savior_claimed_by_parser():
    # Exosuit Savior `{2}{W}` 2/2 Human Soldier — Flying. ETB:
    # return up to one other target permanent you control to its
    # owner's hand. Unlocked by the new exosuit-savior-style bounce
    # primitive (optional + exclude_self).
    assert "Exosuit Savior" in _claimed_names()


def test_rayblade_trooper_claimed_by_parser():
    # Rayblade Trooper `{2}{W}` 2/2 Human Soldier. Warp `{1}{W}`.
    # ETB: put a +1/+1 counter on target creature you control. Death
    # trigger: nontoken creature you control with a +1/+1 counter on
    # it dies → make a 1/1 Human Soldier token (already supported by
    # the parser's death-trigger family). Unlocked here by the new
    # restricted-target +1/+1 counter primitive.
    assert "Rayblade Trooper" in _claimed_names()
