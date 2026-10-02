"""Parser grammar for the Vintage Roto P5 package: board-state prison
and layers (``docs/ROTO_COVERAGE_PLAN.md`` section 3).

Three entry points, each the last fallback of a shared dispatcher, so
no phrase an older recognizer claims changes meaning:

* :func:`parse_roto_board_effect` -- effect phrases (after every other
  bucket in ``effects._parse_effect``);
* :func:`parse_roto_cost_piece` -- activation-cost atoms (after the
  cube creatures bucket in ``activated._classify_cost_piece``);
* :func:`parse_roto_board_line` -- whole oracle lines a permanent
  builder declined: printing-level statics, triggers whose condition
  the trigger tables don't know, ... (``BoardLine``).

Like the cube buckets, the grammar is switched off for printings that
exist only in the EoE-era dumps (the shared ``creature_rmc_grammar``
switch), so no EoE printing's parse can change. Every recognizer is
parameterized over the varying parts of its printed shape; engine
effects live in ``effects/generic/roto_board.py`` and the board-rule
statics in ``mtg_bot.roto_board_statics``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mtg_bot.effects.base import Effect


def _disabled() -> bool:
    from mtg_bot.cards.parser.creature_rmc_grammar import _DISABLED

    return _DISABLED[0]


@dataclass
class BoardLine:
    """What one recognized oracle line contributes to a printing."""

    fields: dict = field(default_factory=dict)
    keywords: tuple[str, ...] = ()
    triggers: tuple = ()
    activated: tuple = ()
    statics: tuple = ()


# Printing fields several lines of one card may each contribute to
# (concatenated rather than overwritten).
_ACCUMULATED_FIELDS = frozenset({"board_rules", "enters_with_named_counters"})


def merge_board_fields(into: dict, fields: dict) -> None:
    """Fold one line's printing fields into the builder's accumulator."""
    for name, value in fields.items():
        if name in _ACCUMULATED_FIELDS:
            into[name] = tuple(into.get(name, ())) + tuple(value)
        else:
            into[name] = value


_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _n(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


# ---------------------------------------------------------------------------
# Noun phrases
# ---------------------------------------------------------------------------

_NON_SUBTYPE = re.compile(r"\bnon-(?P<sub>[A-Z][a-z]+) ")
_PT_MODIFIER = re.compile(r"^(?P<p>\d+)/(?P<t>\d+) (?P<rest>creatures?)$")


def permanent_phrase(np: str, *, plural: bool = False):
    """The compositional permanent grammar
    (``target_phrases.parse_permanent_phrase``) plus the modifiers this
    package's cards print and the base grammar lacks: ``legendary``
    (Minamo), ``non-<Subtype>`` (Emerald Charm's "non-Aura
    enchantment"), a ``P/T`` creature (Pendelhaven's "1/1 creature")
    and the plural controller ``your opponents control`` (Cryptic
    Command). ``None`` when any word is outside the grammar."""
    from mtg_bot.cards.parser.target_phrases import parse_permanent_phrase
    from mtg_bot.effects.generic.roto_board import (
        IsLegendaryPermanent,
        LacksSubtype,
    )
    from mtg_bot.effects.object_predicates import (
        ControlledByOpponent,
        HasPowerToughness,
    )

    np = np.strip()
    if ", " in np and " or " not in np and " and " not in np:
        # "nonland, nontoken permanents": a comma-joined modifier list
        # (conjunctive), not a list of alternatives.
        np = np.replace(", ", " ")
    quals = []
    if np.endswith(" your opponents control"):
        np = np[: -len(" your opponents control")]
        quals.append(ControlledByOpponent())
    for m in list(_NON_SUBTYPE.finditer(np)):
        quals.append(LacksSubtype(m.group("sub")))
    np = _NON_SUBTYPE.sub("", np)
    if np.startswith("legendary "):
        np = np[len("legendary "):]
        quals.append(IsLegendaryPermanent())
    m = _PT_MODIFIER.match(np)
    if m is not None:
        quals.append(HasPowerToughness(int(m.group("p")), int(m.group("t"))))
        np = m.group("rest")
    base = parse_permanent_phrase(np, plural=plural)
    if base is None:
        return None
    for q in quals:
        base = base & q
    return base


# ---------------------------------------------------------------------------
# Effect phrases
# ---------------------------------------------------------------------------

# "deals damage to each player equal to [twice] the number of <np> that
# player controls" (Price of Progress).
_DAMAGE_EACH_PLAYER_PER_CONTROLLED = re.compile(
    r"^deals damage to each player equal to (?P<twice>twice )?the number of "
    r"(?P<np>.+?) that player controls$"
)
# "tap all <plural np>" (Cryptic Command).
_TAP_ALL = re.compile(r"^tap all (?P<np>.+)$")
# "destroy each <np> with mana value equal to the number of <kind>
# counters on this <permanent>" (Engineered Explosives, The Filigree
# Sylex -- whose self-name the clause grammar rewrites to "this
# creature").
_DESTROY_EACH_MV_EQUAL_COUNTERS = re.compile(
    r"^destroy each (?P<np>.+?) with mana value equal to the number of "
    r"(?P<kind>[a-z]+) counters on this "
    r"(?:artifact|creature|enchantment|land|permanent)$"
)
# "destroy each <a>, <b>, and <c> with mana value X or less" (Pernicious
# Deed): in the "each" frame an "and" list is a union.
_DESTROY_EACH_AND_LIST = re.compile(
    r"^(?P<verb>destroy|exile) each (?P<np>[a-z]+(?:, [a-z]+)*,? and [a-z]+)"
    r"(?P<rest> with mana value X or less)?$"
)


# "that player sacrifices a <np> of their choice for each <kind> counter
# on this <permanent>" (Smokestack) / "that player taps an untapped <np>
# they control for each <kind> counter on this <permanent>" (Tangle
# Wire) -- bodies of "At the beginning of each player's upkeep".
_EVENT_PLAYER_PER_COUNTER = re.compile(
    r"^that player (?:(?P<sac>sacrifices) an? (?P<sac_np>.+?) of their choice"
    r"|(?P<tap>taps) an untapped (?P<tap_np>.+?) they control) for each "
    r"(?P<kind>[a-z]+) counter on this "
    r"(?:artifact|creature|enchantment|land|permanent)$"
)
# "destroy this creature unless you pay <cost>" (the Tabernacle's
# granted upkeep ability).
_DESTROY_SELF_UNLESS_PAY = re.compile(
    r"^destroy this creature unless you pay (?P<cost>(?:\{[^}]+\})+)$"
)


# "[un]tap [<count>] target <np>" over the extended permanent grammar
# (Emerald Charm, Deceiver Exarch, Opposition, Earthcraft, Minamo).
_TAP_UNTAP_TARGET = re.compile(r"^(?P<verb>tap|untap) (?P<rest>.*target .+)$")
# "equipped creature gets +P/+T until end of turn" (Umezawa's Jitte).
_EQUIPPED_GETS_UEOT = re.compile(
    r"^equipped creature gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+) until end of "
    r"turn$"
)
# "target <np> gets +P/+T until end of turn" for noun phrases the base
# pump grammar doesn't know (Pendelhaven's "target 1/1 creature").
_TARGET_GETS_UEOT = re.compile(
    r"^target (?P<np>.+?) gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+) until end of "
    r"turn$"
)


# "target <np> loses <keyword> until end of turn" (Emerald Charm).
_LOSES_KEYWORD_UEOT = re.compile(
    r"^target (?P<np>.+?) loses (?P<kw>[a-z]+(?: [a-z]+)?) until end of turn$"
)
# "<plural np> you control gain <keywords> until end of turn" for noun
# phrases the base grammar doesn't cover (Boros Charm's "permanents").
_EACH_GAINS_UEOT = re.compile(
    r"^(?P<np>[a-z]+) you control gain (?P<kws>[a-z ,]+?) until end of turn$"
)
# "deals N damage to target <player-or-permanent list>" (Boros Charm's
# "target player or planeswalker").
_DAMAGE_TO_TARGET_LIST = re.compile(
    r"^deals (?P<n>\d+) damage to target (?P<np>.+)$"
)
# "deals N damage to each of one or two targets" (Prismari Charm).
_DAMAGE_EACH_OF_TARGETS = re.compile(
    r"^deals (?P<n>\d+) damage to each of (?P<count>one or two|up to "
    r"(?:two|three)) targets$"
)
# "destroy target <np>" over the extended permanent grammar (Emerald
# Charm's "non-Aura enchantment").
_DESTROY_TARGET = re.compile(r"^destroy target (?P<np>.+)$")


# "return a <permanent> you control to its owner's hand" -- not
# targeted (Shrieking Drake).
_RETURN_ONE_YOU_CONTROL = re.compile(
    r"^return an? (?P<np>[a-z]+) you control to its owner's hand$"
)
# "<plural np> you control gain <keywords> and get +X/+X until end of
# turn, where X is the number of <plural np> you control" (Craterhoof).
_EACH_GAINS_AND_GETS_X = re.compile(
    r"^(?P<np>[a-z]+) you control gain (?P<kws>[a-z ,]+?) and get \+X/\+X "
    r"until end of turn, where X is the number of (?P<count>[a-z]+) you "
    r"control$"
)
# "<pump>. If you cast this spell during your main phase, that
# creature gets +P/+T until end of turn instead" (Might of Old Krosa).
_MAIN_PHASE_INSTEAD = re.compile(
    r"^(?P<base>target (?P<np>.+?) gets \+\d+/\+\d+ until end of turn)\. If "
    r"you cast this spell during your main phase, that creature gets "
    r"(?P<pt>\+\d+/\+\d+) until end of turn instead$"
)
# "you may put a creature card with mana value equal to the number of
# <kind> counters on this <permanent> from your hand onto the battlefield"
# (Aether Vial).
_PUT_MV_EQUAL_COUNTERS_FROM_HAND = re.compile(
    r"^you may put a creature card with mana value equal to the number of "
    r"(?P<kind>[a-z]+) counters on this (?:artifact|creature|enchantment|"
    r"land|permanent) from your hand onto the battlefield$"
)
# "[you may ]destroy [up to N ]target <np>. For each permanent put into
# a graveyard this way, its controller creates <token>" (Terastodon).
_DESTROY_THEN_CONTROLLER_TOKENS = re.compile(
    r"^(?P<may>you may )?destroy (?:up to (?P<n>one|two|three|four) )?target "
    r"(?P<np>.+?)\. For each permanent put into a graveyard this way, its "
    r"controller creates (?P<tok>.+)$"
)
_SELF_NOUN_LEAVES = (
    r"until this (?:enchantment|artifact|creature|permanent) leaves the "
    r"battlefield$"
)
# "exile [up to one ][other ]target <np> until this <permanent> leaves
# the battlefield" over the extended grammar (Aang's Iceberg).
_EXILE_TARGET_UNTIL_LEAVES = re.compile(
    r"^exile (?P<upto>up to one )?(?P<other>other )?target (?P<np>.+?) "
    + _SELF_NOUN_LEAVES
)
# "exile each <np> until this <permanent> leaves the battlefield"
# (Temporary Lockdown).
_EXILE_EACH_UNTIL_LEAVES = re.compile(
    r"^exile each (?P<np>.+?) " + _SELF_NOUN_LEAVES
)
# Turnabout: "choose <t1>, <t2>, or <t3>. Tap all untapped permanents of
# the chosen type target player controls, or untap all tapped permanents
# of that type that player controls".
_TAP_OR_UNTAP_CHOSEN_TYPE = re.compile(
    r"^choose (?P<types>[a-z]+, [a-z]+, or [a-z]+)\. Tap all untapped "
    r"permanents of the chosen type target player controls, or untap all "
    r"tapped permanents of that type that player controls$"
)


# "sacrifice this creature unless you discard a card[. When you discard
# a card this way, <destroy|exile> target <np> with mana value less than
# or equal to the mana value of the discarded card]" (Argentum Masticore).
_SAC_UNLESS_DISCARD = re.compile(
    r"^sacrifice this (?:creature|artifact|permanent) unless you discard a "
    r"card(?:\. When you discard a card this way, (?P<verb>destroy|exile) "
    r"target (?P<np>.+?) with mana value less than or equal to the mana "
    r"value of the discarded card)?$"
)
# "return any number of target <np> you control to their owners' hands.
# Draw a card for each card returned to your hand this way" (Paradoxical
# Outcome).
_RETURN_ANY_NUMBER_DRAW = re.compile(
    r"^return any number of target (?P<np>.+?) you control to their owners' "
    r"hands\. Draw a card for each card returned to your hand this way$"
)


def _keyword_list(text: str):
    from mtg_bot.cards.parser.keywords import _parse_keyword_line

    words = [w.strip() for w in re.split(r", and |, | and ", text) if w.strip()]
    out = set()
    for w in words:
        kws = _parse_keyword_line(w.capitalize())
        if not kws or len(kws) != 1:
            return None
        out.add(kws[0])
    return frozenset(out) if out else None


def _player_or_permanent_filter(np: str):
    """"player or planeswalker" / "opponent or creature" -- a target
    list mixing players with the permanent grammar."""
    from mtg_bot.effects.object_predicates import ControlledByOpponent, IsPlayer

    arms = []
    has_player = False
    for item in np.split(" or "):
        item = item.strip()
        if item == "player":
            arms.append(IsPlayer())
            has_player = True
        elif item == "opponent":
            arms.append(IsPlayer() & ControlledByOpponent())
            has_player = True
        else:
            f = permanent_phrase(item)
            if f is None:
                return None
            arms.append(f)
    if not has_player:
        return None
    out = arms[0]
    for a in arms[1:]:
        out = out | a
    return out


def _target_slot(rest: str):
    from mtg_bot.cards.parser.target_phrases import parse_target_count
    from mtg_bot.effects.targets import TargetSpec

    counted = parse_target_count(rest)
    if counted is None:
        return None
    lo, hi, np = counted
    if hi == "X":
        return None
    f = permanent_phrase(np)
    if f is None:
        return None
    return TargetSpec(f, count_min=lo, count_max=hi)


def parse_roto_board_effect(phrase: str) -> Effect | None:
    """Effect phrases of the P5 package (normalized: lower-cased first
    letter, no trailing period, source subject stripped)."""
    if _disabled():
        return None
    from mtg_bot.effects.generic import roto_board as rb

    m = _DAMAGE_EACH_PLAYER_PER_CONTROLLED.match(phrase)
    if m is not None:
        f = permanent_phrase(m.group("np"), plural=True)
        if f is None:
            return None
        return rb.DamageEachPlayerPerControlled(
            per_filter=f, multiplier=2 if m.group("twice") else 1,
            label=m.group("np"),
        )
    m = _EVENT_PLAYER_PER_COUNTER.match(phrase)
    if m is not None:
        action = "sacrifice" if m.group("sac") else "tap"
        np = m.group("sac_np") or m.group("tap_np")
        f = permanent_phrase(np)
        if f is None:
            return None
        return rb.EventPlayerActsPerSourceCounter(
            action=action, kind=m.group("kind"), permanent_filter=f, label=np,
        )
    m = _DESTROY_SELF_UNLESS_PAY.match(phrase)
    if m is not None:
        from mtg_bot.cards.base import parse_mana_cost

        try:
            parse_mana_cost(m.group("cost"))
        except ValueError:
            return None
        return rb.DestroySourceUnlessPay(cost=m.group("cost"))
    m = _TAP_UNTAP_TARGET.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.tap import Tap, Untap

        slot = _target_slot(m.group("rest"))
        if slot is None:
            return None
        cls = Tap if m.group("verb") == "tap" else Untap
        return cls(targets=(slot,))
    m = _SAC_UNLESS_DISCARD.match(phrase)
    if m is not None:
        if m.group("verb") is None:
            return rb.SacrificeSourceUnlessDiscard()
        f = permanent_phrase(m.group("np"))
        if f is None:
            return None
        return rb.SacrificeSourceUnlessDiscard(
            reflexive_action=m.group("verb"), reflexive_filter=f,
        )
    m = _RETURN_ANY_NUMBER_DRAW.match(phrase)
    if m is not None:
        from mtg_bot.effects.object_predicates import ControlledByYou

        f = permanent_phrase(m.group("np"), plural=True)
        if f is None:
            return None
        return rb.ReturnAnyNumberDrawPerOwned(target_filter=f & ControlledByYou())
    m = _RETURN_ONE_YOU_CONTROL.match(phrase)
    if m is not None:
        f = permanent_phrase(m.group("np"))
        if f is None:
            return None
        return rb.ReturnPermanentYouControlToHand(
            permanent_filter=f, label=m.group("np"),
        )
    m = _EACH_GAINS_AND_GETS_X.match(phrase)
    if m is not None:
        f = permanent_phrase(m.group("np"), plural=True)
        count = permanent_phrase(m.group("count"), plural=True)
        kws = _keyword_list(m.group("kws"))
        if f is None or count is None or kws is None:
            return None
        return rb.PumpEachYouControlByCountUEOT(
            permanent_filter=f, count_filter=count, keywords=kws,
            label=f"{m.group('np')} you control",
        )
    m = _MAIN_PHASE_INSTEAD.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.effects import _parse_effect

        base = _parse_effect(m.group("base"))
        stronger = _parse_effect(
            f"target {m.group('np')} gets {m.group('pt')} until end of turn"
        )
        if base is None or stronger is None or type(base) is not type(stronger):
            return None
        return rb.IfResolvingInYourMainPhase(main_phase=stronger, otherwise=base)
    m = _PUT_MV_EQUAL_COUNTERS_FROM_HAND.match(phrase)
    if m is not None:
        return rb.PutCreatureWithMVEqualToCountersFromHand(kind=m.group("kind"))
    m = _DESTROY_THEN_CONTROLLER_TOKENS.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.effects import _parse_effect
        from mtg_bot.effects.combinators import MayDo
        from mtg_bot.effects.generic.tokens import CreateToken

        f = permanent_phrase(m.group("np"), plural=m.group("n") is not None)
        token = _parse_effect(f"create {m.group('tok')}")
        if f is None or not isinstance(token, CreateToken):
            return None
        n = _NUMBER_WORDS[m.group("n")] if m.group("n") else 1
        eff = rb.DestroyTargetsControllersGetTokens(
            target_filter=f, token_printing=token.token_printing,
            count_min=0 if m.group("n") else 1, count_max=n,
            tokens_each=token.count,
        )
        return MayDo(inner=eff) if m.group("may") else eff
    m = _EXILE_TARGET_UNTIL_LEAVES.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.enchantment_mechanics import (
            ExileTargetUntilSourceLeaves,
        )
        from mtg_bot.effects.object_predicates import IsSource
        from mtg_bot.effects.targets import TargetSpec

        f = permanent_phrase(m.group("np"))
        if f is None:
            return None
        if m.group("other"):
            f = f & ~IsSource()
        return ExileTargetUntilSourceLeaves(targets=(TargetSpec(
            f, count_min=0 if m.group("upto") else 1, count_max=1,
        ),))
    m = _EXILE_EACH_UNTIL_LEAVES.match(phrase)
    if m is not None:
        f = permanent_phrase(m.group("np"))
        if f is None:
            return None
        return rb.ExileEachUntilSourceLeaves(
            permanent_filter=f, label=m.group("np"),
        )
    m = _TAP_OR_UNTAP_CHOSEN_TYPE.match(phrase)
    if m is not None:
        types = tuple(
            t.capitalize() for t in re.split(r", or |, ", m.group("types"))
        )
        if not all(t in ("Artifact", "Creature", "Land", "Enchantment") for t in types):
            return None
        return rb.TapOrUntapAllOfChosenType(types=types)
    m = _LOSES_KEYWORD_UEOT.match(phrase)
    if m is not None:
        from mtg_bot.effects.targets import TargetSpec

        f = permanent_phrase(m.group("np"))
        kws = _keyword_list(m.group("kw"))
        if f is None or kws is None or len(kws) != 1:
            return None
        return rb.LoseKeywordUEOT(keyword=next(iter(kws)), targets=(TargetSpec(f),))
    m = _EACH_GAINS_UEOT.match(phrase)
    if m is not None:
        from mtg_bot.effects.object_predicates import ControlledByYou

        f = permanent_phrase(m.group("np"), plural=True)
        kws = _keyword_list(m.group("kws"))
        if f is None or kws is None:
            return None
        return rb.GrantKeywordsToEachUEOT(
            permanent_filter=f & ControlledByYou(), keywords=kws,
            label=f"{m.group('np')} you control",
        )
    m = _DAMAGE_EACH_OF_TARGETS.match(phrase)
    if m is not None:
        from mtg_bot.effects.targets import TargetSpec, any_target_filter

        count = m.group("count")
        lo, hi = (1, 2) if count == "one or two" else (
            0, _NUMBER_WORDS[count.split()[-1]],
        )
        return rb.DealDamageToEachTarget(
            amount=int(m.group("n")),
            targets=(TargetSpec(any_target_filter(), count_min=lo, count_max=hi),),
        )
    m = _DAMAGE_TO_TARGET_LIST.match(phrase)
    if m is not None and " or " in m.group("np"):
        from mtg_bot.effects.generic.damage import DealDamage
        from mtg_bot.effects.targets import TargetSpec

        f = _player_or_permanent_filter(m.group("np"))
        if f is None:
            return None
        return DealDamage(amount=int(m.group("n")), targets=(TargetSpec(f),))
    m = _DESTROY_TARGET.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.targeted_removal import (
            RemoveTargetPermanents,
        )

        f = permanent_phrase(m.group("np"))
        if f is None:
            return None
        return RemoveTargetPermanents(action="destroy", target_filter=f)
    m = _EQUIPPED_GETS_UEOT.match(phrase)
    if m is not None:
        return rb.PumpEquippedCreatureUEOT(
            power_bonus=int(m.group("p")), toughness_bonus=int(m.group("t")),
        )
    m = _TARGET_GETS_UEOT.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.pump import Pump
        from mtg_bot.effects.targets import TargetSpec

        f = permanent_phrase(m.group("np"))
        if f is None:
            return None
        return Pump(
            power_bonus=int(m.group("p")), toughness_bonus=int(m.group("t")),
            targets=(TargetSpec(f),),
        )
    m = _TAP_ALL.match(phrase)
    if m is not None:
        f = permanent_phrase(m.group("np"), plural=True)
        if f is None:
            return None
        return rb.TapAllMatching(permanent_filter=f, label=m.group("np"))
    m = _DESTROY_EACH_MV_EQUAL_COUNTERS.match(phrase)
    if m is not None:
        f = permanent_phrase(m.group("np"))
        if f is None:
            return None
        from mtg_bot.effects.generic.targeted_removal import RemoveAllMatching

        return RemoveAllMatching(
            permanent_filter=f & rb.HasManaValueEqualToSourceCounters(
                m.group("kind"),
            ),
            action="destroy",
            label=(
                f"each {m.group('np')} with mana value equal to the number "
                f"of {m.group('kind')} counters on this permanent"
            ),
        )
    m = _DESTROY_EACH_AND_LIST.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.removal_phrases import parse_destroy_all

        union = m.group("np").replace(", and ", ", or ").replace(" and ", " or ")
        return parse_destroy_all(
            f"{m.group('verb')} each {union}{m.group('rest') or ''}"
        )
    return None


# ---------------------------------------------------------------------------
# Trigger conditions
# ---------------------------------------------------------------------------


def parse_roto_trigger_phrase(phrase: str):
    """``(Event, Predicate)`` for the P5 package's trigger conditions:
    "equipped creature deals combat damage" (any recipient, once per
    damage step -- Umezawa's Jitte) and "this creature becomes blocked"
    (Ichorclaw Myr)."""
    if _disabled():
        return None
    from mtg_bot.effects.predicates import Event, IsHost, IsSelf

    if phrase == "equipped creature deals combat damage":
        return (Event.DEALS_COMBAT_DAMAGE_ANY, IsHost(subject="source"))
    if phrase == "this creature becomes blocked":
        return (Event.BECOMES_BLOCKED, IsSelf(subject="attacker"))
    return None


# ---------------------------------------------------------------------------
# Cost atoms
# ---------------------------------------------------------------------------

_SACRIFICE_SELF_PIECES = frozenset({"Sacrifice this enchantment"})
# "Remove ten oil counters from among permanents you control" (The
# Filigree Sylex).
_REMOVE_COUNTERS_FROM_AMONG = re.compile(
    r"^Remove (?P<n>\w+) (?P<kind>[a-z]+) counters? from among permanents "
    r"you control$"
)


def parse_roto_cost_piece(piece: str):
    """Activation-cost atoms of the P5 package -> ``activated._CostPiece``
    (``None`` when the piece isn't one)."""
    if _disabled():
        return None
    from mtg_bot.cards.parser.activated import _CostPiece
    from mtg_bot.effects.generic import roto_board as rb
    from mtg_bot.effects.generic.cube_creatures_rmc import SacrificePermanentsCost
    from mtg_bot.effects.value_predicates import IsPermanent

    m = _REMOVE_COUNTERS_FROM_AMONG.match(piece)
    if m is not None and (m.group("n").isdigit() or m.group("n") in _NUMBER_WORDS):
        return _CostPiece(kind="extra", atom=rb.RemoveCountersFromAmongPermanentsCost(
            kind=m.group("kind"), count=_n(m.group("n")),
        ))
    if piece == "Put a -1/-1 counter on this creature":
        # Devoted Druid.
        return _CostPiece(kind="extra", atom=rb.PutMinusOneCounterOnSelfCost())
    if piece in _SACRIFICE_SELF_PIECES:
        # "Sacrifice this enchantment" (Seal of Cleansing, Pernicious
        # Deed): the enchantment self-reference of ``sacrifice_self``.
        return _CostPiece(kind="sacrifice_self")
    if piece == "Sacrifice a permanent":
        # Claws of Gix: any permanent you control, the source included.
        return _CostPiece(kind="extra", atom=SacrificePermanentsCost(
            permanent_filter=IsPermanent(), label="a permanent",
        ))
    return None


# ---------------------------------------------------------------------------
# Whole lines
# ---------------------------------------------------------------------------


# "<costs>, <cost atom> and sacrifice <this>: <effect>" -- the last two
# cost atoms joined by "and" instead of a comma (The Filigree Sylex's
# "Remove ten oil counters from among permanents you control and
# sacrifice The Filigree Sylex").
_AND_SACRIFICE_SELF_COST = re.compile(
    r"^(?P<costs>[^:]+?) and sacrifice this (?P<noun>creature|artifact|"
    r"enchantment|land): (?P<effect>.+)$"
)


def _activated_with_and_joined_sacrifice(line: str) -> BoardLine | None:
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line

    m = _AND_SACRIFICE_SELF_COST.match(line)
    if m is None:
        return None
    rewritten = (
        f"{m.group('costs')}, Sacrifice this {m.group('noun')}: "
        f"{m.group('effect')}"
    )
    ability = _parse_activated_ability_line(rewritten)
    if ability is None or not ability.cost.sacrifice_self:
        return None
    return BoardLine(activated=(ability,))


# "Creatures [<condition>] can't attack." / "This creature can't block."
# (Moat, Ensnaring Bridge, Carrion Feeder).
_CANT_ATTACK_OR_BLOCK = re.compile(
    r"^(?P<who>Creatures|[Tt]his creature)(?: (?P<cond>.+?))? "
    r"can't (?P<verb>attack|block)\.$"
)
_WITHOUT_KEYWORD = re.compile(r"^without (?P<kw>[a-z]+(?: [a-z]+)?)$")
_POWER_GREATER_THAN_HAND = (
    "with power greater than the number of cards in your hand"
)


def _combat_condition(text: str | None):
    from mtg_bot import roto_board_statics as rs

    if text is None:
        return None
    m = _WITHOUT_KEYWORD.match(text)
    if m is not None:
        from mtg_bot.cards.parser.keywords import _parse_keyword_line

        kws = _parse_keyword_line(m.group("kw").capitalize())
        if not kws or len(kws) != 1:
            return False
        return rs.WithoutKeyword(kws[0])
    if text == _POWER_GREATER_THAN_HAND:
        return rs.PowerGreaterThanControllersHandSize()
    return False


def _cant_attack_or_block(line: str) -> BoardLine | None:
    from mtg_bot import roto_board_statics as rs

    m = _CANT_ATTACK_OR_BLOCK.match(line)
    if m is None:
        return None
    self_only = m.group("who") != "Creatures"
    cond = _combat_condition(m.group("cond"))
    if cond is False or (self_only and cond is not None):
        return None
    rule_cls = rs.CantAttack if m.group("verb") == "attack" else rs.CantBlock
    return BoardLine(fields={
        "board_rules": (rule_cls(condition=cond, self_only=self_only),),
    })


_FADING = re.compile(r"^Fading (?P<n>\d+)$")


def _fading(line: str) -> BoardLine | None:
    """``Fading N`` on a non-enchantment permanent (CR 702.32a: enters
    with N fade counters; at the beginning of your upkeep, remove one,
    or sacrifice it if you can't) -- Tangle Wire. The cube enchantment
    builder has its own recognizer for enchantments."""
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.enchantment_mechanics import (
        RemoveNamedCounterFromSelfOrSacrifice,
    )
    from mtg_bot.effects.predicates import YOU, Controlled, Event

    m = _FADING.match(line)
    if m is None:
        return None
    return BoardLine(
        fields={"enters_with_named_counters": (("fade", int(m.group("n"))),)},
        triggers=(TriggeredAbility(
            event=Event.BEGINNING_OF_UPKEEP,
            predicate=Controlled(YOU),
            effect=RemoveNamedCounterFromSelfOrSacrifice(kind="fade"),
        ),),
    )


# 'All creatures have "<triggered ability>".' (The Tabernacle at
# Pendrell Vale).
_ALL_CREATURES_HAVE_QUOTED = re.compile(
    r'^All creatures have "(?P<ability>.+\.)"$'
)


def _all_creatures_have_trigger(line: str) -> BoardLine | None:
    from mtg_bot import roto_board_statics as rs
    from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line
    from mtg_bot.effects.base import TriggeredAbility

    m = _ALL_CREATURES_HAVE_QUOTED.match(line)
    if m is None:
        return None
    ability = _parse_triggered_ability_line(m.group("ability"))
    if not isinstance(ability, TriggeredAbility):
        return None
    return BoardLine(fields={
        "board_rules": (rs.GrantsTriggerToCreatures(ability=ability),),
    })


# "<Permanents> don't untap during their controllers' untap steps."
# (Back to Basics).
_DONT_UNTAP = re.compile(
    r"^(?P<np>[A-Z][a-z]+(?: [a-z]+)*) don't untap during their "
    r"controllers' untap steps\.$"
)
# "[As long as this <permanent> is untapped, ]players can't untap more
# than <n> <permanents> during their untap steps." (Winter Orb).
_UNTAP_LIMIT = re.compile(
    r"^(?:As long as this (?P<self>artifact|creature|enchantment|land|"
    r"permanent) is untapped, )?[Pp]layers can't untap more than "
    r"(?P<n>one|two|three|\d+) (?P<np>[a-z]+(?: [a-z]+)*) during their "
    r"untap steps\.$"
)


def _untap_rules(line: str) -> BoardLine | None:
    from mtg_bot import roto_board_statics as rs

    m = _DONT_UNTAP.match(line)
    if m is not None:
        np = m.group("np").lower()
        f = permanent_phrase(np, plural=True)
        if f is None:
            return None
        return BoardLine(fields={
            "board_rules": (rs.DoesntUntap(permanent_filter=f, label=np),),
        })
    m = _UNTAP_LIMIT.match(line)
    if m is not None:
        n = _n(m.group("n"))
        np = m.group("np")
        f = permanent_phrase(np, plural=n != 1)
        if f is None:
            return None
        return BoardLine(fields={"board_rules": (rs.UntapLimit(
            permanent_filter=f, limit=n,
            while_source_untapped=m.group("self") is not None,
            label=np,
        ),)})
    return None


# "Each land is a <basic land type> in addition to its other land types."
# (Urborg, Tomb of Yawgmoth; Yavimaya, Cradle of Growth) -- the engine's
# layer-4 ``grants_basic_land_type_to_all_lands`` synthesis (CR 613.7
# dependency on Blood Moon included).
_EACH_LAND_IS_TYPE = re.compile(
    r"^Each land is an? (?P<type>Plains|Island|Swamp|Mountain|Forest) in "
    r"addition to its other land types\.$"
)


def _each_land_is_type(line: str) -> BoardLine | None:
    m = _EACH_LAND_IS_TYPE.match(line)
    if m is None:
        return None
    return BoardLine(fields={
        "grants_basic_land_type_to_all_lands": m.group("type"),
    })


def _nonbasic_lands_are_mountains(line: str) -> BoardLine | None:
    """"Nonbasic lands are Mountains." on a noncreature permanent (Blood
    Moon) -- the printing flag Magus of the Moon's creature grammar
    already sets (``printing_keywords``)."""
    from mtg_bot.cards.parser.printing_keywords import (
        _parse_nonbasic_lands_are_mountains_line,
    )

    if not _parse_nonbasic_lands_are_mountains_line(line):
        return None
    return BoardLine(fields={"nonbasic_lands_are_mountains": True})


# "Whenever equipped creature <condition>, it <body>." -- "it" is the
# equipped creature, not the Equipment (Hawkeye's Bow). These conditions
# stay out of the shared trigger tables, whose effect normalizer would
# read "it" as the trigger's source.
_EQUIPPED_IT_TRIGGER = re.compile(
    r"^Whenever equipped creature (?P<cond>becomes tapped|attacks), it "
    r"(?P<body>.+)\.$"
)
_HOST_DEALS_DAMAGE_EACH_OPPONENT = re.compile(
    r"^deals (?P<n>\d+) damage to each opponent$"
)


def _equipped_it_trigger(line: str) -> BoardLine | None:
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic import roto_board as rb
    from mtg_bot.effects.predicates import Event, IsHost

    m = _EQUIPPED_IT_TRIGGER.match(line)
    if m is None:
        return None
    event, slot = {
        "becomes tapped": (Event.BECOMES_TAPPED, "obj"),
        "attacks": (Event.ATTACKS, "attacker"),
    }[m.group("cond")]
    body = _HOST_DEALS_DAMAGE_EACH_OPPONENT.match(m.group("body"))
    if body is None:
        return None
    return BoardLine(triggers=(TriggeredAbility(
        event=event, predicate=IsHost(subject=slot),
        effect=rb.EventSubjectDealsDamageToEachOpponent(
            amount=int(body.group("n")), subject_slot=slot,
        ),
    ),))


# "This creature gets +P/+T as long as there are N or more <type> cards
# in your graveyard." (Elvish Reclaimer) / "This creature gets +P/+T for
# each <type> card in your graveyard." (Knight of the Reliquary).
_SELF_GETS_PER_GRAVEYARD = re.compile(
    r"^[Tt]his creature gets \+(?P<p>\d+)/\+(?P<t>\d+) (?:as long as there "
    r"are (?P<n>\w+) or more (?P<desc>[a-z]+) cards in your graveyard|for "
    r"each (?P<each>[a-z]+) card in your graveyard)\.$"
)
# "Each other creature you control that's a <T1>, <T2>, or <T3> gets
# +P/+T and has <keyword>." (Kaheera, the Orphanguard).
_OTHER_SUBTYPE_LIST_ANTHEM = re.compile(
    r"^Each other creature you control that's an? (?P<subs>[A-Z][a-z]+"
    r"(?:, [A-Z][a-z]+)*,? or [A-Z][a-z]+) gets \+(?P<p>\d+)/\+(?P<t>\d+)"
    r"(?: and has (?P<kw>[a-z ]+))?\.$"
)


def _graveyard_pt_static(line: str) -> BoardLine | None:
    from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor
    from mtg_bot.effects.base import StaticAbility, StaticScope
    from mtg_bot.effects.generic import roto_board as rb
    from mtg_bot.effects.modifiers import ContinuousModifier, PowerToughnessBonus

    m = _SELF_GETS_PER_GRAVEYARD.match(line)
    if m is None:
        return None
    desc = m.group("desc") or m.group("each")
    card_filter = parse_card_descriptor(f"a {desc} card")
    if card_filter is None:
        return None
    p, t = int(m.group("p")), int(m.group("t"))
    if m.group("each"):
        return BoardLine(statics=(StaticAbility(
            scope=StaticScope.SELF, power_bonus=p, toughness_bonus=t,
            bonus_per_condition_count=True,
            condition=rb.CardsInYourGraveyard(card_filter=card_filter),
        ),))
    n = m.group("n")
    if not (n.isdigit() or n in _NUMBER_WORDS):
        return None
    return BoardLine(statics=(StaticAbility(
        scope=StaticScope.SELF,
        condition=rb.CardsInYourGraveyard(
            card_filter=card_filter, at_least=_n(n),
        ),
        continuous_effect=ContinuousModifier(
            layer=7, payload=PowerToughnessBonus(power_bonus=p, toughness_bonus=t),
        ),
    ),))


def _other_subtype_list_anthem(line: str) -> BoardLine | None:
    from mtg_bot.effects.base import StaticAbility, StaticScope
    from mtg_bot.effects.modifiers import (
        ContinuousModifier,
        GrantKeyword,
        PowerToughnessBonus,
    )
    from mtg_bot.effects.object_predicates import HasSubtype

    m = _OTHER_SUBTYPE_LIST_ANTHEM.match(line)
    if m is None:
        return None
    subs = [s for s in re.split(r",? or |, ", m.group("subs")) if s]
    subject = HasSubtype(subs[0])
    for sub in subs[1:]:
        subject = subject | HasSubtype(sub)
    statics = [StaticAbility(
        scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
        continuous_effect=ContinuousModifier(
            layer=7,
            payload=PowerToughnessBonus(
                power_bonus=int(m.group("p")), toughness_bonus=int(m.group("t")),
            ),
            subject_filter=subject,
        ),
    )]
    if m.group("kw"):
        kws = _keyword_list(m.group("kw"))
        if kws is None:
            return None
        for kw in sorted(kws):
            statics.append(StaticAbility(
                scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
                continuous_effect=ContinuousModifier(
                    layer=6, payload=GrantKeyword(kw), subject_filter=subject,
                ),
            ))
    return BoardLine(statics=tuple(statics))


_LINE_RECOGNIZERS = (
    _activated_with_and_joined_sacrifice,
    _graveyard_pt_static,
    _other_subtype_list_anthem,
    _equipped_it_trigger,
    _each_land_is_type,
    _nonbasic_lands_are_mountains,
    _cant_attack_or_block,
    _fading,
    _all_creatures_have_trigger,
    _untap_rules,
)


def parse_roto_board_line(line: str, card: dict) -> BoardLine | None:
    """A whole oracle line of a P5 permanent the builder's grammar
    declined (reminder text stripped)."""
    if _disabled():
        return None
    from mtg_bot.cards.parser.triggers import _substitute_self_name

    line = _substitute_self_name(line.strip(), card.get("name", ""))
    for recognizer in _LINE_RECOGNIZERS:
        parsed = recognizer(line)
        if parsed is not None:
            return parsed
    return None


def parse_roto_board_line_into(
    line: str, card: dict, fields: dict,
) -> BoardLine | None:
    """:func:`parse_roto_board_line`, folding the line's printing fields
    into the builder's ``fields`` accumulator (so several lines may each
    add board rules); the returned line carries no fields of its own."""
    board = parse_roto_board_line(line, card)
    if board is None:
        return None
    merge_board_fields(fields, board.fields)
    return BoardLine(
        keywords=board.keywords, triggers=board.triggers,
        activated=board.activated, statics=board.statics,
    )


# "<cost>: Choose one —" followed by "• <mode>" lines -- a modal
# activated ability (Umezawa's Jitte).
_MODAL_ACTIVATION_HEADER = re.compile(r"^(?P<cost>[^:]+): Choose one —$")
# "Equipped creature gets +P/+T and has <keywords> and ward {N}." -- the
# ward rider of a granted-keyword list (Lavaspur Boots).
_EQUIPPED_WARD_RIDER = re.compile(
    r"^(?P<head>Equipped creature (?:gets [+-]\d+/[+-]\d+ and )?has .+?),? "
    r"and ward (?P<cost>(?:\{[^}]+\})+)\.$"
)


def _modal_activation(header: str, bullets: list[str], name: str):
    from mtg_bot.cards.parser.activated import _parse_activation_cost
    from mtg_bot.cards.parser.creature_builder import _parse_modal_mode_phrase
    from mtg_bot.cards.parser.triggers import _substitute_self_name
    from mtg_bot.effects.base import ActivatedAbility
    from mtg_bot.effects.combinators import ModalChooseOne

    m = _MODAL_ACTIVATION_HEADER.match(_substitute_self_name(header, name))
    if m is None or len(bullets) < 2:
        return None
    cost = _parse_activation_cost(m.group("cost"))
    if cost is None:
        return None
    modes = []
    for bullet in bullets:
        eff = _parse_modal_mode_phrase(
            _substitute_self_name(bullet[len("• "):], name),
        )
        if eff is None:
            return None
        modes.append(eff)
    return ActivatedAbility(cost=cost, effect=ModalChooseOne(modes=tuple(modes)))


def claim_equipment_lines(card: dict):
    """The equipment builder's pre-pass: claim the multi-line / compound
    shapes its line loop can't see whole. Returns ``(remaining oracle
    text, BoardLine)`` -- modal activated abilities in
    ``BoardLine.activated``, a ward rider as the
    ``attached_grants_ward_cost`` field with the rest of its line handed
    back -- or ``None`` when a claimed block fails to parse."""
    from mtg_bot.cards.base import parse_mana_cost
    from mtg_bot.cards.parser.text import _strip_reminder_text

    text = card.get("oracle_text", "")
    if _disabled():
        return text, BoardLine()
    lines = [_strip_reminder_text(raw).strip() for raw in text.split("\n")]
    kept: list[str] = []
    out = BoardLine()
    activated: list = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _MODAL_ACTIVATION_HEADER.match(line):
            bullets = []
            j = i + 1
            while j < len(lines) and lines[j].startswith("• "):
                bullets.append(lines[j])
                j += 1
            ability = _modal_activation(line, bullets, card.get("name", ""))
            if ability is None:
                return None
            activated.append(ability)
            i = j
            continue
        m = _EQUIPPED_WARD_RIDER.match(line)
        if m is not None:
            out.fields["attached_grants_ward_cost"] = parse_mana_cost(
                m.group("cost"),
            )
            out.fields["attached_grants_ward_str"] = m.group("cost")
            kept.append(f"{m.group('head')}.")
            i += 1
            continue
        kept.append(line)
        i += 1
    out.activated = tuple(activated)
    return "\n".join(kept), out


def apply_board_fields(printing, fields: dict):
    """``dataclasses.replace`` for a builder's accumulated P5 fields:
    accumulated fields extend what the printing already carries."""
    from dataclasses import replace

    if not fields:
        return printing
    updates = {}
    for name, value in fields.items():
        if name in _ACCUMULATED_FIELDS:
            updates[name] = tuple(getattr(printing, name)) + tuple(value)
        else:
            updates[name] = value
    return replace(printing, **updates)


def absorb_land_line(line: str, card: dict, fields: dict,
                     triggered: list, activated: list) -> bool:
    """The line-composed land builder's fallback for a line its grammar
    declined. Lands take triggered / activated abilities and printing
    fields; a line contributing keywords or anthem statics is declined."""
    board = parse_roto_board_line(line, card)
    if board is None or board.keywords or board.statics:
        return False
    triggered.extend(board.triggers)
    activated.extend(board.activated)
    merge_board_fields(fields, board.fields)
    return True


def absorb_enchantment_line(line: str, card: dict, acc) -> bool:
    """The cube enchantment builder's fallback for a line its grammar
    declined: fold a recognized P5 line into its ``_Accumulator``."""
    board = parse_roto_board_line(line, card)
    if board is None:
        return False
    acc.keywords.update(board.keywords)
    acc.triggers.extend(board.triggers)
    acc.activated.extend(board.activated)
    acc.statics.extend(board.statics)
    merge_board_fields(acc.printing_fields, board.fields)
    return True


__all__ = [
    "BoardLine",
    "claim_equipment_lines",
    "parse_roto_trigger_phrase",
    "parse_roto_board_effect",
    "parse_roto_board_line",
    "parse_roto_cost_piece",
    "permanent_phrase",
]
