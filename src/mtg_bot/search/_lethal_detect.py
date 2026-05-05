"""Lethal-detect heuristic: identify guaranteed-win alpha-strike
positions and short-circuit search by emitting the winning attack
directly.

The heuristic only fires in CLEAN cases — see ``detect_lethal_attack``
docstring for the conservative gates. False positives (declaring lethal
when the attack wouldn't actually kill) are catastrophic (the bot
commits to attacks and loses); false negatives (missing real lethal,
falling through to search) are merely a missed opportunity. **Every
gate here errs toward false negatives** — when in doubt, abort.

Why this exists
---------------

The fix is two-fold:

1. **Per-game wall savings.** Search budget for the win-pathing turn
   is reused on earlier (more uncertain) decisions instead of being
   burned on a position whose answer is "attack with everything that
   produces lethal." Typical alpha-strike turns hit 5-10
   declare-attacker sub-decisions; the heuristic short-circuits all
   of them.

2. **Training signal quality.** When fired, the value target
   collapses to +1.0 with confidence and the policy target
   concentrates on the lethal subset. Cleaner end-game gradients
   than the search-derived distribution, which spreads value mass
   over visited variants.

The bypass lives upstream of MCTS in ``ISMCTS.choose_with_visits`` —
when called at a "first attacker decision" priority moment AND the
heuristic detects lethal, the search loop is skipped entirely and a
single ``AttackerDecision(attack=True)`` decision is returned for the
head of the pending-attacker queue. The follow-up attacker decisions
are handled by the next ``choose_with_visits`` call(s); each one in
turn is checked against the lethal subset and routed without search.

Algorithm
---------

Given the gates pass and we have eligible attackers vs eligible
blockers, opp will pick blocks AFTER we declare. To compute the
guaranteed-minimum face damage, assume opp blocks our BIGGEST attackers
(maximizing damage soaked into combat): with N attackers and M
blockers (M <= N), opp blocks the M largest, leaving the N-M
smallest unblocked. Their summed power is the face damage.

Lethal threshold:

    sum_of_smallest_(N-M)_powers >= opp_life + lifelink_lifegain

where lifelink_lifegain accounts for opp blockers with lifelink
(they can deal up to their power in damage to whatever they block,
gaining that much life back conservatively).

If the threshold is met, every eligible attacker is included in the
returned subset — sending all maximizes unblocked damage, which is
exactly what we need for a guaranteed kill. (Sending fewer ALWAYS
yields equal-or-fewer unblocked attackers, never more.)
"""

from __future__ import annotations

from typing import Optional

from mtg_bot.combat import eligible_attackers, eligible_blockers
from mtg_bot.effects.generic.become_type import BecomeLandCreatureUEOT
from mtg_bot.game import (
    GameObject,
    GameState,
    effective_keywords,
    effective_power,
    effective_triggered_abilities,
    is_creature_now,
)


# Effect classes that — when found on an activated ability of a
# noncreature opp permanent — represent self-animation (the permanent
# turns itself into a creature, typically until end of turn). If opp
# controls a noncreature permanent with one of these as a top-level
# activated-ability effect, the heuristic aborts: opp could animate the
# permanent into a blocker mid-combat (e.g. a manland like Mishra's
# Factory, Mutavault) and soak our lethal attacker.
#
# Currently only ``BecomeLandCreatureUEOT`` qualifies (the engine's
# only self-animation effect class). Forward compatibility note: any
# future Effect class that animates the source permanent into a
# creature (e.g. an artifact-animator, a permanent-becomes-creature
# effect that doesn't ride the land path) must be added to this tuple
# or the gate will silently let it through. We check ``isinstance(...)``
# at the TOP LEVEL of ``ability.effect`` only — wrapping in
# ``ApplyEffect`` is uncommon for ``BecomeLandCreatureUEOT`` (per its
# docstring, the class itself composes ``ApplyEffect(BecomeType(...))``
# internally).
_SELF_ANIMATION_EFFECT_CLASSES: tuple[type, ...] = (
    BecomeLandCreatureUEOT,
)


# Keywords that — if present on opp's blockers — break the simple
# math the heuristic uses. We abort rather than try to reason
# accurately about them.
_DISRUPTIVE_BLOCKER_KEYWORDS: frozenset[str] = frozenset({
    "first_strike", "first strike",
    "double_strike", "double strike",
    "indestructible",
    "hexproof",
    "shroud",
})


# Triggered-ability events that fire on combat-related transitions.
# If opp's permanents have any trigger keyed on these events, the
# heuristic aborts — those triggers might disrupt the kill (e.g.
# "whenever a creature attacks you, gain 5 life", "whenever this
# creature is dealt damage, you may pay 2 to prevent it").
_COMBAT_TRIGGER_EVENTS: frozenset[str] = frozenset({
    "attacks", "blocks",
    "deals_combat_damage", "dealt_damage",
})


# Mana-only effect class names. Activated abilities whose effect is
# one of these are treated as inert for combat-disruption purposes
# (opp can produce mana but with empty hand and no other targets,
# the mana goes nowhere). Anything else triggers the abort.
_MANA_ONLY_EFFECT_CLASSES: frozenset[str] = frozenset({
    "AddMana",
    "AddManaChosenColor",
    "AddManaProduceTapped",
    "AddManaOfAnyColor",
    "AddTwoMana",
})


def _has_problematic_blocker_keywords(
    state: GameState, obj: GameObject,
) -> bool:
    """Return True if ``obj`` has any keyword that breaks the simple
    alpha-strike math (first/double strike, indestructible,
    hexproof / shroud)."""
    kws = effective_keywords(state, obj)
    return bool(kws & _DISRUPTIVE_BLOCKER_KEYWORDS)


def _opp_has_combat_triggers(
    state: GameState, opp_id: int,
) -> bool:
    """Return True if opp controls any permanent with a triggered
    ability fired by combat events. Conservative — we don't try to
    reason about whether the trigger could disrupt our kill."""
    for o in state.battlefield:
        if o.controller_id != opp_id:
            continue
        for trig in effective_triggered_abilities(state, o):
            event_obj = getattr(trig, "event", None)
            if event_obj is not None:
                event_value = getattr(event_obj, "value", None)
                if event_value in _COMBAT_TRIGGER_EVENTS:
                    return True
            string_key = getattr(trig, "trigger", "") or ""
            if string_key:
                if string_key in _COMBAT_TRIGGER_EVENTS:
                    return True
                # Common engine string keys for combat-relevant
                # triggers (defensive — string-key naming isn't
                # exhaustively enumerated in our codebase).
                if string_key in (
                    "attack", "block",
                    "deals_damage", "is_dealt_damage",
                    "combat_damage",
                ):
                    return True
    return False


def _opp_has_non_mana_activated_ability(
    state: GameState, opp_id: int,
) -> bool:
    """Return True if opp controls any permanent with an activated
    ability whose effect is something other than producing mana.
    Mana-only abilities are fine; anything else is treated as
    potentially disruptive and aborts the heuristic.
    """
    from mtg_bot.game import effective_activated_abilities
    for o in state.battlefield:
        if o.controller_id != opp_id:
            continue
        for ab in effective_activated_abilities(state, o):
            effect = getattr(ab, "effect", None)
            effect_class = type(effect).__name__ if effect else ""
            if effect_class in _MANA_ONLY_EFFECT_CLASSES:
                continue
            # If we can't classify it as mana-only, assume disruptive.
            return True
    return False


def _opp_has_self_animator_permanent(
    state: GameState, opp_id: int,
) -> bool:
    """Return True if opp controls a noncreature permanent whose
    printing has an activated ability that animates the permanent into
    a creature (e.g. a manland like Mishra's Factory, Mutavault).

    A noncreature permanent that can animate itself mid-combat into a
    blocker breaks the "fixed eligible-blocker set" assumption the
    heuristic relies on: we'd commit to attack-everything based on the
    current blockers, then opp animates a fresh blocker, soaks our
    smallest unblocked attacker, and we lose. Conservative-ABORT.

    Walks ``obj.printing.activated_abilities`` directly (rather than
    ``effective_activated_abilities``) — printed text is the source of
    truth for "can this permanent become a creature." Skips mana
    abilities (``is_mana_ability=True``) since those don't animate.
    Checks ``isinstance(ability.effect, ...)`` at top level only;
    ``ApplyEffect``-wrapped variants are uncommon for the relevant
    class per its docstring.
    """
    for o in state.battlefield:
        if o.controller_id != opp_id:
            continue
        # Already-creature permanents are handled by the existing
        # blocker-keyword / blocker-count gates downstream — only the
        # NONcreature case represents a hidden blocker that could be
        # summoned mid-combat. ``is_creature_now`` covers natively-
        # creature printings, stationed Spacecraft, and already-
        # animated permanents whose UEOT cache is still set.
        if is_creature_now(o):
            continue
        for ability in o.printing.activated_abilities:
            if ability.is_mana_ability:
                continue
            if isinstance(
                ability.effect, _SELF_ANIMATION_EFFECT_CLASSES,
            ):
                return True
    return False


def _opp_can_disrupt(
    state: GameState, opp_id: int,
) -> bool:
    """Return True if opp could plausibly disrupt the alpha strike.
    Combines: empty hand, no non-mana activated abilities, no
    combat-triggered abilities, no noncreature permanent that can
    animate itself into a blocker.

    The "tapped out" piece is implicit: even if opp has untapped
    lands, with empty hand and no instant-speed activated abilities,
    the mana has nothing to spend on. Any non-mana activated ability
    on an untapped permanent is caught by the
    ``_opp_has_non_mana_activated_ability`` check.
    """
    p = state.player_by_id(opp_id)

    # Empty hand — no instants, sorceries, or flash spells to cast.
    if p.hand:
        return True

    # No combat-triggered abilities anywhere on opp's side.
    if _opp_has_combat_triggers(state, opp_id):
        return True

    # No non-mana activated abilities anywhere on opp's side.
    if _opp_has_non_mana_activated_ability(state, opp_id):
        return True

    # No noncreature permanent that could animate itself into a
    # blocker mid-combat (manland-style).
    if _opp_has_self_animator_permanent(state, opp_id):
        return True

    return False


def _powers_from_lifelink_blockers(
    state: GameState, blockers: list[GameObject],
) -> int:
    """Sum the effective power of every blocker with lifelink.
    Conservatively counts max possible damage that gets back to opp
    through lifelink. (If a blocker has lifelink and deals damage to
    our blocked attacker, opp gains that much life — meaning our
    sum-of-power needs to clear opp_life PLUS the lifelink lifegain.)
    """
    total = 0
    for b in blockers:
        kws = effective_keywords(state, b)
        if "lifelink" in kws:
            total += max(0, effective_power(state, b))
    return total


def detect_lethal_attack(
    state: GameState, player_id: int,
) -> Optional[set[int]]:
    """Detect a guaranteed-lethal alpha-strike attack subset for
    ``player_id``. Returns the set of attacker creature ids whose
    attack produces lethal damage to the opp this combat, or
    ``None`` if no guaranteed lethal is detected.

    Conservative — fires only when ALL of these hold:

    - Exactly one opponent (multi-opp not modeled).
    - Opp has empty hand.
    - Opp has no non-mana activated abilities on any permanent.
    - Opp has no triggered abilities keyed on combat events.
    - Opp controls no noncreature permanent with a self-animation
      activated ability (manland-style — would otherwise animate into
      a blocker mid-combat).
    - None of opp's blockers have first/double strike, indestructible,
      hexproof, or shroud.
    - Active player has at least one untapped creature eligible to
      attack.
    - With opp blocking our biggest attackers, the unblocked total
      power (plus lifelink lifegain accounting) >= opp_life_total.

    Returns ``None`` if any gate fails. Returns a set of attacker
    ids (subset of ``eligible_attackers(state, player_id)``) when
    lethal is detected. Today the returned set is ALWAYS the full
    eligible-attacker set when lethal — sending all maximizes
    unblocked damage; sending fewer would only reduce it.

    Time budget target: < 100us per call. Implementation is O(opp's
    permanents + active's eligible attackers + opp's blockers).
    """
    # Single-opp gate. Multi-opp lethal would need separate accounting
    # for each opponent's life total.
    alive_opps = [
        p for p in state.players
        if p.id != player_id and not p.has_lost
    ]
    if len(alive_opps) != 1:
        return None
    opp = alive_opps[0]
    opp_id = opp.id

    if opp.life <= 0:
        # Already losing — heuristic doesn't fire (SBAs handle it).
        return None

    # Disruption gates.
    if _opp_can_disrupt(state, opp_id):
        return None

    # Attacker / blocker enumeration.
    attackers = eligible_attackers(state, player_id)
    if not attackers:
        return None

    blockers = eligible_blockers(state, opp_id)

    # Problematic blocker keywords.
    for b in blockers:
        if _has_problematic_blocker_keywords(state, b):
            return None

    # Compute the unblocked-power sum assuming opp blocks our biggest
    # attackers. Sort attacker powers descending, drop the first
    # ``len(blockers)`` (the ones that get blocked), sum the rest.
    powers_desc = sorted(
        (max(0, effective_power(state, a)) for a in attackers),
        reverse=True,
    )
    n_blockers = len(blockers)
    unblocked_powers = powers_desc[n_blockers:]
    if not unblocked_powers:
        return None
    unblocked_total = sum(unblocked_powers)

    # Lifelink contribution: blockers with lifelink could gain opp
    # life back when they deal damage to our blocked attackers.
    lifelink_gain = _powers_from_lifelink_blockers(state, blockers)

    # Lethal threshold: unblocked face damage must clear opp's life
    # AFTER they recover lifelink. Exact equality kills (opp goes
    # to 0 life and SBAs lose them).
    threshold = opp.life + lifelink_gain
    if unblocked_total < threshold:
        return None

    # Lethal! Send all eligible attackers — opp blocks the biggest
    # ones, the smaller ones (which are what produced the
    # unblocked-total above) reach face. Sending fewer would only
    # reduce unblocked damage.
    return {a.id for a in attackers}


__all__ = ["detect_lethal_attack"]
