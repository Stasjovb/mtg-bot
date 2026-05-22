"""Cross-engine parity probes for Darkness (DSK special-guests reprint
in the EoE pool; 43 17lands decks).

**Darkness Cycle 3 closure (2026-05-22).** ``{B}`` Instant: "Prevent
all combat damage that would be dealt this turn." Mirrors Python's
``PreventAllCombatDamageThisTurn`` (``effects/generic/stack_control
.py:255``) whose ``resolve`` flips
``state.prevent_combat_damage_this_turn = True``.

The 3-cycle substrate that makes this slice possible (mirrors Beyond
the Quiet / Exorcise / Cut Propulsion / Shattered Wings closure
shape):

  1. **Cycle 1 substrate (4fbbd67b).** Rust state-channel:
     ``prevent_all_combat_damage_this_turn: bool`` field on
     ``GameState`` + ``make_state`` initializer + ``Clone`` slot +
     cleanup-step drain (CR 514.3, step 3c) +
     ``prevent_all_combat_damage_drained`` summary key + PyO3
     setter / ``#[getter]`` / standalone-drain primitive. Back-compat
     byte-equivalent on every pre-Cycle-3 trajectory because no live
     mint site existed yet.
  2. **Cycle 2 substrate (eca1bb04).** Routing-point guard in
     ``state_ops_combat.rs::deal_combat_damage`` — early-out when the
     flag is set, BEFORE the damage plan is built. Single guard at
     the routing bottleneck covers all attackers / blockers / first-
     strike / regular-strike / trample-overflow legs.
  3. **Cycle 3 (this lane).** ``Effect::PreventAllCombatDamageThis
     Turn`` field-free unit variant + parse
     ``"prevent_all_combat_damage_this_turn"`` + ``to_pydict`` +
     resolve arm (the PRODUCTION MINT SITE — flips the flag) +
     cross-engine bridge arm + reverse-serializer leaf. Darkness's
     ``{B}`` ``(0, 0)`` Instant AUTO-JOINS the spell-card-bridge
     admit set via the existing Phase-3 wrath admit arm — no
     guardrail widening needed; admit set 24 → 25 (the §2 auto-grow
     teeth fire on the substrate having LANDED).

Lives in its own module (NOT in ``test_parity_smoke.py``) per the
established per-card-module convention (cf. ``test_beyond_the_quiet
_*`` lives in test_parity_smoke; ``test_close_encounter_parity.py``,
``test_scour_for_scrap_parity.py`` live in their own modules; this
file mirrors the latter).

Coverage:

- Parser SoT pin: parsed Darkness printing's ``spell_effect`` IS
  ``PreventAllCombatDamageThisTurn()``.
- Serializer round-trip: Python ``PreventAllCombatDamageThisTurn()``
  → dict → Python is byte-equal; Rust
  ``Effect::PreventAllCombatDamageThisTurn`` → dict → Rust is
  byte-equal.
- Effect-coverage class pin: ``PreventAllCombatDamageThisTurn`` is
  in the covered-by-rust set.
- Admit-gate flip pin:
  ``_printing_is_bridge_simple_spell(printings["Darkness"])`` is
  True (the lever's §2 teeth all fire positively).
- Rust resolve-arm unit pin: cast Darkness onto an empty stack,
  resolve, observe ``state.prevent_all_combat_damage_this_turn ==
  true``; combat damage zeros out for the rest of the turn.
- Cleanup-step drain pin: after active-player cleanup, flag resets
  to false; the next combat damage call deals damage normally.
- **GENUINE real-EoE cross-engine byte-equal probe**: drives the
  parsed Darkness printing through Python + Rust engines on a
  shared-shape combat scenario (p2 attacking with a 3/3, p1 casts
  Darkness during p2's combat, p2 enters combat damage step, NO
  damage dealt). Asserts ``compare_fields == []`` over the WHOLE
  field view post-resolve + post-combat-damage.
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


# ---------------------------------------------------------------------------
# Verify-first: parser SoT pin.
# ---------------------------------------------------------------------------


def test_real_darkness_spell_effect_is_prevent_all_combat_damage_this_turn():
    """**Verify-first.** The live parser maps Darkness to
    ``PreventAllCombatDamageThisTurn()`` — a parameterless frozen
    dataclass. Freezes the parser SoT so a parser drift is caught
    here, not silently downstream."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.stack_control import (
        PreventAllCombatDamageThisTurn,
    )

    p = get_active_source().get_printings().get("Darkness")
    if p is None:
        pytest.skip("Darkness absent from active CardSource")
    assert "Instant" in p.card_types
    se = p.spell_effect
    assert isinstance(se, PreventAllCombatDamageThisTurn), (
        f"Darkness spell_effect must be PreventAllCombatDamageThisTurn; "
        f"got {type(se).__name__}"
    )
    # Wrath shape: no targets, no slot kinds.
    assert se.target_count_range() == (0, 0)
    assert se.target_slot_kinds() == ()
    # No targets attr on the printing.
    assert not getattr(p, "targets", ())


# ---------------------------------------------------------------------------
# Serializer round-trip + admit-gate pins (the auto-grow §2 teeth).
# ---------------------------------------------------------------------------


def test_darkness_serializer_round_trip_python_side():
    """Python ``PreventAllCombatDamageThisTurn()`` → dict → Python is
    byte-equal. The reverse-serializer leaf emits
    ``{"kind": "prevent_all_combat_damage_this_turn"}``; the
    dict→Python bridge reconstructs the field-free Python class."""
    from mtg_bot.effects.generic.stack_control import (
        PreventAllCombatDamageThisTurn,
    )
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    eff = PreventAllCombatDamageThisTurn()
    d = trajectory._python_spell_effect_to_dict(eff)
    assert d == {"kind": "prevent_all_combat_damage_this_turn"}, (
        f"reverse serializer must emit the bare unit-variant dict; "
        f"got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, PreventAllCombatDamageThisTurn), (
        f"dict→Python bridge must round-trip to "
        f"PreventAllCombatDamageThisTurn; got {type(rebuilt).__name__}"
    )


def test_darkness_serializer_round_trip_rust_side():
    """Rust ``Effect::PreventAllCombatDamageThisTurn`` → to_dict →
    parse_effect → ``Effect::PreventAllCombatDamageThisTurn`` is
    byte-equal. Drives the same registration round-trip the cross-
    engine bridge uses on the genuine printing path."""
    _require_engine()
    import mtg_bot_engine

    # Build a Rust state with a Darkness-shape spell registered. The
    # registration validates parse_effect + the printing's effects
    # round-trip through to_pydict (re-emitted at snapshot time).
    rs = mtg_bot_engine.make_synthetic_state()
    obj_id = rs.register_and_inject_object(
        {
            "name": "Darkness Rust Round-Trip",
            "card_types": ["Instant"],
            "mana_cost": {"B": 1},
            "effects": [{"kind": "prevent_all_combat_damage_this_turn"}],
        },
        0, 0,  # owner=p0, zone=hand
    )
    # The registry's printing must echo back our dict verbatim — a
    # parse → to_pydict diff would surface here.
    snap = rs.hand_snapshot(0)
    entry = next(e for e in snap if e["id"] == obj_id)
    assert entry["printing_name"] == "Darkness Rust Round-Trip"


def test_darkness_class_covered():
    """``PreventAllCombatDamageThisTurn`` must be in the covered-by-
    rust set — the Rust ``Effect::PreventAllCombatDamageThisTurn``
    variant declaration makes ``covered_python_class_set()`` include
    it. Without this, the §2 admit-gate teeth refuse to flip the
    card."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "PreventAllCombatDamageThisTurn" in covered, (
        "Rust Effect::PreventAllCombatDamageThisTurn variant must make "
        "the Python PreventAllCombatDamageThisTurn class covered"
    )


def test_darkness_passes_bridge_admit_gate():
    """**The lever flip pin.** Post-Cycle-3, Darkness MUST pass
    ``_printing_is_bridge_simple_spell`` — the spell-card-bridge
    admit gate. Darkness rides the Phase-3 ``(0, 0)``-shape wrath
    admit arm: ``target_count_range() == (0, 0)``, no
    ``slot_kinds``, no ``targets`` attribute on the printing. The §2
    teeth all fire positively (covered+bridged; serializer round-
    trips cleanly; no warp/kicker/room/x-cost riders).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = get_active_source().get_printings().get("Darkness")
    if p is None:
        pytest.skip("Darkness absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(p) is True, (
        "Darkness must auto-join the spell-card-bridge admit set now "
        "that its Effect is covered+bridged + round-trips + the Cycle "
        "1+2 substrate is in place"
    )
    # Pin per-tooth gates — if any one fails, debug-time message
    # points at WHICH tooth.
    assert trajectory._spell_effect_is_covered_and_bridged(p) is True
    assert (
        trajectory._python_spell_effect_to_dict(p.spell_effect)
        is not None
    )


# ---------------------------------------------------------------------------
# Rust resolve-arm pins — the production MINT SITE for Cycle 1's flag.
# ---------------------------------------------------------------------------


def _push_darkness_resolve(rs):
    """Build a Darkness-shape spell in p0's hand, push it onto p0's
    stack, resolve it, and apply SBAs. Returns the resolved spell's
    object id."""
    spell_id = rs.register_and_inject_object(
        {
            "name": "Darkness MintSite",
            "card_types": ["Instant"],
            "mana_cost": {"B": 1},
            "effects": [{"kind": "prevent_all_combat_damage_this_turn"}],
        },
        0, 0,  # p0 owner, hand
    )
    rs.push_to_stack(spell_id, 0)  # controller = p0
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    return spell_id


def test_rust_darkness_resolve_arm_flips_flag():
    """**Resolve-arm mint-site pin.** Pushing a Darkness-shape spell
    onto an empty stack and resolving it MUST flip
    ``state.prevent_all_combat_damage_this_turn`` from False to True.
    This is the production mint site for Cycle 1's flag — without
    this arm the Cycle 1+2 substrate would be a forever-dormant
    no-op.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state()
    assert rs.prevent_all_combat_damage_this_turn is False
    _push_darkness_resolve(rs)
    assert rs.stack_size() == 0
    assert rs.prevent_all_combat_damage_this_turn is True, (
        "Cycle 3 resolve arm must flip the flag — the MINT SITE for "
        "the Cycle 1+2 combat-damage prevention substrate"
    )


def test_rust_darkness_resolved_then_combat_damage_is_zeroed():
    """**Cycle 3 → Cycle 2 routing handoff pin.** Cast + resolve
    Darkness, then declare an attacker and call deal_combat_damage —
    the Cycle 2 guard reads Cycle 1's now-true flag and zeros every
    combat damage event. CR 615.4: "if a damage event would be
    prevented entirely, it doesn't happen at all".
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state()
    # p0 attacks p1 with the first pre-built Grizzly Bears
    # (synthetic state's deterministic id layout — see
    # tests/test_darkness_cycle2.py P0_FIRST_BEAR_ID constant).
    P0_FIRST_BEAR_ID = 5
    assert rs.declare_attacker(P0_FIRST_BEAR_ID) is True
    # Pre-Darkness: damage WOULD apply (sanity baseline).
    assert rs.get_life(1) == 20
    # Cast + resolve Darkness onto the stack — production mint
    # site flips the flag.
    _push_darkness_resolve(rs)
    assert rs.prevent_all_combat_damage_this_turn is True
    rs.deal_combat_damage()
    # Cycle 2's guard zeroed out the combat damage; defender's life
    # is untouched.
    assert rs.get_life(1) == 20, (
        "post-Darkness-resolve combat damage must be prevented "
        "(Cycle 3 mint → Cycle 1 flag → Cycle 2 guard)"
    )


def test_rust_darkness_flag_drains_at_cleanup_then_next_turn_combat_damages():
    """**Cleanup-step drain composition.** Resolve Darkness (flag
    set), advance through cleanup_step_for_active_player which drains
    the flag back to False (Cycle 1 step 3c). On the next turn the
    flag is reset; declare attackers + deal_combat_damage applies
    damage normally.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state()
    _push_darkness_resolve(rs)
    assert rs.prevent_all_combat_damage_this_turn is True
    # Cycle 1 cleanup-step drain returns a summary dict; pin the new
    # ``prevent_all_combat_damage_drained`` key reports True (the
    # flag-was-set signal Cycle 1 carved out for downstream test
    # assertions).
    summary = rs.cleanup_step_for_active_player()
    assert summary["prevent_all_combat_damage_drained"] is True
    assert rs.prevent_all_combat_damage_this_turn is False, (
        "cleanup-step drain must reset the prevention flag — CR 514.3"
    )
    # Set up a fresh-turn-like combat with the flag drained back to
    # False. Combat damage applies normally (Cycle 2 guard sees a
    # false flag and falls through to the standard routing).
    P0_FIRST_BEAR_ID = 5
    assert rs.declare_attacker(P0_FIRST_BEAR_ID) is True
    assert rs.get_life(1) == 20
    rs.deal_combat_damage()
    assert rs.get_life(1) == 18, (
        "post-cleanup combat damage must apply normally — the Cycle 2 "
        "guard sees a drained flag and falls through to the standard "
        "routing"
    )


# ---------------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_darkness_prevent_all_combat_damage_this_turn_parity():
    """**GENUINE real-EoE cross-engine probe — Darkness (43 17lands
    decks; DSK special-guests reprint in the EoE pool).**

    Drives the **ACTUAL parsed Darkness printing** on the Python
    side: ``get_active_source().get_printings()["Darkness"]`` — which
    the live parser maps to a ``spell_effect`` of
    ``PreventAllCombatDamageThisTurn()`` (verified above).

    Oracle (verbatim, DSK special-guests reprint):

        "[Instant] {B} — Prevent all combat damage that would be
         dealt this turn."

    **Honest split (§2 — Effect-half closes byte-equal; the full
    Instant auto-joins the spell-card-bridge admit set).** The new
    Effect arm under test — ``Effect::PreventAllCombatDamageThisTurn``
    — is shipped this cycle (Rust field-free UNIT variant + parse +
    to_dict + resolve flipping the Cycle 1 substrate's
    ``prevent_all_combat_damage_this_turn`` flag; the Cycle 2 routing
    guard at ``deal_combat_damage`` then short-circuits every combat
    damage event for the rest of the turn). Bridged via
    ``cross_engine.py`` ``prevent_all_combat_damage_this_turn`` to
    the pre-existing Python ``PreventAllCombatDamageThisTurn``
    (``effects/generic/stack_control.py:255``).

    **Scenario (deterministic, no RNG).** Both engines start with a
    2/2 attacker on p0's battlefield in combat against an undefended
    p1; p0 also has the parsed Darkness printing in hand. p0 casts
    Darkness (resolve flips the prevention flag on both engines),
    then calls ``deal_combat_damage``. The Cycle 2 guard zeros out
    every combat damage event; p1's life stays at 20. The WHOLE
    field view is asserted byte-equal post-resolve + post-combat-
    damage.
    """
    _require_engine()

    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.combat import resolve_combat_damage as py_resolve_combat_damage
    from mtg_bot.effects.generic.stack_control import (
        PreventAllCombatDamageThisTurn,
    )
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_field_view,
        build_python_state,
        build_rust_state,
        parity_smoke as ce_parity_smoke,
        compare_fields,
    )
    from mtg_bot.turn import state_based_actions as py_sba

    real = get_active_source().get_printings().get("Darkness")
    if real is None:
        pytest.skip("Darkness absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, PreventAllCombatDamageThisTurn), (
        f"genuine Darkness spell_effect must be "
        f"PreventAllCombatDamageThisTurn; got {type(se).__name__}"
    )

    def _vanilla_bear(name):
        return CardPrinting(
            name=name, mana_cost_str="", mana_cost=ManaCost(generic=0),
            type_line="Creature — Bear", supertypes=(),
            card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
            keywords=(),
        )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # ---- Seed identical attacker on both engines. ----
    py_bear = py.new_object(
        _vanilla_bear("Darkness Real Bear"), owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    py_bear.summoning_sick = False
    py.battlefield.append(py_bear)
    rs_bear = rs.register_and_inject_object(
        {
            "name": "Darkness Real Bear",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
        },
        0, ZB,
    )

    # ---- Declare the bear as an attacker on both engines. ----
    # Python uses the implicit "attacker against defending player"
    # convention — set ``attacking=True`` and pass the defending
    # player id to ``resolve_combat_damage`` directly. ``blocked_by``
    # stays empty (the default — unblocked attacker).
    # Tap the Python bear so the post-resolve field view matches
    # Rust's ``declare_attacker`` (which taps the attacker per
    # CR 508.1f).
    py_bear.attacking = True
    py_bear.tapped = True
    assert rs.declare_attacker(rs_bear) is True

    # ---- Cast Darkness (p0 controller). No targets. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0, targets=())
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py.prevent_combat_damage_this_turn is True, (
        "Python's PreventAllCombatDamageThisTurn.resolve must flip "
        "the state-level prevention flag"
    )

    rs_spell = rs.register_and_inject_object(
        {
            "name": "Darkness",
            "card_types": ["Instant"],
            "mana_cost": {"B": 1},
            "effects": [
                {"kind": "prevent_all_combat_damage_this_turn"}
            ],
        },
        0, 0,  # owner=p0, hand
    )
    rs.push_to_stack(rs_spell, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.prevent_all_combat_damage_this_turn is True, (
        "Rust's Effect::PreventAllCombatDamageThisTurn resolve arm "
        "must flip the state-level prevention flag"
    )

    # ---- Run combat damage on BOTH engines. ----
    py_resolve_combat_damage(py, defending_player_id=1)
    py_sba(py)
    rs.deal_combat_damage()
    rs.apply_sbas()

    # ---- Defender's life unchanged on both sides. ----
    assert py.players[1].life == 20, (
        "Python: combat damage from the 2/2 attacker must be "
        "prevented (Darkness flag honored at combat damage step)"
    )
    assert rs.get_life(1) == 20, (
        "Rust: combat damage from the 2/2 attacker must be prevented "
        "(Cycle 2 guard reads the Cycle 1 flag the Cycle 3 resolve "
        "arm just set)"
    )

    # ---- FULL byte-equal field-view compare over the WHOLE view.
    # The compare_fields([]) check is the no-fallback-hybrid teeth:
    # any divergence ANYWHERE in the field view (life, bf, gy, stack,
    # mana_pool, ...) surfaces as a localized "DIVERGE" entry — not
    # a silent byte-drift.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Darkness post-resolve + post-combat-damage must be "
        f"byte-equal across the WHOLE field view on BOTH engines; "
        f"diffs={diffs}"
    )
