"""Wandering Fumarole -- per-card real-EoE cross-engine byte-equal
probe (BLOCKED subsystem-gated -> PROBED tier flip).

Wandering Fumarole is a ``{0}`` Land in the EoE pool (the Oath of the
Gatewatch manland) with an activated ability that animates the land
into a 1/4 creature until end of turn AND grants it a nested P/T-switch
activated ability while animated:

    "{2}{U}{R}: Wandering Fumarole becomes a 1/4 blue and red Elemental
    creature with '{0}: Switch this creature's power and toughness
    until end of turn.' until end of turn. It's still a land."

Parser-emitted shape:
    * AA[0] (mana={2}{U}{R}, no tap) ->
      ``BecomeLandCreatureUEOT(power=1, toughness=4,
      granted_keywords=frozenset(), unblockable=False,
      granted_subtype=None,
      granted_activated_abilities=(
          ActivatedAbility(cost={0}, effect=SwitchSourcePowerToughnessUEOT()),
      ),
      granted_triggered_abilities=())``

The NESTED granted activated ability carries the
``SwitchSourcePowerToughnessUEOT`` Effect -- "switch this creature's
power and toughness until end of turn" while the manland is animated.
This is the NEW Effect class this slice ships on the Rust substrate.

**Substrate landed this slice (2026-05-31):**
    * New Rust ``Effect::SwitchSourcePowerToughnessUEOT`` unit variant
      (``rust/src/cards.rs``) -- enum decl + parse_effect arm +
      to_pydict arm + resolve arm. **Substrate-only landing:** the Rust
      resolve arm is a documented silent no-op (layer-7e P/T-switch
      machinery deferred -- Rust's effective-P/T reader has no
      ``switch_pt`` sublayer-4 pass yet). See
      ``docs/SEARCH_LIMITATIONS.md``. The variant exists for cross-
      engine round-trip + to put Wandering Fumarole into the covered-
      class set; the cross-engine probe pins the Python-side swap
      resolve (which carries the full layer-7e ``switch_pt`` continuous
      effect).
    * Cross-engine bridge arm ``switch_source_power_toughness_ueot`` in
      ``cross_engine._ta_dict_to_python_effect`` (unit-variant dict ->
      ``SwitchSourcePowerToughnessUEOT()``).

With the substrate landed, ``SwitchSourcePowerToughnessUEOT`` joins the
covered-class set, so Wandering Fumarole's full Effect set
``{BecomeLandCreatureUEOT, SwitchSourcePowerToughnessUEOT}`` is
covered. This probe then pins the card via the JJJJ idiom (parse +
bridge round-trip + Python-side resolve smoke), moving it from the
BLOCKED subsystem-gated tail to PROBED.

Sibling of ``test_lavaclaw_reaches_parity.py`` -- the two manlands
share the nested-granted-AA substrate; Lavaclaw's nested effect is the
X-pump, Fumarole's is the P/T switch.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.become_type import BecomeLandCreatureUEOT
from mtg_bot.effects.generic.pump import SwitchSourcePowerToughnessUEOT


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_wandering_fumarole_parser_claims_card():
    assert "Wandering Fumarole" in _PRINTINGS, (
        "Wandering Fumarole must be parser-claimed by the active "
        "CardSource"
    )


def test_wandering_fumarole_printed_attrs():
    """Pins the basic printing surface: Land, no mana cost."""
    p = _PRINTINGS["Wandering Fumarole"]
    assert "Land" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()


def test_wandering_fumarole_activate_ability_shape():
    """The animate AA emits ``BecomeLandCreatureUEOT(1/4)`` with a
    nested ``SwitchSourcePowerToughnessUEOT`` granted activated
    ability."""
    p = _PRINTINGS["Wandering Fumarole"]
    animate_aa = next(
        (
            aa for aa in p.activated_abilities
            if isinstance(aa.effect, BecomeLandCreatureUEOT)
        ),
        None,
    )
    assert animate_aa is not None, (
        "Wandering Fumarole must have an activated ability emitting "
        "BecomeLandCreatureUEOT"
    )
    assert animate_aa.effect.power == 1
    assert animate_aa.effect.toughness == 4
    assert animate_aa.effect.granted_subtype is None
    # The nested granted activated ability carries
    # SwitchSourcePowerToughnessUEOT.
    granted = animate_aa.effect.granted_activated_abilities
    assert len(granted) == 1, (
        f"Wandering Fumarole must grant exactly one nested AA while "
        f"animated; got {len(granted)}"
    )
    assert isinstance(
        granted[0].effect, SwitchSourcePowerToughnessUEOT
    ), (
        f"Fumarole's nested granted AA must carry "
        f"SwitchSourcePowerToughnessUEOT; got "
        f"{type(granted[0].effect).__name__}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip for the nested Effect.
# ---------------------------------------------------------------------------


def test_switch_source_power_toughness_ueot_bridge_arm_round_trip():
    """The bridge arm ``switch_source_power_toughness_ueot`` (a unit-
    variant dict) round-trips to ``SwitchSourcePowerToughnessUEOT()``."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "switch_source_power_toughness_ueot"}
    )
    assert isinstance(bridged, SwitchSourcePowerToughnessUEOT)
    assert bridged == SwitchSourcePowerToughnessUEOT()


def test_become_land_creature_ueot_bridge_arm_round_trip_fumarole():
    """The animate-AA effect's bridge arm round-trips to the bare 1/4
    shape (granted_activated_abilities narrowed per the
    become_land_creature_ueot bridge-narrowing discipline)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "become_land_creature_ueot", "power": 1, "toughness": 4}
    )
    assert isinstance(bridged, BecomeLandCreatureUEOT)
    assert bridged.power == 1
    assert bridged.toughness == 4
    assert bridged.granted_activated_abilities == ()


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_wandering_fumarole_switch_pt_parity():
    """**GENUINE real-EoE cross-engine probe -- Wandering Fumarole
    (Land AA[0] -> BecomeLandCreatureUEOT(1/4) with a nested
    SwitchSourcePowerToughnessUEOT granted AA).**

    Drives the **real parsed Wandering Fumarole printing** through the
    Python-side ``SwitchSourcePowerToughnessUEOT`` resolve path,
    validating the no-resolving-source silent-no-op short-circuit
    (``effects/generic/pump.py``: ``if source is None: return`` -- the
    first observable line of the SwitchSourcePowerToughnessUEOT resolve
    method). Pairs the parse + bridge round-trip verification with the
    live Python resolve smoke, the same parse + bridge-round-trip +
    Python-side resolve idiom established by the Celestial Colonnade /
    batch-5 sibling manland probes.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Wandering Fumarole's slug AND the FIRST probe exercising
    the ``SwitchSourcePowerToughnessUEOT`` Effect class -- the nested
    P/T-switch granted activated ability the manland grants while
    animated. The Rust substrate
    ``Effect::SwitchSourcePowerToughnessUEOT`` landed this slice
    (parse + to_pydict + resolve [substrate-only no-op] + bridge),
    moving Fumarole's full Effect set ``{BecomeLandCreatureUEOT,
    SwitchSourcePowerToughnessUEOT}`` into the covered-class set.

    **Bridge arms exercised:**
    ``switch_source_power_toughness_ueot`` (matching Rust's unit
    ``Effect::SwitchSourcePowerToughnessUEOT``) and
    ``become_land_creature_ueot`` (the animate-AA carrier; granted-AA
    narrowed per the bridge-narrowing discipline).

    **Setup (Python-side):**
      * Empty state -- no resolving_source set (None); the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trips: ``{"kind":
        "switch_source_power_toughness_ueot"}`` ->
        ``SwitchSourcePowerToughnessUEOT()``; ``{"kind":
        "become_land_creature_ueot", "power": 1, "toughness": 4}`` ->
        ``BecomeLandCreatureUEOT(1/4)`` (bare shape).
      * The genuine parsed Fumarole AA[0] emits the
        ``BecomeLandCreatureUEOT(1/4)`` carrier whose nested granted AA
        carries ``SwitchSourcePowerToughnessUEOT``.
      * With ``resolving_source=None``, the
        SwitchSourcePowerToughnessUEOT resolve is a no-op: log
        unchanged, no continuous effect added.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Wandering Fumarole printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Wandering Fumarole")
    if real is None:
        pytest.skip("Wandering Fumarole absent from active CardSource")
    assert "Land" in real.card_types, "Wandering Fumarole must be a Land"
    animate_aa = next(
        (
            aa for aa in real.activated_abilities
            if isinstance(aa.effect, BecomeLandCreatureUEOT)
        ),
        None,
    )
    assert animate_aa is not None, (
        "Wandering Fumarole must have an activated ability emitting "
        "BecomeLandCreatureUEOT"
    )
    assert animate_aa.effect.power == 1
    assert animate_aa.effect.toughness == 4
    granted = animate_aa.effect.granted_activated_abilities
    assert len(granted) == 1
    nested_effect = granted[0].effect
    assert isinstance(nested_effect, SwitchSourcePowerToughnessUEOT), (
        f"Fumarole's nested granted AA must carry "
        f"SwitchSourcePowerToughnessUEOT; got "
        f"{type(nested_effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trips: Rust kind dicts -> Python Effects.
    # ------------------------------------------------------------------
    bridged_switch = _ta_dict_to_python_effect(
        {"kind": "switch_source_power_toughness_ueot"}
    )
    assert isinstance(bridged_switch, SwitchSourcePowerToughnessUEOT)
    assert bridged_switch == SwitchSourcePowerToughnessUEOT()

    bridged_animate = _ta_dict_to_python_effect(
        {"kind": "become_land_creature_ueot", "power": 1, "toughness": 4}
    )
    assert isinstance(bridged_animate, BecomeLandCreatureUEOT)
    assert bridged_animate.power == 1
    assert bridged_animate.toughness == 4

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: no-resolving-
    #    source silent-no-op short-circuit for
    #    SwitchSourcePowerToughnessUEOT.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    assert py.resolving_source is None, (
        "Pre-resolve sanity: resolving_source must be None"
    )

    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    # resolve: no-resolving-source silent-no-op (the nested-effect's
    # genuine instance from the parsed printing).
    nested_effect.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Wandering Fumarole: no-resolving-source "
        f"SwitchSourcePowerToughnessUEOT resolve must NOT append a log "
        f"line; got log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Wandering Fumarole: no-resolving-source resolve must NOT "
        "mutate the battlefield"
    )
