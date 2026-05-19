"""Batch CC: combat-damage trigger lane recon — substrate gap documented.

This module is the round-8 COMBAT_DAMAGE pivot probe batch.  The directive
asked for 2–4 genuine real-EoE byte-equality probes for cards whose primary
mechanic is a ``DEALS_COMBAT_DAMAGE``-family trigger.

SUBSTRATE-GAP FINDING — zero probes shipped.
============================================

All three EoE cards with combat-damage triggers are blocked by a two-layer
substrate gap that makes byte-equal cross-engine probes structurally
impossible at this HEAD:

1. **Rust parse gate** — ``rust/src/cards.rs:parse_triggered_ability``
   explicitly raises on the ``"deals_damage"`` event string::

       "deals_damage" => {
           return Err(PyValueError::new_err(format!(
               "triggered_ability.event {event_str:?} is not yet wired in Slice 9; \
                only \"enters\", \"dies\", \"cast\", \"attacks\", \"blocks\", \
                \"leaves_battlefield\", and \"becomes_tapped\" dispatch today"
           )));
       }

   Any attempt to build a Rust ``GameState`` that includes a card with a
   ``DEALS_COMBAT_DAMAGE`` triggered ability will raise ``PyValueError``
   at registry construction time.

2. **Cross-engine bridge** — ``src/mtg_bot/parity/cross_engine.py``
   (``_ta_dict_to_python_triggered_ability``, line ≈ 8798) handles
   ``"enters"``, ``"dies"``, ``"cast"``, ``"attacks"``, ``"blocks"``,
   ``"leaves_battlefield"``, and ``"becomes_tapped"``.  It has no
   ``"deals_combat_damage"`` arm — the else-branch raises::

       raise ValueError(
           f"cross_engine triggered_abilities bridge: event "
           f"{event_str!r} is not yet wired"
       )

3. **Rust dispatch site** — ``Event::DealsDamage`` exists as an enum
   variant in ``rust/src/cards.rs:4000`` but carries the inline
   comment "no dispatch site yet" (deferred to Slice 12+).  Even if
   the parse gate and bridge were wired today, the trigger would never
   fire on the Rust side.

EoE combat-damage candidate inventory (exhaustive):
----------------------------------------------------
All three cards match "deals combat damage" in their oracle text.  None
have an existing ``test_cross_engine_real_eoe_<slug>`` probe.

* **Illvoi Infiltrator** — "Whenever this creature deals combat damage to a
  player, draw a card."  ``Event.DEALS_COMBAT_DAMAGE`` with
  ``IsSelf(subject="source") & IsPlayer(subject="target")``,
  effect ``DrawCards(1)``.  Blocked by gaps 1+2+3 above.

* **Starwinder** — "Whenever a creature you control deals combat damage to a
  player, you may draw that many cards."  ``Event.DEALS_COMBAT_DAMAGE``
  with an aggregated-per-controller shape; effect
  ``DrawCardsEqualToResolving CombatDamage`` (optional).  Blocked by
  gaps 1+2+3 above.

* **Virulent Silencer** — "Whenever a nontoken artifact creature you control
  deals combat damage to a player, that player gets two poison counters."
  ``Event.DEALS_COMBAT_DAMAGE`` with
  ``IsCreature() & IsArtifact() & IsNontoken()`` on the source; effect
  ``PutPoisonCountersOnTargetPlayer(2)``.  Blocked by gaps 1+2+3 above.

What unblocks the lane:
-----------------------
Wire ``"deals_damage"`` / ``"deals_combat_damage"`` in the Rust
``parse_triggered_ability`` function, add a dispatch fan-out inside
``deal_combat_damage`` (``state_ops_combat.rs``) that mirrors Python's
``_fire_combat_damage_to_player_triggers``, and add the
``"deals_combat_damage"`` arm to the cross-engine bridge in
``cross_engine.py``.  That is Slice 12 scope per the in-code comments.

Sentinel test:
--------------
The single ``test_combat_damage_trigger_lane_blocked`` test below is a
passing sentinel that asserts the gap is real (the Rust parse gate raises
on ``"deals_damage"``) and flags this file as a lane-recon result rather
than an empty file.
"""

import pytest


# ---------------------------------------------------------------------------
# Sentinel: verify the substrate gap is real and document it clearly.
# ---------------------------------------------------------------------------


def test_combat_damage_trigger_lane_blocked() -> None:
    """Substrate now wired; see deals_combat_damage_unlock probe.

    Round-13 wired the ``"deals_damage"`` event string in both the Rust
    parse gate (``cards.rs::parse_triggered_ability``) and the dispatch
    site (``state_ops_combat.rs::apply_damage_pass`` via
    ``dispatch_combat_damage_to_player``).  The gap documented in this
    module's docstring no longer exists at this HEAD.

    The real cross-engine parity probe for Illvoi Infiltrator lives in
    ``tests/test_probe_deals_combat_damage_unlock.py``.
    """
    pytest.skip(
        "substrate now wired (round-13); "
        "see test_probe_deals_combat_damage_unlock.py"
    )
