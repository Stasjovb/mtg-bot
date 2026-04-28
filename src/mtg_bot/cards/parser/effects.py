"""Unified effect grammar shared by creature triggered abilities and
spells.

Each shape's regex matches the *normalized* effect phrase — no
source-subject prefix (``it`` for creature triggers or ``<Name>``
for spells), no trailing period, first letter lowercased. Surface
preprocessing (the ``_normalize_*`` helpers below) strips the
per-context noise before dispatch, so both contexts share one
effect grammar — adding a new effect here makes it available to
creature triggered abilities and to spells (single-line and
multi-line) at the same time.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import (
    AddManaToPool,
    CounterTargetSpell,
    CreateLanderAndScheduleSacrifice,
    CreateToken,
    DealDamageAnyTarget,
    DealDamageEachOpponent,
    DealDamageToOpponentCreature,
    DealDamageToTargetCreature,
    DealDamageToTargetOpponent,
    DealDamageToTargetTappedCreature,
    DealNDamageToEachCreature,
    DestroyTargetArtifact,
    DestroyTargetArtifactEnchantmentOrFlyingCreature,
    DestroyTargetArtifactOrTappedCreature,
    DestroyTargetCreature,
    DestroyTargetLand,
    DestroyTargetNoncreaturePermanent,
    DestroyTargetNonlandPermanent,
    DiscardHandThenDrawN,
    DiscardSelf,
    DoubleTargetCreaturesPowerUEOT,
    DrawCards,
    EachOpponentDiscards,
    EachOpponentLosesLife,
    Effect,
    ExileAllArtifactsWithManaValueAtMost,
    ExileAllCreaturesAndSpacecraft,
    ExileEachOpponentsGraveyard,
    ExileTargetCreature,
    GainLife,
    LookAtTopTwoSplitHandGraveyard,
    LoseLife,
    MillTargetPlayer,
    MoveSelfCountersToTargetCreatureYouControl,
    OptionalDiscardCardThenDrawN,
    OptionalManaCostThenEffect,
    OptionalSacAnotherForEffect,
    OptionalSacAnotherForPumpSelfUEOT,
    OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    PumpCreaturesOpponentsControlUntilEOT,
    PumpCreaturesYouControlUntilEOT,
    PumpSelfUntilEOT,
    PumpTargetArtifactOrCreatureUntilEOT,
    PumpTargetCreatureUntilEOT,
    PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
    PutCardFromGraveyardOnBottomOfLibrary,
    PutChargeCountersOnTargetSpacecraftOrPlanetYouControl,
    PutStunCounterOnTappedCreature,
    PutPlusOneCounterOnCreatureYouControl,
    PutPlusOneCounterOnEachCreatureYouControl,
    PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    PutPlusOneCounterOnOpponentsCreature,
    PutPlusOneCounterOnSelf,
    PutPlusOneCounterOnTargetCreature,
    ReturnCreatureFromYourGraveyardToBattlefield,
    ReturnCreatureFromYourGraveyardToHand,
    ReturnTargetArtifactCardFromYourGraveyardToHand,
    ReturnTargetPermanentYouControlToOwnersHand,
    SearchLibraryForCard,
    SelfMill,
    Sequence,
    Surveil,
    TapAnotherTargetCreature,
    TapTargetArtifactOrCreature,
    TapTargetOpponentPermanentAndStunIt,
    TargetOpponentLosesLife,
    UntapTargetOtherPermanent,
)
from mtg_bot.cards.parser.keywords import _KEYWORD_LINES
from mtg_bot.cards.tokens import TOKEN_PRINTINGS


# Spelled-out small-cardinal lookup for oracle phrasings like
# ``mill three cards``. Scryfall consistently spells out 1–10 as words
# in mill-style effects (e.g. "mill three cards" on Lithic Hierograph).
# Larger amounts use digits, so the table tops out at ten — extend if a
# future card ships an oracle line with "mill twelve cards".
_SMALL_CARDINAL_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_SMALL_CARDINAL_PATTERN = "|".join(_SMALL_CARDINAL_WORDS)


_DEAL_DAMAGE_ANY_TARGET = re.compile(
    r"^deals (\d+) damage to any target$"
)
_DEAL_DAMAGE_TARGET_CREATURE = re.compile(
    r"^deals (\d+) damage to target creature$"
)
# "<source> deals N damage to target creature an opponent controls" —
# Nova Hellkite's ETB. Maps to ``DealDamageToOpponentCreature(amount=N)``
# whose ``legal_targets`` filters to creatures NOT controlled by the
# resolving controller. The ``deals`` form (no ``it`` / ``you`` subject)
# is what survives both creature-trigger normalization (the ``it ``
# prefix-strip) and spell normalization (the ``<Name> `` prefix-strip).
# Tried BEFORE the bare ``deals N damage to target creature`` regex
# which has a ``$`` anchor — phrases that end at ``creature`` with no
# qualifier match the bare form, while phrases with the ``an opponent
# controls`` tail land here.
_DEAL_DAMAGE_TARGET_OPPONENT_CREATURE = re.compile(
    r"^deals (\d+) damage to target creature an opponent controls$"
)
# "<source> deals N damage to target opponent" — Biotech Specialist's
# sacrifice-an-artifact trigger body. Damage targets a player rather
# than a creature; ``DealDamageToTargetOpponent(amount=N)`` filters
# the legal-target pool to opponents (not the source's controller).
#
# The optional ``this creature `` prefix accepts the surface where the
# source is named explicitly inside the trigger body. Scryfall prints
# this form when the trigger's CONDITION already uses ``you`` as the
# subject (Biotech Specialist's ``Whenever you sacrifice an artifact``
# leads into ``this creature deals 2 damage to target opponent`` — the
# explicit ``this creature`` resolves what would otherwise be an
# ambiguous ``it`` reference). The
# ``_normalize_creature_effect_phrase`` strip only consumes ``it ``,
# so we accept the longer subject form here at the regex level
# rather than expanding the normalizer (which would also strip
# ``this creature`` from phrases where it's a self-object reference
# in primitives like ``put a +1/+1 counter on this creature``).
#
# Tried BEFORE the bare ``deals N damage to any target`` regex
# because the ``$`` anchor on the bare regex would not match the
# ``target opponent`` tail anyway, but ordering more-specific before
# more-general is the convention in this dispatcher.
_DEAL_DAMAGE_TARGET_OPPONENT = re.compile(
    r"^(?:this creature )?deals (\d+) damage to target opponent$"
)
# Controller draws cards. The optional ``you `` prefix surfaces in
# compound bodies like ``you draw a card and lose 1 life`` (Voidforged
# Titan, Decode Transmissions, Elegy Acolyte) — the leading ``you`` is
# carried over from the original sentence's subject when the printing
# joins two effects with `` and `` and the splitter would otherwise
# leave the first piece reading as ``you draw a card``. Mirrors the
# ``(?:you )?`` shape on ``_LOSE_N_LIFE`` (the same ``you`` carry-over
# on the other half of the canonical pair) — the ``you`` is purely
# surface noise because the controller is already implicit in every
# effect's resolve signature.
_DRAW_A_CARD = re.compile(r"^(?:you )?draw a card$")
_DRAW_N_CARDS = re.compile(r"^(?:you )?draw (\d+) cards$")
_YOU_GAIN_N_LIFE = re.compile(r"^you gain (\d+) life$")
_PUT_PLUS_ONE_COUNTER_ON_TARGET_CREATURE = re.compile(
    r"^put a \+1/\+1 counter on target creature$"
)
# "Put a +1/+1 counter on target creature you control" — Rayblade
# Trooper's ETB. Restricted variant: legal targets are creatures the
# resolving controller controls. Maps to
# ``PutPlusOneCounterOnCreatureYouControl(amount=1)``. Tried BEFORE
# the bare ``target creature`` regex so the more-specific
# ``you control`` shape wins on phrases that carry it.
_PUT_PLUS_ONE_COUNTER_ON_TARGET_CREATURE_YOU_CONTROL = re.compile(
    r"^put a \+1/\+1 counter on target creature you control$"
)
# "Put a +1/+1 counter on target creature an opponent controls" —
# Sunset Saboteur's attack trigger. Mirror image of the
# ``you control`` restriction above: legal targets are creatures NOT
# controlled by the resolving controller. Maps to
# ``PutPlusOneCounterOnOpponentsCreature(amount=1)``. Tried BEFORE
# the bare ``target creature`` regex so the more-specific
# ``an opponent controls`` shape wins on phrases that carry it.
_PUT_PLUS_ONE_COUNTER_ON_TARGET_OPPONENT_CREATURE = re.compile(
    r"^put a \+1/\+1 counter on target creature an opponent controls$"
)
_PUT_PLUS_ONE_COUNTER_ON_THIS_CREATURE = re.compile(
    r"^put a \+1/\+1 counter on this creature$"
)
# "Put a +1/+1 counter on each of up to N target creatures" —
# multi-target counter spread (Weftblade Enhancer's ETB uses ``two``).
# The amount tail accepts spelled-out small cardinals (the only form
# that ships in EoE today; ``two`` for Weftblade) plus bare digits so
# a future ``up to three target creatures`` printing parses without
# further grammar work. Maps to
# ``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=N)``.
_PUT_PLUS_ONE_COUNTER_ON_EACH_OF_UP_TO_N_TARGET_CREATURES = re.compile(
    rf"^put a \+1/\+1 counter on each of up to "
    rf"(\d+|{_SMALL_CARDINAL_PATTERN}) target creatures$"
)
# "Put its counters on target creature you control." — Dockworker Drone's
# dies trigger. The ``its`` pronoun refers to the source creature (dying
# permanent). Maps to ``MoveSelfCountersToTargetCreatureYouControl()``,
# whose engine class reads ``state.resolving_source.plus_one_counters``
# and transfers them to the chosen target. Surface form is post-
# normalization (the ``it `` prefix-strip in ``_normalize_creature_
# effect_phrase`` doesn't fire because the phrase starts with the verb
# ``put``, not a pronoun subject — so the ``its`` here survives intact).
_PUT_ITS_COUNTERS_ON_TARGET_CREATURE_YOU_CONTROL = re.compile(
    r"^put its counters on target creature you control$"
)
_DESTROY_TARGET_CREATURE = re.compile(r"^destroy target creature$")
# "Destroy up to one other target creature. If that creature wasn't
# dealt damage this turn, its controller draws N cards." — Faller's
# Faithful's ETB. Single primitive with an embedded follow-up
# sentence; the captured amount lands on
# ``DestroyTargetCreature(draw_if_undamaged_amount=N)`` along with
# ``optional=True`` (the ``up to one`` fragment) and
# ``exclude_self=True`` (the ``other`` fragment). The amount tail
# accepts spelled-out small cardinals (``two`` is what Faller's
# prints) plus bare digits for a future printing.
_DESTROY_UP_TO_ONE_OTHER_TARGET_CREATURE_DRAW_IF_UNDAMAGED = re.compile(
    rf"^destroy up to one other target creature\. "
    rf"If that creature wasn't dealt damage this turn, "
    rf"its controller draws (\d+|{_SMALL_CARDINAL_PATTERN}) cards$"
)
# "Destroy target creature or Spacecraft." — Embrace Oblivion's
# destroy clause. Maps to ``DestroyTargetCreature(or_spacecraft=True)``
# whose ``legal_targets`` extends the bare ``destroy target creature``
# pool to also include unstationed Spacecraft (which aren't
# currently creatures). The ``Spacecraft`` capitalization is verbatim
# from the oracle text — the spell-effect normalizer only lowercases
# the first letter of the phrase, so inner type-name capitalization
# survives.
_DESTROY_TARGET_CREATURE_OR_SPACECRAFT = re.compile(
    r"^destroy target creature or Spacecraft$"
)
_COUNTER_TARGET_SPELL = re.compile(r"^counter target spell$")
# "Counter target artifact or enchantment spell." — Annul. Same engine
# class as the bare counterspell, just with a non-empty ``filter_types``
# frozenset that gates which stack items are legal targets. Tried before
# the bare ``counter target spell`` regex below because the bare regex
# requires the phrase to end at ``spell`` with no qualifier.
_COUNTER_TARGET_ARTIFACT_OR_ENCHANTMENT_SPELL = re.compile(
    r"^counter target artifact or enchantment spell$"
)
_EXILE_TARGET_CREATURE = re.compile(r"^exile target creature$")
# "Exile all creatures and Spacecraft." — Beyond the Quiet wrath. Capital
# ``S`` on Spacecraft is preserved verbatim from the oracle text — the
# normalization layer only lowercases the first letter of the phrase, so
# inner type-name capitalization survives. Untargeted (mass) effect.
#
# Note this is matched here as a SINGLE-effect regex, before the
# compound-effect splitter would carve the phrase on `` and `` —
# ``_parse_compound_effect`` runs first in ``_parse_effect`` but punts
# (returns None) when any split-piece fails to parse, and ``Spacecraft``
# alone isn't a recognized effect, so the compound attempt rejects and
# falls through to the single-effect dispatcher where this regex wins.
_EXILE_ALL_CREATURES_AND_SPACECRAFT = re.compile(
    r"^exile all creatures and Spacecraft$"
)
# "Exile all artifacts with mana value N or less." — Ruinous Rampage's
# anti-artifact mode. The captured group is the max mana value (digit
# only — no card prints a spelled-out mana-value bound today). Maps to
# ``ExileAllArtifactsWithManaValueAtMost(max_mv=N)``.
_EXILE_ALL_ARTIFACTS_WITH_MANA_VALUE_AT_MOST = re.compile(
    r"^exile all artifacts with mana value (\d+) or less$"
)
_EACH_OPPONENT_LOSES_N_LIFE = re.compile(
    r"^each opponent loses (\d+) life$"
)
# "Exile each opponent's graveyard" — untargeted graveyard wipe on
# every opponent (Dauntless Scrapbot's ETB compound first half).
# Maps to ``ExileEachOpponentsGraveyard()`` which sweeps every card
# in each opponent's graveyard into exile at resolve time.
_EXILE_EACH_OPPONENTS_GRAVEYARD = re.compile(
    r"^exile each opponent's graveyard$"
)
# "<source> deals N damage to each opponent." — mass burn aimed at
# every opponent (Ruinous Rampage's burn mode). The ``deals`` form
# (no ``it`` / ``you`` subject) is what Scryfall prints for spells
# that name themselves as the subject; the spell-effect normalizer
# strips the ``<Name>`` prefix before this regex sees the phrase, so
# the surface form here is exactly ``deals N damage to each opponent``.
# For creature-source triggered abilities the ``it`` prefix is also
# stripped first, leaving the same canonical ``deals …`` form.
#
# The optional ``this creature `` prefix accepts the surface where the
# trigger body names the source explicitly. Scryfall prints that form
# when the trigger CONDITION already uses a different subject (Weftstalker
# Ardent's ``Whenever another creature or artifact you control enters``
# leads into ``this creature deals 1 damage to each opponent`` — the
# explicit ``this creature`` resolves what would otherwise be an ambiguous
# ``it`` reference to the unrelated entering object). Mirrors the same
# ``(?:this creature )?`` shape on ``_DEAL_DAMAGE_TARGET_OPPONENT``
# (Biotech Specialist's ``Whenever you sacrifice an artifact, this
# creature deals 2 damage to target opponent``) — same justification:
# the normalizer only consumes the ``it `` pronoun, not the longer
# ``this creature`` self-object reference.
_DEAL_N_DAMAGE_EACH_OPPONENT = re.compile(
    r"^(?:this creature )?deals (\d+) damage to each opponent$"
)
# "<source> deals N damage to each creature." — untargeted board-wipe
# burn (Pyroclasm in Duskmourn; the same primitive surfaces inside
# Lithobraking's reflexive optional-sac sequence and Extinguisher
# Battleship's ETB sequence in EoE, where it's already exercised by
# the ``DealNDamageToEachCreature`` engine class). Mirrors the
# ``deals N damage to each opponent`` shape: ``deals`` form (no ``it``
# / ``you`` subject) is what Scryfall prints for spells that name
# themselves as the subject; the spell-effect normalizer strips the
# ``<Name>`` prefix before this regex sees the phrase. The optional
# ``this creature `` prefix accepts the surface where a creature-source
# trigger body names the source explicitly (same precedent as
# ``_DEAL_N_DAMAGE_EACH_OPPONENT`` and ``_DEAL_DAMAGE_TARGET_OPPONENT``
# — the ``it `` normalizer only consumes the bare pronoun).
_DEAL_N_DAMAGE_EACH_CREATURE = re.compile(
    r"^(?:this creature )?deals (\d+) damage to each creature$"
)
# "Search your library for an artifact card, reveal it, put it into
# your hand, then shuffle." — Scour for Scrap mode 1 (and any future
# narrow tutor with the same surface). Maps to
# ``SearchLibraryForCard(filter_name="artifact", may_fail=True)``.
# The full surface form (with reveal/hand/shuffle tail) is required:
# this primitive doesn't claim a simpler ``search your library for an
# artifact card`` line because that bare shape isn't a complete oracle
# clause for any printed card — every artifact tutor in EoE prints the
# full reveal/hand/shuffle tail.
_SEARCH_LIBRARY_FOR_ARTIFACT_CARD = re.compile(
    r"^search your library for an artifact card, "
    r"reveal it, put it into your hand, then shuffle$"
)
# Token-creation effect grammar. Two related shapes co-exist in Scryfall
# oracle text:
#
# 1. **Stat-bearing creature tokens** — e.g.
#    ``create a tapped 2/2 colorless Robot artifact creature token`` or
#    ``create two 1/1 white Human Soldier creature tokens``. Carries
#    explicit power/toughness, a color word, one or more subtype words,
#    and a ``[artifact ]?creature token[s]?`` tail.
# 2. **Bare-name tokens** — e.g. ``create a Lander token``. No stats /
#    color / "creature" tail; the subtype word IS the token name and
#    fully identifies the registered printing (Lander, Munitions, etc.).
#
# Both paths look up the resolved token name in ``TOKEN_PRINTINGS``. The
# parser is NOT in the business of building token printings on the fly —
# if the registry doesn't already carry an entry for the matched name,
# parsing fails (returns ``None``) and the card stays unclaimed. Adding
# new token shapes is a separate concern handled in ``cards/tokens.py``.
#
# The leading count phrase is one of:
#   - ``a`` / ``an``    → 1
#   - a small spelled-out cardinal (``two``, ``three``, …)
#   - a bare digit
# The optional ``tapped`` keyword sits between the count and the stats
# (or directly before the bare-name in shape 2).
_TOKEN_COUNT_PATTERN = rf"a|an|\d+|{_SMALL_CARDINAL_PATTERN}"
# Color word — one of the five colors plus colorless. Not captured for
# correctness (the registry already encodes color via the printing's
# ``card_types``/``produces``); we just need to consume it so the regex
# matches the surface form.
_TOKEN_COLOR_PATTERN = r"white|blue|black|red|green|colorless"
# Stat-bearing creature-token shape. The captured groups are:
#   1. count word/digit
#   2. literal ``tapped`` if present (None otherwise)
#   3. power
#   4. toughness
#   5. color word (consumed only — see above)
#   6. subtype phrase (one or more space-separated capitalized words)
#   7. literal ``artifact`` if the token is also an artifact
# The trailing ``creature token[s]?`` is required — bare-name tokens
# (Lander, Munitions) take a different surface form and parse via
# ``_CREATE_BARE_NAME_TOKEN`` below.
_CREATE_CREATURE_TOKEN = re.compile(
    rf"^create ({_TOKEN_COUNT_PATTERN}) (tapped )?(\d+)/(\d+) "
    rf"({_TOKEN_COLOR_PATTERN}) ([A-Z][A-Za-z]*(?: [A-Z][A-Za-z]*)*) "
    rf"(artifact )?creature tokens?$"
)
# Bare-name token shape — ``create a Lander token`` /
# ``create two Lander tokens``. The captured subtype IS the registry
# key. Optional ``tapped`` sits between the count and the name (no EoE
# card prints a tapped Lander today, but the slot is reserved so a
# future ``create a tapped Lander token`` line parses without further
# grammar work).
_CREATE_BARE_NAME_TOKEN = re.compile(
    rf"^create ({_TOKEN_COUNT_PATTERN}) (tapped )?"
    rf"([A-Z][A-Za-z]*(?: [A-Z][A-Za-z]*)*) tokens?$"
)
_SURVEIL_N = re.compile(r"^surveil (\d+)$")
# "Look at the top two cards of your library. Put one into your hand
# and the other into your graveyard." — Codecracker Hound's ETB.
# Maps to ``LookAtTopTwoSplitHandGraveyard()``. The two-sentence
# surface is what Scryfall prints — the embedded period sits inside
# the effect phrase rather than being the trailing terminator. Compound
# splits don't apply (the second sentence's leading ``Put one`` doesn't
# parse as a standalone effect — see ``_parse_compound_effect``'s
# all-or-nothing rule), so the regex matches the literal two-sentence
# surface as a single primitive.
_LOOK_TOP_TWO_SPLIT_HAND_GRAVEYARD = re.compile(
    r"^look at the top two cards of your library\. "
    r"Put one into your hand and the other into your graveyard$"
)
# Mill is "mill <amount> cards" where the amount is either a digit or
# one of the spelled-out small cardinals (Scryfall printing convention).
# Singular "mill 1 card" / "mill one card" is intentionally unsupported
# — no EoE card prints that surface form. Add it the day one ships.
_MILL_N_CARDS = re.compile(
    rf"^mill (\d+|{_SMALL_CARDINAL_PATTERN}) cards$"
)
_DESTROY_TARGET_ARTIFACT = re.compile(r"^destroy target artifact$")
# "Destroy target artifact, enchantment, or creature with flying." —
# Shattered Wings's destroy clause. Maps to
# ``DestroyTargetArtifactEnchantmentOrFlyingCreature()`` whose
# ``legal_targets`` filters to artifacts (any), enchantments (any),
# or creatures that currently have flying. The Oxford comma after
# ``enchantment`` is required (matches Scryfall's printed form).
_DESTROY_TARGET_ARTIFACT_ENCHANTMENT_OR_FLYING_CREATURE = re.compile(
    r"^destroy target artifact, enchantment, or creature with flying$"
)
_DESTROY_TARGET_LAND = re.compile(r"^destroy target land$")
_DESTROY_TARGET_NONCREATURE_PERMANENT = re.compile(
    r"^destroy target noncreature permanent$"
)
# "Destroy target nonland permanent." — Thaumaton Torpedo's activated
# ability. Maps to the existing ``DestroyTargetNonlandPermanent`` engine
# class whose ``legal_targets`` filters the battlefield to non-land
# permanents (creatures, artifacts, enchantments, planeswalkers).
# Distinct from ``destroy target noncreature permanent`` above — that
# one excludes creatures, this one excludes lands.
_DESTROY_TARGET_NONLAND_PERMANENT = re.compile(
    r"^destroy target nonland permanent$"
)
# "Add {<color>}." — single coin of a single color. Mana ability surface
# form. The captured letter is one of WUBRG (no colorless single-coin
# add in EoE today; extend to ``[WUBRGC]`` if a future card needs it).
# The surrounding ActivatedAbility built by the activated-grammar layer
# auto-flags ``is_mana_ability=True`` once the resulting effect is
# recognized by ``_is_mana_ability_effect``, so the engine bypasses the
# stack on activation per CR 605.
_ADD_SINGLE_COLOR_MANA = re.compile(r"^add \{([WUBRG])\}$")
# "Add one mana of any color" — single coin of any color, the
# at-resolution choose-a-color mana ability surface form (All-Fates
# Scroll's ``{T}: Add one mana of any color.``). Maps to
# ``AddManaToPool(produces=(("any", 1),))`` — the engine treats the
# ``"any"`` color tag as a chosen-at-mint colored coin (the controller
# names the color when the ability resolves). Distinct from the
# bracketed ``add {<color>}`` shape: the latter mints a fixed-color
# coin known at parse time, this one defers the choice to resolution.
# Mana-source tracking treats ``"any"`` coins as untyped at compile
# time, mirroring ``land_builder``'s ``_fancy_pay_one_life_any_color``
# wiring on Mana Confluence.
_ADD_ONE_MANA_OF_ANY_COLOR = re.compile(r"^add one mana of any color$")
# "Add {<color>}{<color>}." — two coins of a single color (Steelswarm
# Operator's ``{T}: Add {U}{U}`` ability mints two restricted coins of
# the same color). The captured letter is reused — the engine class
# accepts a tuple of (color, amount) coins, so the produced effect is
# ``AddManaToPool(produces=((c, 1), (c, 1)))``. Two coins is what EoE
# prints today; if a future card uses ``Add {U}{U}{U}`` extend the
# regex with another optional brace pair (or generalize to a parser
# loop).
_ADD_TWO_SAME_COLOR_MANA = re.compile(
    r"^add \{([WUBRG])\}\{([WUBRG])\}$"
)
# "Add {<mana>}. Spend this mana only to <restriction>." —
# restricted-mana ability whose produced coins are tagged with an
# engine-side ``spend_restriction`` string at mint time. EoE wiring:
#
#   * ``Spend this mana only to cast an artifact spell`` →
#     ``"artifact_spell"`` (Steelswarm Operator's first ability).
#   * ``Spend this mana only to activate abilities of artifact
#     sources`` → ``"artifact_activation"`` (Steelswarm Operator's
#     second ability).
#
# Both restrictions are gated at cost-payment time by
# ``_coin_satisfies_context`` in ``actions.py``. The captured mana
# segment accepts either a single ``{<color>}`` or two of the same
# color (``{<color>}{<color>}``) — extend the inner pattern if a future
# printing mints a hybrid- or multi-color restricted batch. Tried
# BEFORE the bare ``add {<color>}`` regex so the qualifier wins; the
# bare regex's ``$`` anchor wouldn't match the multi-sentence shape
# anyway, but ordering more-specific before more-general is the
# convention here.
_ADD_MANA_WITH_SPEND_RESTRICTION = re.compile(
    r"^add (\{[WUBRG]\}(?:\{[WUBRG]\})?)\. "
    r"Spend this mana only to "
    r"(cast an artifact spell|activate abilities of artifact sources)$"
)
# Surface phrase → ``ActivationCost.spend_restriction`` string mapping
# for the restricted-mana ability above. Each tail phrase below comes
# from a real EoE printing's oracle text; the engine string is the key
# expected by ``_coin_satisfies_context`` (``actions.py``).
_SPEND_RESTRICTION_BY_PHRASE: dict[str, str] = {
    "cast an artifact spell": "artifact_spell",
    "activate abilities of artifact sources": "artifact_activation",
}
# "Target opponent loses N life" — pure life-loss spell/ability surface.
# TargetOpponentLosesLife filters its legal-targets pool to opponents.
_TARGET_OPPONENT_LOSES_N_LIFE = re.compile(
    r"^target opponent loses (\d+) life$"
)
# "Return up to one other target permanent you control to its owner's
# hand" — Exosuit Savior's ETB. Maps to
# ``ReturnTargetPermanentYouControlToOwnersHand(optional=True,
# exclude_self=True)``. The ``up to one other`` fragment combines the
# ``up to one`` optionality (resolves as a no-op if no target chosen)
# with the ``other`` self-exclusion (filters the trigger source out
# of the legal pool). Lands are legal targets — the engine class's
# ``legal_targets`` doesn't filter on type beyond the controller and
# self gate.
_RETURN_UP_TO_ONE_OTHER_PERMANENT_YOU_CONTROL_TO_OWNERS_HAND = re.compile(
    r"^return up to one other target permanent you control "
    r"to its owner's hand$"
)
# "Return target creature card from your graveyard to your hand" —
# graveyard-to-hand reanimation surface.
_RETURN_TARGET_CREATURE_GRAVEYARD_TO_HAND = re.compile(
    r"^return target creature card from your graveyard to your hand$"
)
# "Return target creature card from your graveyard to the battlefield"
# — graveyard reanimation surface (Xu-Ifit and forward-compat for any
# future "raise dead" oracle line).
_RETURN_TARGET_CREATURE_GRAVEYARD_TO_BATTLEFIELD = re.compile(
    r"^return target creature card from your graveyard to the battlefield$"
)
# Multi-sentence Xu-Ifit, Osteoharmonist variant — the printed oracle is
# ``Return target creature card from your graveyard to the battlefield.
# It's a Skeleton in addition to its other types and has no abilities.``
# The ``It's a Skeleton …`` rider is intentionally dropped (the engine
# doesn't yet model "has no abilities" suppression nor in-place subtype
# grants on an arriving creature). This mirrors the matching
# simplification in the static registry — the resulting primitive is
# the same bare ``ReturnCreatureFromYourGraveyardToBattlefield`` the
# bare regex above produces. Kept as its own regex (rather than a
# preprocessing strip) so the simplification is local and explicit:
# the only wrapping that matches this surface verbatim is Xu-Ifit's,
# and any future printing with a different rider tail will hit the
# bare regex's ``$`` anchor and surface a parser miss instead of being
# silently dropped.
_RETURN_TARGET_CREATURE_GRAVEYARD_TO_BATTLEFIELD_AS_SKELETON = re.compile(
    r"^return target creature card from your graveyard "
    r"to the battlefield\. "
    r"It's a Skeleton in addition to its other types "
    r"and has no abilities$"
)
# "Return target artifact card from your graveyard to your hand" —
# matches Scour for Scrap's mode (parsed via the modal combinator
# elsewhere, but a primitive worth surfacing in the unified grammar).
_RETURN_TARGET_ARTIFACT_GRAVEYARD_TO_HAND = re.compile(
    r"^return target artifact card from your graveyard to your hand$"
)
# "Put target card from a graveyard on the bottom of its owner's
# library" — Chrome Companion's tap-mana activated ability. Untyped
# grave-target (any card in any player's graveyard is legal); the
# resolution moves the chosen card to the bottom of its owner's
# library. Maps to the existing ``PutCardFromGraveyardOnBottomOfLibrary``
# engine class. Surface form is post-normalization (the ``it `` prefix-
# strip in ``_normalize_creature_effect_phrase`` doesn't fire because
# the phrase starts with the verb ``put``, not a pronoun subject — so
# the ``its`` here survives intact, mirroring the ``put its counters
# on …`` precedent).
_PUT_CARD_FROM_GRAVEYARD_ON_BOTTOM_OF_LIBRARY = re.compile(
    r"^put target card from a graveyard "
    r"on the bottom of its owner's library$"
)
# "Target creature gets +N/+M until end of turn" or
# "Target creature gets -N/-M until end of turn". Both signs supported
# (PumpTargetCreatureUntilEOT folds positive and negative bonuses
# through the same pump path). Mixed signs (``+1/-1``) are also
# accepted to keep the grammar uniform — no EoE card prints that today
# but the regex stays the simplest correct shape.
_PUMP_TARGET_CREATURE_UEOT = re.compile(
    r"^target creature gets ([+-]\d+)/([+-]\d+) until end of turn$"
)
# "Up to one target creature gets ±N/±M until end of turn" — optional
# pump/debuff with no fizzle when the battlefield has no creatures.
# Surfaces on Dubious Delicacy's ETB ("up to one target creature gets
# -3/-3 until end of turn"). Maps to
# ``PumpTargetCreatureUntilEOT(power_bonus=N, toughness_bonus=M,
# optional=True)`` — the ``optional`` flag flips the engine class's
# ``target_count_range`` to ``(0, 1)`` and ``requires_target`` to
# False, so a no-target resolution is a clean no-op rather than a
# fizzle.
_PUMP_UP_TO_ONE_TARGET_CREATURE_UEOT = re.compile(
    r"^up to one target creature gets ([+-]\d+)/([+-]\d+) "
    r"until end of turn$"
)
# "Target creature an opponent controls gets -N/-M until end of turn" —
# pump variant restricted to opposing creatures (Sinister Cryologist's
# ETB debuff). Maps to ``PumpTargetCreatureUntilEOT(opponents_only=True)``
# which gates ``legal_targets`` to creatures NOT controlled by the
# resolving controller. Negative bonuses are typical here (debuff
# semantics) but the regex accepts both signs so a future card that
# prints a positive opponent-only pump (rare but possible) parses
# without further grammar work — symmetric with the bare pump regex
# above.
_PUMP_TARGET_OPPONENT_CREATURE_UEOT = re.compile(
    r"^target creature an opponent controls gets ([+-]\d+)/([+-]\d+) "
    r"until end of turn$"
)
# "Creatures your opponents control get -N/-M until end of turn" /
# "...until your next turn" — mass debuff on every creature an opponent
# controls (Mouth of the Storm's ETB). Maps to
# ``PumpCreaturesOpponentsControlUntilEOT(power_bonus=N, toughness_bonus=M,
# until_caster_next_turn=...)``. The ``until your next turn`` tail
# extends the duration past the casting turn's cleanup; the bare
# ``until end of turn`` tail clears at the normal cleanup step.
_PUMP_OPPONENT_CREATURES_UEOT = re.compile(
    r"^creatures your opponents control get ([+-]\d+)/([+-]\d+) "
    r"until (end of turn|your next turn)$"
)
# "[Other ]creatures you control get +N/+M[ and gain <kw>[ and <kw2>...]]
# until end of turn" — anthem-style mass pump with optional
# source-self exclusion (``other``) and optional grant-keywords rider
# (``and gain <kw>``). Maps to ``PumpCreaturesYouControlUntilEOT``
# with ``exclude_source`` flipped by group-1 capture and
# ``granted_keywords`` populated from the body parsed by
# ``_parse_keyword_grant_body`` against the keyword-line whitelist.
#
# Surface coverage today:
#   * bare ``creatures you control get +N/+M until end of turn`` —
#     Dual-Sun Adepts' ``{5}`` mass pump (no exclusion, no grants).
#   * ``other creatures you control get +1/+0 and gain deathtouch
#     until end of turn`` — Syr Vondam, the Lucent's enters/attacks
#     trigger (exclude_source + granted_keywords={'deathtouch'}).
#
# Both signs accepted for the bonuses (no EoE printing uses negative
# self-mass pump today, but the uniform shape parses one without
# further grammar work). The ``other`` and ``and gain <kw>`` clauses
# are independently optional — every combination flows through the
# same engine class with the corresponding flags/fields populated.
_PUMP_YOUR_CREATURES_UEOT = re.compile(
    r"^(other )?creatures you control get ([+-]\d+)/([+-]\d+)"
    r"(?: and gain (.+))? until end of turn$"
)
# "Target creature you control gets +N/+M until end of turn" —
# you-control-only single-target pump (Zookeeper Mechan's ``{6}{R}``
# sorcery-speed activated ability). Maps to
# ``PumpTargetCreatureUntilEOT(you_control_only=True)`` whose
# ``legal_targets`` filters the standard creature pool to creatures the
# resolving controller controls. Tried BEFORE the bare ``target creature
# gets ... UEOT`` regex so the ``you control`` qualifier wins; the bare
# regex's ``$`` anchor wouldn't match the qualifier anyway, but
# ordering more-specific before more-general is the convention in this
# dispatcher.
_PUMP_TARGET_CREATURE_YOU_CONTROL_UEOT = re.compile(
    r"^target creature you control gets ([+-]\d+)/([+-]\d+) "
    r"until end of turn$"
)
# "Double the power of target creature you control until end of turn"
# — Mightform Harmonizer's landfall trigger body. The
# ``DoubleTargetCreaturesPowerUEOT`` engine class adds the target's
# current effective power as a temporary power bonus that clears at
# end-of-turn cleanup. Distinct from the ``gets +N/+0`` UEOT pump
# regexes above: the bonus amount is computed dynamically from the
# target's current power at resolve time, not a fixed constant. Maps
# to the engine class with no parameters — the legal-target predicate
# (``target creature you control``) and duration (``until end of
# turn``) are both encoded by the class.
_DOUBLE_TARGET_CREATURE_YOU_CONTROL_POWER_UEOT = re.compile(
    r"^double the power of target creature you control until end of "
    r"turn$"
)
# Controller loses N life. Surface forms ``lose N life`` (post-compound
# split, where the carried-over subject is implicit — Decode
# Transmissions, Elegy Acolyte, Voidforged Titan all print
# ``you draw a card and lose 1 life``) and ``you lose N life`` (the
# explicit form, included for symmetry with ``you gain N life``). Both
# map to the same ``LoseLife`` primitive — the ``you`` is purely
# surface noise here because the controller is already implicit in
# every effect's resolve signature.
_LOSE_N_LIFE = re.compile(r"^(?:you )?lose (\d+) life$")
# "You may pay {COST}. If you do, <inner-effect>." — the ``OptionalManaCost
# ThenEffect`` wrapper. The inner-effect phrase is parsed recursively via
# the unified grammar, so any single-effect (or compound) primitive that
# parses on its own can serve as the ``If you do, …`` payload — e.g.
# ``put a +1/+1 counter on this creature`` (Oreplate Pangolin) or
# ``draw a card and you gain 1 life`` (synthetic compound).
#
# Cost shape is the standard ``{...}`` braced mana-cost mini-language
# (e.g. ``{2}`` or ``{1}{R}``); it's captured verbatim and handed to
# ``OptionalManaCostThenEffect`` which parses it via
# ``parse_mana_cost`` at resolve time.
#
# Note the embedded period after the cost: oracle text always prints
# ``You may pay {N}. If you do, …`` as TWO sentences. The
# normalization layers (``_normalize_creature_effect_phrase`` and
# ``_normalize_spell_effect_phrase``) only strip the OUTER trailing
# period — the inner sentence-boundary period stays as a literal
# match here.
_YOU_MAY_PAY_THEN_EFFECT = re.compile(
    r"^you may pay (\{[^}]+(?:\}\{[^}]+)*\})\. If you do, (.+)$"
)
# "Target creature gets +N/+M and gains <kw>[ and <kw2>...] until end of
# turn." — pump + grant-keywords compound. The granted-keywords body
# (between ``and gains `` and `` until end of turn``) is one or more
# evergreen-keyword tokens joined by `` and `` and validated against the
# keyword-line whitelist before the parsed effect is returned. Both the
# bare-target form (Rig for War, Dark Endurance) and the
# ``target creature you control`` restricted form (Kavaron Turbodrone,
# Molecular Modifier — activated/triggered abilities not yet wired by
# the surrounding builders, but the effect primitive is in place) share
# the same regex via the optional ``(?:you control )?`` group. Future
# cards with multiple keywords (``... and gains first strike and reach
# UEOT``) parse through the same shape. The ``you control`` group is
# captured (group 1) and translated into the engine's
# ``you_control_only=True`` flag at handler time.
_PUMP_AND_GAIN_KEYWORDS_UEOT = re.compile(
    r"^target creature (you control )?gets ([+-]\d+)/([+-]\d+) and gains "
    r"(.+) until end of turn$"
)
# "You may discard a card. If you do, draw N cards." — the
# ``OptionalDiscardCardThenDrawN`` wrapper. The amount tail accepts the
# Scryfall standard variants for "1": the article ``a`` for the singular
# ``draw a card`` and the spelled-out small cardinals (``draw two
# cards`` is Melded Moxite's printed form) plus bare digits for any
# future card that uses ``draw 3 cards``. Inner-effect parsing is NOT
# delegated to ``_parse_effect`` here because the engine class hardcodes
# the inner draw — only the count needs to be extracted from the
# surface text.
_OPTIONAL_DISCARD_THEN_DRAW = re.compile(
    rf"^you may discard a card\. If you do, "
    rf"draw (a|\d+|{_SMALL_CARDINAL_PATTERN}) cards?$"
)
# "You may discard your hand. If you do, draw N cards." — Vaultguard
# Trooper's tapped-creatures-gated end-step trigger inner effect (the
# ``ConditionalOnTappedCreatures`` wrapper sits at the trigger-line
# level, not inside the effect-phrase grammar). Distinct from the
# single-card discard-then-draw above: discards the WHOLE hand, not a
# single chosen card. Maps to ``DiscardHandThenDrawN(amount=N)``. The
# amount tail accepts the Scryfall-printed forms — bare digits and
# spelled-out small cardinals (``two`` is what Vaultguard prints);
# ``a`` would collapse to 1 if a future card prints
# ``draw a card`` after a hand discard.
_OPTIONAL_DISCARD_HAND_THEN_DRAW = re.compile(
    rf"^you may discard your hand\. If you do, "
    rf"draw (a|\d+|{_SMALL_CARDINAL_PATTERN}) cards?$"
)
# "You may sacrifice another creature or artifact. If you do, this
# creature gets +N/+M until end of turn." — the
# ``OptionalSacAnotherForPumpSelfUEOT`` wrapper. Mirrors the surface
# form on Comet Crawler's attack trigger. Pump-self-only (no
# ``granted_keywords`` rider parsed today; no EoE printing pairs the
# self-sac pump with an inner keyword grant). Tried BEFORE the more
# general ``OptionalSacAnotherForEffect`` regex so the self-pump shape
# wins and produces the specialized engine class instead of falling
# through.
_OPTIONAL_SAC_ANOTHER_FOR_PUMP_SELF_UEOT = re.compile(
    r"^you may sacrifice another creature or artifact\. If you do, "
    r"this creature gets ([+-]\d+)/([+-]\d+) until end of turn$"
)
# "You may sacrifice another creature or artifact. If you do, <inner-
# effect>." — the general ``OptionalSacAnotherForEffect`` wrapper.
# Inner-effect phrase is parsed recursively via the unified grammar so
# any single-effect (or compound) primitive that parses on its own can
# serve as the consequence (e.g. ``draw a card`` on Swarm Culler, or a
# ``put a +1/+1 counter on this creature`` on a future printing).
# Failure to parse the inner rejects the whole line so the wrapping
# card stays unclaimed rather than silently dropping the consequence.
_OPTIONAL_SAC_ANOTHER_FOR_EFFECT = re.compile(
    r"^you may sacrifice another creature or artifact\. If you do, (.+)$"
)
# "Each opponent discards a card" / "Each opponent discards N cards" —
# untargeted opponent-wide discard (Virus Beetle's ETB and any other
# wide-discard surface). The amount tail accepts the article ``a`` for
# the singular form (Scryfall's printed shape — every EoE card uses
# ``a card``) plus bare digits and spelled-out small cardinals so a
# future ``each opponent discards two cards`` line parses without
# further grammar work. ``a`` collapses to count=1 in the handler.
_EACH_OPPONENT_DISCARDS = re.compile(
    rf"^each opponent discards (a|\d+|{_SMALL_CARDINAL_PATTERN}) cards?$"
)
# "Exile target creature or Spacecraft." — Gravkill's printed surface.
# The static ``cards/eoe_spells.py`` Gravkill entry intentionally fudges
# this to ``ExileTargetCreature()`` because Spacecraft aren't yet a
# legal target type for the engine's exile path; the parser mirrors
# that fudge to stay in parity. When the engine grows a target kind
# that covers Spacecraft, both sides will need to switch in lockstep
# to a Spacecraft-aware engine class.
_EXILE_TARGET_CREATURE_OR_SPACECRAFT = re.compile(
    r"^exile target creature or Spacecraft$"
)
# "Destroy target artifact or tapped creature." — Radiant Strike's
# destroy clause. Maps to ``DestroyTargetArtifactOrTappedCreature()``
# whose ``legal_targets`` filters to artifacts (any) or creatures that
# are currently tapped. The "permanent" target kind is used because
# either an artifact or a creature can be hit; legality is policed by
# the engine class's predicate.
_DESTROY_TARGET_ARTIFACT_OR_TAPPED_CREATURE = re.compile(
    r"^destroy target artifact or tapped creature$"
)
# "Target artifact or creature's owner puts it on their choice of the
# top or bottom of their library." — Lost in Space's bounce-to-library
# clause. Maps to ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOf
# Library()`` whose target kind is ``("permanent", id)`` so artifacts
# (any) and creatures (any) are both legal; the chosen target's owner
# (not the spell's controller) decides top vs bottom at resolution.
_OWNER_PUTS_TARGET_ARTIFACT_OR_CREATURE_ON_TOP_OR_BOTTOM = re.compile(
    r"^target artifact or creature's owner puts it on their choice of "
    r"the top or bottom of their library$"
)
# "Tap target artifact or creature." — Mental Modulation's middle
# clause and any future card that ships the same surface form. Maps to
# ``TapTargetArtifactOrCreature()``. No-op if the chosen target is
# already tapped at resolution.
_TAP_TARGET_ARTIFACT_OR_CREATURE = re.compile(
    r"^tap target artifact or creature$"
)
# "Tap another target creature." — Starport Security's activated
# ability. ``another`` excludes the source creature (reads
# ``state.resolving_source`` to filter). Maps to
# ``TapAnotherTargetCreature()``. No-op if the chosen target is already
# tapped at resolution. Tried as a separate primitive from the
# ``tap target artifact or creature`` shape because the engine class
# differs (creature-only legal pool, source-self exclusion) and the
# surface tail (no ``artifact or`` qualifier, ``another`` self-exclusion
# fragment) is also distinct.
_TAP_ANOTHER_TARGET_CREATURE = re.compile(
    r"^tap another target creature$"
)
# "Tap target artifact or creature an opponent controls and put a stun
# counter on it" — Mechanozoa's ETB. Single primitive (both clauses
# apply to the same target) — the ``and`` in this surface is a
# conjunction within ONE effect, not a compound joiner. Maps to
# ``TapTargetOpponentPermanentAndStunIt()``. The compound-effect
# splitter does try ``and`` first and produces two pieces, but
# neither piece is a recognized standalone effect, so the splitter
# rejects and we fall through to this single-effect regex.
_TAP_TARGET_OPPONENT_PERMANENT_AND_STUN_IT = re.compile(
    r"^tap target artifact or creature an opponent controls "
    r"and put a stun counter on it$"
)
# "Put a stun counter on up to one target tapped creature." — Cryogen
# Relic's activated ability. Maps to the existing
# ``PutStunCounterOnTappedCreature`` engine class whose
# ``legal_targets`` filters the battlefield to currently-tapped
# creatures and whose ``resolve`` is a no-op when no target is chosen
# (the ``up to one`` optionality fizzles cleanly if the pool is empty).
_PUT_STUN_COUNTER_UP_TO_ONE_TAPPED = re.compile(
    r"^put a stun counter on up to one target tapped creature$"
)
# "Discard a card" / "you discard a card" / "you discard N cards" —
# controller-discards. The bare ``discard a card`` surface is what
# appears post-compound-split for ``draw a card, then discard a card``
# (Mechan Navigator's becomes-tapped trigger); the ``you `` prefix
# variant is included for symmetry with ``you gain N life`` /
# ``you lose N life``. Maps to ``DiscardSelf(amount=N)``. ``a``
# collapses to amount=1 in the handler.
_DISCARD_N_CARDS = re.compile(
    rf"^(?:you )?discard (a|\d+|{_SMALL_CARDINAL_PATTERN}) cards?$"
)
# "Untap another target permanent" — Nanoform Sentinel's becomes-tapped
# trigger. The ``another`` qualifier excludes the source permanent from
# the legal target pool — the engine class
# ``UntapTargetOtherPermanent`` reads ``state.resolving_source`` at
# resolve time to filter the chosen target. Maps to
# ``UntapTargetOtherPermanent()`` with no parameters (the engine class's
# semantics fully specify the legal-target predicate).
_UNTAP_ANOTHER_TARGET_PERMANENT = re.compile(
    r"^untap another target permanent$"
)
# "Another target creature you control gets +X/+X until end of turn,
# where X is this creature's power" — Hemosymbic Mite's becomes-tapped
# trigger. The variable-X bonus is fixed at "the source's effective
# power at resolve time" — both the regex and the engine class hardcode
# the source-power semantics; future cards with a different X-source
# (e.g. "where X is the number of artifacts you control") would land
# their own primitive. Maps to
# ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()`` with no
# parameters — every aspect of the effect (target restriction to other
# creatures the controller controls, X-source from
# ``state.resolving_source``) is encoded by the engine class.
_PUMP_OTHER_TARGET_CREATURE_BY_X_OVER_X_SOURCE_POWER = re.compile(
    r"^another target creature you control gets \+X/\+X until end of "
    r"turn, where X is this creature's power$"
)
# "Put a +1/+1 counter on each creature you control other than this
# creature" — Dawnstrike Vanguard's tapped-creatures-gated end-step
# trigger body. Mass +1/+1-counter spread on each creature the
# controller controls except the source itself. Maps to
# ``PutPlusOneCounterOnEachCreatureYouControl(amount=1,
# exclude_source=True)`` — the ``exclude_source=True`` flag reads
# ``state.resolving_source`` at resolve time to skip the source from
# the firing pool. Distinct from the bare ``put a +1/+1 counter on
# each creature you control`` shape (Atmospheric Greenhouse) which
# would be a separate primitive without the ``other than`` tail; no
# EoE creature today prints the bare form, so only the ``other than
# this creature`` variant is wired here.
_PUT_PLUS_ONE_COUNTER_ON_EACH_OTHER_CREATURE_YOU_CONTROL = re.compile(
    r"^put a \+1/\+1 counter on each creature you control other than "
    r"this creature$"
)
# "This creature gets +N/+M until end of turn" — source pumps itself
# (no separate target). Surfaces on Skystinger's block trigger
# ("Whenever this creature blocks a creature with flying, this
# creature gets +5/+0 until end of turn") and the Landfall self-pump
# family (Icecave Crasher +1/+0, Remnant Elemental +2/+0). Both signs
# are accepted in case a future printing self-debuffs (the engine
# class folds positive and negative bonuses through the same path),
# matching the symmetry already documented for the
# ``_PUMP_TARGET_CREATURE_UEOT`` regex above.
#
# Maps to ``PumpSelfUntilEOT(power_bonus=N, toughness_bonus=M)``.
# Distinct from the ``put a +1/+1 counter on this creature`` shape
# (which produces ``PutPlusOneCounterOnSelf``) — counters persist past
# end of turn while the pump bonus clears at cleanup.
_PUMP_SELF_UEOT = re.compile(
    r"^this creature gets ([+-]\d+)/([+-]\d+) until end of turn$"
)
# "Another target creature you control gains <kw>[ and <kw2>...] until
# end of turn." — pure keyword-grant variant with no P/T pump,
# restricted to other creatures the controller controls (Blooming
# Stinger's ETB grants deathtouch to another creature you control).
# Maps to ``PumpTargetCreatureUntilEOT(power_bonus=0, toughness_bonus=0,
# granted_keywords=..., you_control_only=True, exclude_self=True)``.
# Distinct from the existing ``_PUMP_AND_GAIN_KEYWORDS_UEOT`` regex
# which requires a leading ``gets +N/+M and gains`` clause; this one
# is for pure-grant phrases. The granted-keywords body is validated
# against the keyword-line whitelist before the parsed effect is
# returned, mirroring the behavior of the pump-and-gain primitive.
_GRANT_KEYWORDS_TO_ANOTHER_TARGET_CREATURE_YOU_CONTROL_UEOT = re.compile(
    r"^another target creature you control gains (.+) until end of turn$"
)
# "Target artifact or creature gains <kw>[ and <kw2>...] until end of
# turn." — pure keyword-grant on a permanent target whose legal pool
# spans both artifacts and creatures (Reroute Systems mode 0). Maps to
# ``PumpTargetArtifactOrCreatureUntilEOT(granted_keywords=...)`` which
# uses the ``("permanent", id)`` target kind so the chosen permanent
# may be either an artifact (any) or a creature.
#
# No P/T pump captured — the engine class doesn't ship one for this
# surface today (Reroute Systems' +0/+0 default is the only form in
# use). The keyword body is parsed via ``_parse_keyword_grant_body``
# and validated against the keyword-line whitelist; rejection returns
# ``None`` so an unknown keyword keeps the wrapping spell unclaimed.
_PUMP_TARGET_ARTIFACT_OR_CREATURE_GAINS_KEYWORDS_UEOT = re.compile(
    r"^target artifact or creature gains (.+) until end of turn$"
)
# "<source> deals N damage to target tapped creature" — Reroute Systems
# mode 1's tapped-only burn. Maps to ``DealDamageToTargetTappedCreature(
# amount=N)`` whose ``legal_targets`` filters to creatures that are
# currently tapped, with a re-check at resolution in case a between-
# cast-and-resolve untap removes the tapped creature from the legal
# pool. The ``deals`` form (no ``it`` / ``you`` subject) is what
# Scryfall prints for spells that name themselves as the subject; the
# spell-effect normalizer strips the ``<Name>`` prefix before this
# regex sees the phrase, so the surface form here is exactly
# ``deals N damage to target tapped creature``.
_DEAL_DAMAGE_TARGET_TAPPED_CREATURE = re.compile(
    r"^deals (\d+) damage to target tapped creature$"
)
# "Put N charge counters on target Spacecraft or Planet you control" —
# Drill Too Deep mode 0 (and any future card with the same surface).
# Maps to ``PutChargeCountersOnTargetSpacecraftOrPlanetYouControl(amount=
# N)``. Amount is a digit or one of the spelled-out small cardinals
# (Drill Too Deep prints ``Put five charge counters …``); the engine
# class's ``amount`` field is an int either way. The
# ``Spacecraft or Planet`` capitalization is verbatim from the oracle
# text — the spell-effect normalizer only lowercases the first letter
# of the phrase, so inner type-name capitalization survives.
_PUT_CHARGE_COUNTERS_ON_TARGET_SPACECRAFT_OR_PLANET_YOU_CONTROL = re.compile(
    rf"^put (\d+|{_SMALL_CARDINAL_PATTERN}) charge counters on "
    rf"target Spacecraft or Planet you control$"
)
# "Target player mills cards equal to your life total" — Space-Time
# Anomaly's printed form. Maps to
# ``MillTargetPlayer(use_controller_life=True)``. The engine class's
# ``use_controller_life`` flag substitutes the controller's current
# life total for the bare ``amount`` field at resolve time, so no
# numeric capture is needed here — the surface form is a literal
# match.
_MILL_TARGET_PLAYER_EQUAL_TO_YOUR_LIFE = re.compile(
    r"^target player mills cards equal to your life total$"
)
# "Target player mills N cards" — bare-amount mill at a single
# target player. Forward-looking surface form (no EoE card prints
# this exact shape today; Space-Time Anomaly is the variable-amount
# variant above), but the regex is included so a future printing of
# ``target player mills three cards`` parses without further grammar
# work. Tried AFTER the ``equal to your life total`` regex so the
# more-specific shape wins on phrases that carry it.
_MILL_TARGET_PLAYER_N_CARDS = re.compile(
    rf"^target player mills (\d+|{_SMALL_CARDINAL_PATTERN}) cards$"
)
# "Each player creates a <Name> token" — bare-name token-creation
# variant whose subject is each living player (every player creates
# the token under their own control). Surfaces on Edge Rover's
# dies trigger (``each player creates a Lander token``). Maps to
# ``CreateToken(token_printing=..., count=N, each_player=True)``.
# The captured groups mirror the shape of ``_CREATE_BARE_NAME_TOKEN``
# below — count word/digit, optional ``tapped`` slot, and the bare
# subtype name that doubles as the registry key — except the leading
# subject is ``each player creates`` instead of the implicit
# controller-creates default.
_EACH_PLAYER_CREATE_BARE_NAME_TOKEN = re.compile(
    rf"^each player creates ({_TOKEN_COUNT_PATTERN}) (tapped )?"
    rf"([A-Z][A-Za-z]*(?: [A-Z][A-Za-z]*)*) tokens?$"
)
# "Create a Lander token. At the beginning of the end step on your
# next turn, sacrifice that token." — Kav Landseeker's ETB. Single
# primitive that creates a specific Lander then schedules a delayed-
# trigger sac of that exact token at the controller's next end step.
# The two-sentence surface form is captured as a single literal regex
# — the second sentence's ``sacrifice that token`` references the
# token created in the first, so they can't be split into independent
# effects. Tried via the single-effect dispatcher AFTER the compound
# splitter rejects (the splitter tries `` and `` first — there's no
# ``and`` here — and falls through to the sentence-boundary split,
# whose second piece ``at the beginning of the end step on your next
# turn, sacrifice that token`` doesn't standalone-parse, so the
# splitter rejects and the single-effect dispatcher claims the whole
# phrase).
_CREATE_LANDER_AND_SCHEDULE_SAC = re.compile(
    r"^create a Lander token\. "
    r"At the beginning of the end step on your next turn, "
    r"sacrifice that token$"
)


def _parse_keyword_grant_body(body: str) -> frozenset[str] | None:
    """Parse the tail of a pump-and-gain phrase — one or more evergreen
    keywords joined by `` and `` — into the frozenset of engine
    spellings consumed by ``PumpTargetCreatureUntilEOT.granted_keywords``.

    Returns ``None`` if any piece is not a recognized standalone keyword
    so the caller can reject the whole pump-and-gain phrase rather than
    silently dropping a granted ability. Mirrors the keyword-line
    whitelist in ``parser.keywords`` (``_KEYWORD_LINES``) — adding a new
    evergreen keyword there automatically makes it grantable here.
    """
    pieces = [p.strip() for p in body.split(" and ")]
    if not all(p in _KEYWORD_LINES.values() for p in pieces):
        return None
    return frozenset(pieces)


def _parse_amount(token: str) -> int:
    """Convert a Scryfall amount token (digit or spelled-out small
    cardinal) into the integer N. Assumes the token already passed a
    regex that matched either ``\\d+`` or one of
    ``_SMALL_CARDINAL_WORDS``."""
    if token.isdigit():
        return int(token)
    return _SMALL_CARDINAL_WORDS[token]


def _parse_token_count(token: str) -> int:
    """Convert a token-count word into the integer N. Adds the singular
    articles ``a`` / ``an`` (= 1) to ``_parse_amount``'s digit-or-
    spelled-out-cardinal coverage. Assumes the token already passed
    ``_TOKEN_COUNT_PATTERN``."""
    if token in ("a", "an"):
        return 1
    return _parse_amount(token)


def _parse_create_token_effect(phrase: str) -> Effect | None:
    """Try to parse ``phrase`` as a token-creation effect (either the
    stat-bearing creature shape, the bare-name shape, or the
    each-player bare-name shape). Returns ``None`` if no shape
    matches OR if the resolved token name has no ``TOKEN_PRINTINGS``
    entry — the parser doesn't fabricate new token printings on
    the fly.
    """
    m = _CREATE_CREATURE_TOKEN.match(phrase)
    if m is not None:
        count = _parse_token_count(m.group(1))
        tapped = m.group(2) is not None
        # Stats and color word are consumed by the regex but not used
        # to look up the token — the registered ``TOKEN_PRINTINGS``
        # entry is the canonical source of those values. Mismatches
        # between oracle text and registry would be a static-vs-
        # parser parity bug caught downstream.
        subtype = m.group(6)
        if subtype not in TOKEN_PRINTINGS:
            return None
        return CreateToken(
            token_printing=TOKEN_PRINTINGS[subtype],
            count=count,
            tapped=tapped,
        )
    m = _CREATE_BARE_NAME_TOKEN.match(phrase)
    if m is not None:
        count = _parse_token_count(m.group(1))
        tapped = m.group(2) is not None
        name = m.group(3)
        if name not in TOKEN_PRINTINGS:
            return None
        return CreateToken(
            token_printing=TOKEN_PRINTINGS[name],
            count=count,
            tapped=tapped,
        )
    # ``each player creates a <Name> token`` — every living player
    # creates the bare-name token under their own control. Surfaces
    # on Edge Rover's dies trigger. The captured groups mirror the
    # bare-name shape; the only difference is the leading ``each
    # player creates`` subject (instead of the controller-implicit
    # default) and the resulting ``each_player=True`` flag on the
    # produced ``CreateToken`` engine class.
    m = _EACH_PLAYER_CREATE_BARE_NAME_TOKEN.match(phrase)
    if m is not None:
        count = _parse_token_count(m.group(1))
        tapped = m.group(2) is not None
        name = m.group(3)
        if name not in TOKEN_PRINTINGS:
            return None
        return CreateToken(
            token_printing=TOKEN_PRINTINGS[name],
            count=count,
            tapped=tapped,
            each_player=True,
        )
    return None


# Sentence-boundary split for compound effect phrases — period
# followed by whitespace and an uppercase letter, with a negative
# lookahead for ``If you do,`` so the
# ``You may pay/sacrifice/discard {COST}. If you do, …`` family
# stays welded together (the spell-builder splitter applies the same
# guard at the line level; we mirror it here at the effect-phrase
# level so triggered abilities with multi-sentence bodies — e.g.
# Dauntless Scrapbot's ``exile each opponent's graveyard. Create a
# Lander token.`` — split at the right boundary).
_EFFECT_SENTENCE_BOUNDARY = re.compile(r"(?<=\.) (?=[A-Z](?!f you do,))")


def _split_effect_sentences(phrase: str) -> list[str]:
    """Split a normalized effect phrase at internal sentence
    boundaries, preserving the trailing period on the leading piece(s)
    and lowercasing the first letter of each non-leading piece so each
    piece passes back through ``_parse_effect`` in normalized form.

    Returns ``[phrase]`` when no internal sentence boundary exists.
    The leading piece keeps its trailing period (so it can match
    primitives whose surface form ends mid-phrase, like Codecracker
    Hound's ``look at the top two cards of your library. Put one
    into your hand and the other into your graveyard``); we strip the
    trailing period from EVERY piece before returning so each one
    matches the normalized regex shape (no trailing period). The
    embedded period in Codecracker's surface is part of a single
    primitive's literal regex, so its phrase doesn't reach this
    splitter — it claims through the single-effect dispatcher first.
    """
    pieces = _EFFECT_SENTENCE_BOUNDARY.split(phrase)
    if len(pieces) == 1:
        return pieces
    out: list[str] = []
    for i, piece in enumerate(pieces):
        piece = piece.strip()
        if not piece:
            continue
        if piece.endswith("."):
            piece = piece[:-1]
        if i > 0 and piece and piece[0].isupper():
            piece = piece[0].lower() + piece[1:]
        out.append(piece)
    return out


def _parse_compound_effect(phrase: str) -> Effect | None:
    """Try to parse ``phrase`` as a compound effect: two or more
    primitive effects joined by `` and ``, by ``, then ``, or by
    sentence boundary (``. ``).

    Splits on whichever joiner appears (`` and `` is preferred — see
    below), parses each piece via ``_parse_effect``, and returns a
    ``Sequence`` only if EVERY piece parses cleanly. Returns ``None``
    if the phrase contains no recognized joiner, or if any piece
    fails to parse — never falls back to single-effect parsing on the
    original (the caller does that).

    The strict all-or-nothing rule keeps us from accidentally
    consuming joiner-bearing single effects (e.g. the
    ``search your library for an artifact card, reveal it, put it into
    your hand, then shuffle`` artifact-tutor primitive whose ``, then
    `` is part of one effect's surface): if a split-and-parse attempt
    fails on any piece, we punt and let the caller try the single-
    effect grammar on the unsplit phrase. The artifact-tutor primitive
    in particular survives because its ``shuffle`` half doesn't parse
    as a standalone effect, so the ``, then `` split rejects and the
    full-phrase regex wins.

    Joiner precedence: `` and `` is tried first; ``, then `` second;
    sentence-boundary (``. ``) last. The order matters because the
    joiners can co-occur (a future ``draw a card and you gain 1 life,
    then discard a card`` would have both ``and`` and ``, then``) and
    splitting on the leftmost-listed joiner preserves the same
    left-to-right resolve order the engine expects from ``Sequence``
    regardless of which joiner the printing chose. The sentence-
    boundary split is last so single-effect primitives whose regex
    contains an internal period (Codecracker Hound's two-sentence
    look-at-top-two phrase) still match through the single-effect
    dispatcher first; only when that fails AND no other joiner
    applies do we carve at sentence boundaries.

    A compound where two or more sub-effects each require a target is
    also rejected (returns ``None``) — ``Sequence`` only supports a
    single targeting sub-effect (the cast-time target-selection
    pipeline is single-choice). A multi-target spell needs a
    different combinator and isn't claimed by this slice.
    """
    if " and " in phrase:
        pieces = phrase.split(" and ")
    elif ", then " in phrase:
        pieces = phrase.split(", then ")
    elif _EFFECT_SENTENCE_BOUNDARY.search(phrase):
        pieces = _split_effect_sentences(phrase)
        if len(pieces) < 2:
            return None
    else:
        return None
    parsed: list[Effect] = []
    for piece in pieces:
        eff = _parse_effect(piece)
        if eff is None:
            return None
        parsed.append(eff)
    if sum(1 for e in parsed if e.requires_target()) > 1:
        return None
    return Sequence(effects=tuple(parsed))


def _parse_effect(phrase: str) -> Effect | None:
    """Parse a *normalized* effect phrase into an ``Effect``.

    Normalized form has no source-subject prefix, no trailing period,
    and a lowercased first letter — see ``_normalize_*`` helpers below
    for the per-context surface stripping.

    Compound effects (two or more primitives joined by `` and ``) are
    tried first via ``_parse_compound_effect``; if every split-piece
    parses, returns a ``Sequence``. If the compound attempt fails
    (any piece doesn't parse), falls through to the single-effect
    grammar on the original phrase — preserving the ability of a
    single-effect regex to match a phrase that happens to contain
    `` and ``.
    """
    compound = _parse_compound_effect(phrase)
    if compound is not None:
        return compound
    m = _DEAL_DAMAGE_ANY_TARGET.match(phrase)
    if m is not None:
        return DealDamageAnyTarget(amount=int(m.group(1)))
    # ``deals N damage to target creature an opponent controls`` — Nova
    # Hellkite's ETB. Tried BEFORE the bare ``deals N damage to target
    # creature`` regex because the bare regex's ``$`` anchor would not
    # match this surface anyway, but ordering more-specific before
    # more-general is the convention here.
    m = _DEAL_DAMAGE_TARGET_OPPONENT_CREATURE.match(phrase)
    if m is not None:
        return DealDamageToOpponentCreature(amount=int(m.group(1)))
    # ``deals N damage to target opponent`` — Biotech Specialist's
    # sacrifice-an-artifact trigger body. Tried BEFORE the bare
    # ``deals N damage to target creature`` regex because the bare
    # regex's ``$`` anchor on ``target creature`` would not match the
    # ``target opponent`` tail anyway, but ordering more-specific
    # before more-general is the convention here. Maps to
    # ``DealDamageToTargetOpponent(amount=N)`` which gates the legal-
    # target pool to opponents (not the source's controller).
    m = _DEAL_DAMAGE_TARGET_OPPONENT.match(phrase)
    if m is not None:
        return DealDamageToTargetOpponent(amount=int(m.group(1)))
    m = _DEAL_DAMAGE_TARGET_CREATURE.match(phrase)
    if m is not None:
        return DealDamageToTargetCreature(amount=int(m.group(1)))
    # ``deals N damage to each opponent`` — mass-burn opponents (Ruinous
    # Rampage's burn mode). Tried after the targeted ``deals N damage to
    # any target`` / ``… target creature`` regexes because those bind
    # tighter (the ``each opponent`` tail is an exact literal that won't
    # collide with the targeted shapes).
    m = _DEAL_N_DAMAGE_EACH_OPPONENT.match(phrase)
    if m is not None:
        return DealDamageEachOpponent(amount=int(m.group(1)))
    # ``deals N damage to each creature`` — untargeted board-wipe burn
    # (Pyroclasm). Tried after the targeted ``deals N damage to target
    # creature`` regex above because the bare creature form's ``$``
    # anchor wouldn't match the ``each creature`` tail anyway, but
    # ordering more-specific before more-general is the convention here.
    # Maps to the existing ``DealNDamageToEachCreature`` engine class,
    # already exercised inside Lithobraking's reflexive optional-sac
    # sequence and Extinguisher Battleship's ETB sequence in EoE.
    m = _DEAL_N_DAMAGE_EACH_CREATURE.match(phrase)
    if m is not None:
        return DealNDamageToEachCreature(amount=int(m.group(1)))
    # ``deals N damage to target tapped creature`` — Reroute Systems
    # mode 1's tapped-only burn. Tried AFTER the targeted ``deals N
    # damage to target creature`` regex above so the bare creature
    # form wins on phrases without the ``tapped`` qualifier; this
    # more-specific shape only claims phrases that carry the
    # ``tapped`` tail. Maps to ``DealDamageToTargetTappedCreature``
    # whose ``legal_targets`` gates on ``obj.tapped`` and re-checks
    # at resolution.
    m = _DEAL_DAMAGE_TARGET_TAPPED_CREATURE.match(phrase)
    if m is not None:
        return DealDamageToTargetTappedCreature(amount=int(m.group(1)))
    if _DRAW_A_CARD.match(phrase) is not None:
        return DrawCards(amount=1)
    m = _DRAW_N_CARDS.match(phrase)
    if m is not None:
        return DrawCards(amount=int(m.group(1)))
    m = _YOU_GAIN_N_LIFE.match(phrase)
    if m is not None:
        return GainLife(amount=int(m.group(1)))
    # ``put a +1/+1 counter on each of up to N target creatures`` —
    # multi-target counter spread (Weftblade Enhancer). Tried BEFORE
    # the bare-target regex below because the bare regex's ``target
    # creature$`` tail won't match the ``each of up to`` shape anyway,
    # but ordering more-specific before more-general is the convention
    # here. The amount tail accepts digits and spelled-out small
    # cardinals; both go through ``_parse_amount`` to land as the
    # ``max_n`` int on the engine class.
    m = _PUT_PLUS_ONE_COUNTER_ON_EACH_OF_UP_TO_N_TARGET_CREATURES.match(
        phrase
    )
    if m is not None:
        return PutPlusOneCounterOnEachOfUpToNTargetCreatures(
            max_n=_parse_amount(m.group(1)),
        )
    # ``put a +1/+1 counter on target creature you control`` — Rayblade
    # Trooper's ETB. Restricted variant: legal targets are creatures
    # the resolving controller controls. Tried BEFORE the bare ``target
    # creature`` regex (which has a ``$`` anchor and so wouldn't match
    # the ``you control`` tail anyway) so the more-specific shape wins
    # by convention.
    if _PUT_PLUS_ONE_COUNTER_ON_TARGET_CREATURE_YOU_CONTROL.match(
        phrase
    ) is not None:
        return PutPlusOneCounterOnCreatureYouControl(amount=1)
    # ``put a +1/+1 counter on target creature an opponent controls`` —
    # Sunset Saboteur's attack trigger. Mirror image of the ``you
    # control`` restriction above: legal targets are creatures NOT
    # controlled by the resolving controller. Tried BEFORE the bare
    # ``target creature`` regex (which has a ``$`` anchor that
    # wouldn't match this tail anyway) so the more-specific shape wins
    # by convention.
    if _PUT_PLUS_ONE_COUNTER_ON_TARGET_OPPONENT_CREATURE.match(
        phrase
    ) is not None:
        return PutPlusOneCounterOnOpponentsCreature(amount=1)
    if _PUT_PLUS_ONE_COUNTER_ON_TARGET_CREATURE.match(phrase) is not None:
        return PutPlusOneCounterOnTargetCreature(amount=1)
    if _PUT_PLUS_ONE_COUNTER_ON_THIS_CREATURE.match(phrase) is not None:
        return PutPlusOneCounterOnSelf(amount=1)
    # ``put a +1/+1 counter on each creature you control other than
    # this creature`` — Dawnstrike Vanguard's end-step trigger body
    # (gated by the tapped-creatures wrapper at the trigger-line
    # level, but the inner effect is a plain mass-counter spread).
    # Tried BEFORE the bare-target counter regexes because the bare
    # ones all carry a ``$`` anchor on ``target creature`` etc. that
    # wouldn't match the ``each creature`` subject anyway, but
    # ordering more-specific before more-general is the convention
    # here. Maps to ``PutPlusOneCounterOnEachCreatureYouControl(
    # amount=1, exclude_source=True)`` — mirrors the static-registry
    # layout exactly (the ``other than this creature`` tail is what
    # sets the engine class's ``exclude_source`` flag).
    if _PUT_PLUS_ONE_COUNTER_ON_EACH_OTHER_CREATURE_YOU_CONTROL.match(
        phrase
    ) is not None:
        return PutPlusOneCounterOnEachCreatureYouControl(
            amount=1, exclude_source=True,
        )
    # ``destroy target creature or Spacecraft`` — Embrace Oblivion.
    # Tried BEFORE the bare ``destroy target creature`` regex so the
    # Spacecraft-tail variant wins. Both produce the same engine class
    # today (``DestroyTargetCreature``), just with the
    # ``or_spacecraft=True`` flag flipped — the bare regex below would
    # never match this surface anyway (its ``$`` anchor rejects the
    # ``or Spacecraft`` tail) but ordering more-specific before
    # more-general is the convention here.
    if _DESTROY_TARGET_CREATURE_OR_SPACECRAFT.match(phrase) is not None:
        return DestroyTargetCreature(or_spacecraft=True)
    if _PUT_ITS_COUNTERS_ON_TARGET_CREATURE_YOU_CONTROL.match(
        phrase
    ) is not None:
        # ``put its counters on target creature you control`` — Dockworker
        # Drone's dies trigger. ``its`` refers to the source creature
        # (dying permanent); the engine class reads
        # ``state.resolving_source.plus_one_counters`` at resolve time
        # and transfers them to the chosen target.
        return MoveSelfCountersToTargetCreatureYouControl()
    # ``destroy up to one other target creature. If that creature
    # wasn't dealt damage this turn, its controller draws N cards``
    # — Faller's Faithful's ETB. Tried BEFORE the bare destroy regex
    # below so the longer surface wins. The bare regex's ``$`` anchor
    # would never match this surface anyway, but ordering more-
    # specific before more-general is the convention here.
    m = _DESTROY_UP_TO_ONE_OTHER_TARGET_CREATURE_DRAW_IF_UNDAMAGED.match(
        phrase
    )
    if m is not None:
        return DestroyTargetCreature(
            optional=True,
            exclude_self=True,
            draw_if_undamaged_amount=_parse_amount(m.group(1)),
        )
    if _DESTROY_TARGET_CREATURE.match(phrase) is not None:
        return DestroyTargetCreature()
    # ``counter target artifact or enchantment spell`` — Annul. Tried
    # BEFORE the bare ``counter target spell`` regex so the more
    # specific filter-typed shape wins. Both shapes return the same
    # engine class, just with different ``filter_types`` frozensets.
    if _COUNTER_TARGET_ARTIFACT_OR_ENCHANTMENT_SPELL.match(
        phrase
    ) is not None:
        return CounterTargetSpell(
            filter_types=frozenset({"Artifact", "Enchantment"})
        )
    if _COUNTER_TARGET_SPELL.match(phrase) is not None:
        return CounterTargetSpell()
    # ``exile target creature or Spacecraft`` — Gravkill's printed
    # surface. Tried BEFORE the bare ``exile target creature`` regex so
    # the Spacecraft-tail variant wins. Both produce the same engine
    # class today (``ExileTargetCreature()``) — the static side fudges
    # the same way pending engine support for Spacecraft as a target
    # kind. When the engine grows that, this primitive should switch to
    # a Spacecraft-aware engine class in lockstep with the static.
    if _EXILE_TARGET_CREATURE_OR_SPACECRAFT.match(phrase) is not None:
        return ExileTargetCreature()
    if _EXILE_TARGET_CREATURE.match(phrase) is not None:
        return ExileTargetCreature()
    if _EXILE_ALL_CREATURES_AND_SPACECRAFT.match(phrase) is not None:
        return ExileAllCreaturesAndSpacecraft()
    m = _EXILE_ALL_ARTIFACTS_WITH_MANA_VALUE_AT_MOST.match(phrase)
    if m is not None:
        return ExileAllArtifactsWithManaValueAtMost(max_mv=int(m.group(1)))
    if _SEARCH_LIBRARY_FOR_ARTIFACT_CARD.match(phrase) is not None:
        # ``may_fail=True`` mirrors the static Scour-for-Scrap printing —
        # the controller may decline the fetch (and shuffle anyway). No
        # EoE oracle text spells out ``may_fail=False`` for an artifact
        # tutor today; if one ships, gate it on a different surface form.
        return SearchLibraryForCard(
            filter_name="artifact", may_fail=True,
        )
    m = _EACH_OPPONENT_LOSES_N_LIFE.match(phrase)
    if m is not None:
        return EachOpponentLosesLife(amount=int(m.group(1)))
    if _EXILE_EACH_OPPONENTS_GRAVEYARD.match(phrase) is not None:
        # ``exile each opponent's graveyard`` — Dauntless Scrapbot's
        # first-half compound ETB. Untargeted graveyard wipe on every
        # opponent.
        return ExileEachOpponentsGraveyard()
    m = _EACH_OPPONENT_DISCARDS.match(phrase)
    if m is not None:
        # ``each opponent discards a card`` / ``each opponent discards
        # N cards`` — controller-untargeted opponent-wide discard.
        # ``a`` collapses to count=1; digits and spelled-out small
        # cardinals go through ``_parse_amount``.
        token = m.group(1)
        count = 1 if token == "a" else _parse_amount(token)
        return EachOpponentDiscards(count=count)
    # ``create a Lander token. At the beginning of the end step on
    # your next turn, sacrifice that token`` — Kav Landseeker's ETB.
    # Tried BEFORE the bare token-creation dispatcher because the
    # bare ``create a Lander token`` regex would match the first half
    # of this phrase if the compound splitter ran differently, but
    # this single primitive captures the two-sentence body as one
    # effect (the second sentence references the token created in
    # the first, so they can't be split into independent effects).
    if _CREATE_LANDER_AND_SCHEDULE_SAC.match(phrase) is not None:
        return CreateLanderAndScheduleSacrifice()
    token_eff = _parse_create_token_effect(phrase)
    if token_eff is not None:
        return token_eff
    m = _SURVEIL_N.match(phrase)
    if m is not None:
        return Surveil(amount=int(m.group(1)))
    if _LOOK_TOP_TWO_SPLIT_HAND_GRAVEYARD.match(phrase) is not None:
        # ``look at the top two cards of your library. Put one into
        # your hand and the other into your graveyard`` — Codecracker
        # Hound's ETB. The two-sentence surface form is matched as a
        # single primitive; the agent's ``choose_surveil`` hook
        # decides which card goes to which pile at resolve time.
        return LookAtTopTwoSplitHandGraveyard()
    m = _MILL_N_CARDS.match(phrase)
    if m is not None:
        return SelfMill(amount=_parse_amount(m.group(1)))
    if _DESTROY_TARGET_ARTIFACT.match(phrase) is not None:
        return DestroyTargetArtifact()
    if _DESTROY_TARGET_ARTIFACT_ENCHANTMENT_OR_FLYING_CREATURE.match(
        phrase
    ) is not None:
        # ``destroy target artifact, enchantment, or creature with
        # flying`` — Shattered Wings. The engine class's
        # ``legal_targets`` filters to artifacts (any), enchantments
        # (any), or creatures that currently have flying, with a
        # re-check at resolution in case a between-cast-and-resolve
        # ability removes flying. Tried after the bare
        # ``destroy target artifact`` regex would have matched (which
        # this surface text doesn't due to the ``$`` anchor) so the
        # more-specific shape only claims phrases that carry the
        # ``, enchantment, or creature with flying`` tail.
        return DestroyTargetArtifactEnchantmentOrFlyingCreature()
    if _DESTROY_TARGET_LAND.match(phrase) is not None:
        return DestroyTargetLand()
    if _DESTROY_TARGET_NONCREATURE_PERMANENT.match(phrase) is not None:
        return DestroyTargetNoncreaturePermanent()
    if _DESTROY_TARGET_NONLAND_PERMANENT.match(phrase) is not None:
        # ``destroy target nonland permanent`` — Thaumaton Torpedo's
        # activated ability. Tried after ``destroy target noncreature
        # permanent`` because the two surface forms are disjoint
        # (different exclusion words), but ordering more-specific before
        # more-general is the convention here. Maps to
        # ``DestroyTargetNonlandPermanent`` whose ``legal_targets``
        # filters the battlefield to permanents that aren't lands.
        return DestroyTargetNonlandPermanent()
    if _DESTROY_TARGET_ARTIFACT_OR_TAPPED_CREATURE.match(phrase) is not None:
        # ``destroy target artifact or tapped creature`` — Radiant
        # Strike's destroy clause. The engine class's
        # ``legal_targets`` filters to artifacts (any) plus creatures
        # currently tapped, and re-checks the predicate at resolution
        # in case a between-cast-and-resolve untap removes the tapped
        # creature from the legal pool. Tried after the bare
        # ``destroy target artifact`` regex would have matched (which
        # this surface text doesn't) so the more-specific shape only
        # claims phrases that actually carry the ``or tapped
        # creature`` tail.
        return DestroyTargetArtifactOrTappedCreature()
    # ``tap another target creature`` — Starport Security's activated
    # ability. Tried BEFORE the ``tap target artifact or creature``
    # regex below because the bare regex's ``$`` anchor wouldn't match
    # the ``another`` qualifier anyway, but ordering more-specific
    # before more-general is the convention here.
    if _TAP_ANOTHER_TARGET_CREATURE.match(phrase) is not None:
        return TapAnotherTargetCreature()
    if _TAP_TARGET_ARTIFACT_OR_CREATURE.match(phrase) is not None:
        # ``tap target artifact or creature`` — Mental Modulation's
        # middle clause and any future card with the same surface.
        # No-op if the chosen target is already tapped at resolution.
        return TapTargetArtifactOrCreature()
    if _TAP_TARGET_OPPONENT_PERMANENT_AND_STUN_IT.match(phrase) is not None:
        # ``tap target artifact or creature an opponent controls and
        # put a stun counter on it`` — Mechanozoa's ETB. Both clauses
        # apply to the same chosen target — the ``and`` is an
        # intra-effect conjunction, not a compound joiner.
        return TapTargetOpponentPermanentAndStunIt()
    if _PUT_STUN_COUNTER_UP_TO_ONE_TAPPED.match(phrase) is not None:
        # ``put a stun counter on up to one target tapped creature`` —
        # Cryogen Relic's activated payload. ``up to one`` resolves as
        # a no-op fizzle when no legal target is chosen; the engine
        # class's ``legal_targets`` filters to currently-tapped
        # creatures.
        return PutStunCounterOnTappedCreature()
    if _UNTAP_ANOTHER_TARGET_PERMANENT.match(phrase) is not None:
        # ``untap another target permanent`` — Nanoform Sentinel's
        # becomes-tapped trigger body. The ``another`` qualifier
        # excludes the source from the legal target pool — encoded
        # by the engine class's reading of ``state.resolving_source``
        # at resolve time, not by a parser-level flag. Maps to
        # ``UntapTargetOtherPermanent()`` with no parameters.
        return UntapTargetOtherPermanent()
    if _OWNER_PUTS_TARGET_ARTIFACT_OR_CREATURE_ON_TOP_OR_BOTTOM.match(
        phrase
    ) is not None:
        # ``target artifact or creature's owner puts it on their
        # choice of the top or bottom of their library`` — Lost in
        # Space's bounce-to-library clause. The chosen target's
        # owner decides top vs bottom at resolution (not the
        # spell's controller). Maps to the engine class with no
        # parameters — the surface form is a literal match.
        return OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary()
    # ``add {<mana>}. Spend this mana only to <restriction>`` —
    # restricted-mana ability (Steelswarm Operator). Tried BEFORE the
    # bare ``add {<color>}`` regex so the qualifier wins; the bare
    # regex's ``$`` anchor wouldn't match the multi-sentence shape
    # anyway, but ordering more-specific before more-general is the
    # convention here. The mana segment is parsed by inspecting the
    # captured brace expression — the regex enforces that it's exactly
    # one or two same-color brace pairs but doesn't decompose them
    # into engine coins, so we extract the colors directly.
    m = _ADD_MANA_WITH_SPEND_RESTRICTION.match(phrase)
    if m is not None:
        mana_str = m.group(1)
        restriction = _SPEND_RESTRICTION_BY_PHRASE[m.group(2)]
        # The mana segment is one or two ``{<color>}`` brace pairs;
        # ``parse_mana_cost`` would unpack them but for restricted-mana
        # abilities the engine wants a tuple of single-coin entries
        # (one ``(color, 1)`` per coin minted), so we walk the brace
        # pairs directly.
        colors = re.findall(r"\{([WUBRG])\}", mana_str)
        return AddManaToPool(
            produces=tuple((c, 1) for c in colors),
            spend_restriction=restriction,
        )
    m = _ADD_TWO_SAME_COLOR_MANA.match(phrase)
    if m is not None:
        # Two same-color coin shape (``add {U}{U}``) — only same-color
        # pairs reach this regex (the inner brace pattern captures both
        # letters and we reject mismatched pairs to keep the engine's
        # produced tuple simple). A mismatched pair like
        # ``add {U}{R}`` falls through to the bare single-color regex
        # and fails its anchor, so the card stays unclaimed (no EoE
        # printing today uses dual-color two-coin add anyway).
        if m.group(1) != m.group(2):
            return None
        c = m.group(1)
        return AddManaToPool(produces=((c, 1), (c, 1)))
    m = _ADD_SINGLE_COLOR_MANA.match(phrase)
    if m is not None:
        return AddManaToPool(produces=((m.group(1), 1),))
    if _ADD_ONE_MANA_OF_ANY_COLOR.match(phrase) is not None:
        # ``add one mana of any color`` — at-resolution choose-color
        # mana ability. Mints a single ``("any", 1)`` coin; the engine
        # prompts the controller to name the color at resolution. Same
        # production tuple ``land_builder`` builds for Mana Confluence.
        return AddManaToPool(produces=(("any", 1),))
    m = _TARGET_OPPONENT_LOSES_N_LIFE.match(phrase)
    if m is not None:
        return TargetOpponentLosesLife(amount=int(m.group(1)))
    if _RETURN_UP_TO_ONE_OTHER_PERMANENT_YOU_CONTROL_TO_OWNERS_HAND.match(
        phrase
    ) is not None:
        # ``return up to one other target permanent you control to its
        # owner's hand`` — Exosuit Savior's ETB. ``up to one`` →
        # ``optional=True`` (resolves as a no-op if no target chosen);
        # ``other`` → ``exclude_self=True`` (filters the trigger source
        # via ``state.resolving_source``).
        return ReturnTargetPermanentYouControlToOwnersHand(
            optional=True, exclude_self=True,
        )
    if _RETURN_TARGET_CREATURE_GRAVEYARD_TO_HAND.match(phrase) is not None:
        return ReturnCreatureFromYourGraveyardToHand()
    # Xu-Ifit, Osteoharmonist's reanimate-as-Skeleton multi-sentence
    # surface drops the ``has no abilities`` rider per the static-side
    # simplification — same engine class as the bare reanimate regex
    # but with its own pattern so the simplification stays local and
    # explicit.
    if _RETURN_TARGET_CREATURE_GRAVEYARD_TO_BATTLEFIELD_AS_SKELETON.match(
        phrase
    ) is not None:
        return ReturnCreatureFromYourGraveyardToBattlefield()
    if _RETURN_TARGET_CREATURE_GRAVEYARD_TO_BATTLEFIELD.match(
        phrase
    ) is not None:
        return ReturnCreatureFromYourGraveyardToBattlefield()
    if _RETURN_TARGET_ARTIFACT_GRAVEYARD_TO_HAND.match(phrase) is not None:
        return ReturnTargetArtifactCardFromYourGraveyardToHand()
    # ``put target card from a graveyard on the bottom of its owner's
    # library`` — Chrome Companion's tap-mana activated ability. Untyped
    # grave-target across all players; resolution moves the chosen card
    # to the bottom of its owner's library. Maps to the existing
    # ``PutCardFromGraveyardOnBottomOfLibrary`` engine class — same
    # primitive the static registry uses for Chrome Companion today, so
    # parser/static parity holds out of the box.
    if _PUT_CARD_FROM_GRAVEYARD_ON_BOTTOM_OF_LIBRARY.match(
        phrase
    ) is not None:
        return PutCardFromGraveyardOnBottomOfLibrary()
    # Pump + grant-keywords compound is tried BEFORE the bare-pump
    # regex so a phrase like ``+3/+0 and gains first strike and reach
    # until end of turn`` produces the keyword-bearing
    # ``PumpTargetCreatureUntilEOT``. The bare-pump regex below would
    # never match this surface (it requires the stats to be directly
    # followed by ``until end of turn``), but ordering more-specific
    # before more-general is the convention in this dispatcher.
    m = _PUMP_AND_GAIN_KEYWORDS_UEOT.match(phrase)
    if m is not None:
        keywords = _parse_keyword_grant_body(m.group(4))
        if keywords is None:
            return None
        return PumpTargetCreatureUntilEOT(
            power_bonus=int(m.group(2)),
            toughness_bonus=int(m.group(3)),
            granted_keywords=keywords,
            you_control_only=m.group(1) is not None,
        )
    # ``target creature an opponent controls gets ±N/±M until end of
    # turn`` — opponent-controlled-only debuff/pump (Sinister
    # Cryologist's ETB). Tried BEFORE the bare-pump regex because that
    # bare regex's tail (``until end of turn$``) would never match
    # phrases with the ``an opponent controls`` qualifier in the
    # subject anyway, but ordering more-specific before more-general
    # is the convention here.
    m = _PUMP_TARGET_OPPONENT_CREATURE_UEOT.match(phrase)
    if m is not None:
        return PumpTargetCreatureUntilEOT(
            power_bonus=int(m.group(1)),
            toughness_bonus=int(m.group(2)),
            opponents_only=True,
        )
    # ``target creature you control gets ±N/±M until end of turn`` —
    # you-control-only single-target pump (Zookeeper Mechan's ``{6}{R}``
    # sorcery-speed activated ability). Tried BEFORE the bare
    # ``target creature gets … UEOT`` regex so the ``you control``
    # qualifier wins; the bare regex's ``$`` anchor wouldn't match the
    # qualifier anyway, but ordering more-specific before more-general
    # is the convention here.
    m = _PUMP_TARGET_CREATURE_YOU_CONTROL_UEOT.match(phrase)
    if m is not None:
        return PumpTargetCreatureUntilEOT(
            power_bonus=int(m.group(1)),
            toughness_bonus=int(m.group(2)),
            you_control_only=True,
        )
    # ``up to one target creature gets ±N/±M until end of turn`` —
    # optional pump/debuff (Dubious Delicacy's ETB ``-3/-3``). The
    # ``up to one`` qualifier flips the engine class's
    # ``target_count_range`` to ``(0, 1)`` and ``requires_target`` to
    # False, so a no-target resolution is a clean no-op rather than a
    # fizzle. Tried BEFORE the bare-pump regex because that bare regex's
    # ``$`` anchor wouldn't match the ``up to one`` prefix anyway, but
    # ordering more-specific before more-general is the convention here.
    m = _PUMP_UP_TO_ONE_TARGET_CREATURE_UEOT.match(phrase)
    if m is not None:
        return PumpTargetCreatureUntilEOT(
            power_bonus=int(m.group(1)),
            toughness_bonus=int(m.group(2)),
            optional=True,
        )
    if _DOUBLE_TARGET_CREATURE_YOU_CONTROL_POWER_UEOT.match(
        phrase
    ) is not None:
        # ``double the power of target creature you control until end
        # of turn`` — Mightform Harmonizer's landfall trigger. Distinct
        # from the bare ``gets +N/+0`` pump shapes above: the bonus is
        # computed at resolve time from the target's current power
        # rather than a fixed constant. Maps to the engine class with
        # no parameters — the surface form is a literal match.
        return DoubleTargetCreaturesPowerUEOT()
    m = _PUMP_TARGET_CREATURE_UEOT.match(phrase)
    if m is not None:
        return PumpTargetCreatureUntilEOT(
            power_bonus=int(m.group(1)),
            toughness_bonus=int(m.group(2)),
        )
    # ``[other ]creatures you control get ±N/±M[ and gain <kw>...]
    # until end of turn`` — anthem-style mass pump on every creature
    # the controller controls, with optional source-self exclusion
    # (``other``) and optional grant-keywords rider. The bare form is
    # Dual-Sun Adepts' ``{5}`` activated ability; the
    # exclude-source-and-grant-keywords form is Syr Vondam, the
    # Lucent's enters/attacks trigger ("other creatures you control
    # get +1/+0 and gain deathtouch until end of turn"). An
    # unrecognized granted-keyword body rejects the whole phrase
    # (returns ``None`` so the caller can fall through) — mirrors the
    # ``_PUMP_AND_GAIN_KEYWORDS_UEOT`` precedent: a missing grant is
    # never silently dropped.
    m = _PUMP_YOUR_CREATURES_UEOT.match(phrase)
    if m is not None:
        granted_body = m.group(4)
        granted_keywords: frozenset[str] = frozenset()
        if granted_body is not None:
            parsed_keywords = _parse_keyword_grant_body(granted_body)
            if parsed_keywords is None:
                return None
            granted_keywords = parsed_keywords
        return PumpCreaturesYouControlUntilEOT(
            power_bonus=int(m.group(2)),
            toughness_bonus=int(m.group(3)),
            exclude_source=m.group(1) is not None,
            granted_keywords=granted_keywords,
        )
    # ``creatures your opponents control get ±N/±M until end of turn`` /
    # ``... until your next turn`` — mass debuff/pump on every creature
    # an opponent controls (Mouth of the Storm's ETB uses the
    # ``until your next turn`` tail). The ``until_caster_next_turn``
    # flag flips when the tail matches the longer-duration form;
    # otherwise the bonus clears at the casting turn's cleanup.
    m = _PUMP_OPPONENT_CREATURES_UEOT.match(phrase)
    if m is not None:
        return PumpCreaturesOpponentsControlUntilEOT(
            power_bonus=int(m.group(1)),
            toughness_bonus=int(m.group(2)),
            until_caster_next_turn=(m.group(3) == "your next turn"),
        )
    # ``this creature gets +N/+M until end of turn`` — source pumps
    # itself UEOT. Tried AFTER the targeted ``target creature gets …
    # UEOT`` regex above because the ``this creature`` subject is a
    # different (source-self) primitive from a targeted bonus. Both
    # signs accepted, mirroring the symmetry of the targeted variant.
    m = _PUMP_SELF_UEOT.match(phrase)
    if m is not None:
        return PumpSelfUntilEOT(
            power_bonus=int(m.group(1)),
            toughness_bonus=int(m.group(2)),
        )
    # ``another target creature you control gets +X/+X until end of
    # turn, where X is this creature's power`` — Hemosymbic Mite's
    # becomes-tapped trigger body. Variable-X bonus where X is fixed
    # to the source's effective power at resolve time; the engine
    # class ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower``
    # reads ``state.resolving_source.power`` and applies the bonus
    # symmetrically (P/T both gain the same X) to the chosen target,
    # which must be a creature the source's controller controls and
    # not be the source itself. Maps to the engine class with no
    # parameters — every aspect of the effect is encoded by the
    # class. Future "where X is …" forms with a different scaling
    # source (e.g. number of artifacts you control) would land their
    # own primitive rather than parameterizing this one.
    if _PUMP_OTHER_TARGET_CREATURE_BY_X_OVER_X_SOURCE_POWER.match(
        phrase
    ) is not None:
        return PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()
    # ``another target creature you control gains <kw>[ and <kw2>...]
    # until end of turn`` — pure keyword grant to another creature you
    # control (Blooming Stinger's ETB grants deathtouch). No P/T pump
    # — only the keyword grant fires. Validated against the keyword-
    # line whitelist via ``_parse_keyword_grant_body``; rejection
    # returns ``None`` so an unknown keyword keeps the wrapping card
    # unclaimed rather than silently dropping the grant.
    m = _GRANT_KEYWORDS_TO_ANOTHER_TARGET_CREATURE_YOU_CONTROL_UEOT.match(
        phrase
    )
    if m is not None:
        keywords = _parse_keyword_grant_body(m.group(1))
        if keywords is None:
            return None
        return PumpTargetCreatureUntilEOT(
            power_bonus=0,
            toughness_bonus=0,
            granted_keywords=keywords,
            you_control_only=True,
            exclude_self=True,
        )
    # ``target artifact or creature gains <kw>[ and <kw2>...] until
    # end of turn`` — pure keyword grant on a permanent target whose
    # legal pool spans both artifacts and creatures (Reroute Systems
    # mode 0 grants indestructible). Maps to
    # ``PumpTargetArtifactOrCreatureUntilEOT(granted_keywords=...)``.
    # Validated against the keyword-line whitelist; rejection returns
    # ``None`` so an unknown keyword keeps the wrapping spell
    # unclaimed rather than silently dropping the grant.
    m = _PUMP_TARGET_ARTIFACT_OR_CREATURE_GAINS_KEYWORDS_UEOT.match(phrase)
    if m is not None:
        keywords = _parse_keyword_grant_body(m.group(1))
        if keywords is None:
            return None
        return PumpTargetArtifactOrCreatureUntilEOT(
            granted_keywords=keywords,
        )
    m = _PUT_CHARGE_COUNTERS_ON_TARGET_SPACECRAFT_OR_PLANET_YOU_CONTROL.match(
        phrase
    )
    if m is not None:
        # ``put N charge counters on target Spacecraft or Planet you
        # control`` — Drill Too Deep mode 0 and any future card with
        # the same surface. Amount is a digit or one of the spelled-out
        # small cardinals; both go through ``_parse_amount`` to land
        # as an int on the engine class's ``amount`` field.
        return PutChargeCountersOnTargetSpacecraftOrPlanetYouControl(
            amount=_parse_amount(m.group(1)),
        )
    if _MILL_TARGET_PLAYER_EQUAL_TO_YOUR_LIFE.match(phrase) is not None:
        # ``target player mills cards equal to your life total`` —
        # Space-Time Anomaly. Maps to the engine class's
        # ``use_controller_life=True`` flag, which substitutes the
        # controller's current life total for the bare amount at
        # resolve time. Tried BEFORE the bare-amount mill regex so
        # the more-specific shape wins; the bare-amount form would
        # never match this surface anyway (its tail is a digit) but
        # ordering more-specific before more-general is the
        # convention here.
        return MillTargetPlayer(use_controller_life=True)
    m = _MILL_TARGET_PLAYER_N_CARDS.match(phrase)
    if m is not None:
        # ``target player mills N cards`` — bare-amount targeted
        # mill. Forward-looking surface form (no EoE card prints
        # this exact shape today; Space-Time Anomaly uses the
        # variable form above), but the regex accepts digits and
        # spelled-out small cardinals so a future printing parses
        # without further grammar work.
        return MillTargetPlayer(amount=_parse_amount(m.group(1)))
    m = _LOSE_N_LIFE.match(phrase)
    if m is not None:
        return LoseLife(amount=int(m.group(1)))
    m = _DISCARD_N_CARDS.match(phrase)
    if m is not None:
        # ``discard a card`` / ``you discard a card`` / ``discard N
        # cards`` — controller-discards. Surfaces inside compound
        # ``draw a card, then discard a card`` (Mechan Navigator) and
        # any future card that prints a bare discard clause. ``a``
        # collapses to amount=1; digits and spelled-out small
        # cardinals go through ``_parse_amount``.
        token = m.group(1)
        amount = 1 if token == "a" else _parse_amount(token)
        return DiscardSelf(amount=amount)
    m = _YOU_MAY_PAY_THEN_EFFECT.match(phrase)
    if m is not None:
        # Parse the inner-effect phrase recursively. The inner phrase is
        # already in normalized form (lowercased first letter doesn't
        # apply here — Scryfall prints "If you do, <lowercase-inner>"
        # because the inner is a sub-clause, not a sentence start). If
        # the inner doesn't parse, the whole "you may pay …" line
        # rejects so the wrapping card stays unclaimed (rather than
        # silently dropping the consequence).
        inner = _parse_effect(m.group(2))
        if inner is None:
            return None
        return OptionalManaCostThenEffect(
            cost_str=m.group(1), inner_effect=inner,
        )
    m = _OPTIONAL_DISCARD_THEN_DRAW.match(phrase)
    if m is not None:
        # ``draw a card`` / ``draw N cards`` / ``draw <word> cards`` —
        # ``a`` collapses to 1, digits and spelled-out small cardinals
        # go through ``_parse_amount``.
        token = m.group(1)
        amount = 1 if token == "a" else _parse_amount(token)
        return OptionalDiscardCardThenDrawN(amount=amount)
    m = _OPTIONAL_DISCARD_HAND_THEN_DRAW.match(phrase)
    if m is not None:
        # ``you may discard your hand. If you do, draw N cards`` —
        # Vaultguard Trooper's tapped-creatures-gated end-step trigger
        # body. Distinct from the single-card discard above: discards
        # the WHOLE hand, not a single chosen card. Tried AFTER the
        # ``discard a card`` regex above because the two surface forms
        # are disjoint (``a card`` vs ``your hand`` are non-overlapping
        # tails) but ordering ``discard a card`` first matches the
        # convention of bare-shape-before-variant that the rest of
        # this dispatcher follows.
        token = m.group(1)
        amount = 1 if token == "a" else _parse_amount(token)
        return DiscardHandThenDrawN(amount=amount)
    m = _OPTIONAL_SAC_ANOTHER_FOR_PUMP_SELF_UEOT.match(phrase)
    if m is not None:
        # More-specific shape (self-pump consequence) — produces the
        # specialized ``OptionalSacAnotherForPumpSelfUEOT`` engine
        # class. Tried BEFORE the general optional-sac regex below.
        return OptionalSacAnotherForPumpSelfUEOT(
            power_bonus=int(m.group(1)),
            toughness_bonus=int(m.group(2)),
        )
    m = _OPTIONAL_SAC_ANOTHER_FOR_EFFECT.match(phrase)
    if m is not None:
        # Generic optional-sac wrapper. The inner consequence is parsed
        # recursively via the unified grammar; if the inner doesn't
        # parse, the whole line rejects so the wrapping card stays
        # unclaimed rather than silently dropping the consequence.
        inner = _parse_effect(m.group(1))
        if inner is None:
            return None
        return OptionalSacAnotherForEffect(inner_effect=inner)
    return None


def _normalize_creature_effect_phrase(phrase: str) -> str:
    """Strip the ``it`` source-subject pronoun if present, leaving the
    normalized phrase ready for ``_parse_effect``."""
    phrase = phrase.strip()
    if phrase.startswith("it "):
        phrase = phrase[len("it "):]
    return phrase


def _normalize_spell_effect_phrase(phrase: str, name: str) -> str:
    """Strip the ``<Name>`` source-subject prefix (if present), trailing
    period, and lowercase the first letter — leaving the normalized
    phrase ready for ``_parse_effect``."""
    phrase = phrase.strip()
    if phrase.endswith("."):
        phrase = phrase[:-1]
    prefix = name + " "
    if phrase.startswith(prefix):
        phrase = phrase[len(prefix):]
    if phrase and phrase[0].isupper():
        phrase = phrase[0].lower() + phrase[1:]
    return phrase


def _parse_effect_phrase(phrase: str) -> Effect | None:
    """Parse a creature-triggered-ability effect phrase. Surface form
    is ``it deals N damage…`` / ``draw a card`` / etc. Delegates to
    the unified ``_parse_effect`` after stripping the ``it`` prefix."""
    return _parse_effect(_normalize_creature_effect_phrase(phrase))


def _parse_spell_effect_phrase(phrase: str, name: str) -> Effect | None:
    """Parse a spell's full-sentence effect text.

    ``phrase`` is one sentence (period included) of oracle text. ``name``
    is the card's own name and is stripped if it appears as the subject.
    Delegates to the unified ``_parse_effect`` after normalization, so
    every effect available to creature triggered abilities is also
    available to spells (and vice versa).
    """
    return _parse_effect(_normalize_spell_effect_phrase(phrase, name))
