"""Artifact - Spacecraft ``CardPrinting`` builder.

Spacecraft are an Edge of Eternities-only card type printed as
``Artifact - Spacecraft``. They enter as non-creature artifacts and
become artifact creatures with a printed ``power``/``toughness`` and
a set of stationed keywords once they accumulate a printed number of
charge counters via the ``Station`` ability. The static registry
models them through ``make_spacecraft(name, cost, power, toughness,
station_threshold, stationed_keywords, ...)``.

The printed oracle text follows a uniform skeleton:

- One ``Station (Tap another creature you control: Put charge counters
  equal to its power on this Spacecraft. Station only as a sorcery.
  It's an artifact creature at <N>+.)`` line. The ``<N>`` here is
  always the same number that gates the highest tier-keyword line and
  also the engine's ``station_threshold``.
- Zero or more "tier" lines of the form ``"<N>+ | <body>"``. The
  highest tier is always the keyword grant that the engine encodes as
  ``stationed_keywords`` and ``station_threshold``. Lower tiers are
  static, triggered, or activated abilities gated on charge counters
  via ``StaticAbility.tier_threshold`` / ``TriggeredAbility.tier_threshold``.
- Zero or more "ETB" / standalone trigger lines (``"When this
  Spacecraft enters, ..."``, ``"Whenever this Spacecraft attacks,
  ..."``, etc.) and/or a printed activated ability.

This builder grew in several slices:

- **Slice 1** claimed the simplest end-to-end shape: the Station
  reminder line plus a single ``"<N>+ | <evergreen-keyword-list>"``
  tier line whose threshold matches the Station threshold. The
  keyword list is comma-joined evergreens from ``_KEYWORD_LINES``.
- **Slice 2** extends the grammar to claim a single
  ``"When this Spacecraft enters, <effect>."`` ETB trigger alongside
  the Station + tier-keyword pair. The trigger line is parsed by the
  unified ``_parse_clause`` orchestrator — the type-qualified self-ETB
  predicate-trigger phrase ``this Spacecraft enters`` already lives in
  ``triggers._PREDICATE_TRIGGER_PHRASES`` (added in batch 11), and any
  ETB whose effect phrase resolves through ``effects._parse_effect_phrase``
  becomes a ``TriggeredAbility`` we hand straight to
  ``make_spacecraft(triggered_abilities=...)``. Spacecraft whose ETB
  effect is outside the effect grammar (e.g. ``return target creature
  or enchantment card from your graveyard``) still fall through.
- **Slice 3** extended the trigger arm two ways. First,
  ``Whenever this Spacecraft attacks, <effect>.`` lines are accepted
  alongside the self-ETB shape — the type-qualified self-attack
  predicate-trigger phrase ``this Spacecraft attacks`` lives in the
  same ``_PREDICATE_TRIGGER_PHRASES`` table the self-ETB phrase uses,
  so the only change is the per-line dispatch widening to admit the
  ``Event.ATTACKS, IsSelf()`` shape. Second, the defensive Legendary
  skip is dropped — ``_parse_type_line``'s ``Legendary`` supertype is
  forwarded to ``make_spacecraft(legendary=True)`` so a Legendary
  Spacecraft whose body falls inside the supported grammar can be
  claimed.
- **Slice 4** (this batch) extends the ``"<N>+ | <body>"`` tier-line
  arm to claim **tier-gated triggered abilities**. A tier-line body
  that isn't a pure evergreen keyword list is re-tried through
  ``_parse_clause``; if it parses to a self-ETB or self-ATTACKS
  ``TriggeredAbility`` the trigger is added to the Spacecraft's
  trigger list with ``tier_threshold=N`` so the engine's
  ``TriggeredAbility.tier_threshold`` gate fires only when the
  Spacecraft has enough charge counters. Multi-tier static
  **keyword** grants — the Lumen-Class Frigate / Synthesizer Labship
  shape — were considered as a companion arm but rejected: the engine's
  ``StaticAbility.applies_to`` requires the target be a creature now,
  and every real EoE printing's lower-tier keyword line falls below
  the Station threshold (i.e. while the Spacecraft is still an
  artifact, not a creature), so a self-scoped ``StaticAbility`` with
  ``tier_threshold=N`` would never fire. Modeling those grants
  correctly needs an engine-side change to ``stationed_keywords``
  (tier-keyed keyword sets) and is left for a future slice.

Anything outside the supported shape - lower-tier static/activated
abilities, multiple tier-keyword lines (single-keyword-tier only is
claimed today), an ``X+`` body that isn't a bare keyword list and
isn't a self-trigger, or a missing Station line - falls through and
the Spacecraft is silently skipped, mirroring the
creature/spell/land/equipment builders.

Spacecraft live in their own module rather than extending the artifact/
equipment builders because the printed grammar (Station reminder text
+ tiered ``N+ |`` body lines) is structurally distinct from
``Equipped creature ...`` / ``Equip {N}`` and from plain artifact
oracle text. Folding those shapes together would require either
disjoint per-line regexes or per-builder branching that obscures the
narrow grammar each one actually claims.
"""

from __future__ import annotations

import dataclasses
import re

from mtg_bot.cards.base import (
    ActivatedAbility,
    CardPrinting,
    StaticAbility,
    StaticScope,
    TriggeredAbility,
    cost,
    make_artifact,
    make_spacecraft,
)
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.cards.parser.keywords import _KEYWORD_LINES
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.combinators import (
    OptionalSacLandOrLanderForBasicLandRamp,
    Sequence,
)
from mtg_bot.effects.generic import (
    CreateTokenPerMulticoloredPermanent,
    DealDamageAnyTarget,
    DealDamageToOpponentCreatureByArtifactCount,
    DealDamageToTargetCreature,
    DestroyTargetNoncreaturePermanent,
    DealNDamageToEachCreature,
    DiscardSelf,
    DrawCardPerMulticoloredPermanent,
    DrawCards,
    EachOpponentDiscardsOrLosesLife,
    EachOpponentMillsCards,
    EachOpponentSacrificesCreature,
    PumpSelfUntilEOT,
    PutPlusOneCounterOnEachCreatureYouControl,
    ReturnCreatureFromYourGraveyardToBattlefield,
    ReturnCreatureFromYourGraveyardToHand,
    ReturnUpToNTargetCreaturesToOwnersHands,
    SearchLibraryForCard,
    SelfMill,
    TargetArtifactBecomesCreatureUEOT,
    TargetPlayerLosesLife,
)
from mtg_bot.effects.predicates import OPPONENT, Controlled, Event, IsSelf, YOU


# ---------------------------------------------------------------------------
# Bespoke dispatch table — cards whose ETB effects are outside the general
# Station grammar's effect-phrase coverage. Built eagerly at module load
# (same pattern as ``special_guests_builder``). ``_build_spacecraft_printing``
# checks this table FIRST: if the card name is here and the type line says
# Spacecraft, the pre-built ``CardPrinting`` is returned immediately.
#
# Every entry mirrors the corresponding ``make_spacecraft(...)`` call in
# ``eoe_creatures.py`` exactly — same cost, power, toughness, thresholds,
# frozenset keywords, and trigger tuple.
# ---------------------------------------------------------------------------
_BESPOKE_SPACECRAFT: dict[str, CardPrinting] = {
    c.name: c
    for c in [
        # Atmospheric Greenhouse: ETB puts a +1/+1 counter on each creature
        # you control, 8+ flying + trample.
        make_spacecraft(
            "Atmospheric Greenhouse", "{4}{G}", 5, 4,
            station_threshold=8,
            stationed_keywords={"flying", "trample"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=PutPlusOneCounterOnEachCreatureYouControl(amount=1),
                ),
            ),
        ),
        # Susurian Dirgecraft: ETB each opponent sacrifices a nontoken
        # creature of their choice, 7+ flying.
        make_spacecraft(
            "Susurian Dirgecraft", "{4}{B}", 4, 3,
            station_threshold=7,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=EachOpponentSacrificesCreature(),
                ),
            ),
        ),
        # Uthros Scanship: ETB draw two cards then discard a card, 8+ flying.
        make_spacecraft(
            "Uthros Scanship", "{3}{U}", 4, 4,
            station_threshold=8,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=Sequence(effects=(
                        DrawCards(amount=2),
                        DiscardSelf(amount=1),
                    )),
                ),
            ),
        ),
        # Warmaker Gunship: ETB deals damage equal to artifact count to target
        # creature an opponent controls, 6+ flying.
        make_spacecraft(
            "Warmaker Gunship", "{2}{R}", 4, 3,
            station_threshold=6,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=DealDamageToOpponentCreatureByArtifactCount(),
                ),
            ),
        ),
        # Debris Field Crusher: ETB deals 3 damage to any target, 8+ flying,
        # "{1}{R}: This Spacecraft gets +2/+0 until end of turn."
        make_spacecraft(
            "Debris Field Crusher", "{4}{R}", 1, 5,
            station_threshold=8,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=DealDamageAnyTarget(amount=3),
                ),
            ),
            activated_abilities=(
                ActivatedAbility(
                    cost=cost(mana="{1}{R}"),
                    effect=PumpSelfUntilEOT(power_bonus=2, toughness_bonus=0),
                ),
            ),
        ),
        # Fell Gravship: ETB mill 3 then return a creature card from your
        # graveyard to your hand. Station 8+ flying + lifelink.
        make_spacecraft(
            "Fell Gravship", "{2}{B}", 3, 2,
            station_threshold=8,
            stationed_keywords={"flying", "lifelink"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=Sequence(effects=(
                        SelfMill(amount=3),
                        ReturnCreatureFromYourGraveyardToHand(),
                    )),
                ),
            ),
        ),
        # Larval Scoutlander: ETB optional sac land or Lander → search for up
        # to two basic lands onto battlefield tapped. Station 7+ flying.
        make_spacecraft(
            "Larval Scoutlander", "{2}{G}", 3, 3,
            station_threshold=7,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=OptionalSacLandOrLanderForBasicLandRamp(
                        land_count=2,
                    ),
                ),
            ),
        ),
        # Rescue Skiff: ETB return target creature from your graveyard to the
        # battlefield. Station 10+ flying.
        make_spacecraft(
            "Rescue Skiff", "{5}{W}", 5, 6,
            station_threshold=10,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=ReturnCreatureFromYourGraveyardToBattlefield(),
                ),
            ),
        ),
        # Specimen Freighter: ETB return up to two non-Spacecraft creatures to
        # owners' hands. Whenever attacks, each opponent mills 4. Station 9+
        # flying.
        make_spacecraft(
            "Specimen Freighter", "{5}{U}", 4, 7,
            station_threshold=9,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=ReturnUpToNTargetCreaturesToOwnersHands(
                        max_n=2, exclude_spacecraft=True,
                    ),
                ),
                TriggeredAbility(
                    event=Event.ATTACKS, predicate=IsSelf(),
                    effect=EachOpponentMillsCards(amount=4),
                ),
            ),
        ),
        # Extinguisher Battleship: ETB destroy target noncreature permanent
        # then deal 4 damage to each creature. Station 5+ flying + trample.
        make_spacecraft(
            "Extinguisher Battleship", "{8}", 10, 10,
            station_threshold=5,
            stationed_keywords={"flying", "trample"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=Sequence(effects=(
                        DestroyTargetNoncreaturePermanent(),
                        DealNDamageToEachCreature(amount=4),
                    )),
                ),
            ),
        ),
        # Entropic Battlecruiser: 1+ tier — whenever an opponent discards a
        # card, that player loses 3 life. Attack trigger — each opponent
        # discards a card or loses 3 life. Station 8+ flying + deathtouch.
        make_spacecraft(
            "Entropic Battlecruiser", "{3}{B}", 3, 10,
            station_threshold=8,
            stationed_keywords={"flying", "deathtouch"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.DISCARDS_CARD,
                    predicate=Controlled(by=OPPONENT),
                    effect=TargetPlayerLosesLife(amount=3),
                    tier_threshold=1,
                ),
                TriggeredAbility(
                    event=Event.ATTACKS, predicate=IsSelf(),
                    effect=EachOpponentDiscardsOrLosesLife(life_if_cant=3),
                ),
            ),
        ),
        # Synthesizer Labship: 2+ tier — at the beginning of combat on your
        # turn, target artifact becomes a 2/2 artifact creature with flying
        # UEOT. Station 9+ flying.
        make_spacecraft(
            "Synthesizer Labship", "{U}", 4, 4,
            station_threshold=9,
            stationed_keywords={"flying"},
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.BEGINNING_OF_COMBAT,
                    predicate=Controlled(YOU),
                    effect=TargetArtifactBecomesCreatureUEOT(
                        power=2, toughness=2,
                        granted_keywords=frozenset({"flying"}),
                    ),
                    tier_threshold=2,
                ),
            ),
        ),
        # Lumen-Class Frigate: 2+ tier static anthem (other creatures you
        # control get +1/+1). Station 12+ flying + lifelink.
        make_spacecraft(
            "Lumen-Class Frigate", "{1}{W}", 3, 5,
            station_threshold=12,
            stationed_keywords={"flying", "lifelink"},
            static_abilities=(
                StaticAbility(
                    scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
                    power_bonus=1, toughness_bonus=1,
                    tier_threshold=2,
                ),
            ),
        ),
        # Infinite Guideline Station: Legendary. ETB create a tapped 2/2
        # colorless Robot token for each multicolored permanent you control.
        # Attack trigger draw a card for each multicolored permanent you
        # control. Station 12+ flying.
        make_spacecraft(
            "Infinite Guideline Station", "{W}{U}{B}{R}{G}", 7, 15,
            station_threshold=12,
            stationed_keywords={"flying"},
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=CreateTokenPerMulticoloredPermanent(
                        token_printing=TOKEN_PRINTINGS["Robot"],
                        tapped=True,
                    ),
                ),
                TriggeredAbility(
                    event=Event.ATTACKS, predicate=IsSelf(),
                    effect=DrawCardPerMulticoloredPermanent(),
                ),
            ),
        ),
        # Dawnsire, Sunstar Dreadnought: Legendary. 10+ tier gated attack
        # trigger deals 100 damage to target creature. Station 20+ flying.
        make_spacecraft(
            "Dawnsire, Sunstar Dreadnought", "{5}", 20, 20,
            station_threshold=20,
            stationed_keywords={"flying"},
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ATTACKS, predicate=IsSelf(),
                    effect=DealDamageToTargetCreature(amount=100),
                    tier_threshold=10,
                ),
            ),
        ),
        # The Seriema: Legendary. ETB search library for a legendary creature
        # card → hand. 7+ tier static — other tapped legendary creatures you
        # control have indestructible. Station 7+ flying.
        make_spacecraft(
            "The Seriema", "{1}{W}{W}", 5, 5,
            station_threshold=7,
            stationed_keywords={"flying"},
            legendary=True,
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=SearchLibraryForCard(
                        filter_name="legendary_creature",
                        may_fail=False,
                    ),
                ),
            ),
            static_abilities=(
                StaticAbility(
                    scope=(
                        StaticScope
                        .OTHER_TAPPED_LEGENDARY_CREATURES_YOU_CONTROL
                    ),
                    granted_keywords=frozenset({"indestructible"}),
                    tier_threshold=7,
                ),
            ),
        ),
        # The Eternity Elevator: Legendary Artifact — Spacecraft but has no
        # printed P/T (never animates). The artifact_builder rejects
        # Spacecraft-subtyped cards, so ship it here as a plain artifact
        # using make_artifact to match the static registry.
        make_artifact(
            "The Eternity Elevator", "{5}",
            legendary=True,
        ),
    ]
}


# The Station reminder line. Scryfall prints it as a single line:
#   "Station (Tap another creature you control: Put charge counters
#    equal to its power on this Spacecraft. Station only as a sorcery.
#    It's an artifact creature at <N>+.)"
# We capture the threshold integer inside the parenthetical so we can
# cross-check it against the highest tier line. The trailing
# "It's an artifact creature at <N>+." sub-clause is omitted on
# Spacecraft that never animate (e.g. The Eternity Elevator), but
# every Spacecraft we currently claim has a non-zero station_threshold,
# so the regex requires it. Spacecraft without it fall through.
_STATION_LINE_RE = re.compile(
    r"^Station \(Tap another creature you control: "
    r"Put charge counters equal to its power on this Spacecraft\. "
    r"Station only as a sorcery\. "
    r"It's an artifact creature at (\d+)\+\.\)$"
)


# A tier line: ``"<N>+ | <body>"``. The body for the highest-tier
# keyword line is a comma-joined evergreen keyword list (e.g.
# ``"Flying"``, ``"Flying, haste"``). Lower-tier ability bodies use
# the same prefix; this batch (slice 4) re-tries those bodies through
# the unified clause parser to claim self-ETB / self-ATTACKS triggers
# tagged with ``tier_threshold=N``.
_TIER_LINE_RE = re.compile(r"^(\d+)\+ \| (.+)$")


def _parse_tier_keyword_body(body: str) -> frozenset[str] | None:
    """Parse a tier line body that's a comma-joined evergreen keyword
    list (``"Flying"``, ``"Flying, haste"``) into the frozen set of
    engine spellings. Returns ``None`` if any piece is not a recognized
    evergreen - the enclosing tier line then re-tries through the
    triggered-ability arm and, failing that, the Spacecraft is
    silently skipped.

    Mirrors the equipment-builder rider parser: tier-keyword bodies
    use sentence-case for everything past the first piece (``"Flying,
    haste"``), so we normalize each piece to title-case for the
    ``_KEYWORD_LINES`` lookup.
    """
    pieces = [p.strip() for p in body.split(",")]
    normalized = [p[:1].upper() + p[1:] for p in pieces]
    if not all(p in _KEYWORD_LINES for p in normalized):
        return None
    return frozenset(_KEYWORD_LINES[p] for p in normalized)


def _build_spacecraft_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for a Spacecraft ``card`` (a
    Scryfall record). Returns ``None`` if the card is not a Spacecraft
    or if its oracle text contains anything outside the narrow shape
    this builder supports:

    - a Station reminder line, plus
    - exactly one ``"<N>+ | <evergreen-keyword-list>"`` tier line
      whose threshold matches the Station threshold (this becomes
      ``stationed_keywords`` and ``station_threshold``).
    - zero or more ``"<M>+ | <self-trigger body>"`` tier lines whose
      body parses through ``_parse_clause`` to a self-ETB or self-
      ATTACKS ``TriggeredAbility``. The threshold ``M`` lands on
      ``TriggeredAbility.tier_threshold`` so the engine fires the
      trigger only once the Spacecraft has enough charge counters.
    - at most one ``"When this Spacecraft enters, <effect>."`` line
      whose effect resolves through ``_parse_clause`` to a
      ``TriggeredAbility(event=ENTERS, predicate=IsSelf())``, and
    - at most one ``"Whenever this Spacecraft attacks, <effect>."``
      line whose effect resolves through ``_parse_clause`` to a
      ``TriggeredAbility(event=ATTACKS, predicate=IsSelf())``.

    Legendary Spacecraft (The Seriema, Dawnsire, Infinite Guideline
    Station, The Eternity Elevator) are not skipped — the ``Legendary``
    supertype, when present in the type line, is forwarded to
    ``make_spacecraft(legendary=True)``. Today no EoE Legendary
    Spacecraft body falls inside this grammar (each carries an effect
    outside the effect grammar, missing P/T, or a tier-gated trigger
    whose effect isn't claimed), so accepting the ``Legendary``
    supertype is forward-looking grammar coverage; per-card parity
    stays exact because the static registry builds those cards with
    ``legendary=True`` directly.
    """
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Artifact" not in card_types:
        return None
    if "Spacecraft" not in subtypes:
        return None

    # Bespoke table: cards whose ETB effects aren't covered by the
    # general Station grammar. Check name FIRST — if the card is
    # present here the pre-built ``CardPrinting`` is returned
    # immediately, skipping the grammar entirely.
    name = card.get("name", "")
    if name in _BESPOKE_SPACECRAFT:
        return _BESPOKE_SPACECRAFT[name]

    legendary = "Legendary" in supertypes
    try:
        power = int(card["power"])
        toughness = int(card["toughness"])
    except (KeyError, ValueError):
        return None

    text = card.get("oracle_text", "")
    # Spacecraft oracle text is line-structured but we don't strip
    # reminder text here: the Station line *is* parenthesized reminder
    # text in its entirety, and stripping it would make the line
    # disappear. We match it literally instead.
    lines = [line for line in text.split("\n") if line.strip()]

    station_threshold: int | None = None
    tier_threshold: int | None = None
    stationed_keywords: frozenset[str] | None = None
    triggers: list[TriggeredAbility] = []

    for line in lines:
        m = _STATION_LINE_RE.match(line)
        if m is not None:
            if station_threshold is not None:
                # Two Station lines on one card would be malformed -
                # bail rather than silently keep the second.
                return None
            station_threshold = int(m.group(1))
            continue
        m = _TIER_LINE_RE.match(line)
        if m is not None:
            tier_n = int(m.group(1))
            body = m.group(2)
            kw = _parse_tier_keyword_body(body)
            if kw is not None:
                if tier_threshold is not None:
                    # A second keyword tier line means a multi-tier
                    # keyword Spacecraft (e.g. a synthetic
                    # ``"5+ | Flying" + "10+ | Flying, lifelink"``).
                    # Out of scope: the engine's ``stationed_keywords``
                    # is a single-tier set, and modeling lower-tier
                    # keyword grants via ``StaticAbility`` doesn't
                    # work because ``StaticAbility.applies_to``
                    # requires the target be a creature now (so a
                    # sub-station-threshold keyword grant never fires;
                    # an at-or-above-threshold one would need a
                    # different engine model). Skip rather than
                    # half-claim.
                    return None
                tier_threshold = tier_n
                stationed_keywords = kw
                continue
            # Body wasn't a pure evergreen keyword list — try the
            # unified clause parser for the tier-gated trigger arm.
            clause = _parse_clause(body)
            if clause is None:
                # Static / activated / unknown shape — out of scope.
                return None
            if clause.trigger is None:
                # The clause parsed but as a non-trigger (static
                # ability, activated ability, granted-keyword line).
                # Tier-gated statics on Spacecraft aren't modeled by
                # this builder yet — skip rather than silently drop
                # the ability.
                return None
            trig = clause.trigger
            if trig.predicate != IsSelf():
                # Defensive: only self-targeted predicates make sense
                # for tier-gated Spacecraft body shapes we claim.
                return None
            if trig.event not in (Event.ENTERS, Event.ATTACKS):
                # Same restriction as the standalone trigger-line arm
                # — only the two events we explicitly claim.
                return None
            if any(
                t.event == trig.event and t.tier_threshold == tier_n
                for t in triggers
            ):
                # A second tier-gated trigger at the same threshold on
                # the same event is out of scope; claiming only the
                # first would silently drop the second.
                return None
            triggers.append(
                dataclasses.replace(trig, tier_threshold=tier_n)
            )
            continue
        # Try the unified clause parser. This builder accepts at most
        # one self-ETB trigger and at most one self-ATTACKS trigger
        # per card from non-tier lines; any other clause shape (static,
        # activated, a different trigger event) is out of scope and
        # skips the whole card.
        clause = _parse_clause(line)
        if clause is None:
            # Anything the unified parser doesn't recognize - attack
            # or ETB triggers whose effect phrases aren't modeled,
            # plain activated abilities not yet supported here, etc. -
            # falls through and we skip the whole card.
            return None
        if clause.trigger is None:
            # The clause parsed but as a non-trigger (static keyword,
            # activated ability, granted-keyword line). This builder
            # doesn't model those on Spacecraft yet - skip rather than
            # silently drop the ability.
            return None
        trig = clause.trigger
        if trig.predicate != IsSelf():
            # Defensive: only self-targeted predicates make sense for
            # the Spacecraft body shapes we claim. A trigger whose
            # predicate isn't ``IsSelf()`` is some other observer
            # event whose effect happened to parse — skip rather
            # than mis-wire it.
            return None
        if trig.event not in (Event.ENTERS, Event.ATTACKS):
            # Self-DIES / self-LEAVES / self-BECOMES_TAPPED etc. are
            # not body-trigger shapes any current Spacecraft prints,
            # and accepting them blindly would risk mis-wiring a
            # future printing whose effect happened to parse. Restrict
            # to the two events we explicitly claim.
            return None
        if any(
            t.event == trig.event and t.tier_threshold == 0
            for t in triggers
        ):
            # A second non-tier-gated trigger line on the same event
            # (two ETB lines, two attack-trigger lines) is out of
            # scope — claiming only the first would silently drop the
            # second. Tier-gated triggers at distinct thresholds on
            # the same event remain allowed (handled in the tier-line
            # arm above).
            return None
        triggers.append(trig)

    # Both Station and the keyword-tier line are required: a Spacecraft
    # with no Station line is malformed, and one with no tier-keyword
    # line wouldn't ever animate via ``stationed_keywords``.
    if station_threshold is None:
        return None
    if tier_threshold is None or stationed_keywords is None:
        return None
    # The Station reminder text encodes the same threshold as the
    # highest (and here only) keyword tier line on every printing in
    # the current EoE pool. Treat any drift as a signal that we're
    # looking at a shape outside this grammar and bail.
    if station_threshold != tier_threshold:
        return None

    # Order the triggers deterministically: non-tier-gated triggers
    # (``tier_threshold=0``) first in printed order, followed by tier-
    # gated triggers sorted by tier threshold ascending. This keeps the
    # parsed printing byte-equal to the static-registry analogue
    # regardless of where the printed text places the tier-line vs the
    # standalone-trigger lines.
    non_tier_triggers = [t for t in triggers if t.tier_threshold == 0]
    tier_triggers = sorted(
        (t for t in triggers if t.tier_threshold != 0),
        key=lambda t: (t.tier_threshold, t.event.value if hasattr(t.event, "value") else 0),
    )
    ordered_triggers = tuple(non_tier_triggers) + tuple(tier_triggers)

    return make_spacecraft(
        name=card["name"],
        cost=card["mana_cost"],
        power=power,
        toughness=toughness,
        station_threshold=station_threshold,
        stationed_keywords=stationed_keywords,
        triggered_abilities=ordered_triggers,
        legendary=legendary,
    )
