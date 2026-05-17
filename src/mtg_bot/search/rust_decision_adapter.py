"""Non-vestigial Rust-dict <-> search-``Decision`` adapter (B3-S2 codec
seam helper, introduced by B3-S1 for the provider).

This is the small, **non-vestigial** bidirectional mapping the B3 wiring
spec (``docs/NN_RUST_DECISION_SOURCING_WIRING_DESIGN.md`` §3.2) calls
for. It deliberately does NOT reuse
``mtg_bot.parity.cross_engine._dict_to_python_action``: that symbol is
classified VESTIGIAL by ``docs/BRIDGE_VESTIGIALIZATION_PLAN.md`` §2.2
(it is part of the reverse-serialization path retired at Step 6).
Building B3 on a Step-6-doomed symbol would invert the retirement
order, so the provider owns this mapping outright.

The mapping is mechanical because the Rust ``legal_decisions`` dict
``kind`` + ids map 1:1 to the codec's ``mtg_bot.actions.Action``
classes (the same ``Action`` constructors the codec's own ``decode``
builds at ``action_encoding.py:774-802``).

**VERIFY-FIRST RE-ANCHOR (live ``main 18729610``).** The B3 wiring
spec §2.2 stated the play_land/cast_spell key was ``"id"``. The LIVE
Rust surface emits **``"card_id"``** (``state_ops_legal.rs:485-489`` /
``:504-513``) and the strict apply-side parser
(``rust/src/actions.rs:parse_action``) ``require``s exactly
``"card_id"`` for play_land/cast_spell, ``"source_id"`` +
``"ability_index"`` for activate_ability (plus optional
``"target_creature_id"`` / ``"sacrifice_target_id"``), and
``"attacker_id"``/``"attack"`` / ``"blocker_id"``/``"attacker_id"``
for the G1 factored combat kinds. The code wins over the spec prose
(the round-67-class lesson); this adapter speaks the LIVE canonical
keys so the dict round-trips through ``rust_state.apply_action``:

* ``pass_priority``    <-> ``PassPriority()``
* ``play_land``        <-> ``PlayLand(card_id=d["card_id"])``
* ``cast_spell``       <-> ``CastSpell(card_id=d["card_id"], use_warp=...,
                           kicked=..., cast_for_free=...,
                           use_impending=..., cast_room_half=...)``
* ``activate_ability`` <-> ``ActivateAbility(source_id=d["source_id"],
                           ability_index=d["ability_index"])``  —
                           ``target_creature_id`` /
                           ``sacrifice_target_id`` round-trip through
                           the dict (the Python ``ActivateAbility``
                           dataclass carries only source/index; the
                           cost/target ids are resolved engine-side,
                           so they are preserved on the dict for the
                           apply round-trip but not lifted into the
                           Decision — they re-derive identically from
                           the Rust state at apply).
* ``attacker_decision``<-> ``AttackerDecision(attacker_id=..., attack=...)``
* ``blocker_decision`` <-> ``BlockerDecision(blocker_id=..., attacker_id=...)``
* ``declare_attackers``<-> ``DeclareAttackers(attacker_ids=frozenset(...))``
* ``declare_blockers`` <-> ``DeclareBlockers(assignments=((b,a),...))``

The combat factored kinds (``attacker_decision`` /
``blocker_decision``) are the byte-compatible per-creature shape G1
(merged ``f5c11231``) made Rust ``legal_decisions`` emit; the
whole-action ``declare_attackers`` / ``declare_blockers`` shapes are
what ``rust_state.apply_action`` accepts as the finalized combat
declaration (the B3-S3 provider accumulates the factored decisions and
finalizes through ``decision_to_rust_dict``).

ID-key contract: Rust's ``parse_action`` is **strict** (canonical key
only — ``id`` for play_land/cast_spell, ``source_id`` for
activate_ability, the combat-specific keys). Unlike the vestigial
``_dict_to_python_action`` we do NOT honor cross-vocabulary aliases:
this mapping is the post-flip path where the dict must round-trip
through ``rust_state.apply_action`` cleanly, so it speaks only the
canonical Rust key shape.
"""

from __future__ import annotations

from typing import Any

from mtg_bot.actions import (
    ActivateAbility, CastSpell, DeclareAttackers, DeclareBlockers,
    PassPriority, PlayLand,
)
from mtg_bot.search.combat_decisions import (
    AttackerDecision, BlockerDecision,
)
from mtg_bot.search.protocol import Decision


class UnsupportedRustDecisionKind(ValueError):
    """A Rust ``legal_decisions`` dict carried a ``kind`` the provider
    cannot map to a search ``Decision`` (or vice versa). Raised loudly
    rather than silently dropped — a new Rust decision shape that this
    adapter does not yet model is a scoped gap to surface, never to
    paper over (``feedback_no_fallback_hybrids`` /
    ``feedback_silent_noop_pipelines``)."""


def rust_dict_to_decision(d: dict) -> Decision:
    """Map one Rust ``legal_decisions`` dict to a search ``Decision``.

    The inverse of the codec's own ``decode``-time ``Action``
    construction — same ``Action`` classes, fed from a Rust dict
    instead of a Python policy slot.
    """
    kind = d.get("kind")
    if kind == "pass_priority":
        return PassPriority()
    if kind == "play_land":
        return PlayLand(card_id=int(d["card_id"]))
    if kind == "cast_spell":
        # The exact shape state_ops_legal.rs emits + actions.rs
        # action_to_pydict round-trips (live key = "card_id").
        # Defaults mirror the CastSpell dataclass so a minimal dict
        # decodes to a vanilla cast.
        return CastSpell(
            card_id=int(d["card_id"]),
            use_warp=bool(d.get("use_warp", False)),
            kicked=bool(d.get("kicked", False)),
            cast_for_free=bool(d.get("cast_for_free", False)),
            use_impending=bool(d.get("use_impending", False)),
            cast_room_half=d.get("cast_room_half", None),
        )
    if kind == "activate_ability":
        # The Python ActivateAbility dataclass carries only
        # source_id + ability_index; target_creature_id /
        # sacrifice_target_id are engine-resolved (None on the
        # loader-admitted / pre-Slice-4 surface — Equipment-equip /
        # sacrifice-self abilities are loader-DECLINED, C6-fenced).
        return ActivateAbility(
            source_id=int(d["source_id"]),
            ability_index=int(d["ability_index"]),
        )
    if kind == "attacker_decision":
        return AttackerDecision(
            attacker_id=int(d["attacker_id"]),
            attack=bool(d["attack"]),
        )
    if kind == "blocker_decision":
        atk = d.get("attacker_id", None)
        return BlockerDecision(
            blocker_id=int(d["blocker_id"]),
            attacker_id=None if atk is None else int(atk),
        )
    if kind == "declare_attackers":
        return DeclareAttackers(
            attacker_ids=frozenset(
                int(i) for i in d.get("attacker_ids", ())
            )
        )
    if kind == "declare_blockers":
        return DeclareBlockers(
            assignments=tuple(
                (int(pair[0]), int(pair[1]))
                for pair in d.get("assignments", ())
            )
        )
    raise UnsupportedRustDecisionKind(
        f"rust_dict_to_decision: unsupported kind {kind!r} "
        f"(dict: {d!r})"
    )


def decision_to_rust_dict(decision: Decision) -> dict[str, Any]:
    """Map a search ``Decision`` to a Rust ``apply_action`` dict.

    Mirrors ``rust/src/actions.rs:action_to_pydict``'s key shape so it
    round-trips cleanly through ``rust_state.apply_action`` (canonical
    keys only — no alias honoring). The combat factored decisions map
    to their per-creature kinds; the provider finalizes accumulated
    combat into the whole-action ``declare_attackers`` /
    ``declare_blockers`` shape via the dedicated builders below.
    """
    if isinstance(decision, PassPriority):
        return {"kind": "pass_priority"}
    if isinstance(decision, PlayLand):
        return {"kind": "play_land", "card_id": int(decision.card_id)}
    if isinstance(decision, CastSpell):
        return {
            "kind": "cast_spell",
            "card_id": int(decision.card_id),
            "use_warp": bool(decision.use_warp),
            "kicked": bool(decision.kicked),
            "cast_for_free": bool(decision.cast_for_free),
            "use_impending": bool(decision.use_impending),
            "cast_room_half": decision.cast_room_half,
        }
    if isinstance(decision, ActivateAbility):
        # target_creature_id / sacrifice_target_id default None — the
        # pre-Slice-4 shape, which is the loader-admitted surface
        # (Equipment-equip / sacrifice-self are loader-DECLINED,
        # C6-fenced). parse_action treats a missing key as None.
        return {
            "kind": "activate_ability",
            "source_id": int(decision.source_id),
            "ability_index": int(decision.ability_index),
            "target_creature_id": None,
            "sacrifice_target_id": None,
        }
    if isinstance(decision, AttackerDecision):
        return {
            "kind": "attacker_decision",
            "attacker_id": int(decision.attacker_id),
            "attack": bool(decision.attack),
        }
    if isinstance(decision, BlockerDecision):
        return {
            "kind": "blocker_decision",
            "blocker_id": int(decision.blocker_id),
            "attacker_id": (
                None if decision.attacker_id is None
                else int(decision.attacker_id)
            ),
        }
    if isinstance(decision, DeclareAttackers):
        return {
            "kind": "declare_attackers",
            "attacker_ids": sorted(
                int(i) for i in decision.attacker_ids
            ),
        }
    if isinstance(decision, DeclareBlockers):
        return {
            "kind": "declare_blockers",
            "assignments": [
                [int(b), int(a)] for (b, a) in decision.assignments
            ],
        }
    raise UnsupportedRustDecisionKind(
        f"decision_to_rust_dict: unsupported decision "
        f"{type(decision).__name__}: {decision!r}"
    )


def declare_attackers_dict(attacker_ids) -> dict[str, Any]:
    """Build the whole-action ``declare_attackers`` dict Rust's
    ``apply_action`` accepts as the finalized attacker declaration
    (the B3-S3 provider calls this after accumulating per-attacker
    ``AttackerDecision``s)."""
    return {
        "kind": "declare_attackers",
        "attacker_ids": sorted(int(i) for i in attacker_ids),
    }


def declare_blockers_dict(assignments) -> dict[str, Any]:
    """Build the whole-action ``declare_blockers`` dict Rust's
    ``apply_action`` accepts as the finalized blocker declaration.

    ``assignments`` is an iterable of ``(blocker_id, attacker_id)``
    pairs (the same shape ``DeclareBlockers.assignments`` carries)."""
    return {
        "kind": "declare_blockers",
        "assignments": [
            [int(b), int(a)] for (b, a) in assignments
        ],
    }
