"""Phase 6 trajectory-parity helpers.

Sibling module to :mod:`mtg_bot.parity.cross_engine`. The cross-engine
module ships the per-step / per-action primitives (``build_matched_states``,
``step_both``, ``advance_phase_python``, the family of ``*_selector``
functions, the field-view differ); this module ships the *real-game-shaped*
primitives that drive multi-turn trajectory probes.

Surface (Phase 6 round-13 + round-14 slices):

* :func:`setup_matched_game` — closes infrastructure gap #1 from
  ``docs/PHASE6_TRAJECTORY_PARITY.md``: a single ``(decks, seed,
  mulligans=...)`` entrypoint that produces a parity-synced opening
  state on both engines. Wraps :func:`cross_engine.build_matched_states`
  and the side-channel opening-hand draw.
* :class:`MulliganDeterministicAgent` — Round-14 closure (gap #2): a
  deterministic cross-engine mulligan agent that produces matching
  keep/mulligan + bottom-pick decisions on both Python and Rust. The
  default policy is ``mulligan_target_hand_size=7`` (always keep at 7,
  never mulligan); pass a smaller value to mulligan exactly to that
  size. Bottom-picks are positional (``hand[0..n]``) so they're
  trivially reproducible across engines.

What this module deliberately does NOT cover:

* **Decision-callback mulligans.** The agent surface here is config-
  driven (mulligan to N, bottom by position). It is NOT a full
  ``Agent.choose_mulligan`` / ``Agent.choose_bottom`` bridge — those
  agents make state-conditional decisions, and getting state-
  conditional cross-engine agreement requires either (a) the SAME
  agent instance making the decision and routing it to both engines,
  or (b) two agents that always agree on the same hand. The
  deterministic agent is the (a) path: one agent, one decision per
  iteration, applied to both engines.
* **Real ``mtg_bot.simulate.setup_game`` mirror.** Production
  ``setup_game`` constructs Players via ``_build_player_from_names``,
  which materializes printings out of the *active card source*
  (Scryfall-loaded printings). The cross-engine harness already has
  its own per-DeckSpec card-pool plumbing; this slice builds on that
  plumbing rather than the production printings dict so the harness
  can drive synthetic ``CardDef`` decks (the only deck shape Phase 5
  + 6 actually probe).

The natural follow-up: a ``setup_matched_game_from_real_decks(decks,
seed, mulligans=...)`` that accepts decklist *names* against the live
``mtg_bot.cards.printings`` dict and threads them into a freshly-
materialized DeckSpec. That's a Phase 6 follow-on once the trajectory
suite outgrows hand-rolled CardDef registries.
"""

from __future__ import annotations

import gzip
import json
import pathlib
import random
from dataclasses import dataclass
from typing import Optional

from mtg_bot.parity.cross_engine import (
    CardDef,
    DeckSpec,
    build_matched_states,
)


__all__ = [
    "setup_matched_game",
    "setup_matched_game_from_real_decks",
    "MulliganDeterministicAgent",
    "RealGameCombatAgent",
    "BilateralCombatAgent",
    "CombatStrategy",
    "drive_combat_phase",
    "load_production_deck",
    "production_deck_to_deckspec",
    "DEFAULT_PRODUCTION_DECK_POOL",
]


# Round-17 enhancement (production-decklists slice). The 17lands EoE
# deck pool used by self-play / iterate; relative to repo root.
DEFAULT_PRODUCTION_DECK_POOL = pathlib.Path("data/17lands/eoe_decks.json.gz")


# ---------------------------------------------------------------------------
# Phase 6 round-16: real-game combat agent (closes infrastructure gap #3).
#
# Round-13/14/15 trajectory tests drive multi-turn real-game combat using
# inline scripts: each test re-spells out "find Bears with name == ...,
# emit declare_attackers with [int(bears.id)], walk DA -> DB, emit
# declare_blockers with [], side-channel combat damage, ...". As the
# trajectory suite grows beyond a single attacker / single combat round,
# inlining repeats and ad-hoc per-test combat scripts become the dominant
# noise.
#
# RealGameCombatAgent is the round-16 promotion: a config-driven combat
# decision source that walks the battlefield + per-object flags on each
# call and emits the right action-dict for the current step. Same shape
# as the round-14 MulliganDeterministicAgent — frozen-dataclass config,
# stateless decision functions, Python-only (the action-dicts cross both
# engines via the same `step_both` path the inline scripts use).
#
# Strategy vocabulary:
#   - "attack_all"            — every unsick + untapped non-summoning-sick
#                               creature attacks; defender doesn't block.
#                               Same shape as combat_selector's attacker
#                               branch.
#   - "attack_all_block_smallest" — attackers as above; defender blocks
#                               each attacker with their SMALLEST
#                               available creature (by power, then
#                               toughness, then id).
#   - "no_attack"             — skip combat entirely; emit empty
#                               declare_attackers + empty declare_blockers.
#                               Pins the no-combat baseline path.
#
# The agent does NOT advance phases — it only emits the action-dict for
# the current decision (declare_attackers OR declare_blockers OR pass).
# Callers compose the agent with `_advance_n_phases` / `step_both` /
# `resolve_combat_damage_python` etc. to drive a full combat round.
# ---------------------------------------------------------------------------

CombatStrategy = str  # see _VALID_COMBAT_STRATEGIES

# Round-17 enhancement (production-decklists slice): three new strategies
# that exercise richer attacker / blocker logic than the round-16
# attack_all / attack_all_block_smallest / no_attack triad. Each new
# strategy is a pure function of observable battlefield state — no
# new RNG, no per-side asymmetry, agent stays stateless.
#
# - "attack_with_unblockable_creatures_only" — only declare attackers
#   that carry an evasion keyword (flying / unblockable / shadow / ...)
#   the cross-engine harness understands. Defender does not block
#   (vacuously — the attackers can't be legally blocked anyway, but
#   we emit the empty assignment to make the no-block path explicit).
#   Useful for trajectory probes that want a guaranteed-through-attack
#   shape without involving block-assignment plumbing.
# - "block_with_largest_able" — mirror of attack_all_block_smallest,
#   but defender picks their LARGEST creature per attacker (sorted by
#   (power desc, toughness desc, id asc)). Pins the inverted block
#   selector — verifies that the agent's block-assignment shape doesn't
#   accidentally hardcode "smallest" anywhere.
# - "optimal_no_loss_attack" — only attack if the defender CAN'T block
#   back-and-kill the attacker. For a vanilla creature with power P
#   and toughness T, an attack is "no-loss" if no defender creature has
#   power >= T (defender can't trade up: no single blocker can kill
#   the attacker). Defender then declines blocking (empty assignments).
#   Surfaces a non-trivial state-dependent attacker policy without
#   needing to model deeper combat math.
_VALID_COMBAT_STRATEGIES: frozenset[str] = frozenset(
    {
        "attack_all",
        "attack_all_block_smallest",
        "no_attack",
        "attack_with_unblockable_creatures_only",
        "block_with_largest_able",
        "optimal_no_loss_attack",
    }
)

# Evasion keywords the harness recognizes for the
# "attack_with_unblockable_creatures_only" strategy. Limited to the
# keywords the cross-engine bridge wires symmetrically (same keyword
# on Python's CardPrinting.keywords frozenset and Rust's
# battlefield_has_keyword check). "flying" / "unblockable" / "shadow"
# are the obvious ones; menace is NOT evasion-strict (it just requires
# 2+ blockers, so it CAN be blocked and is excluded here).
_EVASION_KEYWORDS: frozenset[str] = frozenset({"flying", "unblockable", "shadow"})


@dataclass(frozen=True)
class RealGameCombatAgent:
    """Cross-engine deterministic combat policy for real-game trajectories.

    Closes Phase 6 infrastructure gap #3: a config-driven combat
    decision source that drives multi-turn real-game combat via a
    deterministic strategy. Same shape as
    :class:`MulliganDeterministicAgent` — stateless, observation-driven,
    same emission on both engines.

    Parameters
    ----------
    strategy : str, default "attack_all"
        One of:

        * ``"attack_all"`` — at DECLARE_ATTACKERS, every unsick + untapped
          creature the active player controls attacks the opponent; at
          DECLARE_BLOCKERS, defender declines to block (empty
          assignments).
        * ``"attack_all_block_smallest"`` — same attacker selection;
          at DECLARE_BLOCKERS, defender blocks each attacker with their
          SMALLEST available creature, sorted by ``(power, toughness,
          id)``. One blocker per attacker (no multi-block); if defender
          has fewer eligible blockers than attackers, the lowest-id
          attackers get blocked first.
        * ``"no_attack"`` — at DECLARE_ATTACKERS, emit empty attacker
          set; at DECLARE_BLOCKERS, emit empty assignments. Combat
          becomes a no-op; useful for tests that want to drive land
          drops + creature ETBs across multiple turns without combat
          damage.
        * ``"attack_with_unblockable_creatures_only"`` — at
          DECLARE_ATTACKERS, only declare attackers that carry an
          evasion keyword (``"flying"`` / ``"unblockable"`` /
          ``"shadow"``) the cross-engine bridge understands. At
          DECLARE_BLOCKERS, emit empty assignments. Useful for
          trajectory probes that want a guaranteed-unblocked attack
          shape (e.g. lifelink trample probes that need the attacker
          to land combat damage on the player).
        * ``"block_with_largest_able"`` — mirror of
          ``"attack_all_block_smallest"`` but defender picks their
          LARGEST creature per attacker (sorted by ``(power desc,
          toughness desc, id asc)``). Pins the inverted block selector;
          attacker selection is identical to ``"attack_all"``.
        * ``"optimal_no_loss_attack"`` — at DECLARE_ATTACKERS, only
          declare attackers the defender CAN'T trade up against. For
          a vanilla attacker with toughness T, the attack is "no-loss"
          if no defender creature has ``power >= T`` (no single blocker
          can kill the attacker). Defender then declines blocking
          (empty assignments) — pins the attacker side. The "optimal"
          label is light: no continuous-effect / counter / removal
          tracking; just a static p/t comparison on the visible bf.

    Notes
    -----
    The agent reads the PYTHON state (``py_state``) for decision
    construction. Both engines maintain byte-equal field views by the
    Phase 5 / Phase 6 invariants, so reading from Python and applying
    on both engines via :func:`mtg_bot.parity.cross_engine.step_both`
    produces identical post-state. (The same shape Phase 5's
    ``combat_selector`` uses internally — it reads ``py_state``, emits
    the action-dict, the harness applies it on both sides.)

    The agent does NOT touch RNG. Combat decisions are pure functions
    of the visible battlefield + per-object flags. Two calls with the
    same agent + same observable state produce identical output.

    The agent does NOT advance phases. The caller composes phase
    advances around the agent's emit. The
    :func:`drive_combat_phase` helper composes the standard pattern
    (DECLARE_ATTACKERS -> DECLARE_BLOCKERS -> COMBAT_DAMAGE ->
    END_OF_COMBAT) for callers that don't need step-by-step control.
    """

    strategy: CombatStrategy = "attack_all"

    def __post_init__(self) -> None:  # pragma: no cover — frozen guard
        if self.strategy not in _VALID_COMBAT_STRATEGIES:
            raise ValueError(
                f"strategy={self.strategy!r} not supported. "
                f"Valid: {sorted(_VALID_COMBAT_STRATEGIES)}"
            )

    # -- Decision functions --------------------------------------------------

    def pick_attackers(self, py_state) -> list[int]:
        """Pick the active player's attacker ids for DECLARE_ATTACKERS.

        Returns a sorted list of ids.

        Strategy-specific filtering on top of the common eligibility
        gate (untapped + (unsick OR has haste) + not-already-attacking
        Creature controlled by the active player):

        * ``"no_attack"`` returns ``[]`` unconditionally.
        * ``"attack_all"`` / ``"attack_all_block_smallest"`` /
          ``"block_with_largest_able"`` return every eligible attacker.
          (``block_with_largest_able`` only differs on the BLOCKER
          side — it shares ``attack_all``'s attacker selection.)
        * ``"attack_with_unblockable_creatures_only"`` returns only
          eligible attackers carrying one of the
          :data:`_EVASION_KEYWORDS`. Reads the keyword from
          ``o.printing.keywords`` (Python's frozenset spelling — same
          place :func:`mtg_bot.combat.effective_keywords` reads from
          for the no-modifier case).
        * ``"optimal_no_loss_attack"`` returns only eligible attackers
          for which no defender creature on the bf has
          ``power >= attacker.toughness``. Walks the defender's bf
          per-attacker to compare static p/t only — no continuous
          effect / counter modeling.

        Round-18 enhancement: the eligibility gate now honors haste
        (CR 702.10) — a summoning-sick creature with the ``"haste"``
        keyword IS attack-eligible. Previously the gate was a hard
        ``not o.summoning_sick`` filter that silently excluded haste
        creatures. The agent reads the keyword from
        ``o.printing.keywords`` (the same Python-side spelling
        :func:`mtg_bot.combat.effective_keywords` consumes for the
        no-modifier case).
        """
        if self.strategy == "no_attack":
            return []
        active_idx = py_state.active_player_idx
        defender_idx = 1 - active_idx
        eligible = [
            o for o in py_state.battlefield
            if o.controller_id == active_idx
            and "Creature" in o.printing.card_types
            and not o.tapped
            and (
                not o.summoning_sick
                or "haste" in getattr(o.printing, "keywords", frozenset())
            )
            and not getattr(o, "attacking", False)
        ]

        if self.strategy == "attack_with_unblockable_creatures_only":
            eligible = [
                o for o in eligible
                if _EVASION_KEYWORDS & set(
                    getattr(o.printing, "keywords", frozenset())
                )
            ]
        elif self.strategy == "optimal_no_loss_attack":
            # Defender's eligible blockers (untapped Creatures defender
            # controls — sick can still block per CR 302.1, so the
            # filter mirrors pick_blocks's eligibility test).
            defender_blockers = [
                o for o in py_state.battlefield
                if o.controller_id == defender_idx
                and "Creature" in o.printing.card_types
                and not o.tapped
            ]
            # An attacker is "no-loss" if no defender blocker has
            # power >= attacker.toughness. Defender's largest power on
            # bf is the bound; if that's < attacker.toughness, no single
            # blocker can kill the attacker (multi-block sums power
            # but defender CHOOSES whether to block, so "no-loss"
            # against a non-blocking defender holds vacuously).
            max_def_power = max(
                (
                    int(getattr(b.printing, "power", 0) or 0)
                    for b in defender_blockers
                ),
                default=0,
            )
            eligible = [
                o for o in eligible
                if int(getattr(o.printing, "toughness", 0) or 0)
                > max_def_power
            ]

        return sorted(int(o.id) for o in eligible)

    def pick_blocks(self, py_state) -> list[list[int]]:
        """Pick the defender's block assignments for DECLARE_BLOCKERS.

        Returns a list of ``[blocker_id, attacker_id]`` pairs — the
        same shape Rust's ``Action::DeclareBlockers`` accepts and
        Python's ``DeclareBlockers(assignments=...)`` consumes after
        the harness's tuple-conversion.

        ``"no_attack"``, ``"attack_all"``,
        ``"attack_with_unblockable_creatures_only"``, and
        ``"optimal_no_loss_attack"`` return ``[]`` (no blocks).

        ``"attack_all_block_smallest"`` walks attackers in id-sort order
        and assigns the defender's smallest-power-then-toughness-then-id
        creature to each, one blocker per attacker. Already-assigned
        blockers are removed from the eligible pool so we don't
        double-assign.

        ``"block_with_largest_able"`` mirrors the smallest selector but
        sorts the eligible pool by ``(power desc, toughness desc, id
        asc)`` so the LARGEST creature blocks first. The attacker walk
        order (id-sort) is unchanged.

        Block-eligible-creature selection is deterministic: sorted by
        ``(power, toughness, id)`` so ties break the same way on every
        call. Power is read from ``printing.power`` (synthetic vanilla
        decks have static p/t; +1/+1 counters and continuous effects
        are NOT modeled here — the Phase 6 trajectory deck shape uses
        pure vanilla creatures).
        """
        if self.strategy not in (
            "attack_all_block_smallest",
            "block_with_largest_able",
        ):
            return []

        attackers = [
            o for o in py_state.battlefield
            if getattr(o, "attacking", False)
        ]
        if not attackers:
            return []

        active_idx = py_state.active_player_idx
        defender_idx = 1 - active_idx

        # Defender's eligible blockers: untapped Creatures defender
        # controls. CR 509.1b — tapped creatures can't block. CR 302.1
        # allows summoning-sick creatures TO block (sickness only
        # blocks tap-to-attack and tap-to-activate), so we keep
        # summoning-sick creatures eligible to block. Filter out
        # creatures already assigned blocking somewhere via the
        # per-object ``blocking`` flag (in case of re-visits).
        eligible = [
            o for o in py_state.battlefield
            if o.controller_id == defender_idx
            and "Creature" in o.printing.card_types
            and not o.tapped
            and not getattr(o, "blocking", False)
        ]
        if not eligible:
            return []

        # Sort by (power, toughness, id). printing.power can be None
        # for non-creatures, but the eligible list is filtered to
        # Creatures so power is set. Cast to int for the sort key.
        # ``block_with_largest_able`` reverses the (power, toughness)
        # axes so the largest creature sorts FIRST; ties on (power,
        # toughness) still break by id ascending so the agent's
        # output is deterministic regardless of bf insertion order.
        if self.strategy == "block_with_largest_able":
            def _key(o):
                p = int(getattr(o.printing, "power", 0) or 0)
                t = int(getattr(o.printing, "toughness", 0) or 0)
                return (-p, -t, int(o.id))
        else:
            def _key(o):
                p = int(getattr(o.printing, "power", 0) or 0)
                t = int(getattr(o.printing, "toughness", 0) or 0)
                return (p, t, int(o.id))

        eligible_sorted = sorted(eligible, key=_key)

        # Walk attackers in id order (matches the attacker emit order
        # from pick_attackers); assign smallest available blocker.
        attackers_by_id = sorted(attackers, key=lambda o: int(o.id))
        assignments: list[list[int]] = []
        used_blocker_ids: set[int] = set()
        for atk in attackers_by_id:
            for blk in eligible_sorted:
                if int(blk.id) in used_blocker_ids:
                    continue
                assignments.append([int(blk.id), int(atk.id)])
                used_blocker_ids.add(int(blk.id))
                break  # one blocker per attacker for this strategy
            # If no blocker available, attacker goes through unblocked.
        return assignments


# ---------------------------------------------------------------------------
# Phase 6 round-19 enhancement (bilateral / asymmetric combat strategies):
#
# RealGameCombatAgent's strategy is mirror-symmetric -- the same strategy
# decides attackers when p0 is active AND when p1 is active, and the same
# strategy decides blockers regardless of which side is defending. The
# round-17 enhancement-follow-on list flagged this as the next gap:
# "Bilateral / asymmetric combat strategies -- current strategies are
# symmetric across both players. Asymmetric strategies (`p0 attacks, p1
# never attacks back`) would let trajectory tests pin specific defensive
# patterns without needing a second RealGameCombatAgent per player.
# Round-17 ships the agent shape that could carry per-side config, but
# the strategy enum stays mirror-symmetric for now."
#
# BilateralCombatAgent is the per-side wrapper: a frozen-dataclass that
# holds two RealGameCombatAgent instances (one per player) and dispatches
# pick_attackers / pick_blocks to the active-player-side / defender-side
# delegate respectively. Same duck-typed interface as RealGameCombatAgent
# (just .pick_attackers + .pick_blocks), so drive_combat_phase accepts it
# unchanged.
#
# Construction is by (p0_strategy, p1_strategy) string pair (the cleanest
# call shape; the wrapper builds the two RealGameCombatAgent instances
# internally) OR by (p0_agent, p1_agent) for callers that want to share /
# pre-build per-side agents (e.g. a future state-conditional agent that
# isn't a bare RealGameCombatAgent). Both shapes route through the same
# dispatch logic.
#
# The wrapper is stateless (frozen-dataclass holding frozen-dataclass
# RealGameCombatAgent instances). Two calls with the same agent + same
# observable state produce identical output, mirroring the round-16/17
# RealGameCombatAgent invariant.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BilateralCombatAgent:
    """Per-side combat policy wrapper around two ``RealGameCombatAgent``s.

    Closes the round-17 enhancement-follow-on item "Bilateral /
    asymmetric combat strategies": the symmetric strategy enum becomes
    a per-side pair via this wrapper, without changing the underlying
    ``RealGameCombatAgent`` contract.

    The wrapper exposes the same duck-typed interface as
    ``RealGameCombatAgent`` (``pick_attackers`` + ``pick_blocks``) so
    it drops into ``drive_combat_phase`` unchanged. Each call dispatches
    to the appropriate per-side delegate based on which player is the
    active player at decision time:

      * ``pick_attackers(py_state)`` -> delegate for
        ``py_state.active_player_idx``'s strategy. The active player is
        the one declaring attackers per CR 508.1.
      * ``pick_blocks(py_state)`` -> delegate for the DEFENDER (=
        ``1 - py_state.active_player_idx``)'s strategy. The defender is
        the one declaring blockers per CR 509.1.

    Construct from per-side strategy strings (the common case):

        BilateralCombatAgent(p0_strategy="attack_all", p1_strategy="no_attack")

    Or from pre-built per-side agents (for callers sharing agents or
    using a future agent type that isn't a bare RealGameCombatAgent):

        BilateralCombatAgent(
            p0_agent=RealGameCombatAgent(strategy="attack_all"),
            p1_agent=RealGameCombatAgent(strategy="no_attack"),
        )

    Exactly one of the two construction shapes per side must be
    provided; mixing (p0_strategy + p0_agent both set) or omitting
    (neither set) raises ValueError.

    Use cases:

    * **Asymmetric attack/defense** -- p0 plays aggro
      (``"attack_all"``), p1 plays control (``"no_attack"``). Pins the
      aggressor / control trajectory shape in one config.
    * **Per-side block selectors** -- p0 uses
      ``"attack_all_block_smallest"`` to chump-block, p1 uses
      ``"block_with_largest_able"`` to trade up. Surfaces the
      asymmetric block selector divergence directly.
    * **Single-side smoke** -- one side runs an interesting policy
      (``"optimal_no_loss_attack"``), the other side runs a trivial
      baseline (``"no_attack"``) so the trajectory probe isolates one
      side's decision logic cleanly.

    Mirroring RealGameCombatAgent's invariants:

    * **Stateless.** Frozen-dataclass; per-side delegates are
      themselves frozen-dataclasses. No mutation, no RNG.
    * **Same emission on both engines.** Reads PYTHON state and emits
      action-dicts; the harness applies on both sides via
      ``step_both``.
    * **Does NOT advance phases.** The caller composes phase advances
      around the agent (or uses ``drive_combat_phase``).
    """

    p0_strategy: CombatStrategy | None = None
    p1_strategy: CombatStrategy | None = None
    p0_agent: RealGameCombatAgent | None = None
    p1_agent: RealGameCombatAgent | None = None

    def __post_init__(self) -> None:
        # Each side must have exactly one source of truth (strategy OR
        # agent, not both, not neither). Build the per-side agent from
        # the strategy if it was passed; this normalizes the two
        # construction shapes into a single internal representation.
        if self.p0_strategy is not None and self.p0_agent is not None:
            raise ValueError(
                "BilateralCombatAgent: pass either p0_strategy or "
                "p0_agent, not both"
            )
        if self.p0_strategy is None and self.p0_agent is None:
            raise ValueError(
                "BilateralCombatAgent: must pass one of p0_strategy or "
                "p0_agent"
            )
        if self.p1_strategy is not None and self.p1_agent is not None:
            raise ValueError(
                "BilateralCombatAgent: pass either p1_strategy or "
                "p1_agent, not both"
            )
        if self.p1_strategy is None and self.p1_agent is None:
            raise ValueError(
                "BilateralCombatAgent: must pass one of p1_strategy or "
                "p1_agent"
            )
        # Normalize: stamp the constructed delegates onto p0_agent /
        # p1_agent regardless of which constructor shape was used. The
        # validation in RealGameCombatAgent.__post_init__ catches an
        # invalid strategy at construct time (NOT at call time).
        if self.p0_agent is None:
            object.__setattr__(
                self, "p0_agent", RealGameCombatAgent(strategy=self.p0_strategy),
            )
        if self.p1_agent is None:
            object.__setattr__(
                self, "p1_agent", RealGameCombatAgent(strategy=self.p1_strategy),
            )

    def _agent_for(self, player_idx: int) -> RealGameCombatAgent:
        """Return the delegate agent for ``player_idx`` (0 or 1)."""
        if player_idx == 0:
            return self.p0_agent  # type: ignore[return-value]
        if player_idx == 1:
            return self.p1_agent  # type: ignore[return-value]
        raise ValueError(
            f"BilateralCombatAgent only supports two-player engines "
            f"(player_idx in {{0, 1}}); got {player_idx}"
        )

    # -- Decision functions (delegate to the right per-side agent) ----------

    def pick_attackers(self, py_state) -> list[int]:
        """Pick the active player's attackers via that player's delegate.

        The active player is the one declaring attackers per CR 508.1,
        so attacker selection routes to the active-side strategy --
        e.g. ``BilateralCombatAgent(p0_strategy="attack_all",
        p1_strategy="no_attack")`` will declare every eligible p0
        attacker on p0's turn and an empty attacker set on p1's turn.
        """
        return self._agent_for(py_state.active_player_idx).pick_attackers(
            py_state
        )

    def pick_blocks(self, py_state) -> list[list[int]]:
        """Pick the defender's block assignments via that player's delegate.

        The defender (= 1 - active_player_idx) is the one declaring
        blockers per CR 509.1, so block assignment routes to the
        defender-side strategy -- e.g. ``BilateralCombatAgent(
        p0_strategy="attack_all_block_smallest",
        p1_strategy="block_with_largest_able")`` will block with the
        SMALLEST defender on p1's attacks (because p0 is defending and
        their delegate runs ``attack_all_block_smallest``) and with
        the LARGEST defender on p0's attacks (because p1 is defending
        and their delegate runs ``block_with_largest_able``).
        """
        defender_idx = 1 - py_state.active_player_idx
        return self._agent_for(defender_idx).pick_blocks(py_state)


def drive_combat_phase(
    py_state, rust_state, agent: RealGameCombatAgent,
) -> None:
    """Drive one combat phase end-to-end with the supplied agent.

    Pre-condition: ``py_state.step == Step.DECLARE_ATTACKERS`` (i.e.,
    the caller has already advanced phases past PRECOMBAT_MAIN ->
    BEGINNING_OF_COMBAT). Post-condition:
    ``py_state.step == Step.END_OF_COMBAT`` with combat state cleared
    and parity asserted on every intermediate compare.

    Composes the standard "attacker emit -> advance -> blocker emit ->
    advance -> combat damage -> advance -> clear combat" sequence the
    round-13/14/15 inline scripts spell out by hand. Each step asserts
    byte-equal field views on both engines; the first divergence
    raises an AssertionError naming the step.

    The advance from END_OF_COMBAT into POSTCOMBAT_MAIN is NOT done
    here — the caller drives that via ``_advance_n_phases`` so the
    helper's post-condition is the same as the inline scripts'.

    For ``"no_attack"`` strategy: emits ``declare_attackers`` with
    empty list, walks past blockers + damage steps with no-op effect.
    """
    from mtg_bot.parity.cross_engine import (
        advance_phase_python,
        clear_combat_both,
        compare_fields,
        deal_combat_damage_rust,
        resolve_combat_damage_python,
        step_both,
    )
    from mtg_bot.turn import Step

    if py_state.step != Step.DECLARE_ATTACKERS:
        raise ValueError(
            f"drive_combat_phase requires step=DECLARE_ATTACKERS; "
            f"got step={py_state.step.name}"
        )

    # 1. DECLARE_ATTACKERS — emit attacker dict.
    attackers = agent.pick_attackers(py_state)
    s = step_both(
        py_state, rust_state,
        {"kind": "declare_attackers", "attacker_ids": attackers},
    )
    if s.divergences:
        raise AssertionError(
            f"declare_attackers (step=DA, attackers={attackers}) "
            f"surfaced divergences: "
            f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
        )

    # 2. DA -> DB advance.
    advance_phase_python(py_state)
    rust_state.advance_phase()
    assert py_state.step == Step.DECLARE_BLOCKERS, (
        f"expected DECLARE_BLOCKERS after advance, got {py_state.step.name}"
    )

    # 3. DECLARE_BLOCKERS — emit blocker dict.
    assignments = agent.pick_blocks(py_state)
    s = step_both(
        py_state, rust_state,
        {"kind": "declare_blockers", "assignments": assignments},
    )
    if s.divergences:
        raise AssertionError(
            f"declare_blockers (assignments={assignments}) surfaced "
            f"divergences: "
            f"{[(d.field, d.py_value, d.rust_value) for d in s.divergences]}"
        )

    # 4. DB -> COMBAT_DAMAGE advance.
    advance_phase_python(py_state)
    rust_state.advance_phase()
    assert py_state.step == Step.COMBAT_DAMAGE, (
        f"expected COMBAT_DAMAGE after advance, got {py_state.step.name}"
    )

    # 5. COMBAT_DAMAGE — side-channel damage on both engines.
    fired_py = resolve_combat_damage_python(py_state)
    if fired_py:
        deal_combat_damage_rust(rust_state)
    # Post-damage compare.
    from mtg_bot.parity.cross_engine import (
        build_python_field_view,
        parity_smoke,
    )
    ps = parity_smoke()
    py_view = build_python_field_view(py_state)
    rust_view = ps._build_field_view(rust_state)
    divs = compare_fields(py_view, rust_view)
    if divs:
        raise AssertionError(
            f"post combat-damage divergences: "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in divs]}"
        )

    # 6. COMBAT_DAMAGE -> END_OF_COMBAT advance.
    advance_phase_python(py_state)
    rust_state.advance_phase()
    assert py_state.step == Step.END_OF_COMBAT, (
        f"expected END_OF_COMBAT after advance, got {py_state.step.name}"
    )

    # 7. Clear combat state on both engines (matches the
    # ``simulate.run_step`` END_OF_COMBAT hook). Without this Rust's
    # ``self.attackers`` would persist past the turn.
    clear_combat_both(py_state, rust_state)
    py_view = build_python_field_view(py_state)
    rust_view = ps._build_field_view(rust_state)
    divs = compare_fields(py_view, rust_view)
    if divs:
        raise AssertionError(
            f"post clear-combat divergences: "
            f"{[(d.field, d.py_value, d.rust_value, d.known_gap) for d in divs]}"
        )


@dataclass(frozen=True)
class MulliganDeterministicAgent:
    """Cross-engine deterministic mulligan policy.

    A config-driven decision source that produces byte-identical
    keep/mulligan + bottom-pick decisions on both Python and Rust.
    Closes Phase 6 infrastructure gap #2: any state-conditional
    ``Agent.choose_mulligan`` would need a state-equivalent decision
    on both engines, but a config-driven agent ("mulligan exactly
    until hand_size==N, then bottom by position") sidesteps the
    state-equivalence question entirely — the agent makes the same
    decision regardless of which side's hand it's looking at.

    Parameters
    ----------
    target_hand_size : int, default 7
        Number of cards the player should END UP HOLDING after all
        mulligans + bottoming. ``target_hand_size=7`` means "never
        mulligan" (each player keeps the initial 7). ``target_hand_size
        =6`` means "mulligan exactly once and bottom 1". ``=5`` means
        "mulligan twice and bottom 2". Etc. Must be in ``[0, 7]``.
        The London-mulligan rule (CR 103.4) bottoms ``mulls_taken``
        cards on keep, so the final hand size is always
        ``7 - mulls_taken``.
    bottom_strategy : str, default "first"
        Which cards to put on the bottom after the final keep. Only
        ``"first"`` is supported in this slice — bottoms ``hand[0..n]``
        in insertion order. Trivial to reproduce on Rust because hand
        order is byte-equal across engines after the shared-RNG shuffle.
        A ``"last"`` / ``"by_id_descending"`` variant is a one-line
        addition if a future test needs it; ``"first"`` is the default
        because it matches Rust's own
        ``bottom_cards_from_hand``-by-position default.

    Notes
    -----
    The agent does NOT consume any RNG state. The randomness in the
    mulligan loop comes from the *shared RNG instance* threaded into
    each engine's shuffle primitive (``random.Random(seed)._randbelow``
    in both Rust's ``mulligan_atomic(rng=)`` path and Python's local
    Fisher-Yates). The agent only governs the policy decisions
    (mulligan/keep, which cards to bottom), not the shuffle outcome.

    This separation keeps the agent reproducible regardless of seed —
    two calls with ``target_hand_size=5`` always mulligan twice, no
    matter what cards land in hand.
    """

    target_hand_size: int = 7
    bottom_strategy: str = "first"

    def __post_init__(self) -> None:  # pragma: no cover — frozen guard
        # frozen=True forbids __setattr__, so __post_init__ is a no-op
        # validate-only hook. Raise on construction with a bad config.
        if not (0 <= self.target_hand_size <= 7):
            raise ValueError(
                f"target_hand_size must be in [0, 7], got "
                f"{self.target_hand_size}"
            )
        if self.bottom_strategy != "first":
            raise ValueError(
                f"bottom_strategy={self.bottom_strategy!r} not supported. "
                f"Only 'first' is implemented in this slice."
            )

    @property
    def mulligans_to_take(self) -> int:
        """Number of mulligans this agent will run before keeping.

        ``7 - target_hand_size`` per the London-mulligan rule. A
        target of 7 means 0 mulligans; target 5 means 2 mulligans
        (then bottom 2 cards on keep).
        """
        return 7 - self.target_hand_size

    def should_mulligan(self, mulls_taken: int) -> bool:
        """Decision: should the player mulligan again?

        Returns True until ``mulls_taken`` reaches the configured
        ``mulligans_to_take``, then False (keep). Stateless — the
        decision is a pure function of the agent's config and the
        current mulligan count.
        """
        return mulls_taken < self.mulligans_to_take

    def pick_bottom(self, hand_ids: list[int], n: int) -> list[int]:
        """Pick ``n`` card ids from ``hand_ids`` to put on the bottom.

        With ``bottom_strategy="first"`` (the only currently-supported
        strategy), returns ``hand_ids[:n]`` — the first ``n`` cards
        in hand-insertion order.
        """
        if n == 0:
            return []
        if n > len(hand_ids):
            raise ValueError(
                f"pick_bottom: requested {n} cards but hand has only "
                f"{len(hand_ids)}"
            )
        return list(hand_ids[:n])


def _draw_opening_hand_both(py_state, rust_state, n: int = 7) -> None:
    """Mirror real-game ``setup_game``'s seven-card opening draw on BOTH engines.

    Phase 5's CE3 closure proved Python's ``turn.draw_card`` + Rust's
    ``draw_card`` pymethod produce byte-equal hand/library views when
    both libraries start at the same permutation. This helper just
    fires that draw ``n`` times per player.

    Internal helper — :func:`setup_matched_game` is the public entry.
    """
    from mtg_bot.turn import draw_card as py_draw_card

    for pid in (0, 1):
        for _ in range(n):
            py_draw_card(py_state, pid)
            rust_state.draw_card(pid)


def _python_mulligan_iteration(py_state, player_id: int, rng) -> None:
    """One mulligan iteration on the PYTHON side.

    Mirrors Rust's ``mulligan_atomic`` shuffle+redraw step (the bottom
    step is applied separately by :func:`_python_bottom_cards`). Drains
    ``player_id``'s hand back into the library, runs Python's
    ``random.Random.shuffle`` on the library using the SHARED ``rng``
    instance (which is the same instance Rust's ``mulligan_atomic``
    consumes via ``_randbelow``), then redraws 7 cards.

    Both engines call ``rng.shuffle(<library_list>)`` (Python directly,
    Rust via ``_randbelow`` callback in Fisher-Yates). Because the
    rng instance is shared and the pre-shuffle library order is byte-
    equal on both engines, the post-shuffle libraries will be
    byte-equal as well.

    The internal-state mutation here mirrors
    ``mtg_bot.simulate.setup_game``'s mulligan-redraw block (lines
    160-170 of simulate.py) verbatim — same drain, same shuffle, same
    redraw — except it consumes the shared external rng rather than
    setup_game's local one.
    """
    from mtg_bot.game import Zone
    from mtg_bot.turn import draw_card as py_draw_card

    p = py_state.players[player_id]
    # Drain hand into library in HAND-INSERTION order (hand[0] first,
    # hand[6] last). Rust's mulligan_to_n / mulligan_atomic uses
    # ``hand.drain(..)`` which yields entries in insertion order; we
    # mirror that exactly so the pre-shuffle library tail order matches
    # across engines. (NOTE: this differs from Python's
    # mtg_bot.simulate.setup_game which uses ``p.hand.pop()`` (LIFO);
    # the cross-engine path needs the FIFO order to match Rust.)
    returning = list(p.hand)
    p.hand.clear()
    for card in returning:
        card.zone = Zone.LIBRARY
        p.library.append(card)
    # Shared-rng shuffle. random.shuffle consumes _randbelow in
    # Fisher-Yates order, matching Rust's mulligan_atomic(rng=...)
    # consumption order.
    rng.shuffle(p.library)
    # Redraw 7 (or until empty).
    for _ in range(7):
        if not p.library:
            break
        py_draw_card(py_state, player_id)


def _python_bottom_cards(py_state, player_id: int, bottom_ids: list[int]) -> None:
    """Apply the post-mulligan bottom step on the PYTHON side.

    Mirrors Rust's ``bottom_cards_from_hand`` orientation: the FIRST
    id in ``bottom_ids`` ends up at the very BOTTOM of the library
    (last index), each subsequent id sits one slot above.
    Implementation: walk ids in reverse and ``library.append`` each —
    the last-walked (= first-supplied) lands at the tail.

    Per-instance state reset matches Rust's ``bottom_cards_from_hand``:
    ``tapped=False``, ``summoning_sick=False``, ``damage=0``, plus
    counters / attachments cleared. Without this reset, a hand card
    carrying ``summoning_sick=True`` (the default for cards just
    drawn to hand on Python) would keep that flag in the library
    while Rust would not — surfacing as a per-object field divergence
    on the very last cards of the library after bottoming.
    """
    from mtg_bot.game import Zone

    p = py_state.players[player_id]
    by_id = {c.id: c for c in p.hand}
    for oid in reversed(bottom_ids):
        card = by_id[oid]
        p.hand.remove(card)
        card.zone = Zone.LIBRARY
        # Mirror Rust's per-instance reset on bottom (CR-equivalent
        # cleanup: a card moving from hand to library can't legally
        # carry battlefield-only state; defensive against future
        # paths that might leave stale flags).
        card.tapped = False
        card.summoning_sick = False
        card.damage = 0
        # ``counters`` on the Python side is a list (vs Rust's int).
        # Empty it out to match the int=0 reset semantically.
        if hasattr(card, "counters") and isinstance(card.counters, list):
            card.counters.clear()
        if hasattr(card, "attached_to"):
            card.attached_to = None
        p.library.append(card)


def _run_mulligan_loop_both(
    py_state,
    rust_state,
    agent: MulliganDeterministicAgent,
    base_seed: int,
) -> None:
    """Drive the mulligan loop on BOTH engines for both players.

    Per-player loop:

    1. Ask the agent ``should_mulligan(mulls_taken)``. If False, exit
       to step 4.
    2. Construct two ``random.Random(iter_seed)`` instances — one for
       Python's local Fisher-Yates, one for Rust's ``mulligan_to_n``.
       Both seeds derive deterministically from
       ``(base_seed, player_id, mulls_taken)``. Two ``random.Random``
       instances seeded identically produce bit-identical
       ``_randbelow`` sequences (MT determinism), so the in-mulligan
       shuffle on each engine consumes the same draw order.
    3. Fire shuffle+redraw on both engines. Increment ``mulls_taken``.
       Loop to 1.
    4. Pick ``mulls_taken`` bottom ids via ``agent.pick_bottom``. Apply
       on both engines: Python via :func:`_python_bottom_cards`, Rust
       via ``bottom_cards_from_hand(n=mulls_taken)`` which bottoms
       hand[0..n] by position.

    Why ``mulligan_to_n`` for intermediate iterations and a separate
    ``bottom_cards_from_hand`` for the final keep, rather than Rust's
    parity-canonical ``mulligan_atomic``? Two reasons:

    * ``mulligan_atomic`` requires ``bottom_card_ids.len() ==
      mulligan_count + 1``, so an N-mulligan loop would need to bottom
      progressively-larger sets on each iteration even though only the
      LAST iteration's bottom is meaningful.
    * Splitting shuffle+redraw from bottom mirrors Python's
      ``simulate.setup_game`` mulligan-loop shape exactly (intermediate
      iterations are shuffle+redraw only; bottom fires once on keep).

    The split-call path consumes one Rust ``mulligan_count`` slot per
    mulligan, same as ``mulligan_atomic`` would; the per-call cap of 7
    still holds. With ``bottom_strategy="first"`` (the only currently-
    supported strategy), Rust's positional ``bottom_cards_from_hand(n)``
    is exactly equivalent to the agent's ``pick_bottom(hand_ids, n)``
    returning ``hand_ids[:n]``, so the chosen-by-id and chosen-by-
    position results agree.

    A future non-positional bottom strategy (e.g. "highest mana value
    first") would need either Rust hand-reordering before the bottom
    call or a Rust primitive that takes explicit bottom_ids — see the
    Rust API gaps section in ``docs/PHASE6_TRAJECTORY_PARITY.md``.
    """
    for pid in (0, 1):
        mulls_taken = 0
        while agent.should_mulligan(mulls_taken):
            # Per-iteration seed: deterministic in (base_seed, pid,
            # mulls_taken). Two random.Random instances with the same
            # seed produce identical _randbelow sequences, so Python's
            # local Fisher-Yates and Rust's mulligan_to_n consume the
            # same draw order even though they don't share state.
            iter_seed = (base_seed * 1000003 + pid * 31 + mulls_taken) & 0xFFFFFFFF
            py_rng = random.Random(iter_seed)
            rust_rng = random.Random(iter_seed)

            _python_mulligan_iteration(py_state, pid, py_rng)
            # Rust ``mulligan_to_n``'s ``seed`` arg is unused on the
            # external-rng path (the rng kwarg owns shuffle order); pass
            # 0 as a placeholder.
            rust_state.mulligan_to_n(pid, 7, 0, rng=rust_rng)

            mulls_taken += 1

        if mulls_taken > 0:
            # Pick bottom ids from the kept hand. By-position policy
            # ("first") matches Rust's bottom_cards_from_hand(n) which
            # also bottoms by position.
            hand_ids = [c.id for c in py_state.players[pid].hand]
            bottom_ids = agent.pick_bottom(hand_ids, mulls_taken)

            # Python: apply bottoming.
            _python_bottom_cards(py_state, pid, bottom_ids)
            # Rust: bottom by position (n cards from hand[0..n]).
            # bottom_strategy="first" guarantees this matches the
            # agent's pick_bottom([:n]) result by id.
            rust_state.bottom_cards_from_hand(pid, mulls_taken)


def setup_matched_game(
    decks: DeckSpec,
    seed: Optional[int] = None,
    mulligans: bool = False,
    opening_hand_size: int = 7,
    mulligan_agent: Optional[MulliganDeterministicAgent] = None,
    mulligan_seed: int = 0,
):
    """Build a parity-synced opening state on both engines.

    Closes Phase 6 infrastructure gap #1 (``docs/PHASE6_TRAJECTORY_PARITY.md``):
    a single entrypoint that produces a starting state with seven-card
    opening hands dealt on both Python and Rust, identical libraries
    on both sides, ready to walk turn 1 from UNTAP. Round-14 extends
    the helper to optionally drive a deterministic London-mulligan
    loop (gap #2).

    Parameters
    ----------
    decks : DeckSpec
        The matched decklist for both players. Reuses the existing
        ``cross_engine.DeckSpec`` shape so trajectory tests share the
        same registry / decklist / shuffle-seed plumbing as Phase 5
        smoke tests. The DeckSpec's ``shared_rng_seed`` (or
        ``shuffle_seed``) governs library shuffling on both engines —
        see :class:`cross_engine.DeckSpec` for the precedence rules.
    seed : Optional[int], default None
        Convenience: when set AND ``decks.shared_rng_seed`` is None,
        rebuilds ``decks`` with ``shared_rng_seed=seed`` so callers
        don't have to thread the seed twice. When BOTH are None the
        libraries are unshuffled (deck-list order). Callers that want
        explicit per-engine shuffle semantics should set
        ``decks.shared_rng_seed`` directly and leave ``seed=None``.
    mulligans : bool, default False
        When True, runs the deterministic London-mulligan loop on
        both engines using the supplied ``mulligan_agent`` (defaults
        to ``MulliganDeterministicAgent(target_hand_size=7)`` — a
        no-op agent that always keeps the initial 7). When False
        (legacy default), the helper deals 7 cards and stops, matching
        round-13's behavior exactly.
    opening_hand_size : int, default 7
        Cards to draw per player. Defaults to 7 (CR 103.5). Exposed
        primarily for test ergonomics — drop to 0 for a no-draw
        starting state matching the Phase 5 ``build_matched_states``
        pre-draw shape. Ignored when ``mulligans=True`` (the mulligan
        loop assumes the standard 7-card opening hand).
    mulligan_agent : Optional[MulliganDeterministicAgent], default None
        Cross-engine deterministic mulligan policy. Required when
        ``mulligans=True`` to govern the keep/mulligan + bottom-pick
        decisions. Defaults to ``MulliganDeterministicAgent()`` (the
        always-keep policy, equivalent to ``mulligans=False``) when
        not supplied. Ignored when ``mulligans=False``.
    mulligan_seed : int, default 0
        Base seed for the per-iteration shuffle RNGs. Each per-player
        per-iteration shuffle uses a freshly-constructed
        ``random.Random`` derived from ``(mulligan_seed, player_id,
        mulls_taken)``. Two calls with the same agent + seed produce
        bit-identical post-mulligan states. Ignored when
        ``mulligans=False``.

    Returns
    -------
    tuple[GameState, mtg_bot_engine.GameState]
        ``(py_state, rust_state)``. With ``mulligans=False``: both
        have ``opening_hand_size`` cards in hand on each side. With
        ``mulligans=True``: both have ``agent.target_hand_size`` cards
        in hand on each side, library has the bottomed cards on its
        tail. ``step=Step.UNTAP``, ``turn=1``, ``active_player=0``,
        ``priority_player=0`` in either case.

    Raises
    ------
    ValueError
        If ``opening_hand_size`` exceeds the per-player library size
        (would underflow on the side-channel draw); or if a supplied
        ``mulligan_agent`` is passed without ``mulligans=True`` (a
        likely caller bug — the agent has no effect in that path).
    """
    if opening_hand_size < 0:
        raise ValueError(
            f"opening_hand_size must be >= 0 (got {opening_hand_size})"
        )

    if mulligans:
        # MulliganAgent is the gap-#2 substrate. The default agent is
        # the "always keep" policy — equivalent to mulligans=False on
        # the post-state, but exercises the mulligan-loop plumbing.
        if mulligan_agent is None:
            mulligan_agent = MulliganDeterministicAgent()
        # The mulligan path assumes the standard 7-card opening hand
        # (London mulligan only makes sense at 7). Refuse to silently
        # drop a non-default opening_hand_size in this path.
        if opening_hand_size != 7:
            raise ValueError(
                "setup_matched_game(mulligans=True) requires "
                "opening_hand_size=7 (London mulligan deals 7 cards "
                f"by rule); got opening_hand_size={opening_hand_size}"
            )
    else:
        if mulligan_agent is not None:
            raise ValueError(
                "mulligan_agent supplied with mulligans=False — the "
                "agent would have no effect. Pass mulligans=True to "
                "drive the mulligan loop."
            )

    # Apply the convenience seed if the DeckSpec doesn't already pin
    # a shared_rng_seed. Build a fresh DeckSpec (frozen-dataclass
    # contract) rather than mutating in place.
    if seed is not None and decks.shared_rng_seed is None:
        decks = DeckSpec(
            card_defs=decks.card_defs,
            p0_library=decks.p0_library,
            p1_library=decks.p1_library,
            shuffle_seed=decks.shuffle_seed,
            shared_rng_seed=seed,
        )

    # Validate library sizes BEFORE construction so a sub-7-card spec
    # surfaces as a ValueError here rather than as an IndexError deep
    # in the draw loop.
    if opening_hand_size > 0:
        if len(decks.p0_library) < opening_hand_size:
            raise ValueError(
                f"p0 library ({len(decks.p0_library)} cards) smaller "
                f"than opening_hand_size={opening_hand_size}"
            )
        if len(decks.p1_library) < opening_hand_size:
            raise ValueError(
                f"p1 library ({len(decks.p1_library)} cards) smaller "
                f"than opening_hand_size={opening_hand_size}"
            )

    py_state, rust_state = build_matched_states(decks)
    if opening_hand_size > 0:
        _draw_opening_hand_both(py_state, rust_state, n=opening_hand_size)

    if mulligans:
        _run_mulligan_loop_both(
            py_state, rust_state, mulligan_agent, mulligan_seed,
        )

    return py_state, rust_state


# ---------------------------------------------------------------------------
# Round-17 enhancement: production-shape decklists (closes one of the
# Phase 6 round-16 enhancement follow-ons).
#
# `load_production_deck` reads the live 17lands EoE deck pool
# (`data/17lands/eoe_decks.json.gz`, 130k decks, the same source
# self-play / iterate consumes) and returns one deck's card-name list.
# `production_deck_to_deckspec` converts a card-name list into a
# parity-bridge-compatible DeckSpec, **filtering out cards the harness
# can't model on both engines** (see filter rationale below).
#
# Why a filter step? CardDef intentionally carries only a minimal
# cross-engine surface (name / type / mana cost / pt / mana_produced /
# triggered_abilities-as-dict / subtypes). It does NOT carry
# spell_effect, activated_abilities (other than the auto-wired
# {T}: Add C for lands), static_abilities, keywords, ETB-counter
# triggers, warp/kicker/impending costs, etc. Production EoE creatures
# routinely carry triggered abilities + activated abilities + keywords
# that the parser materializes on Python's CardPrinting via the
# OracleParserCardSource path; Rust's `register_printing` accepts only
# the schema shapes documented in `cards.rs:parse_printing`.
#
# The pragmatic Round-17 path: filter the deck to cards that BOTH
# engines can register without effects/triggers/keywords/etc. that
# don't have a matching cross-engine bridge arm. The filter is
# conservative (drop on any rich field, not just unsupported ones)
# so future enhancements can flip a card from "filtered" to "bridged"
# by adding a CardDef field + bridge arm without churning the loader.
#
# What survives the filter on the EoE pool today:
#   * Basic lands (Forest/Island/Plains/Mountain/Swamp/Wastes).
#   * Vanilla creatures (no keywords, no triggered_abilities, no
#     activated_abilities, no static_abilities, no spell_effect,
#     no warp/kicker/impending).
# Per spot-check on the EoE pool: ~5 vanilla creatures total
# (Emissary Escort, Harmonious Grovestrider, Cosmogoyf, Magus of the
# Moon, Spectral Snatcher) plus the basic lands. Most decks contain
# a handful of basic lands + 0-2 vanilla creatures after filtering;
# the loader pads short decks with extra basics so trajectory tests
# always have ~60 cards to draw from.
#
# BLOCKED-RUST-EFFECT 42 (per task brief format): cards with rich
# effects (triggered abilities, activated abilities beyond mana,
# spell effects, warp/kicker/impending, room halves, planeswalker
# loyalty) are blocked at this layer because the CardDef bridge
# doesn't carry the fields needed to register them on both engines.
# Future enhancement: extend CardDef + bridge to carry the full
# CardPrinting surface, then drop the filter. Out of scope for the
# round-17 slice; the trajectory tests need a working production-
# shape deck NOW, not a complete production-shape deck.
# ---------------------------------------------------------------------------


# Mana-symbol -> (generic_count, [(color, count), ...]) parser. Reads a
# Scryfall-style mana-cost string like "{1}{G}{G}" and returns the parts
# CardDef needs. Empty string / None → (0, []).
_COLOR_LETTERS: frozenset[str] = frozenset({"W", "U", "B", "R", "G", "C"})


def _parse_mana_cost_string(s: str) -> tuple[int, tuple[tuple[str, int], ...]]:
    """Parse a Scryfall mana-cost string into ``(generic, colored)``.

    Returns ``(generic, ((color, count), ...))`` where ``colored`` is
    sorted by color for deterministic CardDef construction. Hybrid /
    Phyrexian / X / snow symbols are NOT supported — a card whose mana
    cost contains them is rejected by the deckspec converter
    (production filter responsibility).

    Raises ``ValueError`` on unrecognized mana symbols so the caller
    can fall back to filtering the card out.
    """
    if not s:
        return 0, ()
    generic = 0
    colored: dict[str, int] = {}
    # Tokenize on `{...}` segments.
    i = 0
    while i < len(s):
        if s[i] != "{":
            raise ValueError(f"unexpected char {s[i]!r} in mana cost {s!r}")
        end = s.index("}", i + 1)
        sym = s[i + 1:end]
        if sym.isdigit():
            generic += int(sym)
        elif sym in _COLOR_LETTERS:
            colored[sym] = colored.get(sym, 0) + 1
        else:
            # Hybrid (W/U), Phyrexian (W/P), X, snow (S), 2/W, etc.
            raise ValueError(
                f"unsupported mana symbol {sym!r} in cost {s!r} "
                f"(production filter should drop this card)"
            )
        i = end + 1
    return generic, tuple(sorted(colored.items()))


# Phase 6 carddef-substrate slice: keywords confirmed parity-clean by
# Phase 5/6 probes whose per-keyword combat behaviors both engines
# model byte-for-byte today. Restricting CardDef.keywords to this set
# at filter time keeps the production-deck loader honest — a card
# carrying any keyword OUTSIDE this set falls through to the filter
# drop path, the same as a card with a triggered ability or a non-
# vanilla activated ability. Extending this set should be done in
# lockstep with adding a new trajectory keyword probe + verifying
# Phase 5's selector for that keyword still passes.
#
# Per Phase 6 doc (rounds 17-18 keyword probes) + Phase 5 selector
# coverage, the following keywords are parity-clean:
#
#   * flying      — Phase 5 flying_selector (synthetic) + can be
#                   exercised via the round-17 generic injector.
#   * vigilance   — round-17 trajectory probe
#                   (test_vigilance_attacker_untaps_parity).
#   * lifelink    — round-17 trajectory probe
#                   (test_lifelink_combat_damage_to_self_parity).
#   * trample     — round-17 trajectory probe
#                   (test_trample_overflow_to_player_parity).
#   * haste       — round-18 trajectory probe
#                   (test_haste_attacker_no_summoning_sickness_parity).
#   * deathtouch  — round-18 trajectory probe
#                   (test_deathtouch_combat_damage_kills_blocker_parity).
#   * first strike  — Phase 5 first_strike_selector + cross-engine
#                     bridge pin (cross_engine.py:9381).
#   * double strike — round-18 trajectory probe
#                     (test_double_strike_combat_damage_doubles_parity).
#                     Note: the engines agree byte-for-byte despite
#                     a CR divergence on regular-damage spillover,
#                     documented in SEARCH_LIMITATIONS.md.
#   * menace, defender, indestructible — Phase 5 selectors exist;
#                     keep them in the safe set so cards carrying
#                     these keywords alongside flying / vigilance
#                     etc. (e.g. multi-keyword EoE creatures) still
#                     survive the filter.
#
# Keywords explicitly NOT in this set (and therefore disqualifying):
# flash (CR 702.8 cast-timing; trajectory probes for it land in a
# follow-up slice); reach (no Phase 5 probe yet); hexproof
# (Phase 5 selector exists but lifecycle is fragile in trajectory
# context); ward / protection / scry (cost-modifying / replacement
# effects out of CardDef's per-creature surface).
_SAFE_KEYWORDS: frozenset[str] = frozenset({
    "flying",
    "vigilance",
    "lifelink",
    "trample",
    "haste",
    "deathtouch",
    "first strike",
    "double strike",
    "menace",
    "defender",
    "indestructible",
})


# Phase 6 carddef-triggers slice: triggered-ability shapes that BOTH
# engines model byte-for-byte today via the existing
# ``cross_engine._ta_dict_to_python_predicate`` /
# ``_ta_dict_to_python_effect`` bridge plus Rust's
# ``parse_triggered_ability`` arm. Restricting CardDef.triggered_
# abilities to this set at filter time keeps the production-deck
# loader honest — a card carrying any triggered ability OUTSIDE this
# set falls through to the filter drop path, the same as the keywords
# check above.
#
# Each entry is a ``(event, predicate_kind, effect_kind)`` triple. A
# triggered_ability dict matches a safe-trigger entry when:
#   * ``ta["event"] == event``
#   * Either the safe-trigger entry's ``predicate_kind`` is None and
#     the dict's ``predicate`` is None / absent, OR the dict's
#     ``predicate["kind"]`` equals the safe-trigger's ``predicate_kind``.
#   * ``ta["effect"]["kind"] == effect_kind``.
#   * ``ta.get("once_per_turn", False) is False`` (once-per-turn
#     bookkeeping isn't probed yet on the trajectory shape; restrict to
#     the simpler default to keep the safe set tight).
#   * The effect dict carries no fields beyond a single payload key
#     matching its arm (``count`` for draw_cards/scry_n/surveil,
#     ``amount`` for gain_life — see ``_is_safe_trigger_dict`` for the
#     exact whitelist).
#
# The starter set is the SOURCE-IS-SELF predicate plus three leaf
# effects with the heaviest cross-engine probe coverage in Phase 5 /
# rounds 1-19 of Phase 6:
#
#   * ``draw_cards`` — exercised by every ETB-trigger slice since
#     Slice 3 (test_cross_engine_etb_triggers.py:_etb_draw_bear,
#     CE19 substrate, the very first ETB probe to land cross-engine).
#     Bridge arm: ``cross_engine._ta_dict_to_python_effect`` "draw_cards".
#   * ``gain_life`` — exercised by the gain_life bridge arm
#     (cross_engine._ta_dict_to_python_effect "gain_life") and the
#     cross-controller / cross-event probes (Phase 5).
#   * ``scry_n`` — exercised by round-16's scry_n bridge arm; the
#     cross-engine default-strategy contract is "keep all on top" on
#     both engines, so the no-op trajectory walk is bit-equal without
#     any agent setup (no PendingDecision pipeline to drain on the
#     post-resolve state).
#
# **Landfall extension (round-36 slice)** adds one compound predicate
# shape: ``"land_enters_controlled_by_you"`` — a sentinel canonical
# name for the AND-nested ``{"kind": "and", "left": {"kind":
# "subject_is_land"}, "right": {"kind": "controlled_by_you"}}`` dict
# both engines already parse (Rust at `cards.rs::parse_predicate` —
# subject-anchored type filters slice; Python via
# `cross_engine._ta_dict_to_python_predicate`'s "and" / "subject_is_
# land" / "controlled_by_you" arms). The canonical sentinel keeps
# the ``(event, predicate_kind, effect_kind)`` triple shape uniform
# across the allowlist; ``_is_safe_trigger_dict`` extracts the
# sentinel from the nested dict shape, and ``_python_ta_to_safe_dict``
# recognizes Python's parser-emitted ``And(Subject(slot=None,
# inner=IsLand()), Controlled(by=YOU, subject=None))`` predicate as
# the same canonical shape. Unlocked Eumidian Terrabotanist
# (2/3 {1}{G}, "Landfall — Whenever a land you control enters, you
# gain 1 life") on the production-deck loader.
#
# **Landfall + pump_self_until_eot extension (round-37 DDDD slice)**
# rides the SAME canonical landfall predicate sentinel and adds a
# SECOND safe leaf effect under it: ``pump_self_until_eot`` (bare
# shape — ``power_bonus`` / ``toughness_bonus`` fields, no
# ``granted_keywords`` rider). Cross-engine bridge support landed
# in round 22 (``cross_engine._ta_dict_to_python_effect`` "pump_
# self_until_eot" arm + cross-controller pump-self probe at commit
# 92ac9ec5 in test_parity_smoke.py). Unlocked Icecave Crasher
# (4/4 {3}{G}, Trample, "Landfall — Whenever a land you control
# enters, this creature gets +1/+0 until end of turn") on the
# production-deck loader. Sister consumer Remnant Elemental (1/2
# {1}{R}, Reach, +2/+0 UEOT landfall) carries the SAME bare
# ``PumpSelfUntilEOT`` effect shape but its ``Reach`` keyword is
# outside today's :data:`_SAFE_KEYWORDS` set — the production-deck
# filter still drops it. Adding ``Reach`` to the safe-keyword set
# is a follow-up slice (needs combat-side parity verification).
#
# **Landfall + draw_cards extension (this slice)** adds a THIRD
# safe leaf effect under the canonical landfall predicate
# sentinel: ``draw_cards`` (bare shape — single ``count`` payload
# key; mirrors the source_is_self+draw_cards starter entry's
# allowed-keys whitelist). Cross-engine bridge support pre-existed
# in round 1 of Phase 6 carddef-triggers (``cross_engine._ta_dict
# _to_python_effect`` "draw_cards" arm) and the Python recognizer
# in ``_python_ta_to_safe_dict`` already maps ``DrawCards`` to the
# canonical ``{"kind": "draw_cards", "count": int}`` dict shape;
# only the landfall arm's ``safe_effect_kinds`` tuple needed the
# extension to admit the predicate-effect product. **No real-EoE
# consumer admitted today**: the EoE landfall pool's only
# draw-bearing card is Tannuk, Memorial Ensign, whose effect is
# the bespoke ``TannukEnsignLandfallEffect`` (deal-damage to each
# opponent + second-time-bonus draw), NOT a bare ``DrawCards``
# leaf — Tannuk continues to be dropped by the production-deck
# filter under this slice. Substrate is pre-positioned for any
# future EoE / standard-format printing carrying a bare
# landfall+draw shape (the parser-emitted equivalent of MH3 Hare
# Apparent's "+1/+0 and draw" or a clean "Landfall — draw a card"
# creature) so the next slice landing such a card need not extend
# the allowlist again; pinned by reject-path tests so the predicate
# -effect product gate stays honest in the meantime.
# Tannuk, Memorial Ensign / Mightform Harmonizer / Genemorph Imago
# / Eusocial Engineering / Glacier Godmaw / Icetill Explorer /
# Territorial Bruntar carry the same landfall predicate but pair
# it with bespoke / unsupported effect shapes (deal-damage +
# second-time-bonus, conditional-threshold pump, double-target-
# power, create-token, exile-and-may-cast, mill-a-card); each
# needs its own sister slice. Mightform's substrate is primed by
# round-37 CCCC (commit c7c095ed) on the free-form CardDef bridge
# path — but the production-deck filter would still drop it on
# the ``Warp`` keyword (outside :data:`_SAFE_KEYWORDS`) AND the
# ``requires_target=True`` agent-seating gap that the loader
# doesn't fill, so the matching ``double_target_creatures_power_
# ueot`` allowlist entry waits for those follow-ups.
#
# Triggers explicitly NOT in this set (and therefore disqualifying):
# ``deal_damage`` / ``deal_damage_any_target`` (target-pick at PUSH
# time requires an agent shim — the production-deck loader doesn't
# seat one); ``create_token`` (needs token-printing pre-registration
# via ``register_token_printing``); ``surveil`` (PendingDecision
# substrate requires an explicit auto-resolve drain on the Rust side
# to mirror Python's no-agent default — a follow-up slice once the
# trajectory walk drains pending decisions consistently);
# ``discard_self`` / ``each_opponent_discards`` (requires an agent on
# the discarding player to mirror Rust's hand[0] pick); modal /
# sequence / if_you_do composers (composer bridge arms exist but
# nesting them under ETB triggers compounds the bridge-arm surface
# beyond the leaf-effect floor this slice ships).
#
# Extending this set is a lockstep operation — each new entry needs
# (a) the matching cross-engine bridge arm to already exist on both
# engines, and (b) a trajectory probe that demonstrates the
# end-to-end firing parity. See ``test_carddef_safe_etb_trigger_*``
# in tests/test_trajectory.py and the synthetic real-game probe in
# test_trajectory_parity.py for the Phase 6 ENTERS+IsSelf+DrawCards
# probe shape; the landfall extension's analogue is
# ``test_carddef_landfall_safe_etb_trigger_fires_on_land_play_parity``.
_SAFE_TRIGGERS: frozenset[tuple[str, Optional[str], str]] = frozenset({
    ("enters", "source_is_self", "draw_cards"),
    ("enters", "source_is_self", "gain_life"),
    ("enters", "source_is_self", "scry_n"),
    # Landfall — "Whenever a land you control enters, ...". Compound
    # predicate sentinel; see ``_is_safe_trigger_dict`` /
    # ``_python_ta_to_safe_dict`` for the canonical-vs-nested shape
    # mapping. The canonical landfall predicate now rides THREE safe
    # leaf effects:
    #   * ``gain_life`` — admits Eumidian Terrabotanist (2/3 {1}{G},
    #     gain 1 life on land enter). Landed in the round-36
    #     landfall extension slice.
    #   * ``pump_self_until_eot`` — admits Icecave Crasher (4/4
    #     {3}{G}, +1/+0 until end of turn on land enter). Landed in
    #     the round-37 DDDD slice (commit 94ea1ef3 / 42a5eec9). The
    #     bare ``PumpSelfUntilEOT(power_bonus, toughness_bonus)``
    #     shape (no granted_keywords rider) is what Icecave
    #     Crasher's parser-emitted Landfall trigger uses; sister
    #     consumer Remnant Elemental (Reach, +2/+0 UEOT) carries
    #     the same effect shape but its ``Reach`` keyword is
    #     outside today's :data:`_SAFE_KEYWORDS` set so the
    #     production-deck filter still drops it.
    #   * ``draw_cards`` — this slice. Pinned-by-reject-path-test
    #     today: the ONLY EoE landfall consumer carrying a draw
    #     leaf is Tannuk, Memorial Ensign, but Tannuk's effect is
    #     the bespoke ``TannukEnsignLandfallEffect`` (deal-damage
    #     to each opponent + second-time-bonus draw), NOT a bare
    #     ``DrawCards`` — so no real-EoE consumer is admitted on
    #     EoE today. Substrate is pre-positioned for any future
    #     EoE / standard-format landfall+draw printing (the
    #     equivalent of MH3 Hare Apparent's "+1/+0 and draw" or a
    #     parser-emitted bare landfall-draw card) so the next slice
    #     dropping such a card need not extend the allowlist again.
    #     Cross-engine bridge support pre-existed in round 1 of
    #     Phase 6 carddef-triggers (``cross_engine._ta_dict_to_
    #     python_effect`` "draw_cards" arm + the trajectory probe
    #     at ``test_carddef_safe_etb_trigger_*`` exercising the
    #     bare draw effect under source_is_self); the recognizer
    #     ``_python_ta_to_safe_dict`` already maps ``DrawCards``
    #     to the ``{"kind": "draw_cards", "count": int}`` dict
    #     shape — only the safe-effect-kinds tuple under the
    #     landfall predicate arm needs the extension.
    # Tannuk Memorial Ensign / Mightform Harmonizer / Genemorph
    # Imago / Eusocial Engineering / Glacier Godmaw / Icetill
    # Explorer / Territorial Bruntar carry the same predicate but
    # pair it with bespoke / unsupported effect shapes (deal-damage
    # + second-time-bonus, conditional-threshold pump,
    # double-target-power, create-token, exile-and-may-cast,
    # mill-a-card) — each needs its own sister slice. Mightform
    # Harmonizer's landfall+double-power clause has its substrate
    # primed by the round-37 CCCC slice (commit c7c095ed) on the
    # free-form CardDef bridge path; ``double_target_creatures_
    # power_ueot`` is NOT yet in the allowlist here because
    # Mightform also carries ``Warp`` (outside :data:`_SAFE_KEY
    # WORDS`) and would still be dropped by the bridge-simple
    # filter — adding ``double_target_creatures_power_ueot`` here
    # without a clean non-Warp consumer would be preventative-only
    # but for an effect whose bridge round-trip requires the
    # ``requires_target=True`` PUSH-time pick agent that the
    # production-deck loader doesn't seat; a follow-up slice once
    # the loader grows targeting-agent seating.
    ("enters", "land_enters_controlled_by_you", "gain_life"),
    ("enters", "land_enters_controlled_by_you", "pump_self_until_eot"),
    ("enters", "land_enters_controlled_by_you", "draw_cards"),
})


# Canonical name for the compound landfall predicate shape — Rust's
# ``Predicate::And(Predicate::SubjectIsLand, Predicate::ControlledByYou)``
# / Python's ``And(Subject(slot=None, inner=IsLand()),
# Controlled(by=YOU, subject=None))``. Used as the sentinel
# ``predicate_kind`` token in ``_SAFE_TRIGGERS`` so the compound
# shape composes uniformly with the leaf entries (e.g.
# ``("enters", "source_is_self", "draw_cards")`` shape).
_LANDFALL_PREDICATE_KIND = "land_enters_controlled_by_you"


# Effect arms in the safe set — each arm's allowed keys (other than
# ``"kind"``). Used by ``_is_safe_trigger_dict`` to reject any
# trigger carrying an unrecognized effect-payload field that the
# bridge would silently drop.
#
# ``pump_self_until_eot`` carries two payload keys: ``power_bonus``
# and ``toughness_bonus`` (mirrors Rust's ``PumpSelfUntilEOT
# { power_bonus: i32, toughness_bonus: i32 }``). Both are optional
# in Rust's parser (default 0), but the safe-trigger filter requires
# at least one to be present (a ``(0, 0)`` pump is a pure no-op on
# both engines so it's harmless if it leaks through, but a typed-
# absent payload would be a fixture smell). Riders that the bare
# bridge does NOT carry (``granted_keywords``, etc.) are absent
# here — the parser emits the bare-shape trigger for Icecave
# Crasher / Remnant Elemental, and any future +X/+Y-and-gains-
# keyword landfall consumer would have to ride a separate composer
# arm (out of scope for this slice).
_SAFE_EFFECT_KEYS: dict[str, frozenset[str]] = {
    "draw_cards": frozenset({"kind", "count"}),
    "gain_life": frozenset({"kind", "amount"}),
    "scry_n": frozenset({"kind", "count"}),
    "pump_self_until_eot": frozenset(
        {"kind", "power_bonus", "toughness_bonus"}
    ),
}


def _is_landfall_predicate_dict(pred: object) -> bool:
    """True iff ``pred`` is the canonical landfall compound predicate
    dict shape: ``{"kind": "and", "left": {"kind": "subject_is_land"},
    "right": {"kind": "controlled_by_you"}}``.

    Strict on the left/right ordering and on the exact two-arm shape
    — that ordering is what the parser emits today
    (``cards/parser/triggers.py:603-1266``) and what cross_engine's
    bridge translates onto each engine via the ``and`` /
    ``subject_is_land`` / ``controlled_by_you`` arms in
    ``_ta_dict_to_python_predicate``. Both engines accept the dict
    without raising; the strict check here keeps the safe-trigger
    gate honest by treating any other compound shape (``Or`` /
    ``Not(IsLand)`` / nested-AND / different ordering) as unsafe
    until its own slice lands.
    """
    if not isinstance(pred, dict):
        return False
    if set(pred.keys()) != {"kind", "left", "right"}:
        return False
    if pred.get("kind") != "and":
        return False
    left = pred.get("left")
    right = pred.get("right")
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    if tuple(left.keys()) != ("kind",) or tuple(right.keys()) != ("kind",):
        return False
    return (
        left.get("kind") == "subject_is_land"
        and right.get("kind") == "controlled_by_you"
    )


def _is_safe_trigger_dict(ta_dict: dict) -> bool:
    """True iff ``ta_dict`` matches one of the :data:`_SAFE_TRIGGERS`
    shapes.

    Validates the four-tuple (event, predicate-kind, effect-kind,
    once_per_turn) as well as the effect-payload key whitelist (see
    :data:`_SAFE_EFFECT_KEYS`). Refuses any ``ta_dict`` carrying
    extra top-level keys beyond ``event`` / ``predicate`` / ``effect``
    / ``once_per_turn`` so a future schema extension doesn't silently
    pass through the loader and produce cross-engine drift.
    """
    if not isinstance(ta_dict, dict):
        return False
    allowed_top = {"event", "predicate", "effect", "once_per_turn"}
    if any(k not in allowed_top for k in ta_dict):
        return False
    if ta_dict.get("once_per_turn", False):
        return False
    event = ta_dict.get("event")
    if not isinstance(event, str):
        return False
    pred = ta_dict.get("predicate")
    if pred is None:
        pred_kind: Optional[str] = None
    elif isinstance(pred, dict) and tuple(pred.keys()) == ("kind",):
        pred_kind = pred.get("kind")
    elif _is_landfall_predicate_dict(pred):
        # Landfall extension: compound dict
        # ``{"kind": "and",
        #    "left": {"kind": "subject_is_land"},
        #    "right": {"kind": "controlled_by_you"}}``
        # collapses to the canonical sentinel kind so it composes
        # with the leaf-shape allowlist entries. Strict on the
        # left/right ordering and on the absence of any extra
        # top-level keys — that ordering is exactly what the
        # parser emits today (``cards/parser/triggers.py:603-1266``)
        # and what cross_engine's bridge arms parse on both engines.
        pred_kind = _LANDFALL_PREDICATE_KIND
    else:
        # Any other predicate carrying nested fields (subject, inner,
        # left, right, ...) is NOT in the safe set.
        return False
    eff = ta_dict.get("effect")
    if not isinstance(eff, dict):
        return False
    eff_kind = eff.get("kind")
    if not isinstance(eff_kind, str):
        return False
    triple = (event, pred_kind, eff_kind)
    if triple not in _SAFE_TRIGGERS:
        return False
    allowed_eff_keys = _SAFE_EFFECT_KEYS.get(eff_kind)
    if allowed_eff_keys is None:
        return False
    if any(k not in allowed_eff_keys for k in eff):
        return False
    return True


def _python_ta_to_safe_dict(ta) -> Optional[dict]:
    """Convert a Python ``TriggeredAbility`` back to the Rust-shape
    dict iff it matches one of the :data:`_SAFE_TRIGGERS` shapes.

    Returns ``None`` for triggers whose shape isn't on the safe list.
    The production-deck loader uses this as the gate: a creature
    every one of whose Python-parsed triggered abilities round-trips
    through this helper passes the bridge-simple filter and lands in
    the cross-engine harness with its triggered abilities intact.

    Round-trip invariant: the dict this returns satisfies
    :func:`_is_safe_trigger_dict` AND the Rust + Python bridge arms
    consume it without raising. The dict shape mirrors what a CardDef
    written by a probe author would carry directly — same field
    spellings as :func:`cross_engine._ta_dict_to_python_triggered_ability`
    consumes.
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import (
        And,
        Controlled,
        IsSelf,
        Event,
        Subject,
        YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.generic.library_lookat import Scry
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT

    if not isinstance(ta, TriggeredAbility):
        return None
    if ta.once_per_turn:
        return None
    # Event must be ENTERS for the starter safe set.
    if ta.event is not Event.ENTERS:
        return None
    # Recognize one of the safe predicate shapes; produce the
    # corresponding round-trip dict (or bail if no match).
    pred = ta.predicate
    pred_dict: Optional[dict] = None
    safe_effect_kinds: tuple[str, ...] = ()
    if isinstance(pred, IsSelf) and pred.subject is None:
        # ``IsSelf`` (default-slot form): "source_is_self" canonical
        # kind. Three leaf effects in the safe set.
        pred_dict = {"kind": "source_is_self"}
        safe_effect_kinds = ("draw_cards", "gain_life", "scry_n")
    elif _is_landfall_predicate_python(pred):
        # Landfall extension: compound
        # ``And(Subject(slot=None, inner=IsLand()),
        #       Controlled(by=YOU, subject=None))``
        # — emit the canonical AND-nested dict shape both engines'
        # bridges already translate. THREE safe leaves today:
        # ``gain_life`` (Eumidian Terrabotanist, round-36 slice),
        # ``pump_self_until_eot`` (Icecave Crasher, round-37 DDDD
        # slice — the bare ``power_bonus`` / ``toughness_bonus``
        # shape with NO ``granted_keywords`` rider; sister Remnant
        # Elemental carries the same bare shape but is dropped by
        # the ``_SAFE_KEYWORDS`` filter on its ``Reach`` keyword),
        # and ``draw_cards`` (this slice — preventative substrate
        # extension; no EoE consumer admitted today since Tannuk
        # Memorial Ensign's draw rider is the bespoke
        # ``TannukEnsignLandfallEffect`` second-time-bonus shape,
        # NOT a bare ``DrawCards`` leaf; pinned by reject-path
        # tests so the predicate-effect product gate stays honest).
        # Other landfall consumers (Tannuk, Mightform Harmonizer,
        # Genemorph Imago, Eusocial Engineering, Glacier Godmaw,
        # Icetill Explorer, Territorial Bruntar) need their own
        # leaf-effect bridge arms before they can ride this
        # predicate.
        pred_dict = {
            "kind": "and",
            "left": {"kind": "subject_is_land"},
            "right": {"kind": "controlled_by_you"},
        }
        safe_effect_kinds = (
            "gain_life", "pump_self_until_eot", "draw_cards",
        )
    if pred_dict is None:
        return None
    # Effect must be one of the safe leaves AND in the safe set for
    # this predicate (the predicate-effect product is enforced by
    # ``_SAFE_TRIGGERS``, not the effect kinds alone — e.g.
    # draw_cards under landfall is unsafe today).
    eff = ta.effect
    if isinstance(eff, DrawCards):
        eff_kind = "draw_cards"
        eff_dict: dict = {"kind": "draw_cards", "count": int(eff.amount)}
    elif isinstance(eff, GainLife):
        eff_kind = "gain_life"
        eff_dict = {"kind": "gain_life", "amount": int(eff.amount)}
    elif isinstance(eff, Scry):
        eff_kind = "scry_n"
        # Python's ``Scry`` exposes the count as ``amount``; the dict
        # shape uses Rust's spelling ``count``.
        eff_dict = {"kind": "scry_n", "count": int(eff.amount)}
    elif isinstance(eff, PumpSelfUntilEOT):
        # Bare-shape PumpSelfUntilEOT (no ``granted_keywords``
        # rider). Python's class carries an additional
        # ``granted_keywords: frozenset[str]`` field
        # (``effects/generic/pump.py:632``) that Rust's
        # ``PumpSelfUntilEOT { power_bonus, toughness_bonus }``
        # variant does NOT represent — gate on the rider being
        # empty so a parser-emitted "Landfall — this creature gets
        # +1/+0 and gains haste UEOT" doesn't slip through with the
        # keyword silently dropped on the cross-engine round trip.
        # No EoE landfall consumer carries the rider today (Icecave
        # Crasher and Remnant Elemental both emit the bare shape),
        # so this gate simply pins the contract.
        if eff.granted_keywords:
            return None
        eff_kind = "pump_self_until_eot"
        eff_dict = {
            "kind": "pump_self_until_eot",
            "power_bonus": int(eff.power_bonus),
            "toughness_bonus": int(eff.toughness_bonus),
        }
    else:
        return None
    if eff_kind not in safe_effect_kinds:
        # Effect kind is a safe leaf in the abstract but not safe
        # under this predicate — e.g. a parser-emitted "Landfall —
        # draw a card" would land here once such a card exists in
        # the EoE pool. Out of the safe set until the matching
        # ``_SAFE_TRIGGERS`` entry lands.
        return None
    return {
        "event": "enters",
        "predicate": pred_dict,
        "effect": eff_dict,
    }


def _is_landfall_predicate_python(pred: object) -> bool:
    """True iff ``pred`` is the canonical landfall compound predicate
    on the Python side: ``And(Subject(slot=None, inner=IsLand()),
    Controlled(by=YOU, subject=None))``.

    Mirrors :func:`_is_landfall_predicate_dict` on the Python-object
    side. Strict on operand ordering AND on the optional-slot
    fields' default values — anything else (a non-default subject
    slot, ``Or``-form, an inner type other than ``IsLand``, a
    Controlled-by-OPPONENT) is out of the safe set until its own
    slice lands.
    """
    from mtg_bot.effects.predicates import (
        And,
        Controlled,
        Subject,
        YOU,
    )
    from mtg_bot.effects.object_predicates import IsLand

    if not isinstance(pred, And):
        return False
    left = pred.left
    right = pred.right
    if not isinstance(left, Subject) or left.slot is not None:
        return False
    if not isinstance(left.inner, IsLand):
        return False
    if not isinstance(right, Controlled):
        return False
    if right.by is not YOU:
        return False
    if right.subject is not None:
        return False
    return True


def _printing_is_bridge_simple_creature(printing) -> bool:
    """True if a CardPrinting is a vanilla bridge-supported creature.

    A "bridge-simple" creature has:
      * "Creature" in card_types
      * Non-None power and toughness
      * Either no keywords, OR every keyword in :data:`_SAFE_KEYWORDS`
        (Phase 6 carddef-substrate slice — see the constant's docstring
        for the per-keyword parity provenance).
      * Either no triggered_abilities, OR every triggered_ability
        round-trips through :func:`_python_ta_to_safe_dict` (Phase 6
        carddef-triggers slice — see :data:`_SAFE_TRIGGERS` for the
        per-shape parity provenance).
      * No activated_abilities (other than the empty default)
      * No static_abilities
      * No spell_effect (creatures don't have one anyway, but be
        defensive — flip cards / mdfcs land here)
      * No warp / kicker / impending / room halves / planeswalker
        loyalty
      * Mana cost is parseable into (generic, colored) — no hybrid /
        phyrexian / X / snow.
    """
    if "Creature" not in printing.card_types:
        return False
    if printing.power is None or printing.toughness is None:
        return False
    if printing.keywords and not printing.keywords.issubset(_SAFE_KEYWORDS):
        return False
    if printing.triggered_abilities:
        # Phase 6 carddef-triggers slice: a creature with one or more
        # triggered abilities passes the filter only if EVERY ability
        # round-trips cleanly through the safe-trigger gate. Any single
        # unsafe ability disqualifies the whole printing — there's no
        # "partial admit" semantic since the bridge has to thread the
        # full triggered-abilities tuple to both engines.
        for ta in printing.triggered_abilities:
            if _python_ta_to_safe_dict(ta) is None:
                return False
    if printing.activated_abilities:
        return False
    if printing.static_abilities:
        return False
    if printing.spell_effect is not None:
        return False
    if printing.warp_cost or printing.kicker_cost or printing.impending_cost:
        return False
    if printing.room_halves:
        return False
    if printing.loyalty is not None:
        return False
    if printing.cost_reductions or printing.external_cost_reductions:
        return False
    if printing.station_threshold:
        return False
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True


def _printing_is_bridge_basic_land(printing) -> bool:
    """True if a CardPrinting is a basic Land the harness can model.

    Basic lands carry the ``"Basic"`` supertype + ``"Land"`` card type
    + a single ``produces`` color. The CardDef bridge auto-wires the
    ``{T}: Add {C}`` mana ability via the ``mana_produced`` field so
    activate_ability(land_id, 0) works on both engines.

    Non-basic lands (utility lands, shock lands, planet lands) are
    rejected here because they typically carry activated abilities
    and/or ETB triggers that CardDef can't represent.
    """
    if "Land" not in printing.card_types:
        return False
    if "Basic" not in printing.supertypes:
        return False
    if not printing.produces:
        return False
    if len(printing.produces) != 1:
        return False
    if printing.activated_abilities:
        # Basic lands SHOULD have no activated_abilities (the engine
        # auto-wires the mana ability from `produces`); a parser-shipped
        # ability would conflict with the CardDef-side auto-wire.
        return False
    if printing.triggered_abilities:
        return False
    if printing.static_abilities:
        return False
    return True


def _printing_to_card_def(printing) -> CardDef:
    """Convert a bridge-supported CardPrinting into a CardDef.

    Pre-condition: printing must pass either
    :func:`_printing_is_bridge_simple_creature` or
    :func:`_printing_is_bridge_basic_land`. Otherwise the conversion
    drops fields the bridge can't carry, producing a printing that
    silently disagrees across engines.
    """
    if _printing_is_bridge_basic_land(printing):
        produces = next(iter(printing.produces))
        return CardDef(
            name=printing.name,
            card_type="Land",
            mana_produced=(produces,),
        )
    if _printing_is_bridge_simple_creature(printing):
        generic, colored = _parse_mana_cost_string(printing.mana_cost_str or "")
        # Phase 6 carddef-substrate slice: thread the printing's
        # keywords through to the CardDef in deterministic-sorted
        # order. The filter (above) already guarantees every entry is
        # in ``_SAFE_KEYWORDS``; the bridge in
        # ``cross_engine.build_python_state`` /
        # ``cross_engine.build_rust_state`` re-materializes the same
        # set on each engine, with the underscore-vs-space convention
        # translation handled on the Rust side.
        #
        # Phase 6 carddef-triggers slice: thread the printing's
        # triggered abilities through to the CardDef in their dict
        # round-trip shape. The filter (above) already guarantees
        # every entry round-trips cleanly via
        # :func:`_python_ta_to_safe_dict`; the bridge in
        # ``cross_engine.build_python_state`` re-materializes them
        # via the existing
        # ``_ta_dict_to_python_triggered_ability`` translator and
        # ``cross_engine.build_rust_state`` passes the same dict
        # tuple to Rust's ``register_printing(triggered_abilities=)``
        # parser. Empty tuple is a no-op (every pre-triggers fixture
        # path ends up here unchanged).
        triggered_abilities = tuple(
            _python_ta_to_safe_dict(ta)
            for ta in printing.triggered_abilities
        )
        return CardDef(
            name=printing.name,
            card_type="Creature",
            mana_cost_generic=generic,
            mana_cost_colored=colored,
            power=printing.power,
            toughness=printing.toughness,
            keywords=tuple(sorted(printing.keywords)),
            triggered_abilities=triggered_abilities,
        )
    raise ValueError(
        f"printing {printing.name!r} is not bridge-supported; "
        f"call _printing_is_bridge_* first to filter."
    )


def load_production_deck(
    archetype: int = 0,
    deck_pool_path: Optional[pathlib.Path] = None,
) -> list[str]:
    """Load one real EoE deck from the 17lands deck pool.

    Returns the deck's card-name list (typically 40 cards — limited /
    sealed deck size). The card names are direct Scryfall names that
    the active CardSource (OracleParserCardSource) resolves via
    ``get_printings()``.

    Parameters
    ----------
    archetype : int, default 0
        Index into the deck pool. The 17lands JSON is a flat list of
        deck dicts; ``archetype`` is the positional index. Trivially
        deterministic — index 0 always returns the same deck. Pass a
        different index for a different deck.
    deck_pool_path : pathlib.Path, optional
        Path to the gzipped deck pool. Defaults to
        :data:`DEFAULT_PRODUCTION_DECK_POOL`. Resolved relative to the
        repo root if not absolute.

    Returns
    -------
    list[str]
        The deck's 40-card name list. Order matches the JSON.

    Raises
    ------
    FileNotFoundError
        If the deck pool file is missing.
    IndexError
        If ``archetype`` is out of range for the deck pool.
    """
    if deck_pool_path is None:
        # Resolve relative to the repo root (the parity module sits
        # three dirs deep under src/mtg_bot/parity/, so go up four).
        repo_root = pathlib.Path(__file__).resolve().parents[3]
        deck_pool_path = repo_root / DEFAULT_PRODUCTION_DECK_POOL
        if not deck_pool_path.exists():
            # Worktree fallback: data/ is gitignored, so a freshly-
            # checked-out worktree won't have the pool. Look for it in
            # a sibling `mtg-bot/` main checkout (the project's
            # canonical worktree layout per the repo's CLAUDE.md).
            sibling = repo_root.parent.parent / "mtg-bot" / DEFAULT_PRODUCTION_DECK_POOL
            if sibling.exists():
                deck_pool_path = sibling
    if not deck_pool_path.exists():
        raise FileNotFoundError(
            f"production deck pool not found at {deck_pool_path}; "
            f"regenerate via scripts/fetch_eoe.py + the 17lands "
            f"sync pipeline if it's missing."
        )
    with gzip.open(deck_pool_path, "rt") as fh:
        data = json.load(fh)
    if archetype < 0 or archetype >= len(data):
        raise IndexError(
            f"archetype={archetype} out of range for deck pool with "
            f"{len(data)} decks"
        )
    return list(data[archetype]["cards"])


def production_deck_to_deckspec(
    p0_card_names: list[str],
    p1_card_names: Optional[list[str]] = None,
    *,
    shared_rng_seed: Optional[int] = None,
    pad_to_size: int = 60,
    pad_with: str = "Forest",
) -> DeckSpec:
    """Build a parity-bridge DeckSpec from real EoE deck card-name lists.

    Filters each card-name list to the bridge-supported subset (basic
    lands + vanilla creatures), builds the union CardDef registry, and
    optionally pads each filtered library with extra basic lands so
    short post-filter decks still have enough cards to drive a multi-
    turn trajectory test. Mirror-match defaults: when ``p1_card_names``
    is None, p1 gets the same filtered library as p0.

    Parameters
    ----------
    p0_card_names : list[str]
        p0's deck card-name list (e.g. from
        :func:`load_production_deck`). Card names that don't resolve
        in the active CardSource OR don't pass the bridge-support
        filter are silently dropped.
    p1_card_names : list[str], optional
        p1's deck card-name list. When None, p1 receives a copy of
        p0's filtered library — produces a mirror-match for clean
        trajectory probes.
    shared_rng_seed : int, optional
        Forwarded to :class:`DeckSpec.shared_rng_seed`. When set,
        both engines shuffle to the same library permutation.
    pad_to_size : int, default 60
        Target deck size after filter+pad. If a player's filtered
        library has fewer cards than this, the remainder is padded
        with copies of ``pad_with``. Set to 0 to disable padding (use
        the post-filter library size as-is).
    pad_with : str, default "Forest"
        Card name to use for padding. Must resolve to a bridge-
        supported basic land in the active CardSource. The default is
        "Forest" because the EoE pool's mono-G decks are the most
        likely test target; switch to the deck's primary color for
        non-green archetypes.

    Returns
    -------
    DeckSpec
        Ready to feed into :func:`setup_matched_game`.

    Raises
    ------
    ValueError
        If ``pad_with`` doesn't resolve to a bridge-supported basic
        land in the active CardSource, OR if BOTH players' filtered
        libraries are empty (would produce a zero-card DeckSpec).

    Notes
    -----
    Cards filtered out are NOT logged here — the loader's job is to
    produce a clean DeckSpec, not to audit the filter. To inspect
    which cards a particular EoE deck loses to the filter, use
    :func:`_filter_deck_to_bridge_supported` directly.
    """
    from mtg_bot.cards.source import get_active_source
    src = get_active_source()
    printings = src.get_printings()

    # Validate the pad_with card upfront so a silent zero-pad later
    # surfaces as a clean error.
    pad_printing = printings.get(pad_with)
    if pad_printing is None or not _printing_is_bridge_basic_land(pad_printing):
        raise ValueError(
            f"pad_with={pad_with!r} does not resolve to a bridge-"
            f"supported basic land in the active CardSource; pick a "
            f"basic land name (Forest/Island/Plains/Mountain/Swamp)."
        )
    pad_card_def = _printing_to_card_def(pad_printing)

    p0_filtered, p0_card_defs = _filter_deck_to_bridge_supported(
        p0_card_names, printings,
    )
    if p1_card_names is None:
        p1_filtered = list(p0_filtered)
        p1_card_defs = list(p0_card_defs)
    else:
        p1_filtered, p1_card_defs = _filter_deck_to_bridge_supported(
            p1_card_names, printings,
        )

    # Pad each side to pad_to_size with copies of pad_with.
    if pad_to_size > 0:
        if len(p0_filtered) < pad_to_size:
            p0_filtered.extend(
                [pad_with] * (pad_to_size - len(p0_filtered))
            )
        if len(p1_filtered) < pad_to_size:
            p1_filtered.extend(
                [pad_with] * (pad_to_size - len(p1_filtered))
            )

    # Refuse zero-card libraries even if both filters dropped everything.
    if not p0_filtered or not p1_filtered:
        raise ValueError(
            "production deck filter produced an empty library on at "
            "least one side; check that the input decks contain at "
            "least one bridge-supported card OR set pad_to_size>0."
        )

    # Union CardDef registry: dedup by name (CardDef is frozen+hashable
    # but two CardDefs with the same name from different decks should
    # be the same object — bridge-supported names always have a single
    # representation in the active CardSource).
    union_card_defs: dict[str, CardDef] = {}
    for cd in p0_card_defs + p1_card_defs:
        union_card_defs[cd.name] = cd
    # Always include the pad card (even when both decks happen to
    # already have it — dict-dedup makes this a no-op then).
    union_card_defs.setdefault(pad_card_def.name, pad_card_def)

    return DeckSpec(
        card_defs=tuple(union_card_defs.values()),
        p0_library=tuple(p0_filtered),
        p1_library=tuple(p1_filtered),
        shared_rng_seed=shared_rng_seed,
    )


def _filter_deck_to_bridge_supported(
    card_names: list[str], printings: dict,
) -> tuple[list[str], list[CardDef]]:
    """Filter a card-name list to bridge-supported names + CardDefs.

    Returns ``(filtered_names, card_defs)`` where:

      * ``filtered_names`` is the input list with unsupported names
        dropped, in original order. Duplicates are preserved (a 4x
        Forest in the input stays 4x in the output).
      * ``card_defs`` is the unique CardDef list (deduped by name) the
        filtered names reference.

    Internal helper for :func:`production_deck_to_deckspec`.
    """
    filtered_names: list[str] = []
    seen_card_defs: dict[str, CardDef] = {}
    for name in card_names:
        printing = printings.get(name)
        if printing is None:
            continue
        if not (
            _printing_is_bridge_basic_land(printing)
            or _printing_is_bridge_simple_creature(printing)
        ):
            continue
        if name not in seen_card_defs:
            seen_card_defs[name] = _printing_to_card_def(printing)
        filtered_names.append(name)
    return filtered_names, list(seen_card_defs.values())


def setup_matched_game_from_real_decks(
    p0_card_names: list[str],
    p1_card_names: Optional[list[str]] = None,
    *,
    shared_rng_seed: Optional[int] = None,
    pad_to_size: int = 60,
    pad_with: str = "Forest",
    mulligans: bool = False,
    opening_hand_size: int = 7,
    mulligan_agent: Optional[MulliganDeterministicAgent] = None,
    mulligan_seed: int = 0,
):
    """One-shot: convert real EoE decklists → DeckSpec → matched states.

    Convenience wrapper that composes
    :func:`production_deck_to_deckspec` + :func:`setup_matched_game`.
    Same return contract as :func:`setup_matched_game`. Use this
    entrypoint for trajectory tests that want to drive on real EoE
    deck shapes; use the two-step path
    (``production_deck_to_deckspec`` then ``setup_matched_game``)
    when the caller wants to inspect / mutate the DeckSpec between
    steps.
    """
    spec = production_deck_to_deckspec(
        p0_card_names,
        p1_card_names,
        shared_rng_seed=shared_rng_seed,
        pad_to_size=pad_to_size,
        pad_with=pad_with,
    )
    return setup_matched_game(
        spec,
        mulligans=mulligans,
        opening_hand_size=opening_hand_size,
        mulligan_agent=mulligan_agent,
        mulligan_seed=mulligan_seed,
    )
