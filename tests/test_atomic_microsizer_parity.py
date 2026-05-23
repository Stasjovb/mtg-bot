"""Cross-engine parity probes for Atomic Microsizer — verify-first
HONEST-STOP close (2026-05-22, `feature/atomic-microsizer-cycle-1-p1`).

**Atomic Microsizer Cycle 1 — multi-cycle substrate scope.** ``{U}``
Artifact — Equipment (EoE pool, ~14 17lands decks). Oracle:

    "Equipped creature gets +1/+0.
     Whenever equipped creature attacks, choose up to one target
     creature. That creature can't be blocked this turn and has base
     power and toughness 1/1 until end of turn.
     Equip {2}"

**Verify-first finding (2026-05-22, see `docs/SEARCH_LIMITATIONS.md` —
"Atomic Microsizer Cycle 1 LANDED" section).** The pool-parity
attribution scout reports Atomic Microsizer in
`blocked_subsystem_gated` with THREE gates tripped:

  - `effect_uncovered` (no Rust counterpart for
    `AtomicMicrosizerAttackEffect`)
  - `carrier_activated_abilities` (the Equip {2} ability — Rust CardDef
    has NO `activated_abilities` field; round-42 §2-decline,
    campaign-wide)
  - `nonsafe_triggered_ability` (the `equipped_creature_attacks` trigger
    shape — fails `_python_ta_to_safe_dict` because the effect isn't
    covered)

**No sibling Equipment with an ATTACKS trigger is PROBED.** The three
PROBED Equipment in EoE (Glimmerlight, Hylderblade, Meltstrider's Gear)
all carry ENTERS / BEGINNING_OF_END_STEP triggers; the three
ATTACKS-triggered Equipment (Saw, Baseball Bat, Auxiliary Boosters) are
ALL in `blocked_subsystem_gated` alongside Atomic Microsizer with
identical three-gate attribution. That's strong evidence the gap is the
ATTACKS-triggered-Equipment substrate as a whole, NOT a single per-card
slice.

This module is the **HONEST-STOP pin** for the multi-cycle scope. It
verifies-first that the Python side is fully wired (parser SoT, effect
class, trigger shape) AND pins the Rust gap (no `Effect::
AtomicMicrosizerAttackEffect` variant, the card stays in
`blocked_subsystem_gated`, `_python_ta_to_safe_dict` returns None on
the ATTACKS trigger). When a future cycle lands the substrate, the
honest-stop arms below will fail loud to flag that the pin needs to
flip to a Hylderblade-style real-EoE cross-engine probe.

Lives in its own module per the established per-card-module convention
(cf. `test_darkness_parity.py`, `test_mutinous_massacre_parity.py`,
`test_systems_override_parity.py`).
"""

from __future__ import annotations

import importlib.util

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


# ---------------------------------------------------------------------------
# Verify-first: parser SoT pin — the Python side is fully wired.
# ---------------------------------------------------------------------------


def test_real_atomic_microsizer_parser_sot_attack_trigger_with_microsizer_effect():
    """**Verify-first.** The live parser maps Atomic Microsizer's
    equipped-creature-attacks oracle line to one triggered ability
    whose ``event`` is ``Event.ATTACKS``, ``predicate`` is
    ``IsHost(subject="attacker")``, and ``effect`` is
    ``AtomicMicrosizerAttackEffect()`` — a parameterless frozen
    dataclass. Freezes the parser SoT so a parser drift is caught
    here, not silently downstream."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import AtomicMicrosizerAttackEffect
    from mtg_bot.effects.predicates import Event, IsHost

    p = get_active_source().get_printings().get("Atomic Microsizer")
    if p is None:
        pytest.skip("Atomic Microsizer absent from active CardSource")
    assert "Artifact" in p.card_types
    assert "Equipment" in p.subtypes
    # Static +1/+0 anthem from the printed equipment_bonuses tuple.
    assert p.equipment_bonuses is not None
    pb, tb, gks = p.equipment_bonuses
    assert (pb, tb) == (1, 0)
    assert gks == frozenset()
    # Exactly one triggered ability — the equipped-creature-attacks
    # trigger. Oracle text has no ETB auto-attach line.
    assert len(p.triggered_abilities) == 1
    ta = p.triggered_abilities[0]
    assert ta.event == Event.ATTACKS
    assert isinstance(ta.predicate, IsHost)
    assert ta.predicate.subject == "attacker"
    assert isinstance(ta.effect, AtomicMicrosizerAttackEffect)
    # Equip {2} activated ability surfaces as a single activated
    # ability entry on the printing.
    assert len(p.activated_abilities) >= 1


def test_atomic_microsizer_effect_target_count_is_up_to_one_creature():
    """**Verify-first.** ``AtomicMicrosizerAttackEffect.target_count_range
    `` is ``(0, 1)`` (choose up to one), ``requires_target`` is True,
    and ``legal_targets`` returns ALL battlefield creatures (not just
    controller-owned). This is the load-bearing shape the Rust
    target-binding substrate would have to match in a future cycle —
    `GrantKeywordToTargetCreatureUntilEOT` / `SetBasePTUntilEOT` are
    both first-slice-controller-only today and can NOT compose into
    this surface without a target-id substrate slice."""
    from mtg_bot.cards import SYNTHETIC_CREATURES
    from mtg_bot.effects.bespoke import AtomicMicrosizerAttackEffect
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.agents import RandomAgent

    e = AtomicMicrosizerAttackEffect()
    assert e.requires_target()
    assert e.target_count_range() == (0, 1)
    # legal_targets returns creatures from BOTH controllers' bf.
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    p0_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(p0_bear)
    p1_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(p1_bear)
    legal = e.legal_targets(state, controller_id=0)
    legal_ids = {tid for (_kind, tid) in legal}
    assert p0_bear.id in legal_ids and p1_bear.id in legal_ids, (
        "AtomicMicrosizerAttackEffect.legal_targets must return creatures "
        "on BOTH players' battlefields — Rust's first-slice-controller-only "
        "variants (GrantKeywordToTargetCreatureUntilEOT / SetBasePTUntilEOT) "
        "cannot compose into this surface without a target-id substrate slice"
    )


# ---------------------------------------------------------------------------
# Honest-stop pins — the Rust gap.
# ---------------------------------------------------------------------------


def test_atomic_microsizer_effect_class_NOT_in_covered_set():
    """**Honest-stop pin.** ``AtomicMicrosizerAttackEffect`` is NOT in
    the covered-by-rust set today. No `Effect::AtomicMicrosizerAttackEffect`
    Rust variant exists, so the spell-card-bridge admit-set §2 teeth
    refuse to flip the card.

    When a future cycle lands the substrate, this test will FAIL loud
    to remind us to flip the honest-stop into a real cross-engine
    probe.
    """
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "AtomicMicrosizerAttackEffect" not in covered, (
        "AtomicMicrosizerAttackEffect is now in the covered set — the "
        "honest-stop pin in this module needs to flip to a Hylderblade-"
        "style real-EoE cross-engine probe. See `docs/SEARCH_LIMITATIONS.md` "
        "'Atomic Microsizer Cycle 1 LANDED' for the cycle-list scope."
    )


def test_atomic_microsizer_attack_trigger_is_NOT_safe_dict_today():
    """**Honest-stop pin.** The parsed Atomic Microsizer printing's
    ATTACKS-trigger TriggeredAbility does NOT round-trip through
    `_python_ta_to_safe_dict` today — the trigger is classified
    `nonsafe_triggered_ability` because its effect
    (`AtomicMicrosizerAttackEffect`) has no covered Rust counterpart.

    When the effect is covered AND the predicate/event are safe-dict-
    encodable, this assertion flips and the honest-stop arm needs to
    become a positive bridge test.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory as T

    p = get_active_source().get_printings().get("Atomic Microsizer")
    if p is None:
        pytest.skip("Atomic Microsizer absent from active CardSource")
    [ta] = list(p.triggered_abilities)
    safe_dict = T._python_ta_to_safe_dict(ta)
    assert safe_dict is None, (
        "Atomic Microsizer's ATTACKS trigger now serializes to a safe "
        "dict — the AtomicMicrosizerAttackEffect Rust variant must have "
        "landed. Flip this honest-stop arm into a positive bridge "
        "round-trip pin (mirror `test_darkness_serializer_round_trip_*`)."
    )


def test_atomic_microsizer_stays_in_blocked_subsystem_gated_tier():
    """**Honest-stop pin — the tier classification.** Pool-parity
    classifies Atomic Microsizer in `blocked_subsystem_gated` today;
    it MUST stay there until the multi-cycle substrate lands. When
    the closure flips it to `probed`, this pin fails loud to remind
    us to update both the tier expectation AND the
    `docs/SEARCH_LIMITATIONS.md` "Atomic Microsizer Cycle 1 LANDED"
    block (to a multi-cycle LANDED entry mirroring Darkness / Mutinous
    Massacre / Systems Override).
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from measure_pool_parity import classify_pool

    res = classify_pool()
    assert "Atomic Microsizer" in res.tiers["blocked_subsystem_gated"], (
        "Atomic Microsizer is no longer in blocked_subsystem_gated — the "
        "multi-cycle substrate has landed. Flip this honest-stop pin into "
        "a `'probed' in res.tiers` assertion mirroring "
        "`test_darkness_parity.py`'s admit-gate flip pin, AND update the "
        "`docs/SEARCH_LIMITATIONS.md` 'Atomic Microsizer Cycle 1 LANDED' "
        "block to a multi-cycle LANDED entry."
    )


def test_atomic_microsizer_subsystem_gates_attribution_three_gates():
    """**Verify-first.** The subsystem-attribution scout classifies
    Atomic Microsizer with the THREE gates the honest-stop docs cite:
    `effect_uncovered`, `carrier_activated_abilities`,
    `nonsafe_triggered_ability`. Pins the doc against scout drift —
    if the scout's classification function changes shape, this test
    surfaces the gap before the docs go stale.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from scout_r58_subsystem_attribution import subsystem_attribution

    attrib = subsystem_attribution()
    cards = attrib["cards"]
    info = cards.get("Atomic Microsizer")
    assert info is not None, (
        "Atomic Microsizer is no longer in the subsystem-gated cards dict "
        "— if it has flipped tiers, update the docs + the tier-pin above"
    )
    gates = set(info["gates"])
    assert gates == {
        "effect_uncovered",
        "carrier_activated_abilities",
        "nonsafe_triggered_ability",
    }, (
        f"Atomic Microsizer gate attribution has shifted away from the "
        f"three gates documented in `docs/SEARCH_LIMITATIONS.md` "
        f"'Atomic Microsizer Cycle 1 LANDED' — observed gates: {sorted(gates)}. "
        f"Update either the docs or this pin to match."
    )
    # Multi-gated — no single-mile closure.
    assert info["multi_gated"] is True
    assert info["last_mile"] is None
    # Missing effect classes points at the load-bearing per-card piece.
    assert info["missing_effect_classes"] == ["AtomicMicrosizerAttackEffect"]


def test_no_atomic_microsizer_effect_variant_in_rust_today():
    """**Honest-stop pin — the Rust side.** No
    ``Effect::AtomicMicrosizerAttackEffect`` parse arm exists today,
    so a synthetic `register_and_inject_object` with that effect kind
    in its `triggered_abilities[0].effect` dict raises at registration
    time. The PyO3 error message names the unknown effect kind.

    When the cycle 3 mint-site arm lands, this raises stops raising;
    flip the arm to a positive Hylderblade-pattern probe.
    """
    _require_engine()
    import mtg_bot_engine

    rs = mtg_bot_engine.make_synthetic_state()
    # Try to register a synthetic carrier with the missing effect kind
    # in a triggered_abilities slot — the parser should reject it.
    with pytest.raises(Exception) as exc_info:
        rs.register_and_inject_object(
            {
                "name": "Atomic Microsizer Probe",
                "card_types": ["Artifact"],
                "subtypes": ["Equipment"],
                "supertypes": [],
                "keywords": [],
                "effects": [],
                "triggered_abilities": [
                    {
                        "event": "attacks",
                        "predicate": {
                            "kind": "is_host",
                            "subject": "attacker",
                        },
                        "effect": {"kind": "atomic_microsizer_attack_effect"},
                    },
                ],
            },
            0, 2,  # owner=p0, zone=battlefield
        )
    msg = str(exc_info.value).lower()
    assert (
        "atomic_microsizer_attack_effect" in msg
        or "unknown" in msg
        or "unsupported" in msg
        or "missing" in msg
        or "invalid" in msg
        or "not yet wired" in msg
    ), (
        f"Expected the Rust parser to reject the unknown "
        f"'atomic_microsizer_attack_effect' kind with a recognisable "
        f"error; got: {exc_info.value!r}. If the kind has been added "
        f"to the parser, flip this honest-stop arm into a positive "
        f"register-and-resolve probe."
    )


# ---------------------------------------------------------------------------
# Future-cycle SCAFFOLD (skip-by-default).
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Honest-stop — multi-cycle substrate scope. When the "
        "AtomicMicrosizerAttackEffect Rust variant + target-id-binding "
        "substrate + bridge arms land (see `docs/SEARCH_LIMITATIONS.md` "
        "'Atomic Microsizer Cycle 1 LANDED' for the cycle list), un-skip "
        "this test and pattern it after `test_probe_remaining_lll.py`'s "
        "Hylderblade probe (inject Equipment onto bf via `rs.attach`-"
        "stamped to the attacker, dispatch Event::Attacks, observe "
        "post-resolve unblockable + base-PT 1/1 byte-equal across "
        "engines)."
    )
)
def test_cross_engine_real_eoe_atomic_microsizer_attack_trigger_parity():
    """**Future-cycle scaffold.** GENUINE real-EoE cross-engine probe
    for Atomic Microsizer's equipped-creature-attacks trigger.

    Will mirror `test_probe_remaining_lll.py`'s Hylderblade probe:

      * Both engines: p0 has an alive Wild Bear (the attacker — the
        Equipment's host) on bf.
      * Rust: inject the Atomic Microsizer synthetic carrier with a
        bridged `triggered_abilities` dict {`event: attacks`, predicate:
        `is_host(subject="attacker")`, effect:
        `atomic_microsizer_attack_effect`}; stamp `attached_to` to the
        bear's id via `rs.attach(microsizer_id, bear_id)`. p1 has a
        second Wild Bear (the trigger target).
      * Python: inject the parsed Atomic Microsizer printing onto p0's
        bf directly with `attached_to` set to the bear's id.
      * Both engines: declare the bear as attacker → ATTACKS dispatch
        fires the IsHost(subject="attacker")-matching trigger from
        the Equipment.
      * Resolve the trigger with a `_PickFirstLegalTargetAgent` →
        targets p1's bear (the first legal creature on bf).
      * Assert byte-equal observable state post-resolve:
        - The targeted creature has the cant-be-blocked UEOT
          continuous effect.
        - The targeted creature's effective base P/T == (1, 1).
        - The +1/+0 anthem on the equipped attacker is unchanged
          (covered by ContinuousModifier infrastructure already).
    """
    raise NotImplementedError(
        "Multi-cycle substrate not landed yet — see honest-stop pins "
        "above and `docs/SEARCH_LIMITATIONS.md` 'Atomic Microsizer "
        "Cycle 1 LANDED' for the cycle-list scope."
    )
