"""Codecracker Hound Cycle 3 — per-card real-EoE cross-engine byte-
equality probe (PROBED tier flip).

Codecracker Hound is a ``{2}{U}`` Creature — Dog (2/1, EoE — sourced
from ``data/edge_of_eternities.json``) with an ETB+self trigger and a
Warp keyword:

    "When this creature enters, look at the top two cards of your
    library. Put one into your hand and the other into your graveyard."
    "Warp {2}{U} (You may cast this card from your hand for its warp
    cost. Exile this creature at the beginning of the next end step,
    then you may cast it from exile on a later turn.)"

This module is the **load-bearing PROBED-tier flip evidence** for
Codecracker Hound after the multi-cycle DECLINED→ADMITTED transition:

  * **Cycle 1 (refined fold, commit ``bd37cca0``, 2026-05-24)** folded
    the bespoke ``LookAtTopTwoSplitHandGraveyard`` engine class into
    the parameterized ``LookTopNPutOneInHandRestToGraveyard(n=2,
    reveal_chosen=False)`` — the parser-CLAUDE-faithful path.
  * **Cycle 2 (admit-gate widen, commit ``278992d7``, 2026-05-24)**
    widened ``_python_ta_to_safe_dict`` to admit the 9th ENTERS+
    IsSelf safe-trigger leaf
    (``look_top_n_put_one_in_hand_rest_to_graveyard``) + threaded
    ``reveal_chosen=False`` through the bridge dict shape; the warp
    arm (``_printing_is_bridge_pure_warp_creature``) now ADMITS CH
    (warp-arm admit set 6 → 7).
  * **Cycle 3 (this lane)** ships the GENUINE real-EoE cross-engine
    byte-equality probe that flips CH ``covered_by_construction`` →
    PROBED in the pool-parity metric. Same shape + same strength bar
    as the recent per-card parity probes
    (``test_possibility_technician_parity.py``,
    ``test_boilerbilges_ripper_parity.py``,
    ``test_archenemys_charm_parity.py``,
    ``test_singularity_rupture_parity.py``).

**Probe avoids the warp_cost gate.** Like the sibling Warp-keyword-
card probes (Possibility Technician / Boilerbilges Ripper), this
module seats CH directly via the synthetic-test cast-without-cost
push_to_stack pipeline on the Rust side (bypassing the warp_cost +
normal-cost payment machinery) and manually moves the Python carrier
to bf + dispatches the ENTERS event. The warp_cost cast-from-exile
substrate is exercised in the SEPARATE ``test_probe_warp_admitted.py``
module (the per-card-parametrize add this same Cycle 3 lane lands at
the same time — that is the warp-cast / normal-cast lifecycle real-
EoE byte-equal probe pair). This module is the dedicated PROBED-tier
parity probe shape the pool-parity metric scanner credits.

**Resolve semantics — ``LookTopNPutOneInHandRestToGraveyard(n=2,
reveal_chosen=False)`` cross-engine.** Both engines split the resolve
into a "look + queue choice" phase + an "answer choice + apply"
phase, with auto-resolve picking the topmost card on both sides:

  * Python's ``LookTopNPutOneInHandRestToGraveyard.resolve`` with
    ``agent=None`` falls through to ``examined[0]`` (the topmost
    examined card) — that card moves to hand; the rest move to
    graveyard in popped order. ``reveal_chosen=False`` (Codecracker
    Hound's parser-emitted rider) suppresses Python's
    ``reveal_to_all`` log call on the chosen card — preserving the
    no-reveal observable byte-equal with Rust's no-reveal resolve.
  * Rust pushes ``PendingDecision::PickCardFromExaminedChoice`` at
    state_ops_resolve.rs:6387-6393 and short-circuits;
    ``resolve_top_of_stack`` auto-resolves via ``auto_resolve_pending
    "keep_all_on_top"`` strategy which picks ``cards[0]`` — the same
    topmost card. Rust's resolve never reveals (it has no
    ``reveal_chosen`` field).

Both engines converge on the post-resolve observable: one card to
hand + the remainder in graveyard + no ``publicly_known_to``
mutation.

**Library setup.** p0's library is seeded with 2 named fillers
(top-to-bottom = [CH Filler top, CH Filler deeper]). Post-trigger:
top goes to p0's hand; deeper goes to p0's graveyard; library is
empty. This is the canonical n=2 resolve shape — same as Commune
with Evil's n=4 in ``test_probe_covered_unprobed_p.py``, just at
``n=2`` and ``reveal_chosen=False``.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.library_lookat import (
    LookTopNPutOneInHandRestToGraveyard,
)


_PRINTINGS = get_active_source().get_printings()


# Skip Rust-engine probes if the extension isn't built — mirrors the
# project-wide policy for cross-engine probes.
_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module (the field-view
    builder lives there). Identical to the established pattern in
    ``test_possibility_technician_parity.py`` /
    ``test_territorial_bruntar_parity.py``."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# Zone constants (mirror Rust's u8 zone IDs used by
# ``register_and_inject_object``).
ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3
ZONE_EXILE = 5


# Canonical Codecracker Hound dict shape consumed by Rust's
# ``register_and_inject_object`` to build a synthetic carrier with the
# same ENTERS+IsSelf triggered ability as the real parsed printing.
# ``reveal_chosen`` is intentionally NOT included in the Rust dict —
# Rust's ``parse_effect`` arm at cards.rs:12042-12056 reads only ``n``
# (the field is structurally safe to emit but the bridge dict drives
# Python's reveal_chosen=False via the SAFE-TRIGGER recognizer path,
# not via this synthetic dict). The trigger ABILITY shape on the Rust
# side runs through ``effect_to_pydict`` ↔ ``_ta_dict_to_python_effect``
# in the safe-trigger admit pipeline — this dict ONLY needs ``n`` for
# Rust's parser to accept it.
_CH_PRINTING_DICT: dict = {
    "name": "Codecracker Hound (synthetic carrier)",
    "card_types": ["Creature"],
    "subtypes": ["Dog"],
    "power": 2,
    "toughness": 1,
    "mana_cost": {"generic": 2, "U": 1},
    "triggered_abilities": [
        {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "look_top_n_put_one_in_hand_rest_to_graveyard",
                "n": 2,
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# (1) Parser SoT — Codecracker Hound is parser-claimed and emits the
# expected ENTERS+IsSelf+LookTopNPutOneInHandRestToGraveyard(n=2,
# reveal_chosen=False) trigger shape (the Cycle-1 refined fold).
# ---------------------------------------------------------------------------


def test_codecracker_hound_parser_claims_card():
    assert "Codecracker Hound" in _PRINTINGS, (
        "Codecracker Hound must be parser-claimed by the active "
        "CardSource"
    )


def test_codecracker_hound_printed_attrs():
    """Pins the basic printing surface (cost, type, P/T, warp cost).

    Warp is modeled as a printing-level ``warp_cost`` attribute (a
    ManaCost) rather than as a string in ``keywords``. CH's warp cost
    equals its normal cost (``{2}{U}`` both) — the warp body still
    fires the at-end-step delayed-trigger exile sweep distinct from
    a normal cast, but cost-side they are identical."""
    p = _PRINTINGS["Codecracker Hound"]
    assert p.mana_cost_str == "{2}{U}"
    assert p.warp_cost_str == "{2}{U}"
    assert "Creature" in p.card_types
    assert "Dog" in p.subtypes
    assert p.power == 2
    assert p.toughness == 1
    # Warp cost present (the gate the probe is NOT closing — see
    # SEARCH_LIMITATIONS.md and the warp-keyword-card-probe convention
    # established by Possibility Technician + Boilerbilges Ripper).
    assert p.warp_cost is not None, (
        "Codecracker Hound must carry a parsed warp_cost — the "
        "warp_cost gate is intentionally NOT closed this cycle (the "
        "probe seats CH directly via push_to_stack to bypass it)"
    )


def test_codecracker_hound_enters_trigger_emits_lookn_with_reveal_chosen_false():
    """The Cycle-1 refined fold ensures Codecracker Hound's parsed
    ENTERS+IsSelf trigger emits
    ``LookTopNPutOneInHandRestToGraveyard(n=2, reveal_chosen=False)``
    — the n=2 + no-reveal observable that the Cycle-2 ``_python_ta_to_
    safe_dict`` widen + the bridge ``reveal_chosen`` field thread both
    depend on. Pin the shape here so parser drift surfaces immediately
    rather than silently downstream in the cross-engine probe."""
    from mtg_bot.effects.predicates import Event, IsSelf

    p = _PRINTINGS["Codecracker Hound"]
    enters_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.ENTERS
    ]
    assert len(enters_tas) == 1, (
        f"Codecracker Hound must have exactly 1 ENTERS triggered "
        f"ability; got {len(enters_tas)}"
    )
    (ta,) = enters_tas
    assert isinstance(ta.predicate, IsSelf), (
        f"ENTERS arm predicate must be IsSelf; got {type(ta.predicate).__name__}"
    )
    assert isinstance(ta.effect, LookTopNPutOneInHandRestToGraveyard), (
        f"ENTERS arm effect must be LookTopNPutOneInHandRestToGraveyard; "
        f"got {type(ta.effect).__name__}"
    )
    assert ta.effect.n == 2, (
        f"ENTERS arm effect must be n=2; got n={ta.effect.n}"
    )
    assert ta.effect.reveal_chosen is False, (
        f"ENTERS arm effect must be reveal_chosen=False (the Cycle-1 "
        f"refined fold preserves CH's no-reveal observable); got "
        f"reveal_chosen={ta.effect.reveal_chosen}"
    )


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — the dict shape Codecracker Hound's
# safe-trigger recognizer emits round-trips to the matching Python
# class instance. (Cycle 2 substrate pin is duplicated here so the
# per-card module is self-contained for the PROBED-tier evidence —
# the same bridge round-trip pin is also at
# ``test_codecracker_hound_substrate_cycle_1_refined.py`` Pin #3.)
# ---------------------------------------------------------------------------


def test_codecracker_hound_safe_trigger_bridge_round_trip():
    """The bridge dict shape emitted by ``_python_ta_to_safe_dict``
    for Codecracker Hound's ENTERS+IsSelf trigger reconstructs the
    matching Python ``LookTopNPutOneInHandRestToGraveyard(n=2,
    reveal_chosen=False)`` instance — the load-bearing round-trip the
    Cycle-2 widen depends on."""
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    p = _PRINTINGS["Codecracker Hound"]
    (ta,) = p.triggered_abilities
    d = trajectory._python_ta_to_safe_dict(ta)
    assert d is not None, (
        "Codecracker Hound's ENTERS+IsSelf trigger must be classified "
        "as a safe-dict by _python_ta_to_safe_dict (the Cycle-2 widen)"
    )
    rt = _ta_dict_to_python_effect(d["effect"])
    assert rt == LookTopNPutOneInHandRestToGraveyard(
        n=2, reveal_chosen=False,
    ), (
        f"bridge dict→Python round-trip must yield the matching n=2, "
        f"reveal_chosen=False instance; got {rt!r}"
    )
    assert rt == ta.effect, (
        "bridge round-trip must equal the parser-emitted effect "
        "(structural byte-equality contract)"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity — the Rust parser accepts the
# bridged trigger dict shape for the synthetic carrier the cross-
# engine probe uses.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_codecracker_hound_synthetic_dict():
    """Lockstep pin: Rust's parse_effect arm accepts the
    ``{"kind": "look_top_n_put_one_in_hand_rest_to_graveyard",
    "n": 2}`` dict shape on the Codecracker Hound-shape synthetic
    carrier. Mirrors the existing pin
    ``test_rust_parser_accepts_look_top_n_put_one_in_hand_in_
    triggered_ability`` in ``test_cross_engine_etb_triggers.py``;
    here the dict is wrapped in the full CH-shape printing the
    cross-engine probe uses."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(_CH_PRINTING_DICT)
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe — drives the
# ACTUAL parsed Codecracker Hound printing on Python and a bridged
# synthetic carrier on Rust. After firing the ENTERS+IsSelf ETB
# trigger, asserts the concrete zone observables (library shrinkage
# from 2 to 0, hand gains the chosen examined[0] card, graveyard gains
# the rest) plus the full ``compare_fields == []`` over the whole
# cross-engine field view.
#
# Scenario: CH pre-seated on p0's bf on both engines (via push_to_stack
# on Rust + manual hand→bf move + dispatch_event on Python — the
# established Warp-keyword-card-probe convention from Possibility
# Technician / Boilerbilges Ripper / Fanatic of the Harrowing).
# p0's library is seeded top-to-bottom = [top_filler, deeper_filler].
# The ETB trigger fires; agent=None on Python + "keep_all_on_top"
# on Rust both pick the topmost = top_filler → hand; deeper_filler →
# graveyard.
# ---------------------------------------------------------------------------


@_rust_skip
def test_cross_engine_real_eoe_codecracker_hound_etb_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Codecracker Hound ETB
    LookTopNPutOneInHandRestToGraveyard(n=2, reveal_chosen=False) path.
    PROBED tier flip (Cycle 3 closure marker — ``covered_by_construction``
    → PROBED).**

    Python: the ACTUAL parsed Codecracker Hound printing pre-seated on
    p0's battlefield (no cast path → bypasses both the warp cost path
    AND the normal cost path; the IsSelf-ENTERS trigger is fired by an
    explicit ``dispatch_event(Event.ENTERS, obj=ch)`` after seating).
    p0's library is seeded with top-to-bottom [top_filler,
    deeper_filler].

    Rust: bridged synthetic carrier carrying the same ENTERS+IsSelf
    trigger + ``look_top_n_put_one_in_hand_rest_to_graveyard`` effect
    dict at n=2; p0's library is seeded identically. The synthetic-
    test cast-without-cost push_to_stack path drives the cast (lands
    CH on bf + queues the ETB trigger + drains it).

    Assertion strength: **full ``compare_fields == []``** over the
    whole cross-engine field view (every zone, both players), PLUS
    the concrete zone observables (p0 library 2 → 0, p0 hand gains
    1 card = the topmost examined card, p0 graveyard gains 1 card =
    the deeper examined card; CH itself stays on bf on BOTH engines).

    The CH carrier's ``summoning_sick`` is normalised symmetric on
    both engines (Python's pre-seated bf object defaults to
    summoning_sick=True; Rust's ``register_and_inject_object``
    defaults to False — the Possibility Technician / Icecave
    Crasher / Genemorph Imago fixture-asymmetry idiom).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.actions import dispatch_event, resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.effects.predicates import Event, IsSelf

    real = _PRINTINGS.get("Codecracker Hound")
    if real is None:
        pytest.skip("Codecracker Hound absent from active CardSource")
    assert "Creature" in real.card_types

    # §2 source-of-truth: verify the genuine printing carries the
    # ENTERS+IsSelf+LookTopN(n=2, reveal_chosen=False) arm (the arm
    # the probe fires).
    self_etb_ta = next(
        (
            ta for ta in real.triggered_abilities
            if (
                ta.event is Event.ENTERS
                and isinstance(ta.predicate, IsSelf)
                and isinstance(ta.effect, LookTopNPutOneInHandRestToGraveyard)
                and ta.effect.n == 2
                and ta.effect.reveal_chosen is False
            )
        ),
        None,
    )
    assert self_etb_ta is not None, (
        "Codecracker Hound must carry an ENTERS+IsSelf+"
        "LookTopNPutOneInHandRestToGraveyard(n=2, reveal_chosen=False) "
        "arm (the parser-emitted shape post-Cycle-1 refined fold)"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZH = 0
    ZL = 1

    # Synthetic vanilla filler printings on the Python side (matching
    # the Rust register_and_inject_object dicts byte-for-byte).
    def _instant_printing(name: str) -> CardPrinting:
        return CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(generic=0, colored=(("U", 1),)),
            type_line="Instant",
            supertypes=(),
            card_types=("Instant",),
            subtypes=(),
            power=None,
            toughness=None,
            produces=frozenset(),
            keywords=frozenset(),
        )

    # ---- Probe strategy: seat CH in HAND on BOTH engines + drive
    # the cast via the synthetic-test push_to_stack pipeline (the
    # Boilerbilges Ripper / Possibility Technician precedent). The
    # synthetic-test push_to_stack path BYPASSES the cost-payment
    # machinery — neither the {2}{U} normal cost NOR the {2}{U} warp
    # cost is exercised. The resolve lands CH on bf AND queues the
    # ETB+IsSelf trigger; the trigger then resolves the look-top-2-
    # put-one-in-hand-rest-to-graveyard body.

    # ---- Python: seat the genuine parsed CH in p0's hand; seed
    # p0's library with [top_filler, deeper_filler] top-to-bottom.
    py_ch = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_ch)

    # Allocate library objects bottom-first so IDs align with Rust's
    # register-bottom-first convention (Rust pushes onto lib[0]).
    py_lib_deeper = py.new_object(
        _instant_printing("CH Filler deeper"),
        owner_id=0,
        zone=Zone.LIBRARY,
    )
    py_lib_top = py.new_object(
        _instant_printing("CH Filler top"),
        owner_id=0,
        zone=Zone.LIBRARY,
    )
    # Normalise summoning_sick=False on library cards (Python's
    # new_object defaults summoning_sick=True for cards-in-library
    # while Rust's register_and_inject_object defaults to False — the
    # Possibility Technician / Icecave Crasher / Genemorph Imago
    # fixture-asymmetry idiom).
    for _obj in (py_lib_top, py_lib_deeper):
        _obj.summoning_sick = False
    py.players[0].library.extend([py_lib_top, py_lib_deeper])

    # ---- Rust: seat the bridged synthetic CH carrier in p0's hand;
    # seed p0's library identically.
    #
    # Library-injection order: ``register_and_inject_object`` pushes
    # onto ``lib[0]`` (the TOP), so to build a library with top-to-
    # bottom = [top, deeper] we register deeper FIRST, then top.
    # Use the REAL printing's name on the Rust carrier so the
    # battlefield field-view tuple's name slot agrees byte-equal with
    # Python's actual parsed CH (post-resolve it'll be on the bf with
    # the matching name).
    ch_carrier_for_probe = dict(_CH_PRINTING_DICT)
    ch_carrier_for_probe["name"] = real.name
    rs_ch = rs.register_and_inject_object(
        ch_carrier_for_probe, 0, ZH,
    )
    rs_lib_deeper = rs.register_and_inject_object(
        {
            "name": "CH Filler deeper",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
        },
        0, ZL,
    )
    rs_lib_top = rs.register_and_inject_object(
        {
            "name": "CH Filler top",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
        },
        0, ZL,
    )
    rs.clear_summoning_sick_for_player(0)

    # Sanity: library top-to-bottom matches Python's order.
    rs_lib_check = [e["id"] for e in rs.library_snapshot(0)]
    assert rs_lib_check == [rs_lib_top, rs_lib_deeper], (
        f"Rust library top-to-bottom mismatch pre-trigger; got "
        f"{rs_lib_check}"
    )

    # Pre-cast sanity: no trigger fires during seeding (CH is in
    # hand, the library fillers are vanilla instants).
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # ---- Fire the cast on BOTH (synthetic-test cast-without-cost
    # path). ----
    #
    # **Python.** Move CH from hand → bf manually (the cast-
    # resolution zone change). Fire ENTERS via ``dispatch_event``;
    # the IsSelf trigger queues on the stack with the
    # LookTopNPutOneInHandRestToGraveyard bound; drain the stack to
    # resolve into the look-2-put-one-in-hand-rest-to-graveyard body.
    # Mirrors the Possibility Technician / Fanatic of the Harrowing
    # Python-side convention exactly.
    py.players[0].hand.remove(py_ch)
    py_ch.zone = Zone.BATTLEFIELD
    # summoning_sick=True matches the Rust cast-pipeline default
    # (CR 302.1 — permanents enter with summoning sickness).
    py_ch.summoning_sick = True
    py_ch.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_ch)
    dispatch_event(py, Event.ENTERS, label="enters", obj=py_ch)
    while py.stack:
        resolve_top_of_stack(py)
    from mtg_bot.turn import state_based_actions as py_sba
    py_sba(py)

    # **Rust.** Push CH onto the stack via ``push_to_stack`` (the
    # cast-without-cost synthetic-test pipeline). The spell-resolve
    # lands CH on bf, queues the ETB+IsSelf trigger, and the
    # trigger resolves into the look-top-2 Rust resolve arm at
    # state_ops_resolve.rs:6366-6394. ``resolve_top_of_stack`` auto-
    # resolves the PendingDecision::PickCardFromExaminedChoice via
    # auto_resolve_pending "keep_all_on_top" — picking cards[0] (the
    # topmost = top_filler).
    rs.push_to_stack(rs_ch, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Python observables. ----
    # Library should be empty (both examined cards moved: top → hand,
    # deeper → graveyard).
    py_lib_ids = [o.id for o in py.players[0].library]
    assert py_lib_ids == [], (
        f"Python: library must be empty post-resolve (both examined "
        f"cards moved); got {py_lib_ids}"
    )
    # Hand should contain exactly the top_filler (the agent=None path
    # falls through to examined[0]).
    py_hand_ids = [o.id for o in py.players[0].hand]
    assert py_hand_ids == [py_lib_top.id], (
        f"Python: hand must contain exactly [top_filler]; got "
        f"{py_hand_ids}"
    )
    # Graveyard should contain exactly the deeper_filler.
    py_gy_ids = [o.id for o in py.players[0].graveyard]
    assert py_gy_ids == [py_lib_deeper.id], (
        f"Python: graveyard must contain exactly [deeper_filler]; "
        f"got {py_gy_ids}"
    )
    # CH still on bf.
    assert py_ch in py.battlefield, "Python: CH must remain on bf"

    # ---- Rust observables. ----
    rs_lib_ids = [e["id"] for e in rs.library_snapshot(0)]
    assert rs_lib_ids == [], (
        f"Rust: library must be empty post-resolve; got {rs_lib_ids}"
    )
    rs_hand_ids = [e["id"] for e in rs.hand_snapshot(0)]
    assert rs_hand_ids == [rs_lib_top], (
        f"Rust: hand must contain exactly [top_filler]; got "
        f"{rs_hand_ids}"
    )
    rs_gy_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert rs_gy_ids == [rs_lib_deeper], (
        f"Rust: graveyard must contain exactly [deeper_filler]; got "
        f"{rs_gy_ids}"
    )
    rs_bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert rs_ch in rs_bf_ids, "Rust: CH must remain on bf"

    # ---- Full field-view byte-equality over the WHOLE state. ----
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Codecracker Hound ETB look-top-2-put-one-in-hand-rest-to-"
        f"graveyard must be byte-equal across the WHOLE field view on "
        f"BOTH engines; diffs={diffs}"
    )
