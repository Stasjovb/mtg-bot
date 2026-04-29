"""Printing-level parametric keywords (Warp, Ward, Devour, Impending).

These take a numeric/mana-cost argument so they don't fit the
literal-line ``_KEYWORD_LINES`` map in ``keywords.py``. They share
the same shape: a keyword name followed by its argument on its own
line, with optional parenthesized reminder text. The argument
round-trips into the ``make_creature`` ``warp=`` / ``ward=`` /
``devour_land_multiplier=`` / ``impending=``+``impending_count=``
kwarg.

Two ``Ward`` non-mana-cost rider shapes are also recognized: the
em-dash discard-cost variants ``Ward—Discard a card.`` and
``Ward—Discard a card at random.`` (Sunset Saboteur and Alpharael
Stonechosen respectively). Each produces a sentinel return value
that the creature builder maps to the matching
``ward_discard_chosen=True`` / ``ward_discard_random=True`` kwarg
on ``make_creature``. Other riders (``Warp—{B}, Pay 2 life.``
additional-life-cost variants etc.) remain out of scope — they
intentionally don't match and cause the enclosing card to be
skipped.
"""

from __future__ import annotations

import re


_WARP_LINE = re.compile(
    r"^Warp (\{[^}]+\}(?:\{[^}]+\})*)(?: \([^)]*\))?$"
)


def _parse_warp_line(line: str) -> str | None:
    """Return the warp cost string (e.g. ``"{1}{R}"``) if ``line`` is a
    simple Warp clause, else ``None``. Lines with riders (additional
    life cost, graveyard-castable, etc.) intentionally don't match.
    """
    m = _WARP_LINE.match(line.strip())
    if m is None:
        return None
    return m.group(1)


_WARD_LINE = re.compile(
    r"^Ward (\{[^}]+\}(?:\{[^}]+\})*)(?: \([^)]*\))?$"
)


def _parse_ward_line(line: str) -> str | None:
    """Return the ward cost string (e.g. ``"{2}"``) if ``line`` is a
    simple ``Ward {cost}`` clause, else ``None``. Lines with riders
    (em-dash + life cost, em-dash + discard) intentionally don't match.
    """
    m = _WARD_LINE.match(line.strip())
    if m is None:
        return None
    return m.group(1)


# ``Ward—Discard a card.`` / ``Ward—Discard a card at random.`` —
# em-dash discard-cost ward riders. Scryfall prints both variants
# verbatim with no surrounding reminder text. The two variants are
# distinguished only by the trailing ``at random`` qualifier; the
# function below returns a tagged string (``"chosen"`` or
# ``"random"``) so the creature builder can map it to the matching
# ``make_creature`` boolean kwarg without re-parsing.
_WARD_DISCARD_LINE = re.compile(
    r"^Ward—Discard a card(?P<random> at random)?\.$"
)


def _parse_ward_discard_line(line: str) -> str | None:
    """Return ``"chosen"`` for ``Ward—Discard a card.``, ``"random"``
    for ``Ward—Discard a card at random.``, or ``None`` if the line
    doesn't match either em-dash discard-cost ward shape.

    Two variants only — Scryfall consistently prints these exact
    surface forms; any other discard-cost ward (a future ``Ward—
    Discard two cards.`` printing, say) would land its own entry
    rather than parameterizing this one. Keeping the surface→tag
    mapping 1:1 with the engine's ``ward_discard_chosen`` /
    ``ward_discard_random`` boolean fields preserves parser/static
    parity by construction.
    """
    m = _WARD_DISCARD_LINE.match(line.strip())
    if m is None:
        return None
    return "random" if m.group("random") else "chosen"


_IMPENDING_LINE = re.compile(
    # Impending N—{cost}. Scryfall uses an em-dash (U+2014). The
    # reminder text is stripped per-line by ``_strip_reminder_text``
    # before this lookup runs, so we match the bare keyword line.
    r"^Impending (\d+)—(\{[^}]+\}(?:\{[^}]+\})*)$"
)


def _parse_impending_line(line: str) -> tuple[int, str] | None:
    """Return ``(N, cost_str)`` if ``line`` is an Impending clause
    (``Impending N—{cost}``), else ``None``.

    Matches the verbatim Duskmourn Overlord cycle surface form. The
    reminder text — "(If you cast this spell for its impending cost,
    it enters with N time counters and isn't a creature until the
    last is removed. At the beginning of your end step, remove a
    time counter from it.)" — is stripped via the existing per-line
    reminder-text stripper before this lookup runs, so we only have
    to match the bare keyword line.
    """
    m = _IMPENDING_LINE.match(line.strip())
    if m is None:
        return None
    return int(m.group(1)), m.group(2)


_DEVOUR_LINE = re.compile(
    r"^Devour land (\d+)(?: \([^)]*\))?$"
)


def _parse_devour_line(line: str) -> int | None:
    """Return the devour multiplier ``N`` (an int) if ``line`` is a
    simple ``Devour land N`` clause, else ``None``. The EoE printing
    is Famished Worldsire's ``Devour land 3`` (sacrifice any number of
    lands; enter with three times that many +1/+1 counters). Lines
    with riders or non-``land`` Devour variants intentionally don't
    match — the enclosing card falls through and is skipped.
    """
    m = _DEVOUR_LINE.match(line.strip())
    if m is None:
        return None
    return int(m.group(1))


# ``This creature enters tapped.`` — printing-level static replacement
# (CR 614) flipping the existing ``enters_tapped: bool`` field on the
# card printing. The engine already consults this field at ETB time
# (``actions.put_into_battlefield`` and ``effects/combinators.py``);
# the parser side has been missing the line recognizer. Surfaces on
# Piranha Fly's two-line oracle text alongside Flying.
#
# A literal-string match is sufficient — no card today varies the
# wording. A future printing whose surface text differs (``This
# permanent enters tapped`` for a non-creature, or a numeric variant)
# would land its own entry rather than parameterizing this one,
# matching the ``Ward—Discard`` precedent above where each surface
# gets its own 1:1 recognizer.
_ENTERS_TAPPED_LINE = "This creature enters tapped."


def _parse_enters_tapped_line(line: str) -> bool:
    """Return ``True`` if ``line`` is the printing-level ``This creature
    enters tapped.`` clause, else ``False``. Used by
    ``creature_builder._build_creature_printing`` to flip the
    ``enters_tapped`` kwarg on ``make_creature`` directly — distinct
    from the triggered-ability path because the ETB-tapped behavior is
    a static replacement effect, not an event-firing trigger.
    """
    return line.strip() == _ENTERS_TAPPED_LINE


# ``This creature must be blocked if able.`` — printing-level static
# block-requirement (CR 509.1c). Surfaces on Fear of Being Hunted
# alongside Haste. The matching engine flag
# (``CardPrinting.must_be_blocked_if_able``) is consumed by
# ``actions._declare_blockers``: if no validated blocker is assigned
# to the attacker and at least one eligible defender exists that
# could legally block it, the engine forces one. A literal-string
# match is sufficient; future related surfaces (``This creature can't
# be blocked except by …``) would land their own recognizers.
_MUST_BE_BLOCKED_LINE = "This creature must be blocked if able."


def _parse_must_be_blocked_line(line: str) -> bool:
    """Return ``True`` if ``line`` is the printing-level ``This creature
    must be blocked if able.`` clause, else ``False``. Used by
    ``creature_builder._build_creature_printing`` to flip the
    ``must_be_blocked_if_able`` kwarg on ``make_creature``.
    """
    return line.strip() == _MUST_BE_BLOCKED_LINE


# ``Nonbasic lands are Mountains.`` — Magus of the Moon's printed
# static effect. The engine wires the layer-4 type-replacement off
# the printing-level ``nonbasic_lands_are_mountains`` flag (rather
# than a generic ``StaticAbility`` shape, since the type replacement
# isn't a creature-relative continuous effect). Matched as a literal
# string; a future card with the same shape but different source
# (Blood Moon-style enchantment) would route through whatever
# oracle-text parser owns its card type and reuse the same flag.
_NONBASIC_LANDS_ARE_MOUNTAINS_LINE = "Nonbasic lands are Mountains."


def _parse_nonbasic_lands_are_mountains_line(line: str) -> bool:
    """Return ``True`` if ``line`` is the printing-level
    ``Nonbasic lands are Mountains.`` clause, else ``False``. Flips the
    ``nonbasic_lands_are_mountains`` kwarg on ``make_creature`` /
    ``make_enchantment``; the engine reads the flag at land ETB and
    layer-4 type-replacement application time.
    """
    return line.strip() == _NONBASIC_LANDS_ARE_MOUNTAINS_LINE


# ``Each player can't cast more than one noncreature spell each turn.``
# — Deafening Silence's printed static. The engine wires the cast-
# pipeline gate off the printing-level
# ``restricts_noncreature_spells_to_one_per_turn`` flag (rather than a
# generic ``StaticAbility`` shape, since the cast-restriction lives
# pre-stack and isn't a creature-relative continuous effect). Matched
# as a literal string; a future card with a similar restriction would
# get its own recognizer here.
_RESTRICTS_NONCREATURE_SPELLS_LINE = (
    "Each player can't cast more than one noncreature spell each turn."
)


def _parse_restricts_noncreature_spells_line(line: str) -> bool:
    """Return ``True`` if ``line`` is the printing-level Deafening
    Silence static, else ``False``. Flips the
    ``restricts_noncreature_spells_to_one_per_turn`` kwarg on
    ``make_enchantment``; the engine reads the flag in the cast pipeline
    to gate noncreature spell casts after the first per turn.
    """
    return line.strip() == _RESTRICTS_NONCREATURE_SPELLS_LINE


# ``If one or more tokens would be created under your control, twice
# that many of those tokens are created instead.`` — Exalted Sunborn's
# printed token-doubler replacement effect. The engine wires the
# replacement off the printing-level ``is_token_doubler`` flag (rather
# than a generic ``StaticAbility`` shape, since token replacement
# happens at create-token resolution rather than as a creature-relative
# continuous effect). Matched as a literal string — Exalted Sunborn is
# the only card in the pool with this exact surface today; "broader
# grammar deferred until a second example exists" (e.g. a hypothetical
# Anointed-Procession-style enchantment with the same shape would land
# its own recognizer or, if a parameter varies, parameterize this one).
_TOKEN_DOUBLER_LINE = (
    "If one or more tokens would be created under your control, "
    "twice that many of those tokens are created instead."
)


def _parse_token_doubler_line(line: str) -> bool:
    """Return ``True`` if ``line`` is the printing-level token-doubler
    replacement clause, else ``False``. Flips the ``is_token_doubler``
    kwarg on ``make_creature``; the engine reads the flag at
    create-token resolution time and doubles the count.
    """
    return line.strip() == _TOKEN_DOUBLER_LINE


# ``If a permanent entering the battlefield causes a triggered ability
# of a permanent you control to trigger, that ability triggers an
# additional time.`` — Starfield Vocalist's printed ETB-trigger
# doubler. The engine wires the extra-trigger replacement off the
# printing-level ``extra_etb_trigger`` int field (incremented on the
# permanent; the trigger pipeline reads the controller's battlefield
# total). Matched as a literal string — Starfield Vocalist is the only
# card in the pool with this exact surface today; "broader grammar
# deferred until a second example exists" (a hypothetical
# Panharmonicon-style printing with the same shape would either land
# its own recognizer or, if a parameter such as the trigger count
# varies, parameterize this one).
_EXTRA_ETB_TRIGGER_LINE = (
    "If a permanent entering the battlefield causes a triggered "
    "ability of a permanent you control to trigger, that ability "
    "triggers an additional time."
)


def _parse_extra_etb_trigger_line(line: str) -> bool:
    """Return ``True`` if ``line`` is the printing-level
    Panharmonicon-style ETB-trigger doubler clause, else ``False``.
    Adds 1 to the ``extra_etb_trigger`` kwarg on ``make_creature``;
    the engine reads the controller's battlefield total at trigger
    enqueue time and adds that many extra firings.
    """
    return line.strip() == _EXTRA_ETB_TRIGGER_LINE


# ``As long as you have one or fewer cards in hand, if you would draw
# one or more cards, you draw that many cards plus one instead.`` —
# Quantum Riddler's printed draw-replacement static. The engine wires
# the replacement off the printing-level
# ``replaces_draw_with_extra_when_hand_at_most_one`` flag (rather than
# a generic ``StaticAbility`` shape, since draw replacement happens at
# draw resolution time and reads the controller's hand size). Matched
# as a literal string — Quantum Riddler is the only card in the pool
# with this exact surface today; "broader grammar deferred until a
# second example exists" (a future printing whose hand-size threshold
# differs would parameterize this recognizer's threshold capture).
_REPLACES_DRAW_WHEN_HAND_AT_MOST_ONE_LINE = (
    "As long as you have one or fewer cards in hand, if you would "
    "draw one or more cards, you draw that many cards plus one "
    "instead."
)


def _parse_replaces_draw_when_hand_at_most_one_line(line: str) -> bool:
    """Return ``True`` if ``line`` is the printing-level draw-replacement
    clause for hand-size at-most-one, else ``False``. Flips the
    ``replaces_draw_with_extra_when_hand_at_most_one`` kwarg on
    ``make_creature``; the engine reads the flag at draw resolution
    time and adds one extra card when the controller's hand is at
    most one card.
    """
    return line.strip() == _REPLACES_DRAW_WHEN_HAND_AT_MOST_ONE_LINE


# ``As long as an artifact entered the battlefield under your control
# this turn, this creature can attack as though it didn't have
# defender.`` — Mechan Shieldmate's printed defender-bypass static.
# The engine wires the bypass off the printing-level
# ``attack_bypass_if_artifact_entered_this_turn`` boolean flag (rather
# than a generic ``StaticAbility`` shape, since the attack-eligibility
# check sits in ``combat._can_attack_through_defender`` and reads the
# controller's per-turn artifact-entered counter). Matched as a literal
# string — Mechan Shieldmate is the only card in the pool with this
# exact surface today; "broader grammar deferred until a second
# example exists" (a future printing whose triggering condition
# differs — ``a creature entered``, ``a Spacecraft entered``, etc. —
# would parameterize this recognizer's permanent-type capture).
_ATTACK_BYPASS_IF_ARTIFACT_ENTERED_LINE = (
    "As long as an artifact entered the battlefield under your control "
    "this turn, this creature can attack as though it didn't have "
    "defender."
)


def _parse_attack_bypass_if_artifact_entered_line(line: str) -> bool:
    """Return ``True`` if ``line`` is the printing-level
    ``As long as an artifact entered the battlefield under your control
    this turn, this creature can attack as though it didn't have
    defender.`` clause, else ``False``. Flips the
    ``attack_bypass_if_artifact_entered_this_turn`` kwarg on
    ``make_creature``; the engine reads the flag in
    ``combat._can_attack_through_defender`` and lets the source attack
    despite Defender once the controller's per-turn artifact-entered
    counter is positive.
    """
    return line.strip() == _ATTACK_BYPASS_IF_ARTIFACT_ENTERED_LINE


# ``This creature can't be blocked if you've cast two or more spells
# this turn.`` — Illvoi Infiltrator's printed conditional-unblockable
# static. The engine wires the unblockable check off the printing-level
# ``unblockable_if_two_spells_cast_this_turn`` boolean flag (rather
# than a generic ``StaticAbility`` shape, since the unblockability
# decision sits in ``combat`` and reads the controller's per-turn
# spells-cast counter). Matched as a literal string — Illvoi
# Infiltrator is the only card in the pool with this exact surface
# today; "broader grammar deferred until a second example exists" (a
# future printing whose threshold differs — ``three or more spells``,
# ``a noncreature spell``, etc. — would parameterize this recognizer's
# threshold/spell-type capture).
_UNBLOCKABLE_IF_TWO_SPELLS_CAST_THIS_TURN_LINE = (
    "This creature can't be blocked if you've cast two or more spells "
    "this turn."
)


def _parse_unblockable_if_two_spells_cast_this_turn_line(line: str) -> bool:
    """Return ``True`` if ``line`` is the printing-level
    ``This creature can't be blocked if you've cast two or more spells
    this turn.`` clause, else ``False``. Flips the
    ``unblockable_if_two_spells_cast_this_turn`` kwarg on
    ``make_creature``; the engine reads the flag in ``combat`` (both
    legality at declare-blockers and the cast-time validation hook)
    and treats the creature as unblockable once the controller has
    cast two or more spells this turn.
    """
    return line.strip() == _UNBLOCKABLE_IF_TWO_SPELLS_CAST_THIS_TURN_LINE


# ``This creature gets +X/+0, where X is the greatest mana value among
# other artifacts you control.`` — Emissary Escort's printed dynamic-
# power static. The engine wires the dynamic P/T off the printing-level
# ``dynamic_pt_formula`` string field (rather than a generic
# ``StaticAbility`` shape, since the formula evaluation lives in
# ``game._dynamic_pt`` and reads the controller's battlefield each
# query). Matched as a literal string — Emissary Escort is the only
# card in the pool with this exact surface today; "broader grammar
# deferred until a second example exists" (a future printing whose
# X-source phrase differs — e.g. ``+X/+0 where X is the number of
# artifacts you control``, or a different baseline P/T offset — would
# parameterize this recognizer's X-source capture).
_EMISSARY_ESCORT_DYNAMIC_PT_LINE = (
    "This creature gets +X/+0, where X is the greatest mana value "
    "among other artifacts you control."
)


def _parse_emissary_escort_dynamic_pt_line(line: str) -> str | None:
    """Return ``"emissary_escort"`` if ``line`` is Emissary Escort's
    printed dynamic-power static, else ``None``. The returned string is
    the formula key consumed by ``game._dynamic_pt``; the creature
    builder forwards it as the ``dynamic_pt_formula`` kwarg on
    ``make_creature``.

    Distinct from a boolean recognizer because future X-source variants
    (different formula keys mapping to different in-engine
    computations) will share this same recognizer slot — each new
    surface form lands its own line→key entry while the wiring stays
    centralized.
    """
    if line.strip() == _EMISSARY_ESCORT_DYNAMIC_PT_LINE:
        return "emissary_escort"
    return None


# Basic-landcycling: ``<Land>cycling {cost}`` where ``<Land>`` is one of
# the five basic-land subtypes. CR 702.29 typecycling — while the card
# is in the controller's hand, they may pay the cycling cost and discard
# this card to search their library for a basic-land card of the named
# subtype, reveal it, put it into their hand, then shuffle. The subtype
# capitalizes per the printed line (``Plains`` / ``Island`` / ``Swamp``
# / ``Mountain`` / ``Forest``); the cost is one or more brace-wrapped
# mana symbols. The line's parenthesized reminder text is stripped by
# the per-line ``_strip_reminder_text`` step before this lookup runs,
# so the regex matches the bare keyword head only.
#
# Each of the five basic-land subtypes shares the same engine field
# layout (``CardPrinting.landcycling = (subtype, cost_str)``), so this
# single recognizer covers the whole DSK landcycling-{2} cycle
# (Shepherding Spirits, Daggermaw Megalodon, Spectral Snatcher, Bedhead
# Beastie, Slavering Branchsnapper). A future printing whose oracle
# uses non-basic typecycling (``Spiritcycling``, ``Wizardcycling``)
# would need its own recognizer — this one anchors on the five basic-
# land subtypes by name to keep the grammar's surface form 1:1 with
# the engine field's expected ``land_subtype`` values.
_LANDCYCLING_LINE = re.compile(
    r"^(?P<subtype>Plains|Island|Swamp|Mountain|Forest)cycling "
    r"(?P<cost>\{[^}]+\}(?:\{[^}]+\})*)$"
)


_ENTERS_WITH_PLUS_ONE_IF_DEATH_LINE = (
    "This creature enters with a +1/+1 counter on it if a creature died "
    "this turn."
)


def _parse_enters_with_plus_one_counter_if_creature_died_line(
    line: str,
) -> bool:
    """Return ``True`` if ``line`` is the printing-level ``This creature
    enters with a +1/+1 counter on it if a creature died this turn.``
    clause, else ``False``.

    Surfaces on Cackling Slasher's two-line oracle alongside Deathtouch.
    A literal-string match is sufficient — no card today varies the
    wording. The matching engine field
    (``CardPrinting.enters_with_plus_one_counter_if_creature_died_this_
    turn``) is consumed in ``actions.put_into_battlefield``, which
    reads ``state.creatures_died_this_turn`` (incremented in
    ``turn.move_off_battlefield`` and reset at cleanup) and adds a
    +1/+1 counter when the tracker is positive.
    """
    return line.strip() == _ENTERS_WITH_PLUS_ONE_IF_DEATH_LINE


# Spelled-cardinal -1/-1 ETB rider for cast-from-hand. Surfaces on
# Patched Plaything (DSK Toy) as
# ``This creature enters with two -1/-1 counters on it if you cast it
# from your hand.``. The cardinal is captured so a future Plaything
# variant with a different count (one, three, etc.) would map to the
# same engine field with the appropriate value. The literal-string
# fallback for ``two`` matches the only printing today; if a future
# printing prints the digit ``2`` the regex's ``\d+`` arm picks it up
# without any grammar change.
_ENTERS_WITH_MINUS_ONE_FROM_HAND_LINE = re.compile(
    r"^This creature enters with "
    r"(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten) "
    r"-1/-1 counters? on it if you cast it from your hand\.$"
)

_NUMBER_WORD_TO_INT: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _parse_enters_with_minus_one_counters_from_hand_cast_line(
    line: str,
) -> int | None:
    """Return ``N`` (the count of -1/-1 counters) if ``line`` is the
    printing-level ``This creature enters with N -1/-1 counters on it
    if you cast it from your hand.`` clause, else ``None``.

    Patched Plaything is the only DSK printing carrying this surface
    (``two`` -1/-1 counters). The regex accepts both spelled-out
    cardinals (one through ten) and a digit fallback so a forward-
    looking printing with a different count or numerical surface
    lands the same field. The matching engine field
    (``CardPrinting.enters_with_minus_one_counters_from_hand_cast``)
    is consumed in ``actions.put_into_battlefield`` only when the
    GameObject's ``cast_via_hand`` flag is set — the cast-from-exile
    / library / graveyard paths clear that flag, so the rider stays
    inert on those resolutions (matching the printed "if you cast
    it from your hand" gate).
    """
    m = _ENTERS_WITH_MINUS_ONE_FROM_HAND_LINE.match(line.strip())
    if m is None:
        return None
    raw = m.group("count")
    if raw.isdigit():
        return int(raw)
    return _NUMBER_WORD_TO_INT[raw]


def _parse_landcycling_line(line: str) -> tuple[str, str] | None:
    """Return ``(land_subtype, mana_cost_str)`` if ``line`` is a
    basic-landcycling clause (``<Land>cycling {cost}``), else ``None``.

    The five basic-land subtypes are matched by name; non-basic
    typecycling (no DSK printing today) intentionally doesn't match
    and falls through. The mana-cost capture preserves the printed
    cost string verbatim — e.g. ``{2}`` for the DSK cycle, ``{1}{R}``
    for any forward-looking hybrid-cost printing — which the engine
    field stores as-is for future activation-pipeline support.

    Reminder text is stripped via the existing per-line
    ``_strip_reminder_text`` helper before this lookup runs, so the
    regex only has to match the bare keyword head.
    """
    m = _LANDCYCLING_LINE.match(line.strip())
    if m is None:
        return None
    return m.group("subtype"), m.group("cost")
