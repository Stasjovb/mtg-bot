"""Cross-engine LEGAL-DECISION-SET target-satisfiability — the CLOSED
contract (the permanent regression pin for legal_decisions
mana-awareness Slice 2).

HISTORY (the divergence this module characterizes, CLOSED by
Slice 2): Python ``mtg_bot.legal.legal_actions`` gates every
``CastSpell`` emission on ``_can_cast`` (mana — closed by Slice 1)
**AND** ``_targets_are_satisfiable`` (``src/mtg_bot/legal.py:79-114``,
CR 601.2c — a spell whose targeted ``spell_effect`` has ZERO legal
targets is never enumerated; call sites ``:254`` instant-speed /
``:385`` sorcery-speed / the warp variants / the graveyard-warp loop
``:459`` / the exile-recast ``:488``). Rust
``state_ops_legal.rs:legal_decisions`` USED to emit a ``cast_spell``
for a targeted spell even when no legal target existed — the spell
would push to the stack and resolve to a silent no-op (Python's
``if not targets: return`` resolve early-return). The two engines
presented DIFFERENT legal-decision SETS at the same priority point
whenever a hand spell's targeted effect had zero legal targets.

That divergence was benign-by-construction ONLY under the
single-script-replay contract (the action is computed from the
**Python** SoT state and the SAME ``action_dict`` is replayed on BOTH
engines — no path sources an agent choice from
``rust_state.legal_decisions``). At the SoT flip that contract
INVERTS (the NN/MCTS sources decisions from Rust's OWN enumeration),
at which point Rust offering a target-unsatisfiable cast becomes a
REAL correctness defect (PUCT would expand a "cast" no legal agent
could ever make; the value target would be polluted by a branch the
engine must no-op).

**CLOSED by legal_decisions mana-awareness Slice 2**
(``docs/RUST_LEGAL_DECISIONS_MANA_AWARENESS_DESIGN.md`` §(Slice 2)):
the non-destructive ``spell_targets_satisfiable`` predicate (mirroring
each live bridge-admitted targeted ``Effect`` variant's Python
``legal_targets`` filter via the SAME ``bf_iter_etb_sorted`` scan the
resolve arm uses — single source of truth) now gates ALL of Rust's
live CastSpell emission sites. On the live cast surface
``RustCastSpellSet == PythonCastSpellSet`` for the target axis too.
The change is parity-NEUTRAL under the current single-script-replay
harness (the predicate returns ``false`` ONLY when GENUINELY zero
legal targets exist — never narrower than Python's
``_targets_are_satisfiable`` — so every Python-sourced replayed
action is still emitted by post-fix Rust; design doc §4 proof, same
subset-preserving argument as Slice 1).

This module is the **permanent regression pin for the CLOSED
target-satisfiability contract**. It mirrors the established
synthetic side-channel legal-set idiom (the CE19 flash probe shape:
``build_matched_states`` → ``give_priority_to(0)`` → side-channel
inject the genuine real-EoE printing into p0's hand → compare
``legal_actions`` vs ``legal_decisions``). It:

  1. PINS THE CLOSED CONTRACT — the genuine parsed ``Depressurize``
     printing ({1}{B}, ``DepressurizeEffect``, an any-creature
     single-target instant) in p0's hand, mana AFFORDABLE (2 untapped
     B sources on p0's bf so the Slice-1 mana gate is NOT the
     pruner), with ZERO creatures on either battlefield: **BOTH**
     Python ``legal_actions`` and Rust ``legal_decisions`` omit the
     target-unsatisfiable ``CastSpell``. FAILS LOUDLY if Rust
     regresses to emitting the un-targetable cast.

  2. NEGATIVE CONTROL (over-prune guard): with a genuine vanilla
     creature seated on p0's bf (a legal Depressurize target —
     ``DepressurizeEffect.legal_targets`` is ANY creature on
     ``state.battlefield``) and mana affordable, BOTH engines emit
     exactly the base ``CastSpell`` — proving the new predicate is
     at-least-as-permissive as Python's (it does NOT over-prune a
     cast Python offers; the parity-neutral subset-preserving
     property).

> NOTE (mirrors ``docs/SEARCH_LIMITATIONS.md`` at landing): the
> mana-payability axis (Slice 1) and the target-satisfiability axis
> (Slice 2) on the live CastSpell sites are CLOSED. The residual
> divergence is the SEPARATE deferred surface: additional-cost
> (Slice 3) and the non-live alt-cost axes
> (kicker/impending/granted-warp/Room/X/the "Deferred alt-cost
> flags"). This module pins the target axis only.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

# Mirror the sibling probe modules' path bootstrap so cross-tests-dir
# imports resolve regardless of pytest's rootdir.
_TESTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


_CARD = "Depressurize"
_CARD_GENERIC = 1
_CARD_COLOR = ("B", 1)
# A genuine-shape mono-B producer the synthetic registry seats on
# p0's bf so {1}{B} is affordable from auto-tap headroom (the Slice-1
# mana gate passes — the target axis is the ONLY thing that can prune).
_LAND_NAME = "TS Probe Swamp"
_CREATURE_NAME = "TS Probe Bear"


def _verify_card_is_minimal_targeted_bridge_spell(real):
    """Verify-first guard (Python src = SoT): the genuine printing
    must STILL be the clean bridge-simple any-creature single-target
    instant this characterization rests on. FAILs loudly (never
    silently skips) on live-tree drift.
    """
    from mtg_bot.effects.bespoke import DepressurizeEffect
    from mtg_bot.parity import trajectory

    assert real is not None, f"{_CARD} absent from active CardSource"
    assert real.card_types == ("Instant",), (
        f"{_CARD}: expected a pure Instant; got {real.card_types}"
    )
    se = real.spell_effect
    assert isinstance(se, DepressurizeEffect), (
        f"{_CARD}: expected a DepressurizeEffect spell_effect; got "
        f"{type(se).__name__ if se else None} — re-anchor the pin"
    )
    assert se.requires_target(), (
        f"{_CARD}: DepressurizeEffect.requires_target() must be True "
        f"(the target axis is only testable on a targeting spell)"
    )
    assert real.warp_cost is None and real.kicker_cost is None, (
        f"{_CARD}: expected no alt-cost (the prune must be on the "
        f"PLAIN cast arm); warp={real.warp_cost} "
        f"kicker={real.kicker_cost}"
    )
    assert real.mana_cost.generic == _CARD_GENERIC, (
        f"{_CARD}: generic cost moved {real.mana_cost.generic} != "
        f"{_CARD_GENERIC} — re-pin the card or the expected cost"
    )
    assert tuple(real.mana_cost.colored) == (_CARD_COLOR,), (
        f"{_CARD}: colored cost moved {real.mana_cost.colored!r} != "
        f"{(_CARD_COLOR,)!r}"
    )
    assert trajectory._printing_is_bridge_simple_spell(real), (
        f"{_CARD}: no longer a bridge-simple spell — the Rust "
        f"synthetic carrier path this pin uses requires it"
    )


def _build(*, with_creature: bool):
    """Matched (py, rs) synthetic states at turn-1 / p0 priority with:

      * the genuine real-EoE ``Depressurize`` printing in p0's hand
        (Python: ``new_object(real, HAND)``; Rust: the bridged
        ``depressurize_effect`` dict — the established
        firing-parity-probe carrier shape),
      * 2 untapped mono-B lands on p0's battlefield (so the {1}{B}
        cost is affordable via ``auto_tap_headroom_pool`` — the
        Slice-1 mana gate passes; the target axis is the only pruner),
      * (negative control only) a genuine vanilla 2/2 creature on
        p0's battlefield (a legal Depressurize target).

    Built byte-equal on both engines via the established
    ``new_object`` / ``register_and_inject_object`` side-channel pair.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        tiny_synthetic_deckspec,
    )

    real = get_active_source().get_printings().get(_CARD)
    _verify_card_is_minimal_targeted_bridge_spell(real)

    py, rs = build_matched_states(tiny_synthetic_deckspec())
    # tiny_synthetic_deckspec → turn 1, UNTAP, active=0, priority=0.
    # An Instant only needs `_has_priority` (legal.py:180) — no
    # sorcery-timing gate — so this default priority point is a valid
    # instant-cast window for p0.
    py.priority_player_idx = 0
    rs.give_priority_to(0)

    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2

    # ---- 2 untapped mono-B lands on p0's bf (both engines) ----
    for i in range(2):
        land_cp = CardPrinting(
            name=f"{_LAND_NAME} {i}",
            mana_cost_str="",
            mana_cost=ManaCost(),
            type_line="Land",
            supertypes=(),
            card_types=("Land",),
            subtypes=(),
            power=None,
            toughness=None,
            produces=frozenset({"B"}),
        )
        py_land = py.new_object(
            land_cp, owner_id=0, zone=Zone.BATTLEFIELD
        )
        py_land.summoning_sick = False
        py_land.tapped = False
        py.battlefield.append(py_land)
        rs.register_and_inject_object(
            {
                "name": f"{_LAND_NAME} {i}",
                "card_types": ["Land"],
                "mana_produced": ["B"],
            },
            0,
            ZONE_BATTLEFIELD,
        )

    # ---- (negative control) a genuine vanilla 2/2 on p0's bf ----
    if with_creature:
        bear_cp = CardPrinting(
            name=_CREATURE_NAME,
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
        py_bear = py.new_object(
            bear_cp, owner_id=0, zone=Zone.BATTLEFIELD
        )
        py_bear.summoning_sick = False
        py.battlefield.append(py_bear)
        rs.register_and_inject_object(
            {
                "name": _CREATURE_NAME,
                "card_types": ["Creature"],
                "power": 2,
                "toughness": 2,
            },
            0,
            ZONE_BATTLEFIELD,
        )

    # ---- the genuine real-EoE Depressurize into p0's hand ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py_spell.summoning_sick = False
    py.players[0].hand.append(py_spell)
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": _CARD,
            "card_types": ["Instant"],
            "mana_cost": {"generic": _CARD_GENERIC, "B": 1},
            "effects": [
                {"kind": "depressurize_effect", "power_penalty": 3}
            ],
        },
        0,
        ZONE_HAND,
    )
    return py, rs, int(py_spell.id), int(rs_spell_id)


def _py_cast_decisions_for(py, card_id, player_id):
    from mtg_bot.legal import legal_actions

    return [
        a for a in legal_actions(py, player_id)
        if getattr(a, "card_id", None) == card_id
    ]


def _rs_cast_decisions_for(rs, card_id, player_id):
    return [
        a for a in rs.legal_decisions(player_id)
        if a.get("kind") == "cast_spell" and a.get("card_id") == card_id
    ]


def test_cross_engine_legal_set_target_satisf_closed_both_omit_untargetable():
    """THE CLOSED CONTRACT pin.

    Genuine real-EoE ``Depressurize`` ({1}{B}, DepressurizeEffect —
    target ANY creature) in p0's hand, {1}{B} AFFORDABLE (2 untapped
    mono-B lands on p0's bf, so the Slice-1 mana gate is NOT the
    pruner), with ZERO creatures on EITHER battlefield (no legal
    Depressurize target):

      * Python ``legal_actions(py, 0)`` does NOT emit a ``CastSpell``
        for it — ``_targets_are_satisfiable`` prunes it (zero legal
        targets, CR 601.2c, ``src/mtg_bot/legal.py:95-97``).
        (Unchanged — Python was always target-aware.)
      * Rust ``legal_decisions(0)`` now ALSO does NOT emit a
        ``cast_spell`` for it — Slice 2's
        ``spell_targets_satisfiable`` gate prunes the un-targetable
        cast at the emission site (was: structural emission → push →
        silent no-op resolve).

    LOUD on regression: if Rust reverts to emitting the un-targetable
    cast this FAILS — a Slice-2 regression, not a signal to weaken
    the test.
    """
    py, rs, py_id, rs_id = _build(with_creature=False)

    # Pre-condition A: {1}{B} truly affordable (≥2 untapped B sources)
    # so the mana axis is NOT the pruner.
    n_b_src = sum(
        1 for o in py.battlefield
        if o.controller_id == 0 and o.printing.is_land and not o.tapped
    )
    assert n_b_src >= 2, (
        f"{_CARD}: setup expected ≥2 untapped p0 B sources (so the "
        f"Slice-1 mana gate passes); got {n_b_src}"
    )
    # Pre-condition B: ZERO creatures anywhere on the battlefield.
    n_creatures = sum(
        1 for o in py.battlefield if o.printing.is_creature
    )
    assert n_creatures == 0, (
        f"{_CARD}: setup expected ZERO creatures on bf (the target-"
        f"unsatisfiable condition); got {n_creatures}"
    )

    py_casts = _py_cast_decisions_for(py, py_id, 0)
    rs_casts = _rs_cast_decisions_for(rs, rs_id, 0)

    assert py_casts == [], (
        f"{_CARD}: Python legal_actions UNEXPECTEDLY emitted a "
        f"CastSpell for a target-unsatisfiable spell (0 creatures) — "
        f"the target-aware prune at legal.py:95-97 regressed: "
        f"{py_casts!r}"
    )
    assert rs_casts == [], (
        f"{_CARD}: Rust legal_decisions UNEXPECTEDLY emitted a "
        f"cast_spell for a target-unsatisfiable {_CARD} (0 creatures, "
        f"mana affordable). legal_decisions mana-awareness Slice 2 "
        f"gates every live CastSpell site on "
        f"spell_targets_satisfiable; a non-empty set here means the "
        f"target gate / its DepressurizeEffect arm regressed. Got "
        f"rs_casts={rs_casts!r}"
    )


def test_cross_engine_legal_set_target_satisf_negative_control_both_emit():
    """NEGATIVE CONTROL / over-prune guard — Slice 2's predicate is
    at-least-as-permissive as Python's ``_targets_are_satisfiable``.

    Same genuine ``Depressurize`` in p0's hand, {1}{B} affordable, but
    now a genuine vanilla creature is SEATED on p0's battlefield (a
    legal Depressurize target — ``DepressurizeEffect.legal_targets``
    is ANY creature on ``state.battlefield``). Post-Slice-2 BOTH
    engines emit exactly the base ``CastSpell`` for the card. This is
    the parity-neutral subset-preserving guard: an over-prune
    (returning ``false`` with a legal target present) would WRONGLY
    drop a cast Python offers and the single-script-replay harness
    would replay a Python-sourced cast Rust no longer considers legal.
    Confirms Slice 2 closed the over-emission without introducing an
    under-emission.
    """
    py, rs, py_id, rs_id = _build(with_creature=True)

    n_b_src = sum(
        1 for o in py.battlefield
        if o.controller_id == 0 and o.printing.is_land and not o.tapped
    )
    assert n_b_src >= 2, (
        f"{_CARD}: setup expected ≥2 untapped p0 B sources; got "
        f"{n_b_src}"
    )
    n_creatures = sum(
        1 for o in py.battlefield if o.printing.is_creature
    )
    assert n_creatures >= 1, (
        f"{_CARD}: negative control expected ≥1 creature on bf (a "
        f"legal Depressurize target); got {n_creatures}"
    )

    py_casts = _py_cast_decisions_for(py, py_id, 0)
    rs_casts = _rs_cast_decisions_for(rs, rs_id, 0)

    py_warp = sorted(getattr(a, "use_warp", False) for a in py_casts)
    rs_warp = sorted(bool(a.get("use_warp")) for a in rs_casts)
    assert py_warp == [False] and rs_warp == [False], (
        f"{_CARD}: with a legal target seated AND {{1}}{{B}} "
        f"affordable, BOTH engines must emit exactly the base (non-"
        f"warp) cast — the target prune must NOT fire here (negative "
        f"control / over-prune guard). py={py_warp} rs={rs_warp} "
        f"(py_casts={py_casts!r} rs_casts={rs_casts!r})"
    )


def test_cross_engine_legal_set_target_satisf_only_axis_under_test():
    """Isolation guard: prove the CLOSED-contract test prunes on the
    TARGET axis, not the mana axis.

    With the SAME zero-creature state but the genuine Depressurize and
    its 2 B-lands present, assert the Slice-1 mana gate WOULD pass
    (≥2 untapped B sources cover {1}{B}) — so the only reason BOTH
    engines omit the cast in the closed-contract test is the Slice-2
    target prune, not a coincidental mana-unaffordability. This keeps
    the closed-contract test honest if a future mana-gate change ever
    made {1}{B} unaffordable here (which would make that test pass for
    the WRONG reason).
    """
    from mtg_bot.actions import can_pay_cost
    from mtg_bot.cards.source import get_active_source

    py, rs, py_id, _rs_id = _build(with_creature=False)
    real = get_active_source().get_printings().get(_CARD)
    # Python's own mana predicate must say {1}{B} is payable here
    # (auto-tap headroom from the 2 untapped B lands). If THIS is
    # False the closed-contract test would be passing because of the
    # mana axis, not the target axis — fail loudly.
    assert can_pay_cost(
        py, 0, real.mana_cost, spell_kind=frozenset({"spell"}),
        convoke=False, sac_for_mana=True,
    ), (
        f"{_CARD}: the 2 untapped B lands must make {{1}}{{B}} "
        f"payable (so the closed-contract test prunes on the TARGET "
        f"axis, not the mana axis). can_pay_cost returned False — the "
        f"isolation premise broke."
    )
