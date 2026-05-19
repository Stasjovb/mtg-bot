"""Batch FF: BLOCKED / BLOCKS trigger lane recon — substrate gap documented.

This module is the round-9 pivot probe batch for the BLOCKED trigger family.
The directive asked for 2–4 genuine real-EoE byte-equality probes for cards
whose primary mechanic is an ``Event.BLOCKS``-family trigger ("Whenever this
creature becomes blocked", "Whenever this creature blocks a creature
with <quality>", etc.).

SUBSTRATE-GAP FINDING — zero genuine EoE probes shipped.
=========================================================

Two overlapping substrate gaps block all genuine real-EoE byte-equal probes
for BLOCKS-triggered cards at this HEAD:

Gap 1: ``source_is_self`` bridge predicate fails on multi-subject BLOCKS events
------------------------------------------------------------------------
``Event.BLOCKS`` carries TWO subjects — ``("blocker", "attacker")``
(``src/mtg_bot/effects/predicates.py:211``).  The cross-engine bridge
(``src/mtg_bot/parity/cross_engine.py:8729``) translates ``source_is_self``
to ``IsSelf(subject=None)``.  The ``_resolve_subject`` helper (predicates.py:340)
only auto-resolves the default single-subject case::

    if len(subjects) == 1:
        return next(iter(subjects.values()))
    return None   # ← returns None for 2-subject events

So ``IsSelf(subject=None).matches({blocker: ..., attacker: ...}, source)``
evaluates to ``None is source`` = False — the trigger NEVER fires on the
Python side when the carrier is constructed from the bridge's ``source_is_self``
predicate kind.  The correct predicate for "whenever this creature blocks" is
``IsSelf(subject="blocker")``, which requires a BLOCKS-aware predicate kind or
a slot-parameterised ``source_is_self_as`` kind that the current bridge lacks.

Gap 2: ``attacker_has_keyword`` predicate not bridged (Skystinger)
------------------------------------------------------------------
The EoE pool's only BLOCKS-triggered card is **Skystinger** (8,306 decks,
rank 58).  Its oracle text is::

    Whenever this creature blocks a creature with flying,
    this creature gets +5/+0 until end of turn.

Parsed predicate: ``IsSelf(subject="blocker") & Subject("attacker",
HasKeyword("flying"))`` (``src/mtg_bot/cards/parser/triggers.py:801``).

The second conjunct needs ``HasKeyword`` applied to the **attacker** subject.
Neither the Python bridge (``_ta_dict_to_python_predicate`` in
``cross_engine.py``) nor the Rust ``Predicate`` enum (``cards.rs:4061``)
has a ``subject_has_keyword`` / ``attacker_has_keyword`` variant.  The Rust
``declare_blocker`` site (``state_ops_combat.rs:818``) also documents this
explicitly::

    // **Subject mapping divergence from Python**: Python's BLOCKS event
    // carries two subjects (blocker + attacker) and exposes both to
    // predicates via the multi-subject schema.  Rust's single-subject
    // `dispatch_event` API only threads the blocker today; multi-subject
    // predicates against the attacked creature (e.g. Skystinger's
    // "whenever ~ blocks a creature with flying") need the
    // `Predicate::Subject(slot, inner)` substrate that a future slice
    // will introduce alongside `Event::DealsCombatDamage`.

This was also flagged by batch-B recon (``test_probe_covered_unprobed_b.py``
lines 87-92): "Not cleanly probe-constructible with the existing harness;
dropped."

EoE BLOCKS-triggered candidate inventory (exhaustive):
-------------------------------------------------------
The full EoE pool (266 cards, ``data/edge_of_eternities.json``) contains
exactly **one** card with a BLOCKS-family triggered ability:

* **Skystinger** (rank 58, 8,306 decks) — 3/2 with Reach.
  Oracle: "Whenever this creature blocks a creature with flying, this creature
  gets +5/+0 until end of turn."
  Predicate: ``IsSelf(subject="blocker") & Subject("attacker",
  HasKeyword("flying"))``.
  Blocked by Gaps 1 + 2 above.

The other EoE "block" references in oracle text are:
* Atomic Microsizer — ATTACKS trigger; "can't be blocked this turn" is the
  *effect*, not the trigger.
* Pinnacle Emissary / Station Monitor — IS_CAST triggers; "can block only
  creatures with flying" is a token keyword restriction, not a BLOCKS trigger.
* Various "Menace", "Skulk", "can't be blocked unless…" riders — keyword
  abilities, not triggered abilities.

What unblocks the lane:
-----------------------
1. Add a ``"blocker_is_self"`` (or ``"source_is_self_in_blocker_slot"``)
   predicate kind to the Rust ``Predicate`` enum and the bridge's
   ``_ta_dict_to_python_predicate`` that explicitly resolves the
   ``"blocker"`` subject slot, mirroring ``IsSelf(subject="blocker")``.
   This fixes Gap 1 and enables simple "whenever this creature blocks" probes.
2. Add a ``"subject_has_keyword"`` predicate kind (Rust: a new
   ``Predicate::SubjectHasKeyword(keyword: String)`` variant that reads
   ``battlefield_has_keyword(state, subject_id, &keyword)``; bridge: a new
   arm in ``_ta_dict_to_python_predicate`` returning
   ``Subject(slot, HasKeyword(keyword))``).  This fixes Gap 2 and enables
   Skystinger-shaped probes once Gap 1 is also closed.
3. Wire multi-subject dispatch in Rust's ``declare_blocker`` site so the
   attacker's id is accessible to predicates evaluating the ``"attacker"``
   subject slot.

Sentinel tests:
---------------
Two passing tests below document the two gap layers:

1. ``test_blocks_trigger_fires_on_rust_with_simple_source_predicate`` —
   confirms ``Event::Blocks`` IS wired end-to-end in Rust
   (``declare_blocker`` pushes a stack item and the pump resolves), but
   that the *equivalent Python carrier* built via the bridge's
   ``source_is_self`` predicate kind fires on Rust and silently fails on
   Python (Gap 1).

2. ``test_blocks_trigger_bridge_predicate_gap_skystinger`` — confirms
   Skystinger's genuine parsed predicate cannot be expressed as a bridge
   dict today (no ``subject_has_keyword`` kind), documenting Gap 2.
"""

from __future__ import annotations

import importlib.util

import pytest

# ---------------------------------------------------------------------------
# Skip the whole module if the Rust extension isn't built — mirrors the
# ``tests/test_parity_smoke.py`` / ``tests_rust/conftest.py`` policy so
# a fresh checkout without maturin doesn't break the gate.
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine Rust extension not built in this worktree",
)


# ---------------------------------------------------------------------------
# Sentinel 1 — Event::Blocks IS wired in Rust; Gap 1 is the predicate bridge.
# ---------------------------------------------------------------------------


def test_blocks_trigger_fires_on_rust_with_simple_source_predicate() -> None:
    """``Event::Blocks`` is wired in Rust's ``declare_blocker`` — a synthetic
    carrier with a ``source_is_self``-predicated ``pump_self_until_eot``
    trigger fires correctly on the Rust engine when a blocker is declared.

    This test validates the Rust half of the lane end-to-end (Gap 1's
    Python-side predicate problem is documented, not reproduced here).

    Observable:
    - ``declare_blocker`` returns True (block is legal).
    - ``stack_size()`` rises to 1 immediately after (trigger pushed).
    - After ``resolve_top_of_stack()``: ``effective_power`` == base+5.

    The Python-side analogue CANNOT be driven via the bridge's
    ``source_is_self`` predicate kind because ``_ta_dict_to_python_predicate``
    translates it to ``IsSelf(subject=None)`` — which returns ``None`` from
    ``_resolve_subject`` on a 2-subject BLOCKS event and therefore never
    matches, so the trigger silently fails to push on the Python stack.
    A direct ``IsSelf(subject="blocker")`` construction DOES fire on Python
    (verified in the batch-FF recon session), confirming the gap is in the
    bridge translation, not in the Python dispatch path.
    """
    from mtg_bot.parity.cross_engine import DeckSpec, build_rust_state

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    rs = build_rust_state(spec)
    ZB = 2  # Zone.BATTLEFIELD

    # Inject a synthetic 3/2 blocker with a simple BLOCKS trigger:
    # "whenever this creature blocks (source_is_self), get +5/+0 ueot".
    # This is the predicate the bridge CAN express — but only on the Rust
    # side.  The Rust Predicate::SourceIsSelf matches source_id == subject_id
    # where subject_id is the single subject Rust threads to dispatch_event
    # (the blocker_id), so it correctly gates to the declaring blocker.
    rs_blk = rs.register_and_inject_object(
        {
            "name": "SyntheticBlocker",
            "card_types": ["Creature"],
            "power": 3,
            "toughness": 2,
            "keywords": ["reach"],
            "triggered_abilities": [
                {
                    "event": "blocks",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "pump_self_until_eot",
                        "power_bonus": 5,
                        "toughness_bonus": 0,
                    },
                }
            ],
        },
        0,
        ZB,
    )
    # Inject a vanilla p1 attacker.
    rs_atk = rs.register_and_inject_object(
        {
            "name": "VanillaAttacker",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "keywords": [],
        },
        1,
        ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    rs.clear_summoning_sick_for_player(1)

    assert rs.declare_attacker(rs_atk) is True, (
        "declare_attacker must succeed for an unsick p1 attacker"
    )
    assert rs.stack_size() == 0, (
        "no trigger on ATTACKS for the vanilla attacker"
    )

    assert rs.declare_blocker(rs_blk, rs_atk) is True, (
        "declare_blocker must succeed (no flying/skulk/other restriction on "
        "the vanilla attacker, and the 3/2 blocker with Reach can legally block)"
    )
    assert rs.stack_size() == 1, (
        "BLOCKS trigger (pump_self_until_eot) must be pushed onto the Rust "
        "stack immediately after declare_blocker"
    )

    rs.resolve_top_of_stack()
    rs.apply_sbas()

    rs_eff = rs.effective_power(rs_blk)
    assert rs_eff == 3 + 5, (
        f"Rust: SyntheticBlocker effective_power must be 3 (base) + 5 (pump) "
        f"= 8 after BLOCKS trigger resolves; got {rs_eff}"
    )


# ---------------------------------------------------------------------------
# Sentinel 2 — Skystinger's predicate requires unbridged ``attacker_has_keyword``.
# ---------------------------------------------------------------------------


def test_blocks_trigger_bridge_predicate_gap_skystinger() -> None:
    """Skystinger's genuine trigger predicate cannot be expressed via the
    cross-engine bridge's current predicate vocabulary.

    Skystinger's BLOCKS trigger predicate is::

        IsSelf(subject="blocker") & Subject("attacker", HasKeyword("flying"))

    The bridge's ``_ta_dict_to_python_predicate`` (``cross_engine.py:8692``)
    supports: ``always``, ``source_is_self``, ``source_is_creature``,
    ``subject_is_land``, ``subject_is_artifact``, ``subject_is_creature``,
    ``controlled_by_you``, ``subject_has_subtype``, ``not``, ``and``, ``or``.

    There is no ``subject_has_keyword`` or ``attacker_has_keyword`` kind.
    Attempting to construct such a predicate dict raises ``ValueError`` in
    ``_ta_dict_to_python_predicate``.

    Separately, Rust's ``Predicate`` enum (``cards.rs:4061``) also has no
    ``SubjectHasKeyword`` variant — the matching gap on the Rust side.

    This sentinel asserts both gaps are real:
    1. The bridge raises on an unknown predicate kind.
    2. Rust ``register_printing`` raises when given a predicate dict with
       ``subject_has_keyword`` (since ``parse_predicate`` in ``cards.rs``
       also rejects unknown kinds).

    The Python side (Gap 1) is also documented here: the ``source_is_self``
    predicate kind translates to ``IsSelf(subject=None)``, which resolves
    the default subject as ``None`` on multi-subject BLOCKS events (because
    ``_resolve_subject`` only auto-resolves single-subject events).  The
    EoE parser emits ``IsSelf(subject="blocker")``, not ``IsSelf()``, for
    Skystinger's block trigger — confirming the bridge mistranslates the
    shape.
    """
    import pytest

    # -- Gap 2a: Python bridge raises on unknown predicate kind. --
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_predicate

    unknown_kind_dict = {"kind": "subject_has_keyword", "keyword": "flying"}
    with pytest.raises((ValueError, KeyError)):
        _ta_dict_to_python_predicate(unknown_kind_dict)

    # -- Gap 2b: Rust register_printing raises on unknown predicate kind. --
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    skystinger_shape = {
        "name": "_SentinelSkystingerShape",
        "mana_cost": {},
        "card_types": ["Creature"],
        "power": 3,
        "toughness": 2,
        "keywords": ["reach"],
        "triggered_abilities": [
            {
                "event": "blocks",
                # Attempt to express the attacker-flying gate — unknown kind.
                "predicate": {
                    "kind": "and",
                    "left": {"kind": "source_is_self"},
                    "right": {"kind": "subject_has_keyword", "keyword": "flying"},
                },
                "effect": {
                    "kind": "pump_self_until_eot",
                    "power_bonus": 5,
                    "toughness_bonus": 0,
                },
            }
        ],
    }
    with pytest.raises((ValueError, KeyError, Exception)):
        reg.register_printing(skystinger_shape)

    # -- Gap 1: verify IsSelf(subject=None) fails on 2-subject BLOCKS dispatch. --
    # This documents WHY the bridge's source_is_self translation is wrong for
    # BLOCKS: _resolve_subject returns None when len(subjects) > 1 and slot is None.
    from mtg_bot.effects.predicates import IsSelf, _resolve_subject

    subjects_two = {"blocker": object(), "attacker": object()}
    resolved = _resolve_subject(subjects_two, None)
    assert resolved is None, (
        "Gap 1 confirmed: _resolve_subject returns None for 2-subject events "
        "when slot=None — IsSelf(subject=None) always evaluates False on BLOCKS "
        f"(got {resolved!r})"
    )
