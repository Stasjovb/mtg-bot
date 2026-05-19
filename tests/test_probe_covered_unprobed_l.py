"""Genuine real-EoE cross-engine byte-equality probes — batch L.

CONTINUOUS-PIPELINE phase: convert high-deck-count
``covered-by-construction`` EoE cards into the **strongest parity-
evidence tier** (``PROBED byte-equal`` per ``docs/POOL_PARITY.md`` /
``scripts/measure_pool_parity.py``) via genuine real-EoE cross-engine
probes.

Batch L partition: **BECOMES_TAPPED triggers + LANDFALL triggers**
(land-enters-controlled-by-you ``ENTERS`` event with
``And(Subject(IsLand), Controlled(YOU))`` predicate shape). Sibling
agent J owns sorceries; sibling K owns ETB triggers other than
landfall; this module owns the remaining covered-but-unprobed cards
whose primary trigger is BECOMES_TAPPED or LANDFALL.

WHAT EACH PROBE ASSERTS
----------------------------------------------------------------------
Every probe in this module:

  * drives the **ACTUAL parsed EoE printing** on the Python side
    (``get_active_source().get_printings()[<card>]``) — NOT a synthetic
    stub — so it pins THE CARD, not merely a bridge arm;
  * drives the bridged synthetic carrier on the Rust side
    (``register_and_inject_object`` with the closed-vocab effect dict
    the production bridge round-trips);
  * asserts **full ``compare_fields(...) == []``** — byte-equality
    across the WHOLE cross-engine field view, the strongest
    Effect+bridge-level evidence — after a real EoE deck context
    (the carrier resolved end-to-end on both engines, the trigger
    fired, the stack drained).

The canonical idiom mirrors the established genuine real-EoE probes:
real parsed ``triggered_abilities`` on Python, a bridged synthetic
carrier on Rust, ``compare_fields == []`` on a controlled real-EoE
state. UEOT modifiers (power/toughness bonuses) are also asserted
directly via ``effective_power`` / ``rs.effective_power`` because the
field-view ``_zone_signature`` does not capture transient UEOT state
(the established Icecave Crasher / Remnant Elemental pattern from
batch B).

> CAVEAT (mirrors ``docs/POOL_PARITY.md``): this is Effect+bridge-
> level byte-equality on a *controlled* cross-engine state, NOT
> full-game-trajectory parity.

CANDIDATE POOL EXHAUSTION (honest accounting)
----------------------------------------------------------------------
The covered-by-construction-but-unprobed list was filtered to cards
with a BECOMES_TAPPED trigger or a LANDFALL
(``ENTERS + And(Subject(IsLand), Controlled(YOU))``) trigger at the
batch-L verify-first walk (main c1019cb8).

**BECOMES_TAPPED covered candidates:**

  * **Cryoshatter** (Enchantment, ~Aura with IsHost predicate) —
    DROPPED. Cryoshatter's BECOMES_TAPPED trigger uses the
    ``IsHost`` predicate (``effects/predicates.py:440``: "the
    named subject IS the permanent this source is attached to").
    Rust's ``parse_predicate`` (``cards.rs:7752``) has NO
    ``is_host`` kind — the valid predicate vocabulary is:
    ``always, source_is_self, source_is_creature, subject_is_land,
    subject_is_artifact, subject_is_creature, controlled_by_you,
    subject_has_subtype, not, and, or``. A faithful Rust mirror is
    impossible without a new Rust substrate; dropped rather than
    ship an unfaithful synthetic.

  * All other BECOMES_TAPPED creatures in the EoE pool (Chrome
    Companion, Mechan Navigator, Nanoform Sentinel, Seedship
    Agrarian, Starfighter Pilot) are ALREADY individually PROBED at
    this HEAD — confirmed via ``scripts/measure_pool_parity.py``.

  * Two remaining BECOMES_TAPPED cards (Hemosymbic Mite,
    Swarm Culler) are in the BLOCKED tier (effect uncovered or
    Rust Effect absent) — not reachable from the covered tier.

**LANDFALL covered candidates:**

  * **Sunstar Expansionist** (Creature, 2/3) — CLEAN PROBE. The
    genuine printing carries two ``ENTERS`` triggers:

      - TA[0]: ``And(IsSelf, StateBound(OpponentControlsMoreLands
        ThanYou()))`` → ``CreateToken(Lander)`` — EXCLUDED from
        the Rust bridge dict because ``StateBound`` has no Rust
        predicate analog. However, TA[0]'s ``IsSelf`` predicate
        means it fires ONLY when Sunstar Expansionist itself
        enters; it does NOT fire when a land enters. Seating the
        creature directly on the battlefield (no cast path) and
        then playing a land therefore fires ONLY TA[1] on Python,
        matching the Rust side exactly. Partial-trigger-scope
        precedent: Seedship Agrarian probe (``test_parity_smoke.py``
        :62557) scopes out its second trigger identically.

      - TA[1]: ``And(Subject(IsLand), Controlled(YOU))`` →
        ``PumpSelfUntilEOT(power_bonus=1, toughness_bonus=0)``
        — the CLEAN landfall trigger. Drives via the established
        Eumidian Terrabotanist / Icecave Crasher landfall idiom.

  * All other LANDFALL creatures in the EoE pool (Eumidian
    Terrabotanist, Eusocial Engineering, Glacier Godmaw, Icecave
    Crasher, Icetill Explorer, Mightform Harmonizer, Remnant
    Elemental, Seedship Agrarian, Tannuk Memorial Ensign) are
    ALREADY individually PROBED at this HEAD.

  * Two remaining LANDFALL cards (Territorial Bruntar,
    Genemorph Imago) are in the BLOCKED tier (uncovered effect
    classes) — not reachable.

**Result: 1 clean probe from the entire BECOMES_TAPPED + LANDFALL
covered-but-unprobed surface.** All other candidates were either
already PROBED or could not produce a faithful byte-equal Rust mirror.
This is an honest exhaustion of the batch-L partition at HEAD c1019cb8.

PROBE SUMMARY
  1. Sunstar Expansionist (landfall → PumpSelfUntilEOT +1/+0)
     — covered-by-construction → PROBED

DROPPED-ON-VERIFY (documented above)
  - Cryoshatter: IsHost predicate has no Rust analog
  - Hemosymbic Mite: BLOCKED tier (PumpTargetOtherCreatureByXOver
    XWhereXIsSourcePower uncovered)
  - Swarm Culler: BLOCKED tier (OptionalSacAnotherForEffect
    uncovered)
  - Territorial Bruntar: BLOCKED tier (TerritorialBruntarLandfall
    Effect uncovered)
  - Genemorph Imago: BLOCKED tier (SetBasePTConditionalUntilEOT
    uncovered)
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


# Skip the whole module if the Rust extension isn't built — mirrors the
# ``tests/test_parity_smoke.py`` / ``tests_rust/conftest.py`` policy so
# a fresh checkout without maturin doesn't break the gate.
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


# ---------------------------------------------------------------------------
# Probe 1 — Sunstar Expansionist (landfall → PumpSelfUntilEOT +1/+0).
#
# Covered-by-construction tier, verified unprobed at HEAD c1019cb8.
#
# Oracle (``data/edge_of_eternities.json``):
#   "[Creature — Merfolk Scout] 2/3 ...
#    When this creature enters, if an opponent controls more lands
#    than you, create a Lander token.
#    Landfall — Whenever a land you control enters, this creature
#    gets +1/+0 until end of turn."
#
# Parser → two ENTERS triggered_abilities:
#   TA[0]: And(IsSelf, StateBound(OpponentControlsMoreLandsThanYou))
#          → CreateToken(Lander)   — EXCLUDED from Rust bridge
#   TA[1]: And(Subject(IsLand), Controlled(YOU))
#          → PumpSelfUntilEOT(power_bonus=1, toughness_bonus=0)   ← PROBE
#
# The probe ONLY exercises TA[1] (the landfall pump). TA[0] does NOT
# fire when a land enters (its IsSelf predicate rejects the Forest as
# subject — the predicate matches only when Sunstar itself is the
# entering subject). Pre-seating Sunstar on the battlefield (no cast
# path) prevents even TA[0]'s ETB gate from triggering. The Python and
# Rust sides are therefore observationally equivalent (only the landfall
# trigger fires on both), mirroring the Seedship Agrarian partial-
# trigger-scope precedent (``test_parity_smoke.py``:62557).
#
# Driving idiom: Eumidian Terrabotanist / Icecave Crasher landfall
# pattern — pre-seat the creature, inject a Forest into hand, play_land
# (Python: ``_play_land``; Rust: ``play_land``), drain both stacks.
#
# UEOT observable: ``effective_power`` asserted +1 above printed on
# BOTH before ``compare_fields`` (the established batch-B idiom; UEOT
# modifiers are not captured in ``_zone_signature``).
#
# Forest summoning_sick asymmetry: Python's ``_play_land`` seats the
# played land summoning-sick; Rust's ``play_land`` does not. Normalised
# to False on the Python Forest object before ``compare_fields`` so the
# byte-equality assertion measures the pump, not the fixture artifact
# (the established Icecave Crasher / Remnant Elemental idiom from batch
# B).
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_sunstar_expansionist_landfall_pump_self_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Sunstar Expansionist.
    Batch-L covered-by-construction → PROBED.**

    Python: the ACTUAL parsed Sunstar Expansionist printing pre-seated
    on p0's battlefield; a Forest is played into p0's hand and resolved
    via ``_play_land``. The landfall trigger (TA[1]:
    ``And(Subject(IsLand), Controlled(YOU))`` →
    ``PumpSelfUntilEOT(power_bonus=1, toughness_bonus=0)``) fires;
    TA[0]'s ``IsSelf`` gate silently does NOT match the entering Forest.

    Rust: bridged synthetic carrier carrying ONLY the landfall trigger
    (``{"kind": "and", "left": {"kind": "subject_is_land"}, "right":
    {"kind": "controlled_by_you"}}`` → ``{"kind":
    "pump_self_until_eot", "power_bonus": 1, "toughness_bonus": 0}``);
    tapped via ``play_land`` (→ ``play_land`` path, same as the
    established landfall idiom). TA[0]'s ``StateBound`` predicate is
    excluded from the Rust bridge — it has no ``state_bound`` analog in
    Rust's ``parse_predicate`` vocabulary and does not fire in this probe
    scenario.

    Assertion strength: **full ``compare_fields == []``** over the whole
    cross-engine field view (every zone, both players), PLUS the
    concrete UEOT observable (``effective_power == printed + 1`` on
    BOTH). Forest ``summoning_sick`` is normalised symmetric before the
    whole-view compare (Python/Rust fixture asymmetry, NOT the pump
    under test; the established Icecave Crasher batch-B precedent).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import _play_land, resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.object_predicates import IsLand
    from mtg_bot.effects.predicates import And, Controlled, Subject, YOU
    from mtg_bot.game import Zone, effective_power
    from mtg_bot.turn import state_based_actions as py_sba

    real = get_active_source().get_printings().get("Sunstar Expansionist")
    if real is None:
        pytest.skip("Sunstar Expansionist absent from active CardSource")
    assert "Creature" in real.card_types

    # §2 source-of-truth: verify the genuine printing has exactly the
    # LANDFALL trigger (TA[1]) this probe pins.
    landfall_ta = next(
        (
            ta for ta in real.triggered_abilities
            if (
                getattr(ta.event, "value", ta.event) == "enters"
                and isinstance(ta.effect, PumpSelfUntilEOT)
            )
        ),
        None,
    )
    assert landfall_ta is not None, (
        "Sunstar Expansionist must carry an ENTERS/PumpSelfUntilEOT "
        "landfall trigger"
    )
    assert landfall_ta.effect.power_bonus == 1, (
        f"genuine landfall must pump +1 power; "
        f"got {landfall_ta.effect.power_bonus}"
    )
    assert landfall_ta.effect.toughness_bonus == 0, (
        f"genuine landfall must pump +0 toughness; "
        f"got {landfall_ta.effect.toughness_bonus}"
    )
    assert landfall_ta.effect.granted_keywords == frozenset(), (
        "genuine landfall PumpSelfUntilEOT must grant no keywords"
    )
    # Verify the landfall predicate shape (subject_is_land + controlled_by_you).
    lf_pred = landfall_ta.predicate
    assert isinstance(lf_pred, And), (
        f"landfall predicate must be And; got {type(lf_pred).__name__}"
    )
    assert isinstance(lf_pred.left, Subject) and isinstance(
        lf_pred.left.inner, IsLand
    ), "left branch must be Subject(IsLand)"
    assert isinstance(lf_pred.right, Controlled) and lf_pred.right.by == YOU, (
        "right branch must be Controlled(by=YOU)"
    )

    rp = int(real.power) if real.power is not None else 2
    rt = int(real.toughness) if real.toughness is not None else 3

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0

    # ---- Python: pre-seat the GENUINE parsed printing on p0's bf.
    # No cast path → TA[0] (ETB+IsSelf gate) does NOT fire.
    py_src = py.new_object(real, owner_id=0, zone=Zone.BATTLEFIELD)
    py_src.summoning_sick = False
    py_src.tapped = False
    py_src.damage = 0
    py_src.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_src)

    # Inject a Forest into p0's hand (Python side).
    forest_printing = CardPrinting(
        name="Forest", mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Basic Land — Forest", supertypes=("Basic",),
        card_types=("Land",), subtypes=("Forest",),
        power=None, toughness=None, produces=frozenset({"G"}),
    )
    py_forest = py.new_object(forest_printing, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_forest)

    # ---- Rust: bridged synthetic carrier with ONLY the landfall
    # trigger (TA[0]'s StateBound is excluded — no Rust analog).
    rs_src = rs.register_and_inject_object(
        {
            "name": "Sunstar Expansionist",
            "card_types": ["Creature"],
            "power": rp, "toughness": rt,
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {
                        "kind": "and",
                        "left": {"kind": "subject_is_land"},
                        "right": {"kind": "controlled_by_you"},
                    },
                    "effect": {
                        "kind": "pump_self_until_eot",
                        "power_bonus": 1,
                        "toughness_bonus": 0,
                    },
                }
            ],
        },
        0, ZB,
    )

    # Inject a Forest into p0's hand (Rust side).
    rs_forest = rs.register_and_inject_object(
        {"name": "Forest", "card_types": ["Land"],
         "mana_produced": ["G"], "supertypes": ["Basic"]},
        0, ZH,
    )

    # Pre-trigger sanity: no trigger fires on injection (CR 701.21a —
    # entering is not "becoming tapped"; no land entered yet).
    assert rs.stack_size() == 0 and len(py.stack) == 0, (
        "no trigger should fire during pre-seat injection"
    )

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)

    # ---- Fire the landfall trigger by playing the Forest on BOTH. ----
    py.players[0].lands_played_this_turn = 0
    _play_land(py, 0, py_forest.id)
    rs.play_land(rs_forest, 0)

    assert len(py.stack) == 1, (
        "Python: landfall trigger should be on the stack after Forest "
        "enters (TA[0]/IsSelf rejects the Forest as subject — only "
        "the landfall TA[1] fires)"
    )
    assert rs.stack_size() == 1, (
        "Rust: landfall trigger should be on the stack after Forest enters"
    )

    # ---- Drain both stacks (resolves PumpSelfUntilEOT on BOTH). ----
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # Concrete UEOT observable: +1/+0 on the source on BOTH engines.
    py_ep = effective_power(py, py_src)
    rs_ep = rs.effective_power(rs_src)
    assert py_ep == rp + 1, (
        f"Python: Sunstar effective_power must be printed({rp}) + 1 "
        f"= {rp + 1}; got {py_ep}"
    )
    assert rs_ep == rp + 1, (
        f"Rust: Sunstar effective_power must be printed({rp}) + 1 "
        f"= {rp + 1}; got {rs_ep}"
    )

    # Life totals unchanged (PumpSelfUntilEOT touches no life).
    assert py.players[0].life == py_p0_life0, "p0 life unchanged (Python)"
    assert py.players[1].life == py_p1_life0, "p1 life unchanged (Python)"
    assert rs.get_life(0) == rs_p0_life0, "p0 life unchanged (Rust)"
    assert rs.get_life(1) == rs_p1_life0, "p1 life unchanged (Rust)"

    # Normalise the Forest's summoning_sick slot before the whole-view
    # compare: Python's ``_play_land`` seats the land summoning-sick;
    # Rust's ``play_land`` does not. This is a documented synthetic-
    # state fixture asymmetry (established Icecave Crasher / Remnant
    # Elemental batch-B idiom), NOT the pump under test.
    for o in py.battlefield:
        if o.printing.name == "Forest":
            o.summoning_sick = False

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Sunstar Expansionist landfall PumpSelfUntilEOT must be byte-"
        f"equal across the WHOLE field view on BOTH engines; diffs={diffs}"
    )
