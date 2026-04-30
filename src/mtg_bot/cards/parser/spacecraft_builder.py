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
- **Slice 4** extends the ``"<N>+ | <body>"`` tier-line
  arm to claim **tier-gated triggered abilities**. A tier-line body
  that isn't a pure evergreen keyword list is re-tried through
  ``_parse_clause``; if it parses to a self-ETB or self-ATTACKS
  ``TriggeredAbility`` the trigger is added to the Spacecraft's
  trigger list with ``tier_threshold=N`` so the engine's
  ``TriggeredAbility.tier_threshold`` gate fires only when the
  Spacecraft has enough charge counters. Multi-tier static
  **keyword** grants — the Synthesizer Labship shape — were
  considered as a companion arm but rejected: the engine's
  ``StaticAbility.applies_to`` requires the target be a creature now,
  and every real EoE printing's lower-tier keyword line falls below
  the Station threshold (i.e. while the Spacecraft is still an
  artifact, not a creature), so a self-scoped ``StaticAbility`` with
  ``tier_threshold=N`` would never fire. Modeling those grants
  correctly needs an engine-side change to ``stationed_keywords``
  (tier-keyed keyword sets) and is left for a future slice.
- **Slice 5** (this batch) extends the tier-line arm a third way to
  claim **tier-gated anthem statics**. A tier-line body that re-parses
  through ``_parse_clause`` to a non-self-scoped ``StaticAbility``
  (``CREATURES_YOU_CONTROL`` or ``OTHER_CREATURES_YOU_CONTROL``) gets
  ``tier_threshold=N`` stamped on it and lands in
  ``make_spacecraft(static_abilities=...)``. Lumen-Class Frigate's
  ``2+ | Other creatures you control get +1/+1.`` is the EoE printing
  in this shape; the slice-4 rejection of tier-gated keyword statics
  doesn't apply because anthem scopes target *other* permanents and
  fire as soon as the Spacecraft has enough charge counters
  irrespective of whether the Spacecraft itself is animated.
- **Slice 6** (this batch) migrates the three remaining ``_BESPOKE_SPACECRAFT``
  entries whose effects were previously outside the unified grammar:
  Entropic Battlecruiser, Synthesizer Labship, and Dawnsire, Sunstar
  Dreadnought. Three effect-grammar additions unlock them:

  1. ``"they lose N life"`` → ``TargetPlayerLosesLife(amount=N)`` (for
     DISCARDS_CARD observer effects where "they" is the pre-wired target).
  2. Multi-sentence literal for ``"each opponent discards a card. Each
     opponent who can't loses N life"`` → ``EachOpponentDiscardsOrLosesLife``.
  3. Parameterized regex for ``"up to one other target artifact you control
     becomes an artifact creature with base power and toughness P/T and
     gains <keywords> until end of turn"`` →
     ``TargetArtifactBecomesCreatureUEOT``.

  Additionally the trigger-condition phrasebook gains
  ``"an opponent discards a card"`` → ``(Event.DISCARDS_CARD,
  Controlled(OPPONENT))`` and the tier-gated trigger arm in this builder
  is widened to accept three new (event, predicate) shapes:
  ``DISCARDS_CARD + Controlled(OPPONENT)`` (Entropic Battlecruiser),
  ``BEGINNING_OF_COMBAT + Controlled(YOU)`` (Synthesizer Labship), and
  ``YOU_ATTACK + Controlled(YOU)`` (Dawnsire). The
  ``_DEAL_DAMAGE_UP_TO_ONE_TARGET_CREATURE`` regex is also extended
  to accept a leading ``(?:this creature )?`` prefix and a trailing
  ``(?: or planeswalker)?`` suffix so Dawnsire's
  ``this creature deals 100 damage to up to one target creature or
  planeswalker`` effect phrase claims correctly.

  The Eternity Elevator remains in the bespoke table with a ``# SKIP``
  comment: it lacks printed P/T, uses a Station line without the
  ``"It's an artifact creature at N+."`` sub-clause, and carries a
  tier-gated X-mana activated ability — all outside the current grammar.

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
    make_artifact,
    make_spacecraft,
)
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.cards.parser.keywords import _KEYWORD_LINES
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.effects.predicates import OPPONENT, Controlled, Event, IsSelf, YOU, Predicate


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
        # SKIP — The Eternity Elevator: Legendary Artifact — Spacecraft that
        # has no printed P/T and never animates. Three grammar gaps prevent
        # the unified builder from claiming it:
        #   1. No P/T: the builder requires ``int(card["power"])`` /
        #      ``int(card["toughness"])`` to succeed; The Eternity Elevator
        #      has no P/T fields in the Scryfall record, so the try/except
        #      returns None before the oracle-text parse begins.
        #   2. Station line has no "It's an artifact creature" clause:
        #      ``_STATION_LINE_RE`` requires the ``It's an artifact creature
        #      at N+.`` sub-clause, but The Eternity Elevator's Station line
        #      omits it (the card never animates). The regex match fails, so
        #      no ``station_threshold`` is recorded and the builder bails.
        #   3. Tier-gated activated ability: ``20+ | {T}: Add X mana of any
        #      one color, where X is the number of charge counters on The
        #      Eternity Elevator.`` is a tier-gated X-mana activated ability
        #      the engine doesn't model (no tier-keyed ActivatedAbility +
        #      no variable-X mana production).
        #   4. Uses make_artifact not make_spacecraft: the artifact_builder
        #      rejects Spacecraft-subtyped cards, so this entry ships as a
        #      plain artifact to match the static registry.
        # Modeling this card correctly needs: (a) engine-side support for
        # Spacecraft that never animate (missing P/T grammar), (b) a
        # Station-line variant regex without the animation clause, (c)
        # tier-gated activated-ability support in the builder, and (d)
        # variable-X mana production in the activated-ability grammar. All
        # four are deferred to a future slice.
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


# Valid (event, predicate) pairs for tier-gated trigger lines in the
# Spacecraft body grammar. Self-ETB and self-attack share the ``IsSelf()``
# predicate. Three player-scoped or opponent-observer variants:
#
# - ``DISCARDS_CARD + Controlled(OPPONENT)``: ``"Whenever an opponent
#   discards a card"`` printed on Entropic Battlecruiser's 1+ tier line
#   (fires once per card discarded by any opponent of the source's
#   controller; the discarding player's id is pre-wired as a fixed target
#   by ``fire_opponent_discards_triggers``).
# - ``YOU_ATTACK + Controlled(YOU)``: ``"Whenever you attack"`` printed on
#   Dawnsire, Sunstar Dreadnought's 10+ tier line (fires once per declare-
#   attackers step when you attack with any creature).
# - ``BEGINNING_OF_COMBAT + Controlled(YOU)``: ``"At the beginning of
#   combat on your turn"`` printed on Synthesizer Labship's 2+ tier line
#   (fires at the beginning of the active player's combat step).
_VALID_SPACECRAFT_TIER_TRIGGER_EVENTS: tuple[
    tuple[Event, Predicate], ...
] = (
    (Event.ENTERS, IsSelf()),
    (Event.ATTACKS, IsSelf()),
    (Event.DISCARDS_CARD, Controlled(by=OPPONENT)),
    (Event.YOU_ATTACK, Controlled(YOU)),
    (Event.BEGINNING_OF_COMBAT, Controlled(YOU)),
)


def _is_valid_spacecraft_tier_trigger(trig: "TriggeredAbility") -> bool:
    """Return True when ``trig`` is a trigger type this builder claims
    on tier-gated lines: self-ETB, self-attack, opponent-discards-observer,
    player-attack, or beginning-of-combat-on-your-turn.

    The non-``IsSelf()`` shapes are added in this batch to support
    Entropic Battlecruiser's ``1+ | Whenever an opponent discards a card, …``
    (DISCARDS_CARD + Controlled(OPPONENT)), Dawnsire's
    ``10+ | Whenever you attack, …`` (YOU_ATTACK + Controlled(YOU)), and
    Synthesizer Labship's ``2+ | At the beginning of combat on your turn, …``
    (BEGINNING_OF_COMBAT + Controlled(YOU)) tier lines respectively.
    """
    return any(
        trig.event == event and trig.predicate == predicate
        for event, predicate in _VALID_SPACECRAFT_TIER_TRIGGER_EVENTS
    )


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
      ``TriggeredAbility(event=ATTACKS, predicate=IsSelf())``, and
    - any number of ``"{cost}: <effect>."`` activated-ability lines
      whose cost / effect resolve through ``_parse_clause`` to an
      ``ActivatedAbility``. Debris Field Crusher's
      ``{1}{R}: This Spacecraft gets +2/+0 until end of turn.`` is the
      EoE printing in this shape; the ``this Spacecraft`` self-source
      pronoun is admitted by the unified ``_PUMP_SELF_UEOT`` regex
      alongside the canonical ``this creature`` form.

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
    activateds: list[ActivatedAbility] = []
    statics: list[StaticAbility] = []

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
            # unified clause parser for the tier-gated trigger or
            # tier-gated anthem-static arm. Forward the printing's own
            # name so a tier-line trigger that references the source by
            # its printed name (named-self short form, e.g.
            # ``"Whenever Infinite Guideline Station attacks"``) is
            # substituted to the canonical ``this Spacecraft`` form
            # before the trigger phrase lookup.
            clause = _parse_clause(body, name=name)
            if clause is None:
                # Activated / unknown shape — out of scope.
                return None
            if clause.static is not None:
                # Tier-gated anthem static. Lumen-Class Frigate's
                # ``2+ | Other creatures you control get +1/+1.`` is
                # the EoE printing in this shape: an anthem-scope
                # static ability whose targets are creatures *other
                # than* the Spacecraft, gated on the Spacecraft having
                # at least ``N`` charge counters. The reasoning the
                # tier-keyword arm above rejects multi-tier-keyword
                # bodies (engine ``StaticAbility.applies_to`` requires
                # the Spacecraft itself be a creature for SELF-scoped
                # grants) does NOT apply here: anthem scopes target
                # other permanents on the battlefield, so the gate
                # fires as soon as the Spacecraft accumulates enough
                # charge counters regardless of whether it's animated.
                # Restrict to the anthem scopes the static parser
                # produces today (CREATURES_YOU_CONTROL /
                # OTHER_CREATURES_YOU_CONTROL); SELF-scoped statics
                # remain rejected because their faithfulness story is
                # the unresolved one (would need engine work for
                # tier-gated stationed-keyword grants, deferred to a
                # future slice).
                static_ab = clause.static
                if static_ab.scope not in (
                    StaticScope.OTHER_CREATURES_YOU_CONTROL,
                    StaticScope.CREATURES_YOU_CONTROL,
                ):
                    return None
                statics.append(
                    dataclasses.replace(static_ab, tier_threshold=tier_n)
                )
                continue
            if clause.trigger is None:
                # The clause parsed but as a non-trigger and non-anthem
                # (activated ability, granted-keyword line, self-scope
                # static). Tier-gated activations and self-scope
                # statics on Spacecraft aren't modeled by this builder
                # yet — skip rather than silently drop the ability.
                return None
            trig = clause.trigger
            if not _is_valid_spacecraft_tier_trigger(trig):
                # Defensive: only the three trigger shapes we claim in
                # tier-gated lines are accepted:
                # - ENTERS + IsSelf() (self-ETB tier line)
                # - ATTACKS + IsSelf() (self-attack tier line)
                # - YOU_ATTACK + Controlled(YOU) (player-attack tier line;
                #   Dawnsire's "Whenever you attack" which is oracle-text
                #   faithful to the YOU_ATTACK event rather than the
                #   ATTACKS+IsSelf shape the bespoke table used)
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
        # per card from non-tier lines, plus any number of activated
        # abilities; static-only clauses are still out of scope.
        # Forward the printing's own name so trigger phrases that
        # reference the source by name (Infinite Guideline Station,
        # whose ETB and attack-trigger lines spell out the full name)
        # are substituted to the canonical ``this Spacecraft`` form
        # before the trigger phrase lookup. Same threading the creature
        # builder does for legendary creatures via ``Syr Vondam``.
        clause = _parse_clause(line, name=name)
        if clause is None:
            # Anything the unified parser doesn't recognize - attack
            # or ETB triggers whose effect phrases aren't modeled,
            # activated abilities whose cost or effect grammar we don't
            # support, etc. - falls through and we skip the whole card.
            return None
        if clause.activated is not None:
            # Activated abilities surface as standalone lines on
            # Spacecraft (Debris Field Crusher's
            # ``{1}{R}: This Spacecraft gets +2/+0 until end of turn.``
            # is the EoE printing). The unified ``_parse_activated_
            # ability_line`` produces an ``ActivatedAbility`` whose
            # cost / effect / mana-ability flag are already wired —
            # forward it straight to ``make_spacecraft(activated_
            # abilities=...)``. Static and trigger arms below stay
            # mutually exclusive: a clause with a non-None ``activated``
            # field has an empty ``triggers`` tuple by ``_ParsedClause``
            # construction.
            activateds.append(clause.activated)
            continue
        if clause.static is not None:
            # Standalone (non-tier-gated) anthem static. The Seriema's
            # ``Other tapped legendary creatures you control have
            # indestructible.`` is the EoE printing in this shape: the
            # static is printed without an ``N+ |`` tier prefix, so it
            # is always-on (``tier_threshold=0``) — fires as soon as the
            # source is on the battlefield, regardless of charge
            # counters. The tier-line static arm above admits a
            # superset of anthem scopes (``CREATURES_YOU_CONTROL`` /
            # ``OTHER_CREATURES_YOU_CONTROL``); this non-tier path
            # additionally admits the narrower
            # ``OTHER_TAPPED_LEGENDARY_CREATURES_YOU_CONTROL`` scope
            # because (a) the engine's ``applies_to`` already filters
            # the target permanent without referencing the source's
            # creature status, and (b) the printed surface contains no
            # gating clause that would map to a tier threshold. SELF-
            # scoped statics remain rejected on the same grounds as
            # the tier-line arm: the engine would require the source
            # be a creature, which a Spacecraft only is at-or-above
            # its station threshold — modeling that correctly needs
            # an engine-side change for tier-gated stationed-keyword
            # grants and is out of scope.
            static_ab = clause.static
            if static_ab.scope == StaticScope.SELF:
                return None
            statics.append(static_ab)
            continue
        if clause.trigger is None:
            # The clause parsed but as a non-trigger / non-activated /
            # non-static (e.g. a granted-keyword self-keyword line).
            # This builder doesn't model those on Spacecraft yet -
            # skip rather than silently drop the ability.
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
        static_abilities=tuple(statics),
        activated_abilities=tuple(activateds),
        legendary=legendary,
    )
