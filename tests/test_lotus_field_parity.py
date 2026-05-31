"""Lotus Field -- per-card real-EoE cross-engine byte-equal probe for
the NEW ``Effect::SacrificeNLandsYouControl`` substrate + the existing
``AddNManaOfChosenColor`` mana AA.

**Lotus Field substrate (2026-05-31 -- spec at
``docs/BLOCKED_TAIL_TRACTABILITY_SCOUT_2026-05-27.md`` §Lotus Field.)**

Lotus Field (Land, EoE) is the printed card::

    Lotus Field enters tapped.
    When Lotus Field enters, sacrifice two lands.
    Hexproof.
    {T}: Add three mana of any one color.

The live ``OracleParserCardSource`` flattens this to::

    keywords            = {hexproof}
    enters_tapped       = True
    triggered_abilities = (TriggeredAbility(
                              event=ENTERS, predicate=IsSelf,
                              effect=SacrificeNLandsYouControl(count=2)),)
    activated_abilities = (AA[0] -- {T}: AddNManaOfChosenColor(
                              amount=3, options=('W','U','B','R','G')),)

**This slice is a SUBSTRATE-ONLY landing -- Lotus Field STAYS BLOCKED
at the loader admit gate.** The scout's tractability estimate
(``effect_uncovered`` -- the only uncovered piece being the
``SacrificeNLandsYouControl`` ETB Effect) was correct about the Effect
gap but UNDER-counted the loader admit surface: Lotus Field is a
COMPOSITE carrier (a mana-producing land + ``enters_tapped`` +
``keywords={hexproof}`` + an ETB ``triggered_abilities``). NONE of the
existing bridge admit predicates accept that combination:

  * ``_printing_is_bridge_simple_carrier_aa_land`` hard-DECLINES any
    printing with ``keywords`` (``trajectory.py:9847``) AND any with
    ``triggered_abilities`` (``trajectory.py:9849``).
  * ``_printing_is_bridge_simple_tapped_mana_land`` (and the keyword-
    colorless-tapped sibling) DECLINE any printing carrying activated
    OR triggered abilities.

Admitting Lotus Field through the loader therefore needs a brand-new
COMPOSITE admit path (chosen-color mana AA + enters_tapped + hexproof +
ETB trigger co-gated on one printing) -- well beyond a single Effect
port. Per the campaign honest-stop policy that composite-admit
substrate is left as characterized follow-up work; this slice lands the
solid, genuinely-uncovered ``SacrificeNLandsYouControl`` Rust Effect
mirror + its cross-engine bridge reverse arm, proven byte-equal on a
synthetic-bridged Rust state vs the REAL parsed Lotus Field printing on
Python.

The LOAD-BEARING honest-stop pin
``test_lotus_field_stays_declined_at_loader_admit_gate`` asserts the
printing-level decline so a future composite-admit widen surfaces here
loudly rather than silently auto-admitting an unmodeled rider cluster.

Scenarios:

  * **SAC-TWO (the NEW Effect).** Real parsed Lotus Field on Python's
    battlefield as ``resolving_source``, 3 plain lands alongside; the
    ETB ``SacrificeNLandsYouControl(count=2)`` resolves -> 2 non-source
    lands sacrificed, source + 1 land survive. The byte-equal synthetic
    on Rust (the source land wired with the bare
    ``sacrifice_n_lands_you_control`` AA leaf + 3 plain lands) drives
    the same resolve -> same battlefield / graveyard land split.
  * **SAC-UNDER (under-count).** Only 1 non-source land; both engines
    sacrifice the 1 available and stop (no error).
  * **MINT-3 (the existing mana AA).** Real Lotus Field's
    ``{T}: AddNManaOfChosenColor(3, WUBRG)`` AA[0] mints 3 coins of the
    no-agent-fallback first color (W) on Python; the byte-equal Rust
    synthetic mints the same 3 W coins. (AddNManaOfChosenColor's Rust
    arm landed with the Grove of the Burnwillows closure -- this
    asserts the 5-color amount=3 shape round-trips byte-equal.)
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# Zone constants (Rust int encoding).
ZONE_BATTLEFIELD = 2


# Canonical Rust synthetic dicts. The source land wires Lotus Field's
# ETB-effect leaf (``sacrifice_n_lands_you_control``) as a mana-ability
# AA so the Rust harness can drive the resolve via
# ``apply_action(activate_ability)`` (the ETB-effect resolve dispatch is
# the same ``apply_effect`` path regardless of whether the effect rode a
# trigger or an AA). A separate dict wires the real Lotus Field mana AA
# (``add_n_mana_of_chosen_color``, amount=3, 5 colors) for the MINT-3
# scenario.
_RUST_SAC_SOURCE_DICT = {
    "name": "Lotus Field (sac-leaf synthetic)",
    "card_types": ["Land"],
    "activated_abilities": [
        {
            "cost": {"tap_self": True},
            "effect": {
                "kind": "sacrifice_n_lands_you_control",
                "count": 2,
            },
            "is_mana_ability": True,
        },
    ],
}

_RUST_MINT_SOURCE_DICT = {
    "name": "Lotus Field (mana-AA synthetic)",
    "card_types": ["Land"],
    "activated_abilities": [
        {
            "cost": {"tap_self": True},
            "effect": {
                "kind": "add_n_mana_of_chosen_color",
                "amount": 3,
                "options": ["W", "U", "B", "R", "G"],
            },
            "is_mana_ability": True,
        },
    ],
}

_RUST_PLAIN_LAND = {
    "name": "Plain Land",
    "card_types": ["Land"],
    "mana_produced": ["G"],
}


_EMPTY_MANA_POOL = {
    "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "any": 0,
}


# ---------------------------------------------------------------------------
# (1) Parser SoT -- verify-first: Lotus Field's parsed shape (the §2
# teeth the substrate + the loader-decline both depend on).
# ---------------------------------------------------------------------------


def test_lotus_field_parser_claims_card():
    assert "Lotus Field" in _PRINTINGS, (
        "Lotus Field must be parser-claimed by the active CardSource"
    )


def test_lotus_field_printed_attrs():
    """Pins Lotus Field's parsed surface: bare Land, ``{0}`` cost,
    ``keywords={hexproof}``, ``enters_tapped=True``, ONE ETB triggered
    ability carrying ``SacrificeNLandsYouControl(count=2)``, ONE
    ``{T}: AddNManaOfChosenColor(3, WUBRG)`` mana AA. The §2 teeth.
    """
    from mtg_bot.effects import SacrificeNLandsYouControl
    from mtg_bot.effects.generic.mana import AddNManaOfChosenColor

    p = _PRINTINGS["Lotus Field"]
    assert p.card_types == ("Land",)
    assert p.subtypes == ()
    assert p.supertypes == ()
    assert p.power is None and p.toughness is None
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()
    assert p.keywords == frozenset({"hexproof"})
    assert getattr(p, "enters_tapped", False) is True

    # The ETB triggered ability -- the NEW Effect.
    assert len(p.triggered_abilities) == 1
    ta = p.triggered_abilities[0]
    assert isinstance(ta.effect, SacrificeNLandsYouControl)
    assert ta.effect.count == 2

    # The mana AA -- already covered (Grove landed AddNManaOfChosenColor).
    assert len(p.activated_abilities) == 1
    aa0 = p.activated_abilities[0]
    assert aa0.cost.tap_self is True
    assert isinstance(aa0.effect, AddNManaOfChosenColor)
    assert aa0.effect.amount == 3
    assert aa0.effect.options == ("W", "U", "B", "R", "G")
    assert aa0.is_mana_ability is True


# ---------------------------------------------------------------------------
# (2) LOAD-BEARING honest-stop: Lotus Field STAYS DECLINED at the loader
# admit gate. The composite carrier-shape (mana AA + enters_tapped +
# hexproof + ETB trigger) is admitted by NO existing bridge predicate.
# ---------------------------------------------------------------------------


def test_lotus_field_stays_declined_at_loader_admit_gate():
    """**The substrate-only invariant.** Lotus Field must DECLINE at
    every relevant bridge admit predicate post-substrate: the Carrier-AA
    Land predicate (declines on ``keywords`` + ``triggered_abilities``),
    AND the end-to-end ``_filter_deck_to_bridge_supported`` loader
    (Lotus Field is filtered OUT of the supported set).

    A future composite-admit widen that flips Lotus Field will trip this
    pin -- the author must then update it to the PROBED-tier expectation
    deliberately rather than silently auto-admitting an unmodeled rider.
    """
    from mtg_bot.parity.trajectory import (
        _filter_deck_to_bridge_supported,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_land,
    )

    p = _PRINTINGS["Lotus Field"]
    # Carrier-AA predicates decline (keywords + triggered_abilities teeth).
    assert _printing_is_bridge_simple_carrier_aa_land(p) is False
    assert _printing_is_bridge_simple_carrier_aa_any(p) is False

    # End-to-end loader: Lotus Field is filtered OUT.
    filt, defs = _filter_deck_to_bridge_supported(
        ["Lotus Field"], _PRINTINGS,
    )
    assert filt == [], (
        "Lotus Field must STAY DECLINED at the loader admit gate post-"
        "substrate (composite carrier shape: mana AA + enters_tapped + "
        "hexproof + ETB trigger -- no existing bridge predicate admits "
        "it). Got filt={filt!r}".format(filt=filt)
    )
    assert defs == []


# ---------------------------------------------------------------------------
# (3) Bridge reverse-arm round-trip -- the NEW
# ``sacrifice_n_lands_you_control`` dict rehydrates to the Python
# ``SacrificeNLandsYouControl`` class with the right ``count``.
# ---------------------------------------------------------------------------


def test_sacrifice_n_lands_bridge_reverse_arm():
    """``_ta_dict_to_python_effect({"kind":
    "sacrifice_n_lands_you_control", "count": N})`` -> Python
    ``SacrificeNLandsYouControl(count=N)``. Covers the default count + an
    alt count + the count-omitted forward-compat default (2).
    """
    from mtg_bot.effects import SacrificeNLandsYouControl
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    eff = _ta_dict_to_python_effect(
        {"kind": "sacrifice_n_lands_you_control", "count": 2}
    )
    assert isinstance(eff, SacrificeNLandsYouControl)
    assert eff.count == 2

    eff3 = _ta_dict_to_python_effect(
        {"kind": "sacrifice_n_lands_you_control", "count": 3}
    )
    assert isinstance(eff3, SacrificeNLandsYouControl)
    assert eff3.count == 3

    # count omitted -> forward-compat default 2 (Python dataclass default).
    eff_def = _ta_dict_to_python_effect(
        {"kind": "sacrifice_n_lands_you_control"}
    )
    assert isinstance(eff_def, SacrificeNLandsYouControl)
    assert eff_def.count == 2


# ---------------------------------------------------------------------------
# (4) Rust acceptance smoke -- the synthetic Lotus Field sac dict parses
# on ``register_printing``.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_sac_n_lands_dict():
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_RUST_SAC_SOURCE_DICT)
    assert isinstance(pid, int)
    assert reg.get_printing_name(pid) == "Lotus Field (sac-leaf synthetic)"


# ---------------------------------------------------------------------------
# Python-side harness -- seat the REAL Lotus Field printing as
# ``resolving_source`` plus N plain lands; returns the GameState.
# ---------------------------------------------------------------------------


def _build_python_sac_state(n_plain_lands: int):
    """Real parsed Lotus Field on p0's battlefield as ``resolving_source``,
    plus ``n_plain_lands`` Mountains. No agent (so the sac picks the
    canonical-first land deterministically -- byte-equal with Rust's
    no-agent shortcut).
    """
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import Step

    state = GameState()
    state.players.append(Player(id=0, agent=None))
    state.players.append(Player(id=1, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN

    source = state.new_object(
        _PRINTINGS["Lotus Field"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(source)
    for _ in range(n_plain_lands):
        m = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(m)
    return state, source


def _py_land_split(state, source):
    """(non_source_lands_on_bf, lands_in_graveyard) for p0 -- the byte-
    equal observable the Rust side mirrors.
    """
    non_source_lands = sum(
        1
        for o in state.battlefield
        if o.printing.is_land and o.id != source.id
    )
    gy_lands = sum(
        1 for o in state.players[0].graveyard if o.printing.is_land
    )
    return non_source_lands, gy_lands


# ---------------------------------------------------------------------------
# (5) SAC-TWO -- the NEW Effect end-to-end byte-equal. Real Lotus Field
# ETB sac on Python vs the bridged synthetic on Rust.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_lotus_field_sac_two_parity():
    """**GENUINE real-EoE cross-engine probe -- SAC-TWO.** Real parsed
    Lotus Field's ETB ``SacrificeNLandsYouControl(count=2)`` resolves on
    Python; the bridged synthetic resolves on Rust. Both sacrifice
    exactly 2 non-source lands; the source land + 1 plain land survive.
    Byte-equal on the (non_source_lands_on_bf, lands_in_graveyard) split.
    """
    import mtg_bot_engine
    from mtg_bot.effects import SacrificeNLandsYouControl

    # ---- Python: real Lotus Field + 3 Mountains; resolve the ETB sac.
    py, source = _build_python_sac_state(3)
    py.resolving_source = source
    try:
        SacrificeNLandsYouControl(count=2).resolve(py, 0, ())
    finally:
        py.resolving_source = None
    py_split = _py_land_split(py, source)
    assert py_split == (1, 2), (
        f"Python: 2 of 3 plain lands sacrificed, source + 1 survive; "
        f"got split={py_split}"
    )

    # ---- Rust: synthetic source (sac-leaf AA) + 3 plain lands; drive.
    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    for _ in range(3):
        rs.register_and_inject_object(_RUST_PLAIN_LAND, 0, ZONE_BATTLEFIELD)
    rs_src = rs.register_and_inject_object(
        _RUST_SAC_SOURCE_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.force_set_summoning_sick(rs_src, False)
    rs.apply_action({
        "kind": "activate_ability",
        "source_id": rs_src,
        "ability_index": 0,
    })

    rs_non_source_lands = sum(
        1
        for o in rs.battlefield_snapshot()
        if o["controller_id"] == 0 and o["id"] != rs_src
    )
    rs_gy_lands = len(rs.graveyard_snapshot(0))
    rs_split = (rs_non_source_lands, rs_gy_lands)
    assert rs_split == (1, 2), (
        f"Rust: 2 of 3 plain lands sacrificed, source + 1 survive; "
        f"got split={rs_split}"
    )

    # ---- Cross-engine byte-equal.
    assert py_split == rs_split, (
        f"Cross-engine byte-equal (land split): py={py_split}, rs={rs_split}"
    )
    # Source land survives on both engines.
    assert source in py.battlefield
    assert any(o["id"] == rs_src for o in rs.battlefield_snapshot())


# ---------------------------------------------------------------------------
# (6) SAC-UNDER -- under-count byte-equal. Only 1 non-source land; both
# engines sacrifice the 1 available and stop.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_lotus_field_sac_under_count_parity():
    """**GENUINE real-EoE cross-engine probe -- SAC-UNDER.** Only 1
    non-source land present but ``count=2``; both engines sacrifice the
    1 available and stop (no error). Byte-equal on the land split.
    """
    import mtg_bot_engine
    from mtg_bot.effects import SacrificeNLandsYouControl

    py, source = _build_python_sac_state(1)
    py.resolving_source = source
    try:
        SacrificeNLandsYouControl(count=2).resolve(py, 0, ())
    finally:
        py.resolving_source = None
    py_split = _py_land_split(py, source)
    assert py_split == (0, 1)

    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    rs.register_and_inject_object(_RUST_PLAIN_LAND, 0, ZONE_BATTLEFIELD)
    rs_src = rs.register_and_inject_object(
        _RUST_SAC_SOURCE_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.force_set_summoning_sick(rs_src, False)
    rs.apply_action({
        "kind": "activate_ability",
        "source_id": rs_src,
        "ability_index": 0,
    })
    rs_non_source_lands = sum(
        1
        for o in rs.battlefield_snapshot()
        if o["controller_id"] == 0 and o["id"] != rs_src
    )
    rs_split = (rs_non_source_lands, len(rs.graveyard_snapshot(0)))
    assert rs_split == (0, 1)
    assert py_split == rs_split


# ---------------------------------------------------------------------------
# (7) MINT-3 -- the EXISTING mana AA byte-equal. Real Lotus Field's
# {T}: AddNManaOfChosenColor(3, WUBRG) mints 3 coins of the no-agent
# fallback first color (W) on both engines.
# ---------------------------------------------------------------------------


def _py_mana_pool_counts(py, player_id: int) -> dict:
    counts = dict(_EMPTY_MANA_POOL)
    for coin in py.players[player_id].mana_pool:
        if coin.color in counts:
            counts[coin.color] += 1
    return counts


@_rust_skip
def test_cross_engine_real_eoe_lotus_field_mint_three_parity():
    """**GENUINE real-EoE cross-engine probe -- MINT-3.** Real parsed
    Lotus Field's ``{T}: AddNManaOfChosenColor(3, WUBRG)`` AA[0] mints 3
    coins of the no-agent ``options[0]="W"`` fallback color on Python;
    the byte-equal Rust synthetic mints the same 3 W coins. Pins the
    5-color amount=3 chosen-color shape round-trips byte-equal (the
    AddNManaOfChosenColor Rust arm landed with the Grove closure; this
    exercises it at amount=3 / 5 options).
    """
    import mtg_bot_engine
    from mtg_bot.actions import ActivateAbility, apply_action
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.turn import Step

    # ---- Python: real Lotus Field on p0's bf, no agent (options[0]=W).
    py = GameState()
    py.players.append(Player(id=0, agent=None))
    py.players.append(Player(id=1, agent=None))
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.step = Step.PRECOMBAT_MAIN
    lotus = py.new_object(_PRINTINGS["Lotus Field"], 0, Zone.BATTLEFIELD)
    lotus.summoning_sick = False
    py.battlefield.append(lotus)
    apply_action(
        py, 0, ActivateAbility(source_id=lotus.id, ability_index=0),
    )
    py_pool = _py_mana_pool_counts(py, 0)
    expected = dict(_EMPTY_MANA_POOL, W=3)
    assert py_pool == expected, (
        f"Python: Lotus Field {{T}} must mint 3 W coins (options[0] "
        f"fallback); got {py_pool}"
    )

    # ---- Rust: synthetic mana-AA source; mint 3 W coins.
    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    rs_src = rs.register_and_inject_object(
        _RUST_MINT_SOURCE_DICT, 0, ZONE_BATTLEFIELD,
    )
    rs.force_set_summoning_sick(rs_src, False)
    rs.apply_action({
        "kind": "activate_ability",
        "source_id": rs_src,
        "ability_index": 0,
    })
    rs_pool = rs.mana_pool_snapshot(0)
    assert rs_pool == expected, (
        f"Rust: Lotus Field {{T}} must mint 3 W coins (options[0] "
        f"fallback); got {rs_pool}"
    )
    assert py_pool == rs_pool, (
        f"Cross-engine byte-equal (3-W-coin mint): py={py_pool}, rs={rs_pool}"
    )
