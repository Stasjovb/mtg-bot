"""Genuine real-EoE cross-engine byte-equality probes — batch D.

CONTINUOUS-PIPELINE phase: convert high-deck-count
``covered-by-construction`` EoE cards into the **strongest parity-
evidence tier** (``PROBED byte-equal`` per ``docs/POOL_PARITY.md`` /
``scripts/measure_pool_parity.py``) via genuine real-EoE cross-engine
probes.

WHAT EACH PROBE ASSERTS
-----------------------
Every probe drives the **ACTUAL parsed EoE printing** on the Python
side (``get_active_source().get_printings()[<card>]`` — NOT a synthetic
stub) against the bridged synthetic carrier on the Rust side
(``register_and_inject_object`` with the closed-vocab effect dict the
production bridge round-trips — the established Embrace-Oblivion /
Decode-Transmissions / Gravpack-Monoist cross-engine driving pattern;
the full Instant/Sorcery/non-creature is NOT loader-admitted) and
asserts **full ``compare_fields(...) == []``** — byte-equality across
the WHOLE cross-engine field view, the strongest Effect+bridge-level
evidence — after a real EoE deck context (the carrier resolved
end-to-end on both engines, the trigger / spell fired, the stack
drained). Made campaign-wide possible by the round-r70
``_zone_signature`` ``_net_counters`` counters-blindness fix.

> CAVEAT (mirrors ``docs/POOL_PARITY.md``): this is Effect+bridge-
> level byte-equality on a *controlled* cross-engine state, NOT
> full-game-trajectory parity. PROBED is the strongest evidence tier
> the campaign tracks; it is not a full random multi-turn game.

PARTITION DISCIPLINE (batch D — the band below batch C)
-------------------------------------------------------
Sibling agents own the disjoint batch A (odd-ranked,
``tests/test_probe_covered_unprobed_a.py``) + batch B (even-ranked,
``tests/test_probe_covered_unprobed_b.py``) + batch C
(``tests/test_probe_covered_unprobed_c.py``) + the spell-card-bridge
sweep (Radiant Strike / Depressurize,
``tests/test_probe_spell_card_bridge_admitted.py``); a Rust agent owns
Seedship Impact / Orbital Plunge. This module owns **batch D = the
NEXT deck-count band below C**: the highest-deck cleanly-probe-
constructible covered-but-unprobed cards NOT in any sibling/Rust set.
The covered-by-construction-but-unprobed list (computed read-only via
``scripts/measure_pool_parity.classify_pool`` +
``scripts/scout_r58_subsystem_attribution._deck_counts``, sorted by
17lands deck count desc) was verify-first-recomputed at live HEAD
``1b4af439``; every card below is (a) covered-by-construction, (b) NOT
individually probed, (c) NOT in batch A / B / C / the spell-card-
bridge module / the Rust-owned pair.

The 7 cards pinned here (deck counts at the verify-first walk):

  | rank | card                  | decks  | shape                       |
  |-----:|-----------------------|-------:|-----------------------------|
  |    ~ | Sami's Curiosity      | 21,813 | Sorcery Seq(Gain2, Lander)  |
  |    ~ | Divert Disaster       | 15,955 | Instant CounterTargetSpell  |
  |    ~ | Faller's Faithful     | 14,108 | ETB destroy+draw_if_undmgd  |
  |    ~ | Eusocial Engineering  | 12,909 | landfall → CreateToken Robot|
  |    ~ | Nanoform Sentinel     | 12,078 | becomes_tapped → untap other|
  |    ~ | Honor                 |  9,164 | Sorcery Seq(+1/+1 tgt, draw)|
  |    ~ | Mm'menon, Uthros Exile|  6,692 | other-artifact-ETB → +1/+1  |

DROPPED ON VERIFY (honest verify-first discipline):

  * **Cerebral Download** (~11,768) — its genuine ``spell_effect`` is
    a ``Sequence`` whose live cross-engine probe is the EXISTING
    ``test_cross_engine_cerebral_download_real_eoe_cast_xfails_on_
    sequence_surveil_then_draw`` KNOWN-divergence pin
    (``test_parity_smoke.py``). Driving it as a "byte-equal" probe
    would re-surface that already-tracked divergence — NOT a clean
    covered→PROBED conversion. Excluded (the divergence is owned by
    its existing xfail pin).
  * **Nutrient Block** (~19,858) — a ``leaves_battlefield`` /
    ``IsSelf`` → ``DrawCards`` trigger. NO established cross-engine
    LTB-trigger fire idiom exists in the harness (every established
    probe fires ENTERS / DIES / BECOMES_TAPPED / spell-resolve;
    LTB-on-self requires a bespoke off-bf-move dispatch idiom both
    engines agree on, which the harness does not provide). Dropped
    per the round-17/18/19 synthetic-only-when-the-harness-lacks-the-
    idiom precedent (same discipline as batch-C's Weftblade Enhancer
    drop); deferred to an LTB-fire-idiom slice.

All 7 picks assert **full ``compare_fields == []``** over the whole
cross-engine field view (the strongest tier). NEW dedicated module
(not added to ``tests/test_trajectory_parity.py`` nor the
batch_a / batch_b / batch_c / spell_card_bridge_admitted modules nor
the 6 ``test_audit_safe_trigger_*`` tests — those are owned/protected;
this module avoids all collision and touches no STALENESS-SENTINEL).
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
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there). Identical to ``test_parity_smoke.py``'s
    module-scoped fixture — copied here so this module is fully
    self-contained / collision-free with the owned test files."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


def _drain_both(py_state, rust_state):
    """Resolve the top of stack on both engines until both stacks are
    empty. Mirrors ``test_parity_smoke.py``'s ``_drain_stack_both``."""
    from mtg_bot.actions import resolve_top_of_stack

    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    while py_state.stack:
        resolve_top_of_stack(py_state)


def _kill_both(py_state, rust_state, py_obj, rust_obj_id):
    """Lethal-damage + SBA both engines so a DIES trigger fires.
    Mirrors the established Perigee Beckoner / batch-B dies-fire
    idiom."""
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
# Batch-D probe #1 — Sami's Curiosity (~21,813 17lands decks).
#
# Verified covered (``Sequence`` / ``GainLife`` / ``CreateToken`` ∈
# covered set) + unprobed at HEAD 1b4af439. Oracle:
#   "[Sorcery] {1}{W} — You gain 2 life. Create a Lander token."
# Parser → ``spell_effect = Sequence(GainLife(2), CreateToken(token=
# Lander artifact, tapped=False, each_player=False, count=1))``. The
# Lander pid is registered on Rust; Python seats intrinsic
# ``TOKEN_PRINTINGS["Lander"]`` (the established Beamsaw-Prospector
# token-pid idiom). Sequence + bare create_token, deterministic.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_samis_curiosity_gain_then_lander_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Sami's Curiosity
    (~21,813 17lands decks). Batch-D covered→PROBED.**

    Python: the ACTUAL parsed Sami's Curiosity printing on a
    ``StackItem`` (no targets). Rust: the bridged ``sequence[gain_life
    2, create_token(Lander pid)]`` synthetic Sorcery.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (p0 life +2 on BOTH; exactly one Lander on
    p0's bf on BOTH; p1 untouched).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import Sequence

    real = get_active_source().get_printings().get("Sami's Curiosity")
    if real is None:
        pytest.skip("Sami's Curiosity absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Sami's Curiosity spell_effect must be a Sequence; "
        f"got {type(se).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # Register the Lander token on Rust (pid = registry_size); seat the
    # intrinsic Python printing in p0's library so the STARTING field
    # view is symmetric (the genuine effect mints a FRESH Lander).
    lander_pid = rs.registry_size
    rs.register_and_inject_object(
        {"name": "Lander", "card_types": ["Artifact"],
         "supertypes": ["Token"], "mana_cost": {"generic": 0}},
        0, 1,
    )
    py_seed = py.new_object(
        TOKEN_PRINTINGS["Lander"], owner_id=0, zone=Zone.LIBRARY
    )
    py_seed.summoning_sick = False
    py.players[0].library.append(py_seed)

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    # ---- Python: genuine parsed Sami's Curiosity on a StackItem. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0
    assert py.players[0].life == py_p0_life0 + 2, "p0 gains 2 (Python)"
    assert py.players[1].life == py_p1_life0

    # ---- Rust: bridged sequence[gain_life 2, create_token]. ----
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Sami's Curiosity", "card_types": ["Sorcery"],
         "effects": [{"kind": "sequence", "effects": [
             {"kind": "gain_life", "amount": 2},
             {"kind": "create_token", "count": 1,
              "token_printing_id": lander_pid},
         ]}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    assert rs.get_life(0) == rs_p0_life0 + 2, "p0 gains 2 (Rust)"
    assert rs.get_life(1) == rs_p1_life0

    rust_n = sum(1 for e in rs.battlefield_snapshot()
                 if e["printing_name"] == "Lander")
    py_n = sum(1 for o in py.battlefield
               if o.printing.name == "Lander")
    assert rust_n == 1 == py_n, (
        f"Sami's Curiosity → exactly one Lander on BOTH; "
        f"rust={rust_n} py={py_n}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Sami's Curiosity gain-2-then-Lander must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-D probe #2 — Divert Disaster (~15,955 17lands decks).
#
# Verified covered (``CounterTargetSpell`` ∈ covered set) + unprobed
# at HEAD. Oracle:
#   "[Instant] {1}{U} — Counter target spell."
# Parser → ``spell_effect = CounterTargetSpell(filter_types=∅)``. The
# Rust ``counter_target_spell`` unit-variant arm picks the TOP stack
# item that isn't the counter's own source; Python's ``legal_targets``
# yields ``("stack", i)``. A benign vanilla creature spell ("Bait
# Spell") is seeded on the stack FIRST on BOTH engines; the counter
# resolves and counters it → the bait moves to its owner's graveyard.
# (The documented Python-only ``_is_uncounterable`` enforcement
# divergence does NOT apply — the bait carries no uncounterable flag
# and isn't a controller-protected creature spell, so both engines
# counter it byte-equal.)
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_divert_disaster_counter_target_spell_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Divert Disaster
    (~15,955 17lands decks). Batch-D covered→PROBED.**

    Python: the ACTUAL parsed Divert Disaster printing on a
    ``StackItem`` above a benign Bait Spell, target = ``("stack", 0)``.
    Rust: the bridged ``{"kind":"counter_target_spell"}`` synthetic
    Instant pushed above the bait (auto-picks the non-self stack
    item). The bait is countered → its owner's graveyard on BOTH.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (Bait Spell in p0's graveyard, Divert
    Disaster in p0's graveyard, both stacks empty, NO Bait on the bf
    — countered, never resolved — on BOTH engines byte-equal).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.generic.stack_control import CounterTargetSpell
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Divert Disaster")
    if real is None:
        pytest.skip("Divert Disaster absent from active CardSource")
    assert "Instant" in real.card_types
    se = real.spell_effect
    assert isinstance(se, CounterTargetSpell), (
        f"genuine Divert Disaster spell_effect must be "
        f"CounterTargetSpell; got {type(se).__name__}"
    )
    assert se.filter_types == frozenset(), (
        "Divert Disaster counters ANY spell (empty filter_types)"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0

    # ---- Python: seed a benign p0 Bait Spell on the stack, then the
    # genuine Divert Disaster ABOVE it controlled by p1 (countering
    # p0's spell). Distinct controllers → after both drain, p0's
    # graveyard holds EXACTLY the countered bait and p1's holds
    # EXACTLY Divert Disaster — one card per graveyard, so there is no
    # intra-graveyard insertion-ORDER ambiguity (the documented
    # counter-mechanism asymmetry: Python flips StackItem.countered +
    # routes at pop, Rust removes + routes inline — both byte-equal in
    # CONTENT; same-graveyard probes only differ in ordering, which
    # this distinct-controller setup structurally avoids). ----
    bait_printing = CardPrinting(
        name="DD Bait Spell", mana_cost_str="",
        mana_cost=ManaCost(generic=0), type_line="Creature",
        supertypes=(), card_types=("Creature",), subtypes=(),
        power=2, toughness=2, produces=frozenset(),
    )
    py_bait = py.new_object(bait_printing, owner_id=0, zone=Zone.STACK)
    py_bait.summoning_sick = False
    py.stack.append(StackItem(source=py_bait, controller_id=0))

    py_spell = py.new_object(real, owner_id=1, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=1,
                  targets=(("stack", 0),))
    )
    # Resolve the counter (stack top), then drain the (now-countered)
    # bait.
    resolve_top_of_stack(py)
    py_sba(py)
    while py.stack:
        resolve_top_of_stack(py)
        py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: seed the same p0 Bait Spell, then the p1 counter
    # above. ----
    rs_bait_id = rs.register_and_inject_object(
        {"name": "DD Bait Spell", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 0, ZH,
    )
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Divert Disaster", "card_types": ["Instant"],
         "effects": [{"kind": "counter_target_spell"}]}, 1, ZH,
    )
    rs.push_to_stack(rs_bait_id, 0)
    rs.push_to_stack(rs_spell_id, 1)
    assert rs.stack_size() == 2
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas()
    assert rs.stack_size() == 0

    # The bait was countered → it must NEVER have hit the bf.
    rs_bf = [e["printing_name"] for e in rs.battlefield_snapshot()]
    py_bf = [o.printing.name for o in py.battlefield]
    assert "DD Bait Spell" not in rs_bf and "DD Bait Spell" not in py_bf, (
        f"countered bait must NOT be on the bf on BOTH; "
        f"rust_bf={rs_bf} py_bf={py_bf}"
    )
    # p0 gy = exactly the countered bait; p1 gy = exactly the counter.
    rs_gy0 = [e["printing_name"] for e in rs.graveyard_snapshot(0)]
    py_gy0 = [o.printing.name for o in py.players[0].graveyard]
    rs_gy1 = [e["printing_name"] for e in rs.graveyard_snapshot(1)]
    py_gy1 = [o.printing.name for o in py.players[1].graveyard]
    assert rs_gy0 == py_gy0 == ["DD Bait Spell"], (
        f"p0 gy must be exactly the countered bait on BOTH; "
        f"rust={rs_gy0} py={py_gy0}"
    )
    assert rs_gy1 == py_gy1 == ["Divert Disaster"], (
        f"p1 gy must be exactly the resolved counter on BOTH; "
        f"rust={rs_gy1} py={py_gy1}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Divert Disaster counter-target-spell must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-D probe #3 — Faller's Faithful (~14,108 17lands decks).
#
# Verified covered (``DestroyTargetCreature`` ∈ covered set, via the
# round-56 RUST_TO_PYTHON_OVERRIDES mapping
# ``DestroyTargetCreatureThenDrawIfUndamaged`` → ``DestroyTarget
# Creature``) + unprobed at HEAD. Oracle:
#   "[Creature] 3/1 …
#    When this creature enters, destroy up to one OTHER target
#    creature. If that creature wasn't dealt damage this turn, its
#    controller draws two cards."
# Parser → ETB IsSelf → ``DestroyTargetCreature(draw_if_undamaged_
# amount=2, optional=True, exclude_self=True)``. The Rust
# ``destroy_target_creature_then_draw_if_undamaged`` payload arm maps
# EXACTLY to that parsed class (the cross_engine.py:8075 arm). A p1
# undamaged 2/2 is destroyed → its controller (p1) draws 2 (the
# printed text gives the draw to the victim's controller). The source
# enters on p0's bf so the opponent-scan never sees it (satisfies
# "OTHER target" structurally on BOTH).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_fallers_faithful_etb_destroy_then_draw_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Faller's Faithful
    (~14,108 17lands decks). Batch-D covered→PROBED.**

    Python: the ACTUAL parsed Faller's Faithful printing seated on
    p0's battlefield; its ETB IsSelf trigger (DestroyTargetCreature
    draw_if_undamaged=2) fires via ``_trigger_etb_abilities``. Rust:
    the bridged synthetic carrier with the enters/source_is_self/
    destroy_target_creature_then_draw_if_undamaged{draw_amount:2}
    trigger.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the undamaged 2/2 destroyed → p1's
    graveyard on BOTH; p1 — the victim's controller — draws 2 from a
    seeded library on BOTH; p0 untouched).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields, CardDef,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.destroy import DestroyTargetCreature
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Faller's Faithful")
    if real is None:
        pytest.skip("Faller's Faithful absent from active CardSource")
    assert "Creature" in real.card_types
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, "Faller's Faithful must have an ETB trigger"
    assert isinstance(etb.effect, DestroyTargetCreature), (
        f"genuine Faller's Faithful ETB must be DestroyTargetCreature;"
        f" got {type(etb.effect).__name__}"
    )
    assert etb.effect.draw_if_undamaged_amount == 2
    assert etb.effect.optional is True
    assert etb.effect.exclude_self is True

    # Two seeded library cards for p1 (the victim's controller draws 2
    # → make the draw observable + byte-equal: same printing, same
    # order on BOTH).
    filler = CardDef(name="FF Filler", card_type="Land",
                     mana_produced=("U",))
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=(),
        p1_library=("FF Filler", "FF Filler", "FF Filler"),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    rp = int(real.power) if real.power is not None else 3
    rt = int(real.toughness) if real.toughness is not None else 1

    # p1 (opponent) has a single undamaged vanilla 2/2 — the destroy
    # target on BOTH engines.
    py_vic = py.new_object(
        CardPrinting(
            name="FF Victim", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py_vic.damage = 0
    py.battlefield.append(py_vic)
    # The destroy leg targets at PUSH time via the source-controller's
    # agent; with a single opponent creature the pick is forced.
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "FF Victim", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: seat the GENUINE parsed printing on p0's bf, fire
    # its ETB IsSelf trigger. ----
    py_src = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_src.summoning_sick = False
    py_src.tapped = False
    py_src.damage = 0
    py_src.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_src)
    _trigger_etb_abilities(py, py_src)
    assert len(py.stack) == 1, (
        "Faller's Faithful ETB should be on the Python stack"
    )

    # ---- Rust: bridged synthetic carrier with the payload arm. ----
    rs_src = rs.register_and_inject_object(
        {
            "name": "Faller's Faithful",
            "card_types": ["Creature"],
            "power": rp, "toughness": rt,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": (
                            "destroy_target_creature_then_draw_"
                            "if_undamaged"
                        ),
                        "draw_amount": 2,
                    },
                }
            ],
        },
        0, ZB,
    )
    assert rs.stack_size() == 1, (
        "Faller's Faithful ETB should be on the Rust stack"
    )

    _drain_both(py, rs)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    rs_alive = any(e["id"] == rs_vic_id
                   for e in rs.battlefield_snapshot())
    py_alive = any(o.id == py_vic.id for o in py.battlefield)
    assert rs_alive is False and py_alive is False, (
        f"the undamaged 2/2 must be destroyed on BOTH; "
        f"rust_alive={rs_alive} py_alive={py_alive}"
    )
    # The victim's controller (p1) draws 2 (undamaged) on BOTH.
    assert rs.hand_sizes[1] == len(py.players[1].hand) == 2, (
        f"p1 (victim's controller) draws 2 (undamaged) on BOTH; "
        f"rust={rs.hand_sizes[1]} py={len(py.players[1].hand)}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Faller's Faithful ETB destroy+draw_if_undamaged must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs="
        f"{diffs}"
    )


# ---------------------------------------------------------------------
# Batch-D probe #4 — Eusocial Engineering (~12,909 17lands decks).
#
# Verified covered (``CreateToken`` ∈ covered set) + unprobed at HEAD.
# Oracle:
#   "[Enchantment] …
#    Landfall — Whenever a land you control enters, create a 2/2
#    colorless Robot artifact creature token."
# Parser → single ``Event.ENTERS`` landfall trigger (``And(Subject(
# IsLand()), Controlled(YOU))``) → ``CreateToken(token=Robot 2/2,
# tapped=False, each_player=False, count=1)``. Driven via the
# established ``_play_land`` (Python) / ``play_land`` (Rust) landfall
# idiom (Icecave Crasher batch-B) + the create_token Robot-pid idiom
# (Gravpack Monoist batch-B). A NEW carrier-type axis: the carrier is
# an ENCHANTMENT (not a creature) — exercises the bridge's
# non-creature permanent trigger path.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_eusocial_engineering_landfall_create_robot_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Eusocial Engineering
    (~12,909 17lands decks). Batch-D covered→PROBED.**

    Python: the ACTUAL parsed Eusocial Engineering printing (an
    ENCHANTMENT) seated on p0's battlefield; playing a Forest fires
    its landfall trigger → CreateToken(Robot 2/2). Rust: the bridged
    synthetic enchantment carrier with the enters/and(subject_is_land,
    controlled_by_you)/create_token(Robot pid) trigger.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (exactly one Robot on p0's bf on BOTH).
    The played-land ``summoning_sick`` slot is normalised symmetric
    before the WHOLE-view compare (Python ``_play_land`` seats it
    summoning-sick, Rust ``play_land`` does not — the documented
    synthetic-state fixture asymmetry, the Icecave-Crasher precedent,
    NOT the token-spawn under test).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.actions import _play_land
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.tokens import CreateToken
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import Zone

    real = get_active_source().get_printings().get("Eusocial Engineering")
    if real is None:
        pytest.skip("Eusocial Engineering absent from active CardSource")
    assert "Enchantment" in real.card_types
    assert len(real.triggered_abilities) == 1
    ta = real.triggered_abilities[0]
    assert ta.event == Event.ENTERS
    assert isinstance(ta.effect, CreateToken)
    assert ta.effect.token_printing.name == "Robot"
    assert ta.effect.tapped is False
    assert ta.effect.each_player is False
    assert ta.effect.count == 1

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0

    robot_pid = rs.registry_size
    rs.register_and_inject_object(
        {"name": "Robot", "card_types": ["Artifact", "Creature"],
         "supertypes": ["Token"], "power": 2, "toughness": 2,
         "mana_cost": {"generic": 0}},
        0, 1,
    )
    py_seed = py.new_object(
        TOKEN_PRINTINGS["Robot"], owner_id=0, zone=Zone.LIBRARY
    )
    py_seed.summoning_sick = False
    py.players[0].library.append(py_seed)

    # ---- Python: seat the GENUINE parsed enchantment on p0's bf. ----
    py_src = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_src.summoning_sick = False
    py_src.tapped = False
    py_src.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_src)

    # ---- Rust: bridged synthetic enchantment carrier. ----
    rs_src = rs.register_and_inject_object(
        {"name": "Eusocial Engineering",
         "card_types": ["Enchantment"],
         "triggered_abilities": [{
             "event": "enters",
             "predicate": {"kind": "and",
                           "left": {"kind": "subject_is_land"},
                           "right": {"kind": "controlled_by_you"}},
             "effect": {"kind": "create_token", "count": 1,
                        "token_printing_id": robot_pid}}]},
        0, ZB,
    )

    fp = CardPrinting(
        name="Forest", mana_cost_str="", mana_cost=ManaCost(),
        type_line="Basic Land — Forest", supertypes=("Basic",),
        card_types=("Land",), subtypes=("Forest",),
        power=None, toughness=None, produces=frozenset({"G"}),
    )
    py_f = py.new_object(fp, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_f)
    rs_f = rs.register_and_inject_object(
        {"name": "Forest", "card_types": ["Land"],
         "mana_produced": ["G"], "supertypes": ["Basic"]},
        0, ZH,
    )

    py.players[0].lands_played_this_turn = 0
    _play_land(py, 0, py_f.id)
    rs.play_land(rs_f, 0)
    assert len(py.stack) == 1 and rs.stack_size() == 1, (
        "the landfall trigger should land on BOTH stacks"
    )

    _drain_both(py, rs)
    assert len(py.stack) == 0 and rs.stack_size() == 0

    rust_n = sum(1 for e in rs.battlefield_snapshot()
                 if e["printing_name"] == "Robot")
    py_n = sum(1 for o in py.battlefield
               if o.printing.name == "Robot")
    assert rust_n == 1 == py_n, (
        f"Eusocial Engineering landfall → exactly one Robot on BOTH; "
        f"rust={rust_n} py={py_n}"
    )

    # Documented synthetic-state fixture asymmetry (Icecave-Crasher
    # precedent): normalise the played-Forest summoning_sick slot
    # symmetric before the WHOLE-view compare so byte-equality
    # genuinely measures the token-spawn.
    for o in py.battlefield:
        if o.printing.name == "Forest":
            o.summoning_sick = False

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Eusocial Engineering landfall → Robot must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-D probe #5 — Nanoform Sentinel (~12,078 17lands decks).
#
# Verified covered (``UntapTargetOtherPermanent`` ∈ covered set) +
# unprobed at HEAD. Oracle:
#   "[Artifact Creature] 3/2 …
#    Whenever this creature becomes tapped, untap another target
#    permanent."
# BECOMES_TAPPED leg, predicate ``IsSelf`` → ``UntapTargetOther
# Permanent()``. Driven via the established declare_attacker (Rust) /
# tap_permanent (Python) BECOMES_TAPPED idiom (Chrome Companion /
# Mechan Navigator batch-A). Exactly ONE other tapped permanent is
# seated for p0 on BOTH engines so the untap pick is FORCED +
# deterministic (Rust picks the first OTHER tapped permanent in
# ETB-order; Python filters ``o.id != source_id and o.tapped`` → the
# same single object on BOTH).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_nanoform_sentinel_becomes_tapped_untap_other_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Nanoform Sentinel
    (~12,078 17lands decks). Batch-D covered→PROBED.**

    Python: the ACTUAL parsed Nanoform Sentinel printing seated on
    p0's battlefield (already-tapped), tapped via ``tap_permanent``;
    its BECOMES_TAPPED IsSelf trigger (UntapTargetOtherPermanent)
    fires. Rust: the bridged synthetic carrier tapped via
    ``declare_attacker`` (→ Event::BecomesTapped).

    Exactly ONE OTHER tapped permanent is seated for p0 so the untap
    target is forced + deterministic on BOTH (Rust first-OTHER-tapped
    in ETB order; Python ``o.id != source_id and o.tapped``).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the other permanent goes tapped→UNtapped
    on BOTH; the Sentinel itself ends tapped on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.turn import tap_permanent as py_tap_permanent
    from mtg_bot.effects.generic.tap import UntapTargetOtherPermanent
    from tests.parity._picker_shims import _PickFirstLegalTargetAgent

    real = get_active_source().get_printings().get("Nanoform Sentinel")
    if real is None:
        pytest.skip("Nanoform Sentinel absent from active CardSource")
    assert "Creature" in real.card_types
    bt = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "becomes_tapped"),
        None,
    )
    assert bt is not None, (
        "Nanoform Sentinel must have a BECOMES_TAPPED trigger"
    )
    assert isinstance(bt.effect, UntapTargetOtherPermanent), (
        f"genuine Nanoform Sentinel BECOMES_TAPPED must be "
        f"UntapTargetOtherPermanent; got {type(bt.effect).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    rp = int(real.power) if real.power is not None else 3
    rt = int(real.toughness) if real.toughness is not None else 2

    # ONE other ALREADY-TAPPED vanilla permanent for p0 — the forced
    # untap target on BOTH.
    py_other = py.new_object(
        CardPrinting(
            name="NS Other", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=1, toughness=1, produces=frozenset(),
        ),
        owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_other.summoning_sick = False
    py_other.tapped = True
    py.battlefield.append(py_other)
    # The BECOMES_TAPPED trigger's UntapTargetOtherPermanent
    # requires_target() is True; Python picks the target at PUSH time
    # via the source-controller's agent (build_python_state seats
    # none → without this the targeted trigger fizzles unpushed — the
    # established Susurian-Voidborn batch-A targeted-trigger note).
    # Exactly ONE other tapped permanent is seated so legal_targets[0]
    # is unambiguous and mirrors Rust's first-OTHER-tapped ETB-order
    # pick.
    py.players[0].agent = _PickFirstLegalTargetAgent()
    rs_other_id = rs.register_and_inject_object(
        {"name": "NS Other", "card_types": ["Creature"],
         "power": 1, "toughness": 1}, 0, ZB,
    )
    rs.tap_object(rs_other_id)

    # Python: seat the GENUINE parsed printing on p0's bf.
    py_obj = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)

    # Rust: bridged synthetic carrier with the faithful source_is_self
    # BECOMES_TAPPED → untap_target_other_permanent trigger.
    rs_id = rs.register_and_inject_object(
        {
            "name": "Nanoform Sentinel",
            "card_types": ["Artifact", "Creature"],
            "power": rp, "toughness": rt,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "becomes_tapped",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "untap_target_other_permanent"
                    },
                }
            ],
        },
        0, ZB,
    )

    # The pre-tapped NS Other does NOT itself fire BECOMES_TAPPED
    # (it was tapped before the Sentinel arrived / via tap_object).
    assert rs.stack_size() == 0 and len(py.stack) == 0

    rs.clear_summoning_sick_for_player(0)
    assert rs.declare_attacker(rs_id) is True
    assert rs.stack_size() == 1, (
        "Rust: tapping Nanoform Sentinel must fire BECOMES_TAPPED"
    )
    py_tap_permanent(py, py_obj)
    assert len(py.stack) == 1, (
        "Python: tapping Nanoform Sentinel must fire BECOMES_TAPPED"
    )

    _drain_both(py, rs)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # The OTHER permanent is now UNtapped on BOTH.
    rs_other_tapped = next(
        e["tapped"] for e in rs.battlefield_snapshot()
        if e["id"] == rs_other_id
    )
    assert rs_other_tapped is False and py_other.tapped is False, (
        f"NS Other must be UNtapped on BOTH; "
        f"rust={rs_other_tapped} py={py_other.tapped}"
    )
    # The Sentinel itself ended tapped on BOTH (it became tapped).
    rs_self_tapped = next(
        e["tapped"] for e in rs.battlefield_snapshot()
        if e["id"] == rs_id
    )
    assert rs_self_tapped is True and py_obj.tapped is True, (
        "Nanoform Sentinel must be tapped on BOTH (it became tapped)"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Nanoform Sentinel BECOMES_TAPPED untap-other must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs="
        f"{diffs}"
    )


# ---------------------------------------------------------------------
# Batch-D probe #6 — Honor (~9,164 17lands decks).
#
# Verified covered (``Sequence`` / ``PutPlusOneCounterOnTargetCreature``
# / ``DrawCards`` ∈ covered set) + unprobed at HEAD. Oracle:
#   "[Sorcery] {1}{W} — Put a +1/+1 counter on target creature. Draw
#    a card."
# Parser → ``spell_effect = Sequence(PutPlusOneCounterOnTargetCreature
# (amount=1), DrawCards(1))``. The Rust bridge expresses
# PutPlusOneCounterOnTargetCreature via the ``add_counters`` arm
# (``{"kind":"add_counters","target":{"kind":"any_creature"},
# "count":1}`` → ``PutPlusOneCounterOnTargetCreature(amount=1)``). The
# +1/+1-on-target leg targets a p0-controlled creature (the
# add_counters AnyCreature first-slice picker scans the defender's bf;
# the ``_PickFirstControlledCreatureAgent`` is not used — Honor's
# target is "target creature" any side, and Rust's first-slice picker
# scans the SOURCE-controller's opponent's bf, so the target is seated
# on p1 and the same-opponent shim mirrors it).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_honor_counter_then_draw_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Honor (~9,164 17lands
    decks). Batch-D covered→PROBED.**

    Python: the ACTUAL parsed Honor printing on a ``StackItem`` with
    the chosen creature target (p1's creature — Rust's add_counters
    AnyCreature first-slice picker scans the source-controller's
    opponent's bf, the ``_PickFirstOpponentTargetAgent`` mirrors that
    same-side pick). Rust: the bridged ``sequence[add_counters(
    any_creature, 1), draw_cards 1]`` synthetic Sorcery.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the p1 creature carries net +1 counter
    on BOTH via the r70 ``_net_counters`` counters-aware
    ``_zone_signature``; p0 draws 1 from a seeded library on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields, CardDef,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnTargetCreature,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get("Honor")
    if real is None:
        pytest.skip("Honor absent from active CardSource")
    assert "Sorcery" in real.card_types
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Honor spell_effect must be a Sequence; "
        f"got {type(se).__name__}"
    )
    assert isinstance(se.effects[0], PutPlusOneCounterOnTargetCreature)

    spec = DeckSpec(
        card_defs=(CardDef(name="HN Filler", card_type="Land",
                           mana_produced=("U",)),),
        p0_library=("HN Filler", "HN Filler"),
        p1_library=("HN Filler", "HN Filler"),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 has a single vanilla 2/2 — the +1/+1 target on BOTH.
    py_vic = py.new_object(
        CardPrinting(
            name="HN Target", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "HN Target", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: genuine parsed Honor on a StackItem. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_vic.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # ---- Rust: bridged synthetic Sorcery. ----
    rs_spell_id = rs.register_and_inject_object(
        {"name": "Honor", "card_types": ["Sorcery"],
         "effects": [{"kind": "sequence", "effects": [
             {"kind": "add_counters",
              "target": {"kind": "any_creature"}, "count": 1},
             {"kind": "draw_cards", "count": 1},
         ]}]},
        0, 0,  # controller p0, ZONE_HAND
    )
    rs.push_to_stack(rs_spell_id, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # Concrete cross-engine observable: net +1 counter on the p1
    # creature on BOTH.
    assert py_vic.plus_one_counters == 1, (
        f"Python: target should carry 1 +1/+1 counter; "
        f"got {py_vic.plus_one_counters}"
    )
    rs_t = next(e for e in rs.battlefield_snapshot()
                if e["id"] == rs_vic_id)
    assert rs_t["counters"] == 1, (
        f"Rust: target should carry 1 counter; got {rs_t['counters']}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Honor +1/+1-on-target-then-draw must be byte-equal across "
        f"the WHOLE field view on BOTH (counters-aware "
        f"_zone_signature); diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Batch-D probe #7 — Mm'menon, Uthros Exile (~6,692 17lands decks).
#
# Verified covered (``PutPlusOneCounterOnTargetCreature`` ∈ covered
# set) + unprobed at HEAD. Oracle:
#   "[Creature] …
#    Whenever ANOTHER artifact you control enters, put a +1/+1 counter
#    on target creature."
# A board-wide OTHER-artifact-ETB trigger — predicate
# ``And(And(IsArtifact, ControlledByYou), Not(IsSelf))`` (verified
# live) → ``PutPlusOneCounterOnTargetCreature(amount=1)``. The Rust
# bridge mirrors the FAITHFUL composite predicate
# ``and(and(subject_is_artifact, controlled_by_you), not(
# source_is_self))`` (the Susurian-Voidborn batch-A composite-
# predicate idiom — Rust ``parse_predicate`` supports and / not /
# subject_is_artifact / controlled_by_you / source_is_self). A SECOND
# artifact entering for p0 (NOT the Mm'menon source) fires the trigger
# on BOTH; the +1/+1 lands on a p1 creature (add_counters AnyCreature
# first-slice picker scans the source-controller's opponent's bf).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_mmmenon_other_artifact_etb_counter_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Mm'menon, Uthros Exile
    (~6,692 17lands decks). Batch-D covered→PROBED.**

    Python: the ACTUAL parsed Mm'menon printing seated on p0's bf;
    a SECOND artifact entering for p0 fires its board-wide
    other-artifact-ETB trigger (And(And(IsArtifact, ControlledByYou),
    Not(IsSelf)) → PutPlusOneCounterOnTargetCreature(1)). Rust: the
    bridged synthetic carrier with the FAITHFUL composite predicate
    (and(and(subject_is_artifact, controlled_by_you), not(
    source_is_self))) → add_counters(any_creature, 1).

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the p1 creature carries net +1 counter on
    BOTH via the r70 ``_net_counters`` counters-aware
    ``_zone_signature``; the entered artifact + Mm'menon on p0's bf on
    BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import _trigger_etb_abilities
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnTargetCreature,
    )
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    real = get_active_source().get_printings().get(
        "Mm'menon, Uthros Exile"
    )
    if real is None:
        pytest.skip("Mm'menon absent from active CardSource")
    assert "Creature" in real.card_types
    etb = next(
        (ta for ta in real.triggered_abilities
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, "Mm'menon must have an ENTERS trigger"
    assert isinstance(etb.effect, PutPlusOneCounterOnTargetCreature), (
        f"genuine Mm'menon ETB must be "
        f"PutPlusOneCounterOnTargetCreature; got "
        f"{type(etb.effect).__name__}"
    )
    assert etb.effect.amount == 1

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    rp = int(real.power) if real.power is not None else 2
    rt = int(real.toughness) if real.toughness is not None else 2

    # p1 has a single vanilla 2/2 — the +1/+1 target on BOTH.
    py_vic = py.new_object(
        CardPrinting(
            name="MM Target", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Creature",
            supertypes=(), card_types=("Creature",), subtypes=(),
            power=2, toughness=2, produces=frozenset(),
        ),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_vic.summoning_sick = False
    py.battlefield.append(py_vic)
    # The +1/+1-on-target leg targets at PUSH time via the source-
    # controller's agent; single opponent creature → forced pick.
    py.players[0].agent = _PickFirstOpponentTargetAgent()

    rs_vic_id = rs.register_and_inject_object(
        {"name": "MM Target", "card_types": ["Creature"],
         "power": 2, "toughness": 2}, 1, ZB,
    )

    # ---- Python: seat the GENUINE parsed Mm'menon on p0's bf (its
    # OWN arrival does NOT fire — Not(IsSelf)). ----
    py_src = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_src.summoning_sick = False
    py_src.tapped = False
    py_src.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_src)

    # ---- Rust: bridged synthetic carrier with the FAITHFUL composite
    # predicate (Susurian-Voidborn and/not idiom). ----
    rs_src = rs.register_and_inject_object(
        {
            "name": "Mm'menon, Uthros Exile",
            "card_types": ["Creature"],
            "power": rp, "toughness": rt,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {
                        "kind": "and",
                        "left": {
                            "kind": "and",
                            "left": {"kind": "subject_is_artifact"},
                            "right": {"kind": "controlled_by_you"},
                        },
                        "right": {
                            "kind": "not",
                            "inner": {"kind": "source_is_self"},
                        },
                    },
                    "effect": {"kind": "add_counters",
                               "target": {"kind": "any_creature"},
                               "count": 1},
                }
            ],
        },
        0, ZB,
    )

    # Mm'menon's own arrival does NOT fire (Not(IsSelf)).
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # A SECOND artifact enters for p0 → fires the other-artifact-ETB
    # trigger on BOTH.
    py_art = py.new_object(
        CardPrinting(
            name="MM Artifact", mana_cost_str="",
            mana_cost=ManaCost(generic=0), type_line="Artifact",
            supertypes=(), card_types=("Artifact",), subtypes=(),
            power=None, toughness=None, produces=frozenset(),
        ),
        owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_art.summoning_sick = False
    py_art.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_art)
    _trigger_etb_abilities(py, py_art)

    rs.register_and_inject_object(
        {"name": "MM Artifact", "card_types": ["Artifact"]},
        0, ZB,
    )

    assert len(py.stack) == 1 and rs.stack_size() == 1, (
        f"the other-artifact-ETB trigger should land on BOTH stacks; "
        f"py={len(py.stack)} rust={rs.stack_size()}"
    )

    _drain_both(py, rs)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    assert py_vic.plus_one_counters == 1, (
        f"Python: target should carry 1 +1/+1 counter; "
        f"got {py_vic.plus_one_counters}"
    )
    rs_t = next(e for e in rs.battlefield_snapshot()
                if e["id"] == rs_vic_id)
    assert rs_t["counters"] == 1, (
        f"Rust: target should carry 1 counter; got {rs_t['counters']}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Mm'menon other-artifact-ETB +1/+1-on-target must be "
        f"byte-equal across the WHOLE field view on BOTH "
        f"(counters-aware _zone_signature); diffs={diffs}"
    )
