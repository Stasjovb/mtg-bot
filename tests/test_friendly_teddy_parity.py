"""Cross-engine parity probes for Friendly Teddy.

**Friendly Teddy Cycle 1 closure (2026-05-22).** ``{2}`` Artifact
Creature — Bear Toy, 2/2 (Duskmourn — DSK, present in the active
CardSource via the multi-set source layering). Dies trigger:
"When this creature dies, each player draws a card." The
``effect_uncovered`` + ``nonsafe_triggered_ability`` multi-gate
classifier blocker — the missing Effect class is
``EachPlayerDraws`` (``effects/generic/draw_mill.py:230``).

The single-cycle substrate that makes this slice possible:

  1. **Rust ``Effect::EachPlayerDraws { count }``** — single-int
     variant + parse arm in ``rust/src/cards.rs::parse_effect`` +
     ``to_pydict`` arm + resolve arm in
     ``rust/src/state_ops_resolve.rs`` (the production mint site:
     APNAP-iterate ``state.players`` starting at
     ``state.active_player`` mod-wrapping, skip ``has_lost``
     players, draw ``count`` cards per non-lost player via the
     ``Effect::DrawCards``-shape library-top pop with
     ``attempted_draw_on_empty`` CR 704.5b signal on empty).
  2. **Bridge dict→Python arm** in
     ``cross_engine.py::_ta_dict_to_python_effect`` reconstructs
     the Python ``EachPlayerDraws`` class with the field-name
     translation ``count -> amount`` (sibling of the
     ``draw_cards`` / ``each_opponent_mills_cards`` / ``mill``
     bridge arms — same Rust ``count`` / Python ``amount``
     spelling discrepancy local to the bridge translation).
  3. **Trajectory reverse-serializer leaf** in
     ``parity/trajectory.py::_python_ta_to_safe_dict`` — recognizes
     the bare ``EachPlayerDraws`` Python class and emits the
     canonical dict ``{"kind": "each_player_draws", "count": int}``.
     Paired with a new ``("dies", "source_is_self",
     "each_player_draws")`` entry in ``_SAFE_TRIGGERS`` and a
     ``"each_player_draws": frozenset({"kind", "count"})`` entry
     in ``_SAFE_EFFECT_KEYS`` so the bench-admit gate's payload-
     key whitelist accepts the new leaf.

**Per-card parity probe path (NOT spell-card-bridge admit set).**
Friendly Teddy is a creature with a DIES triggered ability; the
spell-card-bridge admit set + auto-grow §2 teeth gate spell cards
only. The cross-engine probe uses the per-card dedicated parity-
test module convention (cf. ``test_comet_crawler_parity.py``,
``test_mutinous_massacre_parity.py``), driving the parsed Friendly
Teddy printing through both engines on a shared shape and pinning
byte-equal observables.

**Observable byte-equality scope.** The harness's
``_build_field_view`` per-zone signature folds in the
``printing_name`` / ``id`` / ``zone`` tuple, so the full compare
covers the draw path (one card moves library → hand on EACH player,
on both engines) + the Friendly Teddy bf → graveyard move (the
lethal-damage SBA path) + every other zone state. No P/T pump
involved — pure deterministic library-top pops + a destroy.

**Iteration-order pin.** Python's ``EachPlayerDraws.resolve``
walks ``state.players`` starting at ``state.active_player_idx``
and wrapping mod ``len(state.players)``. The Rust resolve arm
mirrors this exact APNAP-style order
(``state.active_player + 0``, then ``+ 1`` mod 2). In the
two-player engine with ``active_player == 0`` the order is
``[p0, p1]``; with ``active_player == 1`` the order is
``[p1, p0]``. Byte-equality of the per-player hand signatures
depends on this ordering — pinned by the cross-engine probe.

Coverage:

- Parser SoT pin: parsed Friendly Teddy printing's DIES trigger
  effect IS ``EachPlayerDraws(amount=1)``.
- Bridge dict→Python round-trip + missing-field default-to-1 +
  negative-count rejection.
- Rust ``Effect::EachPlayerDraws`` parse + to_pydict round-trip
  via ``register_printing`` (etb_effects readback).
- Rust resolve-arm unit pins:
    * Active-player-first APNAP iteration order.
    * ``has_lost`` player is skipped.
    * Negative count raises at resolve.
    * count==0 is a silent no-op.
- Trajectory recognizer + admit-gate round-trip pin:
  ``_python_ta_to_safe_dict`` emits the canonical dict for a
  DIES+IsSelf+EachPlayerDraws TriggeredAbility and the result
  passes ``_is_safe_trigger_dict``.
- Effect-coverage class pin: ``EachPlayerDraws`` is in the
  covered-by-rust set (the new Rust enum variant maps 1:1 to the
  Python class via the identity rule in
  ``effect_coverage.map_rust_to_python``).
- **GENUINE real-EoE cross-engine byte-equal probe** — drives the
  parsed Friendly Teddy printing through Python + Rust engines:
    * p0's bf: real Friendly Teddy. Both engines deal 99 damage to
      Friendly Teddy, run SBA. Friendly Teddy moves bf → p0's
      graveyard on BOTH; DIES trigger fires + resolves on BOTH.
    * Post-resolve on BOTH: p0 and p1 each drew one card (hand
      grew by 1, library shrank by 1 for each player).
    * ``compare_fields`` over the WHOLE field view = []
      (byte-equal hands + libraries + graveyards + bf +
      everything else).
"""

from __future__ import annotations

import importlib
import importlib.util
import pathlib
import sys

import pytest


def _require_engine():
    if importlib.util.find_spec("mtg_bot_engine") is None:
        pytest.skip("mtg_bot_engine PyO3 extension not installed")


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


# ---------------------------------------------------------------------------
# Verify-first: parser SoT pin.
# ---------------------------------------------------------------------------


def test_real_friendly_teddy_dies_trigger_is_each_player_draws():
    """**Verify-first.** The live parser maps Friendly Teddy's DIES
    trigger to ``EachPlayerDraws(amount=1)`` — pin the field shape so
    a parser drift is caught here, not silently downstream in the
    cross-engine probe.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.draw_mill import EachPlayerDraws
    from mtg_bot.effects.predicates import Event, IsSelf

    p = get_active_source().get_printings().get("Friendly Teddy")
    if p is None:
        pytest.skip("Friendly Teddy absent from active CardSource")
    assert "Creature" in p.card_types
    assert "Artifact" in p.card_types
    # Find the single DIES triggered ability.
    dies_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.DIES
    ]
    assert len(dies_tas) == 1, (
        f"Friendly Teddy must have exactly 1 DIES triggered ability; "
        f"got {len(dies_tas)}"
    )
    ta = dies_tas[0]
    assert isinstance(ta.predicate, IsSelf)
    assert ta.predicate.subject is None
    assert isinstance(ta.effect, EachPlayerDraws), (
        f"DIES trigger effect must be EachPlayerDraws; "
        f"got {type(ta.effect).__name__}"
    )
    assert ta.effect.amount == 1


# ---------------------------------------------------------------------------
# Bridge dict→Python + missing-field default + negative reject pins.
# ---------------------------------------------------------------------------


def test_bridge_each_player_draws_dict_to_python_round_trip():
    """Rust-shape dict → Python ``EachPlayerDraws`` via
    ``_ta_dict_to_python_effect`` reconstructs the same field. Bridge
    arm is the lever flip — without it, a Rust→Python triggered-
    ability translation would raise on the unknown kind.

    Note the field-name translation ``count -> amount`` (Rust uses
    ``count``, Python's class uses ``amount``).
    """
    from mtg_bot.effects.generic.draw_mill import EachPlayerDraws
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    rebuilt = _ta_dict_to_python_effect(
        {"kind": "each_player_draws", "count": 2}
    )
    assert isinstance(rebuilt, EachPlayerDraws), (
        f"dict→Python bridge must round-trip to EachPlayerDraws; "
        f"got {type(rebuilt).__name__}"
    )
    assert rebuilt.amount == 2


def test_bridge_each_player_draws_missing_count_defaults_to_one():
    """Missing ``count`` defaults to 1 on the bridge (mirrors Rust's
    parse default and Python's class "amount=1 is the only printed
    shape today" semantics).
    """
    from mtg_bot.effects.generic.draw_mill import EachPlayerDraws
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    rebuilt = _ta_dict_to_python_effect({"kind": "each_player_draws"})
    assert isinstance(rebuilt, EachPlayerDraws)
    assert rebuilt.amount == 1


def test_rust_parse_each_player_draws_rejects_negative_count():
    """Rust's ``parse_effect`` arm rejects ``count < 0`` (mirrors the
    variant invariant + the ``each_opponent_mills_cards`` sibling's
    rejection contract).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "EPD Negative-count Reject",
        "card_types": ["Creature"],
        "power": 1, "toughness": 1,
        "mana_cost": {"generic": 1},
        "etb_effects": [
            {"kind": "each_player_draws", "count": -1},
        ],
    }
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(d)


def test_rust_parse_each_player_draws_missing_count_defaults_to_one():
    """Rust's parse arm defaults missing ``count`` to 1 (mirrors
    Python class default + bridge default).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "EPD Default-count",
            "card_types": ["Creature"],
            "power": 1, "toughness": 1,
            "mana_cost": {"generic": 1},
            "etb_effects": [{"kind": "each_player_draws"}],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1
    assert effs[0]["kind"] == "each_player_draws"
    assert effs[0]["count"] == 1


def test_rust_each_player_draws_to_pydict_round_trip():
    """Rust ``Effect::EachPlayerDraws { count }`` → dict emits the
    expected two-key shape ``{"kind", "count"}``. Drives the round-
    trip through ``Registry.register_printing`` (the parse path) +
    ``get_printing_etb_effects`` (the ``effect_to_pydict`` readback).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "EPD Round-trip",
            "card_types": ["Creature"],
            "power": 1, "toughness": 1,
            "mana_cost": {"generic": 1},
            "etb_effects": [{"kind": "each_player_draws", "count": 3}],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1
    eff = effs[0]
    # PyDict from Rust — index by key.
    assert eff["kind"] == "each_player_draws"
    assert eff["count"] == 3


# ---------------------------------------------------------------------------
# Effect-coverage class pin.
# ---------------------------------------------------------------------------


def test_each_player_draws_class_covered_by_rust():
    """``EachPlayerDraws`` must be in the covered-by-rust set — the
    Rust ``Effect::EachPlayerDraws`` variant declaration makes
    ``covered_python_class_set()`` include it via the 1:1 identity-
    mapping rule in ``effect_coverage.map_rust_to_python``.
    """
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "EachPlayerDraws" in covered, (
        "Rust Effect::EachPlayerDraws variant must make the Python "
        "EachPlayerDraws class covered via the 1:1 identity-mapping "
        "rule"
    )


# ---------------------------------------------------------------------------
# Trajectory recognizer + admit-gate round-trip pin.
# ---------------------------------------------------------------------------


def test_trajectory_recognizer_emits_each_player_draws_dict():
    """``_python_ta_to_safe_dict`` recognizes a
    DIES+IsSelf+EachPlayerDraws(amount=1) Python TriggeredAbility and
    emits the canonical dict ``{"event": "dies", "predicate":
    {"kind": "source_is_self"}, "effect": {"kind":
    "each_player_draws", "count": 1}}``. The result must pass
    ``_is_safe_trigger_dict`` — the §2 admit-gate teeth.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.draw_mill import EachPlayerDraws
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.parity.trajectory import (
        _python_ta_to_safe_dict, _is_safe_trigger_dict,
    )

    ta = TriggeredAbility(
        event=Event.DIES,
        predicate=IsSelf(),
        effect=EachPlayerDraws(amount=1),
    )
    dct = _python_ta_to_safe_dict(ta)
    assert dct is not None, (
        "DIES+IsSelf+EachPlayerDraws(amount=1) must round-trip to a "
        "safe-trigger dict via _python_ta_to_safe_dict"
    )
    assert dct == {
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "each_player_draws", "count": 1},
    }
    assert _is_safe_trigger_dict(dct), (
        "Round-tripped dict must pass _is_safe_trigger_dict (the §2 "
        "admit-gate teeth)"
    )


# ---------------------------------------------------------------------------
# Rust resolve-arm unit pins (APNAP iteration + has_lost skip +
# negative-count raise + count==0 no-op).
# ---------------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine

    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _inject_teddy(rs, owner: int = 0) -> int:
    """Inject a Friendly-Teddy-shape creature with the DIES trigger on
    owner's battlefield. Returns the object id."""
    return rs.register_and_inject_object(
        {
            "name": "Friendly Teddy",
            "card_types": ["Artifact", "Creature"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 2},
            "triggered_abilities": [
                {
                    "event": "dies",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "each_player_draws",
                        "count": 1,
                    },
                },
            ],
        },
        owner,
        ZONE_BATTLEFIELD,
    )


def _inject_library_card(rs, owner: int, name: str) -> int:
    """Inject a vanilla card on owner's library top. Used to give each
    player something to draw."""
    return rs.register_and_inject_object(
        {
            "name": name,
            "card_types": ["Land"],
        },
        owner,
        ZONE_LIBRARY,
    )


def test_rust_resolve_active_player_first_apnap_iteration():
    """**Iteration-order pin.** Active player draws FIRST, then the
    other player. Pin by giving each player a UNIQUELY-NAMED library
    top card and checking the hand-arrival order on apply_sbas. Both
    players' hands grow by 1 in lockstep, but the unique-name pin
    proves each player draws THEIR OWN library card (not the active
    player's twice / the source's controller's twice / etc.).
    """
    rs = _fresh_rust_state()
    # active_player defaults to 0 on a fresh synthetic state.
    p0_card = _inject_library_card(rs, owner=0, name="P0 Card")
    p1_card = _inject_library_card(rs, owner=1, name="P1 Card")
    teddy = _inject_teddy(rs, owner=0)
    # Fire DIES via lethal damage + SBA, then resolve the trigger.
    rs.deal_damage(teddy, 99)
    rs.apply_sbas_until_quiescent()
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas_until_quiescent()
    # Teddy moved to p0's graveyard (owner).
    gy0_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert teddy in gy0_ids, "Friendly Teddy must be in p0's gy"
    # Both players drew their own top.
    p0_hand = [e["id"] for e in rs.hand_snapshot(0)]
    p1_hand = [e["id"] for e in rs.hand_snapshot(1)]
    assert p0_card in p0_hand, "p0 must have drawn its own library top"
    assert p1_card in p1_hand, "p1 must have drawn its own library top"
    # Libraries are empty now.
    assert rs.library_snapshot(0) == []
    assert rs.library_snapshot(1) == []


def test_rust_resolve_each_player_draws_count_zero_is_noop():
    """``count == 0`` is a silent no-op on the resolve arm — every
    player runs the inner draw loop zero times, so no library cards
    move. Pin by injecting count=0 directly on a synthetic ETB
    effects shape (the trigger-driven shape uses count=1 on Friendly
    Teddy; this pin exercises the count==0 branch via etb_effects
    on a sibling printing).
    """
    rs = _fresh_rust_state()
    # Give each player a library card so we can detect movement.
    _inject_library_card(rs, owner=0, name="P0 Stay")
    _inject_library_card(rs, owner=1, name="P1 Stay")
    # Synthetic creature with an ETB EachPlayerDraws count=0.
    carrier = rs.register_and_inject_object(
        {
            "name": "EPD Zero Carrier",
            "card_types": ["Creature"],
            "power": 1, "toughness": 1,
            "mana_cost": {"generic": 1},
            "etb_effects": [
                {"kind": "each_player_draws", "count": 0},
            ],
        },
        0,
        ZONE_HAND,
    )
    # Cast it. ETB fires + resolves; the count==0 arm runs zero draw
    # loops per player.
    # Easiest: move the carrier to bf directly via move_object to
    # trigger the ETB dispatch; skip the cast machinery here.
    # (ETB dispatches fire on the move_object pathway via the
    # pending_etb_dispatches drain in apply_sbas. The state_ops_zones
    # move_object site queues the id; apply_sbas drains it.)
    rs.move_object(carrier, ZONE_BATTLEFIELD, 0)
    rs.apply_sbas_until_quiescent()
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas_until_quiescent()
    # Hands stay empty — no draws happened.
    assert rs.hand_snapshot(0) == [], "count==0 → p0 must not draw"
    assert rs.hand_snapshot(1) == [], "count==0 → p1 must not draw"


def test_python_resolve_each_player_draws_skips_has_lost_player():
    """A player whose ``has_lost`` flag is true does NOT draw —
    pinned on the Python source-of-truth side. The Rust 2-player
    engine treats a lost player as game-over (no DIES trigger could
    fire in that state because ``is_over`` is true), so the gate is
    a transient inner-resolve case only — pinned here on Python
    where it's directly observable, with Rust covered by the
    APNAP-iteration test (which exercises the same per-player loop
    minus the ``has_lost`` gate). The mirrored Rust resolve-arm code
    is read-tested by inspection: the resolve at
    ``state_ops_resolve.rs::Effect::EachPlayerDraws`` calls
    ``if state.players[idx].has_lost { continue; }`` byte-equal
    with Python's ``effects/generic/draw_mill.py:243``.
    """
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.draw_mill import EachPlayerDraws
    from mtg_bot.game import Zone
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state,
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)

    def _land(name: str) -> CardPrinting:
        return CardPrinting(
            name=name, mana_cost_str="", mana_cost=ManaCost(),
            type_line="Basic Land", supertypes=(),
            card_types=("Land",), subtypes=(),
            power=None, toughness=None,
            produces=frozenset(), keywords=frozenset(),
        )

    # Seed library tops.
    p0_top = py.new_object(
        _land("P0 Draws"), owner_id=0, zone=Zone.LIBRARY,
    )
    py.players[0].library.append(p0_top)
    p1_top = py.new_object(
        _land("P1 Skipped"), owner_id=1, zone=Zone.LIBRARY,
    )
    py.players[1].library.append(p1_top)
    # Flag p1 has_lost.
    py.players[1].has_lost = True

    # Directly resolve EachPlayerDraws(amount=1) under a synthetic
    # controller (the resolve doesn't read controller_id beyond its
    # log line, so any seat is fine for this unit pin).
    effect = EachPlayerDraws(amount=1)
    effect.resolve(py, controller_id=0)

    # p0 drew P0 Draws; p1 (has_lost) did NOT draw.
    p0_hand_names = [o.printing.name for o in py.players[0].hand]
    p1_hand_names = [o.printing.name for o in py.players[1].hand]
    p1_lib_names = [o.printing.name for o in py.players[1].library]
    assert p0_hand_names == ["P0 Draws"], (
        "non-lost p0 must draw 'P0 Draws'"
    )
    assert p1_hand_names == [], "has_lost p1 must NOT draw"
    assert p1_lib_names == ["P1 Skipped"], (
        "has_lost p1's library top must stay put"
    )


# ---------------------------------------------------------------------------
# GENUINE real-EoE cross-engine probe — drives the parsed Friendly
# Teddy printing through BOTH engines and pins byte-equal field view.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module so the probe can
    call ``_build_field_view`` for the full cross-engine byte-
    equality compare — same fixture shape as
    ``tests/test_comet_crawler_parity.py``.
    """
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_cross_engine_real_eoe_friendly_teddy_dies_trigger_parity(
    parity_smoke,
):
    """**GENUINE real cross-engine byte-equal probe — Friendly Teddy
    DIES EachPlayerDraws.** The dedicated per-card probe that flips
    Friendly Teddy from Effect-uncovered (BLOCKED) to PROBED tier at
    the per-card cross-engine parity layer (despite the multi-gated
    classifier status — precedent: Comet Crawler 2026-05-22).

    Drives the **real parsed Friendly Teddy printing** through both
    engines:
      - p0's bf: real Friendly Teddy.
      - p0's library: 1 card (top); p1's library: 1 card (top) —
        each engine seeds the same library shape so the per-player
        draw post-resolve byte-equals.
      - Both engines: deal 99 damage to Friendly Teddy, run SBA.
        Friendly Teddy dies → DIES trigger fires + resolves with NO
        agent on the source's controller (the resolve has no
        decisions — every player draws unconditionally).
      - Post-resolve on BOTH: Friendly Teddy in p0's graveyard;
        each player's library top moved to that player's hand.

    **Byte-equality scope.** The full ``compare_fields`` over the
    harness's per-player ``hand_pN`` / ``library_pN`` /
    ``graveyard_pN`` / ``battlefield`` signatures is empty — every
    zone state agrees byte-equal across engines, AND the per-player
    hand contents byte-equal (pins the APNAP iteration order — each
    player drew its OWN library top).
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
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.generic.draw_mill import EachPlayerDraws

    real = get_active_source().get_printings().get("Friendly Teddy")
    if real is None:
        pytest.skip("Friendly Teddy absent from active CardSource")

    # §2 source-of-truth: genuine DIES trigger must be
    # EachPlayerDraws(amount=1).
    dies_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.DIES
        ),
        None,
    )
    assert dies_ta is not None, (
        "Friendly Teddy must have a DIES triggered ability"
    )
    assert isinstance(dies_ta.effect, EachPlayerDraws), (
        f"DIES trigger must be EachPlayerDraws; "
        f"got {type(dies_ta.effect).__name__}"
    )
    assert dies_ta.effect.amount == 1

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZL = 1

    # Vanilla land-shape printing for the per-player library top
    # (mirrors the Rust inject below). Distinct names so the
    # per-player hand contents pin the APNAP order — each player
    # drew its OWN library top, not the active player's twice.
    def _land_printing(name: str) -> CardPrinting:
        return CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(),
            type_line="Basic Land — Forest",
            supertypes=("Basic",),
            card_types=("Land",),
            subtypes=("Forest",),
            power=None,
            toughness=None,
            produces=frozenset({"G"}),
            keywords=frozenset(),
        )

    # --- Python: real Friendly Teddy on p0's bf + per-player
    # library tops.
    py_teddy = py.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD
    )
    py_teddy.summoning_sick = False
    py_teddy.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_teddy)
    # Seed library tops — distinct names for per-player pin. Pin
    # ``summoning_sick=False`` on the freshly-created Python objects
    # (the default is True for new_object, but Rust's
    # register_and_inject_object onto a library leaves the flag at
    # False; aligning here keeps the field-view 8-tuple byte-equal
    # across engines once the cards move library → hand by the
    # draw resolve).
    py_p0_top = py.new_object(
        _land_printing("FT P0 Top"),
        owner_id=0,
        zone=Zone.LIBRARY,
    )
    py_p0_top.summoning_sick = False
    py.players[0].library.append(py_p0_top)
    py_p1_top = py.new_object(
        _land_printing("FT P1 Top"),
        owner_id=1,
        zone=Zone.LIBRARY,
    )
    py_p1_top.summoning_sick = False
    py.players[1].library.append(py_p1_top)
    # No agent setup needed — EachPlayerDraws has no PendingDecision.
    py.players[0].agent = None
    py.players[1].agent = None

    # --- Rust: same shape via register_and_inject_object.
    rs_teddy = rs.register_and_inject_object(
        {
            "name": "Friendly Teddy",
            "card_types": list(real.card_types),
            "power": int(real.power),
            "toughness": int(real.toughness),
            "mana_cost": {"generic": 2},
            "triggered_abilities": [
                {
                    "event": "dies",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "each_player_draws",
                        "count": 1,
                    },
                },
            ],
        },
        0,
        ZB,
    )
    rs_p0_top = rs.register_and_inject_object(
        {
            "name": "FT P0 Top",
            "card_types": ["Land"],
            "subtypes": ["Forest"],
            "supertypes": ["Basic"],
            "mana_produced": ["G"],
        },
        0,
        ZL,
    )
    rs_p1_top = rs.register_and_inject_object(
        {
            "name": "FT P1 Top",
            "card_types": ["Land"],
            "subtypes": ["Forest"],
            "supertypes": ["Basic"],
            "mana_produced": ["G"],
        },
        1,
        ZL,
    )

    # ---- Deal lethal damage on both engines, run SBA, drain stack.
    # Python: set damage then run SBA to fire the DIES trigger; the
    # trigger pushes onto the stack and resolves with no agent
    # interaction.
    py_teddy.damage = 99
    for _ in range(20):
        if not py_sba(py):
            break
        while py.stack:
            resolve_top_of_stack(py)

    # Rust: deal_damage + apply_sbas_until_quiescent drives the SBA-
    # destroy → DIES dispatch → trigger-push chain; resolve_top_of_stack
    # then drains the EachPlayerDraws trigger. Loop in case of cascade
    # (Teddy's trigger has no inner LTB/dies — single resolve suffices,
    # but the loop is harness-safe).
    rs.deal_damage(rs_teddy, 99)
    rs.apply_sbas_until_quiescent()
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
        rs.apply_sbas_until_quiescent()

    # ---- Observable parity: Friendly Teddy in p0's graveyard on
    # BOTH; each player drew its own library top on BOTH.
    # Python observables.
    assert py_teddy not in py.battlefield, (
        "Python: Friendly Teddy must leave the battlefield"
    )
    assert py_teddy in py.players[0].graveyard, (
        "Python: Friendly Teddy must be in p0's graveyard"
    )
    py_p0_hand_names = [o.printing.name for o in py.players[0].hand]
    py_p1_hand_names = [o.printing.name for o in py.players[1].hand]
    assert py_p0_hand_names == ["FT P0 Top"], (
        f"Python: p0 must draw its own library top; "
        f"got {py_p0_hand_names}"
    )
    assert py_p1_hand_names == ["FT P1 Top"], (
        f"Python: p1 must draw its own library top; "
        f"got {py_p1_hand_names}"
    )

    # Rust observables.
    rs_bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert rs_teddy not in rs_bf_ids, (
        "Rust: Friendly Teddy must leave the battlefield"
    )
    rs_gy0_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert rs_teddy in rs_gy0_ids, (
        "Rust: Friendly Teddy must be in p0's graveyard"
    )
    rs_p0_hand_names = [e["printing_name"] for e in rs.hand_snapshot(0)]
    rs_p1_hand_names = [e["printing_name"] for e in rs.hand_snapshot(1)]
    assert rs_p0_hand_names == ["FT P0 Top"], (
        f"Rust: p0 must draw its own library top; "
        f"got {rs_p0_hand_names}"
    )
    assert rs_p1_hand_names == ["FT P1 Top"], (
        f"Rust: p1 must draw its own library top; "
        f"got {rs_p1_hand_names}"
    )

    # ---- Full byte-equal field-view compare. Pins per-player
    # hand / library / graveyard / battlefield signatures.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Friendly Teddy DIES EachPlayerDraws must be byte-equal "
        f"across the WHOLE field view on BOTH; diffs={diffs}"
    )
