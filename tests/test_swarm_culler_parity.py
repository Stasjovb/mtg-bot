"""Cross-engine parity probes for Swarm Culler.

**Swarm Culler Cycle 1 closure (2026-05-23).** ``{3}{B}`` Creature —
Insect Warrior, 2/4, Flying. BECOMES_TAPPED trigger body:
"Whenever this creature becomes tapped, you may sacrifice another
creature or artifact. If you do, draw a card."

The parser maps the oracle line
(``cards/parser/effects.py:_OPTIONAL_SAC_ANOTHER_FOR_EFFECT``) to
``OptionalSacAnotherForEffect(inner_effect=DrawCards(amount=1))``
— the **general** version of ``OptionalSacAnotherForPumpSelfUEOT``
that the Comet Crawler Cycle 1 closure shipped (which is +P/+T-
specific). The cycle ports the substrate to Rust
(``Effect::OptionalSacAnotherForEffect { inner_effect: Box<Effect> }``
— recursive ``Box<Effect>`` shape; parser arm round-trips the
``{"kind": "optional_sac_another_for_effect", "inner_effect":
<dict>}`` two-key dict shape; resolve arm in
``state_ops_resolve.rs`` scans source-controller's bf for the first
eligible other-creature-or-artifact, sacrifices it via CR 400.7
reset + LEAVES/DIES/token-cease dispatches, then recursively calls
``apply_effect(state, inner_effect, source_obj_id)``).

**Multi-gated card; classifier stays multi-gated.** Per the
round-58 subsystem-attribution classifier, Swarm Culler is
multi-gated:

  * ``effect_uncovered`` — closed by this cycle. The new Rust
    variant ``Effect::OptionalSacAnotherForEffect`` makes the
    Python class ``OptionalSacAnotherForEffect`` covered via the
    1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``; the classifier's
    ``missing_effect_classes`` array shrinks by one for this card.
  * ``becomes_tapped_event`` — already closed campaign-wide by
    round-58 N1 (BECOMES_TAPPED event substrate bridge — Rust's
    ``Event::BecomesTapped`` variant + the canonical
    ``turn.tap_permanent`` dispatch sites in
    ``state_ops_resolve.rs`` / ``state_ops_actions.rs`` /
    ``state_ops_mana.rs`` / ``state_ops_combat.rs`` /
    ``state_ops_decisions.rs`` / ``state_ops_cast.rs`` fire
    ``dispatch_event(Event::BecomesTapped, obj_id)`` at every
    Python-side ``Event.BECOMES_TAPPED`` chokepoint). Same
    BECOMES_TAPPED substrate that unblocked Hemosymbic Mite Cycle
    1 also unblocks Swarm Culler here.
  * ``nonsafe_triggered_ability`` — **STAYS active**. The
    trajectory safe-trigger admit gate
    (``parity/trajectory.py::_python_ta_to_safe_dict``) is
    INTENTIONALLY NOT widened — the
    ``("becomes_tapped","source_is_self",
    "optional_sac_another_for_effect")`` triple is not added to
    ``_SAFE_TRIGGERS``. Same per-card real-EoE probe precedent as
    Comet Crawler / Hemosymbic Mite / Ouroboroid / Boilerbilges
    Ripper / Fanatic of the Harrowing / Terrapact Intimidator: the
    trajectory-side bench admit set is a distinct concern from
    per-card real-EoE parity probes.

**Per-card dedicated parity probe path (PROBED tier flip).** Even
though the classifier keeps the card multi-gated at
``nonsafe_triggered_ability``, this test module is the dedicated
per-card real-EoE byte-equal cross-engine probe that flips Swarm
Culler to PROBED tier. Same precedent as
``test_hemosymbic_mite_parity.py``, ``test_comet_crawler_parity.py``,
``test_boilerbilges_ripper_parity.py``, ``test_dyadrine_attack.py``,
``test_mutinous_massacre_parity.py``.

Coverage:

- Parser SoT pin: parsed Swarm Culler printing's BECOMES_TAPPED
  trigger effect IS
  ``OptionalSacAnotherForEffect(inner_effect=DrawCards(amount=1))``.
- Serializer round-trip: dict→Python via
  ``_ta_dict_to_python_effect`` reconstructs the wrapper with a
  non-trivial inner Effect; Rust
  ``Effect::OptionalSacAnotherForEffect { inner_effect }`` → dict
  via ``Registry.get_printing_etb_effects`` emits the expected
  two-key dict shape with the recursive inner dict.
- Effect-coverage class pin: ``OptionalSacAnotherForEffect`` is in
  the covered-by-rust set (the new Rust variant maps 1:1 to the
  Python class via the identity rule in
  ``effect_coverage.map_rust_to_python``).
- Rust resolve-arm unit pins:
    * No-fodder no-op: source alone on its controller's bf — silent
      no-op, NO inner draw (sac-first-then-inner flow).
    * With-fodder sac+inner fires: fodder bear on p0's bf is the
      first eligible victim; resolve sacrifices it (bf → p0's
      graveyard) AND fires the inner DrawCards (p0's hand size
      increases).
    * Opponent creature ineligible: opponent-controlled creature is
      NOT picked (CR-style "controller_id == controller_id" filter).
    * Source itself excluded: even if the source is the only
      creature, the "another" filter excludes it from being its own
      sacrifice victim.
- **GENUINE real-EoE cross-engine byte-equal probe** drives the
  parsed Swarm Culler printing through the
  ``trajectory._python_spell_effect_to_dict`` →
  ``cross_engine._ta_dict_to_python_effect`` round-trip surface, and
  through the directly-applied Rust resolve arm on a synthetic state
  matching Swarm Culler's printed body (fodder bear sacrificed,
  source controller draws a card).
"""

from __future__ import annotations

import importlib.util

import pytest


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


def test_real_swarm_culler_becomes_tapped_trigger_is_optional_sac_another_for_effect():
    """**Verify-first.** The live parser maps Swarm Culler's
    BECOMES_TAPPED trigger to
    ``OptionalSacAnotherForEffect(inner_effect=DrawCards(amount=1))``.
    Pin the field shape so a parser drift is caught here, not silently
    downstream in the cross-engine probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import OptionalSacAnotherForEffect
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.predicates import Event, IsSelf

    p = get_active_source().get_printings().get("Swarm Culler")
    if p is None:
        pytest.skip("Swarm Culler absent from active CardSource")
    assert "Creature" in p.card_types
    # Verify flying is on the printed face — substrate dependency.
    assert "flying" in p.keywords
    # Find the single BECOMES_TAPPED triggered ability.
    tap_tas = [
        ta for ta in p.triggered_abilities
        if ta.event is Event.BECOMES_TAPPED
    ]
    assert len(tap_tas) == 1, (
        f"Swarm Culler must have exactly 1 BECOMES_TAPPED triggered "
        f"ability; got {len(tap_tas)}"
    )
    ta = tap_tas[0]
    assert isinstance(ta.predicate, IsSelf)
    assert ta.predicate.subject is None
    assert isinstance(ta.effect, OptionalSacAnotherForEffect), (
        f"BECOMES_TAPPED trigger effect must be "
        f"OptionalSacAnotherForEffect; got {type(ta.effect).__name__}"
    )
    # Inner Effect is DrawCards(amount=1).
    assert isinstance(ta.effect.inner_effect, DrawCards), (
        f"Inner Effect must be DrawCards; "
        f"got {type(ta.effect.inner_effect).__name__}"
    )
    assert ta.effect.inner_effect.amount == 1


# -------------------------------------------------------------------
# Serializer round-trip + covered-set membership pins.
# -------------------------------------------------------------------


_SWARM_KIND = "optional_sac_another_for_effect"
_INNER_DRAW_DICT = {"kind": "draw_cards", "count": 1}


def test_swarm_culler_effect_dict_to_python_round_trip():
    """Rust-shape dict → Python ``OptionalSacAnotherForEffect`` via
    ``_ta_dict_to_python_effect`` reconstructs the wrapper with a
    non-trivial inner Effect (DrawCards). Bridge arm is the lever
    flip — without it, a Rust→Python triggered-ability translation
    would raise on the unknown kind. The recursion exercises the
    nested ``inner_effect`` field translation."""
    from mtg_bot.effects.combinators import OptionalSacAnotherForEffect
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    d = {
        "kind": _SWARM_KIND,
        "inner_effect": _INNER_DRAW_DICT,
    }
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, OptionalSacAnotherForEffect), (
        f"dict→Python bridge must round-trip to "
        f"OptionalSacAnotherForEffect; got {type(rebuilt).__name__}"
    )
    assert isinstance(rebuilt.inner_effect, DrawCards), (
        f"Inner Effect must be DrawCards; "
        f"got {type(rebuilt.inner_effect).__name__}"
    )
    assert rebuilt.inner_effect.amount == 1


def test_swarm_culler_effect_trajectory_serializer_round_trip():
    """Python
    ``OptionalSacAnotherForEffect(inner_effect=DrawCards(amount=1))``
    → ``trajectory._python_spell_effect_to_dict`` emits the two-key
    dict shape with the recursive inner dict;
    ``cross_engine._ta_dict_to_python_effect`` reconstructs the
    equivalent class. The recursive leaf is the substrate landing —
    a follow-up cycle widening the bench admit set picks it up for
    free."""
    from mtg_bot.effects.combinators import OptionalSacAnotherForEffect
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    src = OptionalSacAnotherForEffect(
        inner_effect=DrawCards(amount=1),
    )
    d = trajectory._python_spell_effect_to_dict(src)
    assert d == {
        "kind": _SWARM_KIND,
        "inner_effect": _INNER_DRAW_DICT,
    }, (
        f"reverse serializer must emit the two-key dict with the "
        f"recursive inner; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, OptionalSacAnotherForEffect)
    assert isinstance(rebuilt.inner_effect, DrawCards)
    assert rebuilt.inner_effect.amount == 1


def test_swarm_culler_rust_effect_to_pydict_round_trip():
    """Rust ``Effect::OptionalSacAnotherForEffect { inner_effect }``
    → dict emits the expected two-key shape with the recursive inner
    dict. Drives the round-trip through ``Registry.register_printing``
    (the parse path) + ``get_printing_etb_effects`` (the
    ``effect_to_pydict`` readback)."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Swarm Culler Round-trip",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 4,
            "mana_cost": {"generic": 3, "B": 1},
            "etb_effects": [
                {
                    "kind": _SWARM_KIND,
                    "inner_effect": _INNER_DRAW_DICT,
                },
            ],
        }
    )
    effs = reg.get_printing_etb_effects(pid)
    assert len(effs) == 1, f"expected 1 etb_effect, got {len(effs)}"
    eff = effs[0]
    assert eff["kind"] == _SWARM_KIND
    # Recursive inner is a dict — verify the inner kind.
    inner = eff["inner_effect"]
    assert inner["kind"] == "draw_cards"
    assert inner["count"] == 1


def test_swarm_culler_class_covered_by_rust():
    """``OptionalSacAnotherForEffect`` must be in the covered-by-rust
    set — the Rust ``Effect::OptionalSacAnotherForEffect`` variant
    declaration makes ``covered_python_class_set()`` include it via
    the 1:1 identity-mapping rule in
    ``effect_coverage.map_rust_to_python``. This is the §2 covered-
    set tooth (parity-doc / coverage-script "covered" alignment) AND
    the closure of the classifier's ``effect_uncovered`` gate for
    Swarm Culler."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "OptionalSacAnotherForEffect" in covered, (
        "Rust Effect::OptionalSacAnotherForEffect variant must make "
        "the Python OptionalSacAnotherForEffect class covered via the "
        "1:1 identity-mapping rule"
    )


# -------------------------------------------------------------------
# Rust resolve-arm unit pins (no-fodder no-op, sac+inner fires,
# opponent ineligible, source-itself excluded).
# -------------------------------------------------------------------


def _fresh_rust_state():
    import mtg_bot_engine
    return mtg_bot_engine.make_synthetic_state(0, 0, 0)


def _swarm_like_printing() -> dict:
    """Synthetic Swarm-Culler-shaped printing. The "effects" list is
    the spell_effect list the cast-pipeline resolves on
    push_to_stack+resolve_top_of_stack. The real card composes this
    Effect under a BECOMES_TAPPED triggered ability; the substrate
    unit pin exercises the resolve arm directly via the spell-
    resolution pipeline (same shape the Hemosymbic Mite probe uses
    for its ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower``
    substrate)."""
    return {
        "name": "Swarm Probe Source",
        "card_types": ["Creature"],
        "power": 2,
        "toughness": 4,
        "keywords": ["flying"],
        "mana_cost": {"generic": 3, "B": 1},
        "effects": [
            {
                "kind": _SWARM_KIND,
                "inner_effect": _INNER_DRAW_DICT,
            },
        ],
    }


# A plain creature target — eligible fodder for the optional sac.
_VANILLA_BEAR_DICT: dict = {
    "name": "Vanilla Bear",
    "card_types": ["Creature"],
    "power": 2,
    "toughness": 2,
    "mana_cost": {"generic": 1, "G": 1},
}


# A non-creature artifact — also eligible fodder (creature OR
# artifact filter).
_PLAIN_ARTIFACT_DICT: dict = {
    "name": "Plain Artifact",
    "card_types": ["Artifact"],
    "mana_cost": {"generic": 2},
}


# A non-creature non-artifact permanent — must be skipped by the
# per-eligibility filter.
_PLAIN_ENCHANTMENT_DICT: dict = {
    "name": "Plain Enchantment",
    "card_types": ["Enchantment"],
    "mana_cost": {"generic": 2},
}


def _seat_library_cards(rs, owner: int, n: int) -> None:
    """Seat ``n`` plain creature cards in ``owner``'s library so the
    inner ``DrawCards`` arm has cards to draw. Each card seeded via
    ``register_and_inject_object`` into the LIBRARY zone."""
    for i in range(n):
        rs.register_and_inject_object(
            {
                "name": f"Library Card {i}",
                "card_types": ["Creature"],
                "power": 1,
                "toughness": 1,
                "mana_cost": {"generic": 1},
            },
            owner,
            ZONE_LIBRARY,
        )


def _hand_size(rs, owner: int) -> int:
    return len(rs.hand_snapshot(owner))


def test_rust_resolve_no_fodder_silent_noop_no_draw():
    """**Rust pin (a): no-fodder no-op.** Source is the only permanent
    on its controller's bf — no eligible victim (the "another" filter
    excludes the source itself). Silent no-op: NO sacrifice AND NO
    inner draw (sac-first-then-inner flow; mirrors Python's
    ``if not options: return`` early-return at
    ``combinators.py:395-396`` BEFORE the inner_effect.resolve call).
    """
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _swarm_like_printing(), 0, ZONE_BATTLEFIELD,
    )
    _seat_library_cards(rs, 0, 3)
    hand_before = _hand_size(rs, 0)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    # Source still on bf (no self-sacrifice).
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert src_id in bf_ids
    # NOTHING in p0's graveyard — no sac occurred.
    assert rs.graveyard_snapshot(0) == [], (
        "no sacrifice occurred → graveyard stays empty"
    )
    # NO inner draw fired — hand size unchanged.
    assert _hand_size(rs, 0) == hand_before, (
        f"no-fodder path: inner DrawCards must NOT fire; "
        f"hand size went {hand_before} → {_hand_size(rs, 0)}"
    )


def test_rust_resolve_with_fodder_sacs_first_eligible_and_inner_fires():
    """**Rust pin (b): sac + inner draw.** A fodder bear on p0's bf
    is the first eligible victim; resolve sacrifices it (bf → p0's
    graveyard) AND fires the inner DrawCards (p0's hand size
    increases by exactly 1). Mirrors Python's flow at
    ``combinators.py:401-419``: pick first eligible → sacrifice →
    inner_effect.resolve."""
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _swarm_like_printing(), 0, ZONE_BATTLEFIELD,
    )
    bear_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 0, ZONE_BATTLEFIELD,
    )
    _seat_library_cards(rs, 0, 3)
    hand_before = _hand_size(rs, 0)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly"

    # Bear sacrificed → bf no longer contains it; p0's graveyard
    # now does.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert bear_id not in bf_ids, "fodder bear must be sacrificed"
    assert src_id in bf_ids, "source must remain on bf"
    gy0_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert bear_id in gy0_ids, (
        "sacrificed bear must move to controller's graveyard"
    )
    # Inner DrawCards fired → p0's hand grew by exactly 1.
    assert _hand_size(rs, 0) == hand_before + 1, (
        f"inner DrawCards(1) must fire after sac; hand size went "
        f"{hand_before} → {_hand_size(rs, 0)}"
    )


def test_rust_resolve_opponent_creature_is_not_eligible_fodder():
    """**Rust pin (c): opponent creature ineligible.** An opponent-
    controlled creature is NOT eligible fodder (the Python filter
    requires ``o.controller_id == controller_id`` — only the
    source's controller's permanents qualify). Resolve is a silent
    no-op even though p1 has a bear on the battlefield — AND the
    inner DrawCards is NOT invoked (sac-first-then-inner flow)."""
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _swarm_like_printing(), 0, ZONE_BATTLEFIELD,
    )
    p1_bear_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 1, ZONE_BATTLEFIELD,
    )
    _seat_library_cards(rs, 0, 3)
    hand_before = _hand_size(rs, 0)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0

    # p1's bear unchanged on p1's bf.
    p1_bear_alive = any(
        e["id"] == p1_bear_id for e in rs.battlefield_snapshot()
    )
    assert p1_bear_alive, "opponent bear must NOT be sacrificed"
    # No draw on either side.
    assert _hand_size(rs, 0) == hand_before, (
        "opponent-only fodder: NO sac → NO inner draw"
    )


def test_rust_resolve_source_itself_excluded_via_another_filter():
    """**Rust pin (d): source excluded via CR 115.4 "another".** Even
    if the source is the ONLY creature on its controller's bf, the
    "another" filter excludes it. Resolve is a silent no-op. Pin the
    self-exclusion explicitly so a future regression on the
    ``o.id != source.id`` filter is caught (the source must NEVER be
    its own sacrifice victim)."""
    rs = _fresh_rust_state()
    # Source is the ONLY creature on bf — no other creature/artifact.
    src_id = rs.register_and_inject_object(
        _swarm_like_printing(), 0, ZONE_BATTLEFIELD,
    )
    # A non-creature non-artifact permanent — must also be skipped.
    enchant_id = rs.register_and_inject_object(
        _PLAIN_ENCHANTMENT_DICT, 0, ZONE_BATTLEFIELD,
    )
    _seat_library_cards(rs, 0, 3)
    hand_before = _hand_size(rs, 0)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0

    # Source still alive; the enchantment too (not eligible fodder).
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert src_id in bf_ids, (
        "source must NOT be its own sacrifice victim (CR 115.4 "
        "'another' / Python's o.id != source.id filter)"
    )
    assert enchant_id in bf_ids, (
        "enchantment is NOT in the creature-OR-artifact filter — "
        "must NOT be sacrificed"
    )
    # No graveyard activity, no draw.
    assert rs.graveyard_snapshot(0) == []
    assert _hand_size(rs, 0) == hand_before


def test_rust_resolve_artifact_fodder_is_eligible():
    """**Rust pin (e — defense in depth): artifact fodder eligible.**
    Artifacts on the controller's bf are eligible fodder (the
    Python filter is
    ``o.printing.is_creature or o.printing.is_artifact``). Pin the
    artifact-half of the eligibility OR explicitly — Swarm Culler's
    printed oracle reads "creature or artifact" and both halves
    must fire on the Rust side."""
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _swarm_like_printing(), 0, ZONE_BATTLEFIELD,
    )
    artifact_id = rs.register_and_inject_object(
        _PLAIN_ARTIFACT_DICT, 0, ZONE_BATTLEFIELD,
    )
    _seat_library_cards(rs, 0, 3)
    hand_before = _hand_size(rs, 0)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0

    # Artifact sacrificed; inner draw fires.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert artifact_id not in bf_ids, (
        "artifact must be eligible fodder (creature OR artifact filter)"
    )
    gy0_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert artifact_id in gy0_ids
    assert _hand_size(rs, 0) == hand_before + 1, (
        "inner DrawCards must fire after artifact sacrifice"
    )


# -------------------------------------------------------------------
# GENUINE real-EoE cross-engine probe — drives the parsed Swarm
# Culler printing through the trajectory →
# _ta_dict_to_python_effect round-trip pipeline, and through the
# directly-applied Rust resolve arm on a synthetic state matching
# the parsed printing's body. Same Hemosymbic-Mite-style PROBED-tier
# round-trip + Rust resolve byte-equal observable.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_swarm_culler_round_trip():
    """**GENUINE real-EoE cross-engine byte-equal probe — Swarm
    Culler optional-sac-for-effect.** The slug-credit anchor for the
    PROBED tier flip even though the classifier multi-gates the card
    on ``nonsafe_triggered_ability``.

    Drives the **real parsed Swarm Culler printing** through the
    trajectory serializer + cross-engine dict→Python bridge:

      * Extract the parsed BECOMES_TAPPED triggered-ability effect
        from the real EoE printing.
      * Walk the effect — must be
        ``OptionalSacAnotherForEffect(inner_effect=DrawCards(1))``
        per the §2 parser SoT pin.
      * Serialize via ``trajectory._python_spell_effect_to_dict`` →
        the two-key dict with the recursive inner.
      * Round-trip via ``cross_engine._ta_dict_to_python_effect`` →
        a fresh
        ``OptionalSacAnotherForEffect(inner_effect=DrawCards(1))``
        equal to the parser-emitted effect.
      * Drive the effect's resolve through Rust on a synthetic
        state matching Swarm Culler's printed body — the fodder
        bear is sacrificed and the controller draws exactly 1
        card, byte-equal-observable to the round-trip dict.

    **Byte-equality scope.** Both the parser-emitted effect and the
    bridge-reconstructed effect compare equal as frozen dataclasses
    on the recursive inner; the Rust-side resolve lands a byte-equal
    bf→graveyard transition AND a +1 hand-size delta on the source's
    controller.

    **Cycle 1 scope caveat.** The full real-EoE BECOMES_TAPPED
    trigger-fan-out byte-equal probe through both engines's
    ``turn.tap_permanent`` machinery requires per-engine coordination
    of the trigger-pushed-onto-stack timing — that broader probe is
    honest-stopped at Cycle 1; the substrate-level round-trip + the
    Rust resolve-arm unit pins carry the PROBED tier flip per the
    Hemosymbic Mite / Ouroboroid / Terrapact Intimidator /
    Boilerbilges Ripper / Fanatic of the Harrowing classifier-
    bypass precedent.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.combinators import OptionalSacAnotherForEffect
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.predicates import Event
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    real = get_active_source().get_printings().get("Swarm Culler")
    if real is None:
        pytest.skip("Swarm Culler absent from active CardSource")

    # §2 source-of-truth: genuine BECOMES_TAPPED trigger must be
    # OptionalSacAnotherForEffect(inner_effect=DrawCards(1)).
    tap_ta = next(
        (
            ta for ta in real.triggered_abilities
            if ta.event is Event.BECOMES_TAPPED
        ),
        None,
    )
    assert tap_ta is not None, (
        "Swarm Culler must have a BECOMES_TAPPED triggered ability"
    )
    leaf = tap_ta.effect
    assert isinstance(leaf, OptionalSacAnotherForEffect), (
        f"BECOMES_TAPPED trigger effect must be "
        f"OptionalSacAnotherForEffect; got {type(leaf).__name__}"
    )
    assert isinstance(leaf.inner_effect, DrawCards)
    assert leaf.inner_effect.amount == 1

    # Round-trip the leaf through trajectory serializer + cross-engine
    # dict→Python bridge.
    d = trajectory._python_spell_effect_to_dict(leaf)
    assert d == {
        "kind": _SWARM_KIND,
        "inner_effect": _INNER_DRAW_DICT,
    }, (
        f"real-EoE leaf serializer must emit the two-key dict with "
        f"the recursive inner; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, OptionalSacAnotherForEffect)
    assert isinstance(rebuilt.inner_effect, DrawCards)
    assert rebuilt.inner_effect.amount == leaf.inner_effect.amount

    # Drive the leaf through Rust's resolve arm on a synthetic state
    # matching the parsed printing's body. Fodder bear must be
    # sacrificed AND the source's controller must draw exactly 1.
    rs = _fresh_rust_state()
    src_id = rs.register_and_inject_object(
        _swarm_like_printing(), 0, ZONE_BATTLEFIELD,
    )
    bear_id = rs.register_and_inject_object(
        _VANILLA_BEAR_DICT, 0, ZONE_BATTLEFIELD,
    )
    _seat_library_cards(rs, 0, 3)
    hand_before = _hand_size(rs, 0)

    rs.push_to_stack(src_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0

    # The fodder bear is sacrificed; p0 draws exactly 1.
    bf_ids = [e["id"] for e in rs.battlefield_snapshot()]
    assert bear_id not in bf_ids, "fodder bear must be sacrificed"
    gy0_ids = [e["id"] for e in rs.graveyard_snapshot(0)]
    assert bear_id in gy0_ids
    assert _hand_size(rs, 0) - hand_before == 1, (
        f"source controller must draw exactly 1 card from the inner "
        f"DrawCards; delta={_hand_size(rs, 0) - hand_before}"
    )
