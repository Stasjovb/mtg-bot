"""Synthetic-printing guard coverage for
``mtg_bot.parity.trajectory._printing_is_bridge_pure_warp_creature``
— the warp_cost Phase-1/1.5 §2 guardrail's teeth.

WHY THIS MODULE EXISTS
----------------------
The warp-substrate guardrail (round-63 Phase 1 + round-65 Phase 1.5,
added this continuous-pipeline cycle) reuses the SAME exclusion set as
:func:`_printing_is_bridge_simple_creature` MINUS the ``warp_cost``
rejection (it *requires* warp_cost) PLUS the two Phase-2-rider positive
rejections (life cost / graveyard recast). Its admit/decline behavior
against the LIVE EoE pool is already pinned by the three real-card
tests in ``test_trajectory.py``
(``test_r63_warp_phase15_guardrail_*``). But the LIVE pool's 32 warp
printings only ever trip a SUBSET of the predicate's structural
disqualifier guards — enumerating every warp card shows NONE carry an
activated ability, a spell effect, a kicker/impending cost, a Room
half, loyalty, a cost-reduction, a station threshold, a dynamic-P/T
formula, a ward cost, an out-of-``_SAFE_KEYWORDS`` keyword, or a mana
string the codec can't parse. Those ``return False`` arms are
genuinely *reachable* (a future warp printing could carry any of
them — the guardrail MUST decline it to stay §2-correct), but no
existing test exercises them, so they were uncovered after this
cycle's merges.

These are NOT coverage-theater line pokes: each test asserts the
load-bearing §2 contract — *a warp creature that is otherwise clean
but carries exactly ONE disqualifier is DECLINED* — the same
guardrail's-teeth shape the sibling ``_printing_is_bridge_simple_
creature`` synthetic-guard tests in ``test_trajectory.py`` assert. The
clean-baseline positive case is pinned too, so a future bug that makes
the predicate reject everything (or accept everything) fails here.

Kept in a SEPARATE module (not appended to the large, concurrently-
edited ``test_trajectory.py``) per the continuous-pipeline
coverage-slice convention.
"""

from __future__ import annotations

import pytest

from mtg_bot.cards.base import (
    CostReduction,
    CardPrinting,
    ManaCost,
    RoomHalf,
)
from mtg_bot.effects.base import ActivatedAbility, StaticAbility
from mtg_bot.effects.generic.life import GainLife
from mtg_bot.parity.trajectory import _printing_is_bridge_pure_warp_creature


def _warp_creature(**overrides) -> CardPrinting:
    """A minimal CLEAN pure-fixed-cost warp creature the guardrail
    ADMITS — Bygone-Colossus-shaped (no triggers, warp is the only
    blocking feature). Tests override exactly one field to a single
    disqualifier and assert the guardrail declines it."""
    base = dict(
        name="Synthetic Warp Bear",
        mana_cost_str="{3}{R}",
        mana_cost=ManaCost(generic=3, colored=(("R", 1),)),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),
        warp_cost=ManaCost(generic=1, colored=(("R", 1),)),
        warp_cost_str="{1}{R}",
    )
    base.update(overrides)
    return CardPrinting(**base)


# --------------------------------------------------- the clean baseline


def test_clean_pure_fixed_cost_warp_creature_is_admitted():
    """The positive control: a warp creature whose ONLY blocking
    feature is ``warp_cost`` (no triggers, no riders) is ADMITTED.
    Pins the predicate's accept path so a future over-tightening that
    declines the legitimate Phase-1 shape fails loudly here (the
    sibling of the real-card ``Bygone Colossus`` admit pin, with a
    synthetic carrier so it stays green if that printing leaves the
    pool)."""
    assert _printing_is_bridge_pure_warp_creature(_warp_creature()) is True


# ---------------------------------- structural-disqualifier guard teeth
# Each: an otherwise-clean warp creature carrying exactly ONE
# disqualifier the LIVE pool's 32 warp cards never exercise. The
# guardrail MUST decline it (the §2 exclusion set's teeth).


def test_warp_guard_declines_unsafe_keyword():
    """A warp creature with a keyword OUTSIDE ``_SAFE_KEYWORDS``
    (``flash``) is DECLINED — admitting an unmodeled keyword would
    silently diverge the two engines at probe time. (No live warp
    printing carries a non-safe keyword; every warp card's keywords
    are flying/haste/lifelink, all already safe.)"""
    p = _warp_creature(keywords=frozenset({"flash"}))
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_activated_ability():
    """A warp creature with ANY activated ability is DECLINED — the
    CardDef bridge models no activated abilities, so admitting one
    would drop a whole interaction surface asymmetrically."""
    aa = ActivatedAbility(cost=ManaCost(generic=1), effect=GainLife(amount=1))
    p = _warp_creature(activated_abilities=(aa,))
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_static_ability():
    """A warp creature with a static ability is DECLINED — Starfield
    Vocalist is the real-pool analogue, but THIS pins the guard
    directly on a synthetic so it stays meaningful if the pool
    shifts."""
    sa = StaticAbility(scope="self", power_bonus=1)
    p = _warp_creature(static_abilities=(sa,))
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_spell_effect():
    """A warp *creature* carrying a ``spell_effect`` is DECLINED — a
    creature with a resolution effect is not the modeled shape (no
    live warp creature has one)."""
    p = _warp_creature(spell_effect=GainLife(amount=3))
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_kicker_cost():
    """A warp creature that is ALSO kicker-able is DECLINED — kicker
    is a separate unmodeled alt-cost; warp_cost is required but kicker
    still rejects (the predicate's explicit NOTE)."""
    p = _warp_creature(kicker_cost=ManaCost(generic=2))
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_impending_cost():
    """A warp creature with an impending alt-cost is DECLINED — same
    unmodeled-alt-cost class as kicker (the ``or`` arm of the same
    guard)."""
    p = _warp_creature(impending_cost=ManaCost(generic=2, colored=(("R", 1),)))
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_room_halves():
    """A warp printing with Room halves is DECLINED — Rooms are a
    distinct enchantment substrate the CardDef bridge does not
    model."""
    rh = RoomHalf(
        name="Door A",
        mana_cost_str="{1}",
        mana_cost=ManaCost(generic=1),
    )
    p = _warp_creature(room_halves=(rh,))
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_loyalty():
    """A warp permanent with loyalty (a planeswalker-shaped carrier)
    is DECLINED — loyalty is unmodeled by the creature CardDef."""
    p = _warp_creature(loyalty=3)
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_cost_reductions():
    """A warp creature with a baked-in cost reduction is DECLINED —
    conditional cost reductions are not modeled in the bridge codec."""
    from mtg_bot.effects.conditions import DuringYourTurn

    cr = CostReduction(amount=1, condition=DuringYourTurn())
    p = _warp_creature(cost_reductions=(cr,))
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_station_threshold():
    """A warp Spacecraft with a station threshold is DECLINED — the
    station mechanic is a separate unmodeled substrate."""
    p = _warp_creature(station_threshold=2)
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_dynamic_pt_formula():
    """A warp creature with a dynamic-P/T formula (``*`` power) is
    DECLINED — the bridge carries only fixed integer P/T."""
    p = _warp_creature(dynamic_pt_formula="*")
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_ward_cost():
    """A warp creature with a ward cost is DECLINED — ward is an
    unmodeled protective cost the CardDef bridge does not carry."""
    p = _warp_creature(ward_cost=ManaCost(generic=1))
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_unparseable_warp_cost_string():
    """A warp creature whose ``warp_cost_str`` contains a symbol the
    codec can't parse (``{X}``) is DECLINED — the predicate parses
    BOTH the normal and warp mana strings and falls back to declining
    on ``ValueError`` (the production-filter contract). The normal
    ``mana_cost_str`` stays valid so the failure is isolated to the
    warp-side parse."""
    p = _warp_creature(warp_cost_str="{X}{R}")
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_unparseable_normal_cost_string():
    """The sibling of the above on the NORMAL mana string — a
    hybrid/Phyrexian/X symbol in ``mana_cost_str`` also declines (the
    first of the two parsed strings in the same try/except)."""
    p = _warp_creature(mana_cost_str="{W/U}{R}")
    assert _printing_is_bridge_pure_warp_creature(p) is False


# ----------------------------------- Phase-2-rider teeth (synthetic)
# Timeline Culler is the real-pool carrier; these pin the two positive
# rejections directly so they stay meaningful independent of the pool.


def test_warp_guard_declines_warp_additional_life_cost():
    """A warp creature with ``warp_additional_life_cost > 0`` is
    DECLINED — a Phase-2 rider (Timeline Culler's "Pay 2 life"); the
    §2 guardrail's teeth."""
    p = _warp_creature(warp_additional_life_cost=2)
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_warp_castable_from_graveyard():
    """A warp creature with ``warp_castable_from_graveyard=True`` is
    DECLINED — the other Phase-2 rider; never flips on warp alone."""
    p = _warp_creature(warp_castable_from_graveyard=True)
    assert _printing_is_bridge_pure_warp_creature(p) is False


# ------------------------------------- the required-feature negatives
# warp_cost is REQUIRED — a non-warp / non-creature / no-P-T printing
# is declined by the early guards (these are exercised by real cards
# too, but pinning them on synthetics keeps the early-return contract
# explicit alongside the rest).


def test_warp_guard_declines_missing_warp_cost():
    """No ``warp_cost`` → DECLINED. This predicate is warp-ONLY; a
    plain simple creature must NOT route through the warp CardDef arm
    (it would spuriously set ``has_warp``)."""
    p = _warp_creature(warp_cost=None, warp_cost_str="")
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_non_creature():
    """A non-creature warp card (e.g. Eusocial Engineering's shape) is
    DECLINED by the first guard — this predicate is creature-only."""
    p = _warp_creature(card_types=("Sorcery",), power=None, toughness=None)
    assert _printing_is_bridge_pure_warp_creature(p) is False


def test_warp_guard_declines_creature_without_power_toughness():
    """A 'Creature' typed printing with ``power``/``toughness`` None is
    DECLINED by the P/T guard (defensive — a malformed parse must not
    sneak through as a 0/0)."""
    p = _warp_creature(power=None, toughness=None)
    assert _printing_is_bridge_pure_warp_creature(p) is False


@pytest.mark.parametrize(
    "safe_kw",
    ["flying", "haste", "lifelink", "trample", "vigilance", "reach"],
)
def test_warp_guard_admits_safe_keyword(safe_kw):
    """A warp creature carrying a SINGLE in-``_SAFE_KEYWORDS`` keyword
    is still ADMITTED (the keyword guard rejects ONLY out-of-set
    keywords). Complements the unsafe-keyword decline above so the
    guard's boundary is pinned on both sides — a regression that
    inverted the subset check would fail one of these."""
    p = _warp_creature(keywords=frozenset({safe_kw}))
    assert _printing_is_bridge_pure_warp_creature(p) is True
