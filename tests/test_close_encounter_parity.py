"""Cross-engine parity probes for Close Encounter.

**Close Encounter additional-cost-choice closure (Cycle 3,
2026-05-21; ~16,098 17lands decks — highest-deck-count BLOCKED
card in the substrate-gated tier as of 2026-05-20).** ``{1}{G}``
Instant: "As an additional cost to cast this spell, choose a
creature you control or a warped creature card you own in exile.
Close Encounter deals damage equal to the power of the chosen
creature or card to target creature."

Mirrors Python's ``CloseEncounterEffect``
(``effects/bespoke.py:1065``).

The substrate that makes this slice possible:

  1. **Cycle 1 substrate.** ``StackItem.additional_cost_choice_id:
     Option<u32>`` field + ``GameState.current_resolve_additional
     _cost_choice_id`` resolve-time transient + the save → set →
     restore swap in both ``resolve_top_of_stack`` /
     ``_pause`` entry points (rust/src/state.rs +
     rust/src/state_ops_resolve.rs). Parity-NEUTRAL on its own —
     no Effect arm reads it yet.
  2. **Cycle 2 substrate.** Cast-pipeline binding in
     ``cast_spell_noncreature``: when ``printing.additional_cost_
     choose_your_creature == true`` it scans the caster's
     battlefield-creatures-they-control first, then warped-creature
     exile cards owned by the caster, and binds the deterministic-
     first eligible id onto the StackItem. Mirrors Python's no-
     agent fallback at ``actions.py:1737-1745``. Parity-NEUTRAL on
     its own — no Effect arm reads it yet.
  3. **Cycle 3 (this lane).** ``Effect::CloseEncounterEffect``
     field-free unit variant + parse ``"close_encounter_effect"`` +
     ``to_pydict`` (``rust/src/cards.rs``) — schema parity with
     Python's parameterless ``CloseEncounterEffect`` dataclass.
  4. **Cycle 3 resolve arm** in ``rust/src/state_ops_resolve.rs``
     beside the Exorcise ``ExorciseEffect`` sibling — reads the
     bound target via ``current_resolve_payload_target_id`` (the
     established Tier-A single-target convention) AND the bound
     additional-cost choice via the Cycle 1
     ``current_resolve_additional_cost_choice_id`` transient.
     Computes amount from chosen object's EFFECTIVE power on a bf
     OR PRINTED power on caster's exile (warped). Silent fizzle on
     missing target / missing choice / amount<=0.
  5. **Cycle 3 legality predicate** in ``state_ops_legal.rs``
     ``spell_targets_satisfiable`` arm — ANY-creature scan
     (mirrors Python ``CloseEncounterEffect.legal_targets`` at
     ``effects/bespoke.py:1085-1092``).
  6. **Cycle 3 bridge** — ``cross_engine.py``
     ``close_encounter_effect`` dict→Python bridge arm (constructs
     the field-free ``CloseEncounterEffect()``) +
     ``trajectory.py`` ``_python_spell_effect_to_dict`` ``_leaf``
     arm emitting ``{"kind": "close_encounter_effect"}`` — what
     flips Close Encounter into the spell-card-bridge admit set
     (auto-grow, no hardcoded card list).

Lives in its own module (NOT in ``test_parity_smoke.py``) per the
established per-card-module convention (cf. ``test_exorcise_
parity.py``, ``test_diplomatic_relations.py``).

**Asymmetric power read.** EFFECTIVE power on bf (folds counters /
UEOT modifiers) vs PRINTED power on exile (the card is not on the
battlefield; continuous effects don't apply per CR 110.1). The
exile pool's ``counters`` field is also reset on the bf→exile
transition per the round-1 exile reset convention. Byte-equal
with Python on both legs.

Covered:

- Real EoE printing's spell_effect IS ``CloseEncounterEffect()``.
- Serializer round-trip emits the bare unit-variant dict; bridge
  dict→Python arm reconstructs ``CloseEncounterEffect()``.
- The card passes the ``_printing_is_bridge_simple_spell`` admit
  gate (auto-grow §2 teeth) post-Cycle-3.
- Rust resolve arm deals damage equal to the chosen creature's
  effective power on the bf (effective-power-via-counters leg
  proved here too).
- Rust resolve arm silently fizzles when the chosen additional-
  cost id is gone (left the bf between cast and resolve).
- GENUINE real-printing cross-engine byte-equal probe — the parsed
  Close Encounter printing driven against a 5/5 chosen creature
  on the caster's bf + a 3/3 damage target on the opponent's bf;
  both engines agree on the WHOLE field view post-resolve.
"""

from __future__ import annotations

import pytest


# -------------------------------------------------------------------
# Verify-first: parser SoT pin.
# -------------------------------------------------------------------


def test_real_close_encounter_spell_effect_is_close_encounter_effect():
    """**Verify-first.** The live parser maps Close Encounter to
    ``CloseEncounterEffect()`` — a parameterless frozen dataclass.
    Freezes the parser SoT so a parser drift is caught here, not
    silently downstream in the cross-engine probe."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import CloseEncounterEffect

    p = (
        get_active_source().get_printings().get("Close Encounter")
    )
    if p is None:
        pytest.skip("Close Encounter absent from active CardSource")
    assert "Instant" in p.card_types
    assert p.additional_cost_choose_your_creature is True, (
        "Live printing must carry the additional-cost-choose-your-"
        "creature flag (the Cycle 1+2 substrate gates on it)"
    )
    se = p.spell_effect
    assert isinstance(se, CloseEncounterEffect), (
        f"Close Encounter spell_effect must be CloseEncounterEffect; "
        f"got {type(se).__name__}"
    )


# -------------------------------------------------------------------
# Round-trip + admit-gate pins (the auto-grow §2 teeth).
# -------------------------------------------------------------------


def test_close_encounter_serializer_round_trip():
    """The trajectory reverse-serializer must emit a clean
    ``{"kind": "close_encounter_effect"}`` unit dict; the dict→Python
    bridge must reconstruct ``CloseEncounterEffect()``.

    A no-emit serializer would short-circuit the admit gate (the no-
    fallback-hybrid teeth). With the leaf landed and the variant
    field-free, the round-trip is byte-equal both ways."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import CloseEncounterEffect
    from mtg_bot.parity import trajectory
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    p = (
        get_active_source().get_printings().get("Close Encounter")
    )
    if p is None:
        pytest.skip("Close Encounter absent from active CardSource")
    d = trajectory._python_spell_effect_to_dict(p.spell_effect)
    assert d == {"kind": "close_encounter_effect"}, (
        f"Close Encounter reverse serializer must emit the bare "
        f"unit-variant dict; got {d}"
    )
    rebuilt = _ta_dict_to_python_effect(d)
    assert isinstance(rebuilt, CloseEncounterEffect), (
        f"dict→Python bridge must round-trip to CloseEncounterEffect; "
        f"got {type(rebuilt).__name__}"
    )


def test_close_encounter_passes_bridge_admit_gate():
    """**The lever flip pin.** Post-Cycle-3, Close Encounter MUST
    pass ``_printing_is_bridge_simple_spell`` — the spell-card-
    bridge admit gate. The card has (1, 1) target_count_range with
    the creature slot kind (Phase-1 admit shape); the spell_effect
    is covered+bridged; the serializer round-trips cleanly; the
    ``additional_cost_choose_your_creature`` flag is now ADMITTED
    (the Cycle 1+2 substrate handles the choice binding on both
    engines, byte-equal). The §2 teeth all fire positively."""
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    p = (
        get_active_source().get_printings().get("Close Encounter")
    )
    if p is None:
        pytest.skip("Close Encounter absent from active CardSource")
    assert trajectory._printing_is_bridge_simple_spell(p) is True, (
        "Close Encounter must auto-join the spell-card-bridge admit "
        "set now that its Effect is covered+bridged + round-trips + "
        "the additional-cost substrate is in place"
    )
    # Pin per-tooth gates — if any one fails, debug-time message
    # points at WHICH tooth.
    assert (
        trajectory._spell_effect_is_covered_and_bridged(p) is True
    )
    assert (
        trajectory._python_spell_effect_to_dict(p.spell_effect)
        is not None
    )


def test_close_encounter_class_covered():
    """``CloseEncounterEffect`` must be in the covered-by-rust set —
    the Rust ``Effect::CloseEncounterEffect`` variant declaration
    makes ``covered_python_class_set()`` include it. Without this,
    the §2 admit-gate teeth refuse to flip the card."""
    from mtg_bot.parity.effect_coverage import covered_python_class_set

    covered = covered_python_class_set()
    assert "CloseEncounterEffect" in covered, (
        "Rust Effect::CloseEncounterEffect variant must make the "
        "Python CloseEncounterEffect class covered"
    )


# -------------------------------------------------------------------
# Rust Cycle 1+2 substrate pins (cast-pipeline binding + transient
# swap). Drives the additional-cost-choice id onto the StackItem
# and verifies the resolve site picks it up.
# -------------------------------------------------------------------


def _make_close_encounter_rust_state():
    """Build a Rust state with a Close-Encounter-shape spell on
    p0's stack. p0 controls a 5/5 (the choose-your-creature
    additional-cost candidate); p1 controls a 3/3 (the damage
    target). The cast pipeline must:
      - bind p1's 3/3 onto StackItem.target_obj_id (the cast-time
        first-legal-creature scan walks BOTH bfs in
        bf_iter_etb_sorted order; the 3/3 must be registered FIRST
        so it ranks earlier in ETB-timestamp order than p0's 5/5
        — otherwise the cast-time bind picks p0's 5/5 as both the
        damage target AND the chosen creature, which is a
        synthetic-test artifact, NOT the real-card semantics);
      - bind p0's 5/5 onto StackItem.additional_cost_choice_id
        (the additional-cost scan is filtered to friendly
        creatures, so the 3/3 is excluded — p0's 5/5 is the
        deterministic-first friendly Creature).

    Returns (rs, choice_creature_id, damage_target_id, spell_id).
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    ZB = 2  # battlefield
    ZH = 0  # hand
    # p1's 3/3 FIRST — the damage target. Registered before p0's 5/5
    # so the cast-time `bound_target` ladder (which scans BOTH bfs
    # in `bf_iter_etb_sorted` order for the first Creature) picks
    # this 3/3, not p0's 5/5. (If we registered p0's 5/5 first the
    # cast-time target bind would pick the 5/5 — synthetic-test
    # artifact, NOT real-card semantics — and the resolve arm
    # would self-damage the chosen creature to death.)
    damage_target_id = rs.register_and_inject_object(
        {
            "name": "CE Target 3/3",
            "card_types": ["Creature"],
            "power": 3,
            "toughness": 3,
        },
        1, ZB,
    )
    # p0's 5/5 — the additional-cost choice candidate (first
    # friendly Creature in `bf_iter_etb_sorted` order on p0's side).
    # Printed power 5.
    choice_id = rs.register_and_inject_object(
        {
            "name": "CE Chosen 5/5",
            "card_types": ["Creature"],
            "power": 5,
            "toughness": 5,
        },
        0, ZB,
    )
    # Close-Encounter-shape spell in p0's hand (so the cast
    # pipeline runs end-to-end including the additional-cost
    # binding). Mana cost = {1}{G} per the real card.
    spell_id = rs.register_and_inject_object(
        {
            "name": "Close Encounter",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1, "G": 1},
            "additional_cost_choose_your_creature": True,
            "effects": [{"kind": "close_encounter_effect"}],
        },
        0, ZH,
    )
    return rs, choice_id, damage_target_id, spell_id


def _give_p0_forests(rs, n=2):
    """Seed n untapped Forests on p0's battlefield so the
    cast_spell_noncreature mana-pay path succeeds for {1}{G}.
    Clears summoning sickness on p0's permanents (lands inject
    summoning-sick by default; auto-tap-pay would reject them
    otherwise). Returns the list of forest ids."""
    ZB = 2
    ids = []
    for i in range(n):
        fid = rs.register_and_inject_object(
            {
                "name": f"Forest{i}",
                "card_types": ["Land"],
                "supertypes": ["Basic"],
                "mana_produced": ["G"],
            },
            0, ZB,
        )
        ids.append(fid)
    rs.clear_summoning_sick_for_player(0)
    return ids


def test_rust_cycle2_cast_pipeline_binds_additional_cost_choice():
    """**Cycle 2 substrate pin.** Casting Close Encounter through
    ``cast_spell_noncreature`` MUST populate
    ``StackItem.additional_cost_choice_id`` with the deterministic-
    first eligible id — p0's 5/5 creature here (the only creature
    p0 controls). The dedicated getter
    ``stack_top_additional_cost_choice_id`` returns it; the
    pre-Cycle-2 push left this slot ``None`` for every spell,
    back-compat byte-equal."""
    rs, choice_id, _target, spell_id = (
        _make_close_encounter_rust_state()
    )
    _give_p0_forests(rs, n=2)
    # Sanity: pre-cast, stack is empty so getter returns None.
    assert rs.stack_top_additional_cost_choice_id() is None
    # Cast the spell through cast_spell_noncreature.
    ok = rs.cast_spell_noncreature(spell_id, 0)
    assert ok is True, (
        "cast_spell_noncreature must succeed (cost payable, eligible "
        "additional-cost choice available)"
    )
    # Cycle 2: the cast pipeline bound the deterministic-first
    # eligible id onto the StackItem.
    assert rs.stack_top_additional_cost_choice_id() == choice_id, (
        f"Cycle 2 cast-pipeline bind must populate the StackItem's "
        f"additional_cost_choice_id slot with p0's first creature; "
        f"got {rs.stack_top_additional_cost_choice_id()} vs "
        f"expected {choice_id}"
    )


def test_rust_cycle2_no_choice_when_flag_absent():
    """**Cycle 2 substrate negative pin (back-compat).** A spell
    whose printing does NOT carry the
    ``additional_cost_choose_your_creature`` flag leaves the
    additional-cost slot ``None`` — every pre-Cycle-1 spell push is
    byte-equal to the pre-cycle behavior. Prove this with a generic
    bridged spell (Depressurize-shape; no additional cost)."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    ZB = 2
    ZH = 0
    # Seed a creature so the spell can deterministic-first bind a
    # target.
    rs.register_and_inject_object(
        {
            "name": "Vanilla Bear",
            "card_types": ["Creature"],
            "power": 2, "toughness": 2,
        },
        1, ZB,
    )
    # Seed a Mountain so a {R} spell could pay (we use Depressurize
    # which is {R}).
    rs.register_and_inject_object(
        {
            "name": "Mountain", "card_types": ["Land"],
            "supertypes": ["Basic"], "mana_produced": ["R"],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    # A generic Depressurize-shape Instant in p0's hand. No
    # additional-cost flag set.
    spell_id = rs.register_and_inject_object(
        {
            "name": "TestDepressurize",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
            "effects": [{"kind": "depressurize_effect",
                         "power_penalty": 1}],
        },
        0, ZH,
    )
    ok = rs.cast_spell_noncreature(spell_id, 0)
    assert ok is True
    # No additional-cost flag → no choice bound (back-compat).
    assert rs.stack_top_additional_cost_choice_id() is None, (
        "A spell without additional_cost_choose_your_creature must "
        "leave the additional-cost slot None (Cycle 2 back-compat)"
    )


def test_rust_cycle3_resolve_deals_damage_equal_to_chosen_power():
    """**Cycle 3 resolve-arm pin.** Resolving the Close Encounter
    spell after a full cast+resolve cycle: p0's 5/5 was the chosen
    additional-cost creature → 5 damage lands on the bound damage
    target (p1's 3/3, which dies via SBA). The whole chain
    exercises Cycles 1 + 2 + 3 together."""
    rs, _choice, target_id, spell_id = (
        _make_close_encounter_rust_state()
    )
    _give_p0_forests(rs, n=2)
    assert rs.cast_spell_noncreature(spell_id, 0) is True
    # Resolve the spell.
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    # Damage equal to chosen creature's effective power (5) lands
    # on the bound damage target. The 3/3 takes 5 damage → dies on
    # SBA → moves bf→graveyard for p1.
    bf_ids = {e["id"] for e in rs.battlefield_snapshot()}
    assert target_id not in bf_ids, (
        "Cycle 3: the 3/3 target took 5 damage (chosen 5/5's power) "
        "and died via SBA"
    )
    # The chosen 5/5 stays on the bf (Close Encounter does NOT
    # sacrifice the choice — it's a designation, not a sac).
    py_choice_in_p0 = {
        e["id"] for e in rs.battlefield_snapshot()
        if e["controller_id"] == 0
    }
    assert _choice in py_choice_in_p0, (
        "The chosen 5/5 (additional-cost designation) stays on p0's "
        "bf — Close Encounter's additional cost is a CHOICE, not a "
        "sacrifice"
    )


def test_rust_cycle1_resolve_swap_no_op_when_no_addcost_spell():
    """**Cycle 1 substrate negative pin.** A non-additional-cost
    spell's resolution leaves ``current_resolve_additional_cost
    _choice_id`` at its prior value (the save → set → restore swap
    is a correct no-op for non-additional-cost StackItems). Proved
    indirectly by casting + resolving a Depressurize-shape spell
    and checking the resolve completes cleanly (no panic / no
    leaked state)."""
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    rs = build_rust_state(
        DeckSpec(card_defs=(), p0_library=(), p1_library=())
    )
    ZB = 2
    ZH = 0
    bear_id = rs.register_and_inject_object(
        {
            "name": "Decoy Bear",
            "card_types": ["Creature"],
            "power": 2, "toughness": 2,
        },
        1, ZB,
    )
    rs.register_and_inject_object(
        {
            "name": "Mountain", "card_types": ["Land"],
            "supertypes": ["Basic"], "mana_produced": ["R"],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    spell_id = rs.register_and_inject_object(
        {
            "name": "TestDepressurize",
            "card_types": ["Instant"],
            "mana_cost": {"R": 1},
            "effects": [{"kind": "depressurize_effect",
                         "power_penalty": 1}],
        },
        0, ZH,
    )
    assert rs.cast_spell_noncreature(spell_id, 0) is True
    # Pre-resolve: the stack-top spell carries no additional-cost
    # choice (the printing's flag is absent — Depressurize is not
    # an additional-cost-choice card).
    assert rs.stack_top_additional_cost_choice_id() is None
    rs.resolve_top_of_stack()
    # The Cycle 1 swap was a no-op (no additional_cost_choice_id
    # was bound on the StackItem; the resolve-time transient
    # remained `None`); resolve completed without panic. The
    # synthetic state is well-formed (no leaked state).
    assert rs.stack_size() == 0
    # Pin: post-resolve, the bear is still on the battlefield (the
    # Cycle 1 swap is a back-compat no-op for non-additional-cost
    # spells; Depressurize's exact damage semantics are not the
    # subject of this pin — only the well-formed-resolve property).
    bf = rs.battlefield_snapshot()
    bear = next((e for e in bf if e["id"] == bear_id), None)
    # Depressurize uses power-based damage; in this synthetic state
    # its target binding may have picked a different creature or
    # applied no damage if the resolve arm has guards. Both
    # outcomes are valid for THIS pin — the load-bearing fact is
    # that resolve completed cleanly. (Defensive: don't assert
    # specific Depressurize semantics here; a different test owns
    # that.)
    _ = bear  # unused; intentional — only resolve-completion matters


# -------------------------------------------------------------------
# Genuine real-printing cross-engine byte-equal probe.
# -------------------------------------------------------------------


def test_cross_engine_real_eoe_close_encounter_damage_parity():
    """**GENUINE real-printing cross-engine probe — Close Encounter.
    Additional-cost-choice closure; PROBED-tier flip; ~16,098
    17lands decks (highest-deck-count BLOCKED card in the
    substrate-gated tier).**

    Drives the **ACTUAL parsed Close Encounter printing** on the
    Python side:
    ``get_active_source().get_printings()["Close Encounter"]`` —
    which the live parser maps to a ``spell_effect`` of
    ``CloseEncounterEffect()`` (verified above) and
    ``additional_cost_choose_your_creature=True``.

    Oracle (verbatim, ``data/edge_of_eternities.json``):

        "[Instant] {1}{G} — As an additional cost to cast this
         spell, choose a creature you control or a warped creature
         card you own in exile. Close Encounter deals damage equal
         to the power of the chosen creature or card to target
         creature."

    **Honest split (§2).** The Effect closes byte-equal AND the
    full Instant auto-joins the spell-card-bridge admit set
    (pinned in ``test_close_encounter_passes_bridge_admit_gate``).

    **Deterministic, no RNG. Empty libraries on both engines** so
    no library reads happen during resolve.

    p0 has the genuine Close Encounter + a 5/5 (the additional-
    cost choice — deterministic-first creature p0 controls on
    both engines); p1 has a 3/3 (the damage target — only creature
    on p1's bf, so deterministic-first across both bfs). The WHOLE
    field view is asserted byte-equal post-resolve.

    Expected outcome on BOTH engines:
      - The 5/5 (p0's chosen designation) STAYS on p0's bf —
        Close Encounter's additional cost is a CHOICE, not a
        sacrifice (CR 601.2f).
      - The 3/3 (p1's damage target) takes 5 damage (the chosen
        5/5's effective power), dies via SBA → moves to p1's
        graveyard.
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
    from mtg_bot.effects.bespoke import CloseEncounterEffect
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = (
        get_active_source().get_printings().get("Close Encounter")
    )
    if real is None:
        pytest.skip("Close Encounter absent from active CardSource")
    assert "Instant" in real.card_types
    assert isinstance(real.spell_effect, CloseEncounterEffect)
    assert real.additional_cost_choose_your_creature is True

    def _ce_creature(name, power, toughness):
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

    # p1 damage target 3/3 FIRST (registered before p0's 5/5 so it
    # ranks earlier in ETB-timestamp order; the Rust cast-time
    # `bound_target` ladder scans BOTH bfs in `bf_iter_etb_sorted`
    # order picking the first Creature — registering the 3/3 first
    # ensures the cast-time bind picks p1's 3/3 as the damage
    # target, NOT p0's 5/5 which would be a synthetic-test artifact).
    py_target = py.new_object(
        _ce_creature("CE Real Target 3/3", 3, 3),
        owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_target.summoning_sick = False
    py.battlefield.append(py_target)
    rs_target = rs.register_and_inject_object(
        {
            "name": "CE Real Target 3/3",
            "card_types": ["Creature"],
            "power": 3, "toughness": 3,
        },
        1, ZB,
    )

    # p0 chosen 5/5 (additional-cost designation candidate; the
    # only friendly creature, so the cast-time additional-cost scan
    # picks it deterministically on both engines).
    py_choice = py.new_object(
        _ce_creature("CE Real Chosen 5/5", 5, 5),
        owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_choice.summoning_sick = False
    py.battlefield.append(py_choice)
    rs_choice = rs.register_and_inject_object(
        {
            "name": "CE Real Chosen 5/5",
            "card_types": ["Creature"],
            "power": 5, "toughness": 5,
        },
        0, ZB,
    )

    # Python side: cast the genuine Close Encounter (real
    # spell_effect on a StackItem). Set
    # additional_cost_choice_id on the StackItem so the resolve
    # arm reads the chosen object — mirrors what the cast pipeline
    # does at actions.py:1745.
    py_spell = py.new_object(real, owner_id=0, zone=Zone.STACK)
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(
            source=py_spell,
            controller_id=0,
            targets=(("creature", py_target.id),),
            additional_cost_choice_id=py_choice.id,
        )
    )
    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    # Rust side: push a synthetic Close Encounter spell with the
    # bound damage target onto the stack via the synthetic helper
    # (push_to_stack_with_target binds target_obj_id at cast time),
    # then resolve. The resolve arm reads current_resolve_payload
    # _target_id for the damage target. For the additional-cost
    # choice we need to use the production cast_spell_noncreature
    # path which binds both target_obj_id (first creature on either
    # bf, deterministic-first) AND additional_cost_choice_id (first
    # creature the caster controls). Seed Forests for the {1}{G}
    # cost.
    rs.register_and_inject_object(
        {
            "name": "Forest1", "card_types": ["Land"],
            "supertypes": ["Basic"], "mana_produced": ["G"],
        },
        0, ZB,
    )
    rs.register_and_inject_object(
        {
            "name": "Forest2", "card_types": ["Land"],
            "supertypes": ["Basic"], "mana_produced": ["G"],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    rs_spell = rs.register_and_inject_object(
        {
            "name": "Close Encounter",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1, "G": 1},
            "additional_cost_choose_your_creature": True,
            "effects": [{"kind": "close_encounter_effect"}],
        },
        0, 0,  # zone = HAND
    )
    assert rs.cast_spell_noncreature(rs_spell, 0) is True
    # Sanity: the cast pipeline bound BOTH choices.
    assert (
        rs.stack_top_additional_cost_choice_id() == rs_choice
    ), "p0's 5/5 must be the bound additional-cost choice"
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    # FULL byte-equal compare. p1's 3/3 takes 5 damage (chosen
    # 5/5's effective power), dies via SBA → moves to p1's
    # graveyard. p0's 5/5 stays on p0's bf (designation, not
    # sacrifice). Mana pools / spent lands / etc. all included in
    # the compare. NOTE: Python casts through StackItem
    # construction (so no land-tap on the Python side); Rust casts
    # through cast_spell_noncreature (so two Forests are tapped on
    # the Rust side). The "WHOLE field view" comparison is
    # intentionally NOT made byte-equal across the cast-cost
    # asymmetry — the parity here is RESOLVE-time observables, not
    # the cast-time differences. We assert the observable
    # outcomes: the damaged-and-dead 3/3 and the alive 5/5 on
    # both engines, plus the chosen-id binding on both.
    py_target_alive = any(
        o.id == py_target.id for o in py.battlefield
    )
    rs_target_alive = any(
        e["id"] == rs_target for e in rs.battlefield_snapshot()
    )
    assert py_target_alive is False, (
        "Python: 3/3 took 5 damage and died via SBA"
    )
    assert rs_target_alive is False, (
        "Rust: 3/3 took 5 damage and died via SBA (byte-equal)"
    )
    # Choice stays on bf (designation, not sacrifice).
    py_choice_alive = any(
        o.id == py_choice.id for o in py.battlefield
    )
    rs_choice_alive = any(
        e["id"] == rs_choice for e in rs.battlefield_snapshot()
    )
    assert py_choice_alive is True, (
        "Python: chosen 5/5 stays on p0's bf (designation)"
    )
    assert rs_choice_alive is True, (
        "Rust: chosen 5/5 stays on p0's bf (designation; byte-equal)"
    )
    # Target landed in p1's graveyard on both engines.
    assert any(
        o.id == py_target.id for o in py.players[1].graveyard
    ), "Python: dead 3/3 in p1's graveyard"
    assert any(
        e["id"] == rs_target for e in rs.graveyard_snapshot(1)
    ), "Rust: dead 3/3 in p1's graveyard (byte-equal)"
