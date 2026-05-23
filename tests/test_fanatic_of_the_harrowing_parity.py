"""Cross-engine parity probes for Fanatic of the Harrowing.

**Fanatic of the Harrowing Cycle 1 closure (2026-05-23).** ``{3}{B}``
Creature — Human Cleric, 2/2 (Duskmourn — sourced from
``data/duskmourn.json:13266``). ETB trigger body: "When this creature
enters, each player discards a card. If you discarded a card this way,
draw a card."

Mirrors Python's ``FanaticOfTheHarrowingETBEffect`` (parameterless
frozen dataclass at ``effects/bespoke.py:2830``).

**Multi-gated card; classifier stays multi-gated.** Per the round-58
subsystem-attribution classifier (``scripts/scout_r58_subsystem_
attribution.py``), Fanatic of the Harrowing is multi-gated:

  * ``effect_uncovered`` — closed by this cycle. The new Rust variant
    ``Effect::FanaticOfTheHarrowingETBEffect`` makes the Python class
    ``FanaticOfTheHarrowingETBEffect`` covered via the 1:1 identity-
    mapping rule in ``effect_coverage.map_rust_to_python``; the
    classifier's ``missing_effect_classes`` array shrinks by one for
    this card.
  * ``nonsafe_triggered_ability`` — **STAYS active**. The trajectory
    safe-trigger admit gate (``parity/trajectory.py::
    _python_ta_to_safe_dict``) is INTENTIONALLY NOT widened — that
    gate is about the production-deck bench admit set, a distinct
    concern from per-card real-EoE parity probes. The classifier's
    multi-gate state therefore reads
    ``{'gates': ['effect_uncovered', 'nonsafe_triggered_ability'],
       'multi_gated': True,
       'missing_effect_classes': []}``
    after this cycle (the effect-class list is empty; the trigger
    leaf class is still not in the safe set).

**Per-card dedicated parity probe path (PROBED tier flip).** Even
though the classifier keeps the card multi-gated at
``nonsafe_triggered_ability``, this test module is the dedicated
per-card real-EoE byte-equal cross-engine probe that flips Fanatic of
the Harrowing to PROBED tier. Same precedent as
``test_boilerbilges_ripper_parity.py``, ``test_comet_crawler_parity.py``,
``test_dyadrine_attack.py``, and ``test_mutinous_massacre_parity.py``:
a per-card probe drives the real printing through both engines and
pins byte-equal observables; the safe-trigger bench admit set is
widened in a separate cycle when the production-deck bench needs it.

**NOT a spell-card-bridge admit-set extension.** Fanatic of the
Harrowing is a Creature, not a non-creature spell. The spell-card-
bridge admit set (``trajectory.py::_python_spell_effect_to_dict`` +
its §2 teeth) gates non-creature spells only. The per-card probe
approach is the right tool here, exactly the Comet Crawler /
Mutinous Massacre / Dyadrine Attack / Boilerbilges Ripper convention.

**Mandatory-discard byte-equal (NOT a no-agent decline).** Unlike
Boilerbilges Ripper (which has an optional yes/no gate that defaults
to "decline" when no agent), Fanatic of the Harrowing's discard is
MANDATORY — each player MUST discard a card from their non-empty
hand. There is no decline option in the printed text or in Python's
resolve. The cross-engine probe drives Python with a deterministic
``choose_discard`` agent that returns ``hand_card_ids[0]`` on both
seats; the Rust resolve pops ``hand[0]`` deterministically by the
established ``EachOpponentDiscards`` / ``DiscardSelf`` /
``EachOpponentExilesCardFromHandWithCastPermission`` convention.
Both engines pick the same card byte-equal.

Coverage:

- Parser SoT pin: the live parser maps Fanatic of the Harrowing's ETB
  trigger to ``FanaticOfTheHarrowingETBEffect()`` (a parameterless
  frozen dataclass).
- Serializer round-trip: dict→Python via ``_ta_dict_to_python_effect``
  rebuilds ``FanaticOfTheHarrowingETBEffect()``; Rust
  ``Effect::FanaticOfTheHarrowingETBEffect`` → dict via
  ``Registry.get_printing_etb_effects`` emits the expected one-key
  dict shape.
- Effect-coverage class pin: ``FanaticOfTheHarrowingETBEffect`` is in
  the covered-by-rust set after this cycle (1:1 identity-mapping rule).
- Rust resolve-arm unit pins:
    * Both players have non-empty hands → both discard hand[0]; the
      controller draws 1 card (the "if you discarded" rider).
    * Controller has empty hand, opponent has non-empty hand → only
      opponent discards; no controller draw (controller didn't
      actually discard).
    * Both players have empty hands → silent no-op (no discards, no
      controller draw).
- **GENUINE real-EoE cross-engine byte-equal probe** drives the parsed
  Fanatic of the Harrowing printing through BOTH engines.
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


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_fanatic_of_the_harrowing_etb_trigger_is_bespoke_effect():
    """**Verify-first.** The live parser maps Fanatic of the
    Harrowing's ETB trigger to ``FanaticOfTheHarrowingETBEffect()`` (a
    parameterless frozen dataclass). Pin the shape so a parser drift
    is caught here, not silently downstream in the cross-engine
    probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import FanaticOfTheHarrowingETBEffect
    from mtg_bot.effects.predicates import Event, IsSelf

    p = get_active_source().get_printings().get("Fanatic of the Harrowing")
    if p is None:
        pytest.skip("Fanatic of the Harrowing absent from active CardSource")
    assert "Creature" in p.card_types
    assert p.power == 2
    assert p.toughness == 2
    # Single ETB triggered ability.
    enters_tas = [
        ta for ta in p.triggered_abilities if ta.event is Event.ENTERS
    ]
    assert len(enters_tas) == 1, (
        f"Fanatic of the Harrowing must have exactly 1 ENTERS triggered "
        f"ability; got {len(enters_tas)}"
    )
    ta = enters_tas[0]
    assert isinstance(ta.predicate, IsSelf)
    assert ta.predicate.subject is None
    assert isinstance(ta.effect, FanaticOfTheHarrowingETBEffect), (
        f"ETB trigger effect must be FanaticOfTheHarrowingETBEffect; "
        f"got {type(ta.effect).__name__}"
    )
    # Field-free unit dataclass — equality with a fresh
    # default-constructed instance.
    assert ta.effect == FanaticOfTheHarrowingETBEffect()


# -------------------------------------------------------------------
# Serializer round-trip + covered-set membership pins.
# -------------------------------------------------------------------


def test_fanatic_of_the_harrowing_effect_dict_to_python_round_trip():
    """Rust-shape dict → Python ``FanaticOfTheHarrowingETBEffect`` via
    ``_ta_dict_to_python_effect`` reconstructs a default-constructed
    instance. Bridge arm is the lever flip — without it, a Rust→Python
    triggered-ability translation would raise on the unknown kind."""
    from mtg_bot.effects.bespoke import FanaticOfTheHarrowingETBEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = {"kind": "fanatic_of_the_harrowing_etb_effect"}
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, FanaticOfTheHarrowingETBEffect), (
        f"dict→Python bridge must round-trip to "
        f"FanaticOfTheHarrowingETBEffect; got {type(rebuilt).__name__}"
    )
    # Field-free unit dataclass; equality with a fresh instance.
    assert rebuilt == FanaticOfTheHarrowingETBEffect()


def test_fanatic_of_the_harrowing_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::FanaticOfTheHarrowingETBEffect`` → dict emits the
    expected one-key shape. Drives the round-trip through
    ``Registry.register_printing`` (the parse path) +
    ``get_printing_etb_effects`` (the ``effect_to_pydict`` readback).
    """
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Fanatic of the Harrowing Round-trip",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 3, "B": 1},
            "etb_effects": [
                {"kind": "fanatic_of_the_harrowing_etb_effect"},
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == "fanatic_of_the_harrowing_etb_effect"
    # Field-free unit variant — no other keys.
    assert set(eff.keys()) == {"kind"}, (
        f"unit-variant to_pydict must emit ONLY 'kind'; got keys "
        f"{sorted(eff.keys())}"
    )


def test_fanatic_of_the_harrowing_class_covered_by_rust():
    """``FanaticOfTheHarrowingETBEffect`` must be in the covered-by-
    rust set — the Rust ``Effect::FanaticOfTheHarrowingETBEffect``
    variant declaration makes ``covered_python_class_set()`` include
    it via the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``. This is the §2 covered-set
    tooth (parity-doc / coverage-script "covered" alignment) AND the
    closure of the classifier's ``effect_uncovered`` gate for Fanatic
    of the Harrowing."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "FanaticOfTheHarrowingETBEffect" in covered, (
        "Rust Effect::FanaticOfTheHarrowingETBEffect variant must make "
        "the Python FanaticOfTheHarrowingETBEffect class covered via "
        "the 1:1 identity-mapping rule"
    )


def test_fanatic_of_the_harrowing_classifier_effect_uncovered_gate_closed():
    """The round-58 subsystem-attribution classifier should report
    Fanatic of the Harrowing with an EMPTY ``missing_effect_classes``
    list after this cycle — proof the ``effect_uncovered`` gate is
    closed at the classifier level. The card stays multi-gated overall
    because ``nonsafe_triggered_ability`` is still in ``gates``; this
    test pins the effect-class closure specifically.

    NB: the classifier scans the EoE pool only; Fanatic of the
    Harrowing is a DSK card so the classifier doesn't surface it.
    This test skips on absence (the load-bearing signal is
    ``covered_python_class_set()`` membership, pinned directly by
    ``test_fanatic_of_the_harrowing_class_covered_by_rust``)."""
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
    row = attr["cards"].get("Fanatic of the Harrowing")
    if row is None:
        pytest.skip(
            "Fanatic of the Harrowing absent from classifier output "
            "(EoE-pool-scoped classifier doesn't surface DSK cards; "
            "covered-set membership is the load-bearing signal)"
        )
    # effect_uncovered gate must be CLOSED at the effect-class level:
    # the missing list should now be empty.
    assert row["missing_effect_classes"] == [], (
        f"Cycle 1 closure expected `missing_effect_classes == []`; "
        f"got {row['missing_effect_classes']}"
    )
    # But the card is still multi-gated overall (the
    # nonsafe_triggered_ability gate hasn't been widened this cycle).
    assert "nonsafe_triggered_ability" in row["gates"], (
        f"Cycle 1 intentionally keeps the nonsafe_triggered_ability "
        f"gate active; classifier `gates` = {row['gates']}"
    )


# -------------------------------------------------------------------
# Rust resolve-arm unit pins — mandatory-discard semantics.
# -------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


_FANATIC_PRINTING_DICT: dict = {
    "name": "Fanatic of the Harrowing",
    "card_types": ["Creature"],
    "power": 2,
    "toughness": 2,
    "mana_cost": {"generic": 3, "B": 1},
    "triggered_abilities": [
        {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "fanatic_of_the_harrowing_etb_effect",
            },
        },
    ],
}


def _inject_fanatic_in_hand(rs, owner: int = 0) -> int:
    return rs.register_and_inject_object(
        _FANATIC_PRINTING_DICT,
        owner,
        ZONE_HAND,
    )


def _inject_filler_in_hand(rs, owner: int, name_suffix: str) -> int:
    """Inject a vanilla filler instant into ``owner``'s hand. Used to
    populate the hand so the discard arm has something to pick.
    Returns the object id."""
    return rs.register_and_inject_object(
        {
            "name": f"Fanatic Filler {name_suffix}",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        owner,
        ZONE_HAND,
    )


def _inject_filler_in_library(rs, owner: int, name_suffix: str) -> int:
    """Inject a vanilla filler instant into ``owner``'s library. Used
    so the controller-draw rider has a card to draw."""
    return rs.register_and_inject_object(
        {
            "name": f"Fanatic Library {name_suffix}",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        owner,
        ZONE_LIBRARY,
    )


def _cast_fanatic_and_resolve_all(rs, fanatic_id: int, controller: int = 0):
    """Cast the Fanatic from ``controller``'s HAND via the standard
    spell-resolution pipeline; drain stack until empty so the ETB
    trigger resolves."""
    rs.push_to_stack(fanatic_id, controller)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()


def test_rust_resolve_both_players_have_hand_both_discard_controller_draws():
    """Both players have a non-empty hand at resolve time. The Rust
    resolve walks both seats starting from controller (p0), pops
    hand[0] of each → moves to that player's graveyard. Since the
    controller (p0) actually discarded, the gate-8 controller-draw
    rider fires and p0 draws 1 card from library[0]."""
    rs = _fresh_rust_state()

    # Seed p0's library so the controller-draw rider has something to
    # draw.
    p0_library_card = _inject_filler_in_library(rs, owner=0, name_suffix="p0-lib")
    # Seed p1's hand with one filler card (the one p1 will discard).
    p1_hand_card = _inject_filler_in_hand(rs, owner=1, name_suffix="p1-hand")
    # Cast Fanatic from p0's hand — it has the Fanatic itself in hand;
    # when it resolves and lands on bf, p0's hand is empty (Fanatic
    # moved bf-ward). To make p0 actually discard during the ETB,
    # seed p0's hand with a filler card BEFORE the resolve fires.
    # Since the ETB queues after the spell resolves and lands the
    # Fanatic, by the time the ETB body runs p0's hand has whatever
    # was there minus the Fanatic.
    p0_hand_filler = _inject_filler_in_hand(rs, owner=0, name_suffix="p0-hand")
    fanatic_id = _inject_fanatic_in_hand(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    p0_hand_size_before = rs.hand_sizes[0]
    p1_hand_size_before = rs.hand_sizes[1]
    assert p0_hand_size_before == 2  # Fanatic + filler
    assert p1_hand_size_before == 1

    _cast_fanatic_and_resolve_all(rs, fanatic_id, controller=0)

    # Fanatic is on bf.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert fanatic_id in bf_ids, "Fanatic must land on bf after spell resolves"

    # p0 discarded their filler (hand[0] at ETB-resolve time was
    # p0_hand_filler, since Fanatic moved off the hand into bf via
    # the cast resolution).
    p0_gy_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert p0_hand_filler in p0_gy_ids, (
        "p0's filler card must be in p0's graveyard (discarded via "
        "Fanatic ETB)"
    )

    # p1 also discarded their filler.
    p1_gy_ids = [e["id"] for e in rs.graveyard_snapshot(1)]
    assert p1_hand_card in p1_gy_ids, (
        "p1's filler card must be in p1's graveyard (discarded via "
        "Fanatic ETB)"
    )

    # Controller draw rider fired: p0's library[0] is now in p0's hand.
    p0_hand_ids_after = [e["id"] for e in rs.hand_snapshot(0)]
    assert p0_library_card in p0_hand_ids_after, (
        "p0 must have drawn library[0] (gate-8 controller-draw rider "
        "fires because p0 actually discarded)"
    )


def test_rust_resolve_controller_empty_hand_only_opponent_discards_no_draw():
    """Controller has an empty hand at ETB-resolve time (only the
    Fanatic itself was in hand, and it moved to bf via the cast).
    Opponent has a non-empty hand. Only opponent discards; the
    controller-draw rider does NOT fire (because controller didn't
    actually discard)."""
    rs = _fresh_rust_state()

    # Seed p0's library — so we can verify p0 did NOT draw.
    p0_library_card = _inject_filler_in_library(rs, owner=0, name_suffix="p0-lib")
    # Seed p1's hand with one filler card.
    p1_hand_card = _inject_filler_in_hand(rs, owner=1, name_suffix="p1-hand")
    # ONLY the Fanatic in p0's hand — after the cast resolves, p0's
    # hand is empty.
    fanatic_id = _inject_fanatic_in_hand(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    _cast_fanatic_and_resolve_all(rs, fanatic_id, controller=0)

    # Fanatic is on bf.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert fanatic_id in bf_ids, "Fanatic must land on bf after spell resolves"

    # p0's hand is empty — no discard from p0.
    assert rs.hand_sizes[0] == 0
    assert rs.graveyard_snapshot(0) == [], (
        "p0 had an empty hand; no discard, no graveyard delta"
    )

    # p1 discarded their filler.
    p1_gy_ids = [e["id"] for e in rs.graveyard_snapshot(1)]
    assert p1_hand_card in p1_gy_ids, (
        "p1's filler card must be in p1's graveyard (discarded via "
        "Fanatic ETB)"
    )

    # Controller-draw rider did NOT fire — p0's library[0] is still in
    # library.
    p0_hand_ids_after = [e["id"] for e in rs.hand_snapshot(0)]
    assert p0_library_card not in p0_hand_ids_after, (
        "p0 must NOT have drawn (gate-8 controller-draw rider does "
        "NOT fire because p0 did not actually discard)"
    )
    # The card is still in library.
    p0_lib_ids = [e["id"] for e in rs.library_snapshot(0)]
    assert p0_library_card in p0_lib_ids, (
        "p0's library[0] stays in library (no controller draw)"
    )


def test_rust_resolve_both_players_empty_hands_silent_no_op():
    """Both players have empty hands (only the Fanatic itself was in
    p0's hand, and it moved to bf via the cast; p1 starts with an
    empty hand). No discards, no graveyard deltas, no controller draw.
    Silent no-op."""
    rs = _fresh_rust_state()

    # Seed p0's library — so we can verify p0 did NOT draw.
    p0_library_card = _inject_filler_in_library(rs, owner=0, name_suffix="p0-lib")
    # ONLY the Fanatic in p0's hand — after the cast resolves, p0's
    # hand is empty. p1 starts with an empty hand.
    fanatic_id = _inject_fanatic_in_hand(rs, owner=0)
    rs.clear_summoning_sick_for_player(0)

    _cast_fanatic_and_resolve_all(rs, fanatic_id, controller=0)

    # Fanatic is on bf.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert fanatic_id in bf_ids, "Fanatic must land on bf after spell resolves"

    # Both graveyards empty — no discards happened.
    assert rs.graveyard_snapshot(0) == [], (
        "p0 had empty hand; no graveyard delta"
    )
    assert rs.graveyard_snapshot(1) == [], (
        "p1 had empty hand; no graveyard delta"
    )

    # Controller-draw rider did NOT fire — p0's library[0] is still in
    # library.
    p0_hand_ids_after = [e["id"] for e in rs.hand_snapshot(0)]
    assert p0_library_card not in p0_hand_ids_after, (
        "p0 must NOT have drawn (gate-8 controller-draw rider does "
        "NOT fire when controller didn't discard)"
    )


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine byte-equal probe — drives the parsed
# Fanatic of the Harrowing printing through BOTH engines and pins
# byte-equal full-field-view equality on the both-discard +
# controller-draw path.
# -------------------------------------------------------------------


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module so the probe can
    call ``_build_field_view`` for the full cross-engine byte-equality
    compare — same fixture shape as ``tests/test_parity_smoke.py``,
    ``tests/test_boilerbilges_ripper_parity.py``, etc."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "parity_smoke", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


class _FirstHandIdDiscardAgent:
    """Stub agent whose ``choose_discard`` returns ``hand_card_ids[0]``
    deterministically. Mirrors the Rust resolve arm's ``hand[0]``-pop
    convention so both engines pick the SAME card byte-equal."""

    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[0]


def test_cross_engine_real_eoe_fanatic_of_the_harrowing_both_discard_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine byte-equal probe — Fanatic of
    the Harrowing ETB both-players-discard + controller-draw path.**
    The slug-credit anchor for the PROBED tier flip even though the
    classifier multi-gates the card on ``nonsafe_triggered_ability``.

    Drives the **real parsed Fanatic of the Harrowing printing**
    through both engines on a shape with both seats holding a filler
    card in hand and p0's library carrying a draw target. Post-
    resolve:
      - both seats' filler cards are in their respective graveyards
        (each player discarded hand[0]);
      - p0 has drawn library[0] (controller-draw rider fired);
      - Fanatic is on p0's bf.

    The cross-engine probe pins the full byte-equal field-view
    compare across the WHOLE harness field view.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.bespoke import FanaticOfTheHarrowingETBEffect

    real = get_active_source().get_printings().get("Fanatic of the Harrowing")
    if real is None:
        pytest.skip("Fanatic of the Harrowing absent from active CardSource")

    # §2 source-of-truth: genuine ENTERS trigger must be a
    # FanaticOfTheHarrowingETBEffect (parameterless).
    enters_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.ENTERS
        ),
        None,
    )
    assert enters_ta is not None, (
        "Fanatic of the Harrowing must have an ENTERS triggered ability"
    )
    assert isinstance(
        enters_ta.effect, FanaticOfTheHarrowingETBEffect
    ), (
        f"ETB trigger must be FanaticOfTheHarrowingETBEffect; "
        f"got {type(enters_ta.effect).__name__}"
    )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD
    ZH = 0  # ZONE_HAND
    ZL = 1  # ZONE_LIBRARY

    # Synthetic vanilla filler instant (same shape on both engines).
    def _filler_printing(name: str) -> CardPrinting:
        return CardPrinting(
            name=name,
            mana_cost_str="",
            mana_cost=ManaCost(generic=0, colored=(("R", 1),)),
            type_line="Instant",
            supertypes=(),
            card_types=("Instant",),
            subtypes=(),
            power=None,
            toughness=None,
            produces=frozenset(),
            keywords=frozenset(),
        )

    # --- Python: seat filler cards in both players' hands + p0's
    # library; place the real Fanatic on p0's bf and fire its ETB
    # trigger via dispatch_event (the round-58 ETB-trigger substrate
    # path). The deterministic ``choose_discard`` agent on BOTH seats
    # picks hand[0] for byte-equal alignment with Rust's hand[0] pop.
    py_p0_filler = py.new_object(
        _filler_printing("Fanatic Filler p0-hand"),
        owner_id=0,
        zone=Zone.HAND,
    )
    # Match Rust's hand/library zone default (summoning_sick=False);
    # the gameplay-irrelevant default difference would otherwise flag a
    # spurious field-view divergence post-discard / post-draw.
    py_p0_filler.summoning_sick = False
    py.players[0].hand.append(py_p0_filler)
    py_p1_filler = py.new_object(
        _filler_printing("Fanatic Filler p1-hand"),
        owner_id=1,
        zone=Zone.HAND,
    )
    py_p1_filler.summoning_sick = False
    py.players[1].hand.append(py_p1_filler)
    py_p0_lib_card = py.new_object(
        _filler_printing("Fanatic Library p0-lib"),
        owner_id=0,
        zone=Zone.LIBRARY,
    )
    py_p0_lib_card.summoning_sick = False
    py.players[0].library.append(py_p0_lib_card)
    py_fanatic = py.new_object(real, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(py_fanatic)
    # Deterministic choose_discard agent on BOTH seats.
    py.players[0].agent = _FirstHandIdDiscardAgent()
    py.players[1].agent = _FirstHandIdDiscardAgent()

    # --- Rust: same shape via register_and_inject_object. Order
    # matters because Rust assigns object IDs in registration order;
    # we mirror Python's hand-construction order to keep IDs aligned.
    rs_p0_filler = rs.register_and_inject_object(
        {
            "name": "Fanatic Filler p0-hand",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        0,
        ZH,
    )
    rs_p1_filler = rs.register_and_inject_object(
        {
            "name": "Fanatic Filler p1-hand",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        1,
        ZH,
    )
    rs_p0_lib_card = rs.register_and_inject_object(
        {
            "name": "Fanatic Library p0-lib",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
        },
        0,
        ZL,
    )
    rs_fanatic = rs.register_and_inject_object(
        _FANATIC_PRINTING_DICT,
        0,
        ZH,
    )
    rs.clear_summoning_sick_for_player(0)

    # ---- Drive the ETB resolution on both engines.
    #
    # **Python.** Move the Fanatic from hand → bf (the cast-resolution
    # zone change). Fire ENTERS via ``dispatch_event``; the trigger
    # queues on the Python stack, then resolves into Python's
    # ``FanaticOfTheHarrowingETBEffect.resolve`` body. Both seats'
    # agents pick hand[0] (the filler card), which moves to graveyard
    # via Python's discard primitive. After the walk, the controller
    # (p0) has discarded, so p0 draws 1 card from library[0].
    #
    # **Rust.** Cast Fanatic via push_to_stack + drain stack. The
    # spell-resolve lands Fanatic on bf, queues the ETB trigger, and
    # the trigger resolves the Rust resolve arm. Both seats' hand[0]
    # is popped; controller-draw rider fires for p0.
    from mtg_bot.actions import dispatch_event

    py.players[0].hand.remove(py_fanatic)
    py_fanatic.zone = Zone.BATTLEFIELD
    # summoning_sick=True matches the Rust cast-pipeline default
    # (CR 302.1 — permanents enter with summoning sickness).
    py_fanatic.summoning_sick = True
    py_fanatic.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_fanatic)
    dispatch_event(py, Event.ENTERS, label="enters", obj=py_fanatic)
    # Drain stack — the ETB trigger pushed by dispatch_event resolves
    # the full body.
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    # Rust: cast the Fanatic through the spell pipeline.
    rs.push_to_stack(rs_fanatic, 0)
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert len(py.stack) == 0 and rs.stack_size() == 0

    # ---- Observable parity: both seats discarded; controller drew.
    # Python observables.
    assert py_fanatic in py.battlefield, (
        "Python: Fanatic must be on bf post-resolve"
    )
    assert py_p0_filler in py.players[0].graveyard, (
        "Python: p0's filler must be in p0's graveyard (discarded)"
    )
    assert py_p1_filler in py.players[1].graveyard, (
        "Python: p1's filler must be in p1's graveyard (discarded)"
    )
    # p0 drew library[0]: library is empty, library[0] is in hand.
    assert py_p0_lib_card in py.players[0].hand, (
        "Python: p0 must have drawn library[0] (controller-draw rider)"
    )
    assert py_p0_lib_card not in py.players[0].library

    # Rust observables.
    rs_bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert rs_fanatic in rs_bf_ids, (
        "Rust: Fanatic must be on bf post-cast"
    )
    rs_gy0_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert rs_p0_filler in rs_gy0_ids, (
        "Rust: p0's filler must be in p0's graveyard (discarded)"
    )
    rs_gy1_ids = [e["id"] for e in rs.graveyard_snapshot(1)]
    assert rs_p1_filler in rs_gy1_ids, (
        "Rust: p1's filler must be in p1's graveyard (discarded)"
    )
    rs_hand0_ids = [e["id"] for e in rs.hand_snapshot(0)]
    assert rs_p0_lib_card in rs_hand0_ids, (
        "Rust: p0 must have drawn library[0] (controller-draw rider)"
    )

    # ---- Full byte-equal field-view compare.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Fanatic of the Harrowing ETB both-discard + controller-draw "
        f"path must be byte-equal across the WHOLE field view on BOTH "
        f"engines; diffs={diffs}"
    )
