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
#   * reach         — round-45 trajectory probe
#                     (test_reach_blocker_blocks_flying_attacker_parity).
#                     Both engines model reach as a blocker-side
#                     gate-opener in their flying-block legality
#                     check (Python: ``combat.can_block`` —
#                     ``"flying" in blocker_kws or "reach" in
#                     blocker_kws``; Rust: ``state_ops_combat.rs``
#                     ``declare_blocker`` — ``blocker_has_flying ||
#                     blocker_has_reach``). Reach on the ATTACKER is
#                     a no-op for blocking purposes on both engines
#                     (a reach attacker is treated as ground for
#                     block-legality), matching CR 702.17.
#
# Keywords explicitly NOT in this set (and therefore disqualifying):
# flash (CR 702.8 cast-timing; trajectory probes for it land in a
# follow-up slice); hexproof (Phase 5 selector exists but lifecycle
# is fragile in trajectory context); ward / protection / scry (cost-
# modifying / replacement effects out of CardDef's per-creature
# surface).
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
    "reach",
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
    # Surveil extension (round-42 carddef-triggers slice). Adds the
    # bare-shape ``surveil`` effect (``count`` payload key only — no
    # ``use_artifact_count`` rider) under both ENTERS and DIES events
    # with the source_is_self predicate. Bridge support:
    #   * Rust ``Effect::Surveil { count: i32 }`` variant has existed
    #     since the I61 controller-of-effect substrate landed; its
    #     resolve arm (state_ops_resolve.rs:2610-2649) pops the top
    #     min(count, library.len()) cards and queues a PendingDecision
    #     that the auto-resolve path (state_ops_resolve.rs:6832, the
    #     ``resolve_top_of_stack``-after-triggered-ability terminal
    #     drain) closes by keeping every card on top of the library.
    #   * Python ``Surveil(amount: int)`` class
    #     (effects/generic/library_lookat.py:569) walks the top N
    #     cards in-line; when ``p.agent is None`` the surveil
    #     callback is short-circuited and every observed card stays
    #     on the library top (library_lookat.py:605).
    #   * Bridge translator arm in ``cross_engine._ta_dict_to_python_
    #     effect`` at cards.rs/cross_engine.py:444-508 has carried the
    #     ``surveil`` arm since round 16 (the scry/surveil slice);
    #     payload key is ``count`` mirroring Rust's terminology.
    #
    # **Cross-engine default-strategy contract.** Both engines'
    # no-agent surveil resolves to "keep_all_on_top" — bit-equal
    # post-resolve library top + graveyard, no auto-resolve drain
    # required on the trajectory walk because the terminal
    # post-triggered-ability path already invokes the keep_all_on_top
    # strategy. Same contract the round-16 scry arm relies on; the
    # earlier "PendingDecision pipeline" deferral noted in the
    # ``_SAFE_TRIGGERS`` docstring above turned out to be moot for
    # the default-strategy case (see the cross_engine.py:474-494
    # surveil bridge-arm docstring for the full no-agent contract).
    #
    # Cards admitted on EoE today (3 net new):
    #   * Thawbringer (4/2 {2}{G}, ENTERS+surveil 1 AND DIES+surveil 1)
    #   * Wary Watchdog (3/1 {1}{G}, ENTERS+surveil 1 AND DIES+surveil 1)
    #   * Wurmwall Sweeper (2/2 {2}, ENTERS+surveil 2)
    # Starbreach Whale carries the ENTERS+surveil 2 shape too but
    # also has ``warp_cost`` (outside the bridge); Skullsnap Nuisance
    # carries ENTERS+And/surveil + ROOM_FULLY_UNLOCKED predicate
    # (both outside today's safe set).
    ("enters", "source_is_self", "surveil"),
    ("dies", "source_is_self", "surveil"),
    # Surveil ATTACKS extension (round-43 slice). The FIRST ATTACKS
    # event in the safe set. Mirrors round-42's surveil ETB+DIES pair
    # on the orthogonal event axis — same bridge arms, same
    # default-strategy contract, just a different dispatch event.
    #
    # Bridge support (both pre-existed before this slice):
    #   * Rust ATTACKS event dispatch in
    #     ``state_ops_combat.rs:684`` (Slice 7 of the carddef-triggers
    #     ramp per the cards.rs:5742 parser arm comment), invoked
    #     after every declared-attacker on the active player's combat
    #     step. The dispatch wraps each attacker in the
    #     ``crate::cards::Event::Attacks`` subject view and runs the
    #     standard ``fire_triggers``/PendingDecision pipeline that
    #     terminates in the ``keep_all_on_top`` auto-resolve drain
    #     (state_ops_resolve.rs:6832) — identical to round-42's
    #     no-agent contract on the ENTERS/DIES surveil paths.
    #   * Python ATTACKS dispatch via ``combat._fire_attacks_triggers``
    #     (combat.py:196) followed by predicate-style ``Event.ATTACKS``
    #     fan-out in ``combat.py:208-217`` — also runs every triggered
    #     ability whose event is ATTACKS, then the standard p.agent-is
    #     -None surveil short-circuit at ``library_lookat.py:605``
    #     fires the same keep-all-on-top semantics as the ENTERS/DIES
    #     paths.
    #
    # **Cross-engine default-strategy contract.** Identical to
    # round-42 surveil ETB/DIES: no agent setup needed for the
    # trajectory walk. The auto-resolve keep_all_on_top default
    # terminates BOTH engines' surveil resolves identically — bit-equal
    # post-resolve library top + graveyard. The only axis that differs
    # from round-42 is the dispatch event; both bridges' resolve arms
    # are oblivious to which event fired the trigger because the
    # PendingDecision and library-lookat substrates fork only on the
    # effect shape (Surveil), not the upstream event.
    #
    # **No real-EoE consumer admitted today.** Pinned-by-reject-path
    # test (sister of round-37 DDDD landfall+draw and round-32+/35+/36+
    # damage-by-X precedent): the production-deck loader's pool
    # (data/17lands/eoe_decks.json.gz, 5000 archetypes) does NOT
    # contain Fear of Surveillance (the EoE printing carrying the bare
    # ATTACKS+IsSelf+Surveil(1) shape with vigilance keyword and no
    # other unsafe fields) — Fear of Surveillance is in the Scryfall
    # EoE set but absent from the 17lands deck pool (low pick rate).
    # Appendage Amalgam carries the same ATTACKS+surveil trigger but
    # its ``Flash`` keyword is outside the :data:`_SAFE_KEYWORDS` set
    # and would still be dropped at the keyword gate. Substrate is
    # pre-positioned for any future EoE / standard-format printing
    # carrying a bare ATTACKS+IsSelf+Surveil shape; the next slice
    # landing such a card in the pool need not extend the allowlist
    # again.
    ("attacks", "source_is_self", "surveil"),
    # ATTACKS+IsSelf draw_cards / gain_life extension (round-44 slice).
    # Adds the SECOND and THIRD ATTACKS leaves to the safe set after
    # round-43's surveil ATTACKS — completes the
    # ``draw_cards`` / ``gain_life`` / ``surveil`` triple under
    # source_is_self for ATTACKS, mirroring the round-1 ENTERS+IsSelf
    # leaf set (draw_cards / gain_life / scry_n / surveil) on the
    # ATTACKS event axis. Pure substrate slice — no
    # cross-engine bridge work needed since both events and both leaf
    # effects already round-trip on the bridge:
    #
    #   * ATTACKS event dispatch: Rust ``state_ops_combat.rs:684``
    #     fires every ATTACKS-event triggered ability after each
    #     declared-attacker on the active player's combat step
    #     (round-43 verified the dispatch path bit-equal vs Python's
    #     ``combat._fire_attacks_triggers`` at combat.py:196 +
    #     predicate-style ``Event.ATTACKS`` fan-out at
    #     combat.py:208-217).
    #   * ``draw_cards`` leaf: ``cross_engine._ta_dict_to_python_effect``
    #     "draw_cards" arm (round 1 of Phase 6 carddef-triggers) +
    #     Python ``DrawCards(amount: int)`` (effects/generic/draw_mill.py).
    #     Rust ``Effect::DrawCards { count: i32 }`` resolves
    #     deterministically on both engines (no
    #     PendingDecision / agent setup needed — drawing is a pure
    #     mechanical zone move from library top to hand).
    #   * ``gain_life`` leaf: ``cross_engine._ta_dict_to_python_effect``
    #     "gain_life" arm (round 1 of Phase 6) + Python
    #     ``GainLife(amount: int)`` (effects/generic/life.py). Rust
    #     ``Effect::GainLife { amount: i32 }`` resolves deterministically
    #     too (no agent setup needed — life-total mutation is a pure
    #     scalar update).
    #
    # **No real-EoE consumer admitted today.** Same precedent as
    # round-43 (substrate-only) and round-37 DDDD (landfall+draw
    # substrate-only). The 17lands deck pool's only ATTACKS+IsSelf+
    # ``draw_cards`` / ``gain_life`` printings would unlock under this
    # extension if any existed; surveying EoE printings via
    # ``scripts/scout_archetype_admit_simulation.py`` (round-44
    # update) confirms zero EoE creatures carry the bare
    # ATTACKS+IsSelf+DrawCards or ATTACKS+IsSelf+GainLife shape with
    # all other gates clean. The shape is a common one in the broader
    # MTG card pool (Curiosity-style "Whenever ~ attacks, draw a card"
    # and Soulmender-style "Whenever ~ attacks, you gain N life"
    # appear in older sets) so the substrate is pre-positioned for any
    # future EoE / standard-format printing carrying this shape — the
    # next slice landing such a card need not extend the allowlist
    # again.
    #
    # **Cross-engine default-strategy contract.** Identical to
    # round-43 surveil-ATTACKS: no agent setup needed for the
    # trajectory walk. The terminal post-triggered-ability path
    # already drains the deterministic ``DrawCards`` / ``GainLife``
    # resolves; both engines' resolve arms execute in lockstep
    # because both leaf effects mutate state via pure mechanical
    # zone moves / scalar updates (no PendingDecision queue
    # interaction).
    ("attacks", "source_is_self", "draw_cards"),
    ("attacks", "source_is_self", "gain_life"),
    # DIES+IsSelf+gain_life extension (this slice — round-47 sister to
    # round-44's ATTACKS+IsSelf+gain_life). Adds the second leaf to the
    # DIES+IsSelf arm (after round-42's surveil), completing the natural
    # ENTERS / DIES / ATTACKS × {gain_life} matrix for the bare
    # "Whenever ~ dies, you gain N life" Soul-Warden-on-death shape.
    # Pure substrate slice — no cross-engine bridge work needed since
    # both the DIES event and the gain_life leaf already round-trip on
    # the bridge:
    #
    #   * DIES event dispatch: Rust ``state_ops_resolve.rs`` /
    #     ``state_ops_sba.rs`` ``dispatch_event(Event::Dies, ...)``
    #     fires every DIES-event triggered ability after a creature
    #     moves from battlefield to graveyard (Slice 5 of the
    #     carddef-triggers ramp — see cards.rs:6035 parser arm; the
    #     DIES dispatch path was verified bit-equal vs Python's
    #     ``effects.dispatch.fire_dies_triggers`` by the round-42
    #     ENTERS+DIES surveil pair).
    #   * ``gain_life`` leaf: ``cross_engine._ta_dict_to_python_effect``
    #     "gain_life" arm (round 1 of Phase 6 carddef-triggers) +
    #     Python ``GainLife(amount: int)`` (effects/generic/life.py).
    #     Rust ``Effect::GainLife { amount: i32 }`` resolves
    #     deterministically (no PendingDecision / agent setup needed —
    #     life-total mutation is a pure scalar update).
    #
    # **Cross-engine default-strategy contract.** Identical to round-44
    # ATTACKS+IsSelf+gain_life: no agent setup needed for the trajectory
    # walk. The terminal post-triggered-ability path drains the
    # deterministic GainLife resolve in lockstep on both engines because
    # the effect mutates state via a pure scalar update with no
    # PendingDecision queue interaction.
    #
    # **No real-EoE consumer admitted today.** Same precedent as
    # round-43 (substrate-only) / round-44 (substrate-only) / round-45
    # landfall+draw substrate-only. The 17lands deck pool's EoE
    # creatures with DIES+IsSelf+GainLife: zero (the EoE death-triggers
    # cluster is CreateToken-heavy; Edge Rover / Gravpack Monoist /
    # Beamsaw Prospector all carry DIES+IsSelf+CreateToken which needs
    # token-printing pre-registration substrate the loader doesn't
    # seat — a separate larger slice). The shape is a common one in
    # the broader MTG card pool (Doomed Traveler-style "When ~ dies,
    # create a 1/1 with flying" or Disciple of the Vault-style "Whenever
    # an artifact you control is put into a graveyard, opponent loses
    # 1 life" variants share the DIES dispatch path) so the substrate
    # is pre-positioned for any future EoE / standard-format printing
    # carrying the bare DIES+IsSelf+GainLife shape — the next slice
    # landing such a card need not extend the allowlist again.
    #
    # Pinned by reject-path tests so the predicate-effect product gate
    # stays honest in the meantime; sister to the round-44 ATTACKS+
    # IsSelf+draw_cards/gain_life substrate-only landing precedent.
    ("dies", "source_is_self", "gain_life"),
    # DIES+IsSelf+draw_cards extension (this slice — round-47 sister to
    # the round-47 DIES+IsSelf+gain_life entry directly above, on the
    # draw_cards axis). Completes the natural DIES+IsSelf leaf set to
    # ``{surveil, gain_life, draw_cards}`` — the SAME three-leaf set
    # ENTERS carries (round-1 draw_cards/gain_life/scry_n + round-42
    # surveil) and ATTACKS carries (round-43 surveil + round-44
    # draw_cards/gain_life). The widening mirrors round-44's pattern
    # exactly: round-43 shipped surveil on a new event axis, round-44
    # then added draw_cards AND gain_life on that same axis once the
    # event dispatch was proven; round-42 shipped surveil on DIES,
    # round-47-gain_life added gain_life, and this slice adds the
    # final draw_cards leaf — closing the ENTERS/DIES/ATTACKS ×
    # {draw_cards, gain_life, surveil} matrix.
    #
    # Pure substrate slice — no cross-engine bridge work needed since
    # both the DIES event and the draw_cards leaf already round-trip
    # on the bridge:
    #
    #   * DIES event dispatch: Rust ``state_ops_resolve.rs`` /
    #     ``state_ops_sba.rs`` ``dispatch_event(Event::Dies, ...)``
    #     fires every DIES-event triggered ability after a creature
    #     moves from battlefield to graveyard (Slice 5 of the
    #     carddef-triggers ramp — cards.rs:6035 parser arm; the DIES
    #     dispatch path was verified bit-equal vs Python's
    #     ``effects.dispatch.fire_dies_triggers`` by the round-42
    #     ENTERS+DIES surveil pair AND the round-47 DIES+gain_life
    #     entry directly above).
    #   * ``draw_cards`` leaf: ``cross_engine._ta_dict_to_python_effect``
    #     "draw_cards" arm (cross_engine.py:242, round 1 of Phase 6
    #     carddef-triggers — the most-exercised leaf in the campaign,
    #     pinned by every ETB-trigger slice since Slice 3) + Python
    #     ``DrawCards(amount: int)`` (effects/generic/draw_mill.py).
    #     Rust ``Effect::DrawCards { count: i32 }`` resolves
    #     deterministically on both engines: drawing is a pure
    #     mechanical zone move (library top -> hand) with no
    #     PendingDecision / agent setup needed — identical resolve
    #     semantics to the already-shipped DIES+gain_life leaf.
    #
    # **Cross-engine default-strategy contract.** Identical to the
    # round-47 DIES+IsSelf+gain_life entry above: no agent setup needed
    # for the trajectory walk. The terminal post-triggered-ability path
    # drains the deterministic DrawCards resolve in lockstep on both
    # engines because the effect mutates state via a pure zone move
    # with no PendingDecision queue interaction.
    #
    # **No real-EoE consumer admitted today.** Substrate-only, same
    # precedent as round-43 / round-44 / round-47-gain_life. A FRESH
    # EoE-pool delta walk at slice time (scripts/scout_r47_dies_draw_
    # delta.py, full 475-printing EoE pool + the 318-name 17lands deck
    # pool) confirms ZERO creatures flip drop->admit on this extension:
    # the EoE death-triggers cluster is CreateToken-heavy (Edge Rover /
    # Gravpack Monoist / Beamsaw Prospector all carry
    # DIES+IsSelf+CreateToken which needs the token-printing
    # pre-registration substrate the loader doesn't seat — a separate
    # larger slice; Edge Rover specifically was investigated as the
    # round-47 N1 primary candidate and declined per that gate). The
    # bare "When ~ dies, draw a card" shape (Doomed Dissenter-adjacent /
    # Bloodsoaked-Champion-style sac-payoff draws / "When ~ dies, draw"
    # variants) is one of the most common death-trigger shapes in the
    # broader MTG card pool, so the substrate is broadly pre-positioned
    # for any future EoE / standard-format printing carrying it — the
    # next slice landing such a card need not extend the allowlist
    # again. Pinned by the round-47-gain_life slice's reject-path tests
    # (``test_is_safe_trigger_dict_rejects_dies_draw_cards_shape`` /
    # ``test_simple_creature_filter_rejects_dies_draw_cards_only_
    # creature``), which this slice CONVERTS from reject to admit —
    # the exact round-37 DDDD / round-44 sister-precedent pattern.
    ("dies", "source_is_self", "draw_cards"),
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
    # Landfall + mill extension (round-48 bench-admit-set slice). Adds
    # a FOURTH safe leaf effect under the canonical landfall predicate
    # sentinel: ``mill`` (bare shape — single ``count`` payload key,
    # see :data:`_SAFE_EFFECT_KEYS` "mill" docstring). This is the
    # round-48 N1 highest-signal lever per the round-47 bench entry's
    # FAIL_TIMEOUT root-cause investigation: the timeout-dominant
    # archetypes (round-46/47 Sweep A grid 0,1,4,5,10,11,12,13,14,15)
    # collapse to ~1-2 admitted creature copies + ~58 basics, so games
    # never end -> FAIL_TIMEOUT. This entry admits a real EoE card.
    #
    # **Real-EoE consumer admitted today: Icetill Explorer**
    # (2/4 {2}{G}{G}, no keywords, single trigger
    # "Landfall — Whenever a land you control enters, mill a card",
    # i.e. ``ENTERS / And(SubjectIsLand, ControlledByYou) /
    # SelfMill(amount=1)``). It carries no keywords, no
    # activated/static abilities, no warp/ward/dynamic-P-T, and its
    # ONLY trigger is this landfall+mill — every gate in
    # :func:`_printing_is_bridge_simple_creature` passes once the
    # ``mill`` leaf rides the landfall predicate. EoE-pool delta
    # (scripts/scout_r48_timeout_archetype_admit_delta.py): Icetill
    # Explorer appears in Sweep-A archetypes 10/11/12 (x1 each,
    # 1->2 admitted creature copies per deck) plus archetypes 2 (x2),
    # 3 (x2), 51 (x1) outside the grid. The other EoE SelfMill
    # carrier, Seedship Broodtender (ENTERS / IsSelf / SelfMill(3)),
    # is NOT admitted — it also carries an activated ability, a
    # declined silent-mistranslation class, so it stays correctly
    # dropped at the ``activated_abilities`` gate (the
    # source_is_self+mill substrate entry below pins this reject-path).
    #
    # **Cross-engine parity contract.** ``mill`` is a pure
    # deterministic zone move (own library top -> own graveyard) with
    # NO PendingDecision / agent / target interaction — identical
    # resolve semantics to the already-shipped ``draw_cards`` /
    # ``gain_life`` landfall leaves. Bridge support pre-existed:
    #   * Rust ``Effect::Mill { count }`` parsed at cards.rs:3991,
    #     serialized at cards.rs:6450, resolved at
    #     state_ops_resolve.rs:1034-1051 reading
    #     ``current_resolve_source_controller`` (I65 controller-of-
    #     effect fix). Empty-library mid-mill silently stops (CR
    #     704.5b applies to DRAWING not MILLING) — both engines break
    #     out of the loop, observably matching.
    #   * Python ``SelfMill(amount)`` (library_lookat.py:624) pops
    #     ``amount`` cards from ``library[0]`` to the controller's
    #     graveyard, breaking on empty library — bit-equal.
    #   * Bridge arm ``cross_engine._ta_dict_to_python_effect`` "mill"
    #     (cross_engine.py:725, shipped round-16) maps the dict's
    #     ``count`` -> ``SelfMill(amount=count)``; the
    #     ``amount``/``count`` field-name discrepancy is local to the
    #     bridge translation, same shape as the established
    #     ``draw_cards count -> amount`` arm.
    # The landfall predicate path itself is the SAME one round-36's
    # landfall+gain_life (Eumidian Terrabotanist) and round-37's
    # landfall+pump_self (Icecave Crasher) validated bit-equal on
    # both engines under the ENTERS dispatch — only the leaf effect
    # differs, and ``mill``'s resolve is strictly simpler (single
    # zone move, no scalar/keyword rider).
    ("enters", "land_enters_controlled_by_you", "mill"),
    # Landfall + put_plus_one_counter_on_self extension (round-59 N1
    # — the sole remaining Seedship Agrarian blocker). Adds a FIFTH
    # safe leaf effect under the canonical landfall predicate
    # sentinel: ``put_plus_one_counter_on_self`` (bare shape — single
    # ``amount`` payload key, see :data:`_SAFE_EFFECT_KEYS`
    # "put_plus_one_counter_on_self" docstring). Exactly the same
    # one-line-widen shape as the round-48 ``landfall+mill`` slice
    # (Icetill Explorer) — only the leaf effect differs.
    #
    # **Real-EoE consumer admitted today: Seedship Agrarian's
    # TRIGGER-2.** Seedship Agrarian (3/3 {3}{G},
    # Creature — Insect Scientist) parses to TWO TriggeredAbilities:
    #   (1) ``BECOMES_TAPPED / IsSelf / CreateToken(Lander)`` — the
    #       FIRST trigger, admitted round-58 N1 by the BECOMES_TAPPED
    #       event bridge + the
    #       ``("becomes_tapped","source_is_self","create_token")``
    #       entry below; genuine real-EoE probe byte-equal.
    #   (2) ``ENTERS / land_enters_controlled_by_you /
    #       PutPlusOneCounterOnSelf(1)`` — "Landfall — Whenever a land
    #       you control enters, put a +1/+1 counter on this creature".
    #       This is the ORTHOGONAL trigger-2 leaf the round-58 resync
    #       narrowed Seedship's ``non_effect_blocker`` to: its sole
    #       remaining residual. This entry admits it. With BOTH
    #       triggers now round-tripping, Seedship Agrarian's FULL card
    #       is byte-equal-admittable (it carries no keywords, no
    #       carrier-side activated/static abilities, no warp/ward/
    #       dynamic-P-T — every gate in
    #       :func:`_printing_is_bridge_simple_creature` passes once
    #       both trigger leaves ride the safe set).
    #
    # **Cross-engine parity contract (bare-shape self-counter).**
    # ``put_plus_one_counter_on_self`` is event-agnostic and has been
    # byte-equal-proven under ATTACKS/ENTERS/DIES since round-22/23 —
    # this slice confirms it round-trips IDENTICALLY under the
    # landfall ENTERS-on-land predicate (the predicate axis is
    # orthogonal to the effect's resolve; the recognizer collapses
    # the parser's ``And(Subject(IsLand), Controlled(YOU))`` to the
    # same ``land_enters_controlled_by_you`` sentinel the shipped
    # gain_life / pump_self / draw_cards / mill landfall leaves use).
    # Bridge support pre-existed (round-56 N2 confirmed both the live
    # Rust variant AND the wired bridge arm):
    #   * Rust ``Effect::PutPlusOneCounterOnSelf { amount: i32 }``
    #     (cards.rs:487, parsed cards.rs:4653, serialized
    #     cards.rs:7179-7181, resolved at
    #     state_ops_resolve.rs reading the ability's source by
    #     ``source_obj_id``). Source not on a battlefield zone ->
    #     silent no-op (mirrors Python's ``source is None`` early
    #     return).
    #   * Python ``PutPlusOneCounterOnSelf(amount: int = 1)``
    #     (effects/generic/counters.py:784) reads
    #     ``state.resolving_source`` and calls
    #     ``add_plus_one_counters(state, source, amount)`` — bit-equal
    #     resolve to Rust's source-walk-then-add.
    #   * Bridge arm ``cross_engine._ta_dict_to_python_effect``
    #     "put_plus_one_counter_on_self" (cross_engine.py:3899,
    #     shipped round-22) maps the dict's ``amount`` (optional,
    #     defaults to 1, rejects negative — same contract as Rust's
    #     parse_effect) -> ``PutPlusOneCounterOnSelf(amount=amount)``.
    #     The ``amount`` field name is IDENTICAL on BOTH sides
    #     (Rust to_dict emits ``{"kind":...,"amount":<i32>}``; no
    #     ``count``/``amount`` spelling discrepancy unlike mill/scry/
    #     surveil) — strictly the simplest bridge shape, single
    #     scalar payload, NO rider the bridge would silently drop
    #     (contrast Surveil's ``use_artifact_count`` / PumpSelf's
    #     ``granted_keywords`` / CreateToken's token-registration).
    # The landfall predicate path itself is the SAME one round-36's
    # landfall+gain_life (Eumidian Terrabotanist), round-37's
    # landfall+pump_self (Icecave Crasher), and round-48's
    # landfall+mill (Icetill Explorer) all validated bit-equal on
    # both engines under the ENTERS dispatch — only the leaf effect
    # differs, and ``put_plus_one_counter_on_self``'s resolve is a
    # single in-place counter add with no scalar/keyword/zone rider.
    ("enters", "land_enters_controlled_by_you", "put_plus_one_counter_on_self"),
    # ENTERS + source_is_self + mill substrate (round-48, sister to
    # the landfall+mill entry above on the source_is_self predicate
    # axis — mirrors how round-1's ENTERS+IsSelf leaf set carries
    # draw_cards/gain_life/scry_n + round-42's surveil). **No real-EoE
    # consumer admitted today**: the only EoE ENTERS+IsSelf+SelfMill
    # carrier is Seedship Broodtender (1/4 {2}{G},
    # "When ~ enters, mill three cards", SelfMill(3)) which ALSO has
    # an activated ability — a declined silent-mistranslation class
    # the loader doesn't seat — so Seedship Broodtender stays dropped
    # at the ``activated_abilities`` gate. This substrate entry is
    # pre-positioned for any future EoE / standard-format bare
    # "When ~ enters, mill N" creature (Stitcher's Supplier-style,
    # one of the most common ETB-mill shapes in the broader pool) so
    # the next slice landing such a card need not extend the
    # allowlist again; pinned by a reject-path test so the
    # predicate-effect product gate stays honest in the meantime.
    # Same substrate-only landing precedent as round-37 DDDD
    # (landfall+draw) / round-43 (ATTACKS+surveil) / round-44
    # (ATTACKS+draw/gain) / round-47 (DIES+draw). The
    # ``_SAFE_EFFECT_KEYS`` "mill" whitelist + the recognizer's
    # ENTERS+IsSelf ``safe_effect_kinds`` widening (below) are the
    # only other edits this leaf needs; the event-string gate and the
    # ``_is_safe_trigger_dict`` dict-side gate stay unchanged since
    # both already admit ENTERS + the ``count`` payload-key whitelist.
    ("enters", "source_is_self", "mill"),
    # ENTERS + source_is_self + create_token substrate (round-49 N1
    # token-printing pre-registration substrate, Phase 1 — see
    # ``docs/TOKEN_PRINTING_SUBSTRATE.md``). Adds the FIRST CreateToken
    # leaf to the safe set: the fixed-single-token "When ~ enters,
    # create N tokens of <fixed printing>" shape (Wedgelight-Rammer /
    # Doomed-Traveler family), restricted to a VANILLA token printing
    # (non-None P/T, no keywords, no activated/triggered/static
    # abilities; card-types may be multi — ``Artifact Creature`` /
    # ``Enchantment Creature``) and a BARE rider profile (``count``
    # only — ``each_player`` / ``tapped`` / ``attacking`` /
    # ``schedule_end_of_combat_sacrifice`` all default-False).
    #
    # **Why VANILLA-token only (the §2 silent-mistranslation gate).**
    # The bridge resolves a Rust ``token_printing_id: u32`` to a Python
    # ``CardPrinting`` via the ``register_token_printing`` map; the
    # loader synthesizes a token CardDef from the carrier's parsed
    # ``token_printing``. CardDef carries name / card-types / P/T /
    # subtypes / keywords / triggered_abilities only — it has NO
    # activated-ability field. A non-vanilla token (the EoE ``Lander``,
    # which carries ``{2}, Sac: SearchLibraryForBasicLandTapped``)
    # would have its activated ability SILENTLY DROPPED on the bridge:
    # Python materializes a Lander that can sac for a land, Rust
    # materializes one that can't. That is exactly the round-38-E1 /
    # §2 silent-mistranslation class. The recognizer
    # (``_python_ta_to_safe_dict``) refuses any non-vanilla token so
    # the carrier falls through to the filter drop path until the
    # token-activated-ability sub-substrate lands (Phase 3 in the
    # design doc).
    #
    # **Why BARE rider only.** Rust's ``Effect::CreateToken { count,
    # token_printing_id }`` (rust/src/cards.rs:219) has NO
    # ``tapped`` / ``each_player`` / ``attacking`` /
    # ``schedule_end_of_combat_sacrifice`` field — the bridge arm
    # constructs ``CreateToken(token_printing=…, count=…)`` with every
    # rider at its Python dataclass default (False). A carrier whose
    # parsed ``CreateToken`` sets ``tapped=True`` (Gravpack Monoist)
    # or ``each_player=True`` (Edge Rover) would round-trip to a token
    # that enters untapped / under one player only on Rust while
    # Python honored the rider — a byte-divergent post-resolve token
    # object. The recognizer gates each rider to its default so those
    # shapes stay dropped (Phase 4 / Phase 5 in the design doc add the
    # sister-variant Rust support).
    #
    # **Cross-engine parity contract (bare-rider vanilla token).**
    # Both engines create ``count`` tokens of the fixed printing under
    # the trigger's resolved controller. Rust's resolve arm
    # (state_ops_resolve.rs) carries the I81 controller-of-effect fix
    # (both the recipient battlefield Vec pick AND the token's
    # ``controller`` byte derive from
    # ``current_resolve_source_controller``); Python's
    # ``CreateToken.resolve`` (effects/generic/tokens.py:195) has
    # always taken ``controller_id`` via the standard
    # ``Effect.resolve`` signature and has been correct on this
    # surface since before I81. The token GameObject's per-object
    # fields (printing_name, P/T, summoning_sick=True at ETB, tapped=
    # False, untap-eligible) are bit-equal because the token printing
    # is a vanilla creature on BOTH engines (registered from the same
    # CardDef → same Rust ``parse_printing`` shape + same Python
    # ``CardPrinting``). ETB dispatch fans out identically (the token
    # itself is vanilla — no nested ETB trigger to compound the
    # surface).
    #
    # **Loader-side auto-registration.** Unlike the per-probe
    # ``register_token_printing(hand_picked_pid, …)`` pattern, the
    # production-deck loader assigns the token printing a DETERMINISTIC
    # pid: ``production_deck_to_deckspec`` appends the token CardDef to
    # the union ``card_defs`` tuple (deduped by name, absent from both
    # libraries so it is registered but never drawn), and its pid =
    # its index in ``build_rust_state``'s sequential registration
    # order. ``_seat_token_printings`` rewrites the carrier's trigger
    # dict's ``token_printing_id`` to that index and calls
    # ``cross_engine.register_token_printing(pid, py_token_printing)``
    # so the Python bridge resolves the same pid. See
    # ``docs/TOKEN_PRINTING_SUBSTRATE.md`` §1.4 / §4 Phase 1.
    #
    # **No real-EoE consumer admitted today (substrate-only landing).**
    # Same precedent as round-37 DDDD (landfall+draw) / round-43
    # (ATTACKS+surveil) / round-44 (ATTACKS+draw/gain) / round-47
    # (DIES+draw). A fresh EoE-pool delta walk
    # (scripts/scout_r49_create_token_shapes.py, full EoE printing set
    # + the 318-name / 129,996-deck 17lands pool) confirms ZERO
    # creatures flip drop→admit on this Phase-1 entry: every
    # high-deck-count fixed-single-token creature carrier produces the
    # ``Lander`` token (non-vanilla — DECLINED §2, Phase 3) or carries
    # a declined rider (Gravpack Monoist ``tapped=True``) or a declined
    # carrier feature (Knight Luminary ``warp``, Honored Knight-Captain
    # activated ability); the ONLY clean creature carrier with a
    # vanilla token is Tunnel Surveyor (Glimmer 1/1) which appears in 0
    # of 129,996 17lands decks. The fixed-single-token "When ~ enters,
    # create a token" shape is one of the most common token shapes in
    # the broader MTG pool, so the substrate is broadly pre-positioned
    # for any future EoE / standard-format printing carrying a
    # bare-rider vanilla-token ENTERS+IsSelf+CreateToken — the next
    # slice landing such a card (or the Phase-3 Lander sub-substrate)
    # need not extend the allowlist again. Pinned by reject-path tests
    # (non-vanilla-token / tapped-rider / each-player-rider stay
    # dropped) so the predicate-effect product gate stays honest.
    ("enters", "source_is_self", "create_token"),
    # DIES + source_is_self + create_token_tapped (Phase 6 token-
    # printing substrate, Phase 4 — round 50). The FIRST real-card
    # token-substrate lever after Phase 1: it admits the real EoE card
    # **Gravpack Monoist** (Creature — Robot, flying; "When this
    # creature dies, create a tapped 2/2 Robot token." — 25,252 of
    # 129,996 17lands EoE decks). Unlike Phase 1 (substrate-only,
    # EoE-pool delta = 0), Phase 4 flips a real card drop→admit:
    # Gravpack Monoist's Robot token is ALREADY vanilla (2/2 Artifact
    # Creature, no abilities/keywords — verified against the parsed
    # printing), so the only Phase-1 decline that kept it dropped was
    # the ``tapped=True`` rider (``docs/TOKEN_PRINTING_SUBSTRATE.md``
    # §2.3). The new Rust ``Effect::CreateTokenTapped`` sister variant
    # + the ``create_token_tapped`` bridge arm + this recognizer widen
    # close that decline with NO Phase-3 Lander-activated-ability
    # dependency.
    #
    # **Why DIES (not ENTERS).** Gravpack Monoist's oracle is a death
    # trigger ("When this creature dies, ..."). The DIES event +
    # IsSelf predicate dispatch was proven bit-equal cross-engine by
    # round-42 (DIES+surveil) / round-47 (DIES+gain_life /
    # DIES+draw_cards) — the recognizer's event-string gate and
    # ``_is_safe_trigger_dict`` already admit DIES; this entry adds the
    # create_token_tapped leaf to the DIES×IsSelf row. The ENTERS
    # sister entry below pre-positions the substrate for any future
    # "When ~ enters, create a tapped token" carrier (sister to the
    # Phase-1 ENTERS+create_token entry) — substrate-only, no EoE
    # ENTERS+tapped consumer today.
    #
    # **Cross-engine parity contract (tapped vanilla token).** Both
    # engines create ``count`` tokens of the fixed vanilla printing
    # under the trigger's resolved controller, each entering TAPPED.
    # Rust's ``Effect::CreateTokenTapped`` resolve arm sets
    # ``tapped: true`` on the pushed GameObject (otherwise byte-
    # identical to the sister ``CreateToken`` arm — same I81
    # controller-of-effect resolution, summoning_sick=true, CE4
    # monotonic etb_timestamp, pending ENTERS dispatch); Python's
    # ``CreateToken.resolve`` flips ``obj.tapped = True`` post-ETB
    # (tokens.py:286-287). The token enters tapped but its ETB still
    # fires on BOTH engines (CR 603.6e — entering tapped does not
    # suppress the enters trigger; the Robot token is vanilla so there
    # is no nested ETB anyway). The token GameObject's per-object
    # signature (printing name / P/T / controller / summoning_sick /
    # **tapped=True**) is byte-equal — the field-view zone signature
    # includes ``tapped`` so the real-EoE probe's byte-equal assertion
    # genuinely exercises the tapped flag.
    #
    # **Loader-side auto-registration.** Same deterministic-pid
    # ``_seat_token_printings`` pass as the Phase-1 ``create_token``
    # entry — it now also rewrites symbolic ``create_token_tapped``
    # triggers (the carrier-ref scan + the trigger rewrite preserve
    # the ``kind`` so the tapped variant survives seating).
    #
    # **Real-EoE delta (NOT substrate-only).** A fresh EoE-pool walk
    # confirms Gravpack Monoist flips drop→admit on this entry
    # (~25,252 decks). Pinned by a real-EoE Gravpack-Monoist cross-
    # engine probe + the reject-path conversion (the round-49
    # ``test_printing_is_bridge_simple_creature_rejects_lander_cluster``
    # Gravpack-Monoist assertion is moved to an admit-path pin).
    ("dies", "source_is_self", "create_token_tapped"),
    ("enters", "source_is_self", "create_token_tapped"),
    # DIES + source_is_self + bare create_token (Phase 3a — round-53
    # N1, ``docs/TOKEN_PRINTING_SUBSTRATE.md`` §7). The round-49 Phase-1
    # ENTERS entry above admits the bare-rider fixed-single-token shape;
    # Phase 1 deliberately left bare ``create_token`` OUT of the DIES
    # row because every DIES Lander carrier was declined on the
    # non-vanilla token and the only DIES+vanilla-token consumer
    # (Gravpack Monoist) is the tapped shape. Phase 3a's
    # ``_token_with_safe_activated_ability_card_def`` ADMITS the bare
    # ``Lander`` token (its ONLY activated ability is the round-52-
    # precursor-verified bridge-correct
    # ``{2},Sac:SearchLibraryForBasicLandTapped`` shape, emitted on the
    # synthesized token CardDef via ``token_activated_abilities``), so
    # **Beamsaw Prospector** ("When ~ dies, create a Lander." —
    # Creature — Human Artificer, **24,310** of 129,996 17lands EoE
    # decks) is now the real DIES+IsSelf+bare-create_token consumer.
    # The bare ``create_token`` kind round-trips identically under DIES
    # vs ENTERS (the bridge's ``create_token`` arm is event-agnostic;
    # ``_seat_token_printings`` recognizes the kind under any event and
    # threads the token's ``token_activated_abilities`` through
    # ``dataclasses.replace`` + ``cached_token_printing`` — the round-52
    # cache key folds ``token_activated_abilities`` in so a Lander never
    # collides with a same-named vanilla token). Paired with the
    # ENTERS+create_token entry (line ~2002, round-49) this flips
    # **Galactic Wayfarer** (ENTERS+IsSelf+bare-Lander — Creature —
    # Human Scout, **33,469** decks) drop→admit too. Phase 3a
    # cumulative real-EoE delta: **2 carriers / 57,779 17lands decks**
    # (the §2-honest subset — see §7 for the per-carrier decline
    # ledger: Edge Rover each_player→Phase 5, Biomechan Engineer
    # carrier-activated-ability, Glacier Godmaw / Biotech Specialist
    # sibling un-bridged trigger, Sunstar Expansionist And-StateBound
    # predicate, Seedship Agrarian BECOMES_TAPPED event, Bioengineered
    # Future non-creature→Phase 2 ALL stay declined).
    ("dies", "source_is_self", "create_token"),
    # BECOMES_TAPPED + source_is_self + create_token (round-58 N1 —
    # the BECOMES_TAPPED event bridge). The FOURTH event in the safe
    # set (after ENTERS / DIES / ATTACKS), and the FIRST that is NOT
    # a zone-change / combat event — it fires on the tap-state
    # transition of an existing battlefield permanent. Closes the
    # campaign landmine cited repeatedly since round-42 (the
    # "``BECOMES_TAPPED`` event — no bridge arm — would silently
    # mistranslate" §2 decline): there is now a bridge arm, and
    # BOTH engines fire the event at the SAME tap sites in the SAME
    # order.
    #
    # **Real-EoE consumer: Seedship Agrarian** (3/3 {3}{G},
    # Creature — Insect Scientist). Its FIRST trigger is
    # "Whenever this creature becomes tapped, create a Lander token"
    # = ``BECOMES_TAPPED / IsSelf / CreateToken(Lander)``. (Its
    # SECOND trigger, "Landfall — ... put a +1/+1 counter on this
    # creature", is the already-bridged
    # ``ENTERS / land_enters_controlled_by_you /
    # put_plus_one_counter_on_self`` shape — out of scope of THIS
    # entry but already round-trips.) This entry closes the
    # BECOMES_TAPPED→CreateToken HALF of Seedship Agrarian: the
    # event now round-trips byte-equal. The residual is narrowed to
    # the Lander token-registration substrate ONLY (a SEPARATE
    # substrate — Lander's ``{2},{T},Sac:SearchLibraryForBasicLand
    # Tapped`` activated ability on the spawned token printing; same
    # boundary Galactic Wayfarer / Beamsaw Prospector hit). See
    # ``docs/SEARCH_LIMITATIONS.md`` "BECOMES_TAPPED event bridge"
    # for the honest split.
    #
    # **Cross-engine parity contract (event firing-set + ordering).**
    # Python fires ``Event.BECOMES_TAPPED`` ONLY through
    # ``turn.tap_permanent`` (`src/mtg_bot/turn.py:542-571`), the
    # no-op-if-already-tapped chokepoint, called from: tap-for-mana
    # (`actions.py:auto_tap_for_cost`), the ``{T}`` activated-ability
    # ``tap_self`` cost (`actions.py:_activate_ability`),
    # ``tap_permanent_you_control`` activated cost, convoke, crew,
    # attack-tap of a non-vigilance attacker (`combat.py:104`, fired
    # BEFORE the per-attacker ATTACKS dispatch at `combat.py:115`),
    # and the tapper-effect family (`effects/generic/tap.py`,
    # `combinators.py:163`, `bespoke.py:496`). It deliberately does
    # NOT fire for permanents entering tapped (`_play_land`,
    # search-land-tapped, reanimate-tapped, token-created-tapped) nor
    # for regeneration's replacement tap (CR 701.21a — entering
    # tapped never "becomes tapped"). Rust's emission set matches
    # this EXACTLY: the round-58 emission slice routes the production
    # tap sites through the centralized
    # ``state_ops_resolve::tap_permanent_and_dispatch`` chokepoint
    # (mirroring `turn.tap_permanent`'s no-op-if-already-tapped +
    # dispatch shape) plus inline dispatches at the
    # mana/tap_self sites; the entering-tapped / regeneration-tap
    # Rust sites stay raw ``obj.tapped = true`` (no event). The
    # attack-tap dispatch is placed BEFORE the ``Event::Attacks``
    # dispatch so the per-attacker stack-push order is byte-equal
    # to Python's (BECOMES_TAPPED triggers ahead of ATTACKS
    # triggers).
    #
    # **Scope: which (predicate, effect) combos are admitted vs
    # declined under BECOMES_TAPPED (§2 bridge-correctness).**
    #   ADMIT: ``source_is_self`` (-> ``IsSelf()``) + ``create_token``
    #     (-> ``CreateToken``). This is the ONLY combo with a real
    #     EoE consumer (Seedship Agrarian) and BOTH the predicate and
    #     effect bridge arms are event-agnostic + already proven
    #     byte-equal under ENTERS/DIES (round-49/53 create_token
    #     work). The event itself is the only new substrate; it
    #     round-trips because both engines' firing-set + ordering
    #     match.
    #   DECLINE (no entry, falls through the recognizer):
    #     * ``IsHost()`` predicate (Cryoshatter-shape "enchanted
    #       permanent becomes tapped" — `enchantment_builder.py:497`):
    #       the Rust predicate substrate has no ``SourceIsHost`` arm
    #       (only ``SourceIsSelf``); admitting it would silently
    #       mistranslate the host-relationship. Separate predicate-
    #       substrate slice.
    #     * Any non-``create_token`` effect under BECOMES_TAPPED
    #       (draw_cards / gain_life / surveil / etc.): no EoE
    #       BECOMES_TAPPED consumer carries those today; admitting
    #       them would be preventative-only AND would widen the
    #       loader's bench-admit surface without a real signal
    #       source. A future slice landing such a card ships the
    #       single new ``_SAFE_TRIGGERS`` entry + a one-line widen
    #       in the recognizer's BECOMES_TAPPED arm (same pattern as
    #       the ENTERS/DIES/ATTACKS leaf-set widenings).
    ("becomes_tapped", "source_is_self", "create_token"),
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
    # Surveil — single ``count`` payload key. Rust's
    # ``Effect::Surveil { count: i32 }`` is bare; the Python
    # ``Surveil`` class additionally carries a ``use_artifact_count``
    # bool that selects the Surveil-X-where-X=artifacts variant
    # (effects/generic/library_lookat.py:580). The bridge does NOT
    # carry the ``use_artifact_count`` flag — gating it out at the
    # recognizer side (:func:`_python_ta_to_safe_dict`) keeps the
    # Surveil-X variant from silently degrading to a fixed surveil-N
    # on round-trip. No EoE consumer triggers Surveil-X today (it's
    # an Anticausal-Vestige-and-friends mechanic on a different
    # axis), so this gate just pins the contract.
    "surveil": frozenset({"kind", "count"}),
    # Mill (self-mill) — single ``count`` payload key (round-48
    # bench-admit-set slice). Rust's ``Effect::Mill { count: i32 }``
    # (cards.rs:75, parsed at cards.rs:3991, serialized at
    # cards.rs:6450) is bare: controller mills the top ``count`` cards
    # of THEIR OWN library into THEIR OWN graveyard (CR 701.13b — the
    # controller-target shortcut sibling of ``MillTargetPlayer``).
    # Python's ``SelfMill(amount: int = 1)``
    # (effects/generic/library_lookat.py:624) is the matched class;
    # its single ``amount`` field round-trips to Rust's ``count``
    # spelling via the existing ``mill`` bridge arm
    # (cross_engine._ta_dict_to_python_effect:725, shipped round-16's
    # scry/surveil-family slice). The bare ``count`` payload is the
    # only field on either side — no rider the bridge would silently
    # drop (unlike Surveil's ``use_artifact_count`` or PumpSelf's
    # ``granted_keywords``). The recognizer in
    # :func:`_python_ta_to_safe_dict` gates this whitelist.
    "mill": frozenset({"kind", "count"}),
    # PutPlusOneCounterOnSelf — single ``amount`` payload key
    # (round-59 N1, the sole remaining Seedship Agrarian blocker).
    # Rust's ``Effect::PutPlusOneCounterOnSelf { amount: i32 }``
    # (cards.rs:487, parsed cards.rs:4653, serialized to the dict
    # ``{"kind": "put_plus_one_counter_on_self", "amount": <i32>}``
    # at cards.rs:7179-7181) is bare: it adds ``amount`` +1/+1
    # counters to the ability's source ("this creature"), the
    # recipient always being ``state.resolving_source`` / Rust's
    # ``source_obj_id`` walk — there is NO target picker and NO rider
    # field on either side. Python's
    # ``PutPlusOneCounterOnSelf(amount: int = 1)``
    # (effects/generic/counters.py:784) carries the SAME single
    # ``amount`` field with the SAME default; the existing
    # ``put_plus_one_counter_on_self`` bridge arm
    # (cross_engine.py:3899, shipped round-22) round-trips it with
    # the field name IDENTICAL on both sides (no ``count``/``amount``
    # spelling discrepancy unlike mill/scry/surveil). The bare
    # ``amount`` payload is the only field — no rider the bridge
    # would silently drop (contrast Surveil's ``use_artifact_count``
    # or PumpSelf's ``granted_keywords``). The recognizer in
    # :func:`_python_ta_to_safe_dict` gates this whitelist.
    "put_plus_one_counter_on_self": frozenset({"kind", "amount"}),
    # CreateToken (round-49 N1 token-printing substrate, Phase 1) —
    # payload keys ``count`` + ``token_printing_id``. This is the
    # POST-SEATING dict shape: the recognizer
    # (``_python_ta_to_safe_dict``) first emits a SYMBOLIC reference
    # (``_token_card_def``) which the loader's ``_seat_token_printings``
    # pass rewrites into a numeric ``token_printing_id`` once the union
    # ``card_defs`` tuple is frozen and the token's Rust-registry pid
    # is known. ``_is_safe_trigger_dict`` validates the final
    # post-seating shape, so this whitelist mirrors Rust's two-field
    # ``Effect::CreateToken { count, token_printing_id }``
    # (rust/src/cards.rs:219, parse_effect cards.rs:4162). Rider flags
    # (``tapped`` / ``each_player`` / ``attacking`` /
    # ``schedule_end_of_combat_sacrifice``) are deliberately ABSENT —
    # Rust's variant has no mirror for them and the recognizer gates
    # each to its Python default, so a dict carrying any of them is
    # rejected here (mirrors the Surveil ``use_artifact_count`` /
    # PumpSelf ``granted_keywords`` rider-exclusion pattern). See
    # ``docs/TOKEN_PRINTING_SUBSTRATE.md`` §2.3.
    "create_token": frozenset({"kind", "count", "token_printing_id"}),
    # CreateTokenTapped (Phase 6 token-printing substrate, Phase 4 —
    # round 50). Same POST-SEATING two-key payload as the sister
    # ``create_token`` whitelist above (``count`` +
    # ``token_printing_id``); the tapped-vs-untapped choice rides on
    # the dict ``kind`` (= the Rust variant name
    # ``Effect::CreateTokenTapped``), not on a payload field, so the
    # whitelist is identical and the ``tapped`` rider is NOT a dict
    # key (mirrors the closed-vocab sister-variant convention — the
    # bridge round-trips the binary choice via ``kind``, never a bool
    # payload field). The recognizer (``_python_ta_to_safe_dict``)
    # emits this ``kind`` when the parsed ``CreateToken`` has
    # ``tapped=True`` and every OTHER rider
    # (``each_player`` / ``attacking`` /
    # ``schedule_end_of_combat_sacrifice``) at its default, gated to a
    # vanilla token (same §2 gate as the sister arm). EoE consumer:
    # Gravpack Monoist (DIES+IsSelf+tapped Robot — 25,252 17lands
    # decks). See ``docs/TOKEN_PRINTING_SUBSTRATE.md`` §4 Phase 4.
    "create_token_tapped": frozenset(
        {"kind", "count", "token_printing_id"}
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


# Token printing keyword set the bridge round-trips (Phase 1: only
# the empty set is honored, but the helper is keyword-aware so the
# Phase-3+ keyword-bearing-token follow-ups are a single-line widen).
# The EoE vanilla token printings (Robot 2/2, Human Soldier 1/1,
# Glimmer 1/1, Gremlin 1/1) carry NO keywords; a keyword-bearing
# token (the Drone token's ``flying``) is deferred until the keyword
# round-trip on TOKEN printings is pinned (creature-printing keyword
# round-trip is pinned, but a token's keyword would need its own
# combat-side parity probe — Phase 1 keeps the gate tight).
_SAFE_TOKEN_KEYWORDS: frozenset[str] = frozenset()


def _token_vanilla_card_def(token_printing) -> Optional["CardDef"]:
    """Build a :class:`cross_engine.CardDef` from a token
    ``CardPrinting`` iff the token is bridge-VANILLA, else ``None``.

    Round-49 N1 token-printing substrate (Phase 1). "Vanilla" here is
    the §2 silent-mistranslation gate: the synthesized CardDef carries
    only name / card-types / P/T / subtypes / keywords /
    triggered_abilities, so any token field the CardDef bridge can't
    represent MUST be absent or the cross-engine round trip would
    silently drop it. Specifically the token must have:

      * ``Creature`` among its card types and non-None printed P/T
        (a token GameObject's per-object signature includes power /
        toughness; a None-P/T token can't be a creature body).
      * NO activated abilities — CardDef has no activated-ability
        field. This is the gate that DECLINES the EoE ``Lander``
        token (``{2}, Sac: SearchLibraryForBasicLandTapped``); its
        ability would vanish on the bridge (Python Lander can sac for
        a land, Rust can't). Lander carriers (Galactic Wayfarer,
        Beamsaw Prospector, Edge Rover, …) therefore stay dropped
        until the Phase-3 token-activated-ability sub-substrate.
      * NO static abilities (CardDef has no static-ability field;
        layered/conditional eval, declined campaign-wide).
      * NO nested triggered abilities (a token whose own ETB/DIES
        trigger would itself have to round-trip — out of Phase 1
        scope; require zero so the surface stays a single leaf).
      * NO keywords outside :data:`_SAFE_TOKEN_KEYWORDS` (Phase 1:
        the empty set — keyword-bearing tokens like the Drone's
        ``flying`` need their own token-keyword combat parity probe).
      * NO ``can_only_block_creatures_with_flying`` block restriction
        (the EoE Drone token's flag — CardDef can't carry it).

    The token's ``card_types`` may be MULTI-type (the EoE ``Robot``
    is ``Artifact Creature``, ``Glimmer`` is ``Enchantment
    Creature``); the primary type is "Creature" and the rest flow
    through ``CardDef.extra_card_types``. The ``Token`` supertype is
    stamped so both engines remove the token from non-battlefield
    zones per CR 704.5d (Python ``CardPrinting.is_token`` reads
    ``"Token" in supertypes``; Rust mirrors via the registry
    ``supertypes`` list).
    """
    if token_printing is None:
        return None
    card_types = tuple(getattr(token_printing, "card_types", ()) or ())
    if "Creature" not in card_types:
        return None
    if token_printing.power is None or token_printing.toughness is None:
        return None
    if token_printing.activated_abilities:
        return None
    if getattr(token_printing, "static_abilities", None):
        return None
    if getattr(token_printing, "triggered_abilities", None):
        return None
    kw = frozenset(token_printing.keywords or frozenset())
    if kw and not kw.issubset(_SAFE_TOKEN_KEYWORDS):
        return None
    if getattr(
        token_printing, "can_only_block_creatures_with_flying", False
    ):
        return None
    # Primary type = "Creature"; remaining types (Artifact /
    # Enchantment) flow through extra_card_types in their printed
    # order minus the primary, so the combined tuple
    # ``(card_type, *extra_card_types)`` round-trips card-type-for-
    # card-type. The token printing's spell_effect / cost fields are
    # irrelevant (tokens are created, never cast) and intentionally
    # not threaded.
    extra = tuple(t for t in card_types if t != "Creature")
    from mtg_bot.parity.cross_engine import CardDef as _CardDef
    return _CardDef(
        name=token_printing.name,
        card_type="Creature",
        extra_card_types=extra,
        power=int(token_printing.power),
        toughness=int(token_printing.toughness),
        subtypes=tuple(token_printing.subtypes or ()),
        supertypes=("Token",),
        keywords=tuple(sorted(kw)),
    )


# The exact bridge-correct activated-ability dict for the EoE
# ``Lander`` token: ``{2}, Sacrifice this artifact: Search your
# library for a basic land card, put it onto the battlefield tapped,
# then shuffle.`` Round-52 N1's Phase-3 precursor verified this shape
# round-trips Python<->Rust with NO §2 gap (the cost is
# ``mana={generic:2}`` + ``sacrifice_self`` — the exact subset both
# engines pay identically — and the effect
# ``search_library_for_basic_land_tapped`` is FULLY DETERMINISTIC on
# BOTH engines: first ``count`` basic lands in library order, no
# PendingDecision, no agent seating). This is the ONLY token-activated
# ability Phase 3a admits; any token whose activated ability differs
# from this exact dict stays declined (§2 — a divergent cost component
# or a non-deterministic / agent-seated effect would silently
# mistranslate). ``count`` is pinned to 1 because the real EoE Lander
# searches for exactly one basic land; a hypothetical multi-land
# variant is a separate recognizer-widen (Phase 3b territory) and is
# NOT admitted here.
_LANDER_SAFE_ACTIVATED_ABILITY: dict = {
    "cost": {"mana": {"generic": 2}, "sacrifice_self": True},
    "effect": {"kind": "search_library_for_basic_land_tapped"},
    "is_mana_ability": False,
}


def _token_with_safe_activated_ability_card_def(
    token_printing,
) -> Optional["CardDef"]:
    """Build a :class:`cross_engine.CardDef` from a token
    ``CardPrinting`` iff the token's ONLY activated ability is the
    exact bridge-correct Lander shape (and it is otherwise clean),
    else ``None``.

    Round-53 N1 Phase 3a (``docs/TOKEN_PRINTING_SUBSTRATE.md`` §7).
    Sibling of :func:`_token_vanilla_card_def`: that helper admits a
    VANILLA token (a creature body, NO activated abilities — declines
    the Lander). This helper admits the ``Lander`` cluster's token,
    whose ONLY activated ability is

      ``{2}, Sac: SearchLibraryForBasicLandTapped``

    The round-52 N1 Phase-3 PRECURSOR landed the
    ``CardDef.token_activated_abilities`` substrate + its
    Python<->Rust bridge plumbing
    (:func:`cross_engine._aa_dict_to_python_activated_ability` /
    :func:`cross_engine._aa_dict_to_python_activation_cost` /
    ``build_rust_state``'s ``activated_abilities`` registry key) and
    proved this exact shape round-trips byte-identical with NO §2 gap
    (the cost is the ``mana``+``sacrifice_self`` subset both engines
    pay identically; the effect is fully deterministic on BOTH engines
    — no agent / PendingDecision). This helper consumes that substrate:
    it emits a token CardDef carrying
    ``token_activated_abilities=(_LANDER_SAFE_ACTIVATED_ABILITY,)``.

    **§2 silent-mistranslation discipline (STRICT).** The token must:

      * be a NON-creature permanent (the real Lander is
        ``Artifact — Lander``, no P/T). A token that is ALSO a
        creature is handled by the vanilla path; this path is for the
        ability-bearing artifact token.
      * carry EXACTLY ONE activated ability, byte-equal to the real
        authored ``TOKEN_PRINTINGS["Lander"]`` ability AND to
        :data:`_LANDER_SAFE_ACTIVATED_ABILITY` (cost
        ``mana={generic:2}`` + ``sacrifice_self`` and nothing else;
        effect ``SearchLibraryForBasicLandTapped(count=1)``;
        ``is_mana_ability=False``). ANY deviation (a different cost
        component, a tap requirement, a non-deterministic effect, a
        ``count`` other than 1) keeps the token DECLINED — admitting a
        token whose ability silently differs cross-engine is exactly
        the §2 class this campaign exists to avoid.
      * carry NO keywords / static abilities / triggered abilities /
        nested abilities (CardDef carries only the synthesized
        single activated ability via ``token_activated_abilities``;
        any other token feature would silently vanish on the bridge).

    The synthesized CardDef's ``card_type`` is the token's primary
    card type with the rest threaded through ``extra_card_types``
    (the Lander is single-type ``Artifact``; the multi-type path is
    kept general). The ``Token`` supertype is stamped so both engines
    remove the token from non-battlefield zones per CR 704.5d.
    """
    from mtg_bot.effects.base import ActivatedAbility
    from mtg_bot.effects.generic.search import (
        SearchLibraryForBasicLandTapped,
    )

    if token_printing is None:
        return None
    card_types = tuple(getattr(token_printing, "card_types", ()) or ())
    if not card_types:
        return None
    # This path is the NON-creature ability-bearing token (the Lander
    # is Artifact — Lander, no P/T). A creature token with an activated
    # ability is out of Phase-3a scope (its P/T body + the ability
    # would BOTH have to round-trip; the only EoE consumer here is the
    # bare Lander).
    if "Creature" in card_types:
        return None
    if token_printing.power is not None or token_printing.toughness is not None:
        return None
    if getattr(token_printing, "static_abilities", None):
        return None
    if getattr(token_printing, "triggered_abilities", None):
        return None
    if token_printing.keywords:
        return None
    if getattr(
        token_printing, "can_only_block_creatures_with_flying", False
    ):
        return None
    aas = tuple(token_printing.activated_abilities or ())
    if len(aas) != 1:
        return None
    aa = aas[0]
    if not isinstance(aa, ActivatedAbility):
        return None
    # STRICT cost gate: exactly {2} generic + sacrifice_self, nothing
    # else. Any extra cost component (tap / other sac / target) would
    # round-trip differently or be silently dropped (§2).
    cost = aa.cost
    if cost.mana is None:
        return None
    if cost.mana.generic != 2 or cost.mana.colored:
        return None
    if not cost.sacrifice_self:
        return None
    for _extra in (
        "tap_self",
        "requires_target_creature_you_control",
        "sacrifice_another_creature_or_artifact",
        "sacrifice_a_land",
        "sacrifice_another_artifact",
        "sacrifice_food",
        "sacrifice_a_desert",
    ):
        if getattr(cost, _extra, False):
            return None
    # STRICT effect gate: the fully-deterministic single-land search.
    if not isinstance(aa.effect, SearchLibraryForBasicLandTapped):
        return None
    if aa.effect.count != 1:
        return None
    if getattr(aa, "is_mana_ability", False):
        return None
    extra = tuple(t for t in card_types if t != card_types[0])
    from mtg_bot.parity.cross_engine import CardDef as _CardDef
    return _CardDef(
        name=token_printing.name,
        card_type=card_types[0],
        extra_card_types=extra,
        subtypes=tuple(token_printing.subtypes or ()),
        supertypes=("Token",),
        token_activated_abilities=(dict(_LANDER_SAFE_ACTIVATED_ABILITY),),
    )


def _canonical_lander_token_card_def() -> Optional["CardDef"]:
    """The canonical bridge-correct ``Lander`` token CardDef, built
    from the authored ``TOKEN_PRINTINGS["Lander"]`` via the SAME
    :func:`_token_with_safe_activated_ability_card_def` helper the
    ``triggered_abilities`` token-seating path uses.

    Lander-spell-token-seating sub-substrate (round-73 — the follow-on
    the round-70 spell-card-bridge SEARCH_LIMITATIONS seam scoped). The
    Lander-pid spell effects (Seedship Impact / Orbital Plunge) emit a
    SYMBOLIC ``_token_card_def`` reference (see
    :func:`_python_spell_effect_to_dict`); the loader's
    :func:`_seat_token_printings` pass (extended to walk
    ``spell_effect``) resolves it to the numeric ``token_printing_id``
    Rust's ``parse_effect`` requires + registers the matching Python
    printing into the cross-engine bridge map.

    Using the EXACT helper the ``triggered_abilities`` path uses is the
    §2 correctness guarantee: the seated Lander's registered Python
    printing (via :func:`cross_engine.cached_token_printing` →
    :func:`cross_engine._card_def_to_python_printing`) is byte-equal to
    what Python's field-free ``SeedshipImpactEffect`` /
    ``DealDamageToTargetCreatureWithExcessLanderRider`` mint
    intrinsically from ``TOKEN_PRINTINGS["Lander"]`` — the SAME
    equivalence the existing Effect-half Seedship/Orbital real-EoE
    probes already proved byte-equal (Rust seats a minimal ``Lander``
    via the registered pid, Python the intrinsic
    ``TOKEN_PRINTINGS["Lander"]``).

    Returns ``None`` (round-trip-or-bail) iff the authored Lander
    token ever drifts out of the bridge-correct shape the
    ``_token_with_safe_activated_ability_card_def`` §2 gate accepts —
    keeping the no-fallback-hybrid discipline: the symbolic ref is
    emitted ONLY when a byte-correct Lander can be seated.
    """
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS

    lander_tp = TOKEN_PRINTINGS.get("Lander")
    if lander_tp is None:
        return None
    return _token_with_safe_activated_ability_card_def(lander_tp)


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
    from mtg_bot.effects.generic.counters import PutPlusOneCounterOnSelf
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.generic.library_lookat import (
        Scry,
        SelfMill,
        Surveil,
    )
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT
    from mtg_bot.effects.generic.tokens import CreateToken

    if not isinstance(ta, TriggeredAbility):
        return None
    if ta.once_per_turn:
        return None
    # Event must be one of the events present in :data:`_SAFE_TRIGGERS`.
    # Round-42 surveil extension widens the starter ENTERS-only gate to
    # also admit DIES (the SECOND event in the safe set — adds Thawbringer
    # / Wary Watchdog whose surveil trigger pair carries both events;
    # without DIES support the whole printing would be dropped because
    # the safe-trigger filter requires EVERY trigger to round-trip).
    # Round-43 surveil ATTACKS extension widens further to admit
    # ATTACKS (the THIRD event in the safe set — pre-positions the
    # substrate for any future ATTACKS+IsSelf+Surveil consumer; no real-
    # EoE consumer admitted today since Fear of Surveillance is absent
    # from the 17lands deck pool and Appendage Amalgam has Flash).
    # The event-string is emitted further down per arm — gate here so
    # any future event extension stays a single edit.
    # Round-58 widens the ENTERS/DIES/ATTACKS gate to also admit
    # BECOMES_TAPPED (the FOURTH event in the safe set — adds Seedship
    # Agrarian whose first trigger is BECOMES_TAPPED+IsSelf+CreateToken;
    # without BECOMES_TAPPED support the whole printing would be
    # dropped because the safe-trigger filter requires EVERY trigger
    # to round-trip and Seedship's landfall trigger alone wouldn't
    # admit it). The event-string is emitted per arm below.
    if ta.event not in (
        Event.ENTERS, Event.DIES, Event.ATTACKS, Event.BECOMES_TAPPED,
    ):
        return None
    if ta.event is Event.ENTERS:
        event_str = "enters"
    elif ta.event is Event.DIES:
        event_str = "dies"
    elif ta.event is Event.BECOMES_TAPPED:
        event_str = "becomes_tapped"
    else:  # Event.ATTACKS
        event_str = "attacks"
    # Recognize one of the safe predicate shapes; produce the
    # corresponding round-trip dict (or bail if no match).
    pred = ta.predicate
    pred_dict: Optional[dict] = None
    safe_effect_kinds: tuple[str, ...] = ()
    if isinstance(pred, IsSelf) and pred.subject is None:
        # ``IsSelf`` (default-slot form): "source_is_self" canonical
        # kind. Three ENTERS-only leaf effects from the starter set
        # (draw_cards / gain_life / scry_n); the round-42 surveil
        # extension adds ``surveil`` under BOTH ENTERS and DIES; the
        # round-43 surveil ATTACKS extension adds ``surveil`` under
        # ATTACKS; the round-44 ATTACKS+draw_cards/gain_life extension
        # adds those two leaves under ATTACKS, mirroring the ENTERS
        # starter set on the ATTACKS event axis.
        pred_dict = {"kind": "source_is_self"}
        if ta.event is Event.ENTERS:
            # Round-48 widens the ENTERS+IsSelf arm from
            # {draw_cards, gain_life, scry_n, surveil} to also include
            # ``mill`` (bare SelfMill — substrate-only; the only EoE
            # ENTERS+IsSelf+SelfMill carrier, Seedship Broodtender,
            # is dropped on its activated ability so no real consumer
            # is admitted on this leaf; the landfall+mill entry below
            # is the one that admits a real card, Icetill Explorer).
            # Round-49 N1 widens it further to include ``create_token``
            # (the fixed-single-vanilla-token "When ~ enters, create N
            # tokens of <fixed printing>" shape — substrate-only; every
            # high-deck-count carrier produces the non-vanilla Lander
            # token or carries a declined rider, so no real consumer is
            # admitted today; see ``docs/TOKEN_PRINTING_SUBSTRATE.md``).
            # Phase 4 (round 50) adds ``create_token_tapped`` under
            # ENTERS as the sister of the Phase-1 ``create_token``
            # leaf — pre-positions the substrate for any future "When ~
            # enters, create a tapped token" carrier (substrate-only on
            # ENTERS; the real-card delta is on DIES via Gravpack
            # Monoist, see the DIES arm below).
            safe_effect_kinds = (
                "draw_cards", "gain_life", "scry_n", "surveil", "mill",
                "create_token", "create_token_tapped",
            )
        elif ta.event is Event.ATTACKS:
            # Round-44 widens the ATTACKS arm from {surveil} to
            # {surveil, draw_cards, gain_life}. ``scry_n`` is
            # intentionally left out today — no EoE consumer carries
            # ATTACKS+IsSelf+Scry and the scry resolver shares the
            # ``keep_all_on_top`` PendingDecision substrate with
            # surveil, so the round-43 ATTACKS+surveil precedent
            # already pins it; a future slice landing such a consumer
            # ships ``scry_n`` under ATTACKS as a single-line edit
            # here AND a single new ``_SAFE_TRIGGERS`` entry.
            safe_effect_kinds = ("surveil", "draw_cards", "gain_life")
        elif ta.event is Event.DIES:
            # Event.DIES — round-42 shipped the surveil leaf; the
            # round-47 DIES+IsSelf+gain_life entry widened it to
            # {surveil, gain_life}; THIS slice (round-47 DIES+IsSelf+
            # draw_cards, sister to the gain_life entry on the
            # draw_cards axis) widens it further to {surveil, gain_life,
            # draw_cards} — the SAME three-leaf set ENTERS carries
            # (minus scry_n, which has no DIES consumer) and ATTACKS
            # carries (round-43 surveil + round-44 draw_cards/gain_life).
            # This closes the ENTERS/DIES/ATTACKS × {draw_cards,
            # gain_life, surveil} matrix. The recognizer's event-string
            # gate above and the ``_is_safe_trigger_dict`` dict-side
            # gate stay unchanged since both already admit DIES + the
            # draw_cards ``count`` payload-key whitelist from
            # :data:`_SAFE_EFFECT_KEYS` (round-1 starter, event-agnostic).
            # ``scry_n`` stays out under DIES — no EoE consumer carries
            # DIES+IsSelf+Scry; a future slice landing one ships it as a
            # single-line edit here AND a single new ``_SAFE_TRIGGERS``
            # entry.
            #
            # Phase 4 (round 50) adds ``create_token_tapped`` under
            # DIES — this is the real-card lever: it admits **Gravpack
            # Monoist** ("When this creature dies, create a tapped 2/2
            # Robot token." — 25,252 17lands decks). Its Robot token is
            # vanilla, so the Phase-1 vanilla-token gate +
            # ``CreateTokenTapped`` Rust sister variant + the
            # ``create_token_tapped`` bridge arm flip it drop→admit
            # with no Phase-3 dependency.
            #
            # Phase 3a (round-53 N1) adds bare ``create_token`` under
            # DIES — the round-50 comment ("no real EoE
            # DIES+IsSelf+bare-create_token consumer exists") held only
            # while every DIES Lander carrier was declined on the
            # non-vanilla token. Phase 3a's
            # ``_token_with_safe_activated_ability_card_def`` admits the
            # bare Lander, so **Beamsaw Prospector** ("When ~ dies,
            # create a Lander." — Creature — Human Artificer, 24,310
            # 17lands decks) is now exactly that consumer. The bare
            # ``create_token`` kind round-trips identically under DIES
            # vs ENTERS (the bridge's ``create_token`` arm is event-
            # agnostic; the seating pass already recognizes the kind
            # under any event), so this is a single-line widen + the
            # paired ``("dies","source_is_self","create_token")``
            # ``_SAFE_TRIGGERS`` entry.
            safe_effect_kinds = (
                "surveil", "gain_life", "draw_cards",
                "create_token", "create_token_tapped",
            )
        else:
            # Event.BECOMES_TAPPED (round-58 N1 — the BECOMES_TAPPED
            # event bridge). The ONLY safe leaf under
            # BECOMES_TAPPED+IsSelf today is ``create_token`` — the
            # Seedship Agrarian shape ("Whenever this creature becomes
            # tapped, create a Lander token"). Deliberately narrow:
            # no other EoE BECOMES_TAPPED+IsSelf consumer exists, and
            # the ``create_token`` bridge arm is event-agnostic +
            # already proven byte-equal under ENTERS/DIES (round-49/53
            # create_token work) so this is a single-leaf widen, NOT
            # the full ENTERS-style {draw_cards, gain_life, scry_n,
            # surveil, mill, create_token, create_token_tapped} set.
            # A future slice landing a BECOMES_TAPPED carrier with a
            # different leaf ships that leaf here + the paired
            # ``("becomes_tapped","source_is_self",<leaf>)``
            # ``_SAFE_TRIGGERS`` entry (same one-line-widen pattern as
            # the ENTERS/DIES/ATTACKS leaf-set extensions). The
            # predicate-effect product is enforced by
            # ``_SAFE_TRIGGERS`` (the
            # ``("becomes_tapped","source_is_self","create_token")``
            # tuple), so even though ``create_token`` is listed here
            # the triple gate rejects any other event/predicate
            # pairing that isn't an explicit ``_SAFE_TRIGGERS`` entry.
            safe_effect_kinds = ("create_token",)
    elif _is_landfall_predicate_python(pred) and ta.event is Event.ENTERS:
        # Landfall is parser-emitted under ENTERS only (CR 614 — the
        # land enters under your control); gate on event to keep the
        # DIES extension (round 42) from accidentally pairing the
        # landfall predicate with a DIES event that no parser emits.
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
        # Round-48 widened the landfall arm from
        # {gain_life, pump_self_until_eot, draw_cards} to also include
        # ``mill`` (Icetill Explorer). Round-59 widens it again to
        # also include ``put_plus_one_counter_on_self`` — admits the
        # real EoE card Seedship Agrarian's TRIGGER-2 ("Landfall —
        # Whenever a land you control enters, put a +1/+1 counter on
        # this creature"), the sole remaining blocker after round-58
        # N1 bridged its BECOMES_TAPPED trigger-1. See the
        # ``("enters", "land_enters_controlled_by_you",
        # "put_plus_one_counter_on_self")`` entry in
        # :data:`_SAFE_TRIGGERS` for the full cross-engine-parity
        # provenance.
        safe_effect_kinds = (
            "gain_life", "pump_self_until_eot", "draw_cards", "mill",
            "put_plus_one_counter_on_self",
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
    elif isinstance(eff, Surveil):
        # Bare-shape Surveil (no ``use_artifact_count`` rider).
        # Python's class carries an additional ``use_artifact_count``
        # flag that selects the Surveil-X-where-X=artifacts variant
        # (effects/generic/library_lookat.py:580); Rust's
        # ``Effect::Surveil { count: i32 }`` does NOT represent the
        # X variant — the bridge would silently degrade Surveil-X to
        # a fixed surveil-N on round trip. Gate on the rider being
        # False so the Surveil-X mechanic falls through to the
        # filter drop path. No EoE consumer's ENTERS / DIES surveil
        # trigger uses the X variant today (it's a separate effect
        # arm on Anticausal Vestige and friends), so this gate just
        # pins the contract.
        if eff.use_artifact_count:
            return None
        eff_kind = "surveil"
        # Python's ``Surveil`` exposes the count as ``amount``; the
        # dict shape uses Rust's spelling ``count`` per the
        # cross_engine bridge arm convention.
        eff_dict = {"kind": "surveil", "count": int(eff.amount)}
    elif isinstance(eff, SelfMill):
        # Bare-shape SelfMill (round-48 bench-admit-set slice). Python's
        # ``SelfMill`` class (effects/generic/library_lookat.py:624)
        # carries a SINGLE ``amount`` field — no rider the bridge would
        # silently drop (contrast Surveil's ``use_artifact_count`` or
        # PumpSelf's ``granted_keywords``). The dict shape uses Rust's
        # spelling ``count`` per the ``mill`` cross_engine bridge arm
        # convention (cross_engine.py:725, shipped round-16); the
        # ``amount``/``count`` field-name discrepancy is local to the
        # bridge translation, same shape as the established
        # ``draw_cards count -> amount`` and ``surveil count -> amount``
        # arms. SelfMill is a pure deterministic zone move (own library
        # top -> own graveyard); empty-library mid-mill silently stops
        # on BOTH engines (CR 704.5b applies to drawing, not milling)
        # — see the ``("enters", "land_enters_controlled_by_you",
        # "mill")`` entry in :data:`_SAFE_TRIGGERS` for the full
        # cross-engine parity contract.
        eff_kind = "mill"
        eff_dict = {"kind": "mill", "count": int(eff.amount)}
    elif isinstance(eff, PutPlusOneCounterOnSelf):
        # Bare-shape PutPlusOneCounterOnSelf (round-59 N1 — the sole
        # remaining Seedship Agrarian blocker). Python's
        # ``PutPlusOneCounterOnSelf`` class
        # (effects/generic/counters.py:784) carries a SINGLE
        # ``amount`` field (default 1) — no rider the bridge would
        # silently drop (contrast Surveil's ``use_artifact_count`` or
        # PumpSelf's ``granted_keywords``). The recipient is ALWAYS
        # the ability's source ("this creature") — no target picker
        # on either side. The dict shape uses the IDENTICAL spelling
        # ``amount`` on both engines (Rust's
        # ``Effect::PutPlusOneCounterOnSelf`` to_dict emits
        # ``{"kind": "put_plus_one_counter_on_self",
        # "amount": <i32>}`` at cards.rs:7179-7181 — no
        # ``count``/``amount`` discrepancy unlike mill/scry/surveil),
        # round-tripped by the ``put_plus_one_counter_on_self``
        # cross_engine bridge arm (cross_engine.py:3899, shipped
        # round-22; event-agnostic + byte-equal-proven under
        # ATTACKS/ENTERS/DIES). Negative amount is rejected by the
        # bridge arm (mirrors Rust parse_effect); amount==0 is a
        # silent no-op on both engines. See the
        # ``("enters", "land_enters_controlled_by_you",
        # "put_plus_one_counter_on_self")`` entry in
        # :data:`_SAFE_TRIGGERS` for the full cross-engine parity
        # contract.
        eff_kind = "put_plus_one_counter_on_self"
        eff_dict = {
            "kind": "put_plus_one_counter_on_self",
            "amount": int(eff.amount),
        }
    elif isinstance(eff, CreateToken):
        # Round-49 N1 token-printing substrate, Phase 1 (bare rider) +
        # Phase 4 (round 50, the ``tapped`` rider). Fixed-single-token
        # "create N tokens of <fixed printing>" shape. Two §2
        # silent-mistranslation gates:
        #
        #  (1) **Supported-rider only.** Rust's bare
        #      ``Effect::CreateToken { count, token_printing_id }``
        #      (cards.rs:219) has NO rider fields; Phase 4 adds the
        #      ``Effect::CreateTokenTapped`` sister variant for the
        #      ``tapped=True`` rider (cards.rs — the
        #      ``create_token_tapped`` parse/to_dict/resolve arms +
        #      the ``create_token_tapped`` bridge arm). So the
        #      recognizer now supports TWO rider profiles:
        #        * all riders default  -> ``create_token`` (Phase 1)
        #        * ``tapped=True`` only -> ``create_token_tapped``
        #          (Phase 4 — the byte-equal tapped sister)
        #      The ``each_player=True`` rider (Edge Rover) still has
        #      its own Rust variant + bridge arm but no loader
        #      recognizer/auto-registration arm (Phase 5 in the design
        #      doc); ``attacking`` and
        #      ``schedule_end_of_combat_sacrifice`` have no Rust
        #      mirror at all. Any carrier engaging those riders (or
        #      ``tapped`` COMBINED with another rider) would round-trip
        #      to a byte-divergent token, so it falls to the filter
        #      drop path here.
        #  (2) **Vanilla token only.** The loader synthesizes a token
        #      CardDef from the parsed ``token_printing``; CardDef
        #      carries name / card-types / P/T / subtypes / keywords /
        #      triggered_abilities but has NO activated-ability field.
        #      A non-vanilla token (the EoE ``Lander``, which carries
        #      ``{2}, Sac: SearchLibraryForBasicLandTapped``) would
        #      have its activated ability SILENTLY DROPPED on the
        #      bridge. Reject any token printing carrying activated /
        #      static abilities, keywords the safe-keyword set doesn't
        #      cover, nested triggered abilities, or a non-creature /
        #      None-P-T body. (The token's triggered abilities, if
        #      any, would also have to round-trip — out of scope here;
        #      require zero.) Gravpack Monoist's Robot token IS vanilla
        #      (2/2 Artifact Creature, no abilities/keywords) so it
        #      passes gate (2); only its ``tapped=True`` rider kept it
        #      dropped under Phase 1 — Phase 4 closes that decline.
        #
        # The emitted dict carries a SYMBOLIC ``_token_card_def`` (the
        # synthesized token CardDef) rather than a numeric
        # ``token_printing_id``. The numeric pid is assigned by the
        # loader's ``_seat_token_printings`` pass once the union
        # ``card_defs`` tuple is frozen and the token's Rust-registry
        # position is known (``docs/TOKEN_PRINTING_SUBSTRATE.md`` §1.4).
        # ``_is_safe_trigger_dict`` validates the POST-seating shape
        # (``token_printing_id`` numeric), so a never-seated dict that
        # leaked to the dict-side gate would correctly be rejected.
        #
        # ``_seat_token_printings`` recognizes BOTH ``create_token``
        # and ``create_token_tapped`` symbolic carriers and preserves
        # the ``kind`` through the seating rewrite (the variant
        # distinction must survive — it IS the tapped-vs-untapped
        # choice on the bridge).
        if eff.each_player or eff.attacking:
            return None
        if getattr(eff, "schedule_end_of_combat_sacrifice", False):
            return None
        tp = eff.token_printing
        # Phase 1/4: a VANILLA token (creature body, no abilities).
        # Phase 3a (round-53 N1): the EoE ``Lander`` token — a
        # non-creature artifact whose ONLY activated ability is the
        # bridge-correct ``{2},Sac:SearchLibraryForBasicLandTapped``
        # shape (round-52 N1 precursor proved it round-trips with NO
        # §2 gap). The vanilla helper declines the Lander (it has an
        # activated ability + no creature body); fall back to the
        # ability-bearing-token helper, which §2-strictly requires the
        # token's ONLY activated ability to be exactly that Lander
        # shape and the token to be otherwise clean. ANY other
        # ability-bearing token (a different cost / effect / extra
        # ability / keyword) returns None from BOTH helpers and stays
        # DECLINED. The emitted CardDef carries
        # ``token_activated_abilities`` which ``_seat_token_printings``
        # threads unchanged through ``dataclasses.replace`` and
        # ``cached_token_printing`` (the round-52 cache key folds
        # ``token_activated_abilities`` in, so a Lander never collides
        # with a same-named vanilla token — verified by the round-52
        # cache-key pin).
        token_cd = _token_vanilla_card_def(tp)
        if token_cd is None:
            token_cd = _token_with_safe_activated_ability_card_def(tp)
        if token_cd is None:
            return None
        # Phase 4: the ``tapped`` rider routes to the
        # ``create_token_tapped`` sister kind (Rust
        # ``Effect::CreateTokenTapped``); all-default routes to the
        # Phase-1 bare ``create_token``. No other rider is set here
        # (each_player/attacking/schedule already declined above), so
        # exactly one of the two profiles applies.
        eff_kind = "create_token_tapped" if eff.tapped else "create_token"
        eff_dict = {
            "kind": eff_kind,
            "count": int(eff.count),
            # Symbolic token reference — replaced with a numeric
            # ``token_printing_id`` by ``_seat_token_printings``
            # (which preserves this ``kind``).
            "_token_card_def": token_cd,
        }
    else:
        return None
    if eff_kind not in safe_effect_kinds:
        # Effect kind is a safe leaf in the abstract but not safe
        # under this (event, predicate) pair — e.g. a parser-emitted
        # "Landfall — draw a card" would land here once such a card
        # exists in the EoE pool. Out of the safe set until the
        # matching ``_SAFE_TRIGGERS`` entry lands.
        return None
    return {
        "event": event_str,
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
      * No ``dynamic_pt_formula`` (round-39 fix — Harmonious
        Grovestrider, Cosmogoyf, Emissary Escort). The CardDef bridge
        carries only the printing's PRINTED ``power`` / ``toughness``
        fields; the parser encodes ``*``-based P/T as ``0`` placeholders
        (see ``parser/printing_keywords.py:478-480``) and the engine
        computes the actual P/T at query time via
        ``game._dynamic_base_pt(formula)``. Without the formula on the
        bridged printing, Python materializes the creature as a literal
        0/0 (or 0/1 for Cosmogoyf, 0/4 for Emissary Escort) and CR
        704.5f sends it straight to graveyard the moment SBAs check —
        but Rust's bridged printing has the same 0/0 / 0/1 / 0/4 placeholder
        and (per the smoke surfaced by round-38 E1) keeps Grovestrider on
        the battlefield. The honest fix is to drop these creatures at
        the filter instead of silently mistranslating them — adding the
        full layer-7 CDA substrate to CardDef is a separate, larger
        slice. (Two-engines-disagree-on-0/0-SBA is its own cross-engine
        gap, but it doesn't affect any real card today because no real
        CR-correct printing is actually 0/0 at ETB.)
      * No ``ward_cost`` (round-39 fix — Harmonious Grovestrider,
        Mouth of the Storm, Famished Worldsire, Lionheart Glimmer).
        The CardDef bridge doesn't carry ``ward_cost``; the bridged
        printing has ``ward_cost=None`` on both engines, so Ward never
        fires on the harness side either, which is BIT-EQUAL in the
        ``attack_all`` strategy used by the bench (the attacker never
        targets the warded creature). Filtering these out anyway keeps
        the substrate honest — if a future trajectory probe drives a
        targeted spell at one of these creatures, the bridge's silent
        Ward-drop would surface as another mystery divergence; better
        to ship them blocked at the filter today than to ship a
        targeting-strategy-conditional latent bug. Cards that ALSO
        carry an unsafe keyword / triggered ability would already be
        dropped above; this catches the bare-Ward case.
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
    # Round-39 dynamic-P/T-formula fix (Harmonious Grovestrider, Cosmogoyf,
    # Emissary Escort): see docstring above for the cross-engine
    # mistranslation this prevents.
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    # Round-39 ward-cost fix (Harmonious Grovestrider et al.): see
    # docstring above for the substrate-honesty rationale.
    if getattr(printing, "ward_cost", None) is not None:
        return False
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True


def _printing_is_bridge_pure_warp_creature(printing) -> bool:
    """True iff a CardPrinting is a warp creature the warp substrate
    round-trips byte-equal across engines — Phase 1's pure fixed-cost
    pair PLUS Phase 1.5's safe-trigger+warp residue trio.

    Phase-6 warp_cost substrate, **phase 1** (round-63; spec at
    ``docs/WARP_COST_PHASE1_DESIGN.md`` §3, written round-62 N2) +
    **phase 1.5** (round-65; the safe-trigger+warp residue trio the
    Phase-1 agent deliberately scoped out — see the live-tree-drift
    note below).

    Motivating set:

    * **Phase 1** — Red Tiger Mechan ({1}{R} warp, {3}{R} normal),
      Bygone Colossus ({3} warp, {9} normal) — both Artifact
      Creatures, ``triggered_abilities=()``, warp is the ONLY
      blocking feature, no life rider, hand-only, no graveyard
      recursion.
    * **Phase 1.5** — Germinating Wurm ({1}{G} warp; ENTERS/IsSelf/
      GainLife 2), Knight Luminary ({1}{W} warp; ENTERS/IsSelf/
      CreateToken Human Soldier 1/1), Starbreach Whale ({1}{U} warp,
      Flying; ENTERS/IsSelf/Surveil 2) — each carries exactly ONE
      SAFE ETB trigger (round-trips through
      :func:`_python_ta_to_safe_dict`) AND ``warp_cost``; warp was
      the ONLY remaining gate (their trigger half already ships
      bridge-correct, and the Rust warp-cast primitive
      ``cast_creature_warp`` fires ENTERS through the SAME
      ``move_from_hand_to_battlefield`` →
      ``drain_pending_etb_dispatches`` path as ``cast_creature``, so
      the ETB fires byte-equal under a warp-cast — pinned by the
      Phase-1.5 real-EoE probe).

    The §2 Class-1 guardrail: it admits ONLY the pure-fixed-cost
    profile OR the safe-trigger+warp profile, and MUST reject
    Timeline Culler (``warp_additional_life_cost=2``,
    ``warp_castable_from_graveyard`` — Phase 2) and every multi-gated
    warp card (static / Effect-uncovered — never flips on warp
    alone). The exclusion set is the SAME as
    :func:`_printing_is_bridge_simple_creature` (so the 7 multi-gated
    warp cards trip one of these and stay filtered) MINUS the
    ``printing.warp_cost`` rejection (which is the whole point — this
    predicate REQUIRES it), with ``triggered_abilities`` gated to the
    SAFE set (not hard-rejected), PLUS the two Phase-2-rider positive
    rejections that are the §2 guardrail's teeth.

    **Live-tree drift caught (round-63) → resolved (round-65 Phase
    1.5).** The round-62 design doc (``WARP_COST_PHASE1_DESIGN.md``
    §1) enumerated Phase-1's set as exactly Red Tiger Mechan + Bygone
    Colossus, both with ``triggered_abilities=()``. Verifying the
    spec's §3.7 predicate against the LIVE ``OracleParserCardSource``
    showed THREE more warp creatures parse with a SINGLE SAFE ETB
    trigger (the trio above). The Phase-1 agent deliberately tightened
    the guardrail to ``triggered_abilities == ()`` to exclude them —
    NOT because their trigger was wrong, but because admitting them
    was a Phase-1-boundary expansion the round-62 scout had not
    cost / pinned, and the warp-cast path was a NEW cast path the
    ETB had never fired through. Phase 1.5 (this slice) closes
    exactly that follow-up: the warp substrate has landed
    (``cast_creature_warp`` + the END-step exile sweep + the
    exile-recast), the trio's trigger half was already bridge-correct
    in :func:`_printing_is_bridge_simple_creature`'s safe-trigger
    machinery, and a genuine real-EoE probe drives an actual trio
    card through warp-cast → ETB-fires → END-step-exile → recast
    byte-equal both engines (the ETB-fires-byte-equal-under-warp-cast
    assertion is the load-bearing new pin). Quantum Riddler — which
    ALSO has a safe ETB trigger ({1}{U} warp, Flying; ENTERS/IsSelf/
    DrawCards 1) — stays correctly DECLINED here on the
    ``static_abilities`` clause (it carries a ``HandSizeAtMost(1)``
    draw-replacement static); it is NOT a safe-trigger+warp-ONLY card
    and is excluded by the general §2 exclusion set, not a
    special-case (the guardrail is NOT widened beyond the 3 — the
    Phase-1 agent's tightening intent is preserved for everything
    whose trigger is not genuinely already-safe+bridged).
    """
    if "Creature" not in printing.card_types:
        return False
    if printing.power is None or printing.toughness is None:
        return False
    if printing.warp_cost is None:
        return False
    # Phase-2 riders — positively rejected (the §2 guardrail teeth):
    if getattr(printing, "warp_additional_life_cost", 0):
        return False
    if getattr(printing, "warp_castable_from_graveyard", False):
        return False
    # Phase-1.5 boundary (round-65): triggered abilities are admitted
    # ONLY if EVERY one round-trips through the already-bridge-correct
    # safe-trigger gate (the SAME machinery
    # _printing_is_bridge_simple_creature uses). Any single unsafe
    # trigger disqualifies the whole printing — there is no
    # "partial admit" since the bridge threads the full
    # triggered-abilities tuple to both engines. Phase 1 (pure
    # fixed-cost, triggered_abilities==()) is the empty-tuple case of
    # this gate; Phase 1.5 admits exactly the trio (Germinating Wurm
    # / Knight Luminary / Starbreach Whale). A warp card with a
    # NON-safe trigger (Codecracker Hound, Mechanozoa, ...) trips
    # this and stays declined — the §2 teeth (see the docstring's
    # live-tree-drift note + SEARCH_LIMITATIONS.md).
    if printing.triggered_abilities:
        for ta in printing.triggered_abilities:
            if _python_ta_to_safe_dict(ta) is None:
                return False
    # No OTHER blocking feature — same exclusion set as
    # _printing_is_bridge_simple_creature (the 7 multi-gated warp
    # cards trip one of these and stay filtered):
    if printing.keywords and not printing.keywords.issubset(_SAFE_KEYWORDS):
        return False
    if printing.activated_abilities:
        return False
    if printing.static_abilities:
        return False
    if printing.spell_effect is not None:
        return False
    # NOTE: unlike _printing_is_bridge_simple_creature, warp_cost is
    # REQUIRED above (not rejected) — kicker / impending still reject.
    if printing.kicker_cost or printing.impending_cost:
        return False
    if printing.room_halves:
        return False
    if printing.loyalty is not None:
        return False
    if printing.cost_reductions or printing.external_cost_reductions:
        return False
    if printing.station_threshold:
        return False
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
        _parse_mana_cost_string(printing.warp_cost_str or "")
    except ValueError:
        return False
    return True


def _spell_effect_is_covered_and_bridged(printing) -> bool:
    """True iff every Effect class the printing's ``spell_effect``
    emits is in the LIVE covered+bridged set.

    Reuses the canonical effect-coverage classifier
    (:mod:`mtg_bot.parity.effect_coverage`, the production-importable
    extraction merged ``326023b4``, hardened to 100% branch coverage
    ``02bf16bf``) so the lever auto-gates on each per-card Tier-A
    close having LANDED — NOT a hardcoded card-name list (the §2
    teeth; the lever-doc §2.1 / round-64 §5 "queries the live covered
    set" requirement). ``card_effect_classes`` walks ``spell_effect``
    (+ triggered/activated/static) and returns the distinct Python
    Effect class names; ``covered_python_class_set`` is the EXACT
    ``py_class_set ∩ rust_py_name_set`` the pool-parity gate reports
    (the single canonical definition of "covered").
    """
    from mtg_bot.parity.effect_coverage import (
        covered_python_class_set,
        card_effect_classes,
    )

    emitted = card_effect_classes(printing)
    if not emitted:
        return False  # no introspectable effect — never spuriously OK
    return emitted.issubset(covered_python_class_set())


def _python_spell_effect_to_dict(spell_effect) -> Optional[dict]:
    """Convert a Python spell ``Effect`` back to the Rust-shape effect
    dict (the SAME schema Rust's ``parse_effect`` consumes and
    :func:`cross_engine._ta_dict_to_python_effect` bridges), iff it is
    one of the spell-card-bridge Phase-1 admissible shapes. Returns
    ``None`` for any shape this recognizer does not serialize.

    Spell-card-bridge lever, **Phase 1** (round-70; spec
    ``docs/SPELL_CARD_BRIDGE_PHASE1_DESIGN.md`` §3.6). The Python↔dict
    reverse of :func:`cross_engine._ta_dict_to_python_effect`
    (verify-first RE-CONFIRMED at the live HEAD: NO generic reverse
    serializer exists — only the dict→Python direction). Mirrors the
    established :func:`_python_ta_to_safe_dict` "recognize → emit the
    round-trip dict, else bail" convention.

    **It is part of the §2 teeth.** It only serializes a shape whose
    every node has a covered+bridged ``_ta_dict_to_python_effect``
    arm AND whose Rust ``parse_effect`` arm needs only a registry pid
    the loader's spell path CAN seat. Concretely, the Phase-1 admit
    set is the pid-FREE covered single-target Tier-A spells — Radiant
    Strike (``Sequence(DestroyTargetArtifactOrTappedCreature,
    GainLife)``) and Depressurize (``DepressurizeEffect``) — PLUS, as
    of the Lander-spell-token-seating sub-substrate (round-73), the
    two **Lander-pid** covered single-target Tier-A spells: Seedship
    Impact (``SeedshipImpactEffect``) and Orbital Plunge
    (``DealDamageToTargetCreatureWithExcessLanderRider``). Those two
    were DECLINED at the Phase-1 landing (round-70) because their Rust
    ``parse_effect`` arms ``require("token_printing_id")`` for the
    Lander and the loader's spell path had NO Lander-token-seating
    pass. The round-73 sub-substrate extends
    :func:`_seat_token_printings` to ALSO walk ``spell_effect`` for a
    symbolic ``_token_card_def`` (the EXACT machinery the
    ``triggered_abilities`` path already uses), so this recognizer
    now emits the symbolic Lander reference for those two shapes — the
    round-trip-or-bail tooth FLIPS POSITIVE for them, the
    no-fallback-hybrid discipline preserved (the symbolic ref is
    emitted ONLY because the seating pass that resolves it now
    exists). The teeth STILL positively decline any genuinely
    unseatable shape: a Sequence with one unrecognized child, any
    other token-pid Effect whose token is not the bridge-correct
    Lander (``_canonical_lander_token_card_def`` returns ``None``),
    and — complementary to this serializer — the covered-set gate
    still declines Close Encounter (``CloseEncounterEffect`` not
    covered+bridged).
    """
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.generic.destroy import (
        DestroyTargetArtifactOrTappedCreature,
    )
    from mtg_bot.effects.bespoke import (
        BiosynthicBurstEffect,
        DepressurizeEffect,
        FocusFireEffect,
        SeedshipImpactEffect,
    )
    from mtg_bot.effects.generic.damage import (
        DealDamageToTargetCreatureWithExcessLanderRider,
    )

    def _leaf(eff) -> Optional[dict]:
        # Pid-free covered leaves only. DestroyTargetArtifactOrTapped
        # Creature is a unit variant (intrinsic filter — Rust's
        # parse arm takes NO fields, the bridge arm constructs the
        # field-free Python class). GainLife carries ``amount``.
        if isinstance(eff, DestroyTargetArtifactOrTappedCreature):
            return {"kind": "destroy_target_artifact_or_tapped_creature"}
        if isinstance(eff, GainLife):
            return {"kind": "gain_life", "amount": int(eff.amount)}
        if isinstance(eff, DepressurizeEffect):
            return {
                "kind": "depressurize_effect",
                "power_penalty": int(eff.power_penalty),
            }
        # Biosynthic Burst (Effect-uncovered Tier-A #6; round-74).
        # Pid-FREE covered unit variant — Rust's ``parse_effect``
        # ``"biosynthic_burst_effect"`` arm takes NO fields and the
        # dict→Python bridge arm (cross_engine.py
        # ``biosynthic_burst_effect``) constructs the field-free
        # ``BiosynthicBurstEffect()``. No token pid → no
        # :func:`_seat_token_printings` dependency (unlike Seedship /
        # Orbital Plunge); the round-trip is trivially clean — emit
        # the kind-only dict, exactly the
        # ``destroy_target_artifact_or_tapped_creature`` unit-leaf
        # idiom. Adding this leaf is what flips Biosynthic Burst into
        # the spell-card-bridge admit set: with the Rust variant +
        # bridge arm landed it is now covered+bridged AND round-trips
        # here, so :func:`_printing_is_bridge_simple_spell` admits the
        # ``{1}{G}`` single-target Instant (auto-grow, no hardcoded
        # list — the §2 teeth).
        if isinstance(eff, BiosynthicBurstEffect):
            return {"kind": "biosynthic_burst_effect"}
        # Focus Fire (Effect-uncovered Tier-A #5; round-75). Single
        # ``base`` int leaf — Rust's ``parse_effect``
        # ``"focus_fire_effect"`` arm + the dict→Python bridge arm
        # (cross_engine.py ``focus_fire_effect``) both carry ``base``
        # and both default it to ``2`` (Focus Fire's printed base).
        # Pid-FREE (no token) — no :func:`_seat_token_printings`
        # dependency; the round-trip is the clean
        # ``depressurize_effect`` single-int-field idiom. Adding this
        # leaf is what flips Focus Fire into the spell-card-bridge
        # admit set: with the Rust variant + bridge arm landed it is
        # now covered+bridged AND round-trips here, so
        # :func:`_printing_is_bridge_simple_spell` admits the ``{W}``
        # single-target Instant (auto-grow, no hardcoded list — the
        # §2 teeth).
        if isinstance(eff, FocusFireEffect):
            return {"kind": "focus_fire_effect", "base": int(eff.base)}
        # Lander-pid spell effects (Seedship Impact / Orbital Plunge) —
        # the Lander-spell-token-seating sub-substrate (round-73; the
        # follow-on the round-70 SEARCH_LIMITATIONS seam scoped). Their
        # Rust ``parse_effect`` arms ``require("token_printing_id")``
        # for the Lander; the matching dict→Python bridge arms
        # (cross_engine.py ``seedship_impact_effect`` /
        # ``deal_damage_to_target_creature_with_excess_lander_rider``)
        # DROP the pid and construct the FIELD-FREE Python class (which
        # mints the Lander intrinsically via ``TOKEN_PRINTINGS
        # ["Lander"]``). The reverse serializer emits a SYMBOLIC
        # ``_token_card_def`` Lander reference exactly as
        # :func:`_python_ta_to_safe_dict`'s ``create_token`` arm does;
        # the loader's :func:`_seat_token_printings` pass (now extended
        # to walk ``spell_effect`` too) rewrites it to the numeric
        # ``token_printing_id`` Rust requires + registers the matching
        # Python printing. round-trip-or-bail preserved: bail if the
        # authored Lander token ever drifts out of the bridge-correct
        # shape (``_canonical_lander_token_card_def`` → ``None``).
        if isinstance(eff, SeedshipImpactEffect):
            lcd = _canonical_lander_token_card_def()
            if lcd is None:
                return None
            return {
                "kind": "seedship_impact_effect",
                "_token_card_def": lcd,
            }
        if isinstance(eff, DealDamageToTargetCreatureWithExcessLanderRider):
            lcd = _canonical_lander_token_card_def()
            if lcd is None:
                return None
            return {
                "kind": (
                    "deal_damage_to_target_creature_with_excess_"
                    "lander_rider"
                ),
                "amount": int(eff.amount),
                "_token_card_def": lcd,
            }
        return None

    # Sequence composer (Radiant Strike): recurse into each child
    # leaf; bail if ANY child is unrecognized (the round-trip-or-bail
    # teeth — a partially-serializable Sequence would silently drop a
    # child on Rust).
    if isinstance(spell_effect, Sequence):
        children: list[dict] = []
        for child in spell_effect.effects:
            cd = _leaf(child)
            if cd is None:
                return None
            children.append(cd)
        return {"kind": "sequence", "effects": children}
    return _leaf(spell_effect)


def _printing_is_bridge_simple_spell(printing) -> bool:
    """True iff a CardPrinting is a PURE single-target Instant/Sorcery
    the spell-card-bridge lever round-trips byte-equal across engines.

    Spell-card-bridge lever, **Phase 1** (round-70; spec at
    ``docs/SPELL_CARD_BRIDGE_PHASE1_DESIGN.md`` §3; scoping basis
    ``docs/SPELL_CARD_BRIDGE_LEVER_DESIGN.md``).

    Motivating set: the single-target Tier-A spells whose bespoke
    Effect close has landed AND whose effect carries no loader-
    unseatable token pid — at landing that is Radiant Strike +
    Depressurize. Seedship Impact / Orbital Plunge are covered but
    DECLINED in Phase 1 (Lander ``token_printing_id`` unseatable on
    the spell path — see :func:`_python_spell_effect_to_dict`).
    Diplomatic Relations (2-slot grammar) is Phase 2; Close Encounter
    (additional-cost-choice + the ``CloseEncounterEffect`` not
    covered) is the §2.2-declined Tier-C card.

    The §2 teeth: it admits ONLY a spell whose ``spell_effect`` is a
    COVERED+BRIDGED effect (queried against the LIVE covered set, NOT
    a hardcoded list — so it auto-gates on each per-card Tier-A close
    having LANDED) AND round-trips through the reverse serializer
    (which structurally declines the unseatable-token-pid shapes),
    single-mode, no X / kicker / warp / additional-cost-choice,
    exactly one required target, an implicit (homogeneous) target
    slot the deterministic-first convention drives byte-equal. Every
    other spell shape stays filtered (the decline set, §2.2).
    """
    if not (
        "Instant" in printing.card_types
        or "Sorcery" in printing.card_types
    ):
        return False
    if "Creature" in printing.card_types:
        return False  # permanent-spell rider — other substrate
    se = printing.spell_effect
    if se is None:
        return False
    # Phase-2+ / declined alt-cost & mode shapes — positively
    # rejected (the §2 teeth). Mirrors the warp guardrail's
    # rider-rejection block.
    if printing.warp_cost is not None:
        return False  # warp-entangled — warp substrate Phase 2
    if printing.kicker_cost or printing.impending_cost:
        return False
    if printing.room_halves:
        return False
    mc = printing.mana_cost
    if mc is not None and getattr(mc, "x_pips", 0):
        return False  # X-cost — a later spell-lever phase
    # Additional-cost-choice (Close Encounter): the live printing
    # exposes NO ``additional_cost_choice`` attribute (verify-first
    # at the implement HEAD — the spec ADDENDUM's "warp_cost is not
    # None" Close-Encounter reason is ALSO stale: live
    # ``Close Encounter.warp_cost is None``). The robust, load-
    # bearing decline for Close Encounter is the covered-set gate
    # below (``CloseEncounterEffect`` is NOT covered+bridged until an
    # additional-cost-choice substrate ships it). The explicit attr
    # reject is kept defensively (future-proof; harmless no-op while
    # the attr is absent) so the rejection is not solely implicit via
    # coverage if a future parser starts structuring the marker.
    if getattr(printing, "additional_cost_choice", None) is not None:
        return False
    from mtg_bot.effects.combinators import ModalChooseOne
    if isinstance(se, ModalChooseOne):
        return False  # modal — later phase
    # Phase-1 single-target ONLY — Phase 2 widens to the 2-slot
    # grammar (Diplomatic Relations: (2,2) / heterogeneous slots).
    min_t, max_t = se.target_count_range()
    if (min_t, max_t) != (1, 1):
        return False  # Phase 1 = exactly one required target
    if se.target_slot_kinds():
        return False  # heterogeneous-slot grammar is Phase 2
    # The load-bearing §2 gate: the effect must be COVERED + BRIDGED
    # (its emitted Effect classes ⊆ the LIVE covered set AND each has
    # a _ta_dict_to_python_effect bridge arm + a Rust variant). This
    # is what makes the lever gate on the per-card Tier-A close
    # having LANDED — admitting a card before its Effect's Rust+bridge
    # exists would silently mistranslate to an effectless spell. NOT
    # a hardcoded card-name list — the §2 teeth.
    if not _spell_effect_is_covered_and_bridged(printing):
        return False
    # Second §2 tooth (verify-first surfaced): the effect must
    # ROUND-TRIP through the Python→dict reverse serializer with NO
    # loader-unseatable token pid. This structurally declines
    # Seedship Impact / Orbital Plunge (covered, but their Rust
    # parse_effect requires a Lander token_printing_id the spell-path
    # loader cannot seat) — the no-fallback-hybrid discipline.
    if _python_spell_effect_to_dict(se) is None:
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


def _printing_is_bridge_nonbasic_mana_land(printing) -> bool:
    """True if a CardPrinting is a NON-basic mana-only land the bridge
    can round-trip byte-equal across both engines.

    Phase-6 non-basic-land substrate, **phase 1** (round-60 N1; spec at
    ``docs/NONBASIC_LAND_SUBSTRATE_PLAN.md`` §2/§3, written round-59 N2).

    The motivating set is the 5 EoE pay-life shocklands — Breeding
    Pool, Watery Grave, Stomping Ground, Godless Shrine, Sacred
    Foundry. The live ``OracleParserCardSource`` flattens each to
    ``produces={c1,c2}`` + ``enters_tapped=False`` + no abilities: the
    parser does **not** structure the "pay 2 life or enter tapped"
    replacement at all (verified round-60 against the live parser).
    Both engines therefore materialize the **same** untapped dual —
    bit-equal cross-engine, but CR-incomplete (a real shockland can
    enter tapped or cost 2 life). This is the round-39 Ward precedent:
    a rider the bridge drops *symmetrically*, admittable as a
    **documented deliberate simplification** (see
    ``docs/SEARCH_LIMITATIONS.md`` —
    ``trajectory.py:_printing_is_bridge_nonbasic_mana_land``).

    The predicate is the §2 Class-1 guardrail: it admits ONLY the
    parser-flattened mana-only profile (non-basic Land, 1-2 produce
    colors, NO abilities, NO structured tapped-entry, NO clone). It
    MUST reject the other 18 non-basic-land-gated cards — the Planet
    lands (``enters_tapped=True`` + Station + activated ability),
    the Duskmourn conditional painlands
    (``enters_tapped_unless_any_player_life_at_most`` set), Secluded
    Starforge (no ``produces`` + activated abilities), Cathedral of
    War (``enters_tapped=True`` + Exalted static + no mana), and
    Echoing Deeps (``optional_copy_land_from_graveyard`` clone). Each
    of those is a real cross-engine divergence or a §2-declined
    subsystem the bridge cannot carry today; admitting them via a bare
    supertype-gate widen would ship silent mistranslation (§4 of the
    plan, the round-38-E5 count-chasing anti-pattern §2 exists to
    prevent).

    NOTE on the conditional-tapped guard: the live
    ``CardPrinting.enters_tapped_unless_any_player_life_at_most`` is an
    ``int`` whose **disabled sentinel is ``0``** (``cards/base.py:733``
    — "0 disables"), NOT ``None``. The round-59 spec text wrote the
    guard as ``... is not None`` against an assumed ``int | None``
    shape; applied literally to the live ``int``-``0`` field that would
    reject all 5 shocklands (``0 is not None`` → True) and ship the
    round-60 slice as a +0-card no-op — the exact opposite of the
    spec's stated intent (§1/§3: "+5 cards"). The intent-preserving
    translation of the spec to the live field is a **falsy** check:
    ``0``/absent ⇒ no conditional tapped ⇒ admit; any positive
    threshold (the painlands' ``13``) ⇒ reject. This honors the spec's
    design (admit exactly the 5, reject the 10 painlands on the
    conditional-tapped guard) rather than its mistyped literal.
    """
    if "Land" not in printing.card_types:
        return False
    if "Basic" in printing.supertypes:
        return False  # basic path owns these
    if not printing.produces or not (1 <= len(printing.produces) <= 2):
        return False
    if printing.activated_abilities:
        return False
    if printing.triggered_abilities:
        return False
    if printing.static_abilities:
        return False
    if getattr(printing, "enters_tapped", False):
        return False
    # int field; 0 (or absent) disables the conditional-tapped
    # replacement (cards/base.py:733). A positive threshold (the
    # Duskmourn painlands' 13) is a parser-structured tapped-entry
    # Python honors and Rust ignores — a real cross-engine divergence.
    if getattr(printing, "enters_tapped_unless_any_player_life_at_most", 0):
        return False
    if getattr(printing, "enters_as_copy_of_creature", False):
        return False
    if getattr(printing, "optional_copy_land_from_graveyard", False):
        return False  # Echoing Deeps' real clone field (round-59 verified)
    return True


def _printing_to_card_def(printing) -> CardDef:
    """Convert a bridge-supported CardPrinting into a CardDef.

    Pre-condition: printing must pass
    :func:`_printing_is_bridge_simple_creature`,
    :func:`_printing_is_bridge_basic_land`, or
    :func:`_printing_is_bridge_nonbasic_mana_land`. Otherwise the
    conversion drops fields the bridge can't carry, producing a
    printing that silently disagrees across engines.
    """
    if _printing_is_bridge_basic_land(printing):
        produces = next(iter(printing.produces))
        return CardDef(
            name=printing.name,
            card_type="Land",
            mana_produced=(produces,),
        )
    if _printing_is_bridge_nonbasic_mana_land(printing):
        # Phase-6 non-basic-land substrate phase 1 (round-60 N1): a
        # mana-only non-basic land becomes the EXACT shape the basic
        # arm produces, just without the "Basic" supertype gate. The
        # per-color mana-ability auto-wire at
        # ``cross_engine.py`` iterates ``mana_produced`` — a 2-color
        # land gets two ``{T}: Add <c>`` abilities on Python and a
        # 2-element ``mana_produced`` Vec on Rust, byte-equal. The
        # pay-life / tapped replacement is dropped on BOTH engines
        # (the parser never structures it; the bridge carries no
        # replacement field) — a documented deliberate simplification
        # (SEARCH_LIMITATIONS.md). No CardDef field change, no Rust
        # change.
        return CardDef(
            name=printing.name,
            card_type="Land",
            mana_produced=tuple(sorted(printing.produces)),
        )
    if _printing_is_bridge_pure_warp_creature(printing):
        # Phase-1 warp substrate (round-63): a pure fixed-cost warp
        # creature routes to the warp-aware CardDef BEFORE the plain
        # simple-creature arm (which would drop ``warp_cost``). Both
        # Phase-1 cards are ('Artifact','Creature') — the Artifact
        # type is cosmetically dropped on BOTH bridge sides
        # (card_type="Creature", no extra_card_types), symmetric +
        # bit-equal (round-59 non-basic-land symmetric-drop
        # precedent; SEARCH_LIMITATIONS.md). Rust's ``cast_creature``
        # / ``cast_creature_warp`` Creature-gate passes on
        # ('Creature',) alone. ``warp_cost_str`` is parsed into the
        # (generic, colored) codec the bridge carries.
        # Phase-1.5 boundary (round-65): the guardrail admits a warp
        # creature with EITHER no triggers (Phase-1 pure-fixed-cost
        # pair) OR a SAFE-trigger set (the residue trio). Thread the
        # triggered abilities through to the CardDef in their
        # safe-dict round-trip shape — IDENTICAL to the
        # _printing_is_bridge_simple_creature arm below. The guardrail
        # (above) already guarantees every entry round-trips cleanly
        # via _python_ta_to_safe_dict; the bridge in
        # cross_engine.build_python_state re-materializes them via
        # _ta_dict_to_python_triggered_ability and
        # build_rust_state passes the same dict tuple to Rust's
        # register_printing(triggered_abilities=) parser. Empty tuple
        # (the Phase-1 pair) is a no-op — bit-identical to the prior
        # behavior. The ETB fires byte-equal under the warp-cast path:
        # Rust's cast_creature_warp routes the freshly-arrived
        # permanent through the SAME move_from_hand_to_battlefield →
        # drain_pending_etb_dispatches ENTERS dispatch as
        # cast_creature (pinned by the Phase-1.5 real-EoE probe).
        generic, colored = _parse_mana_cost_string(printing.mana_cost_str or "")
        wgen, wcol = _parse_mana_cost_string(printing.warp_cost_str or "")
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
            warp_cost_generic=wgen,
            warp_cost_colored=wcol,
            has_warp=True,
        )
    if _printing_is_bridge_simple_spell(printing):
        # Spell-card-bridge lever, Phase 1 (round-70): a pure
        # single-target Instant/Sorcery routes to the spell CardDef
        # BEFORE the plain simple-creature arm (which has no
        # spell_effect and would mis-materialize a spell as an
        # effectless permanent). ``card_type`` is "Instant" /
        # "Sorcery" — Python's CardPrinting is_instant/is_sorcery
        # derive from card_types; Rust's post_resolve_destination
        # routes the resolved spell → graveyard (FREE, CR 608.2m).
        # ``spell_effect`` is the Python→dict reverse-serialized
        # effect dict; the guardrail already proved it round-trips
        # (covered+bridged AND _python_spell_effect_to_dict is not
        # None — so this call cannot return None here).
        generic, colored = _parse_mana_cost_string(
            printing.mana_cost_str or "")
        spell_type = (
            "Instant" if "Instant" in printing.card_types
            else "Sorcery"
        )
        return CardDef(
            name=printing.name,
            card_type=spell_type,
            mana_cost_generic=generic,
            mana_cost_colored=colored,
            spell_effect=_python_spell_effect_to_dict(
                printing.spell_effect),
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

    # Round-49 N1 token-printing substrate (Phase 1): seat any
    # create_token carrier's token printing. This appends synthetic
    # token CardDefs to the registry (absent from both libraries),
    # rewrites the carrier triggers' symbolic ``_token_card_def`` into
    # the numeric Rust-registry pid, and registers the matching Python
    # printing into the cross-engine bridge's
    # ``register_token_printing`` map. No-op when no carrier carries a
    # create_token trigger (every pre-round-49 production deck).
    card_defs_ordered = _seat_token_printings(
        list(union_card_defs.values())
    )

    return DeckSpec(
        card_defs=tuple(card_defs_ordered),
        p0_library=tuple(p0_filtered),
        p1_library=tuple(p1_filtered),
        shared_rng_seed=shared_rng_seed,
    )


def _seat_token_printings(card_defs: list[CardDef]) -> list[CardDef]:
    """Loader-side token-printing pre-registration pass (round-49 N1,
    Phase 1).

    Walks ``card_defs`` for carriers whose ``triggered_abilities``
    carry a symbolic ``create_token`` dict (one with a
    ``_token_card_def`` key emitted by :func:`_python_ta_to_safe_dict`).
    For each distinct token CardDef (deduped by name):

      1. Append the token CardDef to the registry list IF not already
         present, AFTER every carrier card def. Its position in the
         returned list == its Rust ``Registry`` pid, because
         :func:`cross_engine.build_rust_state` registers
         ``spec.card_defs`` in tuple order and
         :meth:`Registry.register_printing` assigns
         ``id = printings.len()`` (sequential). The token CardDef is
         deliberately NOT added to either player's library — it is
         registered (so the pid is valid) but never drawn / played
         (CR: tokens only exist on the battlefield, created by the
         effect).
      2. Rewrite every carrier trigger referencing that token: drop
         the symbolic ``_token_card_def`` key, add the numeric
         ``token_printing_id`` = the token's final list index. The
         resulting dict now satisfies :func:`_is_safe_trigger_dict`
         (``{kind, count, token_printing_id}``) AND both engines'
         ``create_token`` bridge / parser arms.
      3. Register ``(pid, python_token_printing)`` into
         :func:`cross_engine.register_token_printing` so the Python
         bridge's ``create_token`` arm resolves the same pid to the
         same printing :func:`cross_engine.build_python_state`
         materializes for that token CardDef. The printing is obtained
         via :func:`cross_engine.cached_token_printing` (round-51 N1),
         which builds it once via
         :func:`cross_engine._card_def_to_python_printing` (the single
         source of truth ``build_python_state`` also uses — no shape
         drift) and returns the SAME object for the same logical token
         across every game / seed.

    ``CardDef`` is frozen, so carriers with rewritten triggers are
    rebuilt via :func:`dataclasses.replace`.

    Cross-game idempotency (round-51 N1 fix; round-50 N3 finding 1):
    this pass runs once per
    :func:`setup_matched_game_from_real_decks` invocation, and the
    token's pid is its index in the per-game ``card_defs`` union, which
    VARIES BY SEED (different opening hands -> different filtered
    libraries -> different union ordering). The
    ``register_token_printing`` map is a module-global that PERSISTS
    across games. Building a fresh printing per game (the pre-round-51
    behavior) made game 2+ of any token-carrier-bearing archetype hit
    the registry's identity-based conflicting-registration guard
    (``existing is not py_printing``) and raise ``ValueError`` — 56/60
    FAIL_EXCEPTION on a real multi-game Gravpack-Monoist bench sweep.
    :func:`cross_engine.cached_token_printing` keys the printing by
    token SHAPE (not pid) and returns the SAME object every game, so a
    repeat ``register_token_printing`` is identity-idempotent (exact
    no-op when the pid is unchanged; same-object re-register under a
    new pid when the seed shifted the union, never a conflict). Two
    carriers printing the same-named token still share one token
    CardDef + one pid (dedup by name); the shared cache makes their
    Python printing the same object too.

    Returns the (possibly extended + carrier-rewritten) card-def list,
    ordered as carriers-then-tokens so the token pids are stable and
    deterministic.
    """
    import dataclasses

    from mtg_bot.parity.cross_engine import (
        _reset_token_printing_pid_map_for_seating_pass,
        cached_token_printing,
        register_token_printing,
    )

    # Round-57 N1 fix (round-56 N3 finding — the multi-distinct-token
    # cross-archetype pid collision). The ``pid -> CardPrinting`` map
    # is a per-GAME artifact (a token's pid is its index in THIS game's
    # ``card_defs`` union, which varies by archetype AND seed) but is a
    # module-global that persists across games. A different token shape
    # (Lander) that lands on a pid a prior game's different token shape
    # (Robot) still holds would otherwise hit ``register_token_printing``'s
    # identity-conflict guard and raise — even though the prior game's
    # registration is dead. Resetting ONLY the pid map at pass entry
    # restores the per-game invariant the map is supposed to have.
    # Round-51's shape-keyed cache (``_TOKEN_PRINTING_CACHE_BY_KEY``) is
    # deliberately NOT cleared, so the same logical token still resolves
    # to the SAME identity-stable object across games (round-51's
    # same-shape cross-game guarantee is preserved). The full
    # correctness argument (round-51 safety preserved / cross-shape
    # collision fixed / no within-game silent mis-resolution) is in
    # ``_reset_token_printing_pid_map_for_seating_pass``'s docstring.
    # Unconditional + before the fast-path return so the pid map ALWAYS
    # reflects only the current game (a carrier-free game leaves no
    # stale entries behind for the next game either); the cost is one
    # ``dict.clear()``.
    _reset_token_printing_pid_map_for_seating_pass()

    # Phase 4 (round 50): the seating pass handles BOTH the Phase-1
    # bare ``create_token`` symbolic carrier AND the Phase-4
    # ``create_token_tapped`` symbolic carrier. The two are seated
    # identically (deterministic-pid token CardDef append + bridge-map
    # register); the ONLY difference is the ``kind`` string, which is
    # the tapped-vs-untapped choice on the bridge and MUST survive the
    # seating rewrite.
    _TOKEN_CREATE_KINDS = ("create_token", "create_token_tapped")

    # Lander-spell-token-seating sub-substrate (round-73). The two
    # covered single-target Tier-A Lander-pid SPELL effects whose Rust
    # ``parse_effect`` arms ``require("token_printing_id")``. Their
    # reverse serializer (:func:`_python_spell_effect_to_dict`) emits a
    # symbolic ``_token_card_def`` exactly like the ``create_token``
    # triggered carrier; the seating pass now ALSO walks
    # ``spell_effect`` to resolve it. Unlike the triggered
    # ``create_token`` rewrite (which reconstructs a fixed
    # ``{kind,count,token_printing_id}`` dict), the spell rewrite
    # PRESERVES every non-symbolic field (``amount`` for Orbital
    # Plunge; Seedship Impact has none) and only swaps the symbolic
    # ``_token_card_def`` for the numeric ``token_printing_id`` — the
    # exact field set the matching Rust parse arms require.
    _SPELL_TOKEN_PID_KINDS = (
        "seedship_impact_effect",
        "deal_damage_to_target_creature_with_excess_lander_rider",
    )

    def _carrier_token_refs(cd: CardDef):
        """Yield (idx, token_card_def) for each create_token /
        create_token_tapped trigger on ``cd`` that still carries a
        symbolic ``_token_card_def``."""
        for i, ta in enumerate(cd.triggered_abilities):
            if not isinstance(ta, dict):
                continue
            eff = ta.get("effect")
            if not isinstance(eff, dict):
                continue
            if eff.get("kind") not in _TOKEN_CREATE_KINDS:
                continue
            tcd = eff.get("_token_card_def")
            if tcd is not None:
                yield i, tcd

    def _carrier_spell_token_ref(cd: CardDef):
        """Return the symbolic ``token_card_def`` from ``cd``'s
        ``spell_effect`` iff it is a Lander-pid spell effect still
        carrying a symbolic ``_token_card_def``, else ``None``.

        A spell CardDef carries exactly ONE ``spell_effect`` (the
        guardrail is single-mode single-effect), so this returns at
        most one ref — no index needed (the rewrite replaces the whole
        ``spell_effect`` dict)."""
        se = cd.spell_effect
        if not isinstance(se, dict):
            return None
        if se.get("kind") not in _SPELL_TOKEN_PID_KINDS:
            return None
        return se.get("_token_card_def")

    # Fast path: no create_token carrier AND no Lander-pid spell
    # carrier -> return the list untouched (every pre-round-49
    # production deck; every pre-round-73 spell deck). Avoids the
    # dataclasses / cross_engine import cost on the hot loader path
    # when there's nothing to seat.
    has_token_carrier = any(
        any(True for _ in _carrier_token_refs(cd))
        or _carrier_spell_token_ref(cd) is not None
        for cd in card_defs
    )
    if not has_token_carrier:
        return card_defs

    # Stable token order: first appearance across the carrier list
    # (deterministic — card_defs order is the union-dict insertion
    # order, itself deterministic from the deck card-name order).
    # Triggered-ability carriers and spell carriers share ONE token
    # namespace (a Lander is a Lander whichever axis spawns it — same
    # name, same CardDef, ONE pid), so a deck that has BOTH a
    # triggered Lander carrier and a Lander spell shares a single
    # Lander pid.
    token_cd_by_name: dict[str, CardDef] = {}
    for cd in card_defs:
        for _idx, tcd in _carrier_token_refs(cd):
            token_cd_by_name.setdefault(tcd.name, tcd)
        stcd = _carrier_spell_token_ref(cd)
        if stcd is not None:
            token_cd_by_name.setdefault(stcd.name, stcd)

    # Carriers occupy pids [0, len(card_defs)); tokens get the pids
    # immediately after, in token_cd_by_name insertion order. A token
    # whose name already appears as a regular card def reuses that
    # def's pid (a token-named real card in the pool is implausible
    # for the EoE token names — Robot / Glimmer / Lander aren't
    # castable cards — but the dedup keeps the contract honest).
    existing_names = {cd.name: i for i, cd in enumerate(card_defs)}
    result = list(card_defs)
    token_pid_by_name: dict[str, int] = {}
    for tname, tcd in token_cd_by_name.items():
        if tname in existing_names:
            token_pid_by_name[tname] = existing_names[tname]
            continue
        token_pid_by_name[tname] = len(result)
        result.append(tcd)

    # Register each token's Python printing into the bridge map at
    # its pid. ``cached_token_printing`` returns the identity-stable
    # printing for this token shape (built once via the shared
    # CardDef->printing helper, so it is bit-identical to what
    # build_python_state materializes) and reuses the SAME object
    # across every game / seed -> ``register_token_printing`` is
    # cross-game identity-idempotent and never hits the registry's
    # conflicting-registration guard (round-51 N1 fix; round-50 N3
    # finding 1).
    for tname, pid in token_pid_by_name.items():
        py_printing = cached_token_printing(token_cd_by_name[tname])
        register_token_printing(pid, py_printing)

    # Rewrite every carrier's symbolic create_token triggers AND/OR
    # symbolic Lander-pid spell_effect into the numeric
    # token_printing_id shape. CardDef is frozen -> replace.
    rewritten: list[CardDef] = []
    for cd in result:
        refs = list(_carrier_token_refs(cd))
        stcd = _carrier_spell_token_ref(cd)
        if not refs and stcd is None:
            rewritten.append(cd)
            continue
        replace_kwargs: dict = {}
        if refs:
            new_tas = list(cd.triggered_abilities)
            for idx, tcd in refs:
                old = new_tas[idx]
                old_eff = old["effect"]
                new_eff = {
                    # Preserve the original kind — ``create_token``
                    # (Phase 1, bare) vs ``create_token_tapped``
                    # (Phase 4) IS the tapped-vs-untapped choice on
                    # the bridge; the seating pass only swaps the
                    # symbolic ``_token_card_def`` for the numeric
                    # ``token_printing_id``, never the kind.
                    "kind": old_eff["kind"],
                    "count": old_eff["count"],
                    "token_printing_id": token_pid_by_name[tcd.name],
                }
                new_ta = dict(old)
                new_ta["effect"] = new_eff
                new_tas[idx] = new_ta
            replace_kwargs["triggered_abilities"] = tuple(new_tas)
        if stcd is not None:
            # Spell rewrite: copy the whole spell_effect dict, drop
            # the symbolic ``_token_card_def``, add the numeric
            # ``token_printing_id``. EVERY other field is preserved
            # verbatim (``kind`` + ``amount`` for Orbital Plunge;
            # ``kind`` only for Seedship Impact) — the field set the
            # Rust ``parse_effect`` arms require. NO ``count`` is
            # injected (these arms don't take one — that would be the
            # silent-mistranslation class the §2 teeth exist to
            # prevent).
            old_se = cd.spell_effect
            new_se = {
                k: v
                for k, v in old_se.items()
                if k != "_token_card_def"
            }
            new_se["token_printing_id"] = token_pid_by_name[stcd.name]
            replace_kwargs["spell_effect"] = new_se
        rewritten.append(dataclasses.replace(cd, **replace_kwargs))
    return rewritten


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
            or _printing_is_bridge_nonbasic_mana_land(printing)
            or _printing_is_bridge_pure_warp_creature(printing)
            or _printing_is_bridge_simple_creature(printing)
            # Spell-card-bridge lever, Phase 1 (round-70): the 5th
            # disjunct admits a pure single-target Instant/Sorcery
            # whose bespoke Effect close has landed (covered+bridged)
            # and round-trips through the reverse serializer. Wired
            # exactly like the round-63 pure-warp-creature predicate.
            or _printing_is_bridge_simple_spell(printing)
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
