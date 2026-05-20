"""Genuine cross-engine probes — batch RRR downstream unlock
(12th Rust slice; closes RRR Pin 1 — ExileOpponentsNonlandPermanent
UntilLeaves summoning_sick stamp drop).

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

The pre-closure divergence surfaced via QQQ's Trapped-in-the-Screen
probe attempt's ``compare_fields`` divergence on the
``exile_p1`` field-view tuple slot 2 (``summoning_sick``):

  Python: ('Bait', 0, 0, 0, 0, None, 1, 0)
  Rust:   ('Bait', 0, 1, 0, 0, None, 1, 0)
                  ^^ summoning_sick slot

Post-closure, both engines now produce ``summoning_sick=0`` on the
exiled bait — byte-equal.

PROBE TESTS
-----------

Probe 1 -- Banishing Light real-EoE byte-equal probe on the
``summoning_sick`` slot of the exiled object. The bait artifact is
seeded on P1's bf with ``summoning_sick=False`` (sat through SBAs;
the standard MTG state for a controlled permanent), exiled by P0's
Banishing Light ETB trigger; the exiled object must carry
``summoning_sick=False`` on BOTH engines.

This probe complements the existing
``test_cross_engine_real_eoe_banishing_light_etb_exile_nonland_permanent_until_leaves_parity``
in test_parity_smoke.py: that probe asserts NAME + COUNT axes only;
this probe additionally pins the ``summoning_sick`` field of the
exiled object — the axis the QQQ probe attempt surfaced and the RRR
Pin 1 fixture asserted divergent.
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
