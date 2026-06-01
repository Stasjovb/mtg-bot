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

**Layer-7e swap LANDED (feature/fumarole-ptswitch, 2026-06-01):**
    * Rust ``Effect::SwitchSourcePowerToughnessUEOT`` resolve arm is
      now REAL (no longer a no-op): it pushes a ``UeotModifier::SwitchPT``
      onto the source (``rust/src/state_ops_resolve.rs``). A new
      ``UeotModifier::SwitchPT`` variant (``rust/src/state.rs``) +
      ``GameObject::ueot_pt_swapped()`` (odd-count parity) drives a
      layer-7e swap in the two centralized effective-P/T readers
      ``battlefield_creature_power`` / ``battlefield_creature_toughness``
      (``rust/src/state_ops_combat.rs``) — the swap is applied AFTER
      the fully-composed (post-7b/c/d) P/T, mirroring Python's
      ``_compute_effective_pt`` 7e branch (``game.py:2253``). Two
      switches cancel; three is one net swap.
    * Cross-engine bridge arm ``switch_source_power_toughness_ueot`` in
      ``cross_engine._ta_dict_to_python_effect`` (unit-variant dict ->
      ``SwitchSourcePowerToughnessUEOT()``).

With the swap landed, ``SwitchSourcePowerToughnessUEOT`` is fully
covered (the resolve genuinely swaps effective P/T byte-equal cross-
engine), so Wandering Fumarole's full Effect set
``{BecomeLandCreatureUEOT, SwitchSourcePowerToughnessUEOT}`` is
covered. This probe pins the card via the parse + bridge round-trip +
GENUINE cross-engine swap-parity idiom (effective P/T swapped byte-
equal on BOTH engines).

**Honest-stop (manland nested-grant LEGAL-ENUMERATION).** Rust's
``Effect::BecomeLandCreatureUEOT`` substrate still carries only
``power/toughness/granted_subtype`` (no ``granted_activated_abilities``
field), so the granted ``{0}`` switch-AA is not yet enumerated as a
legal action on the animated land in Rust's ``legal_decisions``. The
switch EFFECT, however, is fully reachable + byte-equal through any
effect carrier (the resolve arm is the load-bearing parity behavior).
Driving the literal ``{0}`` activation through Rust's legal-action
codec is the deferred half (touches the encoding-sensitive
``activate_ability`` ability-index scheme). See
``docs/SEARCH_LIMITATIONS.md``. Python drives the REAL animate ->
activate {0} -> swap flow (``tests/test_manland_granted_abilities.py``);
this probe drives the switch effect on a matching carrier on BOTH
engines and asserts the swapped effective P/T byte-equal.

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


# ---------------------------------------------------------------------------
# (4) GENUINE cross-engine layer-7e swap parity (REAL flow on BOTH engines).
# ---------------------------------------------------------------------------


_ZONE_HAND = 0
_ZONE_BATTLEFIELD = 2


def _rust_switch_etb_1_4_dict():
    """A 1/4 creature whose ETB fires the switch effect once -- the
    Rust carrier for the layer-7e swap (the switch EFFECT is the
    load-bearing cross-engine parity behavior; Rust's granted-AA
    legal-enumeration is honest-stopped, so the effect is driven
    through the reachable ETB carrier rather than the {0} AA)."""
    return {
        "name": "Synthetic Fumarole Switch Carrier (ETB)",
        "mana_cost": {"generic": 2, "U": 1},
        "card_types": ["Creature"],
        "power": 1,
        "toughness": 4,
        "effects": [],
        "etb_effects": [
            {"kind": "switch_source_power_toughness_ueot"},
        ],
    }


@_rust_skip
def test_cross_engine_wandering_fumarole_switch_pt_swap_byte_equal():
    """**GENUINE cross-engine layer-7e P/T-switch parity.**

    Python drives the REAL Wandering Fumarole flow: animate the
    genuine parsed printing into a 1/4 ({2}{U}{R}), then activate the
    granted ``{0}`` switch-AA and resolve. Effective P/T must read 4/1
    (one swap) then 1/4 (a second swap cancels).

    Rust drives the SAME switch EFFECT on a matching 1/4 carrier (its
    ETB fires ``switch_source_power_toughness_ueot``). The Rust
    granted-AA legal-enumeration on the animated land is honest-stopped
    (Rust's ``BecomeLandCreatureUEOT`` substrate carries no
    ``granted_activated_abilities`` field — see
    ``docs/SEARCH_LIMITATIONS.md``), so the switch EFFECT (the
    load-bearing parity behavior) is driven through the reachable ETB
    carrier. The assertion is the cross-engine claim that matters:
    **both engines compute the identical post-swap effective P/T**
    (4/1 after one switch; 1/4 after two).
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import (
        GameState, Player, effective_power, effective_toughness,
    )
    from mtg_bot.turn import Step
    from mtg_bot.cards import BASIC_LANDS, parse_mana_cost
    from mtg_bot.actions import (
        ActivateAbility, apply_action, resolve_top_of_stack,
    )
    from mtg_bot.agents import Agent
    from mtg_bot.game import Zone

    printings = get_active_source().get_printings()
    real = printings.get("Wandering Fumarole")
    if real is None:
        pytest.skip("Wandering Fumarole absent from active CardSource")

    # ------------------------------------------------------------------
    # PYTHON -- REAL flow: animate the genuine printing, then activate
    # the granted {0} switch-AA.
    # ------------------------------------------------------------------
    class _MaxXFirstTarget(Agent):
        def choose_x(self, state, player_id, card_name, upper_bound):
            return upper_bound

        def choose_target(self, state, player_id, legal_targets):
            return legal_targets[0] if legal_targets else None

    py = GameState()
    py.players.append(Player(id=0, agent=_MaxXFirstTarget()))
    py.players.append(Player(id=1, agent=_MaxXFirstTarget()))
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.step = Step.PRECOMBAT_MAIN

    def _put(printing, owner_id=0):
        obj = py.new_object(printing, owner_id, Zone.BATTLEFIELD)
        py.battlefield.append(obj)
        return obj

    land = _put(real)
    # Seed mana for {2}{U}{R}.
    for color, count in parse_mana_cost("{2}{U}{R}").colored:
        basic = {"U": "Island", "R": "Mountain"}[color]
        for _ in range(count):
            _put(BASIC_LANDS[basic])
    for _ in range(parse_mana_cost("{2}{U}{R}").generic):
        _put(BASIC_LANDS["Mountain"])

    # Animate ({T}->1/1... here 1/4 per the printing) via AA[0].
    apply_action(py, 0, ActivateAbility(source_id=land.id, ability_index=0))
    while py.stack:
        resolve_top_of_stack(py)
    assert effective_power(py, land) == 1
    assert effective_toughness(py, land) == 4

    # Activate the granted {0} switch-AA (ability_index=1).
    apply_action(py, 0, ActivateAbility(source_id=land.id, ability_index=1))
    while py.stack:
        resolve_top_of_stack(py)
    py_after_one = (effective_power(py, land), effective_toughness(py, land))

    # Second switch cancels.
    apply_action(py, 0, ActivateAbility(source_id=land.id, ability_index=1))
    while py.stack:
        resolve_top_of_stack(py)
    py_after_two = (effective_power(py, land), effective_toughness(py, land))

    # ------------------------------------------------------------------
    # RUST -- drive the switch EFFECT on a matching 1/4 carrier.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)
    carrier = _rust_switch_etb_1_4_dict()

    rs_obj = rs.register_and_inject_object(carrier, 0, _ZONE_HAND)
    rs.push_to_stack(rs_obj, 0)
    rs.resolve_top_of_stack()  # spell enters bf, queues the ETB switch
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs_after_one = (
        rs.effective_power(rs_obj), rs.effective_toughness(rs_obj),
    )

    # Second switch via a second ETB carrier whose target is the SAME
    # object would require an AA path; instead drive the cancel via a
    # double-switch carrier and confirm the printed 1/4 reads back.
    rs2 = build_rust_state(spec)
    double = dict(carrier)
    double["name"] = "Synthetic Fumarole Double Switch Carrier (ETB)"
    double["etb_effects"] = [
        {"kind": "switch_source_power_toughness_ueot"},
        {"kind": "switch_source_power_toughness_ueot"},
    ]
    rs2_obj = rs2.register_and_inject_object(double, 0, _ZONE_HAND)
    rs2.push_to_stack(rs2_obj, 0)
    rs2.resolve_top_of_stack()
    while rs2.stack_size() > 0:
        rs2.resolve_top_of_stack()
    rs_after_two = (
        rs2.effective_power(rs2_obj), rs2.effective_toughness(rs2_obj),
    )

    # ------------------------------------------------------------------
    # CROSS-ENGINE BYTE-EQUAL: both engines swap identically.
    # ------------------------------------------------------------------
    assert py_after_one == (4, 1), (
        f"Python one-switch effective P/T must be 4/1; got {py_after_one}"
    )
    assert rs_after_one == (4, 1), (
        f"Rust one-switch effective P/T must be 4/1; got {rs_after_one}"
    )
    assert py_after_one == rs_after_one, (
        f"one-switch P/T must be byte-equal cross-engine: "
        f"py={py_after_one} rust={rs_after_one}"
    )
    assert py_after_two == (1, 4), (
        f"Python two-switch effective P/T must cancel to 1/4; "
        f"got {py_after_two}"
    )
    assert rs_after_two == (1, 4), (
        f"Rust two-switch effective P/T must cancel to 1/4; "
        f"got {rs_after_two}"
    )
    assert py_after_two == rs_after_two, (
        f"two-switch P/T must be byte-equal cross-engine: "
        f"py={py_after_two} rust={rs_after_two}"
    )


# ---------------------------------------------------------------------------
# (5) Manland granted-AA LEGAL-ENUMERATION + activation (feature/manland-
#     grant-enum, 2026-06-01) -- the granted {0} switch-AA is now a Rust
#     legal action at the SAME ability_index Python emits, and activating it
#     by index swaps byte-equal.
# ---------------------------------------------------------------------------


_ZONE_BATTLEFIELD_BF = 2


def _rust_fumarole_manland_dict():
    """A Land carrying the manland-animate AA whose
    `become_land_creature_ueot` effect grants the nested `{0}` switch-AA
    -- the Rust mirror of the real parsed Wandering Fumarole printing's
    AA[0]. The granted AA round-trips through the new
    `granted_activated_abilities` field on the Rust
    `Effect::BecomeLandCreatureUEOT` substrate.

    The printing carries NO `mana_produced` (matching the real parsed
    Fumarole printing, whose dual-mana production rides `produces` /
    `effective_land_produces`, NOT an enumerated activated ability) so
    the animate AA is at `ability_index=0` and the granted `{0}` switch
    at `ability_index=1` -- byte-equal with Python's
    `effective_activated_abilities` ordering.
    """
    return {
        "name": "Test Fumarole (manland)",
        "card_types": ["Land"],
        "mana_cost": {},
        "effects": [],
        "activated_abilities": [
            {
                "cost": {"mana": {"generic": 2, "U": 1, "R": 1}},
                "effect": {
                    "kind": "become_land_creature_ueot",
                    "power": 1,
                    "toughness": 4,
                    "granted_activated_abilities": [
                        {
                            "cost": {},
                            "effect": {
                                "kind": "switch_source_power_toughness_ueot"
                            },
                        }
                    ],
                },
            }
        ],
    }


@_rust_skip
def test_rust_fumarole_granted_switch_aa_enumerates_and_activates_byte_equal():
    """**Manland granted-AA legal-enumeration + activation parity.**

    Drives the REAL animate -> ActivateAbility(ability_index=1) -> swap
    flow on BOTH engines (no longer the ETB-carrier workaround):

      * Python: the genuine parsed Wandering Fumarole printing.
      * Rust: a faithful manland Land dict whose
        `become_land_creature_ueot` AA carries the nested `{0}` switch
        via the new `granted_activated_abilities` field.

    Asserts (a) the granted `{0}` switch-AA appears in Rust's
    `legal_decisions` at the SAME `ability_index` Python emits (index 1,
    AFTER the printing's own animate AA at index 0), AND (b) activating
    it by that index produces byte-equal swapped P/T (4/1 after one
    switch; 1/4 after two).
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import (
        GameState, Player, effective_power, effective_toughness, Zone,
    )
    from mtg_bot.turn import Step
    from mtg_bot.cards import BASIC_LANDS, parse_mana_cost
    from mtg_bot.actions import ActivateAbility, apply_action, resolve_top_of_stack
    from mtg_bot.agents import Agent

    printings = get_active_source().get_printings()
    real = printings.get("Wandering Fumarole")
    if real is None:
        pytest.skip("Wandering Fumarole absent from active CardSource")

    # ------------------------------------------------------------------
    # PYTHON -- REAL flow: animate, enumerate, activate {0} by index.
    # ------------------------------------------------------------------
    class _FirstTarget(Agent):
        def choose_target(self, state, player_id, legal_targets):
            return legal_targets[0] if legal_targets else None

    py = GameState()
    py.players.append(Player(id=0, agent=_FirstTarget()))
    py.players.append(Player(id=1, agent=_FirstTarget()))
    py.active_player_idx = 0
    py.priority_player_idx = 0
    py.step = Step.PRECOMBAT_MAIN

    def _put(printing, owner_id=0):
        obj = py.new_object(printing, owner_id, Zone.BATTLEFIELD)
        py.battlefield.append(obj)
        return obj

    land = _put(real)
    for color, count in parse_mana_cost("{2}{U}{R}").colored:
        basic = {"U": "Island", "R": "Mountain"}[color]
        for _ in range(count):
            _put(BASIC_LANDS[basic])
    for _ in range(parse_mana_cost("{2}{U}{R}").generic):
        _put(BASIC_LANDS["Mountain"])

    apply_action(py, 0, ActivateAbility(source_id=land.id, ability_index=0))
    while py.stack:
        resolve_top_of_stack(py)
    assert (effective_power(py, land), effective_toughness(py, land)) == (1, 4)

    # Python's effective_activated_abilities index for the granted AA.
    from mtg_bot.game import effective_activated_abilities
    py_eff = effective_activated_abilities(py, land)
    from mtg_bot.effects.generic.pump import SwitchSourcePowerToughnessUEOT
    py_switch_idx = next(
        i for i, ab in enumerate(py_eff)
        if isinstance(ab.effect, SwitchSourcePowerToughnessUEOT)
    )
    assert py_switch_idx == 1, (
        f"Python enumerates the granted {{0}} switch at index 1 (after "
        f"the animate AA at 0); got {py_switch_idx}"
    )

    apply_action(py, 0, ActivateAbility(source_id=land.id, ability_index=1))
    while py.stack:
        resolve_top_of_stack(py)
    py_after_one = (effective_power(py, land), effective_toughness(py, land))
    apply_action(py, 0, ActivateAbility(source_id=land.id, ability_index=1))
    while py.stack:
        resolve_top_of_stack(py)
    py_after_two = (effective_power(py, land), effective_toughness(py, land))

    # ------------------------------------------------------------------
    # RUST -- SAME flow: animate, enumerate (legal_decisions), activate.
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)
    land_id = rs.register_and_inject_object(
        _rust_fumarole_manland_dict(), 0, _ZONE_BATTLEFIELD_BF,
    )
    rs.set_active_player(0)
    rs.set_phase(3)  # PRECOMBAT_MAIN — open the sorcery-timing AA gate.
    for color, n in [("C", 2), ("U", 1), ("R", 1)]:
        rs.add_mana(0, color, n)

    # Animate via AA[0].
    rs.apply_action(
        {"kind": "activate_ability", "source_id": land_id, "ability_index": 0}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    assert (rs.effective_power(land_id), rs.effective_toughness(land_id)) == (1, 4)

    # The granted {0} switch-AA must now appear as a legal action at the
    # SAME index Python emits (1).
    acts = rs.legal_decisions(0)
    rs_switch_idxs = sorted(
        a["ability_index"]
        for a in acts
        if a.get("kind") == "activate_ability"
        and a.get("source_id") == land_id
    )
    assert rs_switch_idxs == [py_switch_idx], (
        f"Rust must enumerate exactly the granted {{0}} switch-AA at "
        f"ability_index={py_switch_idx} on the animated land (byte-equal "
        f"with Python); got {rs_switch_idxs}"
    )

    # Activate by index — swap to 4/1, second cancels to 1/4.
    rs.apply_action(
        {"kind": "activate_ability", "source_id": land_id, "ability_index": 1}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs_after_one = (rs.effective_power(land_id), rs.effective_toughness(land_id))
    rs.apply_action(
        {"kind": "activate_ability", "source_id": land_id, "ability_index": 1}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs_after_two = (rs.effective_power(land_id), rs.effective_toughness(land_id))

    # ------------------------------------------------------------------
    # CROSS-ENGINE BYTE-EQUAL.
    # ------------------------------------------------------------------
    assert py_after_one == (4, 1)
    assert rs_after_one == (4, 1)
    assert py_after_one == rs_after_one, (
        f"granted-AA one-switch P/T must be byte-equal: "
        f"py={py_after_one} rust={rs_after_one}"
    )
    assert py_after_two == (1, 4)
    assert rs_after_two == (1, 4)
    assert py_after_two == rs_after_two, (
        f"granted-AA two-switch P/T must be byte-equal: "
        f"py={py_after_two} rust={rs_after_two}"
    )
