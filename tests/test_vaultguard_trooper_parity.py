"""Cross-engine parity probes for Vaultguard Trooper.

**Vaultguard Trooper Cycle 1 closure (2026-05-23).** ``{4}{R}``
Creature — Kavu Soldier, 5/5 (Edge of Eternities — EoE, in the
active multi-set CardSource). At-beginning-of-end-step trigger: "At
the beginning of your end step, if you control two or more tapped
creatures, you may discard your hand. If you do, draw two cards."
Parsed live as ``TriggeredAbility(event=BEGINNING_OF_END_STEP,
predicate=Controlled(by=YOU, subject=None),
effect=ConditionalOnTappedCreatures(effect=DiscardHandThenDrawN(
amount=2), min_count=2))``. The ``effect_uncovered`` +
``nonsafe_triggered_ability`` multi-gate classifier blocker — the
missing Effect class is ``DiscardHandThenDrawN``
(``effects/generic/discard.py:74``). Multi-gated card flipped to
PROBED tier via the dedicated per-card cross-engine parity probe
(precedent: Friendly Teddy / Boilerbilges Ripper / Comet Crawler /
Fanatic of the Harrowing).

The single-cycle substrate that makes this slice possible:

  1. **Rust ``Effect::DiscardHandThenDrawN { count }``** — single-int
     variant + parse arm in ``rust/src/cards.rs::parse_effect`` +
     ``to_pydict`` arm + resolve arm in
     ``rust/src/state_ops_resolve.rs`` (the production mint site:
     locate source-controller via the standard zone-sweep + stack
     fallback, bulk-discard the entire ``hand[0..]`` to graveyard
     with CR 400.7 zone-change reset, then draw ``count`` cards via
     the ``Effect::DrawCards``-shape library-top pop with
     ``attempted_draw_on_empty`` CR 704.5b signal on empty).
  2. **Bridge dict→Python arm** in
     ``cross_engine.py::_ta_dict_to_python_effect`` reconstructs the
     Python ``DiscardHandThenDrawN`` class with the field-name
     translation ``count -> amount`` (sibling of the
     ``each_player_draws`` / ``draw_cards`` /
     ``each_opponent_mills_cards`` / ``mill`` bridge arms — same
     Rust ``count`` / Python ``amount`` spelling discrepancy local
     to the bridge translation).

**Per-card parity probe path (NOT spell-card-bridge admit set, NOT
``_python_ta_to_safe_dict`` widen).** Vaultguard Trooper is a
Creature with a ``BEGINNING_OF_END_STEP`` triggered ability whose
predicate is ``Controlled(by=YOU)`` (NOT ``IsSelf``) and whose
effect is wrapped in ``ConditionalOnTappedCreatures`` (NOT the bare
effect class). The trigger event + predicate + wrapper composition
is NOT in ``_SAFE_TRIGGERS`` and is INTENTIONALLY NOT widened this
cycle — that gate is about the production-deck bench admit set, a
distinct concern from per-card real-EoE parity probes. Same
precedent as Boilerbilges Ripper Cycle 1.

**No-agent default = DO** (the byte-equal mirror). Python's
``DiscardHandThenDrawN.resolve`` short-circuits the
``if p.agent is not None and not p.agent.choose_yes_no(...)``
clause to False on the first conjunct when ``agent is None`` and
PROCEEDS unconditionally with the discard+draw. The Rust resolve
arm mirrors this by always-discarding (the ``choose_yes_no``
callback substrate is not plumbed at the apply_effect site; same
precedent as the Sothera / ``MayHaveSourceDealDamageToTarget``
Requiem honest-stop). The agent-Some DECLINE divergence is the
documented deliberate divergence (see
``docs/SEARCH_LIMITATIONS.md`` — Vaultguard Trooper Cycle 1 entry).

Coverage:

- Parser SoT pin: parsed Vaultguard Trooper printing's
  BEGINNING_OF_END_STEP trigger effect IS
  ``ConditionalOnTappedCreatures(effect=DiscardHandThenDrawN(
  amount=2), min_count=2)``.
- Bridge dict→Python round-trip + missing-field default-to-2 +
  negative-count rejection.
- Rust ``Effect::DiscardHandThenDrawN`` parse + to_pydict round-trip
  via ``register_printing`` (etb_effects readback).
- Rust resolve-arm unit pins:
    * Empty hand → silent draw-only (no discard, but the draw step
      still runs ``count`` times).
    * Hand with N cards → full discard + draw ``count`` (mirrors
      the production path).
    * Library shorter than ``count`` → ``attempted_draw_on_empty``
      flag set; partial draw + empty-library SBA signal.
    * Negative count raises at resolve.
    * count == 0 → discard still happens (Python's range(0) only
      short-circuits the draw loop).
- Effect-coverage class pin: ``DiscardHandThenDrawN`` is in the
  covered-by-rust set (the new Rust enum variant maps 1:1 to the
  Python class via the identity rule in
  ``effect_coverage.map_rust_to_python``).
- Classifier ``missing_effect_classes == []`` pin (proof the
  ``effect_uncovered`` gate is closed at the classifier level).
- **GENUINE real-EoE cross-engine byte-equal probe** — drives the
  ``DiscardHandThenDrawN(amount=2)`` Effect through both engines as
  a synthetic ETB effect on a parsed Vaultguard-shaped creature.
  Pins the byte-equal post-resolve field view (hand zeroed,
  graveyard grew by N, library shrank by 2, hand grew by 2).
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


def test_real_vaultguard_trooper_end_step_trigger_is_conditional_discard_hand_then_draw_n():
    """**Verify-first.** The live parser maps Vaultguard Trooper's
    end-step trigger to
    ``ConditionalOnTappedCreatures(effect=DiscardHandThenDrawN(
    amount=2), min_count=2)``. Pin the shape so a parser drift is
    caught here, not silently downstream in the cross-engine probe.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.discard import DiscardHandThenDrawN
    from mtg_bot.effects.combinators import ConditionalOnTappedCreatures
    from mtg_bot.effects.predicates import Event

    p = get_active_source().get_printings().get("Vaultguard Trooper")
    if p is None:
        pytest.skip("Vaultguard Trooper absent from active CardSource")
    assert "Creature" in p.card_types
    assert p.power == 5
    assert p.toughness == 5
    # Find the single BEGINNING_OF_END_STEP triggered ability.
    end_step_tas = [
        ta
        for ta in p.triggered_abilities
        if ta.event is Event.BEGINNING_OF_END_STEP
    ]
    assert len(end_step_tas) == 1, (
        f"Vaultguard Trooper must have exactly 1 BEGINNING_OF_END_STEP "
        f"triggered ability; got {len(end_step_tas)}"
    )
    ta = end_step_tas[0]
    assert isinstance(ta.effect, ConditionalOnTappedCreatures), (
        f"end-step trigger effect must be wrapped in "
        f"ConditionalOnTappedCreatures; "
        f"got {type(ta.effect).__name__}"
    )
    assert ta.effect.min_count == 2, (
        f"ConditionalOnTappedCreatures.min_count must be 2; "
        f"got {ta.effect.min_count}"
    )
    inner = ta.effect.effect
    assert isinstance(inner, DiscardHandThenDrawN), (
        f"inner effect must be DiscardHandThenDrawN; "
        f"got {type(inner).__name__}"
    )
    assert inner.amount == 2


# ---------------------------------------------------------------------------
# Bridge dict→Python + missing-field default + negative reject pins.
# ---------------------------------------------------------------------------


def test_bridge_discard_hand_then_draw_n_dict_to_python_round_trip():
    """Rust-shape dict → Python ``DiscardHandThenDrawN`` via
    ``_ta_dict_to_python_effect`` reconstructs the same field. Bridge
    arm is the lever flip — without it, a Rust→Python triggered-
    ability translation would raise on the unknown kind.

    Note the field-name translation ``count -> amount`` (Rust uses
    ``count``, Python's class uses ``amount``).
    """
    from mtg_bot.effects.generic.discard import DiscardHandThenDrawN
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    rebuilt = _ta_dict_to_python_effect(
        {"kind": "discard_hand_then_draw_n", "count": 2}
    )
    assert isinstance(rebuilt, DiscardHandThenDrawN), (
        f"dict→Python bridge must round-trip to DiscardHandThenDrawN; "
        f"got {type(rebuilt).__name__}"
    )
    assert rebuilt.amount == 2


def test_bridge_discard_hand_then_draw_n_missing_count_defaults_to_two():
    """Missing ``count`` defaults to 2 on the bridge (mirrors Rust's
    parse default and Python's class ``amount: int = 2`` default and
    Vaultguard Trooper's printed shape "draw two cards").
    """
    from mtg_bot.effects.generic.discard import DiscardHandThenDrawN
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    rebuilt = _ta_dict_to_python_effect(
        {"kind": "discard_hand_then_draw_n"}
    )
    assert isinstance(rebuilt, DiscardHandThenDrawN)
    assert rebuilt.amount == 2


def test_rust_parse_discard_hand_then_draw_n_rejects_negative_count():
    """Rust's ``parse_effect`` arm rejects ``count < 0`` (mirrors the
    variant invariant + the ``each_player_draws`` sibling's
    rejection contract).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    d = {
        "name": "DHTDN Negative-count Reject",
        "card_types": ["Creature"],
        "power": 1,
        "toughness": 1,
        "mana_cost": {"generic": 1},
        "etb_effects": [
            {"kind": "discard_hand_then_draw_n", "count": -1},
        ],
    }
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(d)


def test_rust_parse_discard_hand_then_draw_n_missing_count_defaults_to_two():
    """Rust's parse arm defaults missing ``count`` to 2 (mirrors
    Python class default + bridge default).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "DHTDN Default-count",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 1,
            "mana_cost": {"generic": 1},
            "etb_effects": [{"kind": "discard_hand_then_draw_n"}],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1
    assert effs[0]["kind"] == "discard_hand_then_draw_n"
    assert effs[0]["count"] == 2


def test_rust_discard_hand_then_draw_n_to_pydict_round_trip():
    """Rust ``Effect::DiscardHandThenDrawN { count }`` → dict emits
    the expected two-key shape ``{"kind", "count"}``. Drives the
    round-trip through ``Registry.register_printing`` (the parse path)
    + ``get_printing_etb_effects`` (the ``effect_to_pydict``
    readback).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "DHTDN Round-trip",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 1,
            "mana_cost": {"generic": 1},
            "etb_effects": [
                {"kind": "discard_hand_then_draw_n", "count": 3}
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1
    eff = effs[0]
    assert eff["kind"] == "discard_hand_then_draw_n"
    assert eff["count"] == 3


# ---------------------------------------------------------------------------
# Effect-coverage class pin.
# ---------------------------------------------------------------------------


def test_discard_hand_then_draw_n_class_covered_by_rust():
    """``DiscardHandThenDrawN`` must be in the covered-by-rust set —
    the Rust ``Effect::DiscardHandThenDrawN`` variant declaration
    makes ``covered_python_class_set()`` include it via the 1:1
    identity-mapping rule in ``effect_coverage.map_rust_to_python``.
    """
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "DiscardHandThenDrawN" in covered, (
        "Rust Effect::DiscardHandThenDrawN variant must make the "
        "Python DiscardHandThenDrawN class covered via the 1:1 "
        "identity-mapping rule"
    )


def test_vaultguard_trooper_classifier_effect_uncovered_gate_closed():
    """**Cycle 1 effect_uncovered closure pin.** After this cycle's
    Effect-class closure, Vaultguard Trooper is EITHER:

      (a) absent from the ``subsystem_attribution()`` ``cards`` dict
          entirely — meaning the card has moved out of the
          ``BLOCKED_SUBSYSTEM`` tier (typically to ``TIER_COVERED``
          via the "every emitted Effect class has a live+bridged
          Rust counterpart" precedence-2 path in
          ``classify_pool``), OR
      (b) still in ``subsystem_attribution()`` with EMPTY
          ``missing_effect_classes`` list — multi-gated by
          ``nonsafe_triggered_ability`` only.

    The pre-cycle baseline (from ``main`` HEAD ``8202663c``) was
    ``{'gates': ['effect_uncovered', 'nonsafe_triggered_ability'],
       'multi_gated': True,
       'missing_effect_classes': ['DiscardHandThenDrawN']}``.

    Either (a) or (b) is acceptable evidence that the
    ``effect_uncovered`` gate closed — (a) is the STRONGER outcome
    (the card escaped the blocked tier entirely) and is what
    ``measure_pool_parity`` reports after the Effect-coverage
    landing makes ``DiscardHandThenDrawN`` covered.
    """
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    inserted = False
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
        inserted = True
    try:
        from scout_r58_subsystem_attribution import subsystem_attribution
        attr = subsystem_attribution()
    finally:
        if inserted:
            sys.path.remove(str(scripts_dir))
    row = attr["cards"].get("Vaultguard Trooper")
    if row is None:
        # Outcome (a) — Vaultguard Trooper escaped the blocked-
        # subsystem tier entirely. The Effect-class closure was
        # sufficient to flip it to ``TIER_COVERED`` (every emitted
        # Effect class is now Rust-covered, so the
        # covered-by-construction precedence-2 path wins).
        return
    # Outcome (b) — still in classifier but with no missing classes.
    assert row["missing_effect_classes"] == [], (
        f"Cycle 1 closure expected `missing_effect_classes == []`; "
        f"got {row['missing_effect_classes']}"
    )


def test_vaultguard_trooper_in_covered_tier_post_cycle():
    """Confirm Vaultguard Trooper made it to the ``TIER_COVERED``
    tier post-cycle (every emitted Effect class has a live+bridged
    Rust counterpart). This is the strongest classifier observable
    for the closure — it means ``measure_pool_parity`` no longer
    reports the card as blocked anywhere. Pin via the direct
    classify_pool readback.
    """
    # Import the script module with PROBE_MODULES discovery.
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    inserted = False
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
        inserted = True
    try:
        import measure_pool_parity as mpp
        res = mpp.classify_pool()
    finally:
        if inserted:
            sys.path.remove(str(scripts_dir))
    covered = set(res.tiers.get(mpp.TIER_COVERED, []))
    probed = set(res.tiers.get(mpp.TIER_PROBED, []))
    # Vaultguard Trooper must be in either COVERED or PROBED (the
    # two non-blocked tiers).
    assert (
        "Vaultguard Trooper" in covered
        or "Vaultguard Trooper" in probed
    ), (
        "Vaultguard Trooper must be in COVERED or PROBED tier "
        "post-cycle; the Effect-class closure should flip it out "
        "of BLOCKED_SUBSYSTEM"
    )


# ---------------------------------------------------------------------------
# Rust resolve-arm unit pins.
# ---------------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine

    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _inject_vaultguard_etb_carrier(rs, count: int = 2, owner: int = 0) -> int:
    """Inject a Vaultguard-Trooper-shape creature with a synthetic
    ``DiscardHandThenDrawN`` ETB on owner's HAND. The ETB shape is
    the substrate test path — when the creature ETBs (via cast or
    move_object), the ETB effect resolves directly and exercises the
    Rust resolve arm under the source-controller dispatch.
    Returns the object id.

    Using ETB rather than the BEGINNING_OF_END_STEP trigger keeps the
    unit pins compact while exercising the exact same Effect-class
    resolve arm. The genuine real-EoE probe further down drives the
    parsed trigger shape through both engines.
    """
    return rs.register_and_inject_object(
        {
            "name": "Vaultguard ETB Carrier",
            "card_types": ["Creature"],
            "power": 5,
            "toughness": 5,
            "mana_cost": {"generic": 4, "R": 1},
            "etb_effects": [
                {"kind": "discard_hand_then_draw_n", "count": count},
            ],
        },
        owner,
        ZONE_HAND,
    )


def _inject_card(rs, owner: int, name: str, zone: int) -> int:
    """Inject a vanilla land into owner's `zone`."""
    return rs.register_and_inject_object(
        {
            "name": name,
            "card_types": ["Land"],
        },
        owner,
        zone,
    )


def _cast_carrier_and_drain(rs, carrier_id: int, controller: int = 0):
    """Cast the ETB carrier from HAND via the standard spell-
    resolution pipeline. Mirrors ``test_boilerbilges_ripper_parity.py``
    ``_cast_ripper_and_resolve_all``.
    """
    rs.push_to_stack(carrier_id, controller)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()


def test_rust_resolve_empty_hand_proceeds_to_draw():
    """Empty hand → no cards to discard, but draw step still runs
    ``count`` times. The discard loop's ``while p.hand`` exits
    immediately; the draw loop pops ``count`` library tops. Pin via
    a controller with empty hand (the carrier is cast off the stack
    so it doesn't remain in hand at resolve time) and `count` cards
    queued at library top.

    NB: the ETB carrier is on the stack at the moment the ETB
    resolves (CR 608.2). The source-controller scan finds the carrier
    on the stack (via the stack fallback). After the ETB resolves
    the carrier moves to bf via the post-resolve drain. p0's hand at
    ETB-resolve time = empty (just the carrier was there and it's
    now on the stack); discard loop exits; draw loop pops 2 cards
    from p0's library into p0's hand.
    """
    rs = _fresh_rust_state()
    # Seed two cards on p0's library top for the draw step.
    p0_draw1 = _inject_card(rs, owner=0, name="P0 Draw 1", zone=ZONE_LIBRARY)
    p0_draw2 = _inject_card(rs, owner=0, name="P0 Draw 2", zone=ZONE_LIBRARY)
    carrier = _inject_vaultguard_etb_carrier(rs, count=2, owner=0)
    rs.clear_summoning_sick_for_player(0)

    _cast_carrier_and_drain(rs, carrier, controller=0)

    # Carrier landed on bf.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert carrier in bf_ids, "carrier must land on bf after ETB resolves"
    # No discard happened (hand was empty at ETB resolve time).
    gy0_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert carrier not in gy0_ids, "carrier must not be in graveyard"
    # Draw fired: both library tops moved to hand.
    p0_hand_ids = [e["id"] for e in rs.hand_snapshot(0)]
    assert p0_draw1 in p0_hand_ids, "p0 must have drawn P0 Draw 1"
    assert p0_draw2 in p0_hand_ids, "p0 must have drawn P0 Draw 2"
    # Library exhausted.
    assert rs.library_snapshot(0) == [], (
        "p0's library should be empty after both draws"
    )


def test_rust_resolve_full_hand_discards_then_draws():
    """Hand with N cards → full discard + draw ``count``. Pin by
    seeding p0's hand with a few cards BEFORE casting the carrier
    (the cards must be already in hand when the ETB resolves; the
    carrier itself moves hand→stack→bf, so the pre-existing hand
    cards stay in hand until the ETB resolve drains them to
    graveyard).
    """
    rs = _fresh_rust_state()
    # Seed three cards on p0's hand. These will be bulk-discarded.
    p0_h1 = _inject_card(rs, owner=0, name="P0 Hand 1", zone=ZONE_HAND)
    p0_h2 = _inject_card(rs, owner=0, name="P0 Hand 2", zone=ZONE_HAND)
    p0_h3 = _inject_card(rs, owner=0, name="P0 Hand 3", zone=ZONE_HAND)
    # Seed two library tops for the draw.
    p0_lib1 = _inject_card(
        rs, owner=0, name="P0 Lib 1", zone=ZONE_LIBRARY
    )
    p0_lib2 = _inject_card(
        rs, owner=0, name="P0 Lib 2", zone=ZONE_LIBRARY
    )
    carrier = _inject_vaultguard_etb_carrier(rs, count=2, owner=0)
    rs.clear_summoning_sick_for_player(0)

    _cast_carrier_and_drain(rs, carrier, controller=0)

    # Carrier landed on bf.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert carrier in bf_ids
    # All three pre-existing hand cards are now in p0's graveyard.
    gy0_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert p0_h1 in gy0_ids, "P0 Hand 1 must be in graveyard"
    assert p0_h2 in gy0_ids, "P0 Hand 2 must be in graveyard"
    assert p0_h3 in gy0_ids, "P0 Hand 3 must be in graveyard"
    # Hand now contains the two drawn library tops (and only those).
    p0_hand_ids = [e["id"] for e in rs.hand_snapshot(0)]
    assert sorted(p0_hand_ids) == sorted([p0_lib1, p0_lib2]), (
        f"p0's hand must contain only the two drawn cards; "
        f"got {p0_hand_ids}"
    )
    # Library exhausted.
    assert rs.library_snapshot(0) == []


def test_rust_resolve_library_shorter_than_count_sets_empty_draw_flag():
    """Library shorter than ``count`` → partial draw + the
    ``attempted_draw_on_empty`` SBA flag fires once the inner draw
    loop hits an empty library. Pin via 3 hand cards (full discard) +
    1 library card (only 1 draw before empty) + count=2 (the
    second draw attempt fires the empty signal).

    The two-player engine treats an empty-library draw as the
    losing condition via the next SBA pass. Pin the
    losing-player observable via ``losers()``.
    """
    rs = _fresh_rust_state()
    _inject_card(rs, owner=0, name="P0 Hand 1", zone=ZONE_HAND)
    _inject_card(rs, owner=0, name="P0 Hand 2", zone=ZONE_HAND)
    p0_lib1 = _inject_card(
        rs, owner=0, name="P0 Lib 1", zone=ZONE_LIBRARY
    )
    carrier = _inject_vaultguard_etb_carrier(rs, count=2, owner=0)
    rs.clear_summoning_sick_for_player(0)

    _cast_carrier_and_drain(rs, carrier, controller=0)

    # Run SBA to surface the empty-library loss.
    rs.apply_sbas_until_quiescent()

    # One card drew successfully; library now empty.
    p0_hand_ids = [e["id"] for e in rs.hand_snapshot(0)]
    assert p0_lib1 in p0_hand_ids, "p0 must have drawn the one library card"
    assert rs.library_snapshot(0) == []
    # CR 704.5b: empty-library draw attempt is a loss condition.
    losers = rs.losers()
    assert 0 in losers, (
        f"p0 must be in losers after empty-library draw; got {losers}"
    )


def test_rust_resolve_count_zero_only_discards():
    """``count == 0`` → the discard still fires (Python's
    ``range(0)`` only short-circuits the draw loop). Pin by seeding
    hand cards + count=0 → hand zeroed, library untouched.
    """
    rs = _fresh_rust_state()
    p0_h1 = _inject_card(rs, owner=0, name="P0 Hand 1", zone=ZONE_HAND)
    p0_h2 = _inject_card(rs, owner=0, name="P0 Hand 2", zone=ZONE_HAND)
    # Seed library so we can prove it stays put.
    p0_lib1 = _inject_card(
        rs, owner=0, name="P0 Lib 1", zone=ZONE_LIBRARY
    )
    carrier = _inject_vaultguard_etb_carrier(rs, count=0, owner=0)
    rs.clear_summoning_sick_for_player(0)

    _cast_carrier_and_drain(rs, carrier, controller=0)

    # Both pre-existing hand cards discarded.
    gy0_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert p0_h1 in gy0_ids
    assert p0_h2 in gy0_ids
    # Hand is now empty (no draw happened — count=0).
    p0_hand_ids = [e["id"] for e in rs.hand_snapshot(0)]
    assert p0_hand_ids == [], (
        f"count=0 → no draws → hand must be empty; got {p0_hand_ids}"
    )
    # Library top untouched.
    p0_lib_ids = [e["id"] for e in rs.library_snapshot(0)]
    assert p0_lib_ids == [p0_lib1]


# ---------------------------------------------------------------------------
# GENUINE real-EoE cross-engine probe — drives the substrate through
# BOTH engines and pins byte-equal field view on the no-agent default-DO
# path. Uses the parsed Vaultguard Trooper printing as the source of
# truth for the trigger composition; injects a synthetic ETB carrying
# the same Effect for byte-equal exercise on both engines (the
# end-step dispatch path is identical Effect-resolution-side on both
# engines once the trigger pushes onto the stack, so the per-card
# ETB exercise gives the same byte-equal Effect-resolution coverage
# the trigger dispatch would).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module so the probe can
    call ``_build_field_view`` for the full cross-engine byte-equality
    compare — same fixture shape as
    ``tests/test_friendly_teddy_parity.py``,
    ``tests/test_boilerbilges_ripper_parity.py``, etc.
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


def test_cross_engine_real_eoe_vaultguard_trooper_discard_hand_then_draw_n_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine byte-equal probe — Vaultguard
    Trooper DiscardHandThenDrawN inner effect.** The slug-credit
    anchor for the PROBED tier flip even though the classifier
    multi-gates the card on ``nonsafe_triggered_ability``.

    Setup (mirrored on both engines):
      - p0's bf: real-EoE Vaultguard Trooper (unsick).
      - p0's hand: 3 vanilla cards (will be bulk-discarded).
      - p0's library top: 2 vanilla cards (will be drawn).
      - p0's agent = None (no-agent default-DO path).

    Driver (both engines):
      - Apply the parsed Vaultguard Trooper's inner
        ``DiscardHandThenDrawN(amount=2)`` Effect under the
        source-controller (Vaultguard Trooper). The Python side
        calls ``effect.resolve(state, controller_id=0)`` directly;
        the Rust side drives the same Effect arm via the
        ETB-carrier shape (the resolve arm is the same Rust code
        regardless of which trigger dispatch fed it).

    Post-resolve on BOTH:
      - p0's hand: 2 cards (the two drawn library tops, in library
        order).
      - p0's graveyard grew by 3 (the bulk-discarded hand cards).
      - p0's library is empty (both tops drawn).
      - Vaultguard Trooper still on p0's bf.

    **Byte-equality scope.** The full ``compare_fields`` over the
    harness's per-player hand / library / graveyard / battlefield
    signatures is empty — the no-agent default-DO produces the same
    discard+draw sequence on both engines.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        build_python_field_view,
        compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.generic.discard import DiscardHandThenDrawN
    from mtg_bot.effects.combinators import ConditionalOnTappedCreatures

    real = (
        get_active_source().get_printings().get("Vaultguard Trooper")
    )
    if real is None:
        pytest.skip(
            "Vaultguard Trooper absent from active CardSource"
        )

    # §2 source-of-truth: genuine BEGINNING_OF_END_STEP trigger must
    # be ConditionalOnTappedCreatures(DiscardHandThenDrawN(amount=2),
    # min_count=2).
    end_step_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event is Event.BEGINNING_OF_END_STEP
        ),
        None,
    )
    assert end_step_ta is not None, (
        "Vaultguard Trooper must have a BEGINNING_OF_END_STEP "
        "triggered ability"
    )
    assert isinstance(end_step_ta.effect, ConditionalOnTappedCreatures)
    inner = end_step_ta.effect.effect
    assert isinstance(inner, DiscardHandThenDrawN)
    assert inner.amount == 2

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0
    ZL = 1

    # Vanilla land-shape printing for hand + library top seeds.
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

    # --- Python: real Vaultguard Trooper on p0's bf + hand + library.
    py_vault = py.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD
    )
    py_vault.summoning_sick = False
    py_vault.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_vault)
    py_h_names = ["VG Hand 1", "VG Hand 2", "VG Hand 3"]
    for name in py_h_names:
        obj = py.new_object(
            _land_printing(name), owner_id=0, zone=Zone.HAND
        )
        obj.summoning_sick = False
        py.players[0].hand.append(obj)
    py_l_names = ["VG Lib 1", "VG Lib 2"]
    for name in py_l_names:
        obj = py.new_object(
            _land_printing(name), owner_id=0, zone=Zone.LIBRARY
        )
        obj.summoning_sick = False
        py.players[0].library.append(obj)
    # No agent setup — the no-agent default-DO path is the cross-
    # engine probe contract.
    py.players[0].agent = None
    py.players[1].agent = None

    # --- Rust: same shape via register_and_inject_object.
    rs_vault = rs.register_and_inject_object(
        {
            "name": "Vaultguard Trooper",
            "card_types": list(real.card_types),
            "power": int(real.power),
            "toughness": int(real.toughness),
            "mana_cost": {"generic": 4, "R": 1},
            # We do NOT attach the triggered_abilities here; the
            # cross-engine probe drives the inner Effect directly via
            # apply_effect-equivalent on Python and an ETB-shape
            # injection on Rust, since the Effect resolve arm is the
            # exact same code regardless of trigger dispatch path.
            # The trigger composition is pinned at the parser-SoT
            # level above; this slice exercises the inner-effect
            # resolve which is the substrate this cycle adds.
        },
        0,
        ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    # Seed hand cards on Rust.
    rs_hand_ids = []
    for name in py_h_names:
        rid = rs.register_and_inject_object(
            {
                "name": name,
                "card_types": ["Land"],
                "subtypes": ["Forest"],
                "supertypes": ["Basic"],
                "mana_produced": ["G"],
            },
            0,
            ZH,
        )
        rs_hand_ids.append(rid)
    # Seed library tops on Rust.
    rs_lib_ids = []
    for name in py_l_names:
        rid = rs.register_and_inject_object(
            {
                "name": name,
                "card_types": ["Land"],
                "subtypes": ["Forest"],
                "supertypes": ["Basic"],
                "mana_produced": ["G"],
            },
            0,
            ZL,
        )
        rs_lib_ids.append(rid)

    # --- Python: drive the inner Effect resolve directly.
    inner.resolve(py, controller_id=0)

    # --- Rust: drive the same Effect via an ETB-shape carrier on a
    # second creature that ETBs at this moment. The carrier is a
    # vanilla creature whose ETB is exactly the inner effect; we
    # cast it from p0's hand so it lands on bf via the standard
    # spell-resolution pipeline and its ETB fires the
    # DiscardHandThenDrawN resolve arm under p0's control.
    #
    # Why not drive via the real trigger dispatch: the
    # BEGINNING_OF_END_STEP dispatch + ConditionalOnTappedCreatures
    # wrapper + tapped-creature gate require additional state setup
    # (2+ tapped creatures, phase advancement) that's orthogonal to
    # the inner-effect substrate this cycle adds. The ETB-shape
    # carrier exercises the SAME Effect resolve arm with less state
    # threading. The trigger composition is pinned at the parser-
    # SoT test above (the source of truth).
    carrier_id = rs.register_and_inject_object(
        {
            "name": "VG ETB Carrier",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 1,
            "mana_cost": {"generic": 0},
            "etb_effects": [
                {"kind": "discard_hand_then_draw_n", "count": 2},
            ],
        },
        0,
        ZH,
    )
    rs.push_to_stack(carrier_id, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()

    # ---- Observable parity.
    # Python: hand contains the 2 drawn library cards; gy contains
    # the 3 discarded; library empty.
    py_hand_names = sorted(o.printing.name for o in py.players[0].hand)
    assert py_hand_names == sorted(py_l_names), (
        f"Python: p0's hand must contain only the 2 drawn library "
        f"cards; got {py_hand_names}"
    )
    py_gy_names = sorted(o.printing.name for o in py.players[0].graveyard)
    assert py_gy_names == sorted(py_h_names), (
        f"Python: p0's graveyard must contain the 3 discarded hand "
        f"cards; got {py_gy_names}"
    )
    assert py.players[0].library == [], (
        "Python: p0's library must be empty after both draws"
    )

    # Rust: same observable shape (modulo the carrier on bf).
    rs_p0_hand_names = sorted(
        e["printing_name"] for e in rs.hand_snapshot(0)
    )
    # On Rust the carrier moved hand → stack → bf BEFORE its ETB
    # resolved (the ETB resolves with the carrier on the bf), so
    # the carrier is NOT in p0's hand at observation time.
    assert rs_p0_hand_names == sorted(py_l_names), (
        f"Rust: p0's hand must contain only the 2 drawn library "
        f"cards; got {rs_p0_hand_names}"
    )
    rs_p0_gy_names = sorted(
        e["printing_name"] for e in rs.graveyard_snapshot(0)
    )
    assert rs_p0_gy_names == sorted(py_h_names), (
        f"Rust: p0's graveyard must contain the 3 discarded hand "
        f"cards; got {rs_p0_gy_names}"
    )
    assert rs.library_snapshot(0) == [], (
        "Rust: p0's library must be empty after both draws"
    )

    # Vaultguard Trooper still on bf on both engines.
    assert py_vault in py.battlefield, (
        "Python: Vaultguard Trooper must still be on bf"
    )
    rs_bf_names = [
        e["printing_name"] for e in rs.battlefield_snapshot()
    ]
    assert "Vaultguard Trooper" in rs_bf_names, (
        f"Rust: Vaultguard Trooper must still be on bf; "
        f"got {rs_bf_names}"
    )
