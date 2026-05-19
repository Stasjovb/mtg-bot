"""Genuine real-EoE cross-engine byte-equality probes — batch I.

CONTINUOUS-PIPELINE phase: convert covered-by-construction EoE cards into
the **strongest parity-evidence tier** (``PROBED byte-equal`` per
``docs/POOL_PARITY.md`` / ``scripts/measure_pool_parity.py``) via genuine
real-EoE cross-engine probes.

WHAT EACH PROBE ASSERTS
-----------------------
Every probe drives the **ACTUAL parsed EoE printing** on the Python side
(``get_active_source().get_printings().get("<card>")`` — NOT a synthetic
stub) against a bridged synthetic carrier on the Rust side
(``register_and_inject_object`` carrying the SAME DIES trigger effect) and
asserts **full ``compare_fields(...) == []``** (byte-equality across the
WHOLE cross-engine field view — the strongest Effect+bridge-level evidence)
after the real EoE creature dies on BOTH engines and its DIES trigger
resolves.

PARTITION DISCIPLINE (batch I — DIES triggers only)
---------------------------------------------------
This module owns **DIES TRIGGERS ONLY** — covered-but-unprobed creature
cards whose primary parser output is a ``triggered_abilities`` entry with
``event = Event.DIES``. Sibling batches G and H own sorcery/instant and
ETB-trigger shapes respectively; those are excluded here. Every card was
verify-first-confirmed at live HEAD to be (a) covered-by-construction,
(b) NOT already individually probed, (c) DIES-event primary trigger,
(d) Rust predicate vocabulary compatible.

The 4 batch-I picks (all at 0 17lands deck count — this is the frontier
of the covered-but-unprobed DIES-trigger tier; all higher-count DIES
cards are already probed by batches A and B):

  1. Grasping Longneck  (0 17lands decks) — DIES IsSelf → GainLife(2)
  2. Wary Watchdog      (0 17lands decks) — DIES IsSelf → Surveil(1)
  3. Piggy Bank         (0 17lands decks) — DIES IsSelf → CreateToken(Treasure)
  4. Fear of Lost Teeth (0 17lands decks) — DIES IsSelf → Sequence(DealDamageAnyTarget(1), GainLife(1))

DROPPED-ON-VERIFY (honest verify-first):

  * **Meltstrider Eulogist** (0 decks) — genuine DIES predicate is
    ``(IsCreature() & HasCounter('+1/+1')) & ControlledByYou``. Rust's
    ``parse_predicate`` (cards.rs:7752) has NO ``has_counter`` arm
    (valid: always, source_is_self, source_is_creature, subject_is_*,
    controlled_by_you, subject_has_subtype, not, and, or). A faithful
    cross-engine mirror is impossible without a new Rust substrate
    (out of scope for a non-Rust slice). Dropped honestly — same reason
    as batch A's odd-rank-65 drop documented in that module's docstring.

  * **Innocuous Rat** / **Bashful Beastie** (0 decks) — DIES IsSelf →
    ManifestDread(1). The cross_engine.py bridge arm docstring
    (cross_engine.py:6313-6357) explicitly defers the cross-engine
    end-to-end probe for ManifestDread: the ``choose_card_from_library``
    agent hook + face-down ETB-trigger fan-out make the byte-equal state
    construction non-trivial. Dropped per established bridge-arm-deferred
    precedent (the round-17/18/19 synthetic-only-when-riders-cascade rule).

  * **Living Phone** (0 decks) — DIES IsSelf → LookAtTopNRevealOrCounter
    (n=5, filter_name='creature', max_power=2, counter_on_miss=False).
    Requires a pending-decision interaction (``PendingDecision::
    LookAtTopNRevealOrCounterChoice``) that has no established byte-equal
    cross-engine auto-resolve path. Dropped per the deferred-interaction
    precedent.

NEW DEDICATED MODULE (not added to ``tests/test_trajectory_parity.py``
nor batch_a through batch_h — those are owned/protected; this module
avoids all collision).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (it's a script, not
    a package member) so probes can call ``_build_field_view`` for the
    full cross-engine byte-equality compare — same fixture shape as
    ``tests/test_parity_smoke.py``."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# Module-level helpers (mirrors batch B's _kill_both / _drain_both).

def _drain_both(py_state, rust_state):
    from mtg_bot.actions import resolve_top_of_stack
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    while py_state.stack:
        resolve_top_of_stack(py_state)


def _kill_both(py_state, rust_state, py_obj, rust_obj_id):
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import state_based_actions
    py_obj.damage = 99
    for _ in range(20):
        if not state_based_actions(py_state):
            break
        while py_state.stack:
            resolve_top_of_stack(py_state)
    rust_state.deal_damage(rust_obj_id, 99)
    rust_state.apply_sbas_until_quiescent()


# ---------------------------------------------------------------------
# Batch-I probe #1 — Grasping Longneck (0 17lands decks).
#
# Verified covered (``GainLife`` ∈ covered set) + unprobed at HEAD.
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Enchantment Creature — Horror] 4/2
#    When this creature dies, you gain 2 life."
# Parser → single DIES IsSelf trigger, effect=GainLife(amount=2).
# Simplest possible shape: no targets, no agent, deterministic.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_grasping_longneck_dies_gain_life_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Grasping Longneck
    (0 17lands decks). Batch-I covered→PROBED.**

    Python: the ACTUAL parsed Grasping Longneck printing seated on p0's
    battlefield, killed by lethal damage; its DIES trigger (IsSelf →
    GainLife(2)) fires through the production SBA-death path. Rust: the
    bridged synthetic carrier with the same dies/source_is_self/
    gain_life{2} trigger.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (carrier in p0 graveyard on BOTH; p0 life
    +2 on BOTH; p1 untouched on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.predicates import Event, IsSelf

    real = get_active_source().get_printings().get("Grasping Longneck")
    if real is None:
        pytest.skip("Grasping Longneck absent from active CardSource")
    assert "Creature" in real.card_types
    dies = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "dies"),
        None,
    )
    assert dies is not None, "Grasping Longneck must have a DIES trigger"
    assert isinstance(dies.predicate, IsSelf)
    assert isinstance(dies.effect, GainLife), (
        f"genuine Grasping Longneck DIES must be GainLife; "
        f"got {type(dies.effect).__name__}"
    )
    assert dies.effect.amount == 2

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    rp = int(real.power) if real.power is not None else 4
    rt = int(real.toughness) if real.toughness is not None else 2

    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    rs_id = rs.register_and_inject_object(
        {
            "name": "Grasping Longneck",
            "card_types": ["Enchantment", "Creature"],
            "power": rp, "toughness": rt,
            "triggered_abilities": [
                {
                    "event": "dies",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "gain_life", "amount": 2},
                }
            ],
        },
        0, ZB,
    )
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)

    assert rs.stack_size() == 0 and len(py.stack) == 0

    _kill_both(py, rs, py_obj, rs_id)
    _drain_both(py, rs)
    assert len(py.stack) == 0 and rs.stack_size() == 0

    assert py.players[0].life == py_p0_life0 + 2, "p0 gains 2 (Python)"
    assert py.players[1].life == py_p1_life0, "p1 untouched (Python)"
    assert rs.get_life(0) == rs_p0_life0 + 2, "p0 gains 2 (Rust)"
    assert rs.get_life(1) == rs_p1_life0, "p1 untouched (Rust)"

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Grasping Longneck DIES gain-life must be byte-equal across "
        f"the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-I probe #2 — Wary Watchdog (0 17lands decks).
#
# Verified covered (``Surveil`` ∈ covered set) + unprobed at HEAD.
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Creature — Dog] 3/1
#    When this creature enters, surveil 1.
#    When this creature dies, surveil 1."
# Parser → two triggers: ETB IsSelf → Surveil(1) (already covered by
# class; DIES leg below is the one we probe) + DIES IsSelf → Surveil(1).
# Surveil with no agent defaults to keep_all_on_top on BOTH engines —
# library top unchanged, graveyard empty from the surveil. Deterministic,
# no RNG, no targets, byte-equal cross-engine.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_wary_watchdog_dies_surveil_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Wary Watchdog
    (0 17lands decks). Batch-I covered→PROBED.**

    Python: the ACTUAL parsed Wary Watchdog printing seated on p0's
    battlefield, killed by lethal damage; its DIES trigger (IsSelf →
    Surveil(1)) fires. Rust: the bridged synthetic carrier with the same
    dies/source_is_self/surveil{1} trigger.

    Surveil default: no agent seated on p0 → both engines use the
    keep_all_on_top default (Python: agent=None short-circuit;
    Rust: auto_resolve keep_all_on_top strategy). Library top unchanged,
    graveyard empty from the surveil step on BOTH.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (carrier in p0 graveyard on BOTH; p0
    library top unchanged on BOTH; life untouched on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke, CardDef,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot.effects.predicates import Event, IsSelf

    real = get_active_source().get_printings().get("Wary Watchdog")
    if real is None:
        pytest.skip("Wary Watchdog absent from active CardSource")
    assert "Creature" in real.card_types
    dies = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "dies"),
        None,
    )
    assert dies is not None, "Wary Watchdog must have a DIES trigger"
    assert isinstance(dies.predicate, IsSelf)
    assert isinstance(dies.effect, Surveil), (
        f"genuine Wary Watchdog DIES must be Surveil; "
        f"got {type(dies.effect).__name__}"
    )
    assert dies.effect.amount == 1

    # One filler card in each library so the surveil "look" is observable
    # (no card to look at → surveil is a no-op; one card → look + keep).
    filler = CardDef(name="WW Filler", card_type="Land", mana_produced=("G",))
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=("WW Filler",),
        p1_library=("WW Filler",),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    rp = int(real.power) if real.power is not None else 3
    rt = int(real.toughness) if real.toughness is not None else 1

    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)

    rs_id = rs.register_and_inject_object(
        {
            "name": "Wary Watchdog",
            "card_types": ["Creature"],
            "power": rp, "toughness": rt,
            "triggered_abilities": [
                {
                    "event": "dies",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "surveil", "count": 1},
                }
            ],
        },
        0, ZB,
    )

    assert rs.stack_size() == 0 and len(py.stack) == 0

    _kill_both(py, rs, py_obj, rs_id)
    _drain_both(py, rs)
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # Library unchanged by keep_all_on_top surveil on BOTH.
    assert len(py.players[0].library) == 1, "p0 library still 1 (Python)"
    assert rs.library_sizes[0] == 1, "p0 library still 1 (Rust)"
    assert len(py.players[0].graveyard) == 1, "only the Watchdog in gy (Python)"
    assert rs.graveyard_sizes[0] == 1, "only the Watchdog in gy (Rust)"

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Wary Watchdog DIES surveil must be byte-equal across "
        f"the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-I probe #3 — Piggy Bank (0 17lands decks).
#
# Verified covered (``CreateToken`` ∈ covered set) + unprobed at HEAD.
# Oracle (verbatim, ``data/edge_of_eternities.json``):
#   "[Artifact Creature — Boar Toy] 3/2
#    When this creature dies, create a Treasure token."
# Parser → single DIES IsSelf trigger, effect=CreateToken(token=
# Treasure artifact, tapped=False, each_player=False, count=1).
# Treasure pid is registered on Rust; Python seats the intrinsic
# TOKEN_PRINTINGS["Treasure"] (the established Lander/Robot token-pid
# idiom from batches A and B). No targets, no agent, deterministic.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_piggy_bank_dies_create_treasure_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Piggy Bank
    (0 17lands decks). Batch-I covered→PROBED.**

    Python: the ACTUAL parsed Piggy Bank printing seated on p0's
    battlefield, killed by lethal damage; its DIES trigger (IsSelf →
    CreateToken(Treasure, count=1)) fires. Rust: the bridged synthetic
    carrier with the same dies/source_is_self/create_token trigger
    (Treasure pid registered via register_and_inject_object).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (carrier in p0 graveyard + one Treasure
    on p0 battlefield on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.effects.generic.tokens import CreateToken
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    real = get_active_source().get_printings().get("Piggy Bank")
    if real is None:
        pytest.skip("Piggy Bank absent from active CardSource")
    assert "Creature" in real.card_types
    assert len(real.triggered_abilities) == 1
    ta = real.triggered_abilities[0]
    assert ta.event == Event.DIES
    assert isinstance(ta.predicate, IsSelf)
    assert isinstance(ta.effect, CreateToken), (
        f"genuine Piggy Bank DIES must be CreateToken; "
        f"got {type(ta.effect).__name__}"
    )
    assert ta.effect.token_printing.name == "Treasure"
    assert ta.effect.tapped is False
    assert ta.effect.each_player is False
    assert ta.effect.count == 1

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    rp = int(real.power) if real.power is not None else 3
    rt = int(real.toughness) if real.toughness is not None else 2

    # Register the Treasure token on Rust (pid = registry_size before
    # any other registration in this state); seat the intrinsic Python
    # printing in p0's library so the STARTING field view is symmetric
    # (the genuine effect mints a FRESH Treasure on the bf).
    treasure_pid = rs.registry_size
    rs.register_and_inject_object(
        {"name": "Treasure", "card_types": ["Artifact"],
         "supertypes": ["Token"], "mana_cost": {"generic": 0}},
        0, 1,  # owner p0, ZONE_HAND (inert seed — not battlefield)
    )
    py_seed = py.new_object(
        TOKEN_PRINTINGS["Treasure"], owner_id=0, zone=Zone.LIBRARY
    )
    py_seed.summoning_sick = False
    py.players[0].library.append(py_seed)

    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)

    rs_src = rs.register_and_inject_object(
        {
            "name": "Piggy Bank",
            "card_types": ["Artifact", "Creature"],
            "power": rp, "toughness": rt,
            "triggered_abilities": [
                {
                    "event": "dies",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "create_token", "count": 1,
                               "token_printing_id": treasure_pid},
                }
            ],
        },
        0, ZB,
    )

    assert rs.stack_size() == 0 and len(py.stack) == 0

    _kill_both(py, rs, py_obj, rs_src)
    _drain_both(py, rs)
    assert len(py.stack) == 0 and rs.stack_size() == 0

    rust_n = sum(1 for e in rs.battlefield_snapshot()
                 if e["printing_name"] == "Treasure")
    py_n = sum(1 for o in py.battlefield
               if o.printing.name == "Treasure")
    assert rust_n == 1 == py_n, (
        f"Piggy Bank dies → exactly one Treasure on BOTH; "
        f"rust={rust_n} py={py_n}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Piggy Bank DIES create-Treasure must be byte-equal across "
        f"the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-I probe #4 — Fear of Lost Teeth (0 17lands decks).
#
# Verified covered (``Sequence`` / ``DealDamageAnyTarget`` / ``GainLife``
# ∈ covered set) + unprobed at HEAD. Oracle (verbatim,
# ``data/edge_of_eternities.json``):
#   "[Enchantment Creature — Nightmare] 1/1
#    When this creature dies, it deals 1 damage to any target and
#    you gain 1 life."
# Parser → single DIES IsSelf trigger, effect=Sequence(
#   DealDamageAnyTarget(amount=1), GainLife(amount=1)).
# Target: p0 controls Fear of Lost Teeth; on an empty p1 battlefield
# both engines pick the opponent-player (p1) — Rust's deterministic
# defender-scan finds no creature and falls to the opponent player;
# Python's _PickFirstOpponentTargetAgent returns the first opponent-side
# target which is the player target p1.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_fear_of_lost_teeth_dies_drain_one_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Fear of Lost Teeth
    (0 17lands decks). Batch-I covered→PROBED.**

    Python: the ACTUAL parsed Fear of Lost Teeth printing seated on p0's
    battlefield, killed by lethal damage; its DIES trigger (IsSelf →
    Sequence(DealDamageAnyTarget(1), GainLife(1))) fires. Target: p1
    player (empty p1 bf → Rust defender-scan falls to p1 player;
    Python _PickFirstOpponentTargetAgent picks the same p1 player).
    Rust: the bridged synthetic carrier with the same
    dies/source_is_self/sequence[deal_damage_any_target1, gain_life1]
    trigger.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (carrier in p0 graveyard on BOTH; p1 life
    −1, p0 life +1 on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.damage import DealDamageAnyTarget
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.predicates import Event, IsSelf
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Fear of Lost Teeth")
    if real is None:
        pytest.skip("Fear of Lost Teeth absent from active CardSource")
    assert "Creature" in real.card_types
    dies = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "dies"),
        None,
    )
    assert dies is not None, "Fear of Lost Teeth must have a DIES trigger"
    assert isinstance(dies.predicate, IsSelf)
    assert isinstance(dies.effect, Sequence), (
        f"genuine Fear of Lost Teeth DIES must be a Sequence; "
        f"got {type(dies.effect).__name__}"
    )
    assert len(dies.effect.effects) == 2
    assert isinstance(dies.effect.effects[0], DealDamageAnyTarget)
    assert dies.effect.effects[0].amount == 1
    assert isinstance(dies.effect.effects[1], GainLife)
    assert dies.effect.effects[1].amount == 1

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    rp = int(real.power) if real.power is not None else 1
    rt = int(real.toughness) if real.toughness is not None else 1

    # Seat the deterministic opponent-target shim on p0: the DIES trigger's
    # DealDamageAnyTarget leg needs a target picked at push time. With an
    # empty p1 battlefield both engines pick the p1 player as the target.
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)
    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    rs_id = rs.register_and_inject_object(
        {
            "name": "Fear of Lost Teeth",
            "card_types": ["Enchantment", "Creature"],
            "power": rp, "toughness": rt,
            "triggered_abilities": [
                {
                    "event": "dies",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {"kind": "sequence", "effects": [
                        {"kind": "deal_damage_any_target", "amount": 1},
                        {"kind": "gain_life", "amount": 1},
                    ]},
                }
            ],
        },
        0, ZB,
    )
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)

    assert rs.stack_size() == 0 and len(py.stack) == 0

    _kill_both(py, rs, py_obj, rs_id)
    _drain_both(py, rs)
    assert len(py.stack) == 0 and rs.stack_size() == 0

    assert py.players[1].life == py_p1_life0 - 1, "p1 loses 1 (Python)"
    assert py.players[0].life == py_p0_life0 + 1, "p0 gains 1 (Python)"
    assert rs.get_life(1) == rs_p1_life0 - 1, "p1 loses 1 (Rust)"
    assert rs.get_life(0) == rs_p0_life0 + 1, "p0 gains 1 (Rust)"

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Fear of Lost Teeth DIES sequence drain must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )
