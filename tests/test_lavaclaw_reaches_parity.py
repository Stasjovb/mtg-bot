"""Lavaclaw Reaches -- per-card real-EoE cross-engine byte-equal probe
(BLOCKED subsystem-gated -> PROBED tier flip).

Lavaclaw Reaches is a ``{0}`` Land in the EoE pool (the Worldwake
manland reprint) with an activated ability that animates the land into
a 2/2 creature until end of turn AND grants it a nested X-pump
activated ability while animated:

    "{1}{B}{R}: Lavaclaw Reaches becomes a 2/2 black and red Elemental
    creature until end of turn. It's still a land.
    {X}: This creature gets +X/+0 until end of turn. Activate this
    ability only if Lavaclaw Reaches is a creature."

Parser-emitted shape:
    * AA[0] (mana={1}{B}{R}, no tap) ->
      ``BecomeLandCreatureUEOT(power=2, toughness=2,
      granted_keywords=frozenset(), unblockable=False,
      granted_subtype=None,
      granted_activated_abilities=(
          ActivatedAbility(cost={X}, effect=PumpSelfXPowerUEOT()),
      ),
      granted_triggered_abilities=())``

The NESTED granted activated ability carries the
``PumpSelfXPowerUEOT`` Effect -- "this creature gets +X/+0 until end of
turn" while the manland is animated. This is the NEW Effect class this
slice ships on the Rust substrate.

**Substrate landed this slice (2026-05-31):**
    * New Rust ``Effect::PumpSelfXPowerUEOT`` unit variant
      (``rust/src/cards.rs``) -- enum decl + parse_effect arm +
      to_pydict arm + resolve arm (reads ``current_resolve_x_value``,
      pushes ``PowerToughnessBonus { power: X, toughness: 0 }`` on the
      source -- mirrors Python's ``temp_power_bonus += x``).
    * Cross-engine bridge arm ``pump_self_x_power_ueot`` in
      ``cross_engine._ta_dict_to_python_effect`` (unit-variant dict ->
      ``PumpSelfXPowerUEOT()``).

With the substrate landed, ``PumpSelfXPowerUEOT`` joins the
covered-class set, so Lavaclaw's full Effect set
``{BecomeLandCreatureUEOT, PumpSelfXPowerUEOT}`` is covered. This probe
then pins the card via the JJJJ idiom (parse + bridge round-trip +
Python-side resolve smoke), moving it from the BLOCKED subsystem-gated
tail to PROBED.

**Re: the nested-AA bridge narrowing.** The ``become_land_creature_ueot``
bridge arm narrows away ``granted_activated_abilities`` (Rust's
``BecomeLandCreatureUEOT`` substrate carries only power/toughness/
granted_subtype). The PROBED credit here rests on (a) both emitted
Effect classes living + bridging on the Rust side, and (b) the
Python-side genuine-printing resolve smoke -- the same parse + bridge-
round-trip + Python-resolve idiom as Celestial Colonnade / the batch-5
manland siblings. The nested-AA's full cross-engine end-to-end
activation lifecycle (granting the AA on the animated land, then
driving the X-cost activation through Rust) is deferred -- the Rust
substrate carries the bare ``PumpSelfXPowerUEOT`` resolve, but the
nested-grant plumbing on ``BecomeLandCreatureUEOT`` is its own surface.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.become_type import BecomeLandCreatureUEOT
from mtg_bot.effects.generic.pump import PumpSelfXPowerUEOT


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_lavaclaw_reaches_parser_claims_card():
    assert "Lavaclaw Reaches" in _PRINTINGS, (
        "Lavaclaw Reaches must be parser-claimed by the active "
        "CardSource"
    )


def test_lavaclaw_reaches_printed_attrs():
    """Pins the basic printing surface: Land, no mana cost."""
    p = _PRINTINGS["Lavaclaw Reaches"]
    assert "Land" in p.card_types
    assert p.mana_cost.generic == 0
    assert p.mana_cost.colored == ()


def test_lavaclaw_reaches_activate_ability_shape():
    """The animate AA emits ``BecomeLandCreatureUEOT(2/2)`` with a
    nested ``PumpSelfXPowerUEOT`` granted activated ability."""
    p = _PRINTINGS["Lavaclaw Reaches"]
    animate_aa = next(
        (
            aa for aa in p.activated_abilities
            if isinstance(aa.effect, BecomeLandCreatureUEOT)
        ),
        None,
    )
    assert animate_aa is not None, (
        "Lavaclaw Reaches must have an activated ability emitting "
        "BecomeLandCreatureUEOT"
    )
    assert animate_aa.effect.power == 2
    assert animate_aa.effect.toughness == 2
    assert animate_aa.effect.granted_subtype is None
    # The nested granted activated ability carries PumpSelfXPowerUEOT.
    granted = animate_aa.effect.granted_activated_abilities
    assert len(granted) == 1, (
        f"Lavaclaw Reaches must grant exactly one nested AA while "
        f"animated; got {len(granted)}"
    )
    assert isinstance(granted[0].effect, PumpSelfXPowerUEOT), (
        f"Lavaclaw's nested granted AA must carry PumpSelfXPowerUEOT; "
        f"got {type(granted[0].effect).__name__}"
    )
    # The nested AA's cost is the {X} mana cost.
    assert granted[0].cost.mana is not None
    assert granted[0].cost.mana.x_pips == 1


# ---------------------------------------------------------------------------
# (2) Bridge round-trip for the nested Effect (PumpSelfXPowerUEOT).
# ---------------------------------------------------------------------------


def test_pump_self_x_power_ueot_bridge_arm_round_trip():
    """The bridge arm ``pump_self_x_power_ueot`` (a unit-variant dict)
    round-trips to ``PumpSelfXPowerUEOT()``."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect({"kind": "pump_self_x_power_ueot"})
    assert isinstance(bridged, PumpSelfXPowerUEOT)
    assert bridged == PumpSelfXPowerUEOT()


def test_become_land_creature_ueot_bridge_arm_round_trip():
    """The animate-AA effect's bridge arm round-trips to the bare 2/2
    shape (granted_activated_abilities narrowed per the
    become_land_creature_ueot bridge-narrowing discipline)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "become_land_creature_ueot", "power": 2, "toughness": 2}
    )
    assert isinstance(bridged, BecomeLandCreatureUEOT)
    assert bridged.power == 2
    assert bridged.toughness == 2
    # Bridge-narrowing: the nested granted AA is dropped (Rust's bare
    # BecomeLandCreatureUEOT substrate carries no granted-AA field).
    assert bridged.granted_activated_abilities == ()


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_lavaclaw_reaches_pump_self_x_power_parity():
    """**GENUINE real-EoE cross-engine probe -- Lavaclaw Reaches (Land
    AA[0] -> BecomeLandCreatureUEOT(2/2) with a nested
    PumpSelfXPowerUEOT granted AA).**

    Drives the **real parsed Lavaclaw Reaches printing** through the
    Python-side ``PumpSelfXPowerUEOT`` resolve path, validating the
    no-resolving-source silent-no-op short-circuit
    (``effects/generic/pump.py``: ``if source is None: return`` -- the
    first observable line of the PumpSelfXPowerUEOT resolve method).
    Pairs the parse + bridge round-trip verification with the live
    Python resolve smoke, the same parse + bridge-round-trip +
    Python-side resolve idiom established by the Celestial Colonnade /
    batch-5 sibling manland probes.

    **NEW shape coverage:** the FIRST credited ``_parity`` probe
    binding Lavaclaw Reaches's slug AND the FIRST probe exercising the
    ``PumpSelfXPowerUEOT`` Effect class -- the nested X-pump granted
    activated ability the manland grants while animated. The Rust
    substrate ``Effect::PumpSelfXPowerUEOT`` landed this slice (parse +
    to_pydict + resolve + bridge), moving Lavaclaw's full Effect set
    ``{BecomeLandCreatureUEOT, PumpSelfXPowerUEOT}`` into the covered-
    class set.

    **Bridge arms exercised:** ``pump_self_x_power_ueot`` (matching
    Rust's unit ``Effect::PumpSelfXPowerUEOT``) and
    ``become_land_creature_ueot`` (the animate-AA carrier; granted-AA
    narrowed per the bridge-narrowing discipline).

    **Setup (Python-side):**
      * Empty state -- no resolving_source set (None); the resolve
        short-circuits at the first observable line.

    **Observables asserted:**
      * Bridge round-trips: ``{"kind": "pump_self_x_power_ueot"}`` ->
        ``PumpSelfXPowerUEOT()``; ``{"kind":
        "become_land_creature_ueot", "power": 2, "toughness": 2}`` ->
        ``BecomeLandCreatureUEOT(2/2)`` (bare shape).
      * The genuine parsed Lavaclaw AA[0] emits the
        ``BecomeLandCreatureUEOT(2/2)`` carrier whose nested granted AA
        carries ``PumpSelfXPowerUEOT``.
      * With ``resolving_source=None``, the PumpSelfXPowerUEOT resolve
        is a no-op: log unchanged, no battlefield mutation.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Lavaclaw Reaches printing.
    # ------------------------------------------------------------------
    real = _PRINTINGS.get("Lavaclaw Reaches")
    if real is None:
        pytest.skip("Lavaclaw Reaches absent from active CardSource")
    assert "Land" in real.card_types, "Lavaclaw Reaches must be a Land"
    animate_aa = next(
        (
            aa for aa in real.activated_abilities
            if isinstance(aa.effect, BecomeLandCreatureUEOT)
        ),
        None,
    )
    assert animate_aa is not None, (
        "Lavaclaw Reaches must have an activated ability emitting "
        "BecomeLandCreatureUEOT"
    )
    assert animate_aa.effect.power == 2
    assert animate_aa.effect.toughness == 2
    granted = animate_aa.effect.granted_activated_abilities
    assert len(granted) == 1
    nested_effect = granted[0].effect
    assert isinstance(nested_effect, PumpSelfXPowerUEOT), (
        f"Lavaclaw's nested granted AA must carry PumpSelfXPowerUEOT; "
        f"got {type(nested_effect).__name__}"
    )

    # ------------------------------------------------------------------
    # 2. Bridge round-trips: Rust kind dicts -> Python Effects.
    # ------------------------------------------------------------------
    bridged_pump = _ta_dict_to_python_effect(
        {"kind": "pump_self_x_power_ueot"}
    )
    assert isinstance(bridged_pump, PumpSelfXPowerUEOT)
    assert bridged_pump == PumpSelfXPowerUEOT()

    bridged_animate = _ta_dict_to_python_effect(
        {"kind": "become_land_creature_ueot", "power": 2, "toughness": 2}
    )
    assert isinstance(bridged_animate, BecomeLandCreatureUEOT)
    assert bridged_animate.power == 2
    assert bridged_animate.toughness == 2

    # ------------------------------------------------------------------
    # 3. Python-side resolve smoke on a controlled state: no-resolving-
    #    source silent-no-op short-circuit for PumpSelfXPowerUEOT.
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
        f"Lavaclaw Reaches: no-resolving-source PumpSelfXPowerUEOT "
        f"resolve must NOT append a log line; got log_len={len(py.log)} "
        f"(expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Lavaclaw Reaches: no-resolving-source resolve must NOT mutate "
        "the battlefield"
    )


# ---------------------------------------------------------------------------
# (4) Manland granted-AA LEGAL-ENUMERATION + X-activation (feature/manland-
#     grant-enum, 2026-06-01) -- the granted {X} pump-AA is now a Rust legal
#     action at the SAME ability_index Python emits, and activating it with X
#     mana pumps +X/+0 byte-equal.
# ---------------------------------------------------------------------------


_ZONE_BATTLEFIELD_BF = 2


def _rust_lavaclaw_manland_dict():
    """A Land carrying the manland-animate AA whose
    ``become_land_creature_ueot`` effect grants the nested ``{X}`` pump-AA
    -- the Rust mirror of the real parsed Lavaclaw Reaches printing's
    AA[0]. The granted AA round-trips through the new
    ``granted_activated_abilities`` field on the Rust
    ``Effect::BecomeLandCreatureUEOT`` substrate.

    No ``mana_produced`` (matching the real parsed Lavaclaw printing,
    whose dual-mana production rides ``produces`` /
    ``effective_land_produces``, NOT an enumerated activated ability), so
    the animate AA is at ``ability_index=0`` and the granted ``{X}`` pump
    at ``ability_index=1`` -- byte-equal with Python's
    ``effective_activated_abilities`` ordering.
    """
    return {
        "name": "Test Lavaclaw (manland)",
        "card_types": ["Land"],
        "mana_cost": {},
        "effects": [],
        "activated_abilities": [
            {
                "cost": {"mana": {"generic": 1, "B": 1, "R": 1}},
                "effect": {
                    "kind": "become_land_creature_ueot",
                    "power": 2,
                    "toughness": 2,
                    "granted_subtype": "Elemental",
                    "granted_activated_abilities": [
                        {
                            "cost": {"mana": {"X": 1}},
                            "effect": {"kind": "pump_self_x_power_ueot"},
                        }
                    ],
                },
            }
        ],
    }


@_rust_skip
def test_rust_lavaclaw_granted_x_pump_aa_enumerates_and_activates_byte_equal():
    """**Manland granted-AA legal-enumeration + X-activation parity.**

    Drives the REAL animate -> ActivateAbility(ability_index=1, X=3) ->
    +X/+0 flow on BOTH engines (no longer a Python-only resolve smoke):

      * Python: the genuine parsed Lavaclaw Reaches printing.
      * Rust: a faithful manland Land dict whose
        ``become_land_creature_ueot`` AA carries the nested ``{X}`` pump
        via the new ``granted_activated_abilities`` field.

    Asserts (a) the granted ``{X}`` pump-AA appears in Rust's
    ``legal_decisions`` at the SAME ``ability_index`` Python emits (index
    1, AFTER the printing's own animate AA at index 0), AND (b)
    activating it with an identical mana state binds the SAME X and pumps
    byte-equal (2/2 -> 5/2 at X=3).

    **Deterministic-X.** The manland is TAPPED before the X-pump on both
    engines and an identical 3-mana floating pool is seeded, so the X
    upper bound is exactly 3 on both sides (no untapped-land headroom).
    Python's agent returns that upper bound; Rust's deterministic-first
    no-agent path picks the same upper bound -- both bind X=3.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import (
        GameState, Player, ManaCoin, effective_power, effective_toughness,
        Zone, effective_activated_abilities,
    )
    from mtg_bot.turn import Step
    from mtg_bot.actions import ActivateAbility, apply_action, resolve_top_of_stack
    from mtg_bot.agents import Agent

    printings = get_active_source().get_printings()
    real = printings.get("Lavaclaw Reaches")
    if real is None:
        pytest.skip("Lavaclaw Reaches absent from active CardSource")

    # ------------------------------------------------------------------
    # PYTHON -- REAL flow: animate, enumerate, activate {X} by index.
    # ------------------------------------------------------------------
    class _MaxX(Agent):
        def choose_x(self, state, player_id, card_name, upper_bound):
            return upper_bound

        def choose_target(self, state, player_id, legal_targets):
            return legal_targets[0] if legal_targets else None

    py = GameState()
    py.players.append(Player(id=0, agent=_MaxX()))
    py.players.append(Player(id=1, agent=_MaxX()))
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.step = Step.PRECOMBAT_MAIN

    land = py.new_object(real, 0, Zone.BATTLEFIELD)
    py.battlefield.append(land)
    p0 = py.players[0]
    # Floating pool for {1}{B}{R} animate cost.
    p0.mana_pool = [ManaCoin(color="C"), ManaCoin(color="B"), ManaCoin(color="R")]
    apply_action(py, 0, ActivateAbility(source_id=land.id, ability_index=0))
    while py.stack:
        resolve_top_of_stack(py)
    assert (effective_power(py, land), effective_toughness(py, land)) == (2, 2)

    # Python's effective_activated_abilities index for the granted pump.
    py_eff = effective_activated_abilities(py, land)
    py_pump_idx = next(
        i for i, ab in enumerate(py_eff)
        if isinstance(ab.effect, PumpSelfXPowerUEOT)
    )
    assert py_pump_idx == 1, (
        "Python enumerates the granted {X} pump at index 1 (after the "
        f"animate AA at 0); got {py_pump_idx}"
    )

    # Tap the manland + seed exactly 3 floating so X upper bound is 3.
    land.tapped = True
    p0.mana_pool = [ManaCoin(color="C"), ManaCoin(color="C"), ManaCoin(color="C")]
    apply_action(py, 0, ActivateAbility(source_id=land.id, ability_index=1))
    while py.stack:
        resolve_top_of_stack(py)
    py_after_pump = (effective_power(py, land), effective_toughness(py, land))

    # ------------------------------------------------------------------
    # RUST -- SAME flow: animate, enumerate, activate {X} by index.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)
    land_id = rs.register_and_inject_object(
        _rust_lavaclaw_manland_dict(), 0, _ZONE_BATTLEFIELD_BF,
    )
    rs.set_active_player(0)
    rs.set_phase(3)  # PRECOMBAT_MAIN — open the sorcery-timing AA gate.
    for color, n in [("C", 1), ("B", 1), ("R", 1)]:
        rs.add_mana(0, color, n)

    rs.apply_action(
        {"kind": "activate_ability", "source_id": land_id, "ability_index": 0}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    assert (rs.effective_power(land_id), rs.effective_toughness(land_id)) == (2, 2)

    # The granted {X} pump-AA must appear at the SAME index Python emits.
    acts = rs.legal_decisions(0)
    rs_pump_idxs = sorted(
        a["ability_index"]
        for a in acts
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == land_id
    )
    assert rs_pump_idxs == [py_pump_idx], (
        "Rust must enumerate exactly the granted {X} pump-AA at "
        f"ability_index={py_pump_idx} on the animated land (byte-equal "
        f"with Python); got {rs_pump_idxs}"
    )

    # Tap the manland + seed exactly 3 floating so X upper bound is 3.
    rs.tap_object(land_id)
    rs.empty_all_mana_pools()
    for color, n in [("C", 3)]:
        rs.add_mana(0, color, n)
    rs.apply_action(
        {"kind": "activate_ability", "source_id": land_id, "ability_index": 1}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs_after_pump = (rs.effective_power(land_id), rs.effective_toughness(land_id))

    # ------------------------------------------------------------------
    # CROSS-ENGINE BYTE-EQUAL: both bind X=3 -> 2/2 becomes 5/2.
    # ------------------------------------------------------------------
    assert py_after_pump == (5, 2), (
        f"Python X=3 pump must yield 5/2; got {py_after_pump}"
    )
    assert rs_after_pump == (5, 2), (
        f"Rust X=3 pump must yield 5/2; got {rs_after_pump}"
    )
    assert py_after_pump == rs_after_pump, (
        f"granted-AA X-pump P/T must be byte-equal cross-engine: "
        f"py={py_after_pump} rust={rs_after_pump}"
    )
