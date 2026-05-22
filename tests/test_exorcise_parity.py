"""Cross-engine parity probes for Exorcise.

**Effect-uncovered single-gated tier — Exorcise (Duskmourn,
``data/duskmourn.json``).** ``{1}{W}`` Sorcery: "Exile target
artifact, enchantment, or creature with power 4 or greater."
Mirrors Python's ``ExorciseEffect`` (``effects/bespoke.py:2268``).

The substrate that makes this slice possible:

  1. ``Effect::ExorciseEffect`` field-free unit variant + parse
     ``"exorcise_effect"`` + ``to_pydict`` (``rust/src/cards.rs``)
     — schema parity with Python's parameterless ``ExorciseEffect``
     dataclass.
  2. Resolve arm in ``rust/src/state_ops_resolve.rs`` beside the
     Shattered Wings ``DestroyTargetArtifactEnchantmentOrFlyingCreature``
     sibling — same payload-target swap pattern, same 3-way OR
     filter shape, two differences: exile-not-destroy and
     power-4-not-flying. The power-4 leg reads EFFECTIVE power via
     the file-local ``read_doubling_power`` helper (folds base +
     ``ueot_power_bonus`` + ``obj.counters`` — matches Python's
     ``effective_power(state, obj)``).
  3. ``state_ops_legal.rs`` ``spell_targets_satisfiable`` arm with
     the same 3-way OR filter, NOT controller-restricted.
  4. ``cross_engine.py`` ``exorcise_effect`` dict→Python bridge arm
     (constructs the field-free ``ExorciseEffect()``).
  5. ``trajectory.py`` ``_python_spell_effect_to_dict`` ``_leaf`` arm
     emitting ``{"kind": "exorcise_effect"}`` — what flips Exorcise
     into the spell-card-bridge admit set (auto-grow, no hardcoded
     card list).

Lives in its own module (NOT in ``test_parity_smoke.py``) per the
concurrent-agent merge-conflict-minimization hint — Lane GG
(multi-target admit phase 4) is touching ``rust/src/state.rs`` and
the parity bridge, and the per-card parity probe modules avoid the
large shared ``test_parity_smoke.py`` file. Mirrors the
``test_drill_too_deep_parity.py`` per-card-module convention.

**Indestructible is NOT skipped on the exile leg** — exile bypasses
indestructible per CR 702.12. Distinguishes Exorcise from the
destroy siblings (Shattered Wings, etc.) which DO skip
indestructible. Probed positively below.

Covered:

- Real Duskmourn printing's spell_effect IS ``ExorciseEffect()``.
- Serializer round-trip emits the bare unit-variant dict; bridge
  dict→Python arm reconstructs ``ExorciseEffect()``.
- The card passes the ``_printing_is_bridge_simple_spell`` admit
  gate (auto-grow §2 teeth).
- Rust resolve arm exiles each leg of the 3-way OR (artifact;
  enchantment; 4+ power creature) and fizzles silently on a
  non-matching creature (3/3 with effective power 3).
- Rust resolve arm exiles an INDESTRUCTIBLE artifact (the exile-
  vs-destroy distinction).
- Effective-power leg reads counters: a 3/3 creature carrying a
  +1/+1 counter (effective power 4) is targetable.
- GENUINE real-printing cross-engine byte-equal probe — the parsed
  Exorcise printing driven against a 5/5 creature on the opponent's
  battlefield; both engines agree on the WHOLE field view
  post-resolve.
"""

from __future__ import annotations

import pytest


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_exorcise_spell_effect_is_exorcise_effect():
    """**Verify-first.** The live parser maps Exorcise to
    ``ExorciseEffect()`` — a parameterless frozen dataclass. This
    pin freezes the parser SoT so a parser drift is caught here, not
    silently downstream in the cross-engine probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import ExorciseEffect

    p = get_active_source().get_printings().get("Exorcise")
    if p is None:
        pytest.skip("Exorcise absent from active CardSource")
    assert "Sorcery" in p.card_types
    se = p.spell_effect
    assert isinstance(se, ExorciseEffect), (
        f"Exorcise spell_effect must be ExorciseEffect; got "
        f"{type(se).__name__}"
    )


# -------------------------------------------------------------------
# Round-trip + admit-gate pins (the auto-grow §2 teeth).
# -------------------------------------------------------------------


def test_exorcise_serializer_round_trip():
    """The trajectory reverse-serializer must emit a clean
    ``{"kind": "exorcise_effect"}`` unit dict; the dict→Python bridge
    must reconstruct ``ExorciseEffect()``.

    A no-emit serializer would short-circuit the admit gate (the no-
    fallback-hybrid teeth). With the leaf landed and the variant
    field-free, the round-trip is byte-equal both ways."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import ExorciseEffect
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    p = get_active_source().get_printings().get("Exorcise")
    if p is None:
        pytest.skip("Exorcise absent from active CardSource")
    d = trajectory._python_spell_effect_to_dict(p.spell_effect)
    assert d == {"kind": "exorcise_effect"}, (
        f"Exorcise reverse serializer must emit the bare unit-variant "
        f"dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, ExorciseEffect), (
        f"dict→Python bridge must round-trip to ExorciseEffect; got "
        f"{type(rebuilt).__name__}"
    )


def test_exorcise_passes_bridge_admit_gate():
    """**The lever flip pin.** Post-slice (this lane), Exorcise MUST
    pass ``_printing_is_bridge_simple_spell`` — the spell-card-bridge
    admit gate. The card has (1, 1) target_count_range with the
    permanent slot kind (Phase-1 admit shape); the spell_effect is
    covered+bridged; the serializer round-trips cleanly (the §2 teeth
    all fire positively)."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = get_active_source().get_printings().get("Exorcise")
    if p is None:
        pytest.skip("Exorcise absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(p) is True, (
        "Exorcise must auto-join the spell-card-bridge admit set now "
        "that its Effect is covered+bridged + round-trips"
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


def test_exorcise_class_covered():
    """``ExorciseEffect`` must be in the covered-by-rust set — the
    Rust ``Effect::ExorciseEffect`` variant declaration makes
    ``covered_python_class_set()`` include it. Without this, the §2
    admit-gate teeth refuse to flip the card."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "ExorciseEffect" in covered, (
        "Rust Effect::ExorciseEffect variant must make the Python "
        "ExorciseEffect class covered"
    )


# -------------------------------------------------------------------
# Rust resolve-arm pins (synthetic state — drives each leg of the
# 3-way OR + the fizzle + the indestructible-exile case + the
# effective-power-via-counters case).
# -------------------------------------------------------------------


def _build_rust_exorcise_state(
    *,
    artifact_target: bool = False,
    enchantment_target: bool = False,
    power_4_creature_target: bool = False,
    low_power_creature_decoy: bool = False,
    indestructible: bool = False,
    counter_pumped_creature: bool = False,
):
    """Build a Rust state with an Exorcise spell on p0's stack
    targeting the seeded permanent (when present). Returns
    ``(rs, target_id_or_None)``.

    Exactly one of ``artifact_target`` / ``enchantment_target`` /
    ``power_4_creature_target`` / ``counter_pumped_creature`` should
    be True for the happy-path probes; ``low_power_creature_decoy``
    adds a creature whose printed AND effective power is < 4 (to
    pin the fizzle leg). ``indestructible`` flips the seeded target
    to indestructible (to pin the exile-bypasses-indestructible
    leg)."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    ZB = 2
    target_id = None
    if artifact_target:
        printing = {
            "name": "Exo Target Artifact",
            "card_types": ["Artifact"],
        }
        if indestructible:
            printing["keywords"] = ["indestructible"]
        target_id = rs.register_and_inject_object(printing, 1, ZB)
    elif enchantment_target:
        printing = {
            "name": "Exo Target Enchantment",
            "card_types": ["Enchantment"],
        }
        if indestructible:
            printing["keywords"] = ["indestructible"]
        target_id = rs.register_and_inject_object(printing, 1, ZB)
    elif power_4_creature_target:
        printing = {
            "name": "Exo 4-Power Creature",
            "card_types": ["Creature"],
            "power": 4,
            "toughness": 4,
        }
        if indestructible:
            printing["keywords"] = ["indestructible"]
        target_id = rs.register_and_inject_object(printing, 1, ZB)
    elif counter_pumped_creature:
        # Effective-power-via-counters leg: a 3/3 creature with a
        # +1/+1 counter (effective power 4) MUST be targetable.
        # Without `obj.counters` folding in, the printed-base-only
        # read would return 3 and silently fizzle.
        printing = {
            "name": "Exo Counter-Pumped 3/3",
            "card_types": ["Creature"],
            "power": 3,
            "toughness": 3,
        }
        target_id = rs.register_and_inject_object(printing, 1, ZB)
        rs.add_counters(target_id, 1)
    if low_power_creature_decoy:
        # A 3/3 creature that must NOT be picked (it fails the 3-way
        # OR filter — it is a Creature with effective power 3 < 4,
        # and it is not an Artifact or Enchantment). ETB-seated AFTER
        # the main target so even if the deterministic-first fallback
        # picks earliest-ETB, this decoy ranks LATER.
        rs.register_and_inject_object(
            {"name": "Exo Decoy 3/3",
             "card_types": ["Creature"],
             "power": 3, "toughness": 3},
            1, ZB,
        )
    spell_id = rs.register_and_inject_object(
        {"name": "Exorcise", "card_types": ["Sorcery"],
         "effects": [{"kind": "exorcise_effect"}]},
        0, 0,
    )
    rs.push_to_stack(spell_id, 0)
    return rs, target_id


def test_rust_exorcise_exiles_artifact():
    """Rust pin (a): artifact-leg of the 3-way OR — vanilla Artifact
    on p1's bf → exiled → in p1's exile zone. Mirrors Python
    ``ExorciseEffect.resolve``'s artifact branch."""
    rs, target = _build_rust_exorcise_state(artifact_target=True)
    assert rs.stack_size() == 1
    rs.resolve_top_of_stack()
    assert not any(
        e["id"] == target for e in rs.battlefield_snapshot()
    ), "artifact target must leave the battlefield (exiled)"
    assert any(
        e["id"] == target for e in rs.exile_snapshot(1)
    ), "exiled artifact must land in its controller's exile zone"


def test_rust_exorcise_exiles_enchantment():
    """Rust pin (b): enchantment-leg of the 3-way OR — vanilla
    Enchantment on p1's bf → exiled → in p1's exile zone.
    Distinguishes Exorcise from the sibling
    ``ExileTargetCreature`` / ``ExileTarget`` arms (neither admits
    a pure Enchantment)."""
    rs, target = _build_rust_exorcise_state(
        enchantment_target=True,
    )
    rs.resolve_top_of_stack()
    assert not any(
        e["id"] == target for e in rs.battlefield_snapshot()
    ), "enchantment target must leave the battlefield"
    assert any(
        e["id"] == target for e in rs.exile_snapshot(1)
    ), "exiled enchantment must land in its controller's exile zone"


def test_rust_exorcise_exiles_4_power_creature():
    """Rust pin (c): power-4-creature-leg of the 3-way OR — a 4/4
    on p1's bf → exiled → in p1's exile zone. The power-4 leg reads
    EFFECTIVE power via ``read_doubling_power`` (folds printed +
    UEOT + counters — matches Python's ``effective_power``)."""
    rs, target = _build_rust_exorcise_state(
        power_4_creature_target=True,
    )
    rs.resolve_top_of_stack()
    assert not any(
        e["id"] == target for e in rs.battlefield_snapshot()
    ), "4-power creature target must leave the battlefield"
    assert any(
        e["id"] == target for e in rs.exile_snapshot(1)
    ), "exiled 4-power creature must land in its exile zone"


def test_rust_exorcise_silent_fizzle_low_power_creature():
    """Rust pin (d): a 3/3 creature on the bf does NOT satisfy the
    3-way OR filter (it is a Creature but effective_power=3 < 4,
    and it is not an Artifact or Enchantment) — fizzle. The decoy
    must NOT be exiled even though it is the only permanent on the
    bf."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    ZB = 2
    decoy = rs.register_and_inject_object(
        {"name": "Exo Decoy 3/3", "card_types": ["Creature"],
         "power": 3, "toughness": 3},
        1, ZB,
    )
    spell_id = rs.register_and_inject_object(
        {"name": "Exorcise", "card_types": ["Sorcery"],
         "effects": [{"kind": "exorcise_effect"}]},
        0, 0,
    )
    rs.push_to_stack(spell_id, 0)
    rs.resolve_top_of_stack()
    assert rs.stack_size() == 0, "spell must resolve (fizzling)"
    assert any(
        e["id"] == decoy for e in rs.battlefield_snapshot()
    ), (
        "3/3 creature must NOT be exiled (fails the 3-way OR filter "
        "— it is a Creature with effective power 3 < 4, and it is "
        "neither Artifact nor Enchantment)"
    )


def test_rust_exorcise_exiles_indestructible_artifact():
    """Rust pin (e): an indestructible artifact gets EXILED (CR
    702.12 — exile bypasses indestructible). Distinguishes Exorcise
    from the destroy siblings (Shattered Wings,
    DestroyTargetArtifact, etc.) which DO skip indestructible. The
    resolve arm has no indestructible-skip; the
    ``state_ops_legal.rs::spell_targets_satisfiable`` arm also has
    no indestructible-skip, mirroring the established
    ``Effect::ExileTarget { AnyCreature }`` precedent."""
    rs, target = _build_rust_exorcise_state(
        artifact_target=True, indestructible=True,
    )
    rs.resolve_top_of_stack()
    assert not any(
        e["id"] == target for e in rs.battlefield_snapshot()
    ), (
        "indestructible artifact MUST be exiled (exile bypasses "
        "indestructible per CR 702.12) — distinguishes Exorcise from "
        "destroy siblings that skip indestructible"
    )
    assert any(
        e["id"] == target for e in rs.exile_snapshot(1)
    ), "exiled indestructible artifact must land in its exile zone"


def test_rust_exorcise_effective_power_via_counters():
    """Rust pin (f): a 3/3 creature carrying a +1/+1 counter
    (effective power 4) is legally targetable AND gets exiled —
    matching Python's ``effective_power(state, obj)`` =
    ``_compute_effective_pt`` at game.py:2138-2251 which folds the
    signed net +1/+1 counter into the power read.

    Distinguishes the EFFECTIVE-power read (folds counters) from a
    PRINTED-base-only read (would see 3, fizzle). Mirrors the
    round-53 Mightform fix's effective-vs-printed distinction."""
    rs, target = _build_rust_exorcise_state(
        counter_pumped_creature=True,
    )
    rs.resolve_top_of_stack()
    assert not any(
        e["id"] == target for e in rs.battlefield_snapshot()
    ), (
        "counter-pumped 3/3 (effective_power=4) must be exiled — "
        "the power-4 leg reads EFFECTIVE power, not printed base"
    )
    assert any(
        e["id"] == target for e in rs.exile_snapshot(1)
    ), "exiled counter-pumped creature must land in its exile zone"


# -------------------------------------------------------------------
# Genuine real-printing cross-engine byte-equal probe.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_exorcise_parity(
):
    """**GENUINE real-printing cross-engine probe — Exorcise.
    Effect-uncovered single-gated tier; PROBED-tier flip.**

    Drives the **ACTUAL parsed Exorcise printing** on the Python
    side: ``get_active_source().get_printings()["Exorcise"]`` —
    which the live parser maps to a ``spell_effect`` of
    ``ExorciseEffect()`` (verified above).

    Oracle (verbatim, ``data/duskmourn.json``):

        "[Sorcery] {1}{W} — Exile target artifact, enchantment, or
         creature with power 4 or greater."

    **Honest split (§2).** The Effect closes byte-equal AND the
    full Sorcery auto-joins the spell-card-bridge admit set (pinned
    in ``test_exorcise_passes_bridge_admit_gate``).

    **Deterministic, no RNG. Empty libraries on both engines** so
    no library reads happen during resolve.

    p0 has the genuine Exorcise; p1 has a 5/5 creature (the
    creature-leg target — the only permanent on the bf matching
    the 3-way OR filter, so deterministic-first on both engines).
    The WHOLE field view is asserted byte-equal post-resolve."""
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
    from mtg_bot.effects.bespoke import ExorciseEffect
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = get_active_source().get_printings().get("Exorcise")
    if real is None:
        pytest.skip("Exorcise absent from active CardSource")
    assert "Sorcery" in real.card_types
    assert isinstance(real.spell_effect, ExorciseEffect)

    def _exo_creature(name, power, toughness):
        return CardPrinting(
            name=name, mana_cost_str="", mana_cost=ManaCost(generic=0),
            type_line="Creature", supertypes=(),
            card_types=("Creature",), subtypes=(),
            power=power, toughness=toughness, produces=frozenset(),
            keywords=(),
        )

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # p1 opponent 5/5 vanilla — the power-4+-creature-leg target
    # (only permanent on either bf matching the 3-way OR filter, so
    # deterministic-first pick on both engines).
    py_target = py.new_object(
        _exo_creature("Exo Real 5/5", 5, 5), owner_id=1,
        zone=Zone.BATTLEFIELD,
    )
    py_target.summoning_sick = False
    py.battlefield.append(py_target)
    rs_target = rs.register_and_inject_object(
        {"name": "Exo Real 5/5", "card_types": ["Creature"],
         "power": 5, "toughness": 5},
        1, ZB,
    )

    # Cast the genuine Exorcise on the 5/5 (Python: real
    # spell_effect on a StackItem targeting the creature; Rust: the
    # bridged synthetic Sorcery — the resolve arm's None-payload
    # fallback picks the only matching permanent on the bf, which
    # IS the 5/5 here, so the deterministic-first observable is
    # byte-equal with Python's explicit cast-time target bind).
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("permanent", py_target.id),))
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    rs_spell = rs.register_and_inject_object(
        {"name": "Exorcise", "card_types": ["Sorcery"],
         "effects": [{"kind": "exorcise_effect"}]},
        0, 0,
    )
    rs.push_to_stack(rs_spell, 0)
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # FULL byte-equal compare. The 5/5 is exiled by the 3-way OR's
    # power-4+ creature leg → moved to p1's exile byte-equal on BOTH
    # engines.
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Exorcise post-resolve must be byte-equal across the WHOLE "
        f"field view on BOTH engines (3-way OR filter + power-4 "
        f"creature leg + exile); diffs={diffs}"
    )
    # Observable cross-checks (defense-in-depth on top of the full
    # field byte-equality).
    assert not [o for o in py.battlefield if o.id == py_target.id], (
        "Python: 5/5 exiled by the 3-way OR's power-4 leg"
    )
    assert not any(
        e["id"] == rs_target for e in rs.battlefield_snapshot()
    ), "Rust: 5/5 exiled by the 3-way OR's power-4 leg (byte-equal)"
    assert any(
        o.id == py_target.id for o in py.players[1].exile
    ), "Python: exiled 5/5 in p1's exile"
    assert any(
        e["id"] == rs_target for e in rs.exile_snapshot(1)
    ), "Rust: exiled 5/5 in p1's exile (byte-equal)"
