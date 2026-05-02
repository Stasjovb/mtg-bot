"""Coverage chip-away: ``Pump.describe()`` text shapes.

The unified ``Pump`` primitive's ``describe()`` body assembles a printed
phrase from three independent dimensions: the (optional) +P/+T bonus,
the (optional) keyword grant set, and the slot-derived target phrase.
The bare ``Pump`` (subclasses override ``describe`` for their own card-
specific wording) covers three branches:

1. P/T-only — "target X gets +N/+M until end of turn."
2. Keywords-only — "target X gains KW1, KW2 until end of turn."
3. P/T + keywords — "target X gets +N/+M and gains KW1 until end of turn."

These are exercised by parser-shape tests on the subclass family but the
bare-``Pump`` ``describe`` body itself (lines 454-468 in generic.py) had
no direct test until now. Single-card resolve paths are out of scope for
these tests — only the ``describe`` surface is pinned.
"""

from __future__ import annotations

from mtg_bot.effects.generic import Pump
from mtg_bot.effects.object_predicates import IsCreature
from mtg_bot.effects.targets import TargetSpec


def _creature_pump(**kwargs) -> Pump:
    return Pump(targets=(TargetSpec(IsCreature()),), **kwargs)


def test_describe_pure_pt_uses_signed_bonus_and_target_phrase():
    """Pure +N/+M (no granted keywords) renders as
    'target creature gets +N/+M until end of turn.'."""
    p = _creature_pump(power_bonus=2, toughness_bonus=2)
    assert p.describe() == "target creature gets +2/+2 until end of turn."


def test_describe_pure_keywords_uses_gains_phrase():
    """Pure keyword grant (no +P/+T) renders as
    'target creature gains <kws> until end of turn.'."""
    p = _creature_pump(granted_keywords=frozenset({"flying"}))
    assert p.describe() == "target creature gains flying until end of turn."


def test_describe_combined_pt_and_keywords_joins_with_and():
    """Combined +P/+T and keyword grant joins both clauses with ' and '."""
    p = _creature_pump(
        power_bonus=1, toughness_bonus=1,
        granted_keywords=frozenset({"flying"}),
    )
    assert (
        p.describe()
        == "target creature gets +1/+1 and gains flying until end of turn."
    )


def test_describe_multi_keyword_grant_sorts_keywords():
    """Multiple granted keywords are sorted for stable output."""
    p = _creature_pump(
        granted_keywords=frozenset({"trample", "flying"}),
    )
    # Sorted: "flying" before "trample".
    assert (
        p.describe()
        == "target creature gains flying, trample until end of turn."
    )


def test_describe_zero_pump_with_keywords_skips_pt_clause():
    """A Pump with both bonuses 0 but keywords present skips the P/T
    clause — the conditional in describe()'s first branch tests truthy
    bonus."""
    p = _creature_pump(
        power_bonus=0, toughness_bonus=0,
        granted_keywords=frozenset({"haste"}),
    )
    # Should NOT include "+0/+0" — only the keyword clause.
    desc = p.describe()
    assert "gets" not in desc
    assert desc == "target creature gains haste until end of turn."
