"""Genuine cross-engine probes — batch RRR downstream unlock
(12th + 13th Rust slices; closes RRR Pins 1+2+3 on the
state_ops_resolve.rs zone-change reset substrate).

**12th Rust slice (Pin 1 closure):**

The 12th Rust slice dropped the explicit ``obj.summoning_sick = true``
stamp at:
  * ``Effect::ExileOpponentsNonlandPermanentUntilLeaves`` (bare arm)
  * ``Effect::ExileOpponentsNonlandPermanentWithMaxMvUntilLeaves``
    (max_mv rider sibling, used by Seam Rip)

Both arms now preserve the pre-exile ``summoning_sick`` value
naturally via the bare ``remove`` -> ``push`` sequence, matching
Python's ``move_off_battlefield`` semantics
(``turn.py:141-315``) which never touches the field.

3 EoE cards parity-aligned: Banishing Light, Hardlight Containment,
Seam Rip.

**13th Rust slice (Pins 2+3 closure):**

The 13th Rust slice closed two more gaps on the same zone-change
reset substrate, both on
``Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``:

  * Pin 2 — dropped the ``obj.summoning_sick = true`` stamp at the
    bf->library transition; the pre-bounce value now persists
    (matches Python's inline-resolve in zone_moves.py:96-128 which
    never touches the field).

  * Pin 3 — changed the no-agent default from ``lib_mut.push(obj)``
    (BOTTOM) to ``lib_mut.insert(0, obj)`` (TOP); matches Python's
    no-agent default of ``library.insert(0, obj)`` on the
    ``choice=0`` branch in zone_moves.py:86-94. CE13's Rust-
    converges-on-Python precedent.

1 EoE card parity-aligned: Lost in Space.

PROBE TESTS
-----------

Probe 1 (slice 12) -- Banishing Light real-EoE byte-equal probe on
the ``summoning_sick`` slot of the exiled object. The bait artifact
is seeded on P1's bf with ``summoning_sick=False`` (sat through SBAs;
the standard MTG state for a controlled permanent), exiled by P0's
Banishing Light ETB trigger; the exiled object must carry
``summoning_sick=False`` on BOTH engines.

Probe 2 (slice 13) -- Lost in Space real-EoE byte-equal probe on
BOTH the ``summoning_sick`` field (Pin 2) AND the library zone
position (Pin 3) of the bounced object. The bait creature is seeded
on P1's bf with ``summoning_sick=False`` and a sentinel card on top
of P1's library; Lost in Space (cast by P0, target=bait) bounces it
to P1's library; the bounced object must (a) preserve
``summoning_sick=False`` and (b) land at library[0] (TOP, above the
sentinel) on BOTH engines. No agent is seated on P1 so the no-agent
default path is exercised on both engines.
"""

from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


def test_rrr_probe_banishing_light_exile_preserves_summoning_sick_real_eoe():
    """**12th Rust slice RRR Pin 1 closure — Banishing Light real-EoE
    byte-equal probe on the exiled object's ``summoning_sick`` field.**

    Drives both engines' ``ExileOpponentsNonlandPermanentUntilLeaves``
    arm end-to-end on a real EoE printing (Banishing Light, bare-shape
    no-MV-cap), then asserts the EXILED bait object's
    ``summoning_sick`` matches the pre-exile value (False) on BOTH
    engines.

    Pre-closure behavior (the divergence Pin 1 locked in):
      Rust hardcoded ``obj.summoning_sick = true`` after bf-removal
      and before the exile push -> Rust's exile_p1 view showed
      summoning_sick=True even though the bait was not summoning-sick
      on the battlefield. Python's ``move_off_battlefield`` preserved
      the pre-exile value (False).

    Post-closure behavior (asserted here):
      Both engines preserve ``summoning_sick=False`` on the exile
      transition. The other CR 400.7 reset fields (tapped, damage,
      counters, attached_to) continue to clear identically; only the
      stamp drop changes behavior, and only on the summoning_sick
      axis.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from tests.parity._picker_shims import (
        _PickFirstOpponentTargetCreaturePreferredAgent,
    )
    from mtg_bot.actions import (
        _trigger_etb_abilities, resolve_top_of_stack,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.exile import (
        ExileOpponentsNonlandPermanentUntilLeaves,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.game import Zone

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2

    # ---- Rust: inject the bait artifact onto P1's bf. --------------
    rust_bait_id = rust_state.register_and_inject_object(
        {
            "name": "Banishing Light Bait Artifact",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 1},
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_BATTLEFIELD,
    )
    # Bait is summoning-sick by default on inject; clear it so the
    # pre-exile value is unambiguously False (the production state
    # for a controlled permanent that's been on bf since the prior
    # turn or doesn't need summoning_sick at all — Artifacts don't
    # care about summoning_sick for tapping but the field carries
    # nonetheless).
    rust_state.clear_summoning_sick_for_player(1)

    # ---- Rust: inject Banishing Light onto P0's bf — fires ETB. ----
    rust_source_id = rust_state.register_and_inject_object(
        {
            "name": "Banishing Light",
            "card_types": ["Enchantment"],
            "mana_cost": {"generic": 2, "W": 1},
            "effects": [],
            "triggered_abilities": [{
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {
                    "kind": "exile_opponents_nonland_permanent_until_leaves",
                },
            }],
        },
        0, ZONE_BATTLEFIELD,
    )
    assert rust_state.stack_size() == 1, (
        "Rust: Banishing Light's arrival on P0 should fire its ENTERS "
        f"trigger; got stack_size={rust_state.stack_size()}"
    )

    # ---- Python: mirror setup. -------------------------------------
    bait_printing = CardPrinting(
        name="Banishing Light Bait Artifact",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=()),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None, toughness=None,
        produces=frozenset(), keywords=frozenset(),
        triggered_abilities=(),
    )
    py_bait = py_state.new_object(
        bait_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    # Match Rust: bait is NOT summoning-sick on its controller's bf.
    py_bait.summoning_sick = False
    py_bait.tapped = False
    py_bait.damage = 0
    py_bait.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_bait)

    source_printing = CardPrinting(
        name="Banishing Light",
        mana_cost_str="",
        mana_cost=ManaCost(generic=2, colored=(("W", 1),)),
        type_line="Enchantment",
        supertypes=(),
        card_types=("Enchantment",),
        subtypes=(),
        power=None, toughness=None,
        produces=frozenset(), keywords=frozenset(),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf(),
                effect=ExileOpponentsNonlandPermanentUntilLeaves(),
            ),
        ),
    )
    py_state.players[0].agent = (
        _PickFirstOpponentTargetCreaturePreferredAgent()
    )
    py_source = py_state.new_object(
        source_printing, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.summoning_sick = False
    py_source.tapped = False
    py_source.damage = 0
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)
    _trigger_etb_abilities(py_state, py_source)
    assert len(py_state.stack) == 1, (
        f"Python: ENTERS trigger should fire; got stack={len(py_state.stack)}"
    )

    # ---- Drain both stacks. ----------------------------------------
    while rust_state.stack_size() > 0:
        rust_state.resolve_top_of_stack()
    while py_state.stack:
        resolve_top_of_stack(py_state)

    # ---- Assert summoning_sick is preserved on the EXILED object. --
    # Rust: walk P1's exile snapshot for the bait.
    rust_exile_p1 = rust_state.exile_snapshot(1)
    rust_bait_in_exile = [
        e for e in rust_exile_p1
        if e["printing_name"] == "Banishing Light Bait Artifact"
    ]
    assert len(rust_bait_in_exile) == 1, (
        f"Rust: bait should be on P1's exile; "
        f"got exile_p1 contents={rust_exile_p1!r}"
    )
    rust_exile_ss = rust_bait_in_exile[0].get("summoning_sick")
    assert rust_exile_ss == 0 or rust_exile_ss is False, (
        f"Rust RRR Pin 1 closure: exiled bait's summoning_sick should "
        f"be 0/False (preserved from pre-exile); got "
        f"summoning_sick={rust_exile_ss!r}"
    )

    # Python: walk P1's exile.
    py_exile_p1 = py_state.players[1].exile
    py_bait_in_exile = [
        o for o in py_exile_p1
        if o.printing.name == "Banishing Light Bait Artifact"
    ]
    assert len(py_bait_in_exile) == 1, (
        f"Python: bait should be on P1's exile; got exile_p1 size="
        f"{len(py_exile_p1)}"
    )
    py_exile_ss = py_bait_in_exile[0].summoning_sick
    assert py_exile_ss is False, (
        f"Python: exiled bait's summoning_sick should be False "
        f"(preserved by move_off_battlefield); got summoning_sick="
        f"{py_exile_ss!r}"
    )

    # Cross-engine: byte-equal on the closing axis.
    assert bool(rust_exile_ss) == bool(py_exile_ss) == False, (
        "Both engines must produce summoning_sick=False on the exiled "
        f"bait (rust={rust_exile_ss}, py={py_exile_ss})"
    )


def test_rrr_probe_lost_in_space_library_bounce_preserves_summoning_sick_and_lands_at_top_real_eoe():
    """**13th Rust slice RRR Pins 2+3 closure — Lost in Space real-EoE
    byte-equal probe on the bounced object's ``summoning_sick`` field
    AND library position.**

    Drives both engines'
    ``Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
    arm end-to-end via a Lost-in-Space-shape Instant cast by P0
    targeting a bait creature on P1's bf. No agent is seated on P1
    (the OWNER of the bait), so the no-agent default path executes
    on both engines. Asserts byte-equality on:

      (a) ``summoning_sick`` field of the bounced object (RRR Pin 2
          closure: pre-bounce value preserved on bf->library; was
          stamped True pre-slice-13 on Rust).

      (b) library position of the bounced object (RRR Pin 3 closure:
          no-agent default = TOP = library[0], matching Python's
          ``library.insert(0, obj)``; was BOTTOM = library[-1] pre-
          slice-13 on Rust).

    Pre-slice-13 behavior (the divergences Pins 2+3 locked in):
      Rust's resolve arm hardcoded ``obj.summoning_sick = true`` and
      ``lib_mut.push(obj)`` (BOTTOM). Python's resolve preserved the
      pre-bounce summoning_sick value and defaulted to TOP via
      ``library.insert(0, obj)`` on the no-agent branch.

    Post-slice-13 behavior (asserted here):
      Both engines preserve ``summoning_sick=False`` AND land the
      bounced creature at ``library[0]`` (TOP, above the sentinel).
      The other CR 400.7 reset fields (tapped, damage, counters,
      attached_to) continue to clear identically on both engines.

    Lost in Space's oracle text: "Target artifact or creature's
    owner puts it on their choice of the top or bottom of their
    library. Surveil 1."  The bridge effect ``kind`` =
    ``owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library``
    drives exactly the Rust arm closed by slice 13; the Surveil 1
    rider is intentionally OUT OF SCOPE for this probe (separate
    Effect, separate parity surface — keeps the byte-equal axis
    focused on the closure).

    Sentinel placement design: a sentinel card is seeded on TOP of
    P1's library BEFORE the resolve, so the bounced creature's
    landing position is observable at library index 0 (above the
    sentinel) vs library index 1 (below, i.e. between top and
    bottom for a 2-element library). Pre-slice-13 Rust would land
    the bounced creature at library[-1] = library[1] (BOTTOM,
    below the sentinel); post-slice-13 it lands at library[0]
    (TOP, above the sentinel) matching Python.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.effects.generic.zone_moves import (
        OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    )
    from mtg_bot.game import Zone

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)
    rust_state = build_rust_state(spec)
    ZONE_BATTLEFIELD = 2
    ZONE_LIBRARY = 1

    # ---- Rust: seed sentinel on TOP of P1's library. ----------------
    # The sentinel anchors the library position assertion: after the
    # bounce, library[0] = bounced creature (TOP), library[1] =
    # sentinel (pushed down from former-top).
    rust_sentinel_id = rust_state.register_and_inject_object(
        {
            "name": "Lost in Space Sentinel Card",
            "card_types": ["Sorcery"],
            "mana_cost": {"generic": 1},
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_LIBRARY,
    )

    # ---- Rust: inject the bait creature onto P1's bf. ---------------
    rust_bait_id = rust_state.register_and_inject_object(
        {
            "name": "Lost in Space Bait Creature",
            "card_types": ["Creature"],
            "mana_cost": {"generic": 1},
            "power": 2,
            "toughness": 2,
            "effects": [],
            "triggered_abilities": [],
        },
        1, ZONE_BATTLEFIELD,
    )
    # Bait is summoning-sick by default on inject; clear it so the
    # pre-bounce value is unambiguously False.
    rust_state.clear_summoning_sick_for_player(1)

    # ---- Rust: register + push Lost in Space onto stack with the ----
    # bait as bound target; cast by P0 (controller=0). Lost in Space
    # is parsed by mtg_bot.cards.parser as
    # ``Sequence(OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary,
    # Surveil(1))``; for this probe we drive ONLY the
    # OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary leg so
    # the byte-equal axis stays focused on the slice-13 closure.
    rust_spell_id = rust_state.register_and_inject_object(
        {
            "name": "Lost in Space",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 3, "U": 1},
            "effects": [
                {
                    "kind": (
                        "owner_puts_target_artifact_or_creature_"
                        "on_top_or_bottom_of_library"
                    ),
                },
            ],
            "triggered_abilities": [],
        },
        0, 0,  # owner=0, ZONE_HAND
    )
    rust_state.push_to_stack_with_target(rust_spell_id, 0, rust_bait_id)
    assert rust_state.stack_size() == 1, (
        f"Rust: Lost in Space should be on the stack with bait as "
        f"target; got stack_size={rust_state.stack_size()}"
    )

    # ---- Python: mirror setup. --------------------------------------
    sentinel_printing = CardPrinting(
        name="Lost in Space Sentinel Card",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=()),
        type_line="Sorcery",
        supertypes=(),
        card_types=("Sorcery",),
        subtypes=(),
        power=None, toughness=None,
        produces=frozenset(), keywords=frozenset(),
        triggered_abilities=(),
    )
    py_sentinel = py_state.new_object(
        sentinel_printing, owner_id=1, zone=Zone.LIBRARY,
    )
    py_state.players[1].library.append(py_sentinel)

    bait_printing = CardPrinting(
        name="Lost in Space Bait Creature",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=()),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2, toughness=2,
        produces=frozenset(), keywords=frozenset(),
        triggered_abilities=(),
    )
    py_bait = py_state.new_object(
        bait_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_bait.summoning_sick = False
    py_bait.tapped = False
    py_bait.damage = 0
    py_bait.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_bait)

    # Pre-condition: no agent seated on P1 (the OWNER); the no-agent
    # default path picks TOP via choice=0 (zone_moves.py:92-93).
    assert py_state.players[1].agent is None, (
        "Probe pre-condition: P1 (the bait OWNER) must have NO agent "
        "seated so the no-agent default path is exercised on Python."
    )

    # Resolve the bounce effect directly on Python (no spell
    # mana-cost / stack machinery, just the resolve arm under test).
    effect = OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary()
    effect.resolve(
        py_state,
        controller_id=0,  # P0 cast the spell
        targets=(("permanent", py_bait.id),),
    )

    # ---- Drain Rust's stack. ----------------------------------------
    rust_state.resolve_top_of_stack()
    assert rust_state.stack_size() == 0, (
        f"Rust: stack should be empty after resolve; got "
        f"stack_size={rust_state.stack_size()}"
    )

    # ---- Per-engine assertions on the bounced object. ---------------
    # Rust: walk P1's library snapshot for the bait.
    rust_lib_p1 = rust_state.library_snapshot(1)
    assert len(rust_lib_p1) == 2, (
        f"Rust: P1's library should have 2 cards after the bounce "
        f"(sentinel + bounced bait); got {len(rust_lib_p1)} cards: "
        f"{[e['printing_name'] for e in rust_lib_p1]!r}"
    )
    rust_bait_lib_entry = next(
        (e for e in rust_lib_p1
         if e["printing_name"] == "Lost in Space Bait Creature"),
        None,
    )
    assert rust_bait_lib_entry is not None, (
        f"Rust: bounced bait should be in P1's library; got "
        f"library_p1 contents={rust_lib_p1!r}"
    )

    # Pin 2 axis: summoning_sick preserved on bf->library.
    rust_lib_ss = rust_bait_lib_entry.get("summoning_sick")
    assert rust_lib_ss == 0 or rust_lib_ss is False, (
        f"Rust RRR Pin 2 closure: bounced bait's summoning_sick "
        f"should be 0/False (preserved from pre-bounce); got "
        f"summoning_sick={rust_lib_ss!r}"
    )

    # Pin 3 axis: bounced bait at library[0] (TOP), sentinel pushed
    # to library[1].
    rust_lib_names = [e["printing_name"] for e in rust_lib_p1]
    assert rust_lib_names[0] == "Lost in Space Bait Creature", (
        f"Rust RRR Pin 3 closure: bounced bait should be at "
        f"library[0] (TOP) per the post-slice-13 no-agent default; "
        f"got library_p1 order={rust_lib_names!r}"
    )
    assert rust_lib_names[1] == "Lost in Space Sentinel Card", (
        f"Rust RRR Pin 3 closure: sentinel should be at library[1] "
        f"(pushed down from former-top); got library_p1 order="
        f"{rust_lib_names!r}"
    )

    # Python: walk P1's library for the bait.
    py_lib_p1 = py_state.players[1].library
    assert len(py_lib_p1) == 2, (
        f"Python: P1's library should have 2 cards after the bounce "
        f"(sentinel + bounced bait); got {len(py_lib_p1)} cards: "
        f"{[o.printing.name for o in py_lib_p1]!r}"
    )
    py_bait_lib_entry = next(
        (o for o in py_lib_p1
         if o.printing.name == "Lost in Space Bait Creature"),
        None,
    )
    assert py_bait_lib_entry is not None, (
        f"Python: bounced bait should be in P1's library; got "
        f"library_p1={[o.printing.name for o in py_lib_p1]!r}"
    )

    # Pin 2 axis on Python.
    py_lib_ss = py_bait_lib_entry.summoning_sick
    assert py_lib_ss is False, (
        f"Python: bounced bait's summoning_sick should be False "
        f"(preserved by inline-resolve in zone_moves.py); got "
        f"summoning_sick={py_lib_ss!r}"
    )

    # Pin 3 axis on Python: bait at library[0] (TOP); sentinel at
    # library[1].
    py_lib_names = [o.printing.name for o in py_lib_p1]
    assert py_lib_names[0] == "Lost in Space Bait Creature", (
        f"Python: bounced bait should be at library[0] (TOP) per "
        f"the no-agent default; got library_p1 order={py_lib_names!r}"
    )
    assert py_lib_names[1] == "Lost in Space Sentinel Card", (
        f"Python: sentinel should be at library[1] (pushed down "
        f"from former-top); got library_p1 order={py_lib_names!r}"
    )

    # ---- Cross-engine byte-equality on both closing axes. ----------
    assert bool(rust_lib_ss) == bool(py_lib_ss) == False, (
        f"Cross-engine byte-equality (RRR Pin 2 closure): both "
        f"engines must produce summoning_sick=False on the bounced "
        f"bait (rust={rust_lib_ss}, py={py_lib_ss})"
    )
    assert rust_lib_names == py_lib_names, (
        f"Cross-engine byte-equality (RRR Pin 3 closure): both "
        f"engines must produce the same library_p1 order; got "
        f"rust={rust_lib_names!r}, py={py_lib_names!r}"
    )
