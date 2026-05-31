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

**This slice is the COMPOSITE LOADER-ADMIT landing -- Lotus Field is
now ADMITTED at the loader admit gate and flips covered-by-construction
-> PROBED.** Lotus Field is a COMPOSITE carrier (a chosen-color mana AA
+ ``enters_tapped`` + ``keywords={hexproof}`` + an ETB
``triggered_abilities``). NONE of the pre-existing bridge admit
predicates accept that combination:

  * ``_printing_is_bridge_simple_carrier_aa_land`` hard-DECLINES any
    printing with ``keywords`` (``trajectory.py:9847``) AND any with
    ``triggered_abilities`` (``trajectory.py:9849``).
  * ``_printing_is_bridge_simple_tapped_mana_land`` (and the keyword-
    colorless-tapped sibling) DECLINE any printing carrying activated
    OR triggered abilities.

The brand-new composite admit path
``_printing_is_bridge_carrier_aa_land_with_etb_sac_and_keyword`` co-
gates all four riders on one printing (chosen-color mana AA +
enters_tapped + hexproof + ETB trigger), admitting EXACTLY the Lotus
Field shape (Phase-1 specificity contract -- NOT a broad widen). The
matching builder
``_carrier_aa_land_with_etb_sac_and_keyword_card_def`` emits all four
pieces all-or-nothing onto one Land CardDef (the mana AA via the safe-
dict round-trip floor, the keyword via the CardDef ``keywords`` field,
the ETB trigger as a ``{"event": "enters", "predicate": {"kind":
"source_is_self"}, "effect": {"kind": "sacrifice_n_lands_you_control",
...}}`` round-trip dict). ``enters_tapped`` is dropped symmetrically on
both engines (no plain enters_tapped bridge field -- the round-85
Planet land / Cathedral of War symmetric-drop precedent). This is a
PYTHON-ONLY landing: the ``SacrificeNLandsYouControl`` Rust Effect +
its reverse bridge arm already landed at merge ``5dbb9c37``, and the
keyword + mana-AA pieces round-trip through the existing ``keywords``
Vec + ``_python_aa_to_safe_dict`` floor (Phase-4E lifted the mana-AA
decline). No Rust change this slice.

The ADMIT pin ``test_lotus_field_admitted_at_loader_admit_gate``
asserts the printing-level admit + the emitted CardDef carrying all
four pieces, so a future regression that drops the composite admit
surfaces here loudly.

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
# (2) LOAD-BEARING admit pin: Lotus Field is ADMITTED at the loader
# admit gate via the composite carrier-shape path (mana AA +
# enters_tapped + hexproof + ETB trigger), and the emitted CardDef
# carries all four pieces.
# ---------------------------------------------------------------------------


def test_lotus_field_admitted_at_loader_admit_gate():
    """**The composite loader-admit invariant.** Lotus Field must:

      * DECLINE at the pre-existing Carrier-AA Land predicate (it still
        hard-declines on ``keywords`` + ``triggered_abilities``) -- the
        composite is NOT admitted by widening that predicate.
      * ADMIT at the NEW composite predicate
        ``_printing_is_bridge_carrier_aa_land_with_etb_sac_and_keyword``.
      * ADMIT end-to-end through ``_filter_deck_to_bridge_supported``,
        with the emitted CardDef carrying all four pieces (the
        ``hexproof`` keyword, the ETB
        ``sacrifice_n_lands_you_control`` triggered ability, and the
        ``add_n_mana_of_chosen_color`` mana AA; ``enters_tapped`` is
        symmetrically dropped -- no plain enters_tapped bridge field).

    A future regression that drops the composite admit (or silently
    auto-admits via the broad Carrier-AA path) trips this pin.
    """
    from mtg_bot.parity.trajectory import (
        _filter_deck_to_bridge_supported,
        _printing_is_bridge_carrier_aa_land_with_etb_sac_and_keyword,
        _printing_is_bridge_simple_carrier_aa_any,
        _printing_is_bridge_simple_carrier_aa_land,
    )

    p = _PRINTINGS["Lotus Field"]
    # The pre-existing broad Carrier-AA predicates STILL decline (the
    # composite admit is a NEW narrow path, not a widen of those).
    assert _printing_is_bridge_simple_carrier_aa_land(p) is False
    assert _printing_is_bridge_simple_carrier_aa_any(p) is False

    # The new composite predicate admits Lotus Field.
    assert (
        _printing_is_bridge_carrier_aa_land_with_etb_sac_and_keyword(p)
        is True
    )

    # End-to-end loader: Lotus Field is ADMITTED.
    filt, defs = _filter_deck_to_bridge_supported(
        ["Lotus Field"], _PRINTINGS,
    )
    assert filt == ["Lotus Field"], (
        "Lotus Field must be ADMITTED at the loader admit gate via the "
        "composite carrier-shape path. Got filt={filt!r}".format(filt=filt)
    )
    assert len(defs) == 1
    cd = defs[0]
    assert cd.name == "Lotus Field"
    assert cd.card_type == "Land"
    # The four-piece all-or-nothing emit (enters_tapped symmetrically
    # dropped -- no CardDef field for it).
    assert cd.keywords == ("hexproof",)
    assert len(cd.triggered_abilities) == 1
    ta_dict = cd.triggered_abilities[0]
    assert ta_dict["event"] == "enters"
    assert ta_dict["predicate"] == {"kind": "source_is_self"}
    assert ta_dict["effect"] == {
        "kind": "sacrifice_n_lands_you_control",
        "count": 2,
    }
    assert len(cd.activated_abilities) == 1
    aa_dict = cd.activated_abilities[0]
    assert aa_dict["effect"]["kind"] == "add_n_mana_of_chosen_color"
    assert aa_dict["effect"]["amount"] == 3
    assert aa_dict["is_mana_ability"] is True


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


# ---------------------------------------------------------------------------
# (8) COMPOSITE LOADER-ADMIT real-EoE cross-engine probes. The
# scenarios above drive a HAND-WRITTEN synthetic Rust source (the
# sac-leaf wired as an AA). These probes instead drive the ACTUAL
# loader-emitted CardDef -> Rust registry dict (via
# ``_printing_to_card_def`` -> ``_spec_card_to_printing_dict``), so the
# composite admit path's CardDef serialization is exercised end-to-end:
# the ETB ``SacrificeNLandsYouControl`` trigger fires from the
# loader-built printing's ``triggered_abilities`` (NOT a hand-wired AA),
# AND the ``{T}: AddNManaOfChosenColor(3, WUBRG)`` mana AA mints from
# the loader-built printing's ``activated_abilities``. Byte-equal vs the
# real parsed Lotus Field on Python.
#
# Rust ETB driver note: ``register_and_inject_object`` ALREADY queues
# the printing's ENTERS-triggered abilities onto the stack at inject
# time (the production ``drain_pending_etb_dispatches`` path), so the
# probe drives the resolve with ``process_stack_until_empty()`` alone
# -- calling ``dispatch_enters`` on top would double-fire.
# ---------------------------------------------------------------------------


def _rust_lotus_field_registry_dict():
    """The Rust registry dict for the LOADER-BUILT Lotus Field CardDef
    (the composite-admit path: ``_printing_to_card_def`` ->
    ``_spec_card_to_printing_dict``). Carries the ``hexproof`` keyword +
    the ETB ``sacrifice_n_lands_you_control`` trigger + the
    ``add_n_mana_of_chosen_color`` mana AA all on one printing.
    """
    from mtg_bot.parity.cross_engine import _spec_card_to_printing_dict
    from mtg_bot.parity.trajectory import _printing_to_card_def

    return _spec_card_to_printing_dict(
        _printing_to_card_def(_PRINTINGS["Lotus Field"]),
    )


@_rust_skip
def test_cross_engine_loader_admit_lotus_field_sac_two_parity():
    """**Composite loader-admit real-EoE probe -- SAC-TWO.** The ETB
    ``SacrificeNLandsYouControl(count=2)`` fires from the LOADER-BUILT
    Lotus Field printing's ``triggered_abilities`` on Rust (queued at
    inject, resolved via ``process_stack_until_empty``); the real parsed
    Lotus Field resolves the same ETB on Python. Both sacrifice exactly
    2 non-source lands; source + 1 plain land survive. Byte-equal on the
    land split.
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
    assert py_split == (1, 2)

    # ---- Rust: loader-built Lotus Field + 3 plain lands; the ETB sac
    # is queued at inject and resolved by draining the stack.
    rd = _rust_lotus_field_registry_dict()
    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    for _ in range(3):
        rs.register_and_inject_object(_RUST_PLAIN_LAND, 0, ZONE_BATTLEFIELD)
    rs_src = rs.register_and_inject_object(rd, 0, ZONE_BATTLEFIELD)
    rs.process_stack_until_empty()
    rs_non_source_lands = sum(
        1
        for o in rs.battlefield_snapshot()
        if o["controller_id"] == 0 and o["id"] != rs_src
    )
    rs_split = (rs_non_source_lands, len(rs.graveyard_snapshot(0)))
    assert rs_split == (1, 2)

    # ---- Cross-engine byte-equal + source survives on both.
    assert py_split == rs_split, (
        f"Cross-engine byte-equal (loader-admit SAC-TWO land split): "
        f"py={py_split}, rs={rs_split}"
    )
    assert source in py.battlefield
    assert any(o["id"] == rs_src for o in rs.battlefield_snapshot())


@_rust_skip
def test_cross_engine_loader_admit_lotus_field_sac_under_count_parity():
    """**Composite loader-admit real-EoE probe -- SAC-UNDER.** Only 1
    non-source land present but ``count=2``; the loader-built printing's
    ETB sac (Rust) and the real parsed ETB sac (Python) both sacrifice
    the 1 available and stop. Byte-equal on the land split.
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

    rd = _rust_lotus_field_registry_dict()
    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    rs.register_and_inject_object(_RUST_PLAIN_LAND, 0, ZONE_BATTLEFIELD)
    rs_src = rs.register_and_inject_object(rd, 0, ZONE_BATTLEFIELD)
    rs.process_stack_until_empty()
    rs_non_source_lands = sum(
        1
        for o in rs.battlefield_snapshot()
        if o["controller_id"] == 0 and o["id"] != rs_src
    )
    rs_split = (rs_non_source_lands, len(rs.graveyard_snapshot(0)))
    assert rs_split == (0, 1)
    assert py_split == rs_split


@_rust_skip
def test_cross_engine_loader_admit_lotus_field_mint_three_parity():
    """**Composite loader-admit real-EoE probe -- MINT-3.** The
    ``{T}: AddNManaOfChosenColor(3, WUBRG)`` mana AA mints 3 W coins
    (options[0] no-agent fallback) from the LOADER-BUILT Lotus Field
    printing's ``activated_abilities`` on Rust; the real parsed Lotus
    Field mints the same on Python. Byte-equal on the mana pool.

    The Rust source's ETB sac (no other lands -> no-op) is drained
    first; the mana pool is then emptied so only the AA mint is
    observed.
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
    assert py_pool == expected

    # ---- Rust: loader-built Lotus Field; drain ETB (no-op, no other
    # lands), empty the pool, then activate the mana AA (index 0).
    rd = _rust_lotus_field_registry_dict()
    rs = mtg_bot_engine.make_synthetic_state(0, 0, 0)
    rs_src = rs.register_and_inject_object(rd, 0, ZONE_BATTLEFIELD)
    rs.process_stack_until_empty()
    rs.empty_all_mana_pools()
    rs.force_set_summoning_sick(rs_src, False)
    assert rs.printing_aa_count_of(rs_src) == 1
    rs.apply_action({
        "kind": "activate_ability",
        "source_id": rs_src,
        "ability_index": 0,
    })
    rs_pool = rs.mana_pool_snapshot(0)
    assert rs_pool == expected
    assert py_pool == rs_pool, (
        f"Cross-engine byte-equal (loader-admit 3-W-coin mint): "
        f"py={py_pool}, rs={rs_pool}"
    )
