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
    CreateToken,
    DealDamageAnyTarget,
    DealDamageEachOpponent,
    DealDamageToOpponentCreature,
    DealDamageToTargetCreature,
    DealDamageToTargetTappedCreature,
    DestroyTargetArtifact,
    DestroyTargetArtifactEnchantmentOrFlyingCreature,
    DestroyTargetArtifactOrTappedCreature,
    DestroyTargetCreature,
    DestroyTargetLand,
    DestroyTargetNoncreaturePermanent,
    DiscardSelf,
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
    PumpSelfUntilEOT,
    PumpTargetArtifactOrCreatureUntilEOT,
    PumpTargetCreatureUntilEOT,
    PutChargeCountersOnTargetSpacecraftOrPlanetYouControl,
    PutPlusOneCounterOnCreatureYouControl,
    PutPlusOneCounterOnEachOfUpToNTargetCreatures,
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
    TapTargetArtifactOrCreature,
    TargetOpponentLosesLife,
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
_DRAW_A_CARD = re.compile(r"^draw a card$")
_DRAW_N_CARDS = re.compile(r"^draw (\d+) cards$")
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
_DEAL_N_DAMAGE_EACH_OPPONENT = re.compile(
    r"^deals (\d+) damage to each opponent$"
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
# "Add {<color>}." — single coin of a single color. Mana ability surface
# form. The captured letter is one of WUBRG (no colorless single-coin
# add in EoE today; extend to ``[WUBRGC]`` if a future card needs it).
# Note: this returns a bare AddManaToPool effect; the surrounding
# ActivatedAbility built by the activated-grammar layer doesn't yet
# auto-flag ``is_mana_ability=True`` — wiring that up is a separate
# concern. Today no EoE card becomes parser-claimed solely by this
# addition (Zookeeper Mechan / Steelswarm Operator both have a second
# line the parser can't yet handle), so static-vs-parser parity is
# unaffected.
_ADD_SINGLE_COLOR_MANA = re.compile(r"^add \{([WUBRG])\}$")
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
# "Return target artifact card from your graveyard to your hand" —
# matches Scour for Scrap's mode (parsed via the modal combinator
# elsewhere, but a primitive worth surfacing in the unified grammar).
_RETURN_TARGET_ARTIFACT_GRAVEYARD_TO_HAND = re.compile(
    r"^return target artifact card from your graveyard to your hand$"
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
    if _PUT_PLUS_ONE_COUNTER_ON_TARGET_CREATURE.match(phrase) is not None:
        return PutPlusOneCounterOnTargetCreature(amount=1)
    if _PUT_PLUS_ONE_COUNTER_ON_THIS_CREATURE.match(phrase) is not None:
        return PutPlusOneCounterOnSelf(amount=1)
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
    if _TAP_TARGET_ARTIFACT_OR_CREATURE.match(phrase) is not None:
        # ``tap target artifact or creature`` — Mental Modulation's
        # middle clause and any future card with the same surface.
        # No-op if the chosen target is already tapped at resolution.
        return TapTargetArtifactOrCreature()
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
    m = _ADD_SINGLE_COLOR_MANA.match(phrase)
    if m is not None:
        return AddManaToPool(produces=((m.group(1), 1),))
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
    if _RETURN_TARGET_CREATURE_GRAVEYARD_TO_BATTLEFIELD.match(
        phrase
    ) is not None:
        return ReturnCreatureFromYourGraveyardToBattlefield()
    if _RETURN_TARGET_ARTIFACT_GRAVEYARD_TO_HAND.match(phrase) is not None:
        return ReturnTargetArtifactCardFromYourGraveyardToHand()
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
    m = _PUMP_TARGET_CREATURE_UEOT.match(phrase)
    if m is not None:
        return PumpTargetCreatureUntilEOT(
            power_bonus=int(m.group(1)),
            toughness_bonus=int(m.group(2)),
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
