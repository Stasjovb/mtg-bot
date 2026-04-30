"""Instant / sorcery ``CardPrinting`` builder.

Single-line spells are parsed straight via the unified spell-effect
phrase parser. Multi-line spells split on ``\\n`` into clauses and
combine them via one of three combinators — ``ConditionalIfVoid`` for
the Plasma-Bolt-shaped Void rider, ``ModalChooseOne`` for Scryfall's
``Choose one —`` modal shape, otherwise ``Sequence`` if every
clause parses as a plain spell-effect sentence. Any unparseable
clause skips the whole spell.

A leading clause that is just an unimplemented spell-only keyword
plus its parenthesized reminder text (currently only ``Convoke``)
is dropped before the remaining clauses are parsed — the static
side ships these spells without modeling the keyword, so the
parser must do the same to stay in parity. See
``_SPELL_KEYWORD_PREAMBLE_RE`` for the exact recognized shapes.

Cost-reduction rider clauses (``This spell costs {N} less to cast
if <condition>.``) are likewise stripped from the effect-clause
stream and surfaced separately on the ``CardPrinting`` via the
``cost_reductions`` kwarg. The ``_detect_cost_reductions`` helper
scans the original text for those rules; ``_parse_spell_oracle_
text`` drops the matching clauses before combinator dispatch.

The modal branch handles two Scryfall printed header shapes:
``Choose one —`` (single-mode pick) and ``Choose one or both —``
(controller may resolve either mode alone or both). Each is followed
by two or more mode lines that begin with ``• `` (bullet + space)
and contain a single sentence parseable by the unified spell-effect
grammar. The ``Choose one or both`` shape constructs
``ModalChooseOne(or_both=True)`` so the engine routes mode-pick
through the agent's ``choose_modes`` (plural) hook. ``Choose two``,
multi-line modes, and ``up to two target`` mode-counts remain out of
scope; the parser declines those spells until the engine grows the
matching machinery.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import (
    BiosynthicBurstEffect,
    CardPrinting,
    CloseEncounterEffect,
    CommuneWithEvilEffect,
    ConditionalIfVoid,
    ConsultTheStarChartsEffect,
    CoordinatedClobberingEffect,
    CostReduction,
    CounterTargetSpell,
    CreateToken,
    ExileTargetCreature,
    CreateXTokensOfTargetPermanentWithHasteEndStepSac,
    CutPropulsionEffect,
    DealDamageAnyTarget,
    DealDamageToTargetCreature,
    DealNDamageToEachCreature,
    DestroyTargetArtifact,
    DestroyTargetCreature,
    DestroyTargetNonlandPermanent,
    DiplomaticRelationsEffect,
    DrawCards,
    EachOpponentLosesLife,
    Effect,
    LoseLife,
    ManifestDread,
    ModalChooseOne,
    MutinousMassacreEffect,
    OptionalSacArtifactForEffect,
    PumpCreaturesYouControlUntilEOT,
    PumpTargetCreatureUntilEOT,
    ReturnCreatureFromYourGraveyardToBattlefield,
    ReturnCreatureFromYourGraveyardToHand,
    ReturnTargetCreatureToOwnersHand,
    ReturnUpToNSmallCreaturesFromGraveyardWithCounters,
    Sequence,
    SystemsOverrideEffect,
    VengefulPossessionEffect,
    ZeroPointBalladEffect,
    make_instant,
    make_sorcery,
)
from mtg_bot.cards.parser.cost_reduction import _parse_cost_reduction_line
from mtg_bot.cards.parser.effects import _parse_spell_effect_phrase
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.cards.tokens import TOKEN_PRINTINGS


# Modal spell headers: ``Choose one —`` (single-mode pick) or
# ``Choose one or both —`` (controller may resolve either mode alone
# or both — currently only Scour for Scrap in EoE). Both em-dashes are
# U+2014. ``Choose two`` and other mode-counts remain out of scope.
_MODAL_CHOOSE_ONE_HEADER_RE = re.compile(r"^Choose one —$")
_MODAL_CHOOSE_ONE_OR_BOTH_HEADER_RE = re.compile(r"^Choose one or both —$")
# A mode line begins with U+2022 BULLET + a single space, then the
# mode's effect sentence. Trailing period is preserved here and stripped
# downstream by the spell-effect-phrase normalizer.
_MODAL_MODE_LINE_RE = re.compile(r"^• (.+)$")


# Plasma-Bolt-shaped Void rider: a second clause of the form
# "Void — <Name> deals M damage instead if a nonland permanent left the
# battlefield this turn or a spell was warped this turn."
# Pairs with a preceding "<Name> deals N damage to any target." clause
# to form a ConditionalIfVoid switching the damage amount.
_SPELL_VOID_DAMAGE_REPLACEMENT = (
    r"^Void — {name} deals (\d+) damage instead "
    r"if a nonland permanent left the battlefield this turn "
    r"or a spell was warped this turn\.$"
)


# Tragic-Trajectory-shaped Void rider: a second clause of the form
# "Void — That creature gets ±M/±M' until end of turn instead if a
# nonland permanent left the battlefield this turn or a spell was
# warped this turn."
# Pairs with a preceding "Target creature gets ±N/±N' until end of
# turn." clause to form a ConditionalIfVoid switching the pump
# bonuses. The carry-over subject ``That creature`` refers back to
# the target chosen on the first clause; the engine reuses the
# same target when resolving either branch (single-target spell).
_SPELL_VOID_PUMP_REPLACEMENT = re.compile(
    r"^Void — That creature gets ([+-]\d+)/([+-]\d+) "
    r"until end of turn instead "
    r"if a nonland permanent left the battlefield this turn "
    r"or a spell was warped this turn\.$"
)


# Hymn-of-the-Faller-shaped Void "adds-a-draw" rider: a second clause
# of the form "Void — If a nonland permanent left the battlefield this
# turn or a spell was warped this turn, draw another card."
# Pairs with ANY base-clause Sequence to append a
# ``ConditionalIfVoid(then=DrawCards(1), else=None)`` to the Sequence.
# Unlike the replacement helpers above (which swap one effect for
# another), this rider ADDS an extra draw on top of the base effects
# when the Void state is active.
_SPELL_VOID_ADDS_DRAW_RE = re.compile(
    r"^Void — If a nonland permanent left the battlefield this turn "
    r"or a spell was warped this turn, draw another card\.$"
)


# Void "instead" rider: ``Void — If a nonland permanent left the
# battlefield this turn or a spell was warped this turn, instead
# <then-effect>.`` (Decode Transmissions). The "instead" keyword
# indicates the rider REPLACES the preceding base effect entirely —
# distinct from the "adds-draw" rider (which appends an effect) and
# from the damage/pump replacement helpers (which swap one specific
# field). The then-branch phrase after ``instead `` is parsed by the
# unified spell-effect grammar; if it doesn't parse, the rider is
# rejected and the spell stays in the bespoke table.
#
# Two-clause shape:
#   base clause → parses via ``_parse_spell_effect_phrase``
#   Void-instead rider → captures the then-branch for parsing
# Combined: ``ConditionalIfVoid(then=then_effect, else=base_effect)``
_SPELL_VOID_INSTEAD_EFFECT_RE = re.compile(
    r"^Void — If a nonland permanent left the battlefield this turn "
    r"or a spell was warped this turn, instead (.+)\.$"
)


# Delirium-rider drop regexes — recognizers for ``Delirium — …``
# clauses that the parser silently drops because the engine doesn't
# implement the Delirium graveyard-card-type check today.
#
# Three distinct shapes exist in the EoE/Duskmourn pool:
#
#   1. **Effect rider** — ``Delirium — If there are four or more card
#      types among cards in your graveyard, <effect>.``  The effect
#      is an upside that is lost entirely when Delirium support is
#      absent; no CostReduction is produced.  (Impossible Inferno,
#      Violent Urge, Demonic Counsel.)
#
#   2. **Cost-reduction rider** — ``Delirium — This spell costs {N}
#      less to cast as long as there are four or more card types among
#      cards in your graveyard.``  Would be a CostReduction but the
#      ``four_or_more_card_types_in_graveyard`` condition isn't wired
#      into ``_evaluate_cost_reduction``; drop cleanly so no spurious
#      CostReduction rule is attached to the printing.  (Drag to the
#      Roots.)
#
#   3. **Modal-header upgrade** — ``Delirium — Choose one. If there
#      are four or more card types among cards in your graveyard, choose
#      one or more instead.``  The header is replaced by the bare
#      ``Choose one —`` semantics; the mode lines that follow still
#      parse normally via ``_parse_modal_choose_one``.
#      (Let's Play a Game.)
#
# All three shapes start with ``Delirium — `` and the remainder
# differs enough that three regexes (rather than one catch-all) are
# cleaner; each regex's sole purpose is to match that shape so the
# caller knows to drop the clause.
_DELIRIUM_EFFECT_RIDER_RE = re.compile(
    r"^Delirium — If there are four or more card types among "
    r"cards in your graveyard, "
)
_DELIRIUM_COST_REDUCTION_RIDER_RE = re.compile(
    r"^Delirium — This spell costs \{\d+\} less to cast as long as "
    r"there are four or more card types among cards in your graveyard\.$"
)
_DELIRIUM_MODAL_HEADER_RE = re.compile(
    r"^Delirium — Choose one\. "
    r"If there are four or more card types among cards in your graveyard, "
    r"choose one or more instead\.$"
)


def _is_delirium_drop_clause(clause: str) -> bool:
    """Return ``True`` if ``clause`` is a Delirium-prefix line that
    the parser drops as an unimplemented mechanic.

    Two shapes are recognized for dropping:
      - Effect rider: ``Delirium — If there are four or more card
        types …, <effect>.``  (Impossible Inferno, Violent Urge,
        Demonic Counsel) — upside dropped because the engine has no
        Delirium graveyard-card-type check.
      - Cost-reduction rider: ``Delirium — This spell costs {N} less
        to cast as long as there are four or more card types ….``
        (Drag to the Roots) — dropped so no spurious ``CostReduction``
        rule is attached (this drop happens BEFORE the cost-reduction-
        stripping pass so the line never reaches ``_detect_cost_
        reductions``).

    The modal-header variant (``Delirium — Choose one. If there are
    four or more card types …, choose one or more instead.``) is NOT
    dropped here; instead ``_parse_modal_choose_one`` recognizes it
    directly and treats it as a plain ``Choose one —`` header (the
    Delirium upgrade to "choose one or more" is silently discarded
    since the engine has no Delirium-conditional modal-count combinator
    today).
    """
    c = clause.strip()
    return (
        _DELIRIUM_EFFECT_RIDER_RE.match(c) is not None
        or _DELIRIUM_COST_REDUCTION_RIDER_RE.match(c) is not None
    )


# Unimplemented secondary-rider regexes — recognizers for clauses that
# the parser drops because the engine lacks the plumbing to model them.
# Unlike the Delirium multi-clause dropper (which strips an entire line
# from the clause stream before any parsing starts), these patterns
# match the SECOND sentence of a two-clause spell body.  When the
# FIRST sentence parses cleanly as a standalone effect and the second
# matches one of these patterns, the two-clause path returns just the
# first-sentence effect (same simplification the bespoke entries make).
#
# Five shapes exist in the EoE/DSK pool:
#
#   1. **Controller-manifest rider** — ``Its controller manifests
#      dread.``  (entry: "Destroy target creature. Its controller
#      manifests dread." → DestroyTargetCreature()).  The engine's
#      ManifestDread primitive resolves for the *casting* controller;
#      adding a ``for_controller_of_target=True`` path would require
#      non-trivial wiring through the targeting/resolution pipeline.
#
#   2. **Death-trigger manifest rider** — ``When it dies this turn,
#      manifest dread.``  (entry: "Target creature gets +3/+0 until
#      end of turn. When it dies this turn, manifest dread." →
#      PumpTargetCreatureUntilEOT(3, 0)).  The engine has no UEOT-
#      scoped per-target death-trigger registry; adding one for a
#      single card's rider would be a non-trivial widening.
#
#   3. **Optional-graveyard-return rider** — ``You may return a
#      permanent card from your graveyard to your hand.``  (entry:
#      "Manifest dread.\n You may return a permanent card from your
#      graveyard to your hand." → ManifestDread()).  Every existing
#      ``Return*FromGraveyardToHand`` primitive is creature-typed;
#      widening to "any permanent card" with optionality for a single
#      card's rider is a non-trivial engine change.
#
#   4. **Mana-spent conditional draw** — ``If the amount of mana spent
#      to cast that spell was less than its mana value, you draw a
#      card.``  (entry: Unravel, "Counter target spell. If the
#      amount…" → CounterTargetSpell()).  The engine doesn't track
#      per-spell cast-time mana accounting.
#
#   5. **Subtype-filtered UEOT keyword grant** — ``<Subtype>s you
#      control gain <keywords> until end of turn.``  (entry: Midnight
#      Mayhem, "Create three 1/1 red Gremlin creature tokens. Gremlins
#      you control gain menace, lifelink, and haste until end of
#      turn." → CreateToken(Gremlin, count=3)).  The existing
#      ``PumpCreaturesYouControlUntilEOT`` applies to ALL your
#      creatures; a subtype-filtered variant would need a new optional
#      kwarg or a sibling primitive for one card's rider.
#
#   6. **Exile-on-death rider** — ``If that creature or planeswalker
#      would die this turn, exile it instead.``  (entry: Scorching
#      Dragonfire, "Scorching Dragonfire deals 3 damage to target
#      creature or planeswalker. If that creature or planeswalker
#      would die this turn, exile it instead." →
#      DealDamageToTargetCreature(amount=3)).  The engine has no
#      UEOT-scoped "exile-instead-of-die" replacement-effect registry
#      for targeted permanents; adding one for a single card's rider
#      is a non-trivial engine widening.
#
#   7. **"If they do" pay-or-counter consequent** — ``If they do,
#      <effect>.``  (entries: Divert Disaster, Don't Make a Sound).
#      The ``Unless its controller pays {N}`` escape clause in the
#      first sentence is recognized as ``CounterTargetSpell()`` via
#      the new ``_COUNTER_TARGET_SPELL_UNLESS_PAYS`` recognizer; the
#      resulting second clause ``If they do, you create a Lander
#      token.`` / ``If they do, surveil 2.`` has no standalone
#      primitive because the engine doesn't model the pay-cost-or-
#      counter branching that determines whether "they do" applies.
#
#   8. **Conditional reanimate-this-way rider** — ``If a creature
#      card is put into a graveyard this way, return it to the
#      battlefield under your control.``  (entry: Come Back Wrong).
#      The engine has no "if destroyed-this-way creature card was
#      put into graveyard, reanimate it" conditional reanimate
#      primitive; adding one would require wiring back to the
#      resolution context of the triggering Destroy effect.
#
#   9. **Delayed end-step sacrifice trigger** — ``Sacrifice it at
#      the beginning of your next end step.``  (entry: Come Back
#      Wrong).  The engine has no per-object one-shot delayed
#      end-step sacrifice trigger registry.
_ITS_CONTROLLER_MANIFESTS_DREAD_RE = re.compile(
    r"^Its controller manifests dread\.$"
)
_WHEN_IT_DIES_THIS_TURN_MANIFEST_DREAD_RE = re.compile(
    r"^When it dies this turn, manifest dread\.$"
)
_YOU_MAY_RETURN_PERMANENT_CARD_FROM_GY_TO_HAND_RE = re.compile(
    r"^You may return a permanent card from your graveyard to your hand\.$"
)
_MANA_SPENT_CONDITIONAL_DRAW_RE = re.compile(
    r"^If the amount of mana spent to cast that spell was less than "
    r"its mana value, you draw a card\.$"
)
# Subtype-filtered UEOT keyword grant — ``<Subtype>s you control gain
# <keywords> until end of turn.``  The subtype group anchors on a
# capitalized word followed by ``s you control gain``.  The negative
# lookahead ``(?!Creatures )`` excludes the bare generic plural
# ``Creatures you control gain …`` surface, which IS modelable via
# the existing ``PumpCreaturesYouControlUntilEOT`` recognizer and
# must not be dropped.  Only subtype-specific plurals (``Gremlins``,
# ``Vampires``, etc.) are dropped because the engine has no subtype-
# filtered UEOT pump primitive today.
_SUBTYPE_CREATURES_YOU_CONTROL_GAIN_KEYWORDS_UEOT_RE = re.compile(
    r"^(?!Creatures )[A-Z][a-z]+s you control gain .+ until end of turn\.$"
)
# Exile-on-death rider — ``If that creature or planeswalker would die
# this turn, exile it instead.``  (Scorching Dragonfire).  The engine
# has no UEOT-scoped "exile-instead-of-die" replacement-effect
# registry for targeted permanents.
_EXILE_ON_DEATH_THIS_TURN_INSTEAD_RE = re.compile(
    r"^If that creature(?: or planeswalker)? would die this turn, "
    r"exile it instead\.$"
)
# Pay-or-counter consequent rider — ``If they do, <effect>.``
# (Divert Disaster, Don't Make a Sound).  The ``unless controller
# pays {N}`` first sentence is recognized as ``CounterTargetSpell()``
# via ``_COUNTER_TARGET_SPELL_UNLESS_PAYS``, but the consequent
# "if they do" clause has no standalone primitive because the engine
# doesn't model which pay-cost-or-counter branch fires.
_IF_THEY_DO_RIDER_RE = re.compile(r"^If they do, .+\.$")
# Conditional reanimate-this-way rider — ``If a creature card is put
# into a graveyard this way, return it to the battlefield under your
# control.``  (Come Back Wrong).  The engine has no "destroyed-this-
# way conditional reanimate" primitive.
_IF_CREATURE_CARD_PUT_INTO_GY_THIS_WAY_RETURN_IT_RE = re.compile(
    r"^If a creature card is put into a graveyard this way, "
    r"return it to the battlefield under your control\.$"
)
# Delayed end-step sacrifice trigger — ``Sacrifice it at the beginning
# of your next end step.``  (Come Back Wrong).  The engine has no per-
# object one-shot delayed end-step sacrifice trigger registry.
_SACRIFICE_IT_AT_BEGINNING_OF_NEXT_END_STEP_RE = re.compile(
    r"^Sacrifice it at the beginning of your next end step\.$"
)


def _is_unimplemented_secondary_rider(clause: str) -> bool:
    """Return ``True`` if ``clause`` is an unimplemented rider sentence
    that the parser drops because the engine lacks the plumbing to model
    it.

    Nine shapes are recognized:
      - ``Its controller manifests dread.`` (controller-manifest rider)
      - ``When it dies this turn, manifest dread.`` (death-trigger
        manifest rider)
      - ``You may return a permanent card from your graveyard to your
        hand.`` (optional graveyard-return rider)
      - ``If the amount of mana spent to cast that spell was less than
        its mana value, you draw a card.`` (mana-spent conditional draw)
      - ``<Subtype>s you control gain <keywords> until end of turn.``
        (subtype-filtered UEOT keyword grant)
      - ``If that creature or planeswalker would die this turn, exile it
        instead.`` (exile-on-death rider)
      - ``If they do, <effect>.`` (pay-or-counter consequent; the first
        sentence must be a ``unless controller pays {N}`` counterspell)
      - ``If a creature card is put into a graveyard this way, return it
        to the battlefield under your control.`` (conditional reanimate-
        this-way rider; Come Back Wrong)
      - ``Sacrifice it at the beginning of your next end step.``
        (delayed end-step sac trigger; Come Back Wrong)

    Used in the two-clause path and the general N-clause rider-drop
    path in ``_parse_spell_oracle_text``: when the FIRST clause parses
    cleanly and all remaining clauses match these patterns, the first
    clause's effect is returned (mirroring the simplification the
    bespoke entries already make).
    """
    c = clause.strip()
    return (
        _ITS_CONTROLLER_MANIFESTS_DREAD_RE.match(c) is not None
        or _WHEN_IT_DIES_THIS_TURN_MANIFEST_DREAD_RE.match(c) is not None
        or _YOU_MAY_RETURN_PERMANENT_CARD_FROM_GY_TO_HAND_RE.match(c) is not None
        or _MANA_SPENT_CONDITIONAL_DRAW_RE.match(c) is not None
        or _SUBTYPE_CREATURES_YOU_CONTROL_GAIN_KEYWORDS_UEOT_RE.match(c) is not None
        or _EXILE_ON_DEATH_THIS_TURN_INSTEAD_RE.match(c) is not None
        or _IF_THEY_DO_RIDER_RE.match(c) is not None
        or _IF_CREATURE_CARD_PUT_INTO_GY_THIS_WAY_RETURN_IT_RE.match(c) is not None
        or _SACRIFICE_IT_AT_BEGINNING_OF_NEXT_END_STEP_RE.match(c) is not None
    )


# Self-shuffle rider clauses — recognizers for the two Scryfall-printed
# self-shuffle surface forms that a spell's oracle text may carry as a
# trailing sentence or a separate oracle line. Both are already handled by
# the ``shuffles_into_library_instead_of_graveyard`` printing flag (wired
# via ``_detect_shuffle_self_flags``), so they contribute no ``Effect``
# and must be dropped from the effect-clause stream before the
# combinator dispatch runs.
#
# Two shapes exist in the EoE pool:
#
#   1. **GSZ form** — ``Shuffle <Name> into its owner's library.``
#      (Green Sun's Zenith). Appears as the trailing sentence on the
#      spell's single oracle line, split off by ``_split_sentences``.
#
#   2. **Nexus form** — ``If <Name> would be put into a graveyard from
#      anywhere, reveal <Name> and shuffle it into its owner's library
#      instead.`` (Nexus of Fate). Appears as the spell's second oracle
#      line (a separate ``\n``-separated clause).
#
# Both shapes are matched with generic regexes that accept any card name
# (an arbitrary non-empty word sequence between the anchors), so a future
# card with the same self-shuffle mechanic claims automatically without
# adding a new literal key. The ``_detect_shuffle_self_flags`` helper uses
# a name-interpolated ``re.search`` against the FULL oracle text, which
# fires correctly regardless of whether the self-shuffle line is dropped
# here — the dropping only affects the effect-clause stream, not the flag
# detection.
_SELF_SHUFFLE_GSZ_RE = re.compile(
    r"^Shuffle .+ into its owner's library\.$"
)
_SELF_SHUFFLE_NEXUS_RE = re.compile(
    r"^If .+ would be put into a graveyard from anywhere, "
    r"reveal .+ and shuffle it into its owner's library instead\.$"
)


def _is_self_shuffle_clause(clause: str) -> bool:
    """Return ``True`` if ``clause`` is a recognized self-shuffle rider
    that the parser drops from the effect-clause stream.

    Two shapes are recognized (after reminder-text stripping):
      - ``Shuffle <Name> into its owner's library.`` (GSZ form)
      - ``If <Name> would be put into a graveyard from anywhere, reveal
        <Name> and shuffle it into its owner's library instead.``
        (Nexus of Fate form)

    Both shapes are already modeled by the
    ``shuffles_into_library_instead_of_graveyard`` printing flag (wired
    via ``_detect_shuffle_self_flags``), so they contribute no ``Effect``
    and should be excluded from the effect-clause stream. Dropping here
    lets the remaining clause(s) parse through the unified per-clause
    grammar rather than failing the whole spell because the self-shuffle
    rider can't parse as a standalone ``Effect``.
    """
    c = clause.strip()
    return (
        _SELF_SHUFFLE_GSZ_RE.match(c) is not None
        or _SELF_SHUFFLE_NEXUS_RE.match(c) is not None
    )


# Sentence-boundary splitter for multi-sentence oracle-text lines.
# Some EoE printings pack two effect sentences onto a single oracle
# line separated by ``. `` rather than ``\n`` (e.g. Radiant Strike's
# ``"Destroy target artifact or tapped creature. You gain 3 life."``).
# We carve the line at the period-then-uppercase boundary so each
# sentence flows through the per-clause parser independently.
#
# The negative lookahead keeps the splitter from breaking the
# ``You may pay/sacrifice/discard {COST}. If you do, <inner-effect>.``
# and ``You may sacrifice an artifact. When you do, <inner-effect>.``
# families of compound primitives — those are matched as a single
# phrase by ``_YOU_MAY_PAY_THEN_EFFECT`` /
# ``_OPTIONAL_DISCARD_THEN_DRAW`` / ``_OPTIONAL_SAC_ANOTHER_FOR_*`` /
# ``_YOU_MAY_SAC_ARTIFACT_WHEN_YOU_DO`` down in ``effects``, and the
# embedded sentence boundary inside those phrases is required (the
# regexes match a literal ``\. `` between the cost and the consequence).
#
# Both "If you do," and "When you do," are guarded because Lithobraking
# prints "Then you may sacrifice an artifact. When you do, …" — without
# the "When you do," guard the splitter would separate the two-sentence
# compound and the per-clause grammar would fail on the second piece.
#
# Decimal numbers and abbreviations don't appear in MTG oracle text,
# so a simple ``period + whitespace + uppercase`` boundary suffices —
# no need for a fuller sentence tokenizer.
_SENTENCE_BOUNDARY_RE = re.compile(
    r"(?<=\.)\s+(?=[A-Z])(?!(?:If|When) you do,)"
)


def _split_sentences(line: str) -> list[str]:
    """Split a single oracle-text line at sentence boundaries.

    Returns ``[line]`` unchanged when the line contains no internal
    boundary. Otherwise returns the list of per-sentence pieces, each
    with surrounding whitespace stripped. Empty pieces are filtered
    out so a stray double-period or trailing whitespace doesn't
    inject blank clauses.

    The boundary is ``period + whitespace + uppercase letter``, with
    a negative lookahead for ``If you do,`` and ``When you do,`` so the
    ``You may pay/sacrifice/discard {COST}. If you do, …`` and
    ``You may sacrifice an artifact. When you do, …`` compound
    primitives don't get split — those are matched as a single phrase
    by the effect grammar and the embedded sentence boundary inside
    them is load-bearing.
    """
    pieces = [p.strip() for p in _SENTENCE_BOUNDARY_RE.split(line)]
    return [p for p in pieces if p]


# Spell-only keyword preamble: a leading clause that's just a static
# keyword followed by its parenthesized reminder text. The keyword
# line itself contributes no ``Effect`` — its behavior is wired via
# a flag on ``CardPrinting`` (e.g. Convoke → ``has_convoke=True``).
# Stripping this preamble lets the remaining clauses parse as a
# single-effect or Sequence spell.
#
# Some keywords here may be intentionally unimplemented (the engine
# treats the spell as if the keyword weren't there). Add a name only
# after confirming the matching ``cards/eoe_spells.py`` entry sets
# the corresponding printing flag — otherwise dropping the preamble
# would silently diverge from the static implementation.
_SPELL_PREAMBLE_KEYWORDS = ("Convoke",)
_SPELL_KEYWORD_PREAMBLE_RE = re.compile(
    r"^(?:" + "|".join(re.escape(k) for k in _SPELL_PREAMBLE_KEYWORDS)
    + r") \(.+\)\.?$"
)


# Kicker preamble: a leading clause of the form
# ``Kicker <cost> (You may pay an additional <cost> as you cast this
# spell.)``. The preamble itself contributes no ``Effect`` — its cost
# is wired onto the ``CardPrinting`` via the ``kicker`` kwarg, which
# the engine uses to allow the caster to pay the additional cost at
# cast time and the spell-effect to read ``state.resolving_kicked``
# at resolve time. The cost is captured as a mana-cost string (e.g.
# ``"{1}{U}"``) and threaded onto the printing verbatim.
#
# This shape is its own preamble (separate from the
# ``_SPELL_PREAMBLE_KEYWORDS`` whitelist) because Kicker carries a
# parameter (the cost), unlike Convoke which is a bare keyword.
_KICKER_PREAMBLE_RE = re.compile(
    r"^Kicker (?P<cost>(?:\{[^}]+\})+) \(.+\)\.?$"
)


# Additional-cost preamble: a leading clause of the form
# ``As an additional cost to cast this spell, <cost-clause>.``. The
# preamble itself contributes no ``Effect`` — its behavior is wired via
# a flag on ``CardPrinting`` (e.g. ``additional_cost_sacrifice_creature_
# or_artifact=True`` for Embrace Oblivion / Scrounge for Eternity).
# Stripping this preamble lets the remaining clauses parse as a
# single-effect or Sequence spell.
#
# The cost-clause body is matched against a small whitelist of
# recognized cost shapes; each maps to a specific printing-flag dict.
# Unrecognized cost clauses leave the spell unclaimed (the preamble
# isn't dropped) so the parser doesn't silently diverge from the
# static implementation.
_ADDITIONAL_COST_PREAMBLE_RE = re.compile(
    r"^As an additional cost to cast this spell, (.+)\.$"
)
# Recognized additional-cost bodies → printing flags. Keys are the
# captured ``(.+)`` group (without trailing period); values are the
# dict of flags applied to the resulting ``CardPrinting`` via
# ``make_instant`` / ``make_sorcery``.
_ADDITIONAL_COST_BODY_FLAGS: dict[str, dict] = {
    "sacrifice an artifact or creature": {
        "additional_cost_sacrifice_creature_or_artifact": True,
    },
    "choose a creature you control or a warped creature card "
    "you own in exile": {
        "additional_cost_choose_your_creature": True,
    },
    # Final Vengeance (Duskmourn) — "sacrifice a creature or
    # enchantment" parallel to Embrace Oblivion's
    # "sacrifice an artifact or creature".
    "sacrifice a creature or enchantment": {
        "additional_cost_sacrifice_creature_or_enchantment": True,
    },
}


def _is_additional_cost_preamble(clause: str) -> bool:
    """Return ``True`` if ``clause`` is a recognized additional-cost
    preamble (``As an additional cost to cast this spell, <cost>.``
    where ``<cost>`` is one of the whitelisted cost bodies). The
    caller drops these preamble clauses before parsing the rest of
    the spell. Unrecognized cost bodies return ``False`` so the
    spell stays unclaimed rather than silently dropping the cost.
    """
    m = _ADDITIONAL_COST_PREAMBLE_RE.match(clause.strip())
    if m is None:
        return False
    return m.group(1) in _ADDITIONAL_COST_BODY_FLAGS


def _additional_cost_flags(clause: str) -> dict:
    """Return the printing-flag dict for a recognized additional-cost
    preamble ``clause``. Returns an empty dict if the clause isn't a
    recognized preamble (caller should ``_is_additional_cost_preamble``
    first to gate the call). Keeps the per-shape flag mapping
    centralized in ``_ADDITIONAL_COST_BODY_FLAGS`` so adding a new
    cost shape is a one-line entry there plus a one-line dispatch
    here is the only edit needed.
    """
    m = _ADDITIONAL_COST_PREAMBLE_RE.match(clause.strip())
    if m is None:
        return {}
    return _ADDITIONAL_COST_BODY_FLAGS.get(m.group(1), {})


def _is_spell_keyword_preamble(clause: str) -> bool:
    """Return ``True`` if ``clause`` is a recognized unimplemented
    spell-keyword preamble (keyword name + parenthesized reminder
    text). The caller drops these preamble clauses before parsing the
    rest of the spell. See ``_SPELL_PREAMBLE_KEYWORDS`` for the
    whitelist."""
    return _SPELL_KEYWORD_PREAMBLE_RE.match(clause.strip()) is not None


def _is_kicker_preamble(clause: str) -> bool:
    """Return ``True`` if ``clause`` is a Kicker preamble of the form
    ``Kicker <cost> (You may pay an additional <cost> as you cast this
    spell.)``. The caller drops these preamble clauses before parsing
    the rest of the spell. The cost is extracted separately by
    ``_kicker_cost`` and threaded onto the resulting ``CardPrinting``
    via the ``kicker`` kwarg.
    """
    return _KICKER_PREAMBLE_RE.match(clause.strip()) is not None


def _kicker_cost(clause: str) -> str | None:
    """Return the kicker cost string (e.g. ``"{1}{U}"``) for a
    recognized Kicker preamble ``clause``, or ``None`` if the clause
    isn't a Kicker preamble. The cost is the verbatim mana-cost
    string captured between ``Kicker `` and the parenthesized reminder
    — the engine accepts the same surface form on the
    ``CardPrinting.kicker_cost_str`` field, so no further parsing is
    needed here.
    """
    m = _KICKER_PREAMBLE_RE.match(clause.strip())
    if m is None:
        return None
    return m.group("cost")


def _parse_void_damage_replacement(
    phrase: str, name: str, base_effect: Effect
) -> Effect | None:
    """If ``phrase`` is a Void rider replacing the damage amount of
    ``base_effect``, return the void-branch ``Effect`` (same shape as
    base, new amount). Returns ``None`` otherwise.

    Currently only handles ``DealDamageAnyTarget`` as the base — the
    only damage shape that pairs with a Void rider in the EoE pool we
    support today (Plasma Bolt). Extend per-card as new pairings show up.
    """
    if not isinstance(base_effect, DealDamageAnyTarget):
        return None
    name_re = re.escape(name)
    m = re.match(
        _SPELL_VOID_DAMAGE_REPLACEMENT.format(name=name_re), phrase.strip()
    )
    if m is None:
        return None
    return DealDamageAnyTarget(amount=int(m.group(1)))


def _parse_void_instead_effect_rider(
    phrase: str, base_effect: Effect, name: str
) -> Effect | None:
    """If ``phrase`` is a Void "instead" rider (``Void — If a nonland
    permanent left the battlefield this turn or a spell was warped
    this turn, instead <then-effect>.``), parse the then-branch and
    return ``ConditionalIfVoid(then=then_effect, else=base_effect)``.
    Returns ``None`` if the phrase doesn't match or the then-branch
    doesn't parse.

    The "instead" keyword means the rider replaces the base effect
    entirely when Void is active (distinct from the adds-draw rider
    which appends, and from the damage/pump replacement helpers which
    swap a specific field). The ``else_effect`` is the original
    ``base_effect`` — the spell resolves as the base when Void is not
    active.

    Currently supports any parseable then-branch; no restriction on
    the base-effect type. The only EoE/Duskmourn card using this shape
    today is Decode Transmissions (base = ``Sequence(DrawCards(2),
    LoseLife(2))``, then = ``Sequence(DrawCards(2), EachOpponentLosesLife
    (2))`` parsed from ``"you draw two cards and each opponent loses 2
    life"``). Extend as new "instead" Void riders ship.
    """
    m = _SPELL_VOID_INSTEAD_EFFECT_RE.match(phrase.strip())
    if m is None:
        return None
    then_phrase = m.group(1).strip()
    then_effect = _parse_spell_effect_phrase(then_phrase, name)
    if then_effect is None:
        return None
    return ConditionalIfVoid(
        then_effect=then_effect,
        else_effect=base_effect,
    )


def _is_void_adds_draw_rider(phrase: str) -> bool:
    """Return ``True`` if ``phrase`` is the Void "adds-a-draw" rider
    from Hymn of the Faller:
    ``"Void — If a nonland permanent left the battlefield this turn
    or a spell was warped this turn, draw another card."``

    This rider runs an *additional* ``DrawCards(1)`` on top of the
    base effects (not a replacement like the damage/pump helpers).
    When paired with a Sequence base effect, the caller wraps the
    base Sequence with an appended
    ``ConditionalIfVoid(then=DrawCards(1), else=None)`` clause.
    """
    return _SPELL_VOID_ADDS_DRAW_RE.match(phrase.strip()) is not None


def _parse_void_pump_replacement(
    phrase: str, base_effect: Effect
) -> Effect | None:
    """If ``phrase`` is a Void rider replacing the pump bonuses of
    ``base_effect``, return the void-branch ``Effect`` (same shape as
    base, new bonuses). Returns ``None`` otherwise.

    Currently only handles ``PumpTargetCreatureUntilEOT`` as the base —
    the only pump shape that pairs with a Void rider in the EoE pool
    we support today (Tragic Trajectory). The carry-over subject
    ``That creature`` refers back to the target chosen on the first
    clause; the engine reuses the same target when resolving either
    branch (single-target spell).

    Mirrors the structure of ``_parse_void_damage_replacement`` —
    keeping the two as separate helpers (vs one polymorphic function)
    keeps the per-shape regex literal explicit and the per-shape
    engine class wiring obvious. Extend per-card as new pairings
    surface; e.g. a future Void rider replacing
    ``DealDamageToTargetCreature`` would land as a third helper.

    The ``base_effect``'s bonuses are not used to compute the void
    branch — only the type is matched. The void branch's bonuses
    come entirely from the rider clause itself.
    """
    if not isinstance(base_effect, PumpTargetCreatureUntilEOT):
        return None
    m = _SPELL_VOID_PUMP_REPLACEMENT.match(phrase.strip())
    if m is None:
        return None
    return PumpTargetCreatureUntilEOT(
        power_bonus=int(m.group(1)),
        toughness_bonus=int(m.group(2)),
    )


def _parse_modal_choose_one(
    clauses: list[str], name: str
) -> Effect | None:
    """If ``clauses`` is a ``Choose one —`` or ``Choose one or both —``
    modal-spell shape, return the corresponding ``ModalChooseOne``
    effect; otherwise ``None``.

    Recognized shapes (from Scryfall printed text):

      ``Choose one —``               (or ``Choose one or both —``)
      ``• <mode 1 sentence>``
      ``• <mode 2 sentence>``
      ``• <mode 3 sentence>``  (optional)
      ...

    Each mode line is parsed by ``_parse_spell_effect_phrase`` after
    stripping the leading ``• `` (bullet + space).

    **All-or-nothing rule (normal path):** if all modes parse, returns
    ``ModalChooseOne(modes=(...), or_both=or_both)`` so the engine routes
    mode-pick through the agent's ``choose_modes`` hook.

    **Exactly-one-parseable fallback (parser-is-right):** if the mode
    lines are all well-formed bullets but EXACTLY ONE mode parses (the
    rest return ``None``), the parser returns that one mode's effect
    directly rather than ``ModalChooseOne``. This matches the same
    "parser-is-right" simplification the whole-spell exact-text table
    already ships for Get Out (mode 1 = counter creature/enchantment;
    mode 2 unrecognized) and Untimely Malfunction (mode 1 = destroy
    artifact; modes 2–3 unrecognized). The engine can only model the
    parseable mode anyway, so presenting the spell as a non-modal spell
    with that fixed effect is the most faithful available representation
    given the current grammar.

    If TWO OR MORE modes parse but not all, the function returns ``None``
    (the spell stays unclaimed) — a multi-mode partial parse can't be
    simplified to a single fixed effect without ambiguity about WHICH
    parseable mode to use.

    A header by itself (zero mode lines) or a header with exactly one
    mode line is rejected — printed modal spells always have at least
    two modes. ``Choose two`` and other variants don't match either
    header regex and fall through. The ``or both`` shape constructs
    ``ModalChooseOne(or_both=True)`` so the engine routes mode-pick
    through the agent's ``choose_modes`` (plural) hook.
    """
    if not clauses:
        return None
    if _MODAL_CHOOSE_ONE_HEADER_RE.match(clauses[0]) is not None:
        or_both = False
    elif _MODAL_CHOOSE_ONE_OR_BOTH_HEADER_RE.match(clauses[0]) is not None:
        or_both = True
    elif _DELIRIUM_MODAL_HEADER_RE.match(clauses[0]) is not None:
        # ``Delirium — Choose one. If there are four or more card types
        # among cards in your graveyard, choose one or more instead.``
        # (Let's Play a Game). Treated as a bare ``Choose one —`` shape
        # (``or_both=False``) — the Delirium upgrade to "choose one or
        # more instead" is dropped because the engine has no Delirium-
        # conditional modal-count combinator today.  The mode lines that
        # follow still parse normally through the unified per-mode
        # grammar; the printed Delirium threshold is silently discarded.
        or_both = False
    else:
        return None
    mode_lines = clauses[1:]
    if len(mode_lines) < 2:
        return None
    # Try to parse every mode. Collect (index, effect) pairs for the
    # modes that parse cleanly; track which are malformed bullets.
    parsed_modes: list[Effect] = []
    malformed = False
    for line in mode_lines:
        m = _MODAL_MODE_LINE_RE.match(line)
        if m is None:
            # Bullet not recognized → whole modal shape is unclaimed
            # (a non-bullet line inside a modal body is unexpected and
            # may indicate a multi-line mode, which we don't support).
            malformed = True
            break
        eff = _parse_spell_effect_phrase(m.group(1), name)
        if eff is not None:
            parsed_modes.append(eff)
        # else: append None placeholder? No — we only collect parseable modes.
    if malformed:
        return None
    if len(parsed_modes) == len(mode_lines):
        # All modes parse → full ModalChooseOne.
        return ModalChooseOne(modes=tuple(parsed_modes), or_both=or_both)
    if len(parsed_modes) == 1 and not or_both:
        # Exactly one mode parseable (and this is a "Choose one —" spell,
        # not "Choose one or both —") → parser-is-right: return that mode's
        # effect directly. Same simplification as Get Out (mode 1 = counter
        # creature/enchantment spell; mode 2 unrecognized) and Untimely
        # Malfunction (mode 1 = destroy artifact; modes 2–3 unrecognized).
        # The "or both" guard ensures "Choose one or both —" spells stay
        # unclaimed when not all modes parse — losing the or_both semantics
        # would silently misbehave if the parseable mode is returned alone.
        return parsed_modes[0]
    # Zero parseable, or 2+ parseable but not all, or or_both with any
    # unrecognized mode → unclaimed.
    return None


# Whole-spell exact-text dispatch table. Each key is the full oracle
# text after reminder-text stripping (parenthesized reminder tail
# removed) but BEFORE sentence splitting — i.e. exactly what a single
# oracle-text line looks like once parentheticals are gone. The value
# is the engine-class instance that the static registry uses for that
# card.
#
# This tier exists for spells whose oracle text is a single sentence-
# block that the static registry models with a one-off engine class
# (no reusable primitive is meaningful). The per-clause grammar
# couldn't claim these because at least one of their internal
# sentences (e.g. ``If that creature has flying, it deals twice that
# much damage to itself instead.``) doesn't parse as a standalone
# effect — and matching the per-sentence grammar to those forms
# would yield primitives no other card uses.
#
# Entries here must be exact verbatim oracle text (post reminder
# stripping). A future printing whose oracle text differs by even
# one character won't match — by design, since this tier is for
# named one-offs, not a reusable shape.
_WHOLE_SPELL_EXACT_TEXT: dict[str, Effect] = {
    # Cut Propulsion: target creature self-damages by its power; if
    # it has flying, it self-damages twice that amount instead.
    (
        "Target creature deals damage to itself equal to its power. "
        "If that creature has flying, "
        "it deals twice that much damage to itself instead."
    ): CutPropulsionEffect(),
    # Mutinous Massacre: parity-of-mana-value wrath + steal-and-haste
    # all-creatures rider. Reminder tail ``(Zero is even.)`` is
    # stripped before lookup.
    (
        "Choose odd or even. "
        "Destroy each creature with mana value of the chosen quality. "
        "Then gain control of all creatures until end of turn. "
        "Untap them. They gain haste until end of turn."
    ): MutinousMassacreEffect(),
    # Depressurize — "Target creature gets -3/-0 until end of turn. Then
    # if that creature's power is 0 or less, destroy it." — migrated to
    # per-clause grammar: the new ``_DEPRESSURIZE`` recognizer in
    # ``effects.py`` matches the full two-sentence body verbatim as a
    # multi-sentence literal (the second sentence's "that creature" is
    # anaphoric to the debuff target) and returns
    # ``DepressurizeEffect(power_penalty=3)``.
    # Diplomatic Relations: pump-and-grant-vigilance on your creature
    # plus a fight-shaped damage rider where the chosen first target
    # deals damage equal to its (post-pump) power to a chosen second
    # target an opponent controls. Two-target spell — the bespoke
    # class threads both targets through one resolve step.
    (
        "Target creature you control gets +1/+0 and gains vigilance "
        "until end of turn. It deals damage equal to its power to "
        "target creature an opponent controls."
    ): DiplomaticRelationsEffect(),
    # Biosynthic Burst: counter + grant-three-keywords + untap on a
    # creature you control. The static class wires the +1/+1 counter,
    # the reach/trample/indestructible UEOT grant, and the untap into
    # one resolve.
    (
        "Put a +1/+1 counter on target creature you control. "
        "It gains reach, trample, and indestructible until end of "
        "turn. Untap it."
    ): BiosynthicBurstEffect(),
    # Cerebral Download — "Surveil X, where X is the number of artifacts
    # you control. Then draw three cards." — migrated to per-clause
    # grammar: the new ``_SURVEIL_X_ARTIFACT_COUNT`` recognizer in
    # ``effects.py`` claims the first sentence as
    # ``Surveil(amount=1, use_artifact_count=True)`` and ``_DRAW_N_CARDS``
    # claims "draw three cards" (after ``_split_effect_sentences`` strips
    # the leading "then "); the Sequence combinator assembles the pair.
    # Desculpting Blast: bounce-target-permanent + a Drone-token
    # rider for the attacking-permanent branch. The bespoke engine
    # class folds the rider into one resolve step.
    (
        "Return target nonland permanent to its owner's hand. "
        "If it was attacking, create a 1/1 colorless Drone artifact "
        "creature token with flying and \"This token can block only "
        "creatures with flying.\""
    ): ReturnTargetCreatureToOwnersHand(
        allow_nonland_permanent=True,
        create_drone_if_was_attacking=True,
    ),
    # Scout for Survivors: return up to three small creature cards
    # from graveyard to battlefield, each with a +1/+1 counter.
    (
        "Return up to three target creature cards with total mana "
        "value 3 or less from your graveyard to the battlefield. "
        "Put a +1/+1 counter on each of them."
    ): ReturnUpToNSmallCreaturesFromGraveyardWithCounters(
        max_n=3, max_total_mv=3,
    ),
    # Zero Point Ballad: variable-X wrath + life-pay + reanimation
    # rider. The bespoke engine class folds all three into one
    # resolve step.
    (
        "Destroy all creatures with toughness X or less. You lose "
        "X life. If X is 6 or more, return a creature card put into "
        "a graveyard this way to the battlefield under your control."
    ): ZeroPointBalladEffect(),
    # Systems Override: gain-control + untap + grant-haste plus a
    # Spacecraft-only charge-counter rider. The bespoke engine
    # class threads all four steps through one resolve, including
    # the end-step counter-removal scheduling.
    (
        "Gain control of target artifact or creature until end of "
        "turn. Untap that permanent. It gains haste until end of "
        "turn. If it's a Spacecraft, put ten charge counters on it. "
        "If you do, remove ten charge counters from it at the "
        "beginning of the next end step."
    ): SystemsOverrideEffect(),
    # Devastating Onslaught: variable-X token-copy spell with haste
    # and end-step sac. The X-formula sits on the spell's mana cost
    # ({X}{X}{R}) and is resolved through the engine class at cast
    # time.
    (
        "Create X tokens that are copies of target artifact or "
        "creature you control. Those tokens gain haste until end "
        "of turn. Sacrifice them at the beginning of the next end "
        "step."
    ): CreateXTokensOfTargetPermanentWithHasteEndStepSac(),
    # Nexus of Fate — "Take an extra turn after this one.\nIf Nexus of
    # Fate would be put into a graveyard from anywhere, reveal Nexus of
    # Fate and shuffle it into its owner's library instead." — migrated
    # to per-clause grammar: the new ``_TAKE_EXTRA_TURN_AFTER_THIS_ONE``
    # recognizer in ``effects.py`` claims the first clause as
    # ``TakeExtraTurnAfterThisOne()``; the Nexus self-shuffle rider (second
    # line) is dropped by the new ``_is_self_shuffle_clause`` dropper, and
    # the ``shuffles_into_library_instead_of_graveyard`` printing flag is
    # wired separately by ``_detect_shuffle_self_flags``.
    # Green Sun's Zenith — "Search your library for a green creature
    # card with mana value X or less, put it onto the battlefield, then
    # shuffle. Shuffle Green Sun's Zenith into its owner's library." —
    # migrated to per-clause grammar: the new
    # ``_SEARCH_LIBRARY_GREEN_CREATURE_X_TO_BATTLEFIELD`` recognizer in
    # ``effects.py`` claims the first sentence as
    # ``SearchLibraryForGreenCreatureWithMVAtMostX()``; the GSZ self-shuffle
    # rider (second sentence on the same oracle line, split off by
    # ``_split_sentences``) is dropped by ``_is_self_shuffle_clause``, and
    # the ``shuffles_into_library_instead_of_graveyard`` printing flag is
    # wired separately by ``_detect_shuffle_self_flags``.
    # Consult the Star Charts: variable-X library look + kicker-gated
    # extra card kept. The static ships ``ConsultTheStarChartsEffect()``
    # (no parameters; the bespoke class handles the X-formula and the
    # kicked vs unkicked branch by reading ``state.resolving_kicked``).
    # The leading Kicker preamble line is detected separately by
    # ``_detect_kicker_cost`` and threaded onto the printing via the
    # ``kicker`` kwarg; the dispatcher returns only the spell-effect.
    # The dispatch key carries the full text including the Kicker
    # preamble — the dispatcher hits BEFORE the per-clause preamble-
    # stripping pass, so the key has to mirror the printed text
    # verbatim.
    (
        "Kicker {1}{U}\n"
        "Look at the top X cards of your library, where X is the "
        "number of lands you control. Put one of those cards into "
        "your hand. If this spell was kicked, put two of those cards "
        "into your hand instead. Put the rest on the bottom of your "
        "library in a random order."
    ): ConsultTheStarChartsEffect(),
    # Close Encounter: directed power-as-damage burn whose source-of-
    # power is chosen as an additional cost to casting (a creature you
    # control or a warped creature card you own in exile). The static
    # ships ``CloseEncounterEffect()`` with the
    # ``additional_cost_choose_your_creature`` printing flag; the flag
    # is detected separately via ``_detect_additional_cost_flags``,
    # which routes the body phrase through ``_ADDITIONAL_COST_BODY_
    # FLAGS``. The dispatch key includes the full additional-cost
    # preamble line — the dispatcher hits BEFORE the per-clause
    # preamble-stripping pass, so the key has to mirror the printed
    # text verbatim.
    (
        "As an additional cost to cast this spell, choose a creature "
        "you control or a warped creature card you own in exile.\n"
        "Close Encounter deals damage equal to the power of the "
        "chosen creature or card to target creature."
    ): CloseEncounterEffect(),
    # Lithobraking — "Create a Lander token. Then you may sacrifice an
    # artifact. When you do, Lithobraking deals 2 damage to each
    # creature." — migrated to per-clause grammar: the new
    # ``_SENTENCE_BOUNDARY_RE`` fix (extending the "don't split before
    # 'If/When you do,'" negative lookahead to also cover "When you do,")
    # keeps "Then you may sacrifice an artifact. When you do, …" as a
    # single unsplit clause; the new ``_YOU_MAY_SAC_ARTIFACT_WHEN_YOU_DO``
    # recognizer in ``effects.py`` claims it as
    # ``OptionalSacArtifactForEffect(DealNDamageToEachCreature(2))``.
    # The ``Then`` prefix stripping in ``_normalize_spell_effect_phrase``
    # lets the first clause "Create a Lander token." parse via the bare
    # token-creation path; the two clauses combine as a Sequence.
    # Unravel — "Counter target spell. If the amount of mana spent to
    # cast that spell was less than its mana value, you draw a card."
    # — migrated to per-clause grammar: ``CounterTargetSpell()``
    # claims the first sentence and the
    # ``_is_unimplemented_secondary_rider`` dropper silently discards
    # the ``If the amount of mana spent…`` mana-spent-conditional
    # draw rider (the engine doesn't track per-spell cast-time mana
    # accounting).
    # Divert Disaster — "Counter target spell unless its controller
    # pays {2}. If they do, you create a Lander token." — migrated to
    # per-clause grammar: the new ``_COUNTER_TARGET_SPELL_UNLESS_PAYS``
    # recognizer claims the first sentence as ``CounterTargetSpell()``
    # (dropping the pay-or-counter branching) and the
    # ``_is_unimplemented_secondary_rider`` dropper silently discards
    # the ``If they do, …`` consequent.
    # Don't Make a Sound — "Counter target spell unless its controller
    # pays {2}. If they do, surveil 2." — same migration as Divert
    # Disaster.
    # Scrounge for Eternity — "As an additional cost to cast this spell,
    # sacrifice an artifact or creature.\nReturn target creature or
    # Spacecraft card with mana value 5 or less from your graveyard to
    # the battlefield. Then create a Lander token." — migrated to per-
    # clause grammar: the additional-cost preamble is recognized by
    # ``_is_additional_cost_preamble`` and stripped; the second clause
    # ("Return … Then create a Lander token.") is split by
    # ``_split_sentences`` into "Return target creature or Spacecraft
    # card with mana value 5 or less from your graveyard to the
    # battlefield." (new ``_RETURN_TARGET_CREATURE_OR_SPACECRAFT_
    # GRAVEYARD_TO_BATTLEFIELD_WITH_MV`` recognizer →
    # ``ReturnCreatureFromYourGraveyardToBattlefield(or_spacecraft=True,
    # max_mv=5)``) and "Then create a Lander token." (``Then`` prefix
    # stripped by ``_normalize_spell_effect_phrase``, then parsed via
    # ``_CREATE_BARE_NAME_TOKEN`` → ``CreateToken(Lander, 1)``).
    # The two clauses combine as a Sequence.
    # Terminal Velocity: put-card-from-hand onto battlefield + haste +
    # death-trigger + end-step-sac. Complex triple-rider oracle text
    # that the per-clause grammar can't parse; the static ships a
    # ``CreateToken(Robot, count=2)`` simplification. Match the full
    # printed oracle text verbatim; reminder text is stripped before
    # dispatch so the outer parentheticals are already removed.
    (
        "You may put an artifact or creature card from your hand onto "
        "the battlefield. That permanent gains haste, \"When this "
        "permanent leaves the battlefield, it deals damage equal to "
        "its mana value to each creature,\" and \"At the beginning of "
        "your end step, sacrifice this permanent.\""
    ): CreateToken(
        token_printing=TOKEN_PRINTINGS["Robot"], count=2
    ),
    # Pull Through the Weft — "Return up to two target nonland permanent
    # cards from your graveyard to your hand, then return up to two
    # target land cards from your graveyard to the battlefield tapped."
    # — migrated to per-clause grammar: the new
    # ``_RETURN_UP_TO_N_NONLAND_PERMANENT_GY_TO_HAND_THEN_LANDS_BF_TAPPED``
    # recognizer in ``effects.py`` claims the full compound sentence as
    # ``ReturnUpToNNonlandPermanentCardsFromGraveyardToHand(max_n=2,
    # min_n=0)``, dropping the second compound piece ("then return up to
    # two target land cards…") as an unimplemented rider. This is MORE
    # faithful than the previous simplification which returned bare
    # ``ReturnCreatureFromYourGraveyardToHand()`` (dropping both the
    # multi-target count and the nonland-permanent scope widening).
    # Scorching Dragonfire (Duskmourn) — "Scorching Dragonfire deals 3
    # damage to target creature or planeswalker. If that creature or
    # planeswalker would die this turn, exile it instead." — migrated
    # to per-clause grammar: ``DealDamageToTargetCreature(amount=3)``
    # claims the first sentence (the ``_DEAL_DAMAGE_TARGET_CREATURE``
    # regex now accepts the optional ``or planeswalker`` tail, dropping
    # the planeswalker scope per the same precedent as Archenemy's
    # Charm mode 1) and the ``_is_unimplemented_secondary_rider``
    # dropper silently discards the exile-on-death rider (the engine
    # has no UEOT-scoped exile-instead-of-die replacement-effect
    # registry for targeted permanents).
    # Unwanted Remake (Duskmourn) — "Destroy target creature. Its
    # controller manifests dread." — migrated to per-clause grammar:
    # ``DestroyTargetCreature()`` claims the first sentence and the
    # ``_is_unimplemented_secondary_rider`` dropper silently discards
    # the ``Its controller manifests dread.`` rider (the engine's
    # ``ManifestDread`` primitive resolves for the CASTER's hand, not
    # the destroyed permanent's controller's hand; the back-reference
    # plumbing required is a non-trivial engine widening).
    # Jump Scare (Duskmourn) — "Until end of turn, target creature
    # gets +2/+2, gains flying, and becomes a Horror enchantment
    # creature in addition to its other types." — migrated to per-
    # clause grammar: the new ``_PUMP_LEADING_UEOT_KEYWORDS_BECOMES_TYPE``
    # recognizer in ``effects.py`` claims the full sentence as
    # ``PumpTargetCreatureUntilEOT(power_bonus=2, toughness_bonus=2,
    # granted_keywords={"flying"})``, dropping the unimplemented
    # type-change rider ("becomes a Horror enchantment creature in
    # addition to its other types") per the parser-is-right simplification
    # precedent (Unravel, Divert Disaster).
    # Vengeful Possession (Duskmourn) — gain-control + untap +
    # haste UEOT plus an optional looter rider ("You may discard a
    # card. If you do, draw a card."). The static side ships
    # ``VengefulPossessionEffect()`` which mirrors Systems
    # Override's gain-control + untap + haste skeleton, narrowed to
    # creature targets and stripped of the Spacecraft charge-counter
    # rider. The optional looter rider is dropped on the parser
    # side per the parser-is-right precedent — the bare base
    # mechanic (gain-control + untap + haste UEOT) is what the
    # engine models cleanly; the optional looter rider would need a
    # new ``OptionalDiscardThenDraw`` primitive that no other DSK
    # spell needs today.
    (
        "Gain control of target creature until end of turn. "
        "Untap it. It gains haste until end of turn. "
        "You may discard a card. If you do, draw a card."
    ): VengefulPossessionEffect(),
    # Coordinated Clobbering (Duskmourn) — two-clause multi-target
    # spell: tap 1-2 friendly untapped creatures, then each deals
    # power-as-damage to one target opp creature. The static ships
    # ``CoordinatedClobberingEffect()`` which uses the cast-pipeline
    # ``target_count_range=(2, 3)`` + ``target_slot_kinds=("creature",
    # "my_creature", "my_creature")`` skeleton — opp creature first
    # (mandatory slot 0), then 1-2 friendlies (slot 1 mandatory,
    # slot 2 optional via min_t-gate). The whole-spell tier is the
    # right place because the per-clause grammar has no two-target-
    # group multi-attacker shape; the existing
    # ``DiplomaticRelationsEffect`` precedent uses the same
    # ``my_creature`` slot kind for a fixed 2-slot spell, and
    # extending the per-clause grammar would over-engineer for one
    # card.
    (
        "Tap one or two target untapped creatures you control. "
        "They each deal damage equal to their power to target "
        "creature an opponent controls."
    ): CoordinatedClobberingEffect(),
    # Trial of Agony (Duskmourn) ``{R}`` Sorcery — single-line spell
    # with a multi-target opp-choice burn shape: caster picks two
    # creatures controlled by the same opponent; that opponent chooses
    # which of the two takes 5 damage; the other "can't block this
    # turn" rider applies UEOT. The static side simplifies to bare
    # ``DealDamageToTargetCreature(amount=5)`` because:
    # (1) the engine has no two-target same-controller slot-kind
    #     ("opp_pair") nor an opponent-side mode-pick hook for picking
    #     which of two chosen targets the burn lands on (the existing
    #     ``my_creature`` / ``creature`` slot kinds and modal-mode
    #     picks both run on the SPELL's controller, not the opp);
    # (2) the engine has no per-creature ``cant_block_this_turn`` flag
    #     to set on the unhit target — wiring one would require new
    #     fields on ``GameObject`` and a guard in combat's declare-
    #     blockers step, beyond the parser's scope.
    # Same parser-is-right precedent as Unravel / Divert Disaster /
    # Scorching Dragonfire — claim the bare base mechanic (5-damage
    # burn) and drop the multi-target opp-choice + can't-block riders
    # rather than leaving the spell unclaimed for unmodeled riders.
    # The per-clause grammar can't claim this spell either: the first
    # sentence ``Choose two target creatures controlled by the same
    # opponent.`` doesn't match any spell-effect shape in the unified
    # grammar (no other card uses the "choose two creatures controlled
    # by the same opponent" target framing), so the whole-spell tier is
    # the right place to land the simplification.
    (
        "Choose two target creatures controlled by the same opponent. "
        "That player chooses one of those creatures. Trial of Agony "
        "deals 5 damage to that creature, and the other can't block "
        "this turn."
    ): DealDamageToTargetCreature(amount=5),
    # Under the Skin (Duskmourn) — "Manifest dread.\nYou may return a
    # permanent card from your graveyard to your hand." — migrated to
    # per-clause grammar: ``ManifestDread()`` claims the first
    # sentence and the ``_is_unimplemented_secondary_rider`` dropper
    # silently discards the ``You may return a permanent card from
    # your graveyard to your hand.`` optional rider (every existing
    # ``Return*FromGraveyardToHand`` primitive is creature-typed;
    # widening to "any permanent card" with optionality for a single
    # card's rider is a non-trivial engine change).
    # Midnight Mayhem (Duskmourn) — "Create three 1/1 red Gremlin
    # creature tokens. Gremlins you control gain menace, lifelink, and
    # haste until end of turn." — migrated to per-clause grammar:
    # ``CreateToken(Gremlin, count=3)`` claims the first sentence and
    # the ``_is_unimplemented_secondary_rider`` dropper silently
    # discards the ``Gremlins you control gain…`` subtype-filtered
    # UEOT keyword-grant rider (the engine's
    # ``PumpCreaturesYouControlUntilEOT`` applies to ALL your
    # creatures; a subtype-filtered variant is a non-trivial engine
    # change for a single card's rider). The trailing parenthesized
    # menace reminder text is stripped before dispatch.
    # Get Out (Duskmourn) ``{U}{U}`` Instant — migrated to per-clause
    # grammar in bespoke-spells3: the new "exactly-one-parseable-mode"
    # fallback in ``_parse_modal_choose_one`` returns the first parseable
    # mode's effect directly when exactly ONE mode parses and the rest
    # are unrecognized. Mode 1 "Counter target creature or enchantment
    # spell." parses as ``CounterTargetSpell(filter_types=frozenset(
    # {"Creature","Enchantment"}))``. Mode 2 "Return one or two target
    # creatures and/or enchantments you own to your hand." has no
    # per-mode primitive, so the exactly-one fallback fires and returns
    # mode 1's effect. Same parser-is-right simplification as before.
    # Untimely Malfunction (Duskmourn) ``{1}{R}`` Instant — same fallback:
    # mode 1 "Destroy target artifact." → ``DestroyTargetArtifact()``;
    # modes 2+3 unrecognized → exactly-one fallback returns mode 1.
    # Unnerving Grasp (Duskmourn) ``{2}{U}`` Sorcery — migrated to
    # per-clause grammar in bespoke-spells3: two new grammar extensions
    # enable the migration:
    # (1) The new ``_RETURN_UP_TO_ONE_TARGET_NONLAND_PERMANENT_TO_OWNERS_HAND``
    #     recognizer in ``effects.py`` claims "Return up to one target
    #     nonland permanent to its owner's hand." as
    #     ``ReturnTargetCreatureToOwnersHand(allow_nonland_permanent=True,
    #     optional=True)``.
    # (2) The new ``Sequence.target_count_range()`` override in
    #     ``combinators.py`` fixes the cast-pipeline bug that previously
    #     caused the optional bounce in a Sequence to silently receive no
    #     target (the override now walks sub-effects to sum their actual
    #     (min, max) target counts, so the cast pipeline correctly offers
    #     an optional target for ``count_min=0, count_max=1`` sub-effects).
    # Together these produce ``Sequence(ReturnTargetCreatureToOwnersHand(
    # allow_nonland_permanent=True, optional=True), ManifestDread())``
    # which is MORE faithful than the previous ``ManifestDread(count=1)``
    # simplification that dropped the optional bounce entirely.
    # Commune with Evil (Duskmourn) ``{2}{B}`` Sorcery — migrated to
    # per-clause grammar: the new
    # ``_LOOK_TOP_N_PUT_ONE_IN_HAND_REST_TO_GRAVEYARD_GAIN_M_LIFE``
    # three-sentence recognizer in ``effects.py`` matches the full
    # oracle text as a single effect-phrase (before sentence splitting)
    # and returns ``Sequence(LookTopNPutOneInHandRestToGraveyard(4),
    # GainLife(3))``. This is more faithful than the previous
    # ``CommuneWithEvilEffect()`` atomic class: the two sub-effects
    # resolve as separate steps, matching the printed structure of three
    # independent sentences.
    # Turn Inside Out (Duskmourn) — "Target creature gets +3/+0 until
    # end of turn. When it dies this turn, manifest dread." — migrated
    # to per-clause grammar: ``PumpTargetCreatureUntilEOT(3, 0)``
    # claims the first sentence and the
    # ``_is_unimplemented_secondary_rider`` dropper silently discards
    # the ``When it dies this turn, manifest dread.`` death-trigger
    # rider (the engine has no UEOT-scoped per-target death-trigger
    # registry; adding one for a single card's rider is a non-trivial
    # engine widening).
    # Come Back Wrong (Duskmourn) — "Destroy target creature. If a
    # creature card is put into a graveyard this way, return it to the
    # battlefield under your control. Sacrifice it at the beginning of
    # your next end step." — migrated to per-clause grammar:
    # ``DestroyTargetCreature()`` claims the first sentence and the
    # general N-clause ``_is_unimplemented_secondary_rider`` dropper
    # silently discards the conditional-reanimate-this-way rider and
    # the delayed-end-step-sac trigger (the engine has no
    # "destroyed-this-way conditional reanimate" primitive and no
    # per-object one-shot delayed end-step sacrifice registry).
}


def _try_whole_spell_exact_text(text: str) -> Effect | None:
    """If ``text`` (post reminder-text stripping) exactly matches a
    whole-spell entry in ``_WHOLE_SPELL_EXACT_TEXT``, return the
    associated engine-class instance; otherwise ``None``.

    Tried at the top of ``_parse_spell_oracle_text`` BEFORE the
    per-clause grammar runs. Each key is exact-match, so the
    dispatch is O(1) per spell — no risk of accidentally catching
    spells whose text overlaps a key.
    """
    return _WHOLE_SPELL_EXACT_TEXT.get(text.strip())


def _parse_spell_oracle_text(text: str, name: str) -> Effect | None:
    """Parse a spell's full oracle text into a single ``Effect``.

    Single-line: parsed by ``_parse_spell_effect_phrase`` directly.
    Multi-line: each ``\\n``-separated clause is parsed; clauses are
    combined either via ``ConditionalIfVoid`` (when the second clause
    is a Void replacement of the first damage effect), via
    ``ModalChooseOne`` (Scryfall ``Choose one —`` or
    ``Choose one or both —`` shape), or via ``Sequence`` (every clause
    is a plain spell-effect sentence).
    Leading clauses that are unimplemented spell-keyword preambles
    (e.g. Vote Out's Convoke) are dropped before combinator dispatch
    so they don't fail the per-clause parse. ``This spell costs {N}
    less to cast if <condition>.`` cost-reduction riders are likewise
    dropped here — the rule is captured separately by
    ``_detect_cost_reductions`` and threaded onto the resulting
    ``CardPrinting`` via the ``cost_reductions`` kwarg.

    A single oracle-text line that packs two effect sentences
    separated by ``. `` (Radiant Strike's
    ``"Destroy target artifact or tapped creature. You gain 3 life."``,
    Sami's Curiosity's ``"You gain 2 life. Create a Lander token."``)
    is further carved at the sentence boundary by ``_split_sentences``
    after reminder-text stripping and cost-reduction dropping. Each
    resulting sentence is then a clause in its own right — the
    Sequence combinator path picks them up the same way it would for
    a printing that put each sentence on its own ``\\n``-separated
    line. Returns ``None`` if any surviving clause fails to parse.
    """
    # Whole-spell exact-text dispatch: try a one-off engine-class
    # match against the full reminder-stripped oracle text BEFORE
    # any clause-level processing. Reserved for cards whose oracle
    # text is a single sentence-block modeled by a dedicated engine
    # class with no parameters — see ``_WHOLE_SPELL_EXACT_TEXT`` for
    # the full table.
    stripped_full = _strip_reminder_text(text)
    if stripped_full:
        whole = _try_whole_spell_exact_text(stripped_full)
        if whole is not None:
            return whole
    clauses = [c.strip() for c in text.split("\n") if c.strip()]
    # Drop leading spell-keyword preambles BEFORE per-clause reminder
    # stripping. The preamble shape (``"Convoke (...)"``) is recognized
    # via the trailing parenthesized reminder, so we have to detect
    # those preamble clauses while their parentheses are still intact.
    while clauses and _is_spell_keyword_preamble(clauses[0]):
        clauses = clauses[1:]
    # Drop leading recognized additional-cost preambles. The preamble
    # itself contributes no ``Effect`` — the corresponding printing
    # flag is threaded onto the resulting ``CardPrinting`` separately
    # via ``_detect_additional_cost_flags`` (called from
    # ``_build_spell_printing``). Unrecognized cost bodies leave the
    # preamble in place; the spell will fail to parse downstream and
    # stay unclaimed rather than silently dropping the cost.
    while clauses and _is_additional_cost_preamble(clauses[0]):
        clauses = clauses[1:]
    # Drop a leading Kicker preamble. The kicker cost is threaded onto
    # the ``CardPrinting`` separately via ``_detect_kicker_cost``
    # (called from ``_build_spell_printing``); the preamble line
    # itself contributes no ``Effect``.
    while clauses and _is_kicker_preamble(clauses[0]):
        clauses = clauses[1:]
    # Now drop per-clause parenthesized reminder text. Empty results
    # (a clause that was nothing but a parenthetical) are filtered out.
    clauses = [
        stripped
        for stripped in (_strip_reminder_text(c) for c in clauses)
        if stripped
    ]
    # Drop Delirium-prefix rider clauses BEFORE the cost-reduction pass.
    # These ``Delirium — …`` lines are unimplemented mechanics that the
    # parser drops entirely — doing so before the cost-reduction pass
    # ensures that Delirium cost-reduction lines (Drag to the Roots's
    # ``Delirium — This spell costs {2} less to cast as long as …``)
    # are not forwarded to ``_detect_cost_reductions`` and do not
    # produce spurious ``CostReduction`` rules on the printing.
    clauses = [c for c in clauses if not _is_delirium_drop_clause(c)]
    # Drop recognized cost-reduction rider clauses — they don't
    # contribute an ``Effect`` (the engine consumes them at cast time
    # via ``CostReduction`` rules on the printing). ``_build_spell_
    # printing`` calls ``_detect_cost_reductions`` separately to thread
    # those rules onto the resulting ``CardPrinting``.
    clauses = [
        c for c in clauses if _parse_cost_reduction_line(c) is None
    ]
    # Carve any line that packs two effect sentences on a single
    # ``. ``-separated line into independent clauses. Done AFTER
    # reminder-text stripping (so quoted/parenthesized inner periods
    # don't fire) and AFTER cost-reduction dropping (so a multi-
    # sentence rider — none ship today, but defensive — never gets
    # half-dropped). Single-sentence clauses round-trip unchanged.
    #
    # A clause whose full multi-sentence text already matches a per-
    # clause grammar primitive (e.g. Orbital Plunge's
    # ``X deals 6 damage to target creature. If excess damage was
    # dealt this way, create a Lander token.`` → the dedicated multi-
    # sentence recognizer in ``effects.py``) is kept whole — splitting
    # would carve the rider's anaphoric ``If`` clause into a piece
    # that has no standalone primitive. Per-clause recognizers that
    # match the unsplit text take precedence; only clauses that fail
    # to parse whole are split into per-sentence pieces.
    new_clauses: list[str] = []
    for c in clauses:
        if _parse_spell_effect_phrase(c, name) is not None:
            new_clauses.append(c)
        elif _DELIRIUM_MODAL_HEADER_RE.match(c) is not None:
            # The Delirium modal header ``Delirium — Choose one. If
            # there are four or more card types …, choose one or more
            # instead.`` is a two-sentence clause that must NOT be
            # split: splitting would carve it into a bare
            # ``Delirium — Choose one.`` fragment (which the modal
            # parser won't recognize) and a dangling ``If …``
            # fragment. Keep it whole so ``_parse_modal_choose_one``
            # can match the full header against
            # ``_DELIRIUM_MODAL_HEADER_RE`` on the next pass.
            new_clauses.append(c)
        elif _MODAL_MODE_LINE_RE.match(c) is not None:
            # Modal mode lines (``• <sentence>``) must NOT be sentence-
            # split, even when the mode sentence contains an embedded
            # period (e.g. Warping Wail mode 3:
            # ``• Create a 1/1 colorless Eldrazi Scion creature token.
            # It has "Sacrifice this token: Add {C}."``) — splitting
            # would carve the second sentence into an unrecognizable
            # fragment that makes the modal shape unclaimable. Keep mode
            # lines whole so ``_parse_modal_choose_one`` can strip the
            # leading ``• `` and parse the full sentence as a mode.
            new_clauses.append(c)
        else:
            new_clauses.extend(_split_sentences(c))
    clauses = new_clauses
    # Drop recognized self-shuffle rider clauses — they contribute no
    # ``Effect`` (the engine consumes them via the
    # ``shuffles_into_library_instead_of_graveyard`` printing flag wired
    # by ``_detect_shuffle_self_flags``). Two shapes are recognized:
    #   - ``Shuffle <Name> into its owner's library.`` (Green Sun's Zenith)
    #   - ``If <Name> would be put into a graveyard from anywhere, reveal
    #     <Name> and shuffle it into its owner's library instead.``
    #     (Nexus of Fate)
    # Dropping happens AFTER the sentence-splitting pass so a single-oracle-
    # line spell like Green Sun's Zenith (whose GSZ self-shuffle sentence
    # was split off by ``_split_sentences``) has its rider clause visible
    # here for dropping. Must also happen BEFORE the ``len(clauses) == 1``
    # short-circuit so spells whose only surviving clause after dropping is
    # the main effect (Nexus of Fate: take-extra-turn) return that effect
    # cleanly via the single-clause path rather than trying to Sequence it
    # with an empty clause list.
    clauses = [c for c in clauses if not _is_self_shuffle_clause(c)]
    if not clauses:
        return None
    if len(clauses) == 1:
        return _parse_spell_effect_phrase(clauses[0], name)
    # Two-clause Void-replacement shape (Plasma Bolt's damage rider,
    # Tragic Trajectory's pump rider). The dispatch tries each
    # supported base/rider pairing in turn and picks the first that
    # both parses the base-clause cleanly AND matches the rider's
    # surface form for that base shape.
    if len(clauses) == 2:
        first = _parse_spell_effect_phrase(clauses[0], name)
        if first is not None:
            void_then = _parse_void_damage_replacement(
                clauses[1], name, first
            )
            if void_then is None:
                void_then = _parse_void_pump_replacement(clauses[1], first)
            if void_then is not None:
                return ConditionalIfVoid(
                    then_effect=void_then, else_effect=first
                )
            # Hymn-of-the-Faller-shaped "adds-a-draw" Void rider:
            # the rider APPENDS a ConditionalIfVoid(then=DrawCards(1),
            # else=None) to the base effect. The base must be a
            # Sequence (multi-step spell body); the appended conditional
            # extends the Sequence rather than replacing any step.
            # Tried after the replacement helpers since the adds-draw
            # shape is orthogonal (it doesn't depend on the type of
            # ``first``).
            if _is_void_adds_draw_rider(clauses[1]):
                # Flatten any top-level Sequence so the result is a
                # single flat Sequence (not a nested Sequence-of-
                # Sequences). The base clause parses via the compound
                # splitter which may itself return a Sequence (e.g.
                # Hymn of the Faller's ``Surveil 1, then you draw a
                # card and lose 1 life.`` → ``Sequence(Sequence(Surveil,
                # DrawCards), LoseLife)``). Flattening keeps the
                # produced effect structurally identical to the static-
                # registry model (a single flat Sequence whose last
                # element is the ConditionalIfVoid).
                def _flatten(eff: Effect) -> tuple[Effect, ...]:
                    if isinstance(eff, Sequence):
                        flat: list[Effect] = []
                        for e in eff.effects:
                            flat.extend(_flatten(e))
                        return tuple(flat)
                    return (eff,)
                base_effects = _flatten(first)
                return Sequence(effects=(
                    *base_effects,
                    ConditionalIfVoid(
                        then_effect=DrawCards(amount=1),
                        else_effect=None,
                    ),
                ))
            # Void "instead" rider: the rider replaces the base effect
            # entirely when Void is active (Decode Transmissions's
            # ``Void — ... instead you draw two cards and each opponent
            # loses 2 life.`` rider). ``_parse_void_instead_effect_rider``
            # parses the then-branch and returns a ConditionalIfVoid
            # whose else-branch is the base effect. Tried after the
            # adds-draw rider since the "instead" keyword is a distinct
            # surface form that the adds-draw matcher doesn't fire on.
            instead_eff = _parse_void_instead_effect_rider(
                clauses[1], first, name
            )
            if instead_eff is not None:
                return instead_eff
            # Unimplemented secondary-rider drop: when the first clause
            # parses cleanly and the second clause is a known-
            # unimplemented rider (controller-manifest, death-trigger-
            # manifest, optional-graveyard-return), return just the
            # first-clause effect — mirroring the simplification the
            # bespoke entries already make (entries 23, 28, 34).
            if _is_unimplemented_secondary_rider(clauses[1]):
                return first
    # General N-clause unimplemented-rider drop: if the first clause
    # parses cleanly AND all remaining clauses (2 through N) are
    # unimplemented secondary riders, return the first-clause effect.
    # Handles spells like Come Back Wrong whose three-sentence body
    # has one parseable base clause + two unimplemented rider clauses
    # (conditional reanimate + delayed-sacrifice trigger).  Only
    # reaches here when ``len(clauses) >= 3`` (the ``len == 2`` path
    # above already handles the two-clause case).
    if len(clauses) >= 3:
        first_multi = _parse_spell_effect_phrase(clauses[0], name)
        if first_multi is not None and all(
            _is_unimplemented_secondary_rider(c) for c in clauses[1:]
        ):
            return first_multi
    # Modal shape: ``Choose one —`` / ``Choose one or both —`` header
    # line + ≥2 bullet mode lines. Tried before the Sequence fallback
    # because Sequence would uselessly attempt to parse the modal
    # header as a spell-effect sentence, fail, and return None —
    # losing any modal spell whose modes are individually parseable.
    modal = _parse_modal_choose_one(clauses, name)
    if modal is not None:
        return modal
    # Sequence shape: every clause must be a plain spell-effect sentence.
    parsed: list[Effect] = []
    for clause in clauses:
        eff = _parse_spell_effect_phrase(clause, name)
        if eff is None:
            return None
        parsed.append(eff)
    return Sequence(effects=tuple(parsed))


def _detect_preamble_flags(text: str) -> dict:
    """Scan ``text``'s leading keyword-preamble clauses and return a
    dict of ``CardPrinting`` flags they imply (e.g.
    ``{"has_convoke": True}`` when "Convoke (...)" leads the oracle
    text). Mirrors the preamble-stripping in
    ``_parse_spell_oracle_text``."""
    flags: dict = {}
    for clause in [c.strip() for c in text.split("\n") if c.strip()]:
        if not _is_spell_keyword_preamble(clause):
            break
        if clause.startswith("Convoke"):
            flags["has_convoke"] = True
    return flags


def _detect_additional_cost_flags(text: str) -> dict:
    """Scan ``text``'s leading additional-cost preamble clauses and
    return a dict of ``CardPrinting`` flags they imply (e.g.
    ``{"additional_cost_sacrifice_creature_or_artifact": True}`` when
    ``"As an additional cost to cast this spell, sacrifice an artifact
    or creature."`` leads the oracle text).

    Mirrors the preamble-stripping in ``_parse_spell_oracle_text`` —
    iterates through leading clauses while each is a recognized
    additional-cost preamble, accumulates the flags, and stops at the
    first non-preamble clause. Multiple stacked additional-cost
    preambles aren't a printed shape today, but the loop handles them
    naturally if a future card ships them.

    Walks past keyword-preamble clauses (the existing Convoke shape)
    in case a future card stacks both shapes (Convoke + additional
    cost). Today no card does, but skipping them keeps the dispatcher
    order-insensitive: the flag set returned doesn't depend on
    whether the spell author put the additional-cost line first or
    after the keyword preamble.
    """
    flags: dict = {}
    for clause in [c.strip() for c in text.split("\n") if c.strip()]:
        if _is_spell_keyword_preamble(clause):
            continue
        if not _is_additional_cost_preamble(clause):
            break
        flags.update(_additional_cost_flags(clause))
    return flags


# Self-shuffle riders: a clause of the form "Shuffle <Name> into its
# owner's library." (Green Sun's Zenith) or "If <Name> would be put
# into a graveyard from anywhere, reveal <Name> and shuffle it into
# its owner's library instead." (Nexus of Fate). The static side wires
# both via the ``shuffles_into_library_instead_of_graveyard`` printing
# flag — so detecting either rider in a spell's oracle text threads the
# flag onto the resulting ``CardPrinting`` without contributing an
# ``Effect``. The rider's text remains in the oracle text and is
# matched verbatim by the whole-spell exact-text dispatcher; there is
# no clause-stripping pass needed for these riders, since the dispatch
# key already includes the rider.
#
# Both shapes interpolate the card's own name and are matched after
# escaping the name. Non-matching cards (no shuffle rider in their
# text) round-trip through ``_detect_shuffle_self_flags`` with an
# empty flag dict.
_SHUFFLE_SELF_GSZ_RE_TEMPLATE = (
    r"Shuffle {name} into its owner's library\."
)
_SHUFFLE_SELF_NEXUS_RE_TEMPLATE = (
    r"If {name} would be put into a graveyard from anywhere, "
    r"reveal {name} and shuffle it into its owner's library instead\."
)


def _detect_shuffle_self_flags(text: str, name: str) -> dict:
    """Return ``{"shuffles_into_library_instead_of_graveyard": True}``
    if ``text`` contains a recognized self-shuffle rider for ``name``;
    an empty dict otherwise.

    Two shapes are recognized:
      - ``Shuffle <Name> into its owner's library.`` (Green Sun's
        Zenith). Appears as the trailing sentence of the spell's
        single oracle line.
      - ``If <Name> would be put into a graveyard from anywhere,
        reveal <Name> and shuffle it into its owner's library
        instead.`` (Nexus of Fate). Appears as the spell's second
        oracle line.

    The matcher uses ``re.search`` (not ``re.match``) so it finds the
    rider regardless of where in the spell text it appears. Each
    pattern interpolates ``re.escape(name)`` so a card name with regex
    metacharacters (e.g. apostrophes, periods) doesn't break the
    match. Non-matching texts return ``{}`` — callers spread the dict
    via ``**`` into ``make_instant`` / ``make_sorcery`` so an empty
    dict is a no-op.
    """
    name_re = re.escape(name)
    patterns = (
        _SHUFFLE_SELF_GSZ_RE_TEMPLATE.format(name=name_re),
        _SHUFFLE_SELF_NEXUS_RE_TEMPLATE.format(name=name_re),
    )
    for p in patterns:
        if re.search(p, text) is not None:
            return {"shuffles_into_library_instead_of_graveyard": True}
    return {}


def _detect_kicker_cost(text: str) -> str | None:
    """Return the Kicker cost string (e.g. ``"{1}{U}"``) if ``text``
    has a leading Kicker preamble, else ``None``. Mirrors the
    preamble-stripping in ``_parse_spell_oracle_text``: walks past
    the existing keyword (Convoke) and additional-cost preambles —
    today no card stacks Kicker behind another preamble, but the
    walk keeps the dispatcher order-insensitive should a future card
    do so. Returns the cost of the FIRST recognized Kicker preamble;
    multi-Kicker spells (which would carry stacked Kicker lines)
    aren't a printed shape.
    """
    for clause in [c.strip() for c in text.split("\n") if c.strip()]:
        if _is_spell_keyword_preamble(clause):
            continue
        if _is_additional_cost_preamble(clause):
            continue
        if _is_kicker_preamble(clause):
            return _kicker_cost(clause)
        break
    return None


def _detect_cost_reductions(text: str) -> tuple[CostReduction, ...]:
    """Return every cost-reduction rule implied by ``text``'s recognized
    ``This spell costs {N} less to cast if <condition>.`` clauses, in
    the order they appear. Reminder text is stripped per clause
    before recognition, so a rider buried after a parenthesized
    flavor still matches.

    Mirrors the rider-dropping pass in ``_parse_spell_oracle_text``;
    callers pass the result via the ``cost_reductions`` kwarg on
    ``make_instant`` / ``make_sorcery``.
    """
    rules: list[CostReduction] = []
    for raw in text.split("\n"):
        clause = _strip_reminder_text(raw)
        if not clause:
            continue
        rule = _parse_cost_reduction_line(clause)
        if rule is not None:
            rules.append(rule)
    return tuple(rules)


def _build_spell_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for an instant or sorcery
    ``card`` (a Scryfall record). Returns ``None`` if the card is
    neither an instant nor a sorcery, or if its oracle text doesn't
    parse into a supported single-effect or composite shape.
    """
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Instant" not in card_types and "Sorcery" not in card_types:
        return None
    text = card.get("oracle_text", "").strip()
    if not text:
        return None
    effect = _parse_spell_oracle_text(text, card["name"])
    if effect is None:
        return None
    factory = make_instant if "Instant" in card_types else make_sorcery
    kicker = _detect_kicker_cost(text)
    kwargs: dict = {}
    if kicker is not None:
        kwargs["kicker"] = kicker
    return factory(
        name=card["name"],
        cost=card["mana_cost"],
        effect=effect,
        cost_reductions=_detect_cost_reductions(text),
        **_detect_preamble_flags(text),
        **_detect_additional_cost_flags(text),
        **_detect_shuffle_self_flags(text, card["name"]),
        **kwargs,
    )
