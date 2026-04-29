"""Static-ability grammar.

Two families of static-ability surface forms are recognized.

**Self-scope** ``As long as``-gated lines come in two shapes:

* **Leading** ``As long as <condition>, this creature gets +N/+N[ and has
  <keyword>].`` — the original shape. Cloudsculpt Technician and
  Gravblade Heavy in EoE.
* **Trailing** ``This creature gets +N/+N[ and has <keyword>] as long as
  <condition>.`` — the rider trails the P/T modifier. Brightspear
  Zealot in EoE prints in this form.

Both shapes share the same condition phrasebook and produce identical
``StaticAbility`` outputs; the parser tries the leading regex first
and falls back to the trailing regex.

Recognized self-scope conditions today:

* ``you control an artifact`` →
  ``requires_artifact_you_control=True`` (Cloudsculpt Technician,
  Gravblade Heavy).
* ``you've cast two or more spells this turn`` →
  ``requires_spells_cast_this_turn=2`` (Brightspear Zealot, via the
  trailing shape).
* ``you've cast three or more spells this turn`` →
  ``requires_spells_cast_this_turn=3``. Batch-11 forward-looking
  variant of the existing ``two or more`` phrase — same engine gate
  field with a higher threshold. No EoE printing today uses this
  threshold but the engine accepts any ``int >= 0`` and the surface
  phrasing is the natural one-word substitution from the ``two``
  variant; adding it keeps the parser ready for printings that
  raise the bar (and makes the threshold-vs-phrase mapping explicit
  in the phrasebook rather than implicit in regex generality).
* ``it's your turn`` → ``active_turn_only=True``. Forward-looking
  grammar coverage; no EoE card prints in the leading/trailing
  self-scope shape with this condition today, but the engine field
  exists and the surface phrase is unambiguous.

Other "As long as" conditions (entered-this-turn, void, you-control-a-
creature, etc.) have no matching engine gate; they intentionally don't
match and the card falls through.

**Anthem-scope** lines target other permanents, not the source. Surface
shapes recognized:

* ``Creatures you control get +N/+M.`` →
  ``StaticScope.CREATURES_YOU_CONTROL`` with the P/T bonus.
* ``Other creatures you control get +N/+M.`` →
  ``StaticScope.OTHER_CREATURES_YOU_CONTROL`` with the P/T bonus.
* ``Creatures you control have <keyword>.`` /
  ``Other creatures you control have <keyword>.`` — keyword-only
  anthems (Tannuk-shape; ``power_bonus``/``toughness_bonus`` stay 0).
* ``... get +N/+M and have <keyword>.`` — combined P/T + keyword
  anthem.
* Optional leading ``During your turn, `` rider on any of the above
  sets ``active_turn_only=True``. Memorial Team Leader prints in this
  shape (``During your turn, other creatures you control get +1/+0.``).

Anthem lines do NOT carry an ``As long as`` condition today; the
self-scope condition phrasebook is therefore not consulted. If a future
printing combines the two we would extend the anthem regex rather than
the self-scope regex (the two surface families have already diverged
enough that a single combined grammar would be hard to read).

**Counter-gated anthem** lines name a per-creature counter filter as
part of the subject rather than as an ``As long as`` condition:

* ``Each creature you control with a +1/+1 counter on it has
  <keyword>.`` → ``StaticScope.CREATURES_YOU_CONTROL_WITH_COUNTER``
  with the keyword grant. Drix Fatemaker prints in this shape. The
  scope itself is what carries the "filter to creatures with a
  +1/+1 counter" semantics — the engine's ``applies_to`` checks
  ``target.plus_one_counters > 0`` for this scope. Subject is
  ``Each creature`` (singular, no ``Other`` variant in EoE today)
  and the verb is therefore ``has`` rather than the plural-anthem
  ``have``.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import StaticAbility, StaticScope
from mtg_bot.cards.parser.keywords import _KEYWORD_LINES


# Ability-word prefix stripper for static lines. Mirrors the trigger-
# layer ``_ABILITY_WORD_PREFIX`` regex but anchors on the static-line
# bodies the parser already accepts (``As long as``,
# ``This creature gets``, ``Creatures you control``, ``Other creatures
# you control``, and ``Each creature you control``). Ability words have
# no rules consequence (CR 207.2c) so the stripped prefix simply
# disappears; the body underneath parses through the existing
# self-scope, anthem-scope, and counter-gated grammars unchanged.
#
# The regex is conservative: it only matches when the body looks like
# one of the static surface families above, so a line that happens to
# start with ``Foo — `` for some other reason (a triggered-ability
# ``<Word> — Whenever ...`` line, say) doesn't get clobbered here. A
# trigger-layer prefix would already have been stripped before the
# clause dispatcher reached the static path; the static stripper exists
# specifically for the Delirium static surface where the body is a
# ``This creature gets`` / ``Creatures you control`` line, not a
# ``When``/``Whenever`` line.
_STATIC_ABILITY_WORD_PREFIX = re.compile(
    r"^[A-Z][A-Za-z]*(?: [A-Z][A-Za-z]*)* — "
    r"(?=As long as |This creature gets |[Cc]reatures you control |"
    r"[Oo]ther creatures you control |Each creature you control )"
)


def _strip_static_ability_word_prefix(line: str) -> str:
    """Strip a generic ``<Ability Word> — `` prefix from ``line`` when
    one precedes a recognized static-line body.

    Static ability words (Duskmourn's Delirium, principally) carry no
    rules meaning per CR 207.2c, so the parser doesn't need to know
    which ability word it's looking at — the substance lives entirely
    in the body that follows. Returns ``line`` unchanged when no such
    prefix is present, mirroring the ``_strip_ability_word_prefix``
    helper in ``triggers.py``.
    """
    return _STATIC_ABILITY_WORD_PREFIX.sub("", line, count=1)


_STATIC_ABILITY_LINE = re.compile(
    r"^As long as (?P<condition>.+?), this creature gets "
    r"\+(?P<power>\d+)/\+(?P<toughness>\d+)"
    r"(?: and has (?P<keyword>[A-Za-z ]+))?\.$"
)

# The trailing surface form: same semantics, rider after the P/T
# modifier instead of before it. The optional ``and has <keyword>``
# tail lives between the P/T modifier and the ``as long as`` clause,
# matching how MTG oracle text would print a keyword-granting
# trailing-rider line.
_STATIC_ABILITY_LINE_TRAILING = re.compile(
    r"^This creature gets "
    r"\+(?P<power>\d+)/\+(?P<toughness>\d+)"
    r"(?: and has (?P<keyword>[A-Za-z ]+))?"
    r" as long as (?P<condition>.+?)\.$"
)

# Conditions recognized as gates on the static ability. The mapping is
# from the surface phrase (matched verbatim, no normalization) to the
# kwargs passed to ``StaticAbility``. Each phrase corresponds 1:1 to a
# gate field on ``StaticAbility``; if no field exists for a given
# condition, we deliberately leave it out so the ability falls through
# and the card gets skipped rather than being silently mis-modeled.
_STATIC_CONDITION_KWARGS: dict[str, dict[str, object]] = {
    "you control an artifact": {"requires_artifact_you_control": True},
    "you've cast two or more spells this turn": {
        "requires_spells_cast_this_turn": 2
    },
    # Batch 11 — forward-looking N=3 variant. Same engine gate as the
    # ``two or more`` entry above with a higher threshold; the engine
    # accepts any non-negative integer for ``requires_spells_cast_this_
    # turn`` and the surface phrasing is the natural one-word
    # substitution. No EoE card prints this threshold today.
    "you've cast three or more spells this turn": {
        "requires_spells_cast_this_turn": 3
    },
    "it's your turn": {"active_turn_only": True},
    # Duskmourn "doors among Rooms" gate. Rampaging Soulrager prints
    # ``This creature gets +3/+0 as long as there are two or more
    # unlocked doors among Rooms you control.`` — the trailing-shape
    # static line lands here via its ``as long as <condition>`` tail.
    # Maps to ``requires_unlocked_doors_among_rooms=2``; the engine
    # gate walks the controller's battlefield, sums
    # ``len(unlocked_halves)`` over every Room, and applies the
    # ability only when the total clears the threshold.
    "there are two or more unlocked doors among Rooms you control": {
        "requires_unlocked_doors_among_rooms": 2
    },
    # Duskmourn "Delirium" gate. Wildfire Wickerfolk prints
    # ``Delirium — This creature gets +1/+1 and has trample as long as
    # there are four or more card types among cards in your graveyard.``
    # — the ``Delirium —`` ability word strips through
    # ``_strip_static_ability_word_prefix`` (no rules consequence per
    # CR 207.2c) and the trailing ``as long as`` tail lands here. Maps
    # to ``requires_delirium=True``; the engine gate walks the
    # controller's graveyard, counts distinct card types, and applies
    # the ability only when the total clears four. Same threshold as
    # the trigger-side ``Delirium()`` predicate so static and trigger
    # evaluations agree on game-state semantics.
    "there are four or more card types among cards in your graveyard": {
        "requires_delirium": True
    },
}


# ---------- Anthem-scope grammar ----------
#
# Anthem lines target permanents other than (or including) the source.
# The ``subject`` group captures the surface noun phrase and is mapped
# verbatim to a ``StaticScope`` via ``_ANTHEM_SUBJECT_SCOPES`` — a
# dedicated mapping (rather than reusing ``_STATIC_CONDITION_KWARGS``)
# because subject-vs-condition are orthogonal axes: anthem lines may
# carry a turn-scope rider but never an ``As long as`` clause today,
# so co-locating the two would conflate independent dimensions.
#
# Two body shapes are accepted:
#
# * ``get +N/+M[ and have <keyword>]`` — P/T anthem, optionally with a
#   keyword grant tail. Mirrors the self-scope rider's ``and has``
#   spelling but uses ``and have`` because the subject is plural.
# * ``have <keyword>`` — keyword-only anthem (Tannuk's "Other creatures
#   you control have haste."), with no P/T component.
#
# An optional leading ``During your turn, `` prefix on either body
# sets ``active_turn_only=True``; this is the only "anthem condition"
# surface form in EoE today (Memorial Team Leader). The parser tries
# the P/T regex first and falls back to the keyword-only regex; both
# share the same ``subject`` and ``turn_rider`` groups so the shared
# parse function reads either match by name.

_ANTHEM_SUBJECT_SCOPES: dict[str, str] = {
    "creatures you control": StaticScope.CREATURES_YOU_CONTROL,
    "other creatures you control": StaticScope.OTHER_CREATURES_YOU_CONTROL,
    # Lecture Hall (DSK Room half) prints ``Other permanents you control
    # have hexproof.`` — strictly broader than "Other creatures" (also
    # affects non-creature permanents). The engine's ``applies_to``
    # walk is creature-only today (``is_creature_now`` short-circuits
    # for non-creatures), so ``OTHER_CREATURES_YOU_CONTROL`` is the
    # widest scope that produces an honest, engine-observable static —
    # a faithful approximation of the printed surface where the
    # difference (hexproof grant on non-creature permanents) is
    # immaterial as long as hexproof remains engine-unenforced
    # metadata. When hexproof becomes targeting-site-checked AND a
    # broader ``OTHER_PERMANENTS_YOU_CONTROL`` scope ships, this entry
    # should switch to that scope to recover full faithfulness.
    "other permanents you control": StaticScope.OTHER_CREATURES_YOU_CONTROL,
    # The Seriema's printed always-on static — narrows the anthem to
    # legendary creatures the controller controls AND that are tapped,
    # excluding the source. The engine's ``applies_to`` already
    # implements this filter (see ``StaticScope.OTHER_TAPPED_
    # LEGENDARY_CREATURES_YOU_CONTROL`` branch in ``effects/base.py``);
    # it does not depend on the source being a creature, so the static
    # fires whether or not the Spacecraft is stationed.
    "other tapped legendary creatures you control": (
        StaticScope.OTHER_TAPPED_LEGENDARY_CREATURES_YOU_CONTROL
    ),
}

# The subject's first letter is capitalized at the start of an oracle
# line ("Creatures you control ...") but lowercase when it follows a
# leading rider ("During your turn, other creatures you control ...").
# The regex normalizes by lowercasing the captured group before
# looking it up in ``_ANTHEM_SUBJECT_SCOPES``; both surface
# capitalizations map to the same scope.
_ANTHEM_SUBJECT_RE = (
    r"(?P<subject>[Cc]reatures you control"
    r"|[Oo]ther creatures you control"
    r"|[Oo]ther permanents you control"
    r"|[Oo]ther tapped legendary creatures you control)"
)
_ANTHEM_TURN_RIDER_RE = r"(?P<turn_rider>During your turn, )?"

_ANTHEM_PT_LINE = re.compile(
    rf"^{_ANTHEM_TURN_RIDER_RE}{_ANTHEM_SUBJECT_RE} get "
    r"\+(?P<power>\d+)/\+(?P<toughness>\d+)"
    r"(?: and have (?P<keyword>[A-Za-z ]+))?\.$"
)

# Keyword-only anthem: ``[During your turn, ]<subject> have <keyword>.``
# No P/T component; ``power``/``toughness`` default to 0 in the
# resulting ``StaticAbility``. The ``turn_rider`` capture mirrors the
# P/T regex so the shared parse function can read it the same way.
_ANTHEM_KEYWORD_LINE = re.compile(
    rf"^{_ANTHEM_TURN_RIDER_RE}{_ANTHEM_SUBJECT_RE} have "
    r"(?P<keyword>[A-Za-z ]+)\.$"
)


# Counter-gated anthem: ``Each creature you control with a +1/+1
# counter on it has <keyword>.`` — singular subject ("Each creature")
# pinned by the regex, no ``During your turn,`` rider in EoE today
# (the rider would be unambiguously parseable but no card prints it,
# so we keep this regex narrow to the surface form actually seen).
# Scope is fixed: every match maps to
# ``StaticScope.CREATURES_YOU_CONTROL_WITH_COUNTER``, so we don't need
# a subject-to-scope mapping like the plural anthems use.
_COUNTER_GATED_ANTHEM_LINE = re.compile(
    r"^Each creature you control with a \+1/\+1 counter on it has "
    r"(?P<keyword>[A-Za-z ]+)\.$"
)

# Player-scope static: ``You have no maximum hand size.`` — Steaming
# Sauna (DSK Room half) is the only EoE/DSK card in the parser pool
# today fitting this exact surface (Marina Vendrell's Grimoire
# combines it with other rules in a multi-line oracle and isn't yet
# claimed by the parser). Per parser/CLAUDE.md a literal-line
# recognizer is acceptable when one card in the pool fits AND the
# docstring notes deferred generalization — when a second printing
# with this surface lands (or with sibling player-scope statics like
# "you don't lose the game for having 0 or less life"), the right
# move is a parameterized player-scope-static regex driving an
# enum/flag dispatch, replacing this literal.
_NO_MAX_HAND_SIZE_LINE = re.compile(r"^You have no maximum hand size\.$")


def _parse_anthem_static_line(line: str) -> StaticAbility | None:
    """Return a ``StaticAbility`` for an anthem-shape static line, or
    ``None`` if the surface form doesn't match, the subject isn't a
    recognized scope, or the granted keyword (if any) isn't a known
    evergreen.

    Tries ``_ANTHEM_PT_LINE`` first (P/T-bearing, with optional
    ``and have <keyword>`` tail) and falls back to
    ``_ANTHEM_KEYWORD_LINE`` (keyword-only, no P/T). Both regexes
    expose the same ``subject`` and ``turn_rider`` groups so the
    scope-and-rider mapping is identical between the two; only the
    P/T extraction differs.

    Capitalization sensitivity: the lowercase ``creatures you control``
    spelling never starts an oracle line in EoE, so the regex requires
    the leading capital. If a future printing nests an anthem inside
    a longer sentence, this routine intentionally won't match — pulling
    anthems out of mid-sentence context is a different parse problem.
    """
    stripped = line.strip()
    m = _ANTHEM_PT_LINE.match(stripped)
    power_bonus = 0
    toughness_bonus = 0
    if m is not None:
        power_bonus = int(m.group("power"))
        toughness_bonus = int(m.group("toughness"))
    else:
        m = _ANTHEM_KEYWORD_LINE.match(stripped)
        if m is None:
            return None
    scope = _ANTHEM_SUBJECT_SCOPES.get(m.group("subject").lower())
    if scope is None:
        # Defensive: the regex alternation only matches subjects that
        # appear in the mapping, so this branch is unreachable today.
        # Kept as belt-and-braces against future edits to the regex
        # that add a subject without updating the mapping.
        return None
    granted: frozenset[str] = frozenset()
    keyword = m.group("keyword")
    if keyword is not None:
        engine_keyword = _KEYWORD_LINES.get(keyword.strip().capitalize())
        if engine_keyword is None:
            return None
        granted = frozenset({engine_keyword})
    return StaticAbility(
        scope=scope,
        power_bonus=power_bonus,
        toughness_bonus=toughness_bonus,
        granted_keywords=granted,
        active_turn_only=m.group("turn_rider") is not None,
    )


def _parse_counter_gated_anthem_line(line: str) -> StaticAbility | None:
    """Return a ``StaticAbility`` for a counter-gated anthem line, or
    ``None`` if the line doesn't match or the granted keyword isn't a
    known evergreen.

    Recognizes the singular-subject shape ``Each creature you control
    with a +1/+1 counter on it has <keyword>.`` (Drix Fatemaker). The
    scope is fixed at ``StaticScope.CREATURES_YOU_CONTROL_WITH_COUNTER``
    — the engine's ``applies_to`` walks every creature the source's
    controller owns and admits only those with at least one +1/+1
    counter, which is exactly the surface filter.

    P/T grants and the ``and has`` combined tail are not supported
    today: every counter-gated print in EoE is keyword-only, and
    pulling the P/T branch in here speculatively would require deciding
    its surface spelling without an example to anchor it.
    """
    m = _COUNTER_GATED_ANTHEM_LINE.match(line.strip())
    if m is None:
        return None
    engine_keyword = _KEYWORD_LINES.get(m.group("keyword").strip().capitalize())
    if engine_keyword is None:
        return None
    return StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL_WITH_COUNTER,
        granted_keywords=frozenset({engine_keyword}),
    )


def _parse_static_ability_line(line: str) -> StaticAbility | None:
    """Return a ``StaticAbility`` for a single static-ability line, or
    ``None`` if no surface form matches.

    Self-scope (``StaticScope.SELF``) shapes are tried first via the
    leading/trailing ``As long as`` grammar; if neither matches, the
    line is then handed to the anthem-scope grammar
    (``_parse_anthem_static_line``) which covers ``Creatures you
    control [get|have] ...`` and ``Other creatures you control
    [get|have] ...`` lines, optionally with a ``During your turn,``
    rider. Finally the counter-gated anthem grammar
    (``_parse_counter_gated_anthem_line``) is tried for the
    ``Each creature you control with a +1/+1 counter on it has
    <keyword>.`` shape.

    The grammar families are mutually exclusive on their subject noun
    phrase (``this creature`` vs. ``[Other ]Creatures you control``
    vs. ``Each creature you control with a +1/+1 counter on it``), so
    the order of fallthrough doesn't matter for correctness — self-
    scope is tried first only because every ``StaticAbility`` produced
    by the parser before the anthem grammar landed was self-scoped,
    and keeping that path first minimizes diff churn for the existing
    test corpus.
    """
    stripped = _strip_static_ability_word_prefix(line.strip())
    m = _STATIC_ABILITY_LINE.match(stripped)
    if m is None:
        m = _STATIC_ABILITY_LINE_TRAILING.match(stripped)
    if m is None:
        anthem = _parse_anthem_static_line(stripped)
        if anthem is not None:
            return anthem
        counter_gated = _parse_counter_gated_anthem_line(stripped)
        if counter_gated is not None:
            return counter_gated
        # Player-scope statics — no creature target, just a flag on
        # the source's controller. ``You have no maximum hand size.``
        # is the only entry today (Steaming Sauna). The produced
        # ``StaticAbility`` carries no granted keywords / no P/T
        # bonus; ``run_cleanup_step`` reads ``grants_no_max_hand_size``
        # directly off the active static abilities of every
        # battlefield permanent under the active player's control.
        # Scope is set to ``SELF`` so the existing creature-only
        # ``applies_to`` walk is a clean no-op for non-creature
        # source permanents (Steaming Sauna is an Enchantment).
        if _NO_MAX_HAND_SIZE_LINE.match(stripped) is not None:
            return StaticAbility(
                scope=StaticScope.SELF,
                grants_no_max_hand_size=True,
            )
        return None
    condition = m.group("condition").strip()
    cond_kwargs = _STATIC_CONDITION_KWARGS.get(condition)
    if cond_kwargs is None:
        return None
    granted: frozenset[str] = frozenset()
    keyword = m.group("keyword")
    if keyword is not None:
        engine_keyword = _KEYWORD_LINES.get(keyword.strip().capitalize())
        if engine_keyword is None:
            return None
        granted = frozenset({engine_keyword})
    return StaticAbility(
        scope=StaticScope.SELF,
        power_bonus=int(m.group("power")),
        toughness_bonus=int(m.group("toughness")),
        granted_keywords=granted,
        **cond_kwargs,
    )
