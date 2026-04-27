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
    DealDamageToTargetCreature,
    DestroyTargetArtifact,
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
    ExileTargetCreature,
    GainLife,
    LoseLife,
    OptionalDiscardCardThenDrawN,
    OptionalManaCostThenEffect,
    OptionalSacAnotherForEffect,
    OptionalSacAnotherForPumpSelfUEOT,
    PumpTargetCreatureUntilEOT,
    PutPlusOneCounterOnSelf,
    PutPlusOneCounterOnTargetCreature,
    ReturnCreatureFromYourGraveyardToBattlefield,
    ReturnCreatureFromYourGraveyardToHand,
    ReturnTargetArtifactCardFromYourGraveyardToHand,
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
_DRAW_A_CARD = re.compile(r"^draw a card$")
_DRAW_N_CARDS = re.compile(r"^draw (\d+) cards$")
_YOU_GAIN_N_LIFE = re.compile(r"^you gain (\d+) life$")
_PUT_PLUS_ONE_COUNTER_ON_TARGET_CREATURE = re.compile(
    r"^put a \+1/\+1 counter on target creature$"
)
_PUT_PLUS_ONE_COUNTER_ON_THIS_CREATURE = re.compile(
    r"^put a \+1/\+1 counter on this creature$"
)
_DESTROY_TARGET_CREATURE = re.compile(r"^destroy target creature$")
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
# Mill is "mill <amount> cards" where the amount is either a digit or
# one of the spelled-out small cardinals (Scryfall printing convention).
# Singular "mill 1 card" / "mill one card" is intentionally unsupported
# — no EoE card prints that surface form. Add it the day one ships.
_MILL_N_CARDS = re.compile(
    rf"^mill (\d+|{_SMALL_CARDINAL_PATTERN}) cards$"
)
_DESTROY_TARGET_ARTIFACT = re.compile(r"^destroy target artifact$")
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
    stat-bearing creature shape or the bare-name shape). Returns
    ``None`` if neither shape matches OR if the resolved token name
    has no ``TOKEN_PRINTINGS`` entry — the parser doesn't fabricate
    new token printings on the fly.
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
    return None


def _parse_compound_effect(phrase: str) -> Effect | None:
    """Try to parse ``phrase`` as a compound effect: two or more
    primitive effects joined by `` and `` or by ``, then ``.

    Splits on whichever joiner appears (`` and `` is preferred — see
    below), parses each piece via ``_parse_effect``, and returns a
    ``Sequence`` only if EVERY piece parses cleanly. Returns ``None``
    if the phrase contains neither joiner, or if any piece fails to
    parse — never falls back to single-effect parsing on the original
    (the caller does that).

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

    Joiner precedence: `` and `` is tried first; only if that joiner
    is absent do we attempt a `` , then `` split. The order matters
    because the two joiners can co-occur (a future ``draw a card and
    you gain 1 life, then discard a card`` would have both) and
    splitting on the leftmost-occurring joiner preserves the same
    left-to-right resolve order the engine expects from ``Sequence``
    regardless of which joiner the printing chose.

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
    if _DRAW_A_CARD.match(phrase) is not None:
        return DrawCards(amount=1)
    m = _DRAW_N_CARDS.match(phrase)
    if m is not None:
        return DrawCards(amount=int(m.group(1)))
    m = _YOU_GAIN_N_LIFE.match(phrase)
    if m is not None:
        return GainLife(amount=int(m.group(1)))
    if _PUT_PLUS_ONE_COUNTER_ON_TARGET_CREATURE.match(phrase) is not None:
        return PutPlusOneCounterOnTargetCreature(amount=1)
    if _PUT_PLUS_ONE_COUNTER_ON_THIS_CREATURE.match(phrase) is not None:
        return PutPlusOneCounterOnSelf(amount=1)
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
    m = _MILL_N_CARDS.match(phrase)
    if m is not None:
        return SelfMill(amount=_parse_amount(m.group(1)))
    if _DESTROY_TARGET_ARTIFACT.match(phrase) is not None:
        return DestroyTargetArtifact()
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
    m = _ADD_SINGLE_COLOR_MANA.match(phrase)
    if m is not None:
        return AddManaToPool(produces=((m.group(1), 1),))
    m = _TARGET_OPPONENT_LOSES_N_LIFE.match(phrase)
    if m is not None:
        return TargetOpponentLosesLife(amount=int(m.group(1)))
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
    m = _PUMP_TARGET_CREATURE_UEOT.match(phrase)
    if m is not None:
        return PumpTargetCreatureUntilEOT(
            power_bonus=int(m.group(1)),
            toughness_bonus=int(m.group(2)),
        )
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
