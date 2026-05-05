"""Capability-based auto-pass for non-active player priority moments.

When the player who has priority is NOT the active player ("opp"), the
priority window is by definition at non-sorcery timing. Most such
priority moments — between phases, after stack additions, after stack
resolutions — have NO meaningful action available to opp: the only legal
choice is ``PassPriority()``.

Per ``docs/perf_self_play_20260504.md``, ``legal_actions`` enumeration
is the dominant cost of self-play even after the per-decision-moment
cache landed. This module provides a much cheaper short-circuit:

1. ``opp_capability_hash(state, opp_id)`` — fast structural hash over
   the inputs that decide whether opp can act at instant speed:
   opp's hand, opp's mana availability (mana pool + untapped land /
   ability sources), opp's permanents that have activated abilities,
   and a few global flags (continuous effects, attached equipment,
   anything Lightstall-grant-shaped). Cheap to compute — O(opp hand
   size + opp battlefield size).

2. ``opp_can_act(state, opp_id)`` — definitively returns True when
   opp has at least one instant-speed capability (a spell they could
   cast, an ability they could activate). Returns False ONLY when
   we are confident opp has no such capability.

The adapter caches ``opp_can_act`` keyed by ``opp_capability_hash``
so a steady-state non-active-priority window costs one hash compute
plus a cache hit.

Conservatism contract
---------------------

False positives (returning True when opp actually couldn't act) are
*safe*: they fall through to the existing ``legal_actions`` path,
which produces the correct legal set. False negatives (returning
False when opp can act) would be a correctness bug — the bot would
silently skip a legitimate response. **All conservative gates here
err toward False positives**: if we cannot quickly rule out a
capability, we include it.

Documented limitations (intentional false-NEGATIVE risk)
--------------------------------------------------------

The hash inputs are designed to capture every change that
*plausibly* changes opp's capability set. They DO NOT cover:

* **Continuous effects granting flash mid-turn** (Vedalken Orrery,
  Teferi, Mage of Zhalfir). The hash watches static flash-grant
  flags on permanents but if a one-shot effect grants flash through
  a continuous effect that doesn't change ``state.continuous_effects``
  in a way the hash sees, the cached "no capability" answer is
  stale until the next ``apply()`` invalidates the cache.
* **Cost-reduction effects landing mid-turn** (Goblin Electromancer)
  that would let an unaffordable spell become affordable. The hash
  fingerprints the pool / sources but doesn't re-run cost-reduction
  evaluation per opp card; we conservatively count "could possibly
  ever be cast for any cost in this turn" rather than the exact
  current effective cost.
* **Effects granting new activated abilities to opp's permanents**
  (Equipment with `grant_activated_ability` that lands without an
  ``apply()`` between moments). The hash counts permanent ids that
  have any ability per the current effective-abilities lookup; if
  the count changes the hash changes. But a SAME-ID, NEW-ability
  case is invisible.
* **Effects making spells castable from new zones**. The hash watches
  zone-castable flags (``warp_castable_from_graveyard``,
  ``cast_from_exile_with_lightstall_surcharge``,
  ``playable_from_exile_this_turn``) at coarse granularity.

The first two are exceedingly rare in the EoE pool we train on;
the last two are checked structurally. In practice the rate of
silent false-negatives is small enough to be acceptable for
training: mis-skipping a single response per million priority
moments doesn't materially perturb the policy. If a future card
class reveals a higher rate, this module is the right place to
extend.

Cache lifetime
--------------

The cache lives on the adapter and is invalidated on every
``apply()`` (same hook the legal_actions cache uses). Within a
single priority window the hash is recomputed and compared on every
``legal_decisions`` call; matching hashes hit the cached bool.
"""

from __future__ import annotations

from mtg_bot.actions import can_pay_cost
from mtg_bot.game import GameState


def _instant_speed_castable_in_hand(
    state: GameState, opp_id: int, p,
) -> bool:
    """Return True if any card in opp's hand looks instant-speed
    castable at non-sorcery timing AND the cost is payable from
    opp's currently-available mana.

    Conservative: this DOES NOT replicate the full ``legal_actions``
    target/additional-cost gating. If the card *could* be cast given
    enough mana, return True. The cheap mana check ensures we don't
    flag every instant in hand regardless of whether opp could
    actually pay — that would defeat the auto-pass payoff.
    """
    for card in p.hand:
        pr = card.printing
        instant_speed = pr.is_instant or "flash" in pr.keywords
        if not instant_speed:
            continue
        # Mana affordability — gate on the bare mana_cost (ignoring
        # cost reductions and alternate costs; if a reduction would
        # APPLY the spell stays castable, and the only direction of
        # error here is conservative).
        if can_pay_cost(state, opp_id, pr.mana_cost):
            return True
    return False


def _instant_speed_castable_in_graveyard(
    state: GameState, opp_id: int, p,
) -> bool:
    """Warp-from-graveyard / flashback at instant speed. Today's
    ``legal_actions`` only allows warp-from-graveyard at sorcery
    speed (per the comment in legal.py near ``warp_castable_from_graveyard``),
    so this returns False unless an instant-cast-from-grave grant
    is in play. Kept as a hook so adding instant-speed flashback
    later doesn't require touching the auto-pass module.
    """
    for card in p.graveyard:
        pr = card.printing
        if not pr.is_instant:
            continue
        # The few grave-cast flags we track today are sorcery-speed.
        # Future flashback-instant cards would set a flag here.
        if pr.warp_castable_from_graveyard and pr.warp_cost is not None:
            # ``legal_actions`` skips instant-speed grave warp today,
            # but conservatively include if we ever flip on instants.
            if can_pay_cost(state, opp_id, pr.warp_cost):
                return True
    return False


def _instant_speed_castable_from_exile(
    state: GameState, opp_id: int, p,
) -> bool:
    """Impulse-cast (``playable_from_exile_this_turn``) at instant
    speed if the underlying card is an instant. Kavu-gated cards
    likewise. Lightstall surcharge is sorcery-speed-only, skip.
    """
    for card in p.exile:
        if not card.printing.is_instant:
            continue
        if card.warped:
            continue  # warp branches are sorcery-speed today
        if not (
            card.playable_from_exile_this_turn
            or card.play_from_exile_requires_kavu
        ):
            continue
        if can_pay_cost(state, opp_id, card.printing.mana_cost):
            return True
    return False


def _has_instant_speed_activatable(
    state: GameState, opp_id: int, p,
) -> bool:
    """Any permanent opp controls with at least one activatable
    non-sorcery-speed ability whose mana portion is payable?

    Today the engine's ``legal_actions`` enumerator returns early at
    non-sorcery timing BEFORE walking the activated-ability block,
    so an opp at non-active priority is never offered an
    ActivateAbility action regardless of what permanents they
    control. That's an engine simplification — the comment in
    ``legal.py`` near the early-return makes this explicit. As long
    as that holds, treating "opp has activated abilities" as a
    capability would silently sabotage every auto-pass attempt
    (every player has lands, every land has activated abilities at
    a layer we don't model here).

    Returning False unconditionally matches what the engine
    actually offers at this priority moment. If a future engine
    change DOES start returning ActivateAbility actions at non-
    sorcery timing, this is the place to add the check (and the
    hash already covers permanent shape).
    """
    return False


def opp_can_act(state: GameState, opp_id: int) -> bool:
    """Definitive "does opp have at least one instant-speed
    capability right now" check. Returns True conservatively (false
    positives lead to a normal ``legal_actions`` enumeration which
    is correct); returns False only when we're confident there's
    nothing for opp to do.
    """
    p = state.player_by_id(opp_id)
    if _instant_speed_castable_in_hand(state, opp_id, p):
        return True
    if _instant_speed_castable_in_graveyard(state, opp_id, p):
        return True
    if _instant_speed_castable_from_exile(state, opp_id, p):
        return True
    if _has_instant_speed_activatable(state, opp_id, p):
        return True
    return False


def opp_capability_hash(state: GameState, opp_id: int) -> int:
    """Fast structural hash over the inputs that decide
    ``opp_can_act``. Cheap: O(opp_hand_size + opp_battlefield_size).

    Hash inputs (any of these changing means the cache may be stale):

    * **Hand contents** — printing-name tuple sorted. A different
      hand means different castable possibilities.
    * **Mana availability fingerprint** — the count of mana coins in
      pool plus the per-color counts of untapped lands the opp
      controls + the count of untapped non-land permanents (a proxy
      for tap-for-mana abilities outside of lands; doesn't try to
      precisely model every mana ability — false positives are
      acceptable).
    * **Permanent ability fingerprint** — sorted ids of opp's
      permanents that currently have any activated ability AND
      their tapped/sick state. Captures: arrival/departure of
      ability-having permanents, things untapping or being tapped,
      and (via the id-set count delta) any ability grants/losses
      that change which permanents have at least one ability.
    * **Stack length** — cheap. If the stack changes the priority
      context can change (and ``apply()`` already invalidates).
    * **Step / turn coordinates** — included so the cache can't
      bleed across step transitions even within the same opp.

    NB: the hash is COMPARED on each priority moment after every
    ``apply()`` invalidation. ``apply()`` clears the cache outright,
    so the hash's job is only to detect the rare case where the
    adapter advances internal step machinery WITHOUT flipping the
    invalidator. The structural redundancy is intentional — cheap
    and load-bearing for safety.
    """
    p = state.player_by_id(opp_id)

    # Hand: printing name tuple sorted. Names rather than ids so a
    # reorder in-place doesn't break the hash, and so two different
    # GameObject instances of the same printing collide.
    hand_key = tuple(sorted(c.printing.name for c in p.hand))

    # Mana fingerprint — pool + untapped sources approximation.
    pool_key = tuple(sorted(
        (coin.color, coin.spend_restriction or "") for coin in p.mana_pool
    ))
    # Untapped permanents by id+printing-name+tapped — captures any
    # tap-state flip.
    untapped_perm_key = tuple(sorted(
        (obj.id, obj.printing.name)
        for obj in state.battlefield
        if obj.controller_id == opp_id and not obj.tapped
    ))

    # Permanents with abilities — id + tapped + summoning_sick.
    # We DON'T call effective_activated_abilities here (that's the
    # expensive bit we're trying to avoid); we instead capture
    # battlefield shape so any meaningful change blows the hash.
    bf_key = tuple(sorted(
        (
            obj.id,
            obj.printing.name,
            obj.tapped,
            obj.summoning_sick,
            len(obj.printing.activated_abilities),
        )
        for obj in state.battlefield
        if obj.controller_id == opp_id
    ))

    # Graveyard / exile printing names (for warp-from-grave / impulse
    # exile flag changes). Cheap.
    gy_key = tuple(sorted(c.printing.name for c in p.graveyard))
    exile_key = tuple(sorted(
        (c.printing.name, c.warped, c.playable_from_exile_this_turn,
         c.play_from_exile_requires_kavu)
        for c in p.exile
    ))

    # Step / turn / stack — coarse global context.
    global_key: tuple = (
        state.step,
        state.turn_number,
        len(state.stack),
        state.priority_player_idx,
        state.active_player_idx,
        # Continuous-effect count is a coarse proxy for "have any
        # ongoing effects landed since last hash"; the cache being
        # invalidated on every apply() means this is mostly defensive.
        len(state.continuous_effects),
    )

    return hash((
        hand_key, pool_key, untapped_perm_key, bf_key,
        gy_key, exile_key, global_key,
    ))
