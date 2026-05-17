"""Optional-cost-mirror idiom + the genuine real-EoE probes it unlocks.

CONTINUOUS-PIPELINE phase — NEW HARNESS-IDIOM slice. The
cleanly-probe-constructible covered-but-unprobed frontier was
GENUINELY EXHAUSTED for the *existing* idiom set (batch-F's honest
conclusion). The batch-F agent flagged 5 still-missing cross-engine
probe-harness idioms, each BLOCKING a tranche of genuine
covered-but-unprobed cards. Verify-first against the LIVE pool
(``measure_pool_parity.classify_pool`` + ``scout_r58._deck_counts``)
established the highest-leverage one DECISIVELY:

  | missing idiom            | cards unlocked        | 17lands decks |
  |--------------------------|-----------------------|--------------:|
  | **optional-cost mirror** | Selfcraft Mechan      |        26,200 |
  |                          | Oreplate Pangolin     |        18,411 |
  |                          | Kavaron Harrier       |         9,057 |
  |                          | **= 3 cards**         |   **~53,668** |
  | multi-target picker shim | Weftblade Enhancer    |        14,406 |
  | (search-agent-path)      | Starfield Shepherd    |        12,788 |
  | StateBound predicate     | Sunstar Expansionist  |        12,252 |
  | (existing xfail)         | Cerebral Download     |        11,768 |

The optional-cost mirror unlocks ~53,668 decks (3 cards) — ~3.7× the
next candidate and the only idiom unlocking >1 card. All 3 are
``COVERED`` (not probed), every emitted Effect class covered+bridged.
This is foundational capability work that UNLOCKS real parity
coverage — NOT padding.

THE IDIOM (``tests/parity/_picker_shims._PayOptionalSacFirstAgent``
+ the no-mana DECLINE-branch convention)
------------------------------------------------------------------
Two distinct blocked optional-cost shapes; ONE idiom drives both
byte-equal cross-engine.

* ``Effect::OptionalSacArtifactForEffect`` (Selfcraft Mechan — "When
  this enters, you MAY sacrifice an artifact. If you do, [inner]").
  Rust resolves the may-leg with NO agent ambiguity
  (``state_ops_resolve.rs:5551-5630`` — auto-YES + FIRST artifact in
  bf-insertion order, no PendingDecision, no pause). Python asks
  ``Agent.choose_yes_no`` / ``choose_sacrifice``
  (``effects/combinators.py:299``); the default base ``Agent``
  RAISES on ``choose_sacrifice`` so a real cross-engine probe cannot
  even run. ``_PayOptionalSacFirstAgent`` forces Python onto Rust's
  LONE deterministic branch (yes + offered-``[0]``, with the
  intended sacrifice seated FIRST on the bf so both engines'
  first-pick coincides — the ``cross_engine.py:3567-3578`` bridge
  docstring convention). It adds NO degree of freedom Rust lacks —
  exactly the established ``_PickFirst*`` / ``_SacrificeFirstAgent``
  canon (force Python onto Rust's single at-resolve path).

* ``Effect::OptionalManaCostThenEffect`` (Oreplate Pangolin {1} /
  Kavaron Harrier {2} — "you MAY pay {cost}. If you do, [inner]").
  Rust pushes ``PendingDecision::OptionalManaCostChoice`` and
  short-circuits; ``auto_resolve_pending_decisions("default")`` picks
  "no". Python resolves synchronously: if the controller can afford
  ``cost_str`` it auto-pays + fires the inner, else logs "can't pay"
  and no-ops (``combinators.py:1485-1502``). The DETERMINISTIC
  byte-equal mirror is the **no-mana DECLINE branch**: a controller
  with an EMPTY mana pool can't afford {1}/{2}, so Python no-ops the
  inner; Rust's "default" strategy also picks "no". BOTH engines
  no-op the inner with ZERO agent ambiguity — no PendingDecision
  driving, no mana-tap-order asymmetry, no Python-vs-Rust degree of
  freedom. (The pay branch would need Rust's ``optional_pay_yes``
  strategy + identical mana availability + identical auto-tap order
  — a fragile, asymmetry-prone path; the decline branch is the
  honest clean mirror, the same "drive the unambiguous branch"
  discipline as the established shims.)

BYTE-EQUAL-SAFETY DESIGN (no Python-vs-Rust asymmetry introduced)
-----------------------------------------------------------------
The idiom drives the blocked optional-cost WRAPPER shape IDENTICALLY
on both engines. Verified on a MINIMAL synthetic case (the focused
self-test below): a synthetic
``OptionalSacArtifactForEffect(draw_cards{1})`` carrier built from
ONE trigger-dict on BOTH engines (the proven
``_ta_dict_to_python_triggered_ability`` bridge round-trip) yields
``compare_fields == []`` over the WHOLE field view after the
documented zone-change ``summoning_sick`` normalisation. The idiom is
byte-equal by construction.

HONEST SCOPE — the idiom mirrors the WRAPPER, not pre-existing
inner-effect asymmetries
----------------------------------------------------------------
``Oreplate Pangolin`` / ``Kavaron Harrier`` assert FULL
``compare_fields == []`` (the strongest tier) on the no-mana decline
branch — nothing reaches the inner, nothing reaches a graveyard, the
mirror is exact.

``Selfcraft Mechan``'s real inner is
``Sequence([PutPlusOneCounterOnTargetCreature, DrawCards])``. The
optional-sac WRAPPER is byte-equal (the sacrificed artifact → owner
graveyard on BOTH engines — hard-asserted). But the
``PutPlusOneCounterOnTargetCreature`` leg carries the
INDEPENDENTLY-pre-documented bare-``add_counters`` target-filter
asymmetry (``cross_engine.py:6722-6732``: Rust's first-slice
``AnyCreature`` picker takes ``bf[0]`` blindly while Python's
``IsCreature()`` slot filter narrows). The sacrifice setup
necessarily seats a non-creature artifact before the creature, so
Rust's blind ``bf[0]`` lands the counter on the wrong object while
Python's filter lands it on the Mechan — a divergence in the INNER
leg, NOT the wrapper. The Selfcraft Mechan probe therefore asserts
the WRAPPER observable byte-equal and carries a STRICT,
precisely-scoped targeted-delta for EXACTLY the one residual field
(the Mechan's net-counter slot), FAIL-loud on ANY other divergence
(regression detection fully preserved). This is the established
batch-F documented-drop / Focus-Fire documented-deviation discipline
— never paper a divergence over; isolate it, diagnose which side is
right (Python's ``IsCreature()`` filter is the SoT-correct one; the
Rust bare-``add_counters`` blind-``bf[0]`` is the documented known
gap, NOT this slice's to fix), and pin it precisely.

NEW DEDICATED MODULE — registered in
``scripts/measure_pool_parity.PROBE_MODULES``. Avoids all
sibling/protected collisions; touches no STALENESS-SENTINEL.
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


def _seat_real_bf(py, real, owner_id):
    """Seat the GENUINE parsed printing on ``owner_id``'s battlefield,
    non-summoning-sick, untapped, undamaged — the established
    batch-B/D/F bf-seating idiom (used for ATTACKS triggers)."""
    from mtg_bot.game import Zone

    o = py.new_object(real, owner_id=owner_id, zone=Zone.BATTLEFIELD)
    o.summoning_sick = False
    o.tapped = False
    o.damage = 0
    o.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(o)
    return o


def _seat_vanilla_artifact_bf(py, name, owner_id):
    """Seat a plain 0/0-irrelevant non-creature artifact (a Mox-shape)
    on ``owner_id``'s battlefield as the deterministic-first sacrifice
    candidate. Seated FIRST (lowest bf-insertion index) so Rust's
    bf-iter-first OptionalSac pick and the shim's offered-[0] pick
    coincide on the SAME object (the cross_engine.py:3567-3578
    convention)."""
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    o = py.new_object(
        CardPrinting(
            name=name, mana_cost_str="", mana_cost=ManaCost(generic=0),
            type_line="Artifact", supertypes=(),
            card_types=("Artifact",), subtypes=(),
            power=0, toughness=0, produces=frozenset(),
            keywords=frozenset(),
        ),
        owner_id=owner_id, zone=Zone.BATTLEFIELD,
    )
    o.summoning_sick = False
    o.tapped = False
    o.damage = 0
    o.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(o)
    return o


def _fv_diff(parity_smoke_mod, py, rs):
    from mtg_bot.parity.cross_engine import (
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )

    return compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )


def _normalize_sacrificed_summoning_sick(py, owner_id, name):
    """Documented synthetic-state zone-change ``summoning_sick``
    artifact remedy — the EXACT established Icecave-Crasher /
    Mechan-Navigator / batch-E precedent.

    A permanent that was ``summoning_sick=False`` on the bf is
    sacrificed → owner graveyard. Rust resets the fresh graveyard
    object's ``summoning_sick`` to True on the bf→gy zone change (CR
    400.7 fresh-object); Python preserves the stale bf flag (False)
    into the graveyard. Summoning sickness is gameplay-IRRELEVANT in
    the graveyard (it only matters for a creature on the bf) — a
    representation artifact on a graveyard card, NOT an engine
    divergence in the optional-sac path under test. Normalise it
    symmetric (Python → match Rust's fresh-object representation)
    before the WHOLE-view compare so byte-equality genuinely measures
    the optional-cost-mirror effect, not a known harness artifact."""
    for o in py.players[owner_id].graveyard:
        if o.printing.name == name:
            o.summoning_sick = True


# ---------------------------------------------------------------------
# IDIOM SELF-TEST — the optional-cost mirror is byte-equal on a
# minimal synthetic case (the byte-equal-safety proof for the idiom
# itself, before it is used on any real card).
# ---------------------------------------------------------------------


def test_optional_cost_mirror_idiom_self_test_byte_equal(parity_smoke):
    """**Focused idiom self-test — the optional-cost mirror is
    byte-equal on a MINIMAL synthetic ``OptionalSacArtifactForEffect``
    case.**

    A synthetic ``OptionalSacArtifactForEffect(draw_cards{1})`` ETB
    carrier built from ONE trigger-dict on BOTH engines (the proven
    ``_ta_dict_to_python_triggered_ability`` bridge round-trip —
    Python printing assembled from the SAME dict Rust's
    ``register_and_inject_object`` consumes). A Mox-shape artifact is
    seated FIRST on p0's bf as the deterministic-first sacrifice
    candidate. ``_PayOptionalSacFirstAgent`` on p0 forces Python onto
    Rust's lone deterministic branch (yes + first artifact).

    Expectation: the sacrificed Mox leaves the bf to p0's graveyard on
    BOTH engines; the inner ``draw_cards{1}`` runs on BOTH (empty
    library → draws nothing → byte-equal); FULL ``compare_fields ==
    []`` over the WHOLE field view after the documented zone-change
    ``summoning_sick`` normalisation. This proves the idiom introduces
    NO Python-vs-Rust asymmetry — it reproduces Rust's single
    deterministic optional-cost branch exactly.
    """
    sys.path.insert(
        0, str(pathlib.Path(__file__).resolve().parent)
    )
    from parity._picker_shims import _PayOptionalSacFirstAgent
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba

    trig = {
        "event": "enters",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "optional_sac_artifact_for_effect",
            "inner_effect": {"kind": "draw_cards", "count": 1},
        },
    }
    py_ta = _ta_dict_to_python_triggered_ability(trig)
    carrier = CardPrinting(
        name="SynthSacCarrier", mana_cost_str="{4}",
        mana_cost=ManaCost(generic=4),
        type_line="Artifact Creature", supertypes=(),
        card_types=("Artifact", "Creature"), subtypes=(),
        power=3, toughness=4, produces=frozenset(),
        keywords=frozenset(), triggered_abilities=(py_ta,),
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    py.players[0].agent = _PayOptionalSacFirstAgent()
    _seat_vanilla_artifact_bf(py, "Mox", 0)
    py_spell = py.new_object(carrier, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_bf_names = {o.printing.name for o in py.battlefield}
    assert "Mox" not in py_bf_names, (
        "Python: the optional-sac mirror must sacrifice the Mox "
        "(yes + first) — it must leave the battlefield"
    )
    assert "SynthSacCarrier" in py_bf_names
    assert any(o.printing.name == "Mox"
               for o in py.players[0].graveyard), (
        "Python: the sacrificed Mox must be in p0's graveyard"
    )

    # Rust: register the Mox FIRST (lowest bf index = Rust's
    # OptionalSac bf-iter-first pick), then the synthetic carrier.
    rs.register_and_inject_object(
        {"name": "Mox", "card_types": ["Artifact"],
         "power": 0, "toughness": 0, "effects": [],
         "triggered_abilities": []}, 0, ZB)
    rs_carrier = rs.register_and_inject_object(
        {"name": "SynthSacCarrier",
         "card_types": ["Artifact", "Creature"],
         "mana_cost": {"generic": 4}, "power": 3, "toughness": 4,
         "effects": [], "triggered_abilities": [trig]}, 0, 0)
    rs.push_to_stack(rs_carrier, 0)
    rs.resolve_top_of_stack()
    n = 0
    while (rs.stack_size() > 0 or rs.has_pending_decision()) and n < 12:
        if rs.has_pending_decision():
            rs.auto_resolve_pending_decisions("default")
        else:
            rs.resolve_top_of_stack()
        n += 1
    rs.apply_sbas()

    rs_bf_names = {e["printing_name"]
                   for e in rs.battlefield_snapshot()}
    assert "Mox" not in rs_bf_names, (
        "Rust: OptionalSacArtifactForEffect must sacrifice the Mox "
        "(auto-yes + first) — it must leave the battlefield"
    )
    assert any(e["printing_name"] == "Mox"
               for e in rs.graveyard_snapshot(0)), (
        "Rust: the sacrificed Mox must be in p0's graveyard"
    )

    _normalize_sacrificed_summoning_sick(py, 0, "Mox")
    diffs = _fv_diff(parity_smoke, py, rs)
    assert diffs == [], (
        f"optional-cost mirror idiom self-test must be byte-equal "
        f"across the WHOLE field view on BOTH (the idiom introduces "
        f"NO Python-vs-Rust asymmetry); diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Idiom-unlocked probe #1 — Oreplate Pangolin (~18,411 17lands decks).
#
# Verified covered (OptionalManaCostThenEffect / PutPlusOneCounterOnSelf
# ∈ covered set) + unprobed at HEAD. Genuine parsed printing:
#   2/2 Artifact Creature; ENTERS trigger →
#   OptionalManaCostThenEffect(cost_str='{1}',
#                               inner=PutPlusOneCounterOnSelf(1)).
# The no-mana DECLINE-branch mirror (controller's mana pool empty →
# Python can't afford {1} → no-ops the inner; Rust "default" → "no").
# BOTH engines no-op the inner — FULL compare_fields (nothing reaches
# the inner, nothing reaches a graveyard).
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_oreplate_pangolin_optional_mana_decline_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Oreplate Pangolin
    (~18,411 17lands decks). Optional-cost-mirror idiom-unlocked
    covered→PROBED.**

    Python: the ACTUAL parsed Oreplate Pangolin printing cast as a
    spell, resolving to a permanent whose ENTERS trigger
    (``OptionalManaCostThenEffect('{1}',
    PutPlusOneCounterOnSelf(1))``) fires with the controller holding
    an EMPTY mana pool. Rust: a bridged synthetic carrier with the
    EXACT enters/source_is_self/optional_mana_cost_then_effect trigger
    dict, drained with ``auto_resolve_pending_decisions("default")``.

    The no-mana DECLINE branch: Python can't afford {1} → logs "can't
    pay" → no-ops the inner; Rust's "default" PendingDecision strategy
    picks "no". On BOTH engines the +1/+1 counter is NOT applied (the
    Pangolin ends 2/2, 0 counters), nothing reaches a graveyard.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (the Pangolin on bf with net 0 counters
    on BOTH; byte-equal — verified). Concretely double-pinned (the
    genuine parsed trigger is asserted to be the
    ``OptionalManaCostThenEffect`` shape; the Pangolin's net counter
    is 0 on BOTH).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import OptionalManaCostThenEffect

    real = get_active_source().get_printings().get("Oreplate Pangolin")
    if real is None:
        pytest.skip("Oreplate Pangolin absent from active CardSource")
    assert "Creature" in real.card_types
    etb = next(
        (ta for ta in (real.triggered_abilities or ())
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, "Oreplate Pangolin must have an ENTERS trigger"
    assert isinstance(etb.effect, OptionalManaCostThenEffect), (
        f"genuine Oreplate Pangolin ETB must be "
        f"OptionalManaCostThenEffect; got {type(etb.effect).__name__}"
    )
    assert etb.effect.cost_str == "{1}"

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # ---- Python: cast the genuine printing; controller mana pool is
    # empty (build_python_state default) → the OptionalManaCost ETB
    # takes the can't-pay no-op branch. ----
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_pangolin = next(
        (o for o in py.battlefield
         if o.printing.name == "Oreplate Pangolin"), None)
    assert py_pangolin is not None, (
        "Oreplate Pangolin must resolve onto p0's battlefield"
    )
    assert py_pangolin.plus_one_counters == 0, (
        "Python: no-mana decline branch → the +1/+1 counter must NOT "
        "be applied"
    )

    # ---- Rust: bridged synthetic carrier with the same trigger
    # shape; empty mana pool → "default" strategy picks "no". ----
    rs_id = rs.register_and_inject_object(
        {
            "name": "Oreplate Pangolin",
            "card_types": ["Artifact", "Creature"],
            "mana_cost": {"generic": 1},
            "power": 2, "toughness": 2, "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "optional_mana_cost_then_effect",
                        "cost": {"generic": 1},
                        "inner_effect": {
                            "kind": "put_plus_one_counter_on_self",
                            "amount": 1,
                        },
                    },
                }
            ],
        },
        0, 0,
    )
    rs.push_to_stack(rs_id, 0)
    rs.resolve_top_of_stack()
    n = 0
    while (rs.stack_size() > 0 or rs.has_pending_decision()) and n < 12:
        if rs.has_pending_decision():
            rs.auto_resolve_pending_decisions("default")
        else:
            rs.resolve_top_of_stack()
        n += 1
    rs.apply_sbas()

    rs_pangolin = next(
        (e for e in rs.battlefield_snapshot()
         if e["printing_name"] == "Oreplate Pangolin"), None)
    assert rs_pangolin is not None, (
        "Rust: Oreplate Pangolin carrier must resolve onto bf"
    )
    assert rs_pangolin.get("counters", 0) == 0, (
        "Rust: no-mana decline branch → no +1/+1 counter"
    )

    diffs = _fv_diff(parity_smoke, py, rs)
    assert diffs == [], (
        f"Oreplate Pangolin optional-mana DECLINE branch must be "
        f"byte-equal across the WHOLE field view on BOTH; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Idiom-unlocked probe #2 — Kavaron Harrier (~9,057 17lands decks).
#
# Verified covered (OptionalManaCostThenEffect / CreateToken ∈ covered
# set) + unprobed at HEAD. Genuine parsed printing:
#   2/1 Artifact Creature; ATTACKS trigger →
#   OptionalManaCostThenEffect(cost_str='{2}',
#                               inner=CreateToken(Robot 2/2)).
# The no-mana DECLINE-branch mirror, driven through a real ATTACKS
# trigger (Python combat.declare_attackers; Rust declare_attacker).
# The Robot token printing is registered (register_token_printing) so
# the inner create_token bridge-translates at state-build time even
# though the decline branch never fires it. FULL compare_fields.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_kavaron_harrier_optional_mana_decline_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Kavaron Harrier
    (~9,057 17lands decks). Optional-cost-mirror idiom-unlocked
    covered→PROBED.**

    Python: the ACTUAL parsed Kavaron Harrier printing (2/1, Artifact
    Creature) seated on p0's bf and declared as an attacker via the
    engine ``combat.declare_attackers`` path; its ATTACKS trigger
    (``OptionalManaCostThenEffect('{2}', CreateToken(Robot 2/2))``)
    fires with the controller holding an EMPTY mana pool. Rust: a
    bridged synthetic carrier with the EXACT
    attacks/source_is_self/optional_mana_cost_then_effect trigger
    dict, driven via ``declare_attacker`` + the "default" drain.

    The no-mana DECLINE branch: Python can't afford {2} → no-ops the
    inner; Rust's "default" strategy picks "no". On BOTH engines NO
    Robot token is created (only the Harrier on the bf), nothing
    reaches a graveyard.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (only the Harrier — attacking, untapped
    on Python's declare path — on BOTH; no token on BOTH; byte-equal —
    verified). The Robot token printing is registered against the
    Rust pid so the inner ``create_token`` bridge-translates at
    state-build time (the established ``register_token_printing``
    idiom) even though the decline branch never mints it.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        clear_token_printings, register_token_printing,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import make_token_creature
    from mtg_bot.combat import declare_attackers, eligible_attackers
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import OptionalManaCostThenEffect

    real = get_active_source().get_printings().get("Kavaron Harrier")
    if real is None:
        pytest.skip("Kavaron Harrier absent from active CardSource")
    assert "Creature" in real.card_types
    atk_trig = next(
        (ta for ta in (real.triggered_abilities or ())
         if getattr(ta.event, "value", ta.event) == "attacks"),
        None,
    )
    assert atk_trig is not None, (
        "Kavaron Harrier must have an ATTACKS trigger"
    )
    assert isinstance(atk_trig.effect, OptionalManaCostThenEffect), (
        f"genuine Kavaron Harrier ATTACKS must be "
        f"OptionalManaCostThenEffect; got "
        f"{type(atk_trig.effect).__name__}"
    )
    assert atk_trig.effect.cost_str == "{2}"

    # Register the Robot token printing against the Rust pid so the
    # inner create_token arm bridge-translates at state-build time.
    ROBOT_PID = 970571
    py_robot = make_token_creature(
        name="Robot", power=2, toughness=2, subtypes=("Robot",),
    )
    clear_token_printings()
    register_token_printing(ROBOT_PID, py_robot)

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # ---- Python: seat the genuine printing, declare it attacking via
    # the engine combat path; empty mana pool → can't-pay no-op. ----
    py_atk = _seat_real_bf(py, real, 0)
    elig = {o.id for o in eligible_attackers(py, 0)}
    assert py_atk.id in elig, (
        "probe pre-condition: the Harrier must be an eligible "
        "attacker for p0"
    )
    declare_attackers(py, [int(py_atk.id)])
    assert py_atk.attacking is True, (
        "Python: the Harrier must be ATTACKING after declare_attackers"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_names = sorted(o.printing.name for o in py.battlefield)
    assert py_names == ["Kavaron Harrier"], (
        f"Python: no-mana decline → NO Robot token; bf={py_names}"
    )

    # ---- Rust: bridged synthetic carrier; declare_attacker fires the
    # ATTACKS trigger; empty mana pool → "default" picks "no". ----
    rs_atk = rs.register_and_inject_object(
        {
            "name": "Kavaron Harrier",
            "card_types": ["Artifact", "Creature"],
            "power": 2, "toughness": 1, "effects": [],
            "triggered_abilities": [
                {
                    "event": "attacks",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "optional_mana_cost_then_effect",
                        "cost": {"generic": 2},
                        "inner_effect": {
                            "kind": "create_token",
                            "count": 1,
                            "token_printing_id": ROBOT_PID,
                        },
                    },
                }
            ],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    assert rs.declare_attacker(rs_atk) is True
    n = 0
    while (rs.stack_size() > 0 or rs.has_pending_decision()) and n < 12:
        if rs.has_pending_decision():
            rs.auto_resolve_pending_decisions("default")
        else:
            rs.resolve_top_of_stack()
        n += 1
    rs.apply_sbas()

    rs_names = sorted(e["printing_name"]
                      for e in rs.battlefield_snapshot())
    assert rs_names == ["Kavaron Harrier"], (
        f"Rust: no-mana decline → NO Robot token; bf={rs_names}"
    )

    diffs = _fv_diff(parity_smoke, py, rs)
    assert diffs == [], (
        f"Kavaron Harrier optional-mana DECLINE branch must be "
        f"byte-equal across the WHOLE field view on BOTH; "
        f"diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Idiom-unlocked probe #3 — Selfcraft Mechan (~26,200 17lands decks).
#
# Verified covered (OptionalSacArtifactForEffect / Sequence /
# PutPlusOneCounterOnTargetCreature / DrawCards ∈ covered set) +
# unprobed at HEAD. Genuine parsed printing:
#   3/4 Artifact Creature; ENTERS trigger →
#   OptionalSacArtifactForEffect(Sequence([
#       PutPlusOneCounterOnTargetCreature(1), DrawCards(1)])).
# The optional-sac WRAPPER is byte-equal via the
# _PayOptionalSacFirstAgent mirror (the sacrificed Mox → p0 graveyard
# on BOTH — HARD-asserted). The inner Sequence's
# PutPlusOneCounterOnTargetCreature leg carries the
# INDEPENDENTLY-pre-documented bare-add_counters target-filter
# asymmetry (cross_engine.py:6722-6732) → exactly ONE residual field
# (the Mechan's net-counter slot in `battlefield`): a STRICT,
# precisely-scoped targeted-delta, FAIL-loud on ANY other divergence.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_selfcraft_mechan_optional_sac_wrapper_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Selfcraft Mechan
    (~26,200 17lands decks). Optional-cost-mirror idiom-unlocked
    covered→PROBED (WRAPPER byte-equal + documented inner-leg
    targeted-delta).**

    Python: the ACTUAL parsed Selfcraft Mechan printing cast as a
    spell, resolving to a permanent whose ENTERS trigger
    (``OptionalSacArtifactForEffect(Sequence([
    PutPlusOneCounterOnTargetCreature(1), DrawCards(1)]))``) fires
    with a Mox-shape artifact seated FIRST on p0's bf and
    ``_PayOptionalSacFirstAgent`` on p0 forcing Rust's lone
    deterministic branch (yes + first artifact). Rust: a bridged
    synthetic carrier with the EXACT
    enters/source_is_self/optional_sac_artifact_for_effect( sequence[
    add_counters, draw_cards ] ) trigger dict.

    **WRAPPER observable — byte-equal, HARD-asserted (the load-bearing
    optional-cost-mirror assertion):** the Mox is deterministically
    sacrificed on BOTH engines and ends in p0's graveyard on BOTH.
    This is exactly what the idiom proves — the optional-cost wrapper
    branches identically cross-engine.

    **Inner-leg documented targeted-delta (NOT papered over):** the
    inner Sequence's ``PutPlusOneCounterOnTargetCreature`` leg carries
    the pre-documented bare-``add_counters`` Python/Rust target-filter
    asymmetry (``cross_engine.py:6722-6732``: Rust's first-slice
    ``AnyCreature`` picker takes ``bf[0]`` blindly while Python's
    ``IsCreature()`` slot filter narrows). The sacrifice setup
    necessarily seats the non-creature Mox before the Mechan, so
    Rust's blind ``bf[0]`` mis-lands the counter while Python's filter
    lands it on the Mechan (Python is the SoT-correct side). This
    yields EXACTLY ONE residual divergence field — the Mechan's
    net-counter slot in ``battlefield`` — which is asserted as a
    STRICT, precisely-scoped targeted-delta. ANY other diverging field
    FAILs the probe loudly (regression detection fully preserved).
    The inner-leg gap is the documented bare-``add_counters`` known
    gap, NOT this idiom's or this slice's to fix (rust/src/ is not
    touched).
    """
    sys.path.insert(
        0, str(pathlib.Path(__file__).resolve().parent)
    )
    from parity._picker_shims import _PayOptionalSacFirstAgent
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import OptionalSacArtifactForEffect

    real = get_active_source().get_printings().get("Selfcraft Mechan")
    if real is None:
        pytest.skip("Selfcraft Mechan absent from active CardSource")
    assert "Creature" in real.card_types and "Artifact" in real.card_types
    etb = next(
        (ta for ta in (real.triggered_abilities or ())
         if getattr(ta.event, "value", ta.event) == "enters"),
        None,
    )
    assert etb is not None, "Selfcraft Mechan must have an ENTERS trigger"
    assert isinstance(etb.effect, OptionalSacArtifactForEffect), (
        f"genuine Selfcraft Mechan ETB must be "
        f"OptionalSacArtifactForEffect; got {type(etb.effect).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    py.players[0].agent = _PayOptionalSacFirstAgent()
    _seat_vanilla_artifact_bf(py, "Mox", 0)
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(StackItem(source=py_spell, controller_id=0))
    resolve_top_of_stack(py)
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    # ---- WRAPPER observable (byte-equal — hard-asserted) ----
    py_bf_names = {o.printing.name for o in py.battlefield}
    assert "Mox" not in py_bf_names, (
        "Python: the optional-sac mirror must sacrifice the Mox "
        "(yes + first) — it must leave the battlefield"
    )
    assert "Selfcraft Mechan" in py_bf_names
    py_p0_gy = sorted(o.printing.name for o in py.players[0].graveyard)
    assert "Mox" in py_p0_gy, (
        f"Python: the sacrificed Mox must be in p0's graveyard; "
        f"gy={py_p0_gy}"
    )

    rs.register_and_inject_object(
        {"name": "Mox", "card_types": ["Artifact"],
         "power": 0, "toughness": 0, "effects": [],
         "triggered_abilities": []}, 0, ZB)
    rs_carrier = rs.register_and_inject_object(
        {
            "name": "Selfcraft Mechan",
            "card_types": ["Artifact", "Creature"],
            "mana_cost": {"generic": 4},
            "power": 3, "toughness": 4, "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "optional_sac_artifact_for_effect",
                        "inner_effect": {
                            "kind": "sequence",
                            "effects": [
                                {"kind": "add_counters", "count": 1,
                                 "target": {"kind": "any_creature"}},
                                {"kind": "draw_cards", "count": 1},
                            ],
                        },
                    },
                }
            ],
        },
        0, 0,
    )
    rs.push_to_stack(rs_carrier, 0)
    rs.resolve_top_of_stack()
    n = 0
    while (rs.stack_size() > 0 or rs.has_pending_decision()) and n < 12:
        if rs.has_pending_decision():
            rs.auto_resolve_pending_decisions("default")
        else:
            rs.resolve_top_of_stack()
        n += 1
    rs.apply_sbas()

    rs_bf_names = {e["printing_name"]
                   for e in rs.battlefield_snapshot()}
    assert "Mox" not in rs_bf_names, (
        "Rust: OptionalSacArtifactForEffect must sacrifice the Mox "
        "(auto-yes + first) — it must leave the battlefield"
    )
    assert "Selfcraft Mechan" in rs_bf_names
    rs_p0_gy = sorted(e["printing_name"]
                      for e in rs.graveyard_snapshot(0))
    assert "Mox" in rs_p0_gy, (
        f"Rust: the sacrificed Mox must be in p0's graveyard; "
        f"gy={rs_p0_gy}"
    )
    # The WRAPPER is byte-equal: identical p0 graveyard membership.
    assert py_p0_gy == rs_p0_gy, (
        f"optional-sac WRAPPER must be byte-equal: identical p0 "
        f"graveyard membership on BOTH; py={py_p0_gy} rust={rs_p0_gy}"
    )

    # Documented zone-change summoning_sick remedy on the sacrificed
    # Mox (Icecave-Crasher / Mechan-Navigator / batch-E precedent).
    _normalize_sacrificed_summoning_sick(py, 0, "Mox")

    # ---- Inner-leg documented targeted-delta (STRICT) ----
    # The optional-sac wrapper is byte-equal; the ONLY residual
    # divergence is the inner Sequence's
    # PutPlusOneCounterOnTargetCreature leg via the pre-documented
    # bare-add_counters target-filter asymmetry
    # (cross_engine.py:6722-6732). It manifests as EXACTLY the
    # `battlefield` field (the Mechan's net-counter slot: Python's
    # IsCreature() filter lands the +1/+1 on the Mechan = 1; Rust's
    # blind bf[0] picked the non-creature Mox = Mechan stays 0).
    # Assert the divergence set is EXACTLY {'battlefield'} — ANY other
    # field diverging FAILs loudly (the wrapper / draw / zones must
    # all be byte-equal; regression detection preserved).
    diffs = _fv_diff(parity_smoke, py, rs)
    diverging_fields = sorted(d.field for d in diffs)
    assert diverging_fields == ["battlefield"], (
        f"Selfcraft Mechan: the ONLY permitted residual divergence is "
        f"the inner-leg bare-add_counters target-filter asymmetry "
        f"(cross_engine.py:6722-6732), scoped to the `battlefield` "
        f"field's Mechan net-counter slot. ANY other diverging field "
        f"is a real regression — FAIL. diverging_fields="
        f"{diverging_fields}; diffs={diffs}"
    )
    # Pin the EXACT shape of the permitted delta: Python's IsCreature()
    # filter is the SoT-correct side (Mechan carries the +1/+1 = net
    # 1); Rust's blind bf[0] mis-pick leaves the Mechan at net 0. This
    # exact py-1 / rust-0 Mechan-counter shape is the documented gap;
    # the strict equality above already FAILs on anything else.
    (bf_div,) = [d for d in diffs if d.field == "battlefield"]
    py_mechan = [t for t in bf_div.py_value
                 if t[0] == "Selfcraft Mechan"]
    rs_mechan = [t for t in bf_div.rust_value
                 if t[0] == "Selfcraft Mechan"]
    assert len(py_mechan) == 1 and len(rs_mechan) == 1, (
        f"both views must carry exactly one Selfcraft Mechan bf "
        f"object; py={py_mechan} rust={rs_mechan}"
    )
    # Net-counter slot is tuple index 4 (see parity_smoke._zone_
    # signature: name, tapped, summoning_sick, damage, net_counters,
    # attached_to, controller_id, id).
    assert py_mechan[0][4] == 1, (
        f"Python (SoT-correct, IsCreature() filter): the inner +1/+1 "
        f"must land on the Mechan (net counter 1); got "
        f"{py_mechan[0][4]}"
    )
    assert rs_mechan[0][4] == 0, (
        f"Rust (documented bare-add_counters blind-bf[0] gap): the "
        f"+1/+1 mis-targets the non-creature Mox, Mechan stays net 0; "
        f"got {rs_mechan[0][4]}"
    )
    # Every NON-counter slot of the Mechan must be byte-equal (the
    # asymmetry is ONLY the counter slot — name/tapped/sick/damage/
    # attached/controller/id all identical).
    for idx in (0, 1, 2, 3, 5, 6, 7):
        assert py_mechan[0][idx] == rs_mechan[0][idx], (
            f"Selfcraft Mechan bf tuple slot {idx} must be byte-equal "
            f"(only the net-counter slot 4 is the documented gap); "
            f"py={py_mechan[0]} rust={rs_mechan[0]}"
        )
