"""Genuine real-EoE cross-engine byte-equality probes — batch III (round 19).

All three cards are in the ``covered_by_construction`` tier: every Effect
class they emit has a live Rust variant + bridge arm, but no genuine
per-card probe had pinned them.  This module upgrades them to the
``PROBED`` tier.

The three probes exercise three distinct trigger-dispatch paths:

  * ``BEGINNING_OF_END_STEP`` (Glassworks // Shattered Yard — Room
    Enchantment using ``DealDamageEachOpponent(1)`` via the end-step
    dispatch; first EoE Room probe to drive this leg)
  * ``ATTACKS`` + ``IsSelf`` (Appendage Amalgam — Enchantment Creature
    using ``Surveil(1)``; keep-on-top behavior is byte-equal with
    ``agent=None`` on both engines)
  * ``DIES`` + ``IsSelf`` (Bashful Beastie — Enchantment Creature using
    ``ManifestDread(1)``; deterministic top-card manifest + graveyard
    with ``agent=None``)

PROBE CARDS
-----------

**Probe 1 — Glassworks // Shattered Yard (EoE)**
Oracle: "[Enchantment — Room]
  (First half / second half details omitted for brevity.)
  At the beginning of your end step, deal 1 damage to each opponent."

The ``BEGINNING_OF_END_STEP`` trigger — ``Controlled(YOU) →
DealDamageEachOpponent(1)`` — is the cross-engine-clean leg for this
card.  In the 2-player probe setup (p0 = active player, p1 = opponent)
the observable is simple: p1's life total drops by 1 on BOTH engines.

Observable:
  * p1 life total: 20 → 19 on BOTH engines.

Rust triggered-ability dict::

    {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {"kind": "damage_each_opponent", "amount": 1},
    }

**Probe 2 — Appendage Amalgam (EoE)**
Oracle: "[Enchantment Creature — Horror] {1}{U} 3/2
  Whenever this creature attacks, surveil 1."

The ``ATTACKS`` trigger — ``IsSelf() → Surveil(1)`` — is the
cross-engine-clean leg.  With ``agent=None`` (the default in
``build_python_state``):

  * Python's ``Surveil.resolve`` falls into the ``if p.agent is not
    None and p.agent.choose_surveil(...)`` branch — the condition is
    False so NO card is moved to the graveyard; the top card stays in
    the library.
  * Rust's surveil arm keeps all examined cards on top (no decision
    required, no ``submit_surveil_decision`` needed).

Both engines therefore produce the SAME observable: library unchanged,
graveyard unchanged, trigger fired.

Observable:
  * Rust stack: 1 trigger pushed after ``declare_attacker`` → drained.
  * Python stack: 1 trigger pushed after ``declare_attackers`` → drained.
  * Both engines: library still has 2 seed cards, graveyard empty.

Rust triggered-ability dict::

    {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "surveil", "count": 1},
    }

**Probe 3 — Bashful Beastie (EoE)**
Oracle: "[Enchantment Creature — Horror] {4}{U}{U} 5/4
  When Bashful Beastie dies, manifest dread."

The ``DIES`` trigger — ``IsSelf() → ManifestDread(1)`` — is the
cross-engine-clean leg.  With ``agent=None`` (default in
``build_python_state``), ManifestDread is deterministic:

  * Python: ``ManifestDread.resolve`` uses the DEFAULT FALLBACK
    ``manifest_id = options[0]`` when ``p.agent is None`` — the TOP
    card of the library is manifested face-down, the second card goes
    to the graveyard.
  * Rust: ManifestDread does the same: manifests the top-indexed
    library object onto the battlefield face-down, puts the second in
    the graveyard.

Both engines produce the SAME observable: a face-down 2/2 creature on
p0's battlefield, p0's library empty, one plains card in p0's
graveyard (the non-manifested card).

Observable:
  * p0 battlefield: 1 face-down object (the manifested Plains).
  * p0 library: 0 cards (both consumed by ManifestDread).
  * p0 graveyard: Bashful Beastie + 1 Plains (the non-manifested card).

Rust triggered-ability dict::

    {
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "manifest_dread", "count": 1},
    }

HONEST EXHAUSTION NOTES (HHH-downstream + remaining targets checked)
---------------------------------------------------------------------

* **Haliya, Ascendant Cadet** — already PROBED (line 36675 of
  ``tests/test_parity_smoke.py``). No new probe needed.

* **Biotech Specialist** — already PROBED (line 37380 of
  ``tests/test_parity_smoke.py``). No new probe needed.

* **Requiem Monolith** — BLOCKED (``blocked_subsystem_gated``); the
  DEALT_DAMAGE trigger's ``IsHost`` predicate is not wired in the
  cross_engine bridge (``_ta_dict_to_python_predicate`` raises on
  ``'is_host'``). Cannot be genuinely cross-engine probed without a
  new bridge arm (out of scope).

* **Pain for All** — BLOCKED (``blocked_genuinely_missing``); a true
  new-Rust-Effect ask. Cannot probe.

* **Lightless Evangel** — in covered_by_construction with IS_SACRIFICED
  trigger, BUT the predicate is ``And(And(Subject(IsCreature|IsArtifact),
  Controlled(YOU)), Not(IsSelf))`` — the ``Not(IsSelf)`` inner and the
  ``Subject`` slot-filter are not bridgeable, so a FAITHFUL Rust
  synthetic carrier cannot be constructed. A probe with a simplified
  ``always`` predicate would diverge from the real card's predicate
  (fires on self-sacrifice in Rust but not in Python). Deferred.

* **Cryoshatter** — in covered_by_construction with DEALT_DAMAGE
  trigger, BUT its predicate is ``IsHost`` — same unbridged kind as
  Requiem Monolith above. Deferred.

* **Meltstrider Eulogist** — in covered_by_construction with DIES
  trigger, BUT the predicate is ``And(Subject(IsCreature HasCounter),
  Controlled(YOU))`` — Rust's ``parse_predicate`` has no
  ``has_counter`` predicate (explicitly noted in batch-A drop comment).
  Deferred.

COVERED-BY-CONSTRUCTION → PROBED (this module)
-----------------------------------------------
Three cards move from ``covered_by_construction`` to the ``PROBED`` tier
upon merge.  Prior PROBED count: 187 → 190 (+3).
Prior covered count: 124 → 121 (-3).
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
    """Load ``scripts/parity_smoke.py`` as a module."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location("parity_smoke", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Probe 1 — Glassworks // Shattered Yard: BEGINNING_OF_END_STEP →
#   DealDamageEachOpponent(1)
# (ControlledByYou predicate; Enchantment Room carrier)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_glassworks_end_step_deal_damage_each_opponent_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Glassworks // Shattered Yard
    (round 19, BEGINNING_OF_END_STEP / ControlledByYou, DealDamageEachOpponent(1)).**

    Drives the **real parsed Glassworks // Shattered Yard printing** on the
    Python side and a bridged synthetic Enchantment carrier on the Rust side
    through the ``BEGINNING_OF_END_STEP`` dispatch path.

    This probe pins the Shattered Yard half's "At the beginning of your end
    step, deal 1 damage to each opponent." trigger — the cross-engine-clean
    leg for this Room.  The ENTERS trigger (DealDamageToOpponentCreature on
    the Glassworks half) requires targeting and is out of scope here.

    Setup:
      * p0 has Glassworks // Shattered Yard (Enchantment) on the battlefield.
      * p1 has no permanents and no library cards.
      * Active player = p0.

    Trigger flow:
      1. Rust: ``advance_phase()`` loops to ``PHASE_END_STEP`` (10).
         Entry fires ``dispatch_event(BeginningOfEndStep,
         PLAYER_SUBJECT_OFFSET + 0)``; ``ControlledByYou`` resolves
         player_index=0; matches Glassworks' controller=0 → trigger pushed.
         Python: ``run_beginning_of_end_step_triggers(state)`` →
         ``dispatch_event(state, Event.BEGINNING_OF_END_STEP,
         player=state.active_player())``. Same ``Controlled(YOU)`` match.
      2. Both stacks have 1 item (the DealDamageEachOpponent(1) trigger).
      3. Drain: p1 loses 1 life on BOTH engines.

    Observables asserted (targeted):
      * p1 life: 20 → 19 on BOTH engines.

    Rust triggered-ability dict::

        {
            "event": "beginning_of_end_step",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {"kind": "damage_each_opponent", "amount": 1},
        }
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
        build_python_field_view,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import (
        run_beginning_of_end_step_triggers,
        state_based_actions as py_sba,
    )
    from mtg_bot.effects.predicates import Event, Controlled, YOU
    from mtg_bot.effects.generic.damage import DealDamageEachOpponent

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Glassworks // Shattered Yard printing
    #    has the expected BEGINNING_OF_END_STEP trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Glassworks // Shattered Yard")
    if real is None:
        pytest.skip("Glassworks // Shattered Yard absent from active CardSource")

    assert "Enchantment" in real.card_types, (
        "Glassworks // Shattered Yard must be an Enchantment"
    )
    end_step_ta = next(
        (
            ta
            for ta in real.triggered_abilities
            if ta.event == Event.BEGINNING_OF_END_STEP
        ),
        None,
    )
    assert end_step_ta is not None, (
        "Glassworks // Shattered Yard must have a BEGINNING_OF_END_STEP "
        "triggered ability; abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(end_step_ta.effect, DealDamageEachOpponent), (
        f"Glassworks end-step TA effect must be DealDamageEachOpponent; "
        f"got {type(end_step_ta.effect).__name__}"
    )
    assert end_step_ta.effect.amount == 1, (
        f"Glassworks end-step DealDamageEachOpponent amount must be 1; "
        f"got {end_step_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 2. Build cross-engine states (empty decks).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    ZB = 2  # ZONE_BATTLEFIELD
    PHASE_END_STEP = 10

    # ------------------------------------------------------------------
    # 3. Build the shared triggered-ability dict.
    # ------------------------------------------------------------------
    glassworks_ta_dict = {
        "event": "beginning_of_end_step",
        "predicate": {"kind": "controlled_by_you"},
        "effect": {"kind": "damage_each_opponent", "amount": 1},
    }

    # Sanity: bridge translates the dict correctly.
    bridge_ta = _ta_dict_to_python_triggered_ability(glassworks_ta_dict)
    assert bridge_ta.event == Event.BEGINNING_OF_END_STEP, (
        f"Bridge must translate 'beginning_of_end_step' to "
        f"Event.BEGINNING_OF_END_STEP; got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, Controlled), (
        f"Bridge predicate must be Controlled; "
        f"got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, DealDamageEachOpponent), (
        f"Bridge effect must be DealDamageEachOpponent; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert bridge_ta.effect.amount == 1, (
        f"Bridge DealDamageEachOpponent amount must be 1; "
        f"got {bridge_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 4. Rust: inject Glassworks carrier (pure Enchantment, no P/T)
    #    directly onto p0's battlefield.
    # ------------------------------------------------------------------
    rs_gw_id = rs.register_and_inject_object(
        {
            "name": "Glassworks // Shattered Yard",
            "card_types": ["Enchantment"],
            "effects": [],
            "triggered_abilities": [glassworks_ta_dict],
        },
        0, ZB,
    )
    assert rs.find_object_zone(rs_gw_id) == ZB, (
        "Glassworks carrier must be on Rust battlefield"
    )

    # ------------------------------------------------------------------
    # 5. Rust: advance to PHASE_END_STEP (10); drain trigger (damage p1).
    # ------------------------------------------------------------------
    for _ in range(20):
        if rs.current_phase() == PHASE_END_STEP:
            break
        rs.advance_phase()
    assert rs.current_phase() == PHASE_END_STEP, (
        f"Rust: must reach PHASE_END_STEP (10); got {rs.current_phase()}"
    )

    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 trigger (Glassworks end-step DealDamageEachOpponent) "
        f"must be on the stack at PHASE_END_STEP entry; "
        f"got {rs.stack_size()}"
    )

    rs_p1_life_before = ce_parity_smoke()._build_field_view(rs)["life_p1"]

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_p1_life_after = ce_parity_smoke()._build_field_view(rs)["life_p1"]
    assert rs_p1_life_after == rs_p1_life_before - 1, (
        f"Rust: p1 must lose exactly 1 life after DealDamageEachOpponent(1) "
        f"resolves; before={rs_p1_life_before}, after={rs_p1_life_after}"
    )

    # ------------------------------------------------------------------
    # 6. Python: inject genuine Glassworks // Shattered Yard printing
    #    (bridge TA) onto p0's battlefield.
    # ------------------------------------------------------------------
    py_gw_printing = CardPrinting(
        name="Glassworks // Shattered Yard",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Enchantment — Room",
        supertypes=(),
        card_types=("Enchantment",),
        subtypes=("Room",),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_gw = py.new_object(py_gw_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_gw.summoning_sick = False
    py_gw.tapped = False
    py_gw.damage = 0
    py_gw.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_gw)

    # ------------------------------------------------------------------
    # 7. Python: fire end-step trigger; drain (DealDamageEachOpponent resolves).
    # ------------------------------------------------------------------
    run_beginning_of_end_step_triggers(py)

    assert len(py.stack) == 1, (
        f"Python: exactly 1 trigger (Glassworks end-step DealDamageEachOpponent) "
        f"must be on the stack after run_beginning_of_end_step_triggers; "
        f"got {len(py.stack)}"
    )

    py_p1_life_before = py.players[1].life

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_p1_life_after = py.players[1].life
    assert py_p1_life_after == py_p1_life_before - 1, (
        f"Python: p1 must lose exactly 1 life after DealDamageEachOpponent(1) "
        f"resolves; before={py_p1_life_before}, after={py_p1_life_after}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_p1_life_after == py_p1_life_after, (
        f"p1 life: Rust={rs_p1_life_after}, Python={py_p1_life_after} "
        f"(must be byte-equal — DealDamageEachOpponent(1) resolved on BOTH "
        f"engines via BEGINNING_OF_END_STEP dispatch for "
        f"Glassworks // Shattered Yard)"
    )


# ---------------------------------------------------------------------------
# Probe 2 — Appendage Amalgam: ATTACKS → Surveil(1)
# (IsSelf predicate; keep-on-top behavior byte-equal with agent=None)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_appendage_amalgam_attacks_surveil_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Appendage Amalgam
    (round 19, ATTACKS / IsSelf, Surveil(1)).**

    Drives the **real parsed Appendage Amalgam printing** on the Python side
    and a bridged synthetic carrier on the Rust side through the ``ATTACKS``
    dispatch path.

    This probe pins Appendage Amalgam's "Whenever this creature attacks,
    surveil 1." trigger.

    NOTE: With ``agent=None`` (the default in ``build_python_state``),
    Surveil is fully deterministic on both engines:

      * Python: ``Surveil.resolve`` checks ``if p.agent is not None and
        p.agent.choose_surveil(...)``. When ``agent is None`` the condition
        is False and NO card is moved; the examined top card stays in the
        library unchanged. The library size is unchanged; graveyard is
        unchanged.
      * Rust: Surveil resolves non-interactively, keeping all examined
        cards on top (no ``submit_surveil_decision`` is raised; the
        graveyard snapshot is empty after resolution).

    Both engines therefore produce the SAME byte-equal observables: 1
    trigger pushed after attack, library stays at 2 seed cards, graveyard
    stays empty.

    Setup:
      * p0 has Appendage Amalgam (3/2 Enchantment Creature) on the
        battlefield (not summoning-sick).
      * p0's library has 2 Plains seed cards on both engines (mirrors the
        token-pid idiom: symmetrical seed ensures library_p0 shape is the
        same across engines during compare_fields — only the counter-tuple
        detail differs, so a targeted observable assertion is used).
      * p1 has no permanents.
      * Active player = p0.

    Trigger flow:
      1. Rust: ``declare_attacker(rs_id)`` fires ``dispatch_event(Attacks,
         rs_id)``; ``IsSelf`` matches the attacker; trigger pushed.
         Python: ``declare_attackers(py, [py_obj.id])`` → ``_fire_attacks_
         triggers`` → ``dispatch_event(state, Event.ATTACKS, obj=py_obj,
         source=py_obj)``; same ``IsSelf`` match.
      2. Both stacks have 1 item (the Surveil(1) trigger).
      3. Drain: Surveil resolves; no card moves on either engine.

    Observables asserted (targeted):
      * Stack size after attack: 1 on BOTH engines.
      * Library size after resolve: 2 on BOTH engines (no surveil mill).
      * Graveyard size after resolve: 0 on BOTH engines (no surveil mill).

    Rust triggered-ability dict::

        {
            "event": "attacks",
            "predicate": {"kind": "source_is_self"},
            "effect": {"kind": "surveil", "count": 1},
        }
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.game import Zone
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.generic.library_lookat import Surveil
    from mtg_bot import combat as py_combat

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Appendage Amalgam printing has the
    #    expected ATTACKS trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Appendage Amalgam")
    if real is None:
        pytest.skip("Appendage Amalgam absent from active CardSource")

    assert "Creature" in real.card_types, (
        "Appendage Amalgam must be a Creature"
    )
    attacks_ta = next(
        (ta for ta in real.triggered_abilities if ta.event == Event.ATTACKS),
        None,
    )
    assert attacks_ta is not None, (
        "Appendage Amalgam must have an ATTACKS triggered ability; "
        f"abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(attacks_ta.effect, Surveil), (
        f"Appendage Amalgam ATTACKS TA effect must be Surveil; "
        f"got {type(attacks_ta.effect).__name__}"
    )
    assert attacks_ta.effect.amount == 1, (
        f"Appendage Amalgam Surveil amount must be 1; "
        f"got {attacks_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 2. Build cross-engine states (empty decks) then seed each engine's
    #    p0 library with 2 Plains (provides a surveil target without
    #    moving any card — keep-on-top path).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # Python library seeds.
    plains = BASIC_LANDS["Plains"]
    for _ in range(2):
        py_seed = py.new_object(plains, owner_id=0, zone=Zone.LIBRARY)
        py_seed.summoning_sick = False
        py.players[0].library.append(py_seed)

    # Rust library seeds (inert lib objects; provide surveil target).
    for _ in range(2):
        rs.register_and_inject_object(
            {
                "name": "Plains",
                "card_types": ["Land", "Basic"],
                "supertypes": ["Basic"],
                "mana_cost": {"generic": 0},
            },
            0, 1,  # owner=0, ZONE_LIBRARY
        )

    ZB = 2  # ZONE_BATTLEFIELD

    # ------------------------------------------------------------------
    # 3. Build the shared triggered-ability dict.
    # ------------------------------------------------------------------
    aa_ta_dict = {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "surveil", "count": 1},
    }

    # Sanity: bridge translates the dict correctly.
    bridge_ta = _ta_dict_to_python_triggered_ability(aa_ta_dict)
    assert bridge_ta.event == Event.ATTACKS, (
        f"Bridge must translate 'attacks' to Event.ATTACKS; "
        f"got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, IsSelf), (
        f"Bridge predicate must be IsSelf; "
        f"got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, Surveil), (
        f"Bridge effect must be Surveil; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert bridge_ta.effect.amount == 1, (
        f"Bridge Surveil amount must be 1; got {bridge_ta.effect.amount}"
    )

    # ------------------------------------------------------------------
    # 4. Rust: inject Appendage Amalgam (Enchantment Creature 3/2) onto
    #    p0's battlefield (not summoning-sick).
    # ------------------------------------------------------------------
    rs_aa_id = rs.register_and_inject_object(
        {
            "name": "Appendage Amalgam",
            "card_types": ["Enchantment", "Creature"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [aa_ta_dict],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)

    # ------------------------------------------------------------------
    # 5. Rust: declare_attacker → ATTACKS trigger pushed → drain.
    # ------------------------------------------------------------------
    assert rs.declare_attacker(rs_aa_id) is True, (
        "Rust: declare_attacker must succeed for a valid unsick attacker"
    )
    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 ATTACKS trigger (Surveil) must be pushed "
        f"after declaring; got {rs.stack_size()}"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_lib_size = rs.library_sizes[0]
    rs_gy_size = rs.graveyard_sizes[0]
    assert rs_lib_size == 2, (
        f"Rust: library must still have 2 seed cards after Surveil "
        f"(keep-on-top path, agent=None); got {rs_lib_size}"
    )
    assert rs_gy_size == 0, (
        f"Rust: graveyard must be empty after Surveil "
        f"(keep-on-top path, agent=None); got {rs_gy_size}"
    )

    # ------------------------------------------------------------------
    # 6. Python: inject genuine Appendage Amalgam printing (bridge TA)
    #    onto p0's battlefield.
    # ------------------------------------------------------------------
    py_aa_printing = CardPrinting(
        name="Appendage Amalgam",
        mana_cost_str="{1}{U}",
        mana_cost=ManaCost(generic=1, colored=(("U", 1),)),
        type_line="Enchantment Creature — Horror",
        supertypes=(),
        card_types=("Enchantment", "Creature"),
        subtypes=("Horror",),
        power=int(real.power),
        toughness=int(real.toughness),
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_aa = py.new_object(py_aa_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_aa.summoning_sick = False
    py_aa.tapped = False
    py_aa.damage = 0
    py_aa.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_aa)

    # ------------------------------------------------------------------
    # 7. Python: declare_attackers → ATTACKS trigger pushed → drain.
    # ------------------------------------------------------------------
    py_combat.declare_attackers(py, [py_aa.id])

    assert len(py.stack) == 1, (
        f"Python: exactly 1 ATTACKS trigger (Surveil) must be pushed "
        f"after declaring; got {len(py.stack)}"
    )

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    py_lib_size = len(py.players[0].library)
    py_gy_size = len(py.players[0].graveyard)
    assert py_lib_size == 2, (
        f"Python: library must still have 2 seed cards after Surveil "
        f"(keep-on-top path, agent=None); got {py_lib_size}"
    )
    assert py_gy_size == 0, (
        f"Python: graveyard must be empty after Surveil "
        f"(keep-on-top path, agent=None); got {py_gy_size}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_lib_size == py_lib_size, (
        f"Library size: Rust={rs_lib_size}, Python={py_lib_size} "
        f"(must be byte-equal — Surveil(1) keep-on-top path resolved "
        f"on BOTH engines via ATTACKS dispatch for Appendage Amalgam)"
    )
    assert rs_gy_size == py_gy_size, (
        f"Graveyard size: Rust={rs_gy_size}, Python={py_gy_size} "
        f"(must be byte-equal — Surveil(1) keep-on-top path: "
        f"no card moved to graveyard on BOTH engines)"
    )


# ---------------------------------------------------------------------------
# Probe 3 — Bashful Beastie: DIES → ManifestDread(1)
# (IsSelf predicate; deterministic top-card manifest with agent=None)
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_bashful_beastie_dies_manifest_dread_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe — Bashful Beastie
    (round 19, DIES / IsSelf, ManifestDread(1)).**

    Drives the **real parsed Bashful Beastie printing** on the Python side
    and a bridged synthetic carrier on the Rust side through the ``DIES``
    dispatch path.

    This probe pins Bashful Beastie's "When Bashful Beastie dies, manifest
    dread." trigger.

    With ``agent=None`` (the default in ``build_python_state``),
    ManifestDread is fully deterministic on both engines:

      * Python: ``ManifestDread.resolve`` falls back to ``manifest_id =
        options[0]`` (TOP card) when ``p.agent is None``; the top Plains
        seed card is manifested face-down on the battlefield, the second
        Plains goes to the graveyard.
      * Rust: ManifestDread manifests the top-indexed library object onto
        the battlefield face-down; the second goes to the graveyard.

    Setup:
      * p0 has Bashful Beastie (5/4 Enchantment Creature) on the
        battlefield.
      * p0's library has 2 Plains seed cards on both engines.
      * p1 has no permanents.
      * Active player = p0.

    Kill flow:
      1. Deal ``toughness`` damage to Bashful Beastie on BOTH engines.
      2. Apply SBAs: Bashful Beastie is lethal-damaged → moves to
         graveyard → DIES trigger pushed on BOTH engines.
      3. Drain: ManifestDread resolves — top Plains manifested face-down
         on p0's battlefield, second Plains to p0's graveyard.

    Observables asserted (targeted):
      * Bashful Beastie no longer on battlefield (moved to graveyard).
      * p0 battlefield: exactly 1 object (the face-down manifested Plains).
      * p0 library: 0 cards (both consumed by ManifestDread).
      * p0 graveyard: 2 objects (Bashful Beastie + one Plains).

    Rust triggered-ability dict::

        {
            "event": "dies",
            "predicate": {"kind": "source_is_self"},
            "effect": {"kind": "manifest_dread", "count": 1},
        }
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state,
        build_rust_state,
        _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.game import Zone
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.generic.library_lookat import ManifestDread

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Bashful Beastie printing has the
    #    expected DIES trigger shape.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Bashful Beastie")
    if real is None:
        pytest.skip("Bashful Beastie absent from active CardSource")

    assert "Creature" in real.card_types, (
        "Bashful Beastie must be a Creature"
    )
    dies_ta = next(
        (ta for ta in real.triggered_abilities if ta.event == Event.DIES),
        None,
    )
    assert dies_ta is not None, (
        "Bashful Beastie must have a DIES triggered ability; "
        f"abilities found: "
        f"{[(ta.event, type(ta.effect).__name__) for ta in real.triggered_abilities]}"
    )
    assert isinstance(dies_ta.effect, ManifestDread), (
        f"Bashful Beastie DIES TA effect must be ManifestDread; "
        f"got {type(dies_ta.effect).__name__}"
    )
    assert dies_ta.effect.count == 1, (
        f"Bashful Beastie ManifestDread count must be 1; "
        f"got {dies_ta.effect.count}"
    )

    # ------------------------------------------------------------------
    # 2. Build cross-engine states (empty decks) then seed each engine's
    #    p0 library with 2 Plains (ManifestDread consumes them).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)

    # Python library seeds.
    plains = BASIC_LANDS["Plains"]
    for _ in range(2):
        py_seed = py.new_object(plains, owner_id=0, zone=Zone.LIBRARY)
        py_seed.summoning_sick = False
        py.players[0].library.append(py_seed)

    # Rust library seeds (inert lib objects; provide ManifestDread targets).
    for _ in range(2):
        rs.register_and_inject_object(
            {
                "name": "Plains",
                "card_types": ["Land", "Basic"],
                "supertypes": ["Basic"],
                "mana_cost": {"generic": 0},
            },
            0, 1,  # owner=0, ZONE_LIBRARY
        )

    ZB = 2  # ZONE_BATTLEFIELD

    # ------------------------------------------------------------------
    # 3. Build the shared triggered-ability dict.
    # ------------------------------------------------------------------
    bb_ta_dict = {
        "event": "dies",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "manifest_dread", "count": 1},
    }

    # Sanity: bridge translates the dict correctly.
    bridge_ta = _ta_dict_to_python_triggered_ability(bb_ta_dict)
    assert bridge_ta.event == Event.DIES, (
        f"Bridge must translate 'dies' to Event.DIES; "
        f"got {bridge_ta.event!r}"
    )
    assert isinstance(bridge_ta.predicate, IsSelf), (
        f"Bridge predicate must be IsSelf; "
        f"got {type(bridge_ta.predicate).__name__}"
    )
    assert isinstance(bridge_ta.effect, ManifestDread), (
        f"Bridge effect must be ManifestDread; "
        f"got {type(bridge_ta.effect).__name__}"
    )
    assert bridge_ta.effect.count == 1, (
        f"Bridge ManifestDread count must be 1; got {bridge_ta.effect.count}"
    )

    # ------------------------------------------------------------------
    # 4. Rust: inject Bashful Beastie onto p0's battlefield.
    # ------------------------------------------------------------------
    rs_bb_id = rs.register_and_inject_object(
        {
            "name": "Bashful Beastie",
            "card_types": ["Enchantment", "Creature"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [bb_ta_dict],
        },
        0, ZB,
    )
    assert rs.find_object_zone(rs_bb_id) == ZB, (
        "Bashful Beastie carrier must be on Rust battlefield"
    )

    # ------------------------------------------------------------------
    # 5. Rust: deal lethal damage → SBA moves to graveyard → DIES
    #    trigger pushed → drain (ManifestDread resolves).
    # ------------------------------------------------------------------
    rs.deal_damage(rs_bb_id, int(real.toughness))
    rs.apply_sbas()  # lethal damage → graveyard + DIES dispatch

    assert rs.stack_size() == 1, (
        f"Rust: exactly 1 DIES trigger (ManifestDread) must be pushed "
        f"after lethal damage + SBAs; got {rs.stack_size()}"
    )
    assert rs.find_object_zone(rs_bb_id) != ZB, (
        "Rust: Bashful Beastie must have left the battlefield after "
        "lethal damage + SBAs"
    )

    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # Observe Rust BF: exactly 1 face-down object (the manifested Plains).
    rs_bf = rs.battlefield_snapshot()
    rs_bf_count = len(rs_bf)
    assert rs_bf_count == 1, (
        f"Rust: exactly 1 object (manifested Plains) must be on p0's "
        f"battlefield after ManifestDread; got {rs_bf_count}"
    )

    # Library exhausted (both Plains consumed by ManifestDread).
    rs_lib_size = rs.library_sizes[0]
    assert rs_lib_size == 0, (
        f"Rust: library must be empty after ManifestDread consumes both "
        f"Plains seeds; got {rs_lib_size}"
    )

    # Graveyard: Bashful Beastie + 1 Plains (the non-manifested card).
    rs_gy_size = rs.graveyard_sizes[0]
    assert rs_gy_size == 2, (
        f"Rust: graveyard must have 2 cards (Bashful Beastie + 1 Plains) "
        f"after ManifestDread; got {rs_gy_size}"
    )

    # ------------------------------------------------------------------
    # 6. Python: inject genuine Bashful Beastie printing (bridge TA)
    #    onto p0's battlefield.
    # ------------------------------------------------------------------
    py_bb_printing = CardPrinting(
        name="Bashful Beastie",
        mana_cost_str="{4}{U}{U}",
        mana_cost=ManaCost(generic=4, colored=(("U", 2),)),
        type_line="Enchantment Creature — Horror",
        supertypes=(),
        card_types=("Enchantment", "Creature"),
        subtypes=("Horror",),
        power=int(real.power),
        toughness=int(real.toughness),
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(bridge_ta,),
    )
    py_bb = py.new_object(py_bb_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_bb.summoning_sick = False
    py_bb.tapped = False
    py_bb.damage = 0
    py_bb.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_bb)

    # ------------------------------------------------------------------
    # 7. Python: deal lethal damage → SBA → DIES trigger pushed → drain.
    # ------------------------------------------------------------------
    py_bb.damage = int(real.toughness)  # mark lethal damage directly
    py_sba(py)  # lethal damage → graveyard + DIES dispatch

    assert len(py.stack) == 1, (
        f"Python: exactly 1 DIES trigger (ManifestDread) must be pushed "
        f"after lethal damage + SBAs; got {len(py.stack)}"
    )
    assert py_bb not in py.battlefield, (
        "Python: Bashful Beastie must have left the battlefield after "
        "lethal damage + SBAs"
    )

    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)

    # Observe Python BF: exactly 1 face-down object (the manifested Plains).
    py_bf_count = len(py.battlefield)
    assert py_bf_count == 1, (
        f"Python: exactly 1 object (manifested Plains) must be on p0's "
        f"battlefield after ManifestDread; got {py_bf_count}"
    )
    assert py.battlefield[0].face_down is True, (
        "Python: the manifested object must be face-down"
    )

    # Library exhausted.
    py_lib_size = len(py.players[0].library)
    assert py_lib_size == 0, (
        f"Python: library must be empty after ManifestDread consumes both "
        f"Plains seeds; got {py_lib_size}"
    )

    # Graveyard: Bashful Beastie + 1 Plains.
    py_gy_size = len(py.players[0].graveyard)
    assert py_gy_size == 2, (
        f"Python: graveyard must have 2 cards (Bashful Beastie + 1 Plains) "
        f"after ManifestDread; got {py_gy_size}"
    )

    # ------------------------------------------------------------------
    # 8. Cross-engine byte-equality on targeted observables.
    # ------------------------------------------------------------------
    assert rs_bf_count == py_bf_count, (
        f"Battlefield count: Rust={rs_bf_count}, Python={py_bf_count} "
        f"(must be byte-equal — 1 face-down manifested Plains on BOTH "
        f"engines via DIES dispatch for Bashful Beastie)"
    )
    assert rs_lib_size == py_lib_size, (
        f"Library size: Rust={rs_lib_size}, Python={py_lib_size} "
        f"(must be byte-equal — both Plains consumed by ManifestDread "
        f"on BOTH engines)"
    )
    assert rs_gy_size == py_gy_size, (
        f"Graveyard size: Rust={rs_gy_size}, Python={py_gy_size} "
        f"(must be byte-equal — Bashful Beastie + 1 Plains in graveyard "
        f"on BOTH engines)"
    )
