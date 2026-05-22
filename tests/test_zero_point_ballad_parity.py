"""Cross-engine parity probes for Zero Point Ballad.

**X-value subsystem — Cycle 3 (the FIRST X-cost cross-engine close).**
Zero Point Ballad `{X}{B}` Sorcery (EoE): "Destroy all creatures with
toughness X or less. You lose X life. If X is 6 or more, return a
creature card put into a graveyard this way to the battlefield under
your control."

The substrate that makes this slice possible:

  1. C1 (commit ``7c28643c``): per-StackItem ``x_value: Option<i32>``
     slot + ``GameState.current_resolve_x_value`` transient + the
     save → set → restore bracket in both ``resolve_top_of_stack``
     entry points + PyO3 getter/setter + the constructor subsumption
     ``new_spell_with_targets_mode_addcost_and_x``.
  2. C2 (commit ``6a35d8e0``): ``cards::ManaCost.x_pips: u8`` field +
     ``parse_mana_cost`` accepts the ``"X"`` key +
     ``mana_cost_to_pydict`` emits it + ``Registry.get_printing_x_pips``
     PyO3 getter.
  3. C2.5 (commit ``157336d1``): admit-predicate widen
     (``_printing_is_x_cost`` local; Phase 3 wrath shape is the SOLE
     admit phase for X-cost printings) + cast-pipeline detector in
     ``cast_spell_noncreature``'s Delta-2 block (binds X via the
     no-agent fallback → X=0 on the cross-engine harness; folds
     ``x_pips * x_value`` into generic; threads ``Some(0)`` into
     the C1 constructor — the FIRST live mint site).
  4. C3 (THIS LANE): ``Effect::ZeroPointBalladEffect`` Rust unit
     variant + parse arm + ``to_pydict`` arm + resolve arm (reads
     ``current_resolve_x_value``, applies the X-dependent destroy +
     lose-X-life + X>=6 reanimation surface) + bridge dict→Python
     arm + reverse serializer leaf.

Lives in its own module per the per-card parity probe convention
(mirrors ``test_exorcise_parity.py`` /
``test_scour_for_scrap_parity.py`` / ``test_drill_too_deep_parity.py``).

**Cross-engine harness X=0 dormancy.** Under the no-agent harness
(``agent=None`` on Python; X=0 mint on Rust per C2.5), the destroy
walks creatures with effective toughness <= 0 (typically empty —
SBA has already removed every <=0 creature at the prior SBA pass).
Lose-X-life is ``-= 0``. The X>=6 reanimation branch is dormant.
The cross-engine probe at X=0 verifies parse + admit + serializer
round-trip + resolve byte-equal without exercising the X-dependent
surface. The X-dependent surface is exercised by the synthetic-state
Rust unit pins (X=0 happy-path + X=2 destroy-by-toughness +
X=6 reanimation). This is the deliberate harness limitation
documented in ``docs/SEARCH_LIMITATIONS.md``.

Covered:

  - Parser SoT: the live parsed Zero Point Ballad printing's
    ``spell_effect`` IS the field-free Python ``ZeroPointBalladEffect()``;
    its ``mana_cost.x_pips == 1``.
  - Serializer round-trip: ``_python_spell_effect_to_dict`` emits
    ``{"kind": "zero_point_ballad_effect"}``; the dict→Python bridge
    reconstructs ``ZeroPointBalladEffect()``.
  - Admit-gate flip: Zero Point Ballad NOW passes
    ``_printing_is_bridge_simple_spell`` (the §2 auto-grow teeth fire
    positively post-C3); the C2.5 widen accepted the SHAPE, the C3
    Effect arm + bridge arms fill in the covered+bridged + round-trip
    teeth.
  - Rust resolve unit pins:
      * X=0 base: empty bf, empty graveyard → silent vacuous-resolve;
        controller's life is unchanged; no panic.
      * X=2 destroy-by-toughness: bf with a 1/1 (destroyed), a 2/2
        (destroyed), a 3/3 (survives); caster loses 2 life.
      * X=6 reanimation: bf with a caster-owned 3/3 → destroyed; X=6
        ≥ 6 fires the reanimation branch; the 3/3 returns to the
        caster's battlefield.
      * indestructible-skip: an indestructible 1/1 on the bf is NOT
        destroyed (CR 702.12). Lose-X-life still fires.
  - GENUINE real-EoE cross-engine byte-equal probe:
    ``test_cross_engine_real_eoe_zero_point_ballad_x_value_parity``
    drives the parsed Zero Point Ballad printing through both
    engines at X=0 on an empty-bf state; asserts the WHOLE field
    view byte-equal post-resolve.
"""

from __future__ import annotations

import pytest


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_zero_point_ballad_spell_effect_is_zero_point_ballad_effect():
    """**Verify-first.** The live parser maps Zero Point Ballad to
    ``ZeroPointBalladEffect()`` — a parameterless frozen dataclass —
    and its ``mana_cost.x_pips == 1``. This pin freezes the parser SoT
    so a parser drift is caught here, not silently downstream in the
    cross-engine probe.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import ZeroPointBalladEffect

    p = get_active_source().get_printings().get("Zero Point Ballad")
    if p is None:
        pytest.skip("Zero Point Ballad absent from active CardSource")
    assert "Sorcery" in p.card_types
    assert isinstance(p.spell_effect, ZeroPointBalladEffect), (
        f"Zero Point Ballad spell_effect must be ZeroPointBalladEffect; "
        f"got {type(p.spell_effect).__name__}"
    )
    assert p.mana_cost.x_pips == 1, (
        f"Zero Point Ballad mana_cost.x_pips must be 1 ({{X}}{{B}}); "
        f"got {p.mana_cost.x_pips}"
    )


# -------------------------------------------------------------------
# Round-trip + admit-gate pins (the auto-grow §2 teeth).
# -------------------------------------------------------------------


def test_zero_point_ballad_serializer_round_trip():
    """The trajectory reverse-serializer must emit a clean
    ``{"kind": "zero_point_ballad_effect"}`` unit dict; the dict→Python
    bridge must reconstruct ``ZeroPointBalladEffect()``.

    A no-emit serializer would short-circuit the admit gate (the
    no-fallback-hybrid teeth). With the leaf landed and the variant
    field-free, the round-trip is byte-equal both ways.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import ZeroPointBalladEffect
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    p = get_active_source().get_printings().get("Zero Point Ballad")
    if p is None:
        pytest.skip("Zero Point Ballad absent from active CardSource")
    d = trajectory._python_spell_effect_to_dict(p.spell_effect)
    assert d == {"kind": "zero_point_ballad_effect"}, (
        f"Zero Point Ballad reverse serializer must emit the bare "
        f"unit-variant dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, ZeroPointBalladEffect), (
        f"dict→Python bridge must round-trip to ZeroPointBalladEffect; "
        f"got {type(rebuilt).__name__}"
    )


def test_zero_point_ballad_passes_bridge_admit_gate():
    """**The lever flip pin.** Post-Cycle-3, Zero Point Ballad MUST
    pass ``_printing_is_bridge_simple_spell`` — the spell-card-bridge
    admit gate. Phase-3 wrath ``(0, 0)``-shape admit + X-cost C2.5
    widen + Effect covered+bridged + serializer round-trips (the §2
    teeth all fire positively).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = get_active_source().get_printings().get("Zero Point Ballad")
    if p is None:
        pytest.skip("Zero Point Ballad absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(p) is True, (
        "Zero Point Ballad must auto-join the spell-card-bridge admit "
        "set post-C3 (covered+bridged + round-trips + Phase-3 shape)"
    )
    # Pin per-tooth gates — if any one fails, debug-time message points
    # at WHICH tooth.
    assert (
        trajectory._spell_effect_is_covered_and_bridged(p) is True
    )
    assert (
        trajectory._python_spell_effect_to_dict(p.spell_effect)
        is not None
    )


def test_zero_point_ballad_class_covered():
    """``ZeroPointBalladEffect`` must be in the covered-by-rust set —
    the Rust ``Effect::ZeroPointBalladEffect`` variant declaration
    makes ``covered_python_class_set()`` include it (1:1 identity
    mapping; no override needed). Without this, the §2 admit-gate
    teeth refuse to flip the card.
    """
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "ZeroPointBalladEffect" in covered, (
        "Rust Effect::ZeroPointBalladEffect variant must make the "
        "Python ZeroPointBalladEffect class covered"
    )


# -------------------------------------------------------------------
# Rust resolve-arm pins (synthetic state — drives X=0 base / X=2
# destroy-by-toughness / X>=6 reanimation / indestructible-skip).
# -------------------------------------------------------------------


def _build_rust_zpb_state(
    *,
    creatures=(),
    grave_creatures=(),
    x_value=0,
):
    """Build a Rust state with Zero Point Ballad on p0's stack +
    seeded creatures on each bf + the X value bound to the StackItem's
    ``x_value`` slot via the C1 synthetic setter.

    ``creatures``: iterable of (owner_pidx, name, power, toughness,
                                  indestructible?, counters?) tuples.
    ``grave_creatures``: iterable of (owner_pidx, name, power,
                                       toughness) tuples seeded into
                          that player's graveyard (used as base state
                          for the X>=6 reanimation pin — the bf
                          destroy pushes the destroyed creatures
                          itself into the graveyard, so this is for
                          pre-seeded "creature cards already in the
                          caster's graveyard but NOT put there this
                          way" cases — kept as a forward-substrate
                          hook; today's pins seed only via destroys).
    Returns ``(rs, target_ids)`` where ``target_ids`` is a list of the
    bf object ids in seed order.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    ZB = 2  # battlefield
    ZG = 3  # graveyard
    target_ids = []
    for owner_pidx, name, power, toughness, indestr, counters in (
        creatures
    ):
        printing = {
            "name": name,
            "card_types": ["Creature"],
            "power": power,
            "toughness": toughness,
        }
        if indestr:
            printing["keywords"] = ["indestructible"]
        oid = rs.register_and_inject_object(printing, owner_pidx, ZB)
        if counters:
            rs.add_counters(oid, counters)
        target_ids.append(oid)
    for owner_pidx, name, power, toughness in grave_creatures:
        rs.register_and_inject_object(
            {"name": name, "card_types": ["Creature"],
             "power": power, "toughness": toughness},
            owner_pidx, ZG,
        )
    spell_id = rs.register_and_inject_object(
        {"name": "Zero Point Ballad",
         "card_types": ["Sorcery"],
         "effects": [{"kind": "zero_point_ballad_effect"}]},
        0, 0,
    )
    rs.push_to_stack(spell_id, 0)
    # Bind X via the C1 synthetic setter (the production cast-time
    # bind would mint Some(0) for the no-agent harness per C2.5, but
    # this surface pins the X-dependent branches at higher synthetic
    # X values that no-agent harness can never produce alone).
    rs.set_stack_top_x_value(x_value)
    return rs, target_ids


def test_rust_zpb_x_zero_vacuous_resolve():
    """Rust pin (a): X=0 base — empty bf → silent vacuous-resolve.
    No state mutation, no panic. Mirrors the no-agent harness's X=0
    mint behavior (the cross-engine probe's dominant resolve shape).
    """
    rs, _ = _build_rust_zpb_state(creatures=(), x_value=0)
    p0_life_before, p1_life_before = rs.life_totals
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve cleanly at X=0"
    # X=0 lose-X-life is a -= 0 no-op.
    p0_after, p1_after = rs.life_totals
    assert p0_after == p0_life_before, (
        "caster's life must be unchanged at X=0"
    )
    assert p1_after == p1_life_before, (
        "non-caster's life must be unchanged"
    )


def test_rust_zpb_x_two_destroys_by_toughness():
    """Rust pin (b): X=2 — destroys creatures with toughness 1 and 2
    (both legs of the ``<= X`` filter), leaves the 3/3 alive. The
    caster (p0) loses 2 life. Mirrors Python
    ``ZeroPointBalladEffect.resolve``'s first two clauses.
    """
    rs, target_ids = _build_rust_zpb_state(
        creatures=(
            # owner_pidx, name, power, toughness, indestr, counters
            (1, "ZPB Victim 1/1", 1, 1, False, 0),
            (1, "ZPB Victim 2/2", 2, 2, False, 0),
            (1, "ZPB Survivor 3/3", 3, 3, False, 0),
        ),
        x_value=2,
    )
    onehp_id, twohp_id, threehp_id = target_ids
    p0_life_before = rs.life_totals[0]
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0
    # 1/1 + 2/2 destroyed, 3/3 survives.
    bf_ids_after = {e["id"] for e in rs.battlefield_snapshot()}
    assert onehp_id not in bf_ids_after, (
        "1-toughness creature must be destroyed at X=2"
    )
    assert twohp_id not in bf_ids_after, (
        "2-toughness creature must be destroyed at X=2"
    )
    assert threehp_id in bf_ids_after, (
        "3-toughness creature must SURVIVE at X=2"
    )
    # Caster loses X=2 life.
    p0_after = rs.life_totals[0]
    assert p0_after == p0_life_before - 2, (
        f"caster's life must drop by 2 (X=2); was {p0_life_before}, "
        f"got {p0_after}"
    )


def test_rust_zpb_indestructible_skip_but_lose_life_still_fires():
    """Rust pin (c): an indestructible 1/1 on the bf is NOT destroyed
    (CR 702.12 — indestructible permanents are not destroyed; their
    SBA / destroy-effect destroy is suppressed). Lose-X-life still
    fires (it isn't gated on destroy success). Distinguishes the
    destroy-gate from the lose-life leg.
    """
    rs, target_ids = _build_rust_zpb_state(
        creatures=(
            (1, "ZPB Indestructible 1/1", 1, 1, True, 0),
        ),
        x_value=3,
    )
    p0_life_before = rs.life_totals[0]
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    bf_ids_after = {e["id"] for e in rs.battlefield_snapshot()}
    assert target_ids[0] in bf_ids_after, (
        "indestructible 1/1 MUST survive Zero Point Ballad at X=3 "
        "(CR 702.12 suppresses the destroy)"
    )
    # Lose-X-life leg still fires independently of the destroy gate.
    assert rs.life_totals[0] == p0_life_before - 3, (
        "caster's life must drop by X=3 even when no creatures are "
        "destroyed (the lose-X-life leg is unconditional)"
    )


def test_rust_zpb_x_six_reanimates_caster_owned_victim():
    """Rust pin (d): X=6 — destroys a caster-owned 3/3 → the
    reanimation branch fires (X >= 6) → the 3/3 returns to the
    caster's battlefield. Mirrors Python ``bespoke.py:1722-1741``
    under a target-picker shape that always picks the FIRST candidate
    (the deterministic-first convention every other Effect arm
    consumes for cross-engine parity).

    Distinguishes the X<6 dormant branch from the X>=6 active
    branch — the X<6 case is pinned by the X=2 destroy pin above
    (which destroys caster-owned creatures but does NOT reanimate
    them).
    """
    rs, target_ids = _build_rust_zpb_state(
        creatures=(
            # Caster-owned 3/3 (p0's bf) — destroyed AND returned.
            (0, "ZPB Caster 3/3", 3, 3, False, 0),
        ),
        x_value=6,
    )
    p0_life_before = rs.life_totals[0]
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # The 3/3 was destroyed (Python's destroy-then-reanimate sequence
    # routes the object through the graveyard mid-resolve), then the
    # X>=6 branch reanimated it to p0's battlefield. Pin the FINAL
    # observable: the creature is back on p0's bf with the same id.
    bf = rs.battlefield_snapshot()
    bf_ids = {e["id"] for e in bf}
    # Identity is preserved by the bf-pop → push-graveyard →
    # pop-graveyard → push-bf shape (the same obj.id rides through).
    assert target_ids[0] in bf_ids, (
        f"caster-owned 3/3 must return to the battlefield at X=6; "
        f"bf ids after resolve: {bf_ids}"
    )
    # Caster lost X=6 life (the lose-life leg fires BEFORE the
    # reanimation, but observable life is the same either way).
    p0_after = rs.life_totals[0]
    assert p0_after == p0_life_before - 6, (
        f"caster's life must drop by X=6; was {p0_life_before}, got "
        f"{p0_after}"
    )


def test_rust_zpb_x_six_dormant_when_no_caster_owned_victims():
    """Rust pin (e): X=6 but only opponent-controlled victims — the
    reanimation branch finds no caster-owned-victim-id candidates →
    silent fizzle on the reanimation tail (no creature returns).
    Mirrors Python's ``if candidates and p.agent is not None`` guard.
    """
    rs, target_ids = _build_rust_zpb_state(
        creatures=(
            # Opponent-owned 3/3 — destroyed but NOT in the caster's
            # owned-victim set, so the reanimation branch finds no
            # candidates.
            (1, "ZPB Opponent 3/3", 3, 3, False, 0),
        ),
        x_value=6,
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    bf_ids = {e["id"] for e in rs.battlefield_snapshot()}
    assert target_ids[0] not in bf_ids, (
        "opponent's 3/3 must STAY destroyed — the X>=6 reanimation "
        "branch is restricted to caster-owned victims"
    )


# -------------------------------------------------------------------
# Genuine real-printing cross-engine byte-equal probe.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_zero_point_ballad_x_value_parity():
    """**GENUINE real-printing cross-engine probe — Zero Point Ballad
    at X=0 (no-agent harness mint). X-value subsystem Cycle 3
    PROBED-tier flip.**

    Drives the **ACTUAL parsed Zero Point Ballad printing** on the
    Python side: ``get_active_source().get_printings()["Zero Point
    Ballad"]`` — which the live parser maps to a ``spell_effect`` of
    ``ZeroPointBalladEffect()`` (verified above) with
    ``mana_cost.x_pips == 1``.

    Oracle (verbatim, ``data/edge_of_eternities.json``):

        "[Sorcery] {X}{B} — Destroy all creatures with toughness X or
         less. You lose X life. If X is 6 or more, return a creature
         card put into a graveyard this way to the battlefield under
         your control."

    **No-agent harness X=0 mint (C2.5 SoT).** Under the cross-engine
    harness, Python's ``_choose_and_apply_x`` at
    ``actions.py:529-549`` returns 0 when ``p.agent is None``; the
    Rust ``cast_spell_noncreature`` Delta-2 detector (C2.5) mints
    ``StackItem.x_value = Some(0)`` to match. The X-dependent surface
    (destroy-by-toughness, lose-X-life, X>=6 reanimation) is
    DORMANT at X=0:

      * Destroy filter ``effective_toughness <= 0`` — typically empty
        (SBA has already removed every <=0-toughness creature at the
        prior SBA pass).
      * Lose-X-life is ``-= 0``.
      * X>=6 branch dormant.

    This probe verifies the GENUINE parsed printing + C1+C2+C2.5+C3
    substrate + admit gate + serializer round-trip + resolve byte-
    equal at X=0, NOT the X-dependent action surface (which the
    synthetic-state Rust unit pins above exercise). This is the
    deliberate harness limitation documented in
    ``docs/SEARCH_LIMITATIONS.md`` — see the C3 LANDED block.

    p0 has the genuine Zero Point Ballad on the stack with X=0;
    p1 has a vanilla 3/3 (which CANNOT be destroyed at X=0 because
    3 > 0). The WHOLE field view is asserted byte-equal post-resolve.
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
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.bespoke import ZeroPointBalladEffect
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Zero Point Ballad")
    if real is None:
        pytest.skip("Zero Point Ballad absent from active CardSource")
    assert "Sorcery" in real.card_types
    assert isinstance(real.spell_effect, ZeroPointBalladEffect)

    def _vanilla_creature(name, power, toughness):
        return CardPrinting(
            name=name, mana_cost_str="",
            mana_cost=ManaCost(generic=0),
            type_line="Creature", supertypes=(),
            card_types=("Creature",), subtypes=(),
            power=power, toughness=toughness, produces=frozenset(),
            keywords=(),
        )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 opponent 3/3 vanilla — guaranteed-to-survive at X=0 (3 > 0
    # so it never enters the destroy filter; the probe pins the
    # invariant byte-equal under the dormant X-dependent surface).
    py_survivor = py.new_object(
        _vanilla_creature("ZPB Real Survivor 3/3", 3, 3),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_survivor.summoning_sick = False
    py.battlefield.append(py_survivor)
    rs_survivor = rs.register_and_inject_object(
        {"name": "ZPB Real Survivor 3/3",
         "card_types": ["Creature"],
         "power": 3, "toughness": 3},
        1, ZB,
    )

    # Cast the genuine Zero Point Ballad on Python with the StackItem's
    # x_value = 0 (the no-agent harness mint shape — agent is None
    # by default on a build_python_state, so the production cast path
    # would mint X=0 anyway; we set it explicitly on the StackItem to
    # mirror the Rust C2.5 mint side byte-equal).
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0, x_value=0)
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # Cast on Rust: push the spell, bind X=0 via the C1 setter (which
    # is what C2.5's production cast-pipeline detector also produces
    # under no-agent semantics — Some(0) for an X-cost spell). The
    # bridged synthetic Sorcery's effect dict carries the
    # ``zero_point_ballad_effect`` kind that round-trips to the
    # Python side via ``_ta_dict_to_python_effect``.
    rs_spell = rs.register_and_inject_object(
        {"name": "Zero Point Ballad",
         "card_types": ["Sorcery"],
         "effects": [{"kind": "zero_point_ballad_effect"}]},
        0, 0,
    )
    rs.push_to_stack(rs_spell, 0)
    rs.set_stack_top_x_value(0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # FULL byte-equal compare. At X=0 the destroy filter is empty
    # (3 > 0 — the 3/3 survives), the lose-life leg is -= 0, the
    # X>=6 branch is dormant. The post-resolve field view is byte-
    # equal across both engines (every observable — bf, graveyard,
    # life totals, exile, hand, library — matches).
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Zero Point Ballad at X=0 post-resolve must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )
    # Observable cross-checks.
    assert any(o.id == py_survivor.id for o in py.battlefield), (
        "Python: 3/3 must survive at X=0 (3 > 0; outside the destroy "
        "filter)"
    )
    assert any(
        e["id"] == rs_survivor for e in rs.battlefield_snapshot()
    ), "Rust: 3/3 must survive at X=0 (byte-equal)"
    # Caster lost X=0 life on both engines.
    assert py.players[0].life == 20, (
        "Python: caster's life unchanged at X=0"
    )
    assert rs.life_totals[0] == 20, (
        "Rust: caster's life unchanged at X=0 (byte-equal)"
    )
