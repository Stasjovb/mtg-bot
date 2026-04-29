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
    ExileTargetCreatureWithPowerOrToughnessAtMost,
    CreateXTokensOfTargetPermanentWithHasteEndStepSac,
    CutPropulsionEffect,
    DealDamageAnyTarget,
    DealDamageToTargetCreature,
    DealDamageToTargetCreatureSpacecraftBoosted,
    DealDamageToTargetCreatureWithExcessLanderRider,
    DealNDamageToEachCreature,
    DepressurizeEffect,
    DestroyTargetArtifact,
    DestroyTargetCreature,
    DestroyTargetNonlandPermanent,
    DestroyTargetNonlandPermanentWithLanderForController,
    DiplomaticRelationsEffect,
    DrawCards,
    EachOpponentLosesLife,
    Effect,
    ExorciseEffect,
    FocusFireEffect,
    LoseLife,
    ManifestDread,
    ModalChooseOne,
    MutinousMassacreEffect,
    OptionalSacArtifactForEffect,
    PreventAllCombatDamageThisTurn,
    PumpCreaturesYouControlUntilEOT,
    PumpTargetCreatureUntilEOT,
    PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
    ReturnCreatureFromYourGraveyardToBattlefield,
    ReturnCreatureFromYourGraveyardToHand,
    ReturnTargetCreatureToOwnersHand,
    ReturnUpToNCreaturesFromYourGraveyardToHand,
    ReturnUpToNSmallCreaturesFromGraveyardWithCounters,
    SearchLibraryForGreenCreatureWithMVAtMostX,
    SeedshipImpactEffect,
    Sequence,
    SingularityRuptureEffect,
    Surveil,
    SystemsOverrideEffect,
    TakeExtraTurnAfterThisOne,
    TargetOpponentDiscardsCasterChoice,
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


# Sentence-boundary splitter for multi-sentence oracle-text lines.
# Some EoE printings pack two effect sentences onto a single oracle
# line separated by ``. `` rather than ``\n`` (e.g. Radiant Strike's
# ``"Destroy target artifact or tapped creature. You gain 3 life."``).
# We carve the line at the period-then-uppercase boundary so each
# sentence flows through the per-clause parser independently.
#
# The negative lookahead for ``If you do,`` keeps the splitter from
# breaking the ``You may pay/sacrifice/discard {COST}. If you do,
# <inner-effect>.`` family of compound primitives — those are matched
# as a single phrase by ``_YOU_MAY_PAY_THEN_EFFECT`` /
# ``_OPTIONAL_DISCARD_THEN_DRAW`` / ``_OPTIONAL_SAC_ANOTHER_FOR_*``
# down in ``effects``, and the embedded sentence boundary inside
# those phrases is required (the regexes match a literal ``\. ``
# between the cost and the consequence).
#
# Decimal numbers and abbreviations don't appear in MTG oracle text,
# so a simple ``period + whitespace + uppercase`` boundary suffices —
# no need for a fuller sentence tokenizer.
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=\.)\s+(?=[A-Z])(?!If you do,)")


def _split_sentences(line: str) -> list[str]:
    """Split a single oracle-text line at sentence boundaries.

    Returns ``[line]`` unchanged when the line contains no internal
    boundary. Otherwise returns the list of per-sentence pieces, each
    with surrounding whitespace stripped. Empty pieces are filtered
    out so a stray double-period or trailing whitespace doesn't
    inject blank clauses.

    The boundary is ``period + whitespace + uppercase letter``, with
    a negative lookahead for ``If you do,`` so the
    ``You may pay/sacrifice/discard {COST}. If you do, …`` compound
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
    stripping the leading ``• `` (bullet + space). If any mode fails
    to parse, the whole shape is rejected (returns ``None``) — partial
    modal effects would silently change a spell's playable behavior.

    A header by itself (zero mode lines) or a header with exactly one
    mode line is rejected — printed modal spells always have at least
    two modes, and a single-mode "modal" spell would be indistinguishable
    from a non-modal effect. ``Choose two`` and other variants don't
    match either header regex and fall through. The ``or both`` shape
    constructs ``ModalChooseOne(or_both=True)`` so the engine routes
    mode-pick through the agent's ``choose_modes`` (plural) hook.
    """
    if not clauses:
        return None
    if _MODAL_CHOOSE_ONE_HEADER_RE.match(clauses[0]) is not None:
        or_both = False
    elif _MODAL_CHOOSE_ONE_OR_BOTH_HEADER_RE.match(clauses[0]) is not None:
        or_both = True
    else:
        return None
    mode_lines = clauses[1:]
    if len(mode_lines) < 2:
        return None
    parsed_modes: list[Effect] = []
    for line in mode_lines:
        m = _MODAL_MODE_LINE_RE.match(line)
        if m is None:
            return None
        eff = _parse_spell_effect_phrase(m.group(1), name)
        if eff is None:
            return None
        parsed_modes.append(eff)
    return ModalChooseOne(modes=tuple(parsed_modes), or_both=or_both)


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
    # Darkness: prevent all combat damage that would be dealt this turn.
    # Single-sentence spell — the whole-spell tier matches it directly
    # because no per-clause primitive for "prevent all combat damage"
    # is meaningful elsewhere in the EoE pool. The
    # ``PreventAllCombatDamageThisTurn`` engine class sets the
    # ``state.prevent_combat_damage_this_turn`` flag, which combat's
    # damage step honors and which clears at end-of-turn cleanup.
    (
        "Prevent all combat damage that would be dealt this turn."
    ): PreventAllCombatDamageThisTurn(),
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
    # Singularity Rupture: wrath + opt-in mass mill of half-library.
    (
        "Destroy all creatures, then any number of target players "
        "each mill half their library, rounded down."
    ): SingularityRuptureEffect(),
    # Depressurize: -3/-0 UEOT + state-based death check ("if power is 0
    # or less, destroy it"). The engine class folds the pump and the
    # conditional destroy into one resolve step, so the parser maps the
    # full two-sentence text to the single bespoke class.
    (
        "Target creature gets -3/-0 until end of turn. "
        "Then if that creature's power is 0 or less, destroy it."
    ): DepressurizeEffect(power_penalty=3),
    # Focus Fire: variable-X burn whose X reads "2 plus the number of
    # creatures and/or Spacecraft you control". The bespoke engine
    # class computes X at resolve time; the parser dispatches on the
    # printed surface form.
    (
        "Focus Fire deals X damage to target attacking or blocking "
        "creature, where X is 2 plus the number of creatures and/or "
        "Spacecraft you control."
    ): FocusFireEffect(base=2),
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
    # Zealous Display: anthem + opp-turn-untap rider. The
    # ``also_untap_if_not_your_turn`` flag on the engine class fires
    # only when the spell resolves on an opponent's turn, untapping
    # every creature that received the pump.
    (
        "Creatures you control get +2/+0 until end of turn. "
        "If it's not your turn, untap those creatures."
    ): PumpCreaturesYouControlUntilEOT(
        power_bonus=2,
        toughness_bonus=0,
        also_untap_if_not_your_turn=True,
    ),
    # Dual-Sun Technique: grant double strike + conditional draw rider
    # ("If it has a +1/+1 counter on it, draw a card"). The engine
    # class's ``draw_if_target_has_plus_one_counter`` field captures
    # the rider; the keyword grant rides the standard pump path.
    (
        "Target creature you control gains double strike until end of "
        "turn. If it has a +1/+1 counter on it, draw a card."
    ): PumpTargetCreatureUntilEOT(
        power_bonus=0,
        toughness_bonus=0,
        granted_keywords=frozenset({"double strike"}),
        you_control_only=True,
        draw_if_target_has_plus_one_counter=1,
    ),
    # Invasive Maneuvers: bare burn with a Spacecraft-state boost
    # ("It deals 5 damage instead if you control a Spacecraft").
    # The bespoke class picks ``base`` vs ``boosted`` by inspecting
    # the controller's battlefield at resolve time.
    (
        "Invasive Maneuvers deals 3 damage to target creature. "
        "It deals 5 damage instead if you control a Spacecraft."
    ): DealDamageToTargetCreatureSpacecraftBoosted(base=3, boosted=5),
    # Cerebral Download: variable surveil ("Surveil X, where X is the
    # number of artifacts you control") + flat draw three. The Surveil
    # primitive's ``use_artifact_count=True`` flag substitutes the
    # controller's artifact count for the bare ``amount`` field at
    # resolve time, so the static-side ``Surveil(use_artifact_count=
    # True)`` initializer (no ``amount`` kwarg) fires the same code
    # path as the explicit ``Surveil(amount=1, use_artifact_count=
    # True)`` form here. The dataclass default for ``amount`` is 1.
    (
        "Surveil X, where X is the number of artifacts you control. "
        "Then draw three cards."
    ): Sequence(effects=(
        Surveil(amount=1, use_artifact_count=True),
        DrawCards(amount=3),
    )),
    # Decode Transmissions: two-clause Void shape that doesn't fit
    # the existing ``_parse_void_damage_replacement`` /
    # ``_parse_void_pump_replacement`` helpers — the Void rider
    # replaces the LIFE-LOSS half of the base sentence (the draw stays,
    # the lose-2-life flips to each-opponent-loses-2-life). The
    # static models this as ``Sequence(DrawCards, ConditionalIfVoid(
    # then=EachOpponentLosesLife, else=LoseLife))``: the draw runs
    # unconditionally, then the Void branch picks lose-life at the
    # caster vs at each opponent. Multi-line oracle text — the key
    # carries the literal newline between base sentence and rider.
    (
        "You draw two cards and lose 2 life.\n"
        "Void — If a nonland permanent left the battlefield this turn "
        "or a spell was warped this turn, instead you draw two cards "
        "and each opponent loses 2 life."
    ): Sequence(effects=(
        DrawCards(amount=2),
        ConditionalIfVoid(
            then_effect=EachOpponentLosesLife(amount=2),
            else_effect=LoseLife(amount=2),
        ),
    )),
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
    # Emergency Eject: destroy + Lander-for-controller rider. The
    # Lander goes to the destroyed permanent's CONTROLLER (not the
    # spell's caster), which the bespoke engine class threads
    # through resolution.
    (
        "Destroy target nonland permanent. "
        "Its controller creates a Lander token."
    ): DestroyTargetNonlandPermanentWithLanderForController(),
    # Orbital Plunge: 6-damage burn + excess-damage Lander rider.
    # The bespoke engine class checks whether excess damage was
    # dealt (target's toughness < 6 at resolve time) and creates
    # the Lander only on excess.
    (
        "Orbital Plunge deals 6 damage to target creature. "
        "If excess damage was dealt this way, create a Lander token."
    ): DealDamageToTargetCreatureWithExcessLanderRider(amount=6),
    # Seedship Impact: destroy artifact-or-enchantment + small-mv
    # Lander rider. The bespoke engine class gates the Lander on
    # the destroyed permanent's mana value (≤ 2).
    (
        "Destroy target artifact or enchantment. "
        "If its mana value was 2 or less, create a Lander token."
    ): SeedshipImpactEffect(),
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
    # Full Bore: pump-your-creature with warp-conditional extra
    # keywords. The ``granted_keywords_if_warp_cast`` field on the
    # generic pump engine class fires only when the target was
    # cast for its warp cost — a generic primitive that any future
    # warp-conditional pump spell can reuse.
    (
        "Target creature you control gets +3/+2 until end of turn. "
        "If that creature was cast for its warp cost, it also gains "
        "trample and haste until end of turn."
    ): PumpTargetCreatureUntilEOT(
        power_bonus=3,
        toughness_bonus=2,
        you_control_only=True,
        granted_keywords_if_warp_cast=frozenset({"trample", "haste"}),
    ),
    # Nexus of Fate: take-extra-turn instant + shuffle-instead-of-
    # graveyard rider. The rider is wired separately via the
    # ``shuffles_into_library_instead_of_graveyard`` printing flag
    # (see ``_detect_shuffle_self_flags``); the dispatcher returns
    # only the spell-effect engine class for the first clause. The
    # full multi-line key is required here because the per-clause
    # parser can't stand up the take-extra-turn primitive on its
    # own (no other card shares it). Multi-line key carries the
    # literal newline between effect line and rider line.
    (
        "Take an extra turn after this one.\n"
        "If Nexus of Fate would be put into a graveyard from anywhere, "
        "reveal Nexus of Fate and shuffle it into its owner's library "
        "instead."
    ): TakeExtraTurnAfterThisOne(),
    # Green Sun's Zenith: variable-X tutor for a green creature plus
    # a self-shuffle rider on the same line. The ``X`` in the search
    # primitive is read from ``state.resolving_x_value`` at resolve
    # time. The shuffle rider is wired separately via the
    # ``shuffles_into_library_instead_of_graveyard`` printing flag
    # (see ``_detect_shuffle_self_flags``); the dispatcher returns
    # only the search-engine instance.
    (
        "Search your library for a green creature card with mana "
        "value X or less, put it onto the battlefield, then shuffle. "
        "Shuffle Green Sun's Zenith into its owner's library."
    ): SearchLibraryForGreenCreatureWithMVAtMostX(),
    # Hymn of the Faller: three-clause Sequence + Void ADDS-A-DRAW
    # rider. Unlike the existing Void replacement helpers (which swap
    # one effect for another), this rider runs an additional effect
    # (``draw another card``) on top of the base. The static models
    # the rider as ``ConditionalIfVoid(then=DrawCards(1), else=None)``:
    # the conditional resolves the extra draw only if the Void state
    # is active; otherwise it's a no-op (else=None).
    (
        "Surveil 1, then you draw a card and lose 1 life.\n"
        "Void — If a nonland permanent left the battlefield this turn "
        "or a spell was warped this turn, draw another card."
    ): Sequence(effects=(
        Surveil(amount=1, use_artifact_count=False),
        DrawCards(amount=1),
        LoseLife(amount=1),
        ConditionalIfVoid(
            then_effect=DrawCards(amount=1),
            else_effect=None,
        ),
    )),
    # Temporal Intervention: 3-sentence directed-discard plus a Void-
    # prefixed cost-reduction rider on its own line. The static ships
    # the discard via ``TargetOpponentDiscardsCasterChoice`` and wires
    # the cost reduction via ``cost_reductions=(CostReduction(amount=2,
    # condition="void_active"),)`` on the printing. The cost-reduction
    # rider is detected and threaded separately by ``_detect_cost_
    # reductions`` (which now recognizes the ``Void — `` prefix);
    # the dispatcher returns only the spell-effect engine class.
    # The leading Void-rider line stays in the dispatch key — the
    # cost-reduction stripping pass that runs LATER (per-clause, in
    # ``_parse_spell_oracle_text``) is bypassed by hitting the
    # whole-spell tier first, so the key must include every line of
    # the printed text.
    (
        "Void — This spell costs {2} less to cast "
        "if a nonland permanent left the battlefield this turn "
        "or a spell was warped this turn.\n"
        "Target opponent reveals their hand. "
        "You choose a nonland card from it. "
        "That player discards that card."
    ): TargetOpponentDiscardsCasterChoice(),
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
    # Warping Wail: 3-mode modal whose third mode contains an inner
    # quoted ability sentence (``It has "Sacrifice this token: Add
    # {C}."``). The static side simplifies mode 3 to a bare token
    # creation because the token printing already carries the
    # sacrifice-for-mana ability — no redundant inner-effect modeling
    # needed. The modal-mode parser is single-sentence per mode and
    # the existing per-mode primitives don't cover ``Exile target
    # creature with power or toughness 1 or less.`` or ``Counter
    # target sorcery spell.``, so the spell lands here as a whole-
    # text dispatch entry. The leading ``({C} represents colorless
    # mana.)`` line is reminder text and stripped before lookup.
    (
        "Choose one —\n"
        "• Exile target creature with power or toughness 1 or less.\n"
        "• Counter target sorcery spell.\n"
        "• Create a 1/1 colorless Eldrazi Scion creature token. "
        "It has \"Sacrifice this token: Add {C}.\""
    ): ModalChooseOne(modes=(
        ExileTargetCreatureWithPowerOrToughnessAtMost(max_value=1),
        CounterTargetSpell(filter_types=frozenset({"Sorcery"})),
        CreateToken(token_printing=TOKEN_PRINTINGS["Eldrazi Scion"]),
    )),
    # Lithobraking: create-Lander + reflexive-trigger optional sac.
    # The static ships ``Sequence(CreateToken(Lander),
    # OptionalSacArtifactForEffect(DealNDamageToEachCreature(2)))``.
    # The "Then you may sacrifice an artifact. When you do, ... "
    # compound is a fixed surface form that the per-clause grammar
    # doesn't carve up (the reflexive trigger inside the optional sac
    # has no standalone primitive); the whole-spell tier matches the
    # verbatim text and returns the static-side composite. The
    # trailing parenthesized Lander reminder text is stripped before
    # dispatch.
    (
        "Create a Lander token. Then you may sacrifice an artifact. "
        "When you do, Lithobraking deals 2 damage to each creature."
    ): Sequence(effects=(
        CreateToken(
            token_printing=TOKEN_PRINTINGS["Lander"], count=1,
        ),
        OptionalSacArtifactForEffect(
            inner_effect=DealNDamageToEachCreature(amount=2),
        ),
    )),
    # Unravel: counter-target-spell + conditional-draw rider whose
    # condition (``the amount of mana spent to cast that spell was
    # less than its mana value``) requires per-spell cast-time accounting
    # the engine doesn't track. The static ships the bare
    # ``CounterTargetSpell()`` and drops the rider; matching here
    # mirrors that simplification on a single multi-sentence printed
    # line. The per-clause grammar would carve this on the sentence
    # boundary and try to parse the conditional rider as a standalone
    # effect, which has no primitive — so the whole-spell tier is the
    # right place to claim the simplified shape.
    (
        "Counter target spell. "
        "If the amount of mana spent to cast that spell was less "
        "than its mana value, you draw a card."
    ): CounterTargetSpell(),
    # Divert Disaster: ``unless its controller pays {2}`` mana-pump
    # counterspell + ``If they do, you create a Lander token.`` rider.
    # The static ships the bare ``CounterTargetSpell()`` (no pay-cost
    # branching, no Lander creation) — the engine doesn't yet model
    # the pay-cost-or-counter Mana Leak shape. Matching here mirrors
    # that simplification. The trailing parenthesized Lander reminder
    # text is stripped before dispatch.
    (
        "Counter target spell unless its controller pays {2}. "
        "If they do, you create a Lander token."
    ): CounterTargetSpell(),
    # Don't Make a Sound: ``unless its controller pays {2}`` mana-pump
    # counterspell + ``If they do, surveil 2.`` rider. Mirrors Divert
    # Disaster's simplification: the static ships the bare
    # ``CounterTargetSpell()`` because the engine doesn't yet model the
    # pay-cost-or-counter Mana Leak shape. The base mechanic — a
    # counterspell — survives the rider drop, so claiming the spell
    # here matches the parser-is-right boundary (same precedent as
    # Divert Disaster, Unravel). The trailing parenthesized surveil
    # reminder text is stripped before dispatch.
    (
        "Counter target spell unless its controller pays {2}. "
        "If they do, surveil 2."
    ): CounterTargetSpell(),
    # Scrounge for Eternity: additional-cost-sacrifice preamble plus a
    # graveyard-return-to-battlefield base + Lander-rider tail. The
    # static ships the bare ``ReturnCreatureFromYourGraveyardToBattle
    # field()`` engine class, dropping the ``or Spacecraft`` target
    # widening, the ``with mana value 5 or less`` cap, and the
    # ``Then create a Lander token`` rider. The base mechanic (a
    # graveyard return) survives the simplification, so claiming the
    # spell here matches the batch-19 parser-is-right boundary —
    # Unravel and Divert Disaster drop similar riders while preserving
    # the printed effect's intent.
    #
    # The dispatch key carries the full additional-cost preamble line —
    # the dispatcher hits BEFORE the per-clause preamble-stripping pass
    # in ``_parse_spell_oracle_text``. The
    # ``additional_cost_sacrifice_creature_or_artifact=True`` flag is
    # wired separately via ``_detect_additional_cost_flags`` (called
    # from ``_build_spell_printing``); the dispatcher returns only the
    # spell-effect engine class. The trailing parenthesized Lander
    # reminder text is stripped before dispatch.
    #
    # The per-clause grammar can't claim this spell because the second
    # clause's ``Return target creature or Spacecraft card with mana
    # value 5 or less ... Then create a Lander token.`` doesn't parse
    # as a standalone effect (no primitive widens to ``or Spacecraft``
    # / mana-value cap, and the trailing ``Then create a Lander token``
    # rider has no per-sentence shape). The whole-spell tier mirrors
    # the static-side simplification verbatim.
    (
        "As an additional cost to cast this spell, sacrifice an "
        "artifact or creature.\n"
        "Return target creature or Spacecraft card with mana value 5 "
        "or less from your graveyard to the battlefield. "
        "Then create a Lander token."
    ): ReturnCreatureFromYourGraveyardToBattlefield(),
    # Archenemy's Charm: 3-mode Choose-one modal with one one-off
    # primitive per mode. The per-mode parser (``_parse_modal_choose_
    # one``) can't claim it because none of the three mode lines parse
    # as standalone spell-effect phrases — Mode 1's ``or planeswalker``
    # tail and Mode 2's ``creature and/or planeswalker cards`` shape
    # don't exist in the unified grammar, and Mode 3 is a multi-
    # sentence pump-and-grant-keyword combined-target effect that has
    # no per-clause primitive. Each of the three engine classes
    # (``ExileTargetCreature``, ``ReturnUpToNCreaturesFromYourGraveyard
    # ToHand``, ``PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreature
    # YouControl``) is used only by this spell, so adding per-mode
    # grammar entries would be over-engineering. The whole-spell tier
    # is the right place — same pattern as Warping Wail's mode 3,
    # which similarly drops a one-off mode into a whole-spell entry.
    #
    # The Mode 1 ``or planeswalker`` and Mode 2 ``and/or planeswalker``
    # simplifications match Warping Wail's ``ExileTargetCreatureWith
    # PowerOrToughnessAtMost`` (which similarly drops the planeswalker
    # scope) — planeswalkers aren't fully modeled in the EoE pool yet.
    (
        "Choose one —\n"
        "• Exile target creature or planeswalker.\n"
        "• Return one or two target creature and/or planeswalker "
        "cards from your graveyard to your hand.\n"
        "• Put two +1/+1 counters on target creature you control. "
        "It gains lifelink until end of turn."
    ): ModalChooseOne(modes=(
        ExileTargetCreature(),
        ReturnUpToNCreaturesFromYourGraveyardToHand(max_n=2, min_n=1),
        PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl(
            amount=2, granted_keywords=frozenset({"lifelink"}),
        ),
    )),
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
    # Pull Through the Weft: multi-target graveyard return — up to two
    # nonland permanents to hand, then up to two lands to battlefield
    # tapped. The per-clause grammar has no "nonland permanent card to
    # hand" nor "land card to battlefield tapped" primitive; the static
    # ships ``ReturnCreatureFromYourGraveyardToHand()`` as a single-
    # target simplification. Match the full printed oracle text
    # verbatim.
    (
        "Return up to two target nonland permanent cards from your "
        "graveyard to your hand, then return up to two target land "
        "cards from your graveyard to the battlefield tapped."
    ): ReturnCreatureFromYourGraveyardToHand(),
    # Scorching Dragonfire (Duskmourn) — 3-damage burn to creature/
    # planeswalker plus an "if it would die this turn, exile it
    # instead" replacement-effect rider. The static side simplifies
    # to bare ``DealDamageToTargetCreature(amount=3)`` because:
    # (1) the engine doesn't model planeswalkers as targets — every
    # other DSK/EoE primitive that prints "creature or planeswalker"
    # likewise drops the planeswalker scope (Archenemy's Charm,
    # Warping Wail mode 1 precedent);
    # (2) the engine doesn't model "if it would die this turn, exile
    # it instead" replacement effects — there's no GameObject
    # ``exile_if_dies_this_turn`` flag to set, and adding one would
    # require touching ``game.py`` and the SBA / die-trigger pipeline
    # (Mutinous Massacre / Singularity Rupture precedent: complex die-
    # replacement riders are out of scope for whole-spell dispatch).
    # Same parser-is-right precedent as Unravel / Divert Disaster —
    # claim the bare base mechanic (3-damage burn) and drop the
    # rider rather than leaving the spell unclaimed for an unmodeled
    # rider.
    (
        "Scorching Dragonfire deals 3 damage to target creature or "
        "planeswalker. If that creature or planeswalker would die "
        "this turn, exile it instead."
    ): DealDamageToTargetCreature(amount=3),
    # Unwanted Remake (Duskmourn) — bare destroy-target-creature plus
    # an "Its controller manifests dread" rider. The static side
    # simplifies to bare ``DestroyTargetCreature()`` because the
    # engine's ``ManifestDread`` primitive resolves at the
    # caster's hand (the controller_id passed into resolve), not at
    # the destroyed creature's CONTROLLER's hand. Adding "manifest by
    # the destroyed permanent's controller" would require a new
    # back-reference plumbing through ``ManifestDread`` to read off a
    # different player than the resolving controller — a non-trivial
    # widening that would also need engine-side wiring beyond the
    # parser. Same parser-is-right simplification as Unravel / Divert
    # Disaster: claim the bare base mechanic (creature destroy) and
    # drop the rider that requires unmodeled engine plumbing.
    # Reminder text inside the parenthetical is stripped before
    # dispatch.
    (
        "Destroy target creature. Its controller manifests dread."
    ): DestroyTargetCreature(),
    # Jump Scare (Duskmourn) — pump-target-creature plus a type-
    # change rider ("becomes a Horror enchantment creature in
    # addition to its other types"). The static side simplifies to
    # bare ``PumpTargetCreatureUntilEOT(power_bonus=2,
    # toughness_bonus=2, granted_keywords={"flying"})`` because the
    # engine doesn't model UEOT type-line additions on targeted
    # creatures — the closest aura plumbing
    # (``attached_grants_subtype``) is single-subtype Aura-only and
    # doesn't add a card type (Enchantment) on top of the target.
    # Same parser-is-right simplification as Unravel / Divert
    # Disaster: claim the bare base mechanic (pump UEOT + flying
    # grant) and drop the type-change rider. The leading
    # ``Until end of turn,`` adverb is part of the dispatch key so
    # the surface form matches verbatim — the per-clause grammar
    # parses ``target creature gets +2/+2 and gains flying until
    # end of turn`` (trailing UEOT) but not the leading-UEOT shape,
    # so the whole-spell tier is the right place.
    (
        "Until end of turn, target creature gets +2/+2, gains "
        "flying, and becomes a Horror enchantment creature in "
        "addition to its other types."
    ): PumpTargetCreatureUntilEOT(
        power_bonus=2,
        toughness_bonus=2,
        granted_keywords=frozenset({"flying"}),
    ),
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
    # Exorcise (Duskmourn) — single-sentence three-way disjunctive
    # exile: target artifact / target enchantment / target creature
    # with power 4 or greater. The static ships ``ExorciseEffect()``
    # which evaluates the three-arm filter at both target-pick and
    # resolve time using ``effective_power`` for the creature arm.
    # The whole-spell tier is the right place because the per-clause
    # grammar has no shape that ORs across three target-type
    # filters with one of them gated on a P/T threshold; modeling
    # this as a generic primitive would over-engineer for one card.
    (
        "Exile target artifact, enchantment, or creature with "
        "power 4 or greater."
    ): ExorciseEffect(),
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
    # Under the Skin (Duskmourn) ``{2}{G}`` Sorcery — two-clause spell:
    # ``Manifest dread.`` followed by ``You may return a permanent
    # card from your graveyard to your hand.``. The static side
    # simplifies to bare ``ManifestDread(count=1)`` (the trailing
    # parenthesized reminder text on the first clause is stripped
    # before dispatch, but the SECOND clause is the rider being
    # dropped here). The optional graveyard-return rider has no
    # standalone primitive: the per-clause spell-effect grammar has
    # no "may return a permanent card from your graveyard to your
    # hand" parse — every existing ``Return*FromGraveyardToHand``
    # primitive is creature-typed (single-target or up-to-N), and
    # widening one to "any nonland permanent card" with optionality
    # would be a non-trivial primitive change for a single card's
    # rider. Same parser-is-right precedent as Unwanted Remake /
    # Vengeful Possession — claim the bare base mechanic (manifest
    # dread) and drop the optional secondary rider. Multi-line key
    # carries the literal newline between the manifest clause and
    # the optional return clause; reminder text inside the manifest
    # clause's parenthetical is stripped before dispatch.
    (
        "Manifest dread.\n"
        "You may return a permanent card from your graveyard to your "
        "hand."
    ): ManifestDread(count=1),
    # Midnight Mayhem (Duskmourn) ``{2}{R}{W}`` Sorcery — three-Gremlin
    # token creation plus a UEOT keyword grant ("Gremlins you control
    # gain menace, lifelink, and haste until end of turn"). The static
    # side simplifies to bare ``CreateToken(Gremlin, count=3)``: the
    # UEOT keyword grant on a creature subtype is dropped because:
    # (1) the engine has no
    #     ``PumpCreaturesYouControlOfSubtypeUntilEOT`` primitive — the
    #     existing ``PumpCreaturesYouControlUntilEOT`` widens to ALL
    #     your creatures, not a subtype-filtered subset, and adding
    #     the subtype filter would require a new optional kwarg or a
    #     sibling class for one card's rider;
    # (2) the just-created Gremlin tokens with haste are the
    #     mechanically dominant payload — three 1/1 attackers UEOT
    #     under any combinator-style Sequence still wouldn't get the
    #     keywords on the freshly-created tokens unless the pump runs
    #     against creatures-you-control-with-subtype-Gremlin AT
    #     resolve time, which the existing
    #     ``PumpCreaturesYouControlUntilEOT`` doesn't do.
    # Same parser-is-right precedent as Terminal Velocity / Pull
    # Through the Weft — claim the bare token-creation payload and
    # drop the UEOT keyword-grant rider rather than leaving the spell
    # unclaimed for an unmodeled rider. The trailing parenthesized
    # menace reminder text is stripped before dispatch.
    (
        "Create three 1/1 red Gremlin creature tokens. "
        "Gremlins you control gain menace, lifelink, and haste until "
        "end of turn."
    ): CreateToken(
        token_printing=TOKEN_PRINTINGS["Gremlin"], count=3,
    ),
    # Get Out (Duskmourn) ``{U}{U}`` Instant — two-mode modal: ``•
    # Counter target creature or enchantment spell.`` and ``• Return
    # one or two target creatures and/or enchantments you own to your
    # hand.``. The static side simplifies to bare
    # ``CounterTargetSpell(filter_types=frozenset({"Creature",
    # "Enchantment"}))`` because:
    # (1) the per-mode parser (``_parse_modal_choose_one``) can't
    #     claim this spell — mode 2's ``return one or two target
    #     creatures and/or enchantments you own to your hand`` shape
    #     has no per-mode primitive (the existing
    #     ``ReturnUpToNCreaturesFromYourGraveyardToHand`` /
    #     ``ReturnUpToNTargetCreaturesToOwnersHands`` are
    #     creature-typed, and widening to "creatures and/or
    #     enchantments you own" plus the multi-target ``one or two``
    #     framing on the BATTLEFIELD-to-hand bounce path would need a
    #     new primitive for one card's mode);
    # (2) mode 1 is a faithful, well-modeled counter — the existing
    #     ``CounterTargetSpell(filter_types=frozenset({"Creature",
    #     "Enchantment"}))`` exactly captures the printed scope (same
    #     filter shape Warping Wail's mode 2 ``filter_types=frozenset
    #     ({"Sorcery"})`` uses).
    # Same parser-is-right precedent as Archenemy's Charm — claim a
    # well-modeled mode of a multi-mode modal spell rather than
    # leaving the spell unclaimed; the engine's mode-selection plumbing
    # would normally route through ``ModalChooseOne`` but the
    # whole-spell tier yields a single fixed effect when only one of
    # the modes is modelable.
    (
        "Choose one —\n"
        "• Counter target creature or enchantment spell.\n"
        "• Return one or two target creatures and/or enchantments "
        "you own to your hand."
    ): CounterTargetSpell(
        filter_types=frozenset({"Creature", "Enchantment"}),
    ),
    # Untimely Malfunction (Duskmourn) ``{1}{R}`` Instant — three-mode
    # modal: ``• Destroy target artifact.``, ``• Change the target of
    # target spell or ability with a single target.``, and ``• One or
    # two target creatures can't block this turn.``. The static side
    # simplifies to bare ``DestroyTargetArtifact()`` (mode 1) because:
    # (1) the per-mode parser (``_parse_modal_choose_one``) can't
    #     claim this spell — modes 2 and 3 don't parse as standalone
    #     spell-effect phrases (the engine has no
    #     ``ChangeTargetOfSpellOrAbility`` redirect primitive, and no
    #     per-creature ``cant_block_this_turn`` flag — same gap as
    #     Trial of Agony's can't-block rider);
    # (2) mode 1 is a faithful, well-modeled artifact destruction —
    #     ``DestroyTargetArtifact()`` exactly captures the printed
    #     scope, the same primitive Untimely Malfunction's mode 1
    #     exact-text would land on.
    # Same parser-is-right precedent as Get Out — claim a well-modeled
    # mode of a multi-mode modal rather than leaving the spell
    # unclaimed; modes 2 and 3 are dropped because they have no
    # per-mode primitive.
    (
        "Choose one —\n"
        "• Destroy target artifact.\n"
        "• Change the target of target spell or ability with a "
        "single target.\n"
        "• One or two target creatures can't block this turn."
    ): DestroyTargetArtifact(),
    # Unnerving Grasp (Duskmourn) ``{2}{U}`` Sorcery — two-clause
    # spell: ``Return up to one target nonland permanent to its
    # owner's hand.`` followed by ``Manifest dread.``. The static side
    # simplifies to bare ``ManifestDread(count=1)`` because:
    # (1) the per-clause grammar can't claim either clause as a
    #     standalone effect — ``Return up to one target nonland
    #     permanent`` has no per-clause primitive (the existing
    #     ``ReturnTargetCreatureToOwnersHand`` widens to
    #     ``allow_nonland_permanent=True`` only for Desculpting Blast,
    #     and the ``optional=True``/``up to one`` shape isn't reached
    #     by any per-clause regex);
    # (2) composing the two as a Sequence would lose the up-to-one
    #     optional bounce: Sequence's ``requires_target`` returns
    #     False when its only targeting sub-effect has
    #     ``optional=True``, so the cast pipeline never picks a
    #     target — the bounce silently no-ops at every cast. The
    #     manifest-only simplification keeps the more
    #     mechanically-meaningful body of the spell intact.
    # Same parser-is-right precedent as Under the Skin (which drops
    # its optional graveyard-return rider while keeping the
    # ManifestDread base) — the bounce is the optional secondary
    # rider here, the manifest is the base mechanic. Reminder text
    # inside the manifest parenthetical is stripped before dispatch.
    (
        "Return up to one target nonland permanent to its owner's "
        "hand. Manifest dread."
    ): ManifestDread(count=1),
    # Commune with Evil (Duskmourn) ``{2}{B}`` Sorcery — three-step
    # single-resolve effect: look at top 4 cards, put one of them
    # into hand, the rest into graveyard, and gain 3 life. The static
    # ships ``CommuneWithEvilEffect()`` (no parameters; the bespoke
    # class folds all three steps into one resolve). The whole-spell
    # tier is the right place because the per-clause grammar can't
    # carve up the printed text — the first sentence ``Look at the
    # top four cards of your library.`` is informational (the actual
    # mechanical effect happens in the second sentence's split), and
    # the second sentence ``Put one of them into your hand and the
    # rest into your graveyard.`` has no per-clause primitive (the
    # existing ``LookAtTopTwoSplitHandGraveyard`` is fixed at 2 cards
    # with a per-card surveil-vs-hand prompt; Commune with Evil
    # generalizes to 4 cards with a single forced-pick prompt). The
    # trailing ``You gain 3 life.`` rider would parse as a standalone
    # ``GainLife(amount=3)`` but the static ships the whole spell as
    # one engine class for resolve-step atomicity.
    (
        "Look at the top four cards of your library. Put one of them "
        "into your hand and the rest into your graveyard. You gain 3 "
        "life."
    ): CommuneWithEvilEffect(),
    # Turn Inside Out (Duskmourn) ``{R}`` Instant — pump-target-creature
    # +3/+0 UEOT plus a "When it dies this turn, manifest dread."
    # death-triggered rider on the targeted creature. The static side
    # simplifies to bare
    # ``PumpTargetCreatureUntilEOT(power_bonus=3, toughness_bonus=0)``
    # because:
    # (1) the engine has no UEOT-scoped death-trigger plumbing for
    #     attaching a one-shot trigger to a targeted creature for the
    #     remainder of the turn — the closest mechanism is the
    #     creature-side ``triggered_abilities`` field on a printing,
    #     which fires on every match against the printing (not on a
    #     single targeted instance), and adding a per-resolve
    #     ``state.dies_this_turn_manifest_dread_for_target`` registry
    #     would be a non-trivial widening for a single card's rider;
    # (2) the per-clause grammar can't claim the spell either — the
    #     second sentence ``When it dies this turn, manifest dread.``
    #     doesn't parse as a standalone spell-effect phrase (it's a
    #     trigger fragment, not a self-contained effect).
    # Same parser-is-right precedent as Jump Scare / Scorching
    # Dragonfire — claim the bare base mechanic (the +3/+0 pump UEOT)
    # and drop the death-trigger rider rather than leaving the spell
    # unclaimed for an unmodeled rider. Reminder text inside the
    # manifest parenthetical is stripped before dispatch.
    (
        "Target creature gets +3/+0 until end of turn. When it dies "
        "this turn, manifest dread."
    ): PumpTargetCreatureUntilEOT(
        power_bonus=3,
        toughness_bonus=0,
    ),
    # Impossible Inferno (Duskmourn) ``{4}{R}`` Instant — 6-damage
    # burn plus a Delirium-gated impulse-draw rider ("If there are
    # four or more card types among cards in your graveyard, exile
    # the top card of your library. You may play it until the end of
    # your next turn."). Whole-spell exact-text dispatch simplifies
    # to bare ``DealDamageToTargetCreature(amount=6)`` because:
    # (1) the spell-builder has no Delirium-gated conditional
    #     dispatcher today; the only conditional combinator wired in
    #     is ``ConditionalIfVoid`` (Plasma Bolt's Void rider) and
    #     extending it to Delirium would require both a graveyard-
    #     card-types runtime predicate and a UEOT impulse-draw
    #     primitive — neither shape is reused by another DSK card we
    #     model, so the work would be a one-off;
    # (2) the per-clause grammar can't claim the second clause as a
    #     standalone effect either — "Delirium — If there are four
    #     or more card types..." parses as an ability-word prefix on
    #     a conditional impulse-draw, not a standalone spell-effect
    #     phrase.
    # Same parser-is-right precedent as Trial of Agony (drop the
    # multi-target-opp-choice + can't-block rider, keep the bare
    # 5-damage burn): keep the base damage, drop the unmodelable
    # Delirium impulse-draw upside.
    (
        "Impossible Inferno deals 6 damage to target creature.\n"
        "Delirium — If there are four or more card types among "
        "cards in your graveyard, exile the top card of your "
        "library. You may play it until the end of your next turn."
    ): DealDamageToTargetCreature(amount=6),
    # Violent Urge (Duskmourn) ``{R}`` Instant — +1/+0 first-strike
    # UEOT pump plus a Delirium-gated double-strike upgrade rider
    # ("If there are four or more card types among cards in your
    # graveyard, that creature gains double strike until end of
    # turn."). Whole-spell exact-text dispatch simplifies to bare
    # ``PumpTargetCreatureUntilEOT(power_bonus=1, granted_keywords=
    # frozenset({"first strike"}))`` — the base mechanic is preserved
    # (the +1/+0 plus first strike UEOT) and the Delirium-gated
    # double-strike upgrade is dropped. Same parser-is-right
    # precedent as Impossible Inferno: no Delirium-gated conditional
    # dispatcher in the spell-builder today, and the second clause
    # doesn't parse as a standalone spell-effect phrase. The
    # ``first strike`` keyword grant rides on the existing
    # ``PumpTargetCreatureUntilEOT.granted_keywords`` field already
    # used by other DSK pump spells (no new field needed).
    (
        "Target creature gets +1/+0 and gains first strike until end "
        "of turn.\n"
        "Delirium — If there are four or more card types among "
        "cards in your graveyard, that creature gains double strike "
        "until end of turn."
    ): PumpTargetCreatureUntilEOT(
        power_bonus=1,
        toughness_bonus=0,
        granted_keywords=frozenset({"first strike"}),
    ),
    # Drag to the Roots (Duskmourn) ``{2}{B}{G}`` Instant — Delirium-
    # gated ``{2}``-cost-reduction rider plus a bare destroy-target-
    # nonland-permanent body. Whole-spell exact-text dispatch
    # simplifies to bare ``DestroyTargetNonlandPermanent()`` because:
    # (1) the cost-reduction parser ``_parse_cost_reduction_line``
    #     recognizes only the ``This spell costs {N} less to cast if
    #     <condition>.`` and ``... cast <connector>.`` shapes, not
    #     the ``Delirium — This spell costs {N} less to cast as
    #     long as <condition>.`` shape with the ability-word prefix
    #     and the ``as long as`` connector — adding it would require
    #     a new ``four_or_more_card_types_in_graveyard`` engine
    #     condition key plus a matching branch in
    #     ``mtg_bot.actions._evaluate_cost_reduction``, neither of
    #     which exists today and would be a one-off for this card;
    # (2) the per-clause grammar drops the cost-reduction rider via
    #     ``_parse_cost_reduction_line`` only when that helper
    #     recognizes the line, so an unrecognized cost-reduction
    #     leaves the clause intact and the spell fails to parse.
    # Same parser-is-right precedent as the other Delirium-gated
    # drops (Impossible Inferno, Violent Urge): keep the base
    # mechanic (destroy a nonland permanent at the printed full
    # cost) and drop the unmodelable Delirium cost discount.
    (
        "Delirium — This spell costs {2} less to cast as long "
        "as there are four or more card types among cards in your "
        "graveyard.\n"
        "Destroy target nonland permanent."
    ): DestroyTargetNonlandPermanent(),
    # Come Back Wrong (Duskmourn) ``{2}{B}`` Sorcery — destroy
    # target creature with a conditional reanimate-then-sac-next-
    # end-step rider ("If a creature card is put into a graveyard
    # this way, return it to the battlefield under your control.
    # Sacrifice it at the beginning of your next end step."). Whole-
    # spell exact-text dispatch simplifies to bare
    # ``DestroyTargetCreature()`` because:
    # (1) the rider is a conditional reanimation chained to the
    #     destruction's outcome (only fires if the destroyed
    #     creature was actually put into a graveyard — tokens,
    #     indestructible creatures, and replacement-effect-killed
    #     creatures don't trigger it), plus a one-shot delayed
    #     end-step sacrifice trigger on the reanimated creature;
    #     the engine has no "if a creature card was put into
    #     graveyard this way, reanimate-and-schedule-end-step-sac"
    #     primitive and no per-target delayed sacrifice trigger
    #     plumbing;
    # (2) the per-clause grammar can't claim the second and third
    #     sentences as standalone spell-effect phrases either —
    #     both are riders on the resolution of the first sentence,
    #     not self-contained effects.
    # Same parser-is-right precedent as Trial of Agony (drop the
    # multi-target opp-choice + can't-block rider, keep the bare
    # 5-damage burn): keep the base destroy and drop the
    # unmodelable conditional reanimation rider.
    (
        "Destroy target creature. If a creature card is put into a "
        "graveyard this way, return it to the battlefield under "
        "your control. Sacrifice it at the beginning of your next "
        "end step."
    ): DestroyTargetCreature(),
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
    clauses = [s for c in clauses for s in _split_sentences(c)]
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
