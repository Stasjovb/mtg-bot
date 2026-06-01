"""Secluded Starforge — FULL 3-AA cross-engine PROBE (PROBED-tier flip).

Secluded Starforge is a real EoE ``Land`` (``mana_cost == ""``) with
three printed activated abilities:

  1. ``{T}: Add {C}.``
  2. ``{2}, {T}, Tap X untapped artifacts you control: Target creature
     gets +X/+0 until end of turn. Activate only as a sorcery.``
  3. ``{5}, {T}: Create a 2/2 colorless Robot artifact creature token.``

**The flip (2026-05-31, ``feature/secluded-starforge-flip``).** A prior
worker characterized the card and HONEST-STOPPED at the substrate-map
level (the prior version of this module). This lane lands the full
substrate and flips the card BLOCKED-SG → PROBED:

  * **AA2 X-channel substrate (BOTH engines).** A new
    ``ActivationCost.tap_x_untapped_artifacts_you_control`` cost atom;
    the ``_activate_ability`` cost-payment (taps lowest-id-first X
    artifacts via the existing ``choose_x`` agent hook, stashing X onto
    ``StackItem.x_value`` → ``state.resolving_x_value``); a new
    ``PumpTargetCreatureUntilEOT.power_bonus_from_x`` flag (Python) +
    the mirrored Rust ``Effect::PumpTargetCreatureUntilEOT`` field
    (reads ``current_resolve_x_value``) + parse / to_pydict / bridge.
  * **Parser claim-ordering fix.** ``land_builder._try_build_colorless_
    utility_land`` now routes ALL printed lines through the
    activated-ability grammar (multi-line shape) instead of dropping
    the trailing AAs — the full faithful 3-AA printing. The static
    ``lands.py`` entry was upgraded to match byte-for-byte.

The genuine PROBED-tier evidence is
``test_cross_engine_real_eoe_secluded_starforge_pump_by_x_parity``: it
drives AA2's +X/+0 pump on BOTH engines (seat a target creature + X,
resolve, assert the target's effective power is byte-equal) PLUS AA1
(mana) and AA3 (Robot token) parser pins so the WHOLE 3-AA printing is
faithful.

This module IS registered in
``scripts/measure_pool_parity.PROBE_MODULES``.
"""

from __future__ import annotations

import pytest


def _starforge_card_record():
    """Return the raw Scryfall record for Secluded Starforge, or skip."""
    import json
    import os

    data_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data",
        "edge_of_eternities.json",
    )
    if not os.path.exists(data_path):
        pytest.skip("data/edge_of_eternities.json absent")
    with open(data_path, encoding="utf-8") as fh:
        data = json.load(fh)
    cards = data if isinstance(data, list) else data.get("cards", [])
    for c in cards:
        if isinstance(c, dict) and c.get("name") == "Secluded Starforge":
            return c
    pytest.skip("Secluded Starforge absent from edge_of_eternities.json")


# ---------------------------------------------------------------------------
# (1) Raw oracle text: the three printed activated abilities are present.
# ---------------------------------------------------------------------------


def test_secluded_starforge_raw_oracle_has_three_activated_abilities():
    """Freeze the raw printed surface: a plain ``Land`` with three
    activated-ability lines (mana / tap-X-artifacts pump / Robot token)."""
    rec = _starforge_card_record()
    assert rec.get("type_line") == "Land"
    oracle = rec.get("oracle_text", "")
    lines = [ln.strip() for ln in oracle.split("\n") if ln.strip()]
    assert len(lines) == 3
    assert lines[0] == "{T}: Add {C}."
    assert lines[1] == (
        "{2}, {T}, Tap X untapped artifacts you control: Target creature "
        "gets +X/+0 until end of turn. Activate only as a sorcery."
    )
    assert lines[2] == (
        "{5}, {T}: Create a 2/2 colorless Robot artifact creature token."
    )


# ---------------------------------------------------------------------------
# (2) AA1 (tap-for-C mana) parses through the live grammar.
# ---------------------------------------------------------------------------


def test_aa1_tap_for_colorless_parses_through_grammar():
    """AA1 ``{T}: Add {C}.`` is a recognized mana ability."""
    from mtg_bot.cards.base import AddManaToPool
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line

    ab = _parse_activated_ability_line("{T}: Add {C}.")
    assert ab is not None
    assert isinstance(ab.effect, AddManaToPool)
    assert ab.effect.produces == (("C", 1),)
    assert ab.is_mana_ability is True
    assert ab.cost.tap_self is True


# ---------------------------------------------------------------------------
# (3) AA2 (tap-X-artifacts → +X/+0) NOW parses (the substrate landed).
# ---------------------------------------------------------------------------


def test_aa2_tap_x_artifacts_pump_parses_through_grammar():
    """AA2's variable tap-X-artifacts cost + +X/+0 pump now parses: the
    cost atom ``Tap X untapped artifacts you control`` classifies and the
    ``Target creature gets +X/+0 until end of turn`` effect maps to
    ``PumpTargetCreatureUntilEOT(power_bonus_from_x=True)``. The
    ``Activate only as a sorcery.`` rider sets ``sorcery_speed=True``."""
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line

    ab = _parse_activated_ability_line(
        "{2}, {T}, Tap X untapped artifacts you control: Target creature "
        "gets +X/+0 until end of turn. Activate only as a sorcery."
    )
    assert ab is not None
    assert isinstance(ab.effect, PumpTargetCreatureUntilEOT)
    assert ab.effect.power_bonus_from_x is True
    assert ab.effect.toughness_bonus == 0
    # Cost: {2} mana + tap-self + tap-X-untapped-artifacts.
    assert ab.cost.mana is not None
    assert ab.cost.mana.generic == 2
    assert ab.cost.tap_self is True
    assert ab.cost.tap_x_untapped_artifacts_you_control is True
    assert ab.sorcery_speed is True


# ---------------------------------------------------------------------------
# (4) AA3 (Robot token) parses through the live grammar.
# ---------------------------------------------------------------------------


def test_aa3_robot_token_creation_parses_through_grammar():
    """AA3 ``{5}, {T}: Create a 2/2 colorless Robot artifact creature
    token.`` is fully recognized by the live grammar."""
    from mtg_bot.effects.generic import CreateToken
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line

    ab = _parse_activated_ability_line(
        "{5}, {T}: Create a 2/2 colorless Robot artifact creature token."
    )
    assert ab is not None
    assert isinstance(ab.effect, CreateToken)
    assert ab.effect.count == 1
    assert ab.effect.token_printing.power == 2
    assert ab.effect.token_printing.toughness == 2
    assert "Robot" in ab.effect.token_printing.subtypes
    assert ab.cost.tap_self is True
    assert ab.cost.mana is not None
    assert ab.cost.mana.generic == 5


# ---------------------------------------------------------------------------
# (5) The live whole-card printing is the FULL faithful 3-AA land.
# ---------------------------------------------------------------------------


def test_live_printing_is_full_three_aa_land():
    """The live parser now emits the FULL faithful printing: a colorless
    land that produces {C} and carries all three activated abilities. The
    static registry agrees byte-for-byte (parity gate requirement)."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.lands import UTILITY_LANDS

    p = get_active_source().get_printings().get("Secluded Starforge")
    if p is None:
        pytest.skip("Secluded Starforge absent from active CardSource")
    assert "Land" in p.card_types
    assert p.produces == frozenset({"C"})
    assert len(p.activated_abilities) == 3
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()
    # Parser source and static registry must agree.
    assert p == UTILITY_LANDS["Secluded Starforge"]


# ---------------------------------------------------------------------------
# (6) Rust resolve-arm pins (synthetic state — pump-by-X reads X).
# ---------------------------------------------------------------------------


def _build_rust_pump_x_state(*, x_value, bear_power=2, bear_tough=2):
    """Build a Rust state with a creature on p0's bf + a
    ``pump_target_creature_until_eot(power_bonus_from_x=True)`` ability
    on the stack with X seated. Returns ``(rs, bear_id)``."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    _ZB = 2
    bear_id = rs.register_and_inject_object(
        {
            "name": "Bear",
            "card_types": ["Creature"],
            "power": bear_power,
            "toughness": bear_tough,
        },
        0,
        _ZB,
    )
    spell_id = rs.register_and_inject_object(
        {
            "name": "Starforge AA2",
            "card_types": ["Land"],
            "effects": [
                {
                    "kind": "pump_target_creature_until_eot",
                    "power_bonus": 0,
                    "toughness_bonus": 0,
                    "power_bonus_from_x": True,
                }
            ],
        },
        0,
        0,
    )
    rs.push_to_stack(spell_id, 0)
    rs.set_stack_top_x_value(x_value)
    return rs, bear_id


def test_rust_pump_by_x_applies_x_power_bonus():
    """X=3 — the target creature gets +3/+0 (effective power 2 → 5)."""
    rs, bear = _build_rust_pump_x_state(x_value=3)
    assert rs.effective_power(bear) == 2
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0
    assert rs.effective_power(bear) == 5, "+X/+0 with X=3 → power 2+3=5"
    assert rs.effective_toughness(bear) == 2, "+X/+0 leaves toughness"


def test_rust_pump_by_x_zero_is_noop():
    """X=0 — +0/+0 is a silent no-op (power unchanged)."""
    rs, bear = _build_rust_pump_x_state(x_value=0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0
    assert rs.effective_power(bear) == 2, "X=0 → no pump"
    assert rs.effective_toughness(bear) == 2


def test_rust_pump_by_x_round_trips_flag():
    """The ``power_bonus_from_x`` flag round-trips through the dict→Python
    bridge (mirrors Rust parse / to_pydict)."""
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT

    d = {
        "kind": "pump_target_creature_until_eot",
        "power_bonus": 0,
        "toughness_bonus": 0,
        "power_bonus_from_x": True,
    }
    eff = _ta_dict_to_python_effect(d)
    assert isinstance(eff, PumpTargetCreatureUntilEOT)
    assert eff.power_bonus_from_x is True


# ---------------------------------------------------------------------------
# (7) GENUINE real-printing cross-engine PROBE (the PROBED-tier flip).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_secluded_starforge_pump_by_x_parity():
    """**GENUINE cross-engine probe — Secluded Starforge AA2 tap-X-
    artifacts +X/+0 pump. PROBED-tier flip.**

    Drives AA2's variable-X pump on BOTH engines with X seated on the
    StackItem (the established X-cost probe shape — GSZ / Zero Point
    Ballad seat X directly via ``set_stack_top_x_value`` / a Python
    ``StackItem(x_value=...)``; the cost-payment tap-X path that mints X
    is exercised separately by the Python ``_activate_ability`` unit
    tests below). A single 2/2 bear is the pump target on each engine,
    X=3, so the byte-equal observable is the bear's effective power
    2 → 5 (toughness unchanged at 2) on both engines.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.game import (
        StackItem, Zone, effective_power, effective_toughness,
    )

    # Verify-first: the real printing's AA2 is the X-pump.
    real = get_active_source().get_printings().get("Secluded Starforge")
    if real is None:
        pytest.skip("Secluded Starforge absent from active CardSource")
    aa2 = real.activated_abilities[1]
    assert isinstance(aa2.effect, PumpTargetCreatureUntilEOT)
    assert aa2.effect.power_bonus_from_x is True

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    _ZB = 2
    _X = 3

    # ---- Rust: seat a 2/2 bear, push the AA2 pump with X=3, resolve.
    rs_bear = rs.register_and_inject_object(
        {
            "name": "Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        0,
        _ZB,
    )
    rs_spell = rs.register_and_inject_object(
        {
            "name": "Secluded Starforge",
            "card_types": ["Land"],
            "effects": [
                {
                    "kind": "pump_target_creature_until_eot",
                    "power_bonus": 0,
                    "toughness_bonus": 0,
                    "power_bonus_from_x": True,
                }
            ],
        },
        0,
        0,
    )
    rs.push_to_stack(rs_spell, 0)
    rs.set_stack_top_x_value(_X)
    assert rs.effective_power(rs_bear) == 2
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0

    # ---- Python: seat a 2/2 bear, push the AA2 pump with x_value=3,
    # resolve. The source is the Starforge; targets is the bear.
    bear_printing = CardPrinting(
        name="Bear",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
    )
    py_bear = py.new_object(bear_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_bear.summoning_sick = False
    py_bear.tapped = False
    py_bear.damage = 0
    py_bear.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_bear)
    assert effective_power(py, py_bear) == 2

    starforge_printing = CardPrinting(
        name="Secluded Starforge",
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Land",
        supertypes=(),
        card_types=("Land",),
        subtypes=(),
        produces=frozenset({"C"}),
    )
    py_src = py.new_object(
        starforge_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py.battlefield.append(py_src)
    pump_ability = ActivatedAbility(
        cost=ActivationCost(),  # cost already paid; resolve-only here
        effect=PumpTargetCreatureUntilEOT(power_bonus_from_x=True),
    )
    py.stack.append(
        StackItem(
            source=py_src,
            controller_id=0,
            ability=pump_ability,
            targets=(("creature", py_bear.id),),
            x_value=_X,
        )
    )
    resolve_top_of_stack(py)
    assert len(py.stack) == 0

    # ---- Byte-equal observable: the bear's effective power 2 → 5 on
    # BOTH engines, toughness unchanged at 2.
    assert effective_power(py, py_bear) == 5, (
        "Python: bear gets +X/+0 with X=3 → power 5"
    )
    assert effective_toughness(py, py_bear) == 2
    assert rs.effective_power(rs_bear) == 5, (
        "Rust: bear gets +X/+0 with X=3 → power 5 (byte-equal)"
    )
    assert rs.effective_toughness(rs_bear) == 2
    assert effective_power(py, py_bear) == rs.effective_power(rs_bear)
    assert (
        effective_toughness(py, py_bear) == rs.effective_toughness(rs_bear)
    )


# ---------------------------------------------------------------------------
# (8) Python cost-payment unit pins (the tap-X-artifacts mint path).
# ---------------------------------------------------------------------------


def test_python_tap_x_artifacts_cost_taps_and_mints_x():
    """``_activate_ability`` with the tap-X-artifacts cost: the chosen
    count of untapped artifacts is tapped (lowest-id-first) and X flows
    onto the resolving pump so the target gets +X/+0."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.game import GameState, Player, Zone, effective_power
    from mtg_bot.actions import _activate_ability, resolve_top_of_stack

    class _ChooseN:
        def __init__(self, n):
            self.n = n

        def choose_x(self, state, pid, name, upper):
            return min(self.n, upper)

        def choose_target(self, state, pid, options):
            return options[0]

    state = GameState(players=[Player(id=0), Player(id=1)])
    state.players[0].agent = _ChooseN(2)

    art = CardPrinting(
        name="Trinket", mana_cost_str="", mana_cost=ManaCost(),
        type_line="Artifact", supertypes=(), card_types=("Artifact",),
        subtypes=(), produces=frozenset(),
    )
    arts = []
    for _ in range(3):
        o = state.new_object(art, owner_id=0, zone=Zone.BATTLEFIELD)
        o.tapped = False
        state.battlefield.append(o)
        arts.append(o)

    bear_p = CardPrinting(
        name="Bear", mana_cost_str="", mana_cost=ManaCost(),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=2, toughness=2, produces=frozenset(),
    )
    bear = state.new_object(bear_p, owner_id=0, zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    state.battlefield.append(bear)

    src_p = CardPrinting(
        name="Secluded Starforge", mana_cost_str="", mana_cost=ManaCost(),
        type_line="Land", supertypes=(), card_types=("Land",), subtypes=(),
        produces=frozenset({"C"}),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    tap_self=True,
                    tap_x_untapped_artifacts_you_control=True,
                ),
                effect=PumpTargetCreatureUntilEOT(power_bonus_from_x=True),
            ),
        ),
    )
    src = state.new_object(src_p, owner_id=0, zone=Zone.BATTLEFIELD)
    src.tapped = False
    state.battlefield.append(src)

    _activate_ability(state, 0, src.id, 0)
    # Two of the three artifacts tapped (lowest-id-first).
    tapped = [a for a in arts if a.tapped]
    assert len(tapped) == 2
    assert tapped == sorted(arts, key=lambda o: o.id)[:2]
    # The ability is on the stack carrying X=2.
    assert len(state.stack) == 1
    assert state.stack[-1].x_value == 2
    resolve_top_of_stack(state)
    assert effective_power(state, bear) == 4, "+X/+0 with X=2 → power 4"


def test_python_tap_x_artifacts_cost_zero_choice_taps_nothing():
    """Choosing X=0 taps no artifacts and the pump is a no-op."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import ActivatedAbility, ActivationCost
    from mtg_bot.effects.generic.pump import PumpTargetCreatureUntilEOT
    from mtg_bot.game import GameState, Player, Zone, effective_power
    from mtg_bot.actions import _activate_ability, resolve_top_of_stack

    class _ChooseZero:
        def choose_x(self, state, pid, name, upper):
            return 0

        def choose_target(self, state, pid, options):
            return options[0]

    state = GameState(players=[Player(id=0), Player(id=1)])
    state.players[0].agent = _ChooseZero()

    art = CardPrinting(
        name="Trinket", mana_cost_str="", mana_cost=ManaCost(),
        type_line="Artifact", supertypes=(), card_types=("Artifact",),
        subtypes=(), produces=frozenset(),
    )
    a = state.new_object(art, owner_id=0, zone=Zone.BATTLEFIELD)
    a.tapped = False
    state.battlefield.append(a)

    bear_p = CardPrinting(
        name="Bear", mana_cost_str="", mana_cost=ManaCost(),
        type_line="Creature", supertypes=(), card_types=("Creature",),
        subtypes=(), power=2, toughness=2, produces=frozenset(),
    )
    bear = state.new_object(bear_p, owner_id=0, zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    state.battlefield.append(bear)

    src_p = CardPrinting(
        name="Secluded Starforge", mana_cost_str="", mana_cost=ManaCost(),
        type_line="Land", supertypes=(), card_types=("Land",), subtypes=(),
        produces=frozenset({"C"}),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    tap_x_untapped_artifacts_you_control=True,
                ),
                effect=PumpTargetCreatureUntilEOT(power_bonus_from_x=True),
            ),
        ),
    )
    src = state.new_object(src_p, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(src)

    _activate_ability(state, 0, src.id, 0)
    assert a.tapped is False, "X=0 → no artifact tapped"
    assert state.stack[-1].x_value == 0
    resolve_top_of_stack(state)
    assert effective_power(state, bear) == 2, "X=0 → no pump"
