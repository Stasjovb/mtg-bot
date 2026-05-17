"""Cross-engine LEGAL-DECISION-SET additional-cost — the CLOSED
contract (the permanent regression pin for legal_decisions
mana-awareness Slice 3).

HISTORY (the divergence this module characterizes, CLOSED by
Slice 3): Python ``mtg_bot.legal.legal_actions`` gates every
``CastSpell`` emission on ``_can_cast`` (mana — Slice 1) AND
``_targets_are_satisfiable`` (CR 601.2c — Slice 2) **AND**
``_additional_costs_payable`` (``src/mtg_bot/legal.py:117-165``,
CR 601.2f/601.2h — a spell whose cast-time additional NON-mana cost
the player cannot pay is never enumerated; the 3 flags
``additional_cost_sacrifice_creature_or_artifact`` /
``..._creature_or_enchantment`` / ``..._choose_your_creature``; call
sites ``:254`` instant / ``:385`` sorcery / the warp variants / the
graveyard-warp loop ``:460`` / the exile-recast ``:488``). Rust
``state_ops_legal.rs:legal_decisions`` USED to emit a ``cast_spell``
for such a spell even when the additional cost was unpayable (it
modeled NONE of the 3 flags — exactly like kicker/impending, the
"Deferred alt-cost flags" surface).

That divergence was benign-by-construction ONLY under the
single-script-replay contract. At the SoT flip that contract INVERTS
(the NN/MCTS sources decisions from Rust's OWN enumeration), at which
point Rust offering an additional-cost-unpayable cast becomes a REAL
correctness defect (PUCT would expand a "cast" no legal agent could
make).

**CLOSED by legal_decisions mana-awareness Slice 3**
(``docs/RUST_LEGAL_DECISIONS_MANA_AWARENESS_DESIGN.md`` §(Slice 3)):
the 3 ``additional_cost_*`` flags are added to the Rust
``CardPrinting`` (parsed from the registry dict with the same
back-compat ``match get_item { Some => extract, None => false }``
shape as ``warp_castable_from_graveyard``), and the non-destructive
``state_ops_legal::additional_costs_payable`` predicate — the Rust
analog of Python ``_additional_costs_payable`` — gates ALL 6 live
CastSpell emission sites.

**Verified-zero live incidence (the design §5 prediction realized).**
All 4 EoE printings carrying any additional-cost flag (Embrace
Oblivion, Scrounge for Eternity, Final Vengeance, Close Encounter)
are bridge-DECLINED by BOTH ``_printing_is_bridge_simple_spell`` and
``_printing_is_bridge_simple_creature``, so NO card on any of the 6
live Rust CastSpell axes carries one. The Slice-3 gate is therefore
**parity-NEUTRAL by construction** on the live surface (the predicate
is ``true`` for every live-surface card — never prunes, never
narrower than Python; same subset-preserving argument as Slices 1-2).
The full predicate is implemented anyway (NOT a stub) so it is the
faithful Python mirror AND fires correctly the instant an
additional-cost card becomes bridge-admitted.

This module pins the additional-cost contract via the established
synthetic side-channel legal-set idiom (the Slice-2 shape:
``build_matched_states`` → ``give_priority_to(0)`` → inject a
printing CARRYING the additional-cost flag into p0's hand on both
engines → compare ``legal_actions`` vs ``legal_decisions``). The
injected printing is a {0}-cost no-target Instant so the ONLY axis
that can prune it is the additional-cost gate (mana + target gates
trivially pass). It:

  1. PINS THE CLOSED CONTRACT — a {0} Instant flagged
     ``additional_cost_sacrifice_creature_or_artifact`` in p0's
     hand, with NO creature/artifact the caster controls (the
     additional cost is UNpayable): **BOTH** Python and Rust omit
     the ``CastSpell``. NEGATIVE-CONTROL-VERIFIED: against a
     pre-Slice-3 engine this FAILS (Rust modeled no
     additional-cost flag → emitted the un-payable cast; Python
     omitted).

  2. NEGATIVE CONTROL (over-prune guard): with a creature the
     caster controls (the additional cost IS payable — a
     sacrificeable permanent exists) BOTH engines emit exactly the
     base ``CastSpell`` — proving ``additional_costs_payable`` is
     at-least-as-permissive as Python's
     ``_additional_costs_payable`` (the parity-neutral
     subset-preserving property).

> NOTE (mirrors ``docs/SEARCH_LIMITATIONS.md`` at landing): the
> mana-payability (Slice 1), target-satisfiability (Slice 2) and
> additional-cost (Slice 3) axes on the live CastSpell sites are now
> ALL CLOSED. The residual divergence is the SEPARATE deferred
> surface: the non-live alt-cost axes
> (kicker/impending/granted-warp/Room/X — no Rust emission site
> yet). This is the C1 SoT-flip keystone fully landed at the
> legal-decision-set level.
"""

from __future__ import annotations

import pathlib
import sys

# Mirror the sibling probe modules' path bootstrap.
_TESTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


_SPELL_NAME = "AC Probe Bomb"
_CREATURE_NAME = "AC Probe Bear"


def _build(*, with_sac_permanent: bool):
    """Matched (py, rs) synthetic states at turn-1 / p0 priority with:

      * a {0}-cost no-target Instant FLAGGED
        ``additional_cost_sacrifice_creature_or_artifact`` in p0's
        hand (Python: ``new_object`` of a CardPrinting with the flag;
        Rust: ``register_and_inject_object`` of the dict carrying
        ``additional_cost_sacrifice_creature_or_artifact: true``).
        {0} cost + no spell_effect so the Slice-1 mana gate and the
        Slice-2 target gate BOTH trivially pass — the additional-cost
        gate is the ONLY axis that can prune it.
      * (negative control only) a genuine vanilla creature on p0's
        battlefield (a sacrificeable permanent — the additional cost
        becomes payable).

    Built byte-equal on both engines via the established
    ``new_object`` / ``register_and_inject_object`` side-channel pair
    (the Slice-2 idiom).
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        tiny_synthetic_deckspec,
    )

    py, rs = build_matched_states(tiny_synthetic_deckspec())
    # tiny_synthetic_deckspec → turn 1, UNTAP, active=0, priority=0.
    # An Instant only needs `_has_priority` (legal.py:180).
    py.priority_player_idx = 0
    rs.give_priority_to(0)

    ZONE_HAND = 0
    ZONE_BATTLEFIELD = 2

    if with_sac_permanent:
        # A genuine vanilla 2/2 the caster controls — a sacrificeable
        # creature so `additional_cost_sacrifice_creature_or_artifact`
        # is PAYABLE (Python `_additional_costs_payable` :124-131
        # returns True; Rust `additional_costs_payable` finds the
        # controlled creature).
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

    # The {0}-cost no-target Instant carrying the additional-cost
    # flag, into p0's hand on BOTH engines.
    spell_cp = CardPrinting(
        name=_SPELL_NAME,
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Instant",
        supertypes=(),
        card_types=("Instant",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        additional_cost_sacrifice_creature_or_artifact=True,
    )
    py_spell = py.new_object(spell_cp, owner_id=0, zone=Zone.HAND)
    py_spell.summoning_sick = False
    py.players[0].hand.append(py_spell)
    rs_spell_id = rs.register_and_inject_object(
        {
            "name": _SPELL_NAME,
            "card_types": ["Instant"],
            "mana_cost": {"generic": 0},
            "additional_cost_sacrifice_creature_or_artifact": True,
            "effects": [],
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


def test_cross_engine_legal_set_addcost_closed_both_omit_unpayable():
    """THE CLOSED CONTRACT pin.

    A {0}-cost no-target Instant FLAGGED
    ``additional_cost_sacrifice_creature_or_artifact`` in p0's hand,
    with NO creature/artifact the caster controls (the additional
    cost is UNpayable; the mana gate trivially passes — {0} cost —
    and the target gate trivially passes — no spell_effect):

      * Python ``legal_actions(py, 0)`` does NOT emit a ``CastSpell``
        for it — ``_additional_costs_payable`` prunes it
        (``src/mtg_bot/legal.py:124-131``: no creature/artifact the
        caster controls). (Unchanged — Python was always
        additional-cost-aware.)
      * Rust ``legal_decisions(0)`` now ALSO does NOT emit a
        ``cast_spell`` for it — Slice 3's
        ``additional_costs_payable`` gate (reading the new
        ``CardPrinting.additional_cost_sacrifice_creature_or_artifact``
        field) prunes the un-payable cast.

    LOUD on regression: if Rust reverts to emitting the
    additional-cost-unpayable cast (the field stops being
    parsed/read, or the gate is removed) this FAILS — a Slice-3
    regression, not a signal to weaken the test.
    """
    py, rs, py_id, rs_id = _build(with_sac_permanent=False)

    # Pre-condition: NO creature/artifact the caster controls (the
    # additional cost is genuinely unpayable — the additional-cost
    # axis is the ONLY thing that can prune here; {0} cost makes the
    # mana axis a non-factor, no spell_effect makes the target axis a
    # non-factor).
    n_sac = sum(
        1 for o in py.battlefield
        if o.controller_id == 0
        and (o.printing.is_creature or o.printing.is_artifact)
    )
    assert n_sac == 0, (
        f"{_SPELL_NAME}: setup expected ZERO sacrificeable "
        f"creature/artifact for p0 (the additional-cost-unpayable "
        f"condition); got {n_sac}"
    )

    py_casts = _py_cast_decisions_for(py, py_id, 0)
    rs_casts = _rs_cast_decisions_for(rs, rs_id, 0)

    assert py_casts == [], (
        f"{_SPELL_NAME}: Python legal_actions UNEXPECTEDLY emitted a "
        f"CastSpell for an additional-cost-unpayable spell — the "
        f"_additional_costs_payable prune at legal.py:124-131 "
        f"regressed: {py_casts!r}"
    )
    assert rs_casts == [], (
        f"{_SPELL_NAME}: Rust legal_decisions UNEXPECTEDLY emitted a "
        f"cast_spell for an additional-cost-unpayable spell ({{0}} "
        f"cost, no targets, no sacrificeable permanent). "
        f"legal_decisions mana-awareness Slice 3 gates every live "
        f"CastSpell site on additional_costs_payable; a non-empty "
        f"set here means the additional-cost gate / the "
        f"CardPrinting.additional_cost_* field parse regressed. Got "
        f"rs_casts={rs_casts!r}"
    )


def test_cross_engine_legal_set_addcost_negative_control_both_emit():
    """NEGATIVE CONTROL / over-prune guard — Slice 3's predicate is
    at-least-as-permissive as Python's ``_additional_costs_payable``.

    Same {0} Instant flagged
    ``additional_cost_sacrifice_creature_or_artifact`` in p0's hand,
    but now a genuine vanilla creature is SEATED on p0's battlefield
    (a sacrificeable permanent — the additional cost is PAYABLE).
    Post-Slice-3 BOTH engines emit exactly the base ``CastSpell``.
    This is the parity-neutral subset-preserving guard: an over-prune
    (returning ``false`` with a sacrificeable permanent present)
    would WRONGLY drop a cast Python offers and the single-script-
    replay harness would replay a Python-sourced cast Rust no longer
    considers legal. Confirms Slice 3 closed the over-emission
    without introducing an under-emission.
    """
    py, rs, py_id, rs_id = _build(with_sac_permanent=True)

    n_sac = sum(
        1 for o in py.battlefield
        if o.controller_id == 0
        and (o.printing.is_creature or o.printing.is_artifact)
    )
    assert n_sac >= 1, (
        f"{_SPELL_NAME}: negative control expected >=1 sacrificeable "
        f"creature/artifact for p0 (additional cost payable); got "
        f"{n_sac}"
    )

    py_casts = _py_cast_decisions_for(py, py_id, 0)
    rs_casts = _rs_cast_decisions_for(rs, rs_id, 0)

    py_warp = sorted(getattr(a, "use_warp", False) for a in py_casts)
    rs_warp = sorted(bool(a.get("use_warp")) for a in rs_casts)
    assert py_warp == [False] and rs_warp == [False], (
        f"{_SPELL_NAME}: with a sacrificeable permanent seated (the "
        f"additional cost payable), BOTH engines must emit exactly "
        f"the base (non-warp) cast — the additional-cost prune must "
        f"NOT fire here (negative control / over-prune guard). "
        f"py={py_warp} rs={rs_warp} (py_casts={py_casts!r} "
        f"rs_casts={rs_casts!r})"
    )


def test_cross_engine_legal_set_addcost_only_axis_under_test():
    """Isolation guard: prove the CLOSED-contract test prunes on the
    ADDITIONAL-COST axis, not the mana axis nor the target axis.

    With the SAME no-sac-permanent state, assert (a) the spell is
    {0}-cost so the Slice-1 mana gate WOULD pass (Python can_pay_cost
    is True for a {0} cost regardless of board), and (b) the spell
    has no spell_effect so the Slice-2 target gate trivially passes
    (Python _targets_are_satisfiable returns True). Therefore the ONLY
    reason BOTH engines omit the cast in the closed-contract test is
    the Slice-3 additional-cost prune — not a coincidental mana- or
    target-unsatisfiability that would make that test pass for the
    WRONG reason.
    """
    from mtg_bot.actions import can_pay_cost
    from mtg_bot.legal import _targets_are_satisfiable

    py, rs, py_id, _rs_id = _build(with_sac_permanent=False)
    spell = next(
        o for o in py.players[0].hand if o.printing.name == _SPELL_NAME
    )
    # (a) mana axis is a non-factor: {0} is payable on an empty board.
    assert can_pay_cost(
        py, 0, spell.printing.mana_cost,
        spell_kind=frozenset({"spell"}),
        convoke=False, sac_for_mana=True,
    ), (
        f"{_SPELL_NAME}: {{0}} cost must be payable (so the closed-"
        f"contract test prunes on the ADDITIONAL-COST axis, not the "
        f"mana axis). can_pay_cost returned False — the isolation "
        f"premise broke."
    )
    # (b) target axis is a non-factor: no spell_effect.
    assert spell.printing.spell_effect is None, (
        f"{_SPELL_NAME}: must have no spell_effect so the Slice-2 "
        f"target gate is a non-factor; got "
        f"{spell.printing.spell_effect!r}"
    )
    assert _targets_are_satisfiable(py, 0, spell), (
        f"{_SPELL_NAME}: _targets_are_satisfiable must be True for a "
        f"non-targeting spell (so the closed-contract test prunes on "
        f"the ADDITIONAL-COST axis, not the target axis)."
    )
