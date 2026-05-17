"""Cross-engine LEGAL-DECISION-SET factored combat — the CLOSED
contract (the permanent regression pin for the G1 slice: Rust
``legal_decisions`` factored per-creature combat emission, the
C1-analog for the combat axis).

HISTORY (the divergence this module characterizes, CLOSED by G1):
Python ``mtg_bot.legal.legal_actions`` does NOT emit a whole
``DeclareAttackers`` / ``DeclareBlockers`` action at all — the engine
docstring (``src/mtg_bot/engine.py:10-19``) is explicit that the
combat-declaration actions "aren't enumerable as legal moves because
their decision space is combinatorial." Python's SEARCH seam uses a
FACTORED per-creature decomposition in
``src/mtg_bot/search/combat_decisions.py`` —
``AttackerDecision(attacker_id, attack)`` (ONE per eligible attacker,
exactly 2 branches: ``attack=True`` then ``attack=False``) and
``BlockerDecision(blocker_id, attacker_id)`` (ONE per eligible
blocker, one branch per currently-attacking creature plus a final
``attacker_id=None`` "don't block") — surfaced for the HEAD pending
creature by ``MtgGameStateAdapter.legal_decisions``
(``src/mtg_bot/search/engine_adapter.py:808-828``) and accumulated by
the adapter into a single engine-level ``DeclareAttackers`` /
``DeclareBlockers`` at finalize (``:1080-1144``).

Rust ``state_ops_legal.rs:legal_decisions`` USED to emit a Rust-only
**capped 2^n POWERSET** of whole ``declare_attackers`` actions
(``DECLARE_ATTACKERS_POWERSET_CAP = 4``) during DECLARE_ATTACKERS and
a Rust-only **capped (M+1)^N PRODUCT** of whole ``declare_blockers``
assignments (``DECLARE_BLOCKERS_PRODUCT_CAP = 3``,
``DECLARE_BLOCKERS_MAX_ATTACKERS = 3``) during DECLARE_BLOCKERS. That
Rust set was **neither a superset nor byte-equal** to Python's
factored per-creature set — it lost the per-creature MCTS
progressive-widening shape the codec ATTACKER/BLOCKER slots are built
for, and silently dropped the middle of the combinatorial space above
the cap. That was the documented G1 flip-blocker
(``docs/NN_RUST_DECISION_SOURCING_WIRING_DESIGN.md`` §2.4 G1).

That divergence was benign-by-construction ONLY under the
single-script-replay contract (every cross-engine harness computes the
action from the **Python** SoT state and replays the SAME
``action_dict`` — a Python-derived whole ``declare_attackers`` /
``declare_blockers`` dict — on BOTH engines via ``step_both``; no path
sources an agent choice from ``rust_state.legal_decisions``, verified
``cross_engine.py:10443-10448``). At the SoT flip that contract
INVERTS (the NN/MCTS sources combat decisions from Rust's OWN
enumeration), at which point Rust's powerset/product shape becomes a
REAL correctness defect (the codec cannot byte-map it onto the
factored ATTACKER/BLOCKER policy slots and the dropped middle is
unreachable).

**CLOSED by G1 (``feature/rust-g1-factored-combat``)** — the
combat-axis sibling of the C1 legal-set mana/target/cost closures
(Slices 1–3), the same non-destructive, parity-NEUTRAL,
subset-preserving, negative-control-verified discipline. Rust
``legal_decisions`` now emits, for the HEAD pending creature
(smallest-id eligible — matching the adapter's ``_pending_attackers =
sorted(o.id for o in eligible)`` ``engine_adapter.py:1315`` and the
codec's ``_pending_attacker_head`` ``min(...)`` fallback
``action_encoding.py:990-995``), the SAME factored per-creature shape
the Python search seam consumes:

  * DECLARE_ATTACKERS → exactly two
    ``{"kind":"attacker_decision","attacker_id":head,"attack":<bool>}``
    dicts (``attack=true`` then ``false``).
  * DECLARE_BLOCKERS → one
    ``{"kind":"blocker_decision","blocker_id":head,"attacker_id":atk}``
    per currently-attacking creature then a final
    ``…,"attacker_id":None`` ("don't block").

The whole-action ``apply_action`` arms (``declare_attackers`` /
``declare_blockers``) are UNCHANGED, so the Python-sourced
single-script-replay harness stays byte-identical (the C1 §4
parity-neutrality proof; empirically: the 4-file gate baseline 1532
is unmoved, every existing trajectory/probe/combat pin UNCHANGED).
``apply_action`` ALSO accepts a single factored
``attacker_decision``/``blocker_decision`` dict directly, dispatching
the SAME round-5 ``declare_attacker``/``declare_blocker`` primitive
the whole-action arms loop over (single source of truth).

This module pins the factored contract via the established synthetic
side-channel legal-set idiom (the C1 Slice-2/3 shape:
``build_matched_states`` → inject creatures onto the battlefield via
``register_and_inject_object`` → ``set_phase`` to the combat phase →
compare Rust ``legal_decisions`` SHAPE to the Python search-seam
factored shape). It:

  1. PINS THE CLOSED CONTRACT — at DECLARE_ATTACKERS with 2 eligible
     attackers (ids differ), Rust ``legal_decisions`` emits EXACTLY
     the two factored ``attacker_decision`` dicts for the smallest-id
     head (``attack=True`` first), byte-equal to the Python
     ``MtgGameStateAdapter`` ``AttackerDecision`` pair, and ZERO
     whole ``declare_attackers`` dicts. Likewise DECLARE_BLOCKERS →
     the ``m+1`` factored ``blocker_decision`` dicts, ZERO whole
     ``declare_blockers``.

  2. NEGATIVE-CONTROL-VERIFIED: against a pre-G1 engine this FAILS
     (pre-G1 Rust emitted ``2^n`` whole ``declare_attackers`` /
     ``(M+1)^N`` whole ``declare_blockers`` dicts and ZERO factored
     ``attacker_decision``/``blocker_decision`` — the
     powerset/product-vs-factored divergence the design names). The
     pin asserts the post-fix factored shape AND the absence of the
     pre-fix whole-action emission, so a regression to powerset/
     product is caught loudly.

  3. ROUND-TRIP / SINGLE-SOURCE-OF-TRUTH: applying the chosen factored
     ``attacker_decision`` dict directly via ``apply_action`` is
     byte-identical to applying the accumulated whole
     ``declare_attackers`` — the factored apply arm dispatches the
     SAME ``declare_attacker`` primitive (``state_ops_combat.rs``),
     mirroring the adapter's accumulate-then-finalize.

> NOTE (mirrors ``docs/SEARCH_LIMITATIONS.md`` at landing): the
> combat-declaration axis on the live Rust ``legal_decisions``
> emission is now CLOSED — byte-compatible with the Python factored
> search seam. The two former ACCEPTED entries ("DeclareAttackers
> powerset emission" / "DeclareBlockers product-space emission") are
> replaced by the single closed-G1 note. The B3 Python provider
> (sibling slice — NOT this one) owns the per-creature accumulation +
> finalize; this pin is the Rust-emission-shape contract only.
"""

from __future__ import annotations

import pathlib
import sys

# Mirror the sibling probe modules' path bootstrap.
_TESTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


# Rust phase constants (state_ops_steps.rs:104/106).
_PHASE_DECLARE_ATTACKERS = 5
_PHASE_DECLARE_BLOCKERS = 6

_ATK_A = "FC Probe Attacker A"
_ATK_B = "FC Probe Attacker B"
_BLK_A = "FC Probe Blocker A"
_BLK_B = "FC Probe Blocker B"


def _vanilla_creature_dict(name: str, power: int, toughness: int) -> dict:
    """A bridge-simple vanilla creature printing dict for the Rust
    ``register_and_inject_object`` side channel — no keywords, no
    effects, so eligibility is purely "is a non-tapped non-sick
    creature" on both engines."""
    return {
        "name": name,
        "card_types": ["Creature"],
        "power": power,
        "toughness": toughness,
    }


def _py_vanilla_printing(name: str, power: int, toughness: int):
    from mtg_bot.cards.base import CardPrinting, ManaCost

    return CardPrinting(
        name=name,
        mana_cost_str="",
        mana_cost=ManaCost(),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=power,
        toughness=toughness,
        produces=frozenset(),
    )


def _build_declare_attackers_context():
    """Matched (py, rs) synthetic states at DECLARE_ATTACKERS with TWO
    distinct-id vanilla creatures on p0's battlefield (the active
    player), p0 holding priority, stack empty.

    ``register_and_inject_object`` seats Rust battlefield objects with
    ``summoning_sick=false`` (``state_ops_resolve.rs:12454``) so both
    are immediately attack-eligible by ``combat.py:eligible_attackers``
    (non-tapped, non-sick creature) and the Rust eligibility loop
    (``state_ops_legal.rs:1229-1256``). Two creatures so the pre-G1
    powerset (``2^2 = 4`` whole ``declare_attackers`` dicts) is
    visibly distinct from the post-G1 factored shape (exactly 2
    ``attacker_decision`` dicts for the smaller-id head).
    """
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        tiny_synthetic_deckspec,
    )

    py, rs = build_matched_states(tiny_synthetic_deckspec())

    ZONE_BATTLEFIELD = 2

    # Python side: two vanilla creatures on p0's battlefield,
    # non-sick. ``new_object`` mints ascending ids; we capture both.
    py_ids: list[int] = []
    for nm, pw, tf in ((_ATK_A, 2, 2), (_ATK_B, 3, 3)):
        cp = _py_vanilla_printing(nm, pw, tf)
        obj = py.new_object(cp, owner_id=0, zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        py.battlefield.append(obj)
        py_ids.append(int(obj.id))

    # Rust side: same two via the register_and_inject side channel.
    rs_ids: list[int] = []
    for nm, pw, tf in ((_ATK_A, 2, 2), (_ATK_B, 3, 3)):
        rs_ids.append(
            int(
                rs.register_and_inject_object(
                    _vanilla_creature_dict(nm, pw, tf),
                    0,
                    ZONE_BATTLEFIELD,
                )
            )
        )

    # Move BOTH engines into DECLARE_ATTACKERS, p0 active, p0 priority,
    # empty stack (the Rust emission gate at
    # state_ops_legal.rs:1221-1224).
    from mtg_bot.turn import Step

    py.step = Step.DECLARE_ATTACKERS
    py.active_player_idx = 0
    py.priority_player_idx = 0
    rs.set_phase(_PHASE_DECLARE_ATTACKERS)
    rs.give_priority_to(0)

    return py, rs, sorted(py_ids), sorted(rs_ids)


def _build_declare_blockers_context():
    """Matched (py, rs) synthetic states at DECLARE_BLOCKERS: p0 has
    TWO attacking creatures; p1 (the defender) has TWO distinct-id
    eligible blockers. p1 holds priority.

    The Rust blocker eligibility loop reads ``self.attackers`` (the
    set the active player committed during DECLARE_ATTACKERS); we
    declare both p0 creatures as attackers via the round-5
    ``declare_attacker`` primitive (the same primitive the
    whole-action arm + the new factored arm dispatch — single source
    of truth) so the blocker emission has 2 attacker branches + the
    "don't block" branch = 3 factored dicts for the head blocker.
    """
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        build_matched_states,
        tiny_synthetic_deckspec,
    )

    py, rs = build_matched_states(tiny_synthetic_deckspec())
    ZONE_BATTLEFIELD = 2

    # p0 attackers (2) + p1 blockers (2), all vanilla non-sick.
    py_atk: list[int] = []
    for nm, pw, tf in ((_ATK_A, 2, 2), (_ATK_B, 3, 3)):
        cp = _py_vanilla_printing(nm, pw, tf)
        o = py.new_object(cp, owner_id=0, zone=Zone.BATTLEFIELD)
        o.summoning_sick = False
        py.battlefield.append(o)
        py_atk.append(int(o.id))
    py_blk: list[int] = []
    for nm, pw, tf in ((_BLK_A, 2, 2), (_BLK_B, 1, 1)):
        cp = _py_vanilla_printing(nm, pw, tf)
        o = py.new_object(cp, owner_id=1, zone=Zone.BATTLEFIELD)
        o.summoning_sick = False
        py.battlefield.append(o)
        py_blk.append(int(o.id))

    rs_atk: list[int] = []
    for nm, pw, tf in ((_ATK_A, 2, 2), (_ATK_B, 3, 3)):
        rs_atk.append(
            int(
                rs.register_and_inject_object(
                    _vanilla_creature_dict(nm, pw, tf), 0, ZONE_BATTLEFIELD
                )
            )
        )
    rs_blk: list[int] = []
    for nm, pw, tf in ((_BLK_A, 2, 2), (_BLK_B, 1, 1)):
        rs_blk.append(
            int(
                rs.register_and_inject_object(
                    _vanilla_creature_dict(nm, pw, tf), 1, ZONE_BATTLEFIELD
                )
            )
        )

    # Declare both p0 creatures as attackers on the Rust side (the
    # round-5 primitive — same one the whole-action + factored arms
    # use). Python: set the attacking flag directly (the engine-level
    # state the Rust `self.attackers` Vec mirrors).
    rs.set_phase(_PHASE_DECLARE_ATTACKERS)
    rs.give_priority_to(0)
    for aid in rs_atk:
        rs.declare_attacker(aid)

    from mtg_bot.turn import Step

    for o in py.battlefield:
        if o.controller_id == 0 and int(o.id) in py_atk:
            o.attacking = True

    # Both engines into DECLARE_BLOCKERS, p1 (defender) holds priority.
    py.step = Step.DECLARE_BLOCKERS
    py.active_player_idx = 0
    py.priority_player_idx = 1
    rs.set_phase(_PHASE_DECLARE_BLOCKERS)
    rs.give_priority_to(1)

    return py, rs, sorted(py_atk), sorted(rs_atk), sorted(py_blk), sorted(rs_blk)


def _rs_combat_dicts(rs, player_id, kinds):
    return [
        d for d in rs.legal_decisions(player_id)
        if d.get("kind") in kinds
    ]


# ----------------------------------------------------------------------
# DECLARE_ATTACKERS — the CLOSED-contract pin + negative control
# ----------------------------------------------------------------------


def test_cross_engine_factored_attackers_closed_contract():
    """THE CLOSED CONTRACT pin (DECLARE_ATTACKERS).

    With 2 distinct-id eligible attackers on p0's battlefield at
    DECLARE_ATTACKERS / p0 priority, Rust ``legal_decisions(0)`` emits
    EXACTLY the two factored ``attacker_decision`` dicts for the
    smallest-id head — ``attack=True`` first, then ``attack=False`` —
    byte-equal to the Python ``MtgGameStateAdapter`` factored
    ``AttackerDecision`` pair (``engine_adapter.py:811-814``), and
    emits ZERO whole ``declare_attackers`` dicts.

    NEGATIVE CONTROL (embedded): against a pre-G1 engine this FAILS —
    pre-G1 emitted ``2^2 = 4`` whole ``declare_attackers`` powerset
    dicts and ZERO ``attacker_decision``. Asserting BOTH the presence
    of the exact factored pair AND ``declare_attackers == []`` makes a
    regression to the powerset shape a loud failure (not a signal to
    weaken the test).
    """
    py, rs, py_ids, rs_ids = _build_declare_attackers_context()
    head = rs_ids[0]  # smallest-id eligible attacker

    # Python search-seam reference: the adapter's factored pair for
    # the head pending attacker (the byte-target Rust must mirror).
    from mtg_bot.search.combat_decisions import AttackerDecision

    py_head = py_ids[0]
    py_seam = [
        AttackerDecision(attacker_id=py_head, attack=True),
        AttackerDecision(attacker_id=py_head, attack=False),
    ]

    rs_factored = _rs_combat_dicts(rs, 0, {"attacker_decision"})
    rs_whole = _rs_combat_dicts(rs, 0, {"declare_attackers"})

    assert rs_whole == [], (
        f"G1 regression: Rust legal_decisions still emits whole "
        f"declare_attackers dicts at DECLARE_ATTACKERS — the pre-G1 "
        f"powerset emission. Post-G1 the byte-compatible factored "
        f"shape (attacker_decision per head) REPLACES the powerset; a "
        f"non-empty whole-action set here means the powerset block "
        f"was reintroduced. Got {rs_whole!r}"
    )
    assert rs_factored == [
        {"kind": "attacker_decision", "attacker_id": head, "attack": True},
        {"kind": "attacker_decision", "attacker_id": head, "attack": False},
    ], (
        f"G1: Rust legal_decisions must emit EXACTLY the two factored "
        f"attacker_decision dicts for the smallest-id head ({head}), "
        f"attack=True first then attack=False — byte-equal to the "
        f"Python search seam {py_seam!r} (engine_adapter.py:811-814). "
        f"Got {rs_factored!r}"
    )
    # Byte-map onto the Python seam (head id + branch order match —
    # the codec maps these 1:1 to SLOT_ATTACKER_ATTACK/SKIP).
    assert [
        (d["attacker_id"], d["attack"]) for d in rs_factored
    ] == [(s.attacker_id, s.attack) for s in py_seam], (
        f"G1: factored head/branch order must byte-mirror the Python "
        f"AttackerDecision seam. rs={rs_factored!r} py={py_seam!r}"
    )


def test_cross_engine_factored_attackers_apply_round_trips_to_whole():
    """SINGLE-SOURCE-OF-TRUTH / round-trip pin.

    Applying the chosen factored ``attacker_decision`` (``attack=True``
    for the head) directly via ``apply_action`` dispatches the SAME
    round-5 ``declare_attacker`` primitive the whole-action
    ``declare_attackers`` arm loops over — so the resulting state
    (head creature flagged attacking) is byte-identical to applying
    the accumulated whole ``declare_attackers`` for that id. The
    ``attack=False`` factored decision is a no-op (mirrors the
    adapter's ``_apply_attacker_decision`` only recording when
    ``decision.attack``, ``engine_adapter.py:1095-1096``).
    """
    # Path A: factored attacker_decision(head, attack=True).
    _, rs_a, _, rs_ids_a = _build_declare_attackers_context()
    head_a = rs_ids_a[0]
    rs_a.apply_action(
        {"kind": "attacker_decision", "attacker_id": head_a, "attack": True}
    )

    # Path B: whole declare_attackers([head]) for the same head.
    _, rs_b, _, rs_ids_b = _build_declare_attackers_context()
    head_b = rs_ids_b[0]
    rs_b.apply_action(
        {"kind": "declare_attackers", "attacker_ids": [head_b]}
    )

    assert rs_a.fingerprint() == rs_b.fingerprint(), (
        "G1 single-source-of-truth: applying the factored "
        "attacker_decision(head, attack=True) must be byte-identical "
        "to applying the accumulated whole declare_attackers([head]) "
        "— both dispatch the SAME declare_attacker primitive. "
        f"factored fp={rs_a.fingerprint()} whole fp={rs_b.fingerprint()}"
    )

    # attack=False is a no-op AT THE PRIMITIVE LEVEL (dispatches no
    # declare_attacker) — byte-identical to the accumulated whole
    # declare_attackers([]) (empty set, also no dispatch). Both run the
    # same unconditional post-arm reset (CR 117.1c); the right
    # single-source-of-truth assertion is factored-skip == whole-empty.
    _, rs_skip, _, rs_ids_s = _build_declare_attackers_context()
    head_s = rs_ids_s[0]
    rs_skip.apply_action(
        {"kind": "attacker_decision", "attacker_id": head_s, "attack": False}
    )
    _, rs_empty_a, _, _ = _build_declare_attackers_context()
    rs_empty_a.apply_action(
        {"kind": "declare_attackers", "attacker_ids": []}
    )
    assert rs_skip.fingerprint() == rs_empty_a.fingerprint(), (
        "G1: a factored attacker_decision with attack=False (the "
        "creature simply isn't declared) must be byte-identical to "
        "the accumulated whole declare_attackers([]) — both dispatch "
        "ZERO declare_attacker primitives, mirroring the adapter's "
        "_apply_attacker_decision recording nothing when not "
        "decision.attack (engine_adapter.py:1095-1096). factored-skip "
        f"fp={rs_skip.fingerprint()} whole-empty "
        f"fp={rs_empty_a.fingerprint()}"
    )


# ----------------------------------------------------------------------
# DECLARE_BLOCKERS — the CLOSED-contract pin + negative control
# ----------------------------------------------------------------------


def test_cross_engine_factored_blockers_closed_contract():
    """THE CLOSED CONTRACT pin (DECLARE_BLOCKERS).

    With 2 attacking p0 creatures and 2 distinct-id eligible p1
    blockers at DECLARE_BLOCKERS / p1 priority, Rust
    ``legal_decisions(1)`` emits EXACTLY the factored
    ``blocker_decision`` dicts for the smallest-id head blocker — one
    per currently-attacking creature (in ``self.attackers``
    declaration order) then a final ``attacker_id=None`` ("don't
    block") — byte-equal to the Python ``MtgGameStateAdapter``
    factored ``BlockerDecision`` list (``engine_adapter.py:815-828``),
    and ZERO whole ``declare_blockers`` dicts.

    NEGATIVE CONTROL (embedded): against a pre-G1 engine this FAILS —
    pre-G1 emitted ``(2+1)^2 = 9`` whole ``declare_blockers`` product
    dicts and ZERO ``blocker_decision``. Asserting BOTH the exact
    factored list AND ``declare_blockers == []`` makes a regression to
    the product shape a loud failure.
    """
    (
        py,
        rs,
        py_atk,
        rs_atk,
        py_blk,
        rs_blk,
    ) = _build_declare_blockers_context()
    head = rs_blk[0]  # smallest-id eligible blocker

    rs_factored = _rs_combat_dicts(rs, 1, {"blocker_decision"})
    rs_whole = _rs_combat_dicts(rs, 1, {"declare_blockers"})

    assert rs_whole == [], (
        f"G1 regression: Rust legal_decisions still emits whole "
        f"declare_blockers dicts at DECLARE_BLOCKERS — the pre-G1 "
        f"(M+1)^N product emission. Post-G1 the factored "
        f"blocker_decision shape REPLACES the product. Got {rs_whole!r}"
    )

    # The factored emission: one blocker_decision per attacking
    # creature (Rust iterates self.attackers declaration order =
    # rs_atk in declare order) + a final attacker_id=None.
    attacker_branch_ids = [d["attacker_id"] for d in rs_factored]
    assert attacker_branch_ids[-1] is None, (
        f"G1: the LAST factored blocker_decision must be the "
        f"'don't block' branch (attacker_id=None), mirroring "
        f"BlockerDecision(attacker_id=None) (engine_adapter.py:"
        f"825-827). Got branch ids {attacker_branch_ids!r}"
    )
    assert all(d["blocker_id"] == head for d in rs_factored), (
        f"G1: every factored blocker_decision must be for the "
        f"smallest-id head blocker ({head}). Got {rs_factored!r}"
    )
    # One branch per attacker + the None branch (m+1 total). The
    # attacker ids (order-independent set) must be exactly the
    # currently-attacking creatures.
    non_none = [a for a in attacker_branch_ids if a is not None]
    assert sorted(non_none) == sorted(rs_atk), (
        f"G1: the factored blocker branches must cover EXACTLY the "
        f"currently-attacking creatures {sorted(rs_atk)!r} (one "
        f"branch each) plus the None branch. Got non-None branch "
        f"ids {sorted(non_none)!r}"
    )
    assert len(rs_factored) == len(rs_atk) + 1, (
        f"G1: factored blocker emission must be exactly m+1 dicts "
        f"(one per attacker + don't-block), m={len(rs_atk)}. Got "
        f"{len(rs_factored)}: {rs_factored!r}"
    )

    # Byte-map onto the Python search seam for the head blocker.
    from mtg_bot.search.combat_decisions import BlockerDecision

    py_head = py_blk[0]
    attacking_ids = [
        o.id for o in py.battlefield if getattr(o, "attacking", False)
    ]
    py_seam = [
        BlockerDecision(blocker_id=py_head, attacker_id=a)
        for a in attacking_ids
    ] + [BlockerDecision(blocker_id=py_head, attacker_id=None)]
    assert len(rs_factored) == len(py_seam), (
        f"G1: Rust factored blocker count must equal the Python seam "
        f"({len(py_seam)} = m+1). rs={rs_factored!r} py={py_seam!r}"
    )


def test_cross_engine_factored_blockers_apply_round_trips_to_whole():
    """SINGLE-SOURCE-OF-TRUTH / round-trip pin (blockers).

    Applying the chosen factored ``blocker_decision(head, atk)``
    directly via ``apply_action`` dispatches the SAME round-5
    ``declare_blocker`` primitive the whole-action ``declare_blockers``
    arm loops over — byte-identical resulting state. ``attacker_id=
    None`` is a no-op (mirrors the adapter's ``_apply_blocker_decision``
    only recording when ``attacker_id is not None``,
    ``engine_adapter.py:1127-1128``).
    """
    # Path A: factored blocker_decision(head, first attacker).
    (
        _,
        rs_a,
        _,
        rs_atk_a,
        _,
        rs_blk_a,
    ) = _build_declare_blockers_context()
    head_a = rs_blk_a[0]
    target_a = rs_atk_a[0]
    rs_a.apply_action(
        {
            "kind": "blocker_decision",
            "blocker_id": head_a,
            "attacker_id": target_a,
        }
    )

    # Path B: whole declare_blockers([[head, target]]).
    (
        _,
        rs_b,
        _,
        rs_atk_b,
        _,
        rs_blk_b,
    ) = _build_declare_blockers_context()
    head_b = rs_blk_b[0]
    target_b = rs_atk_b[0]
    rs_b.apply_action(
        {
            "kind": "declare_blockers",
            "assignments": [[head_b, target_b]],
        }
    )

    assert rs_a.fingerprint() == rs_b.fingerprint(), (
        "G1 single-source-of-truth (blockers): the factored "
        "blocker_decision(head, atk) must be byte-identical to the "
        "accumulated whole declare_blockers([[head, atk]]) — both "
        "dispatch the SAME declare_blocker primitive. factored "
        f"fp={rs_a.fingerprint()} whole fp={rs_b.fingerprint()}"
    )

    # attacker_id=None is a no-op AT THE PRIMITIVE LEVEL: it dispatches
    # no declare_blocker. It is byte-identical to the accumulated whole
    # declare_blockers([]) (an empty assignment — also no declare_blocker
    # dispatch). NOTE: both still run the unconditional round-27 post-arm
    # reset (priority_player := active_player; CR 117.1c,
    # state_ops_actions.rs:1424-1428) — that is CORRECT engine behavior
    # shared by BOTH paths, not a G1 effect, so the right
    # single-source-of-truth assertion is factored-None == whole-empty
    # (NOT factored-None == pre-state, which would wrongly assert the
    # post-arm reset away).
    (
        _,
        rs_skip,
        _,
        _,
        _,
        rs_blk_s,
    ) = _build_declare_blockers_context()
    head_s = rs_blk_s[0]
    rs_skip.apply_action(
        {
            "kind": "blocker_decision",
            "blocker_id": head_s,
            "attacker_id": None,
        }
    )
    (
        _,
        rs_empty,
        _,
        _,
        _,
        _,
    ) = _build_declare_blockers_context()
    rs_empty.apply_action(
        {"kind": "declare_blockers", "assignments": []}
    )
    assert rs_skip.fingerprint() == rs_empty.fingerprint(), (
        "G1: a factored blocker_decision with attacker_id=None (the "
        "'don't block' branch) must be byte-identical to the "
        "accumulated whole declare_blockers([]) — both dispatch ZERO "
        "declare_blocker primitives and run the same post-arm reset, "
        "mirroring the adapter's _apply_blocker_decision recording "
        "nothing when attacker_id is None (engine_adapter.py:"
        f"1127-1128). factored-None fp={rs_skip.fingerprint()} "
        f"whole-empty fp={rs_empty.fingerprint()}"
    )


def test_cross_engine_factored_combat_action_round_trips_dict():
    """Codec/dict round-trip pin: the factored
    ``attacker_decision``/``blocker_decision`` dicts round-trip
    through ``parse_action`` → ``action_to_pydict`` without key drift
    (the byte-stability the codec slot mapping rests on)."""
    py, rs, _, rs_ids = _build_declare_attackers_context()
    head = rs_ids[0]

    # The emitted factored dicts must be exactly the canonical shape
    # (kind + 2 scalar keys for attacker, kind + blocker_id +
    # attacker_id for blocker — no extra keys, no drift).
    atk = _rs_combat_dicts(rs, 0, {"attacker_decision"})
    for d in atk:
        assert set(d.keys()) == {"kind", "attacker_id", "attack"}, (
            f"G1: attacker_decision dict has unexpected keys "
            f"{sorted(d.keys())!r} — round-trip key drift would "
            f"break the codec slot mapping. {d!r}"
        )
        assert d["attacker_id"] == head and isinstance(d["attack"], bool)

    (
        _,
        rs_b,
        _,
        _,
        _,
        _,
    ) = _build_declare_blockers_context()
    blk = _rs_combat_dicts(rs_b, 1, {"blocker_decision"})
    for d in blk:
        assert set(d.keys()) == {"kind", "blocker_id", "attacker_id"}, (
            f"G1: blocker_decision dict has unexpected keys "
            f"{sorted(d.keys())!r}. {d!r}"
        )
        assert d["attacker_id"] is None or isinstance(
            d["attacker_id"], int
        )
