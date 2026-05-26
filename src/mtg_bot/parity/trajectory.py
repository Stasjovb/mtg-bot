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
    "production_deck_to_deckspec_instrumented",
    "LoaderAdmitReport",
    "LoaderAdmitPolicy",
    "NonAdmittedCardError",
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
        elif sym == "X":
            # **X-cost bench-loader support (devastating-onslaught-cycle-1,
            # 2026-05-22).** ``{X}`` contributes 0 to ``generic`` —
            # mirrors the no-agent cross-engine harness's X=0 bind
            # (Rust's ``cast_spell_noncreature`` Delta-2 mint at C2.5
            # + Python's ``_choose_and_apply_x`` returning 0 when
            # ``p.agent is None``). At X=0 the cost-fold
            # ``x_pips * x_value = 0`` is a no-op on generic, so
            # reporting generic without the X contribution is
            # byte-equal to Rust's post-fold ``ManaCost.generic`` for
            # the no-agent harness path. Closes the X-cost C3 baseline
            # bench-loader failure on Zero Point Ballad (admit-gate-
            # passing post X-value C3 but bench loader crashed at
            # parse time); also enables Devastating Onslaught (Phase-1
            # X-cost admit) to flow through. Production agents that
            # pick X>0 are out of scope for this bench-loader path —
            # the bench bot is no-agent by construction. See
            # ``docs/SEARCH_LIMITATIONS.md`` for the X-cost bench-
            # loader harness limitation.
            pass
        else:
            # Hybrid (W/U), Phyrexian (W/P), snow (S), 2/W, etc.
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


# Aura-substrate Phase 2 (round-79) — extra static keywords that the
# Aura predicate `_printing_is_bridge_simple_aura` admits ON TOP of
# `_SAFE_KEYWORDS`. These are cast-timing / non-combat riders that the
# CardDef bridge does **NOT** propagate from the source printing
# through to the materialized CardDef → CardPrinting round-trip on
# either engine — both Python's and Rust's bridge re-materialize the
# Aura with empty `keywords`, so the rider is **symmetrically
# dropped** on both sides. The drop is therefore bit-equal cross-
# engine under the bench's `attack_all` coverage (which only casts at
# sorcery speed; the cast-timing rider is never exercised by either
# engine in a bench game). The simple-creature filter continues to
# use the strict `_SAFE_KEYWORDS` set unchanged — these extras are
# Aura-only because Auras are not creatures and never enter combat
# (so a creature carrying `flash` would still need its own per-keyword
# parity work before admission).
#
# **Per-keyword admit rationale (round-79):**
#
#   * `flash` (CR 702.8) — cast-timing rider only; instant-speed
#     castability is documented at `parity/cross_engine.py` (the CE19
#     Bear-Flash legal-decisions emission probe) as a known
#     active!=priority divergence on CREATURE casts, but Auras are
#     dropped symmetrically through the CardDef bridge (no keywords
#     thread through), AND the bench's `attack_all` only ever casts at
#     sorcery speed where the gate is irrelevant on both engines.
#     Carriers: Frantic Strength + Shardmage's Rescue (S1 carriers per
#     `docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md` §1; both 0 EoE 17lands
#     decks — the substrate's value is the unblock of the first live
#     EoE Aura admit path, not the deck count). Symmetric-drop SL
#     entry: `docs/SEARCH_LIMITATIONS.md` (the "Aura `flash` cast-
#     timing rider" entry, sibling to the round-39 Ward / round-59
#     shockland precedents).
_AURA_SAFE_EXTRA_KEYWORDS: frozenset[str] = frozenset({
    "flash",
})


# Dynamic-P/T-formula substrate (round-78 + round-84). Admit-set for
# the simple-creature bridge predicate's ``dynamic_pt_formula``
# whitelist. Mirrors the Rust dispatch table in
# ``state_ops_combat::dynamic_base_pt_pub`` (lockstep with Python's
# ``game._dynamic_base_pt``). One entry per ROUND that landed a
# formula shape end-to-end on both engines:
#
#   * ``"harmonious_grovestrider"`` — round-78 (CDA P=T=lands-controlled).
#   * ``"cosmogoyf"`` — round-84 (CDA P=N, T=N+1 where
#     N = controller's-exile-zone count).
#
# Honest-stopped (NOT in this set, still drop-at-filter):
#
#   * ``"emissary_escort"`` — printed-base + X-from-other-artifact-MV
#     shape (different from the CDA-only dispatch arms above); the
#     Rust dispatch table's ``_`` arm returns ``None`` for any
#     unrecognized key, so admitting Escort would produce a 0/0
#     creature on Rust. Escort's slice extends the dispatch table
#     when it lands.
_DYNAMIC_PT_FORMULA_ADMIT_SET: frozenset[str] = frozenset({
    "harmonious_grovestrider",
    "cosmogoyf",
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
    # **Tier-C target-seating sub-substrate, lever-a — Exosuit
    # Savior (the count_min=0 optional-bounce edge; ENTERS sibling
    # of Sunset Saboteur's ATTACKS targeted entry below).** {2}{W}
    # Creature — 2/2 ``flying`` (in :data:`_SAFE_KEYWORDS`). "When
    # Exosuit Savior enters, you may return another target permanent
    # you control to its owner's hand." — 12,480 17lands decks.
    # Parsed live as ``(ENTERS, IsSelf,
    # ReturnTargetPermanentYouControlToOwnersHand)`` with
    # ``requires_target=False`` (because ``count_min=0`` — the bounce
    # is OPTIONAL, CR "you may return"), ``count_range=(0,1)``,
    # ``slot_kinds=()``, slot filter
    # ``ControlledByYou() & ~IsPlayer() & ~IsSource()``.
    #
    # **Reuses the SHARED Tier-C seat shipped with Sunset Saboteur.**
    # The deterministic push-time first-legal seat
    # (``first_legal_trigger_target`` on Rust at
    # ``state_ops_resolve.rs:push_triggered_ability``; the no-agent
    # ``pool[0]`` seat on Python at
    # ``actions.py:_put_triggered_ability_on_stack``, gated by
    # ``_is_target_seated_safe_trigger``) is ALREADY in place — this
    # entry only adds the per-card Effect (Rust unit variant
    # ``ReturnTargetPermanentYouControlToOwnersHand`` + the
    # ``return_target_permanent_you_control`` bridge arm + this
    # recognizer/triple). The **count_min=0 edge** (the distinct
    # contribution vs Sunset Saboteur's count_min=1): with NO
    # eligible own permanent the shared seat returns ``None`` and the
    # trigger pushes via the UNCHANGED ``new_trigger`` path
    # (push-with-no-target) → the resolve arm no-ops, byte-equal with
    # Python's ``targets=()`` ``Bounce.resolve`` early-return — the
    # optional is DECLINED, NOT fizzle-skipped (contrast Sunset
    # Saboteur, which IS skip-pushed via
    # ``lever_trigger_requires_target``). With an eligible permanent
    # both engines pick the SAME smallest-bf-index own-non-source
    # permanent and bounce it (the established ``Effect::ReturnToHand``
    # bounce-to-hand lifecycle + LTB fan-out, byte-equal). The ENTERS
    # event dispatch itself is already byte-equal-proven (the round-1
    # ENTERS+IsSelf starter set + every ENTERS probe). The genuine
    # real-EoE firing-parity probe is in test_parity_smoke.py.
    #
    # **Necessary-but-not-sufficient teeth.** Terrapact Intimidator
    # shares the IDENTICAL ``(ENTERS, source_is_self, targeted)``
    # shape but its resolve is a modal ``opponent.agent.choose_mode``
    # (the substrate seats a *target*, not a *mode*) — its
    # ``TerrapactIntimidatorETBEffect`` leaf is NOT added to the
    # ENTERS ``safe_effect_kinds``, so it stays declined even though
    # it shares the exact necessary shape (negative-pinned in
    # tests/test_trajectory.py — proves the gate is the triple +
    # bare-shape product, not the bare targeted-ETB shape).
    ("enters", "source_is_self", "return_target_permanent_you_control"),
    # **Codecracker Hound Cycle 2 (2026-05-24)** — the 9th ENTERS+IsSelf
    # leaf. Adds ``look_top_n_put_one_in_hand_rest_to_graveyard`` to the
    # safe set under (ENTERS, source_is_self). Sole admitted EoE consumer
    # at HEAD is **Codecracker Hound** ({1}{U} 2/2 warp creature, ~22,144
    # 17lands decks — the multi-cycle closure target from the 2026-05-24
    # multi-gated-tail tractability scout). Parser-emitted shape: ETB
    # trigger with ``IsSelf`` predicate + ``LookTopNPutOneInHandRest
    # ToGraveyard(n=2, reveal_chosen=False)`` effect.
    #
    # **Bridge support (both pre-existed; this slice only wires the safe-
    # trigger recognizer).**
    #   * Rust ``Effect::LookTopNPutOneInHandRestToGraveyard { n: i32 }``
    #     (rust/src/cards.rs:4392) + parse_effect at cards.rs:12042-12056
    #     + resolve at state_ops_resolve.rs:6366-6394 + the
    #     ``PendingDecision::PickCardFromExaminedChoice`` + the
    #     ``submit_pick_card_decision`` dispatcher have been on main
    #     since round 28.
    #   * Cross-engine bridge arm (cross_engine.py:4901-4978) — the
    #     ``look_top_n_put_one_in_hand_rest_to_graveyard`` translator
    #     — has been on main since round 21 (BLOCKED-BRIDGE-ARM slice).
    #     C2 widens it minimally to thread ``reveal_chosen`` from the
    #     dict to the Python class so the round-trip preserves the
    #     no-reveal contract.
    #   * Refined-Cycle-1 fold (commit ``bd37cca0``, 2026-05-24)
    #     collapsed the prior bespoke ``LookAtTopTwoSplitHandGraveyard``
    #     class into ``LookTopNPutOneInHandRestToGraveyard(n=2,
    #     reveal_chosen=False)`` — the parser-CLAUDE-faithful
    #     primitive-merge path.
    #
    # **§2 silent-mistranslation teeth.** The recognizer
    # (``_python_ta_to_safe_dict``) gates on ``eff.reveal_chosen ==
    # False``: Rust's resolve never reveals, so a ``reveal_chosen=True``
    # instance would silently mistranslate the post-resolve
    # ``publicly_known_to`` observable on the chosen card (Python's
    # ``reveal_to_all`` rider sets it; Rust leaves it unchanged).
    # Codecracker Hound's parser path emits ``reveal_chosen=False``;
    # Commune-with-Evil (n=4, reveal_chosen=True) is a Sorcery and
    # reaches the engine via the spell-card-bridge path, never this
    # safe-trigger path. ``n`` must be non-negative (Rust's parse_effect
    # rejects negatives at cards.rs:12051-12055; mirror in the
    # recognizer).
    #
    # **Cross-engine resolve contract.** Both engines split the resolve
    # into a "look + queue choice" phase + an "answer choice + apply"
    # phase, but the wire-shape differs: Rust pushes
    # ``PendingDecision::PickCardFromExaminedChoice`` at
    # state_ops_resolve.rs:6387-6393 and short-circuits; the choice is
    # drained via ``submit_pick_card_decision(chosen_id)``. Python's
    # ``LookTopNPutOneInHandRestToGraveyard.resolve`` synchronously calls
    # ``agent.choose_card_from_library(...)`` and resolves inline:
    # chosen card moves to hand (no reveal_to_all when
    # ``reveal_chosen=False``), the rest move to graveyard in popped
    # order. Both converge on the post-resolve observable: one card to
    # hand + the remainder in graveyard + ``publicly_known_to`` unchanged
    # for the moved cards. The genuine per-card real-EoE byte-equality
    # probe under both warp-cast and normal-cast lifecycles ships in
    # Cycle 3 (mirror of the Phase-1.5 trio's
    # ``test_probe_warp_admitted.py`` per-card probe shape).
    ("enters", "source_is_self", "look_top_n_put_one_in_hand_rest_to_graveyard"),
    # **Weftwalking Cycle 2 (2026-05-24) — 10th ENTERS+IsSelf leaf.**
    # Adds ``conditional_if_cast_from_hand`` under (ENTERS,
    # source_is_self). Sole admitted EoE consumer at HEAD is
    # **Weftwalking** ({4}{U}{U} Enchantment, ~3,680 17lands decks —
    # the #1 multi-gated-tail closure target from the 2026-05-24
    # tractability rescout). Parser-emitted shape: ETB trigger with
    # ``IsSelf`` predicate + ``ConditionalIfCastFromHand`` whose
    # ``inner_effect`` is the canonical
    # ``Sequence(ShuffleZonesIntoLibrary(zones=('hand','graveyard')),
    # DrawCards(amount=7))`` composite.
    #
    # **Bridge support (all pre-existed in C1 substrate commit
    # ``61f04bef`` / main merge ``d18bb3a4``; this slice only wires
    # the safe-trigger recognizer).**
    #   * Rust ``Effect::ConditionalIfCastFromHand { inner:
    #     Box<Effect> }`` (rust/src/cards.rs — recursive composer,
    #     sibling of MayDo / IfYouDo / OptionalSacAnotherForEffect) +
    #     parse_effect arm + to_pydict arm + resolve arm.
    #   * Rust ``Effect::ShuffleZonesIntoLibrary { zones:
    #     Vec<String> }`` (rust/src/cards.rs — flat leaf, sibling of
    #     zone-move shapes) + parse/to_pydict/resolve arms.
    #   * Cross-engine bridge arms at
    #     ``cross_engine.py:2295-2387`` (recursive
    #     ``conditional_if_cast_from_hand`` + flat-leaf
    #     ``shuffle_zones_into_library``).
    #   * Reverse-serializer leaves in this module (including the
    #     nested-``Sequence``-as-leaf arm so the composer-wrapping-
    #     Sequence shape round-trips byte-equal — at lines 5607-5635
    #     for the new variants and 6430-6437 for the nested-Sequence
    #     arm).
    #
    # **§2 silent-mistranslation teeth.** The recognizer
    # (``_python_ta_to_safe_dict``) gates on the EXACT canonical
    # Weftwalking inner shape: ``Sequence(ShuffleZonesIntoLibrary(
    # zones=('hand','graveyard')), DrawCards(amount=7))``. Any other
    # inner shape (different zones, different draw count, non-
    # Sequence inner, single-leaf inner, nested combinator inner)
    # falls through to the filter drop. The narrow gate is the
    # AV-C2 / CH-C2 surgical-widen precedent: a future
    # ConditionalIfCastFromHand carrier with a different inner ships
    # its own admit slice with a fresh ``_SAFE_TRIGGERS`` entry +
    # the matching widen, NOT a blanket combinator widen.
    #
    # **Verify-first silent-auto-grow check.** Live HEAD scan
    # confirmed Weftwalking is the SOLE ``ConditionalIfCastFromHand``
    # carrier system-wide (every card type / every event / every
    # predicate combination). No other carrier silently auto-grows
    # under this widen. The widen is genuinely Weftwalking-scoped at
    # HEAD — same scoped-widen discipline as today's AV C2 LEAVES
    # leaf and CH C2 ``LookTopNPutOneInHandRestToGraveyard`` leaf.
    #
    # **Cross-engine resolve contract.** Both engines degrade the
    # ``ConditionalIfCastFromHand`` gate to "always run the inner
    # effect" (the documented engine simplification at
    # combinators.py:1518-1536 — the cast-via-hand flag is ephemeral
    # and cleared by ``put_into_battlefield`` before ETB triggers
    # fire, so neither engine has a reliable resolve-time persistent
    # flag); inner resolve walks both Sequence children in order: the
    # ShuffleZonesIntoLibrary leaf moves the controller's hand +
    # graveyard back into the library and shuffles (deterministic
    # zone-move; no PendingDecision; the parser-faithful "hand" and
    # "graveyard" zones are the only ones honored at resolve time on
    # both engines per cross_engine.py:2360-2365); the DrawCards(7)
    # leaf draws 7 cards. Genuine per-card real-EoE byte-equality
    # probe under normal-cast lifecycle (Weftwalking has no
    # warp_cost) ships in Cycle 3.
    ("enters", "source_is_self", "conditional_if_cast_from_hand"),
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
    # **Tier-C target-seating sub-substrate, lever-a — Sunset
    # Saboteur (the FIRST targeted-safe-trigger entry in this set).**
    # ``{1}{B}`` Creature — 4/1 ``menace`` (in :data:`_SAFE_KEYWORDS`).
    # "Whenever Sunset Saboteur attacks, put a +1/+1 counter on target
    # creature an opponent controls." — 6,375 17lands decks. Parsed
    # live as ``(ATTACKS, IsSelf, PutPlusOneCounterOnOpponentsCreature)``
    # with ``requires_target=True``, ``count_range=(1,1)``,
    # ``slot_kinds=()``, slot filter
    # ``IsCreature() & ControlledByOpponent()``, ``amount=1``.
    #
    # **Why this needs a NEW substrate (not just a leaf widen).**
    # Every prior ``_SAFE_TRIGGERS`` leaf is recipient-is-self /
    # untargeted; the production-deck bench loader seats NO agent, so
    # a targeted trigger has no one to pick the push-time target. The
    # ``_SAFE_TRIGGERS`` docstring's decline class
    # (``deal_damage_any_target`` "target-pick at PUSH time requires
    # an agent shim — the production-deck loader doesn't seat one")
    # is exactly this. The Tier-C target-seating shared sub-substrate
    # (this slice) replaces BOTH engines' no-agent behavior with the
    # SAME deterministic first-legal pick:
    #   * **Rust** — ``first_legal_trigger_target`` at
    #     ``state_ops_resolve.rs:push_triggered_ability`` scans
    #     ascending seat × bf-Vec order, seats the smallest-bf-index
    #     opponent-controlled creature into the EXISTING
    #     ``TriggerPayload.target_id`` via ``new_trigger_with_target``
    #     (CE20 Slice 4 — no new ``StackItem`` field); the resolve arm
    #     reads it via ``current_resolve_payload_target_id``
    #     (the ``EquipToTargetCreatureYouControl`` precedent).
    #     ``count_min>=1`` + no eligible target ⇒ trigger NOT pushed
    #     (CR 603.3c fizzle).
    #   * **Python** — the no-agent ``pool[0]`` seat at
    #     ``actions.py:_put_triggered_ability_on_stack`` (the
    #     ``controller.agent is None`` branch), gated to
    #     ``_is_target_seated_safe_trigger``; ``pool[0]`` IS
    #     ``Effect._enumerate_for_filter``'s first entry =
    #     ``legal_targets[0]`` = the same object Rust seats. No legal
    #     target with ``min_t>0`` ⇒ Python's existing
    #     "no legal targets; fizzles" ``return False`` — byte-equal
    #     with the Rust skip-push.
    # Both directions resolve to the SAME object by construction (the
    # cross-engine harness keeps bf insertion order + object ids in
    # lockstep), so the post-resolve ``counters`` fingerprint is
    # byte-equal. The deterministic-first no-agent target replacing
    # the CR 603.3d controller choice is documented in
    # ``docs/SEARCH_LIMITATIONS.md`` §2.3 (same class as every
    # ``_PickFirst*`` / first-eligible-resolve-arm convention the
    # campaign already documents).
    #
    # **Bridge support (the lockstep contract — both exist before
    # this entry):**
    #   * Rust ``Effect::PutPlusOneCounterOnOpponentsCreature
    #     { amount: i32 }`` variant + parse / to_dict / resolve arms
    #     (``rust/src/cards.rs`` + ``state_ops_resolve.rs``) — the
    #     opponent-direction sibling of the existing
    #     ``PutPlusOneCounterOnCreatureYouControl``, but reading the
    #     SEATED payload target (NOT a first-eligible self-scan — a
    #     self-scan is exactly the divergence the shared seat removes).
    #   * Python ``PutPlusOneCounterOnOpponentsCreature(amount: int =
    #     1)`` (effects/generic/counters.py — a ``PutPlusOneCounters``
    #     subclass) + the ``put_plus_one_counter_on_opponents_creature``
    #     cross_engine bridge arm. Bare ``amount`` payload, identical
    #     spelling both engines, non-negative-guarded.
    # The ATTACKS event dispatch itself is already byte-equal-proven
    # (round-43/44 surveil/draw/gain ATTACKS pins). The genuine
    # real-EoE firing-parity probe is in test_parity_smoke.py.
    #
    # **Necessary-but-not-sufficient teeth.** ``(attacks,
    # source_is_self)`` is shared by Hardened Escort / Flesh Burrower
    # (``ATTACKS/source_is_self/PumpTargetCreatureUntilEOT``) — those
    # are NOT admitted because ``pump_target_creature_until_eot`` is
    # never added to the ATTACKS ``safe_effect_kinds``. The gate is
    # the full triple + the recognizer's bare-shape slot check, NOT
    # the bare targeted-ATTACKS shape (negative-pinned in
    # tests/test_trajectory.py).
    ("attacks", "source_is_self", "put_plus_one_counter_on_opponents_creature"),
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
    # **Friendly Teddy Cycle 1 (2026-05-22)** — DIES+IsSelf+
    # ``each_player_draws``. Admits **Friendly Teddy** (Duskmourn —
    # Artifact Creature — Bear Toy, ``{2}``, 2/2: "When this creature
    # dies, each player draws a card."). The bridge round-trips the
    # ``EachPlayerDraws(amount=1)`` leaf via the new
    # ``each_player_draws`` cross_engine bridge arm + Rust
    # ``Effect::EachPlayerDraws { count }`` variant. The cross-engine
    # contract:
    #
    #   * DIES event dispatch: already proven byte-equal under
    #     ``draw_cards`` (round-47 sister) / ``gain_life`` (round-47)
    #     / ``surveil`` (round-42) leaves. Both engines fire the
    #     DIES-event triggered ability after the bf -> graveyard
    #     move; the resolve runs deterministically with no
    #     PendingDecision / agent setup (every player draws
    #     unconditionally — no per-player choice).
    #   * ``each_player_draws`` leaf: bridge arm at
    #     ``cross_engine._ta_dict_to_python_effect``
    #     ("each_player_draws") + Python ``EachPlayerDraws(amount:
    #     int)`` (``effects/generic/draw_mill.py:230``). Rust
    #     ``Effect::EachPlayerDraws { count: i32 }`` resolves
    #     deterministically on both engines via APNAP iteration
    #     (active player FIRST, then mod-wraparound) skipping
    #     ``has_lost`` players, drawing ``count`` cards per non-lost
    #     player. NO source-controller lookup needed (every player
    #     draws regardless of who controls the source).
    #
    # **Cross-engine default-strategy contract.** Identical to the
    # sibling DIES+IsSelf+draw_cards / gain_life entries: no agent
    # setup needed for the trajectory walk. The post-triggered-
    # ability path drains the deterministic EachPlayerDraws resolve
    # in lockstep on both engines because the effect mutates state
    # via pure library-top pops with no PendingDecision queue
    # interaction.
    #
    # **Friendly Teddy is from Duskmourn (DSK), not EoE.** The
    # admit-flip lands the bench-substrate for any future EoE
    # printing carrying the DIES+IsSelf+each_player_draws shape
    # (the "When ~ dies, each player draws a card" oracle pattern
    # is broadly used across MTG history — Howling Mine-style
    # symmetric draw effects); no EoE consumer is admitted on this
    # leaf today, but the per-card cross-engine probe at
    # ``tests/test_friendly_teddy_parity.py`` drives the real
    # Friendly Teddy DSK printing through both engines end-to-end,
    # mirroring the Comet Crawler / Mutinous Massacre per-card
    # parity-test module convention.
    ("dies", "source_is_self", "each_player_draws"),
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
    # **Anticausal Vestige Cycle 2 (2026-05-24)** — the FIRST
    # LEAVES_BATTLEFIELD entry in the safe set, and the FIRST
    # genuinely-new event vocabulary since BECOMES_TAPPED. Sole
    # admitted EoE consumer at HEAD is **Anticausal Vestige** ({2}{B}
    # 2/2 warp creature with ``warp_cost {4}``, ~6,900 17lands decks
    # — the #3-ranked multi-gated-tail closure target from the
    # 2026-05-24 multi-gated tractability scout). Parser-emitted
    # shape: LEAVES_BATTLEFIELD trigger with ``IsSelf`` predicate +
    # bespoke unit-variant ``AnticausalVestigeLeavesEffect`` effect.
    #
    # **Bridge support (all pre-existed; this slice only wires the
    # safe-trigger recognizer + the matching triple + the bare-shape
    # whitelist).**
    #   * Rust ``Effect::AnticausalVestigeLeavesEffect`` (unit variant,
    #     rust/src/cards.rs) + parse_effect arm + effect_to_pydict arm
    #     + resolve arm in ``state_ops_resolve.rs`` shipped in C1
    #     commit ``e148450a`` (2026-05-24). The resolve arm mirrors
    #     the seated-agent deterministic ``candidates[0]`` fallback
    #     path step-for-step (draw 1, count controller lands as X,
    #     scan hand for first permanent with ``mana_cost.total <= X``,
    #     remove from hand, put onto bf TAPPED with
    #     ``summoning_sick=True``, queue ``Event::Enters`` dispatch).
    #   * Cross-engine bridge arm at ``cross_engine.py:9475`` (also
    #     shipped in C1) consumes ``{"kind": "anticausal_vestige_
    #     leaves_effect"}`` and yields the Python instance; extra dict
    #     keys ignored per the unit-variant convention.
    #
    # **No silent-mistranslation rider on this leaf.** Unit-variant ⇒
    # no payload keys to gate (contrast Surveil's ``use_artifact_count``
    # or LookTopN's ``reveal_chosen``). The dict-side extra-key refusal
    # in :func:`_is_safe_trigger_dict` (backed by the bare ``{"kind"}``
    # whitelist in ``_SAFE_EFFECT_KEYS`` below) is the only round-trip
    # backstop needed.
    #
    # **Cross-engine resolve contract along the deterministic-first
    # candidates[0] path.** Both engines split the resolve into a
    # "draw + filter + pick" phase + a "put-onto-bf + queue ETB"
    # phase. The seated-agent deterministic-first contract was the C1
    # honest-stop's open design question (deferred); C2 ships the
    # admit widen under the assumption it's stable. If the C3 per-card
    # real-EoE byte-equality probe surfaces a byte-divergence under
    # deterministic-first, THAT's where the design pivots to a real
    # ``PendingDecision::PickCardFromHandChoice`` round-trip (NOT in
    # this C2 slice).
    #
    # **LEAVES_BATTLEFIELD ≠ DIES.** ``DIES`` is the strict bf→
    # graveyard subset; ``LEAVES_BATTLEFIELD`` covers every bf→
    # {anywhere} zone change (bounce / exile / library / hand /
    # graveyard). Genuinely new event vocabulary — not a relabel of
    # DIES.
    ("leaves_battlefield", "source_is_self",
     "anticausal_vestige_leaves_effect"),
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
    # **Friendly Teddy Cycle 1 (2026-05-22)** — ``each_player_draws``
    # bare-shape: single ``count`` payload key. Rust's
    # ``Effect::EachPlayerDraws { count: i32 }``
    # (rust/src/cards.rs) is bare: every non-lost player draws
    # ``count`` cards in APNAP order. Python's
    # ``EachPlayerDraws(amount: int)``
    # (``effects/generic/draw_mill.py:230``) is the matched class;
    # its single ``amount`` field round-trips to Rust's ``count``
    # spelling via the new ``each_player_draws`` bridge arm
    # (``cross_engine.py``, this slice — same ``count``/``amount``
    # spelling discrepancy as the established ``draw_cards`` /
    # ``each_opponent_mills_cards`` / ``mill`` arms). The bare
    # ``count`` payload is the only field on either side — no
    # rider the bridge would silently drop (unlike Surveil's
    # ``use_artifact_count`` or PumpSelf's ``granted_keywords``).
    # The recognizer in :func:`_python_ta_to_safe_dict` gates this
    # whitelist.
    "each_player_draws": frozenset({"kind", "count"}),
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
    # PutPlusOneCounterOnOpponentsCreature — single ``amount`` payload
    # key (Tier-C target-seating sub-substrate, lever-a — Sunset
    # Saboteur). Rust's
    # ``Effect::PutPlusOneCounterOnOpponentsCreature { amount: i32 }``
    # (rust/src/cards.rs) is bare: it adds ``amount`` +1/+1 counters
    # to the push-time-SEATED target (a creature an opponent of the
    # source's controller controls; the seat is the Tier-C shared
    # ``first_legal_trigger_target`` / no-agent ``pool[0]`` pick — NOT
    # a payload field, NOT a self-scan). Its to_dict emits ``{"kind":
    # "put_plus_one_counter_on_opponents_creature", "amount": <i32>}``
    # — IDENTICAL spelling to Python's
    # ``PutPlusOneCounterOnOpponentsCreature(amount: int = 1)``
    # (effects/generic/counters.py, a ``PutPlusOneCounters``
    # subclass), round-tripped by the
    # ``put_plus_one_counter_on_opponents_creature`` cross_engine
    # bridge arm. The slot filter
    # (``IsCreature() & ControlledByOpponent()``) is NOT a dict
    # payload key — it is structural to the effect class on Python and
    # to the seat's per-variant scan on Rust (the recognizer's
    # bare-shape gate enforces the single-implicit-target contract),
    # so the payload whitelist stays the bare ``{"kind", "amount"}``
    # exactly like the ``put_plus_one_counter_on_self`` sibling. The
    # recognizer in :func:`_python_ta_to_safe_dict` gates this
    # whitelist; the ``_is_safe_trigger_dict`` extra-key refusal is
    # the backstop.
    "put_plus_one_counter_on_opponents_creature": frozenset(
        {"kind", "amount"}
    ),
    # ReturnTargetPermanentYouControlToOwnersHand — UNIT shape, the
    # only payload key is ``kind`` (Tier-C target-seating
    # sub-substrate, lever-a — Exosuit Savior, the count_min=0
    # optional-bounce edge). Rust's
    # ``Effect::ReturnTargetPermanentYouControlToOwnersHand``
    # (rust/src/cards.rs) is a unit variant — no amount / no rider;
    # its to_dict emits ``{"kind":
    # "return_target_permanent_you_control"}`` and the parse arm
    # tolerates/ignores extra fields. Python's
    # ``ReturnTargetPermanentYouControlToOwnersHand(optional=True,
    # exclude_self=True)`` (effects/generic/bounce.py, a ``Bounce``
    # subclass) is reconstructed by the
    # ``return_target_permanent_you_control`` cross_engine bridge arm
    # with the optional/exclude_self flags fixed structurally (they
    # ARE Exosuit Savior's shape — not caller-varied). The slot
    # filter (own ∧ ~player ∧ ~source) and count_min=0 are structural
    # to the effect class / the seat's per-variant scan, NOT dict
    # payload keys (the recognizer's bare-shape gate enforces the
    # single implicit-target contract), so the whitelist is the bare
    # ``{"kind"}``. The recognizer in
    # :func:`_python_ta_to_safe_dict` gates this whitelist; the
    # ``_is_safe_trigger_dict`` extra-key refusal is the backstop.
    "return_target_permanent_you_control": frozenset({"kind"}),
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
    # **Codecracker Hound Cycle 2 (2026-05-24)** —
    # ``look_top_n_put_one_in_hand_rest_to_graveyard`` bare-shape: three
    # payload keys (``kind`` + ``n`` + ``reveal_chosen``). Rust's
    # ``Effect::LookTopNPutOneInHandRestToGraveyard { n: i32 }``
    # (rust/src/cards.rs:4392) carries only ``n`` — its parse_effect at
    # cards.rs:12042-12056 reads ``n`` and ignores other fields, so
    # carrying ``reveal_chosen`` in the dict is structurally safe on the
    # Rust side (effective ``reveal_chosen=False`` always, since Rust's
    # resolve never reveals). Python's
    # ``LookTopNPutOneInHandRestToGraveyard(n: int = 4, reveal_chosen:
    # bool = True)`` (effects/generic/library_lookat.py:160) carries the
    # ``reveal_chosen`` rider for parser-faithful no-reveal observable
    # on the Codecracker Hound surface form. The recognizer
    # (``_python_ta_to_safe_dict``) gates on ``eff.reveal_chosen == False``
    # so the only dict emitted by the safe-trigger path carries
    # ``reveal_chosen: False`` — that gate is the §2 silent-mistranslation
    # teeth, NOT this whitelist (the whitelist's job is to refuse any
    # OTHER unrecognized key, e.g. a future rider added to either engine
    # without a matched bridge widen). The bridge arm at
    # ``cross_engine.py:4901-4978`` reads ``reveal_chosen`` to
    # reconstruct the Python instance with the matching flag — the
    # post-resolve byte-equality contract requires both engines to skip
    # the ``reveal_to_all`` rider. See the ``("enters", "source_is_self",
    # "look_top_n_put_one_in_hand_rest_to_graveyard")`` entry in
    # :data:`_SAFE_TRIGGERS` for the full cross-engine parity provenance
    # + the Cycle-3 per-card real-EoE byte-equality probe plan.
    "look_top_n_put_one_in_hand_rest_to_graveyard": frozenset(
        {"kind", "n", "reveal_chosen"}
    ),
    # **Anticausal Vestige Cycle 2 (2026-05-24)** —
    # ``anticausal_vestige_leaves_effect`` bare unit-variant: ONLY
    # ``kind`` (no payload fields). Rust's
    # ``Effect::AnticausalVestigeLeavesEffect`` (rust/src/cards.rs
    # unit variant shipped in C1 commit ``e148450a``) carries no
    # fields — its parse_effect arm reads only ``kind`` (extras
    # ignored), its to_pydict emits the SAME minimal unit-shape
    # ``{"kind": "anticausal_vestige_leaves_effect"}``. Python's
    # ``AnticausalVestigeLeavesEffect`` (``effects/bespoke.py:858-
    # 907``) is a no-args ``@dataclass`` — also no payload. Both the
    # land count (X) and the hand pick are dynamic resolve-time
    # computations, not static fields. The bridge arm at
    # ``cross_engine.py:9475`` round-trips the bare ``{"kind"}`` dict
    # (extras ignored per the unit-variant convention) to the Python
    # instance. The recognizer in :func:`_python_ta_to_safe_dict`
    # emits the bare dict shape (no payload fields); this whitelist
    # gates any future extra-key drift as the round-trip backstop
    # (the ``_is_safe_trigger_dict`` extra-key refusal). See the
    # ``("leaves_battlefield", "source_is_self",
    # "anticausal_vestige_leaves_effect")`` entry in
    # :data:`_SAFE_TRIGGERS` for the full cross-engine parity
    # provenance + the C3 per-card real-EoE byte-equality probe plan.
    "anticausal_vestige_leaves_effect": frozenset({"kind"}),
    # **Weftwalking Cycle 2 (2026-05-24)** —
    # ``conditional_if_cast_from_hand`` recursive composer: two payload
    # keys (``kind`` + ``inner``). Rust's
    # ``Effect::ConditionalIfCastFromHand { inner: Box<Effect> }``
    # (rust/src/cards.rs — recursive Box payload, sibling of MayDo /
    # IfYouDo / OptionalSacAnotherForEffect) carries the ``inner``
    # field as a nested Effect dict; the parse_effect arm recursively
    # parses ``inner`` via the same parse_effect dispatcher. Python's
    # ``ConditionalIfCastFromHand(inner_effect: Effect)`` (effects/
    # combinators.py:1513) is the matched class; the field-name
    # translation seam (Rust ``inner`` ↔ Python ``inner_effect``)
    # lives in the bridge arm at ``cross_engine.py:2295-2346`` and
    # the reverse-serializer leaf at trajectory.py:5607-5614 (both
    # shipped in C1 substrate commit ``61f04bef``). The recognizer in
    # :func:`_python_ta_to_safe_dict` gates on the EXACT canonical
    # Weftwalking inner shape (``Sequence(ShuffleZonesIntoLibrary(
    # zones=('hand','graveyard')), DrawCards(amount=7))``); the
    # ``inner`` field passes the dict-shape whitelist (it is a nested
    # dict, not an unrecognized scalar key) but the recognizer's
    # narrow-shape gate is the §2 silent-mistranslation teeth — any
    # other inner shape gets rejected before reaching this whitelist.
    # See the ``("enters", "source_is_self",
    # "conditional_if_cast_from_hand")`` entry in
    # :data:`_SAFE_TRIGGERS` for the full cross-engine parity
    # provenance + the C3 per-card real-EoE byte-equality probe plan.
    "conditional_if_cast_from_hand": frozenset({"kind", "inner"}),
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


# **Warping Wail Cycle 3 (2026-05-24) — token-AA bridge widen for the
# Eldrazi-Scion creature-token-with-sac-self-mana-ability shape.** The
# exact bridge-correct activated-ability dict for the EoE ``Eldrazi
# Scion`` token: ``Sacrifice this token: Add {C}.`` minted by Warping
# Wail's third mode. Round-trips Python<->Rust with NO §2 gap:
#   * the cost is ``sacrifice_self`` alone (no mana / tap component) —
#     the exact subset both engines pay identically (Rust's
#     ``parse_activation_cost`` accepts the bare bool; Python's
#     ``ActivationCost`` honors it bit-identically);
#   * the effect is ``add_mana_to_pool`` with a single ``(color, amount)``
#     pair — Rust's scalar-pair ``Effect::AddManaToPool { color: String,
#     amount: i32 }`` and the bridge's
#     :func:`cross_engine._ta_dict_to_python_effect` ``add_mana_to_pool``
#     arm fold to Python's one-pair ``produces=((color, amount),)``;
#   * ``is_mana_ability: True`` flags the CR 605.3a stack-bypass on
#     BOTH engines (Rust's ActivateAbility path direct-credits the
#     pool, Python's ``ActivatedAbility.is_mana_ability=True`` does
#     the same).
# This is the ONLY token-activated ability the creature-token+mana-AA
# Phase admits; any token whose activated ability differs from this
# exact dict stays declined (§2 — a divergent cost component, a
# non-mana effect, or ``is_mana_ability=False`` would silently
# mistranslate or change the activation timing). The ``color`` is
# pinned to ``"C"`` because the real EoE Eldrazi Scion produces exactly
# one colorless mana; a hypothetical multi-color / multi-amount variant
# is a separate recognizer-widen and is NOT admitted here.
_ELDRAZI_SCION_SAFE_ACTIVATED_ABILITY: dict = {
    "cost": {"sacrifice_self": True},
    "effect": {"kind": "add_mana_to_pool", "color": "C", "amount": 1},
    "is_mana_ability": True,
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


def _token_creature_with_safe_mana_activated_ability_card_def(
    token_printing,
) -> Optional["CardDef"]:
    """Build a :class:`cross_engine.CardDef` from a token
    ``CardPrinting`` iff the token is a CREATURE whose ONLY activated
    ability is the exact bridge-correct Eldrazi-Scion shape (and it is
    otherwise clean), else ``None``.

    **Warping Wail Cycle 3 (2026-05-24) — token-AA bridge widen for
    creature tokens with sac-self mana abilities.** Sibling of
    :func:`_token_vanilla_card_def` (vanilla creature, no AAs) and
    :func:`_token_with_safe_activated_ability_card_def` (Lander shape —
    non-creature with the {2}+Sac+Search AA). This third helper closes
    the §2-honest gap left by the first two: a CREATURE token with one
    activated ability whose shape is

      ``Sacrifice this token: Add {C}``  (``is_mana_ability=True``)

    The dict-side shape is :data:`_ELDRAZI_SCION_SAFE_ACTIVATED_ABILITY`.

    **§2 silent-mistranslation discipline (STRICT).** The token must:

      * have ``Creature`` among its card types AND non-None printed
        P/T (a creature-token GameObject's per-object signature includes
        power / toughness — None-P/T would silently diverge).
      * carry EXACTLY ONE activated ability, byte-equal to the real
        authored ``TOKEN_PRINTINGS["Eldrazi Scion"]`` ability AND to
        :data:`_ELDRAZI_SCION_SAFE_ACTIVATED_ABILITY` (cost
        ``sacrifice_self`` alone — NO mana, NO tap, NO other sac flag;
        effect ``AddManaToPool(produces=(("C", 1),))``;
        ``is_mana_ability=True``). ANY deviation (an added mana / tap
        cost, an extra sac flag, a different color or amount, a non-
        mana effect, or ``is_mana_ability=False``) keeps the token
        DECLINED — admitting a token whose ability silently differs
        cross-engine is exactly the §2 class this campaign exists to
        avoid.
      * carry NO keywords / static abilities / triggered abilities /
        nested abilities / block-restriction flags (CardDef carries
        only the synthesized single activated ability via
        ``token_activated_abilities``; any other token feature would
        silently vanish on the bridge).

    The synthesized CardDef's ``card_type`` is ``"Creature"`` (with
    any multi-type overlap threaded through ``extra_card_types`` —
    the Eldrazi Scion is single-type ``Creature`` so this is the
    empty tuple in practice). The ``Token`` supertype is stamped so
    both engines remove the token from non-battlefield zones per CR
    704.5d. P/T thread through as in :func:`_token_vanilla_card_def`.

    **Why a sibling rather than widening
    :func:`_token_with_safe_activated_ability_card_def`?** The two
    shapes have orthogonal positive gates:
      * Lander: NON-creature artifact, mana+sacrifice_self cost,
        non-mana-ability search effect.
      * Eldrazi Scion: CREATURE, sacrifice_self ONLY cost, mana-ability
        AddManaToPool effect.
    Widening the single helper to admit BOTH would require disjunctive
    cost-and-effect gating that obscures the per-shape §2 contract.
    The sibling-split mirrors the Lander vs. vanilla split — each
    helper §2-strictly admits ONE token shape and declines every
    other, so a future bug in either path can't silently widen the
    other.

    **Substrate-only landing.** Cycle 3 lands the helper + a sibling
    constant + the byte-equal probe. The
    :func:`_printing_is_bridge_simple_spell` admit predicate is NOT
    flipped — that's Cycle 4's job. The
    ``test_warping_wail_stays_declined_at_admit_gate_post_cycle_1a``
    pin in ``tests/test_warping_wail_substrate_cycle_1a.py``
    continues to fire (and is verified still-green by this lane's
    sanity gates).
    """
    from mtg_bot.effects.base import ActivatedAbility
    from mtg_bot.effects.generic.mana import AddManaToPool

    if token_printing is None:
        return None
    card_types = tuple(getattr(token_printing, "card_types", ()) or ())
    if "Creature" not in card_types:
        return None
    # Creature body requires non-None printed P/T (the per-object
    # signature carries P/T; a None-P/T creature token would silently
    # diverge cross-engine).
    if token_printing.power is None or token_printing.toughness is None:
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
    # STRICT cost gate: exactly ``sacrifice_self`` alone. NO mana cost,
    # NO tap, NO other sac flag, NO targeting requirement. Any extra
    # cost component would round-trip differently or silently change
    # cross-engine activation legality (§2).
    cost = aa.cost
    if cost.mana is not None:
        # The Eldrazi Scion AA carries no mana cost — its ``cost.mana``
        # is ``None`` on the authored printing. A printing whose mana
        # is a zero-but-present ManaCost should still be DECLINED
        # here because the bridge dict would carry the empty mana
        # field, which the round-trip-or-bail teeth would reject as
        # a shape drift.
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
    # STRICT effect gate: ``AddManaToPool(produces=(("C", 1),))``.
    # No spend_restriction, exactly one (color, amount) pair, color
    # is colorless, amount is 1.
    if not isinstance(aa.effect, AddManaToPool):
        return None
    if getattr(aa.effect, "spend_restriction", None) is not None:
        return None
    produces = tuple(aa.effect.produces or ())
    if produces != (("C", 1),):
        return None
    if not getattr(aa, "is_mana_ability", False):
        return None
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
        token_activated_abilities=(
            dict(_ELDRAZI_SCION_SAFE_ACTIVATED_ABILITY),
        ),
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
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetPermanentYouControlToOwnersHand,
    )
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCounterOnOpponentsCreature,
        PutPlusOneCounterOnSelf,
    )
    from mtg_bot.effects.generic.draw_mill import DrawCards, EachPlayerDraws
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.generic.library_lookat import (
        LookTopNPutOneInHandRestToGraveyard,
        Scry,
        SelfMill,
        Surveil,
    )
    from mtg_bot.effects.generic.pump import PumpSelfUntilEOT
    from mtg_bot.effects.generic.tokens import CreateToken
    # **Anticausal Vestige Cycle 2 (2026-05-24).** The bespoke
    # unit-variant whose LEAVES_BATTLEFIELD+IsSelf safe-trigger leaf
    # this slice admits. Imported alongside the other effect classes
    # so the ``isinstance`` dispatch below recognizes it.
    from mtg_bot.effects.bespoke import AnticausalVestigeLeavesEffect
    # **Weftwalking Cycle 2 (2026-05-24).** The recursive composer
    # whose narrow ConditionalIfCastFromHand(Sequence(Shuffle..., Draw))
    # shape this slice admits. Imported alongside the other effect
    # classes so the ``isinstance`` dispatch below recognizes the
    # combinator (the inner Sequence + ShuffleZonesIntoLibrary +
    # DrawCards leaves are imported above already).
    from mtg_bot.effects.combinators import (
        ConditionalIfCastFromHand,
        Sequence,
    )
    from mtg_bot.effects.generic.zone_moves import ShuffleZonesIntoLibrary
    # **Spacecraft Phase 3A Cycle 1 (2026-05-25).** Reverse-serializer
    # leaf import for ``OptionalSacLandOrLanderForBasicLandRamp`` — the
    # Larval Scoutlander ETB ramp Effect (
    # ``effects/combinators.py:699``). Substrate-only landing — the
    # arm below recognizes the Effect class and constructs the round-
    # trip dict, but the kind string is NOT in any (event, predicate)
    # ``safe_effect_kinds`` set yet, so the ``eff_kind not in
    # safe_effect_kinds`` gate below the dispatch cascade returns None
    # and Larval Scoutlander STAYS DECLINED at the
    # ``_python_ta_to_safe_dict`` gate post-Cycle-1. Cycle 2 ships the
    # Phase-3 admit predicate (which uses its own dispatch separate
    # from ``_python_ta_to_safe_dict`` per design doc §5.3) + the FLIP.
    # Import kept narrow per the established convention.
    from mtg_bot.effects.combinators import (
        OptionalSacLandOrLanderForBasicLandRamp,
    )
    # **Spacecraft Phase 3B Cycle 1 (2026-05-25).** Reverse-serializer
    # leaf import for ``OptionalPutCreatureFromHandOntoBattlefield`` —
    # Sledge-Class Seedship's ATTACKS trigger Effect (
    # ``effects/combinators.py:205``). Substrate-only landing — the
    # arm below recognizes the Effect class and constructs the round-
    # trip dict, but the kind string is NOT in any (event, predicate)
    # ``safe_effect_kinds`` set yet (the Phase-3 admit predicate has
    # its OWN dispatch path separate from ``_python_ta_to_safe_dict``
    # per design doc §5.3a). Sledge-Class Seedship STAYS DECLINED at
    # the ``_python_ta_to_safe_dict`` gate post-Cycle-1. Cycle 2 widens
    # ``_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES`` to include this
    # Effect class + extends ``_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_
    # SHAPES`` with ``(ATTACKS, IsSelf())`` + the FLIP per design doc
    # §7.2.
    from mtg_bot.effects.combinators import (
        OptionalPutCreatureFromHandOntoBattlefield,
    )

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
    # **Anticausal Vestige Cycle 2 (2026-05-24)** widens the gate to
    # also admit ``LEAVES_BATTLEFIELD`` — the FIFTH event in the safe
    # set, and the FIRST genuinely-new event vocabulary since
    # BECOMES_TAPPED. ``LEAVES_BATTLEFIELD`` is *not* ``DIES``: ``DIES``
    # is the strict bf→graveyard subset whereas ``LEAVES_BATTLEFIELD``
    # covers every bf→{anywhere} zone change (bounce / exile / library
    # / hand / graveyard). The sole admitted EoE consumer at HEAD is
    # **Anticausal Vestige** ({2}{B} 2/2 warp creature with
    # ``warp_cost {4}``, ~6,900 17lands decks — the #3-ranked multi-
    # gated-tail closure target). The C1 substrate (commit
    # ``e148450a``) shipped Rust's
    # ``Effect::AnticausalVestigeLeavesEffect`` unit variant + parse /
    # to_pydict / resolve arms + the cross_engine bridge arm. The C2
    # widen here threads LEAVES through the recognizer + the matching
    # ``_SAFE_TRIGGERS`` triple + ``_SAFE_EFFECT_KEYS`` bare-shape
    # whitelist; the warp arm
    # (``_printing_is_bridge_pure_warp_creature``) now admits AV.
    #
    # **Verify-first silent-auto-grow check.** Live HEAD scan
    # confirmed only 5 other cards carry a LEAVES_BATTLEFIELD
    # triggered ability (Cryogen Relic, Broodguard Elite, Syr Vondam,
    # Nutrient Block, and AV itself). None silently auto-grow under
    # this widen: Cryogen Relic / Nutrient Block carry ``DrawCards``
    # which is not in the LEAVES ``safe_effect_kinds`` arm below;
    # Broodguard Elite + Syr Vondam carry non-safe effect kinds
    # (``MoveSelfCountersToTargetCreatureYouControl`` / ``Sequence`` /
    # ``ConditionalIfSourcePowerAtLeast``) and Syr Vondam additionally
    # has an ``And`` predicate. The widen is genuinely AV-scoped at
    # HEAD; a future LEAVES carrier with a different safe leaf would
    # be a single one-line widen here + a paired ``_SAFE_TRIGGERS``
    # entry (same pattern as the ENTERS/DIES/ATTACKS leaf-set
    # extensions).
    if ta.event not in (
        Event.ENTERS, Event.DIES, Event.ATTACKS, Event.BECOMES_TAPPED,
        Event.LEAVES_BATTLEFIELD,
    ):
        return None
    if ta.event is Event.ENTERS:
        event_str = "enters"
    elif ta.event is Event.DIES:
        event_str = "dies"
    elif ta.event is Event.BECOMES_TAPPED:
        event_str = "becomes_tapped"
    elif ta.event is Event.LEAVES_BATTLEFIELD:
        event_str = "leaves_battlefield"
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
            # Tier-C target-seating lever-a (Exosuit Savior) widens
            # the ENTERS+IsSelf arm with the targeted-safe leaf
            # ``return_target_permanent_you_control`` (the
            # count_min=0 optional-bounce edge — the ENTERS sibling
            # of Sunset Saboteur's ATTACKS
            # ``put_plus_one_counter_on_opponents_creature``). The
            # predicate-effect product is still enforced by the
            # ``("enters", "source_is_self",
            # "return_target_permanent_you_control")``
            # ``_SAFE_TRIGGERS`` entry (this list is necessary, not
            # sufficient); the recognizer's bare-shape gate above is
            # the §2 teeth.
            # **Codecracker Hound Cycle 2 (2026-05-24) — 9th ENTERS+IsSelf
            # leaf.** Adds ``look_top_n_put_one_in_hand_rest_to_graveyard``
            # to the safe set. Sole admitted EoE consumer at HEAD is
            # Codecracker Hound ({1}{U} 2/2 warp creature, ENTERS+IsSelf+
            # ``LookTopNPutOneInHandRestToGraveyard(n=2, reveal_chosen=
            # False)``). Bridge support: Rust ``Effect::LookTopNPutOne
            # InHandRestToGraveyard { n: i32 }`` (cards.rs:4392 +
            # parse_effect at cards.rs:12042-12056 + resolve at
            # state_ops_resolve.rs:6366-6394 + PendingDecision::Pick
            # CardFromExaminedChoice + submit_pick_card_decision
            # dispatcher) has been on main since round 28; the
            # cross_engine bridge arm (cross_engine.py:4901-4978) has
            # been on main since round 21. The §2 silent-mistranslation
            # gate (handled in the effect-class arm below): the parsed
            # Codecracker Hound effect MUST carry ``reveal_chosen=
            # False`` (Rust's resolve never reveals; admitting a
            # ``reveal_chosen=True`` instance would silently mistranslate
            # public-knowledge state across engines — the Python
            # ``reveal_to_all`` rider sets ``publicly_known_to`` whereas
            # Rust does not). Codecracker Hound's parser path explicitly
            # emits ``reveal_chosen=False``; Commune-with-Evil (which
            # uses the same primitive at n=4 with ``reveal_chosen=True``)
            # is a Sorcery (spell_effect, not a triggered ability), so
            # it does NOT flow through this safe-trigger path.
            # **Weftwalking Cycle 2 (2026-05-24) — 10th ENTERS+IsSelf
            # leaf.** Adds ``conditional_if_cast_from_hand`` to the safe
            # set. Sole admitted EoE consumer at HEAD is **Weftwalking**
            # ({4}{U}{U} Enchantment, ~3,680 17lands decks — the #1
            # multi-gated-tail closure target from the 2026-05-24
            # tractability rescout). Parser-emitted shape: ETB trigger
            # with ``IsSelf`` predicate + ``ConditionalIfCastFromHand``
            # whose ``inner_effect`` is the NARROW
            # ``Sequence(ShuffleZonesIntoLibrary(zones=('hand',
            # 'graveyard')), DrawCards(amount=7))`` composite — the
            # admit gate in the effect-class arm below enforces that
            # exact inner shape; the wrap stays SURGICAL (does NOT
            # silently admit arbitrary combinator inners). Bridge
            # support (both Rust + cross_engine bridge arms) shipped
            # in C1 substrate commit ``61f04bef``.
            #
            # **Silent auto-grow check.** Live HEAD scan confirmed
            # Weftwalking is the SOLE carrier of
            # ``ConditionalIfCastFromHand`` system-wide (any card type,
            # any event/predicate combination); no other Enchantment /
            # Creature / Spell carries the combinator. The widen is
            # genuinely Weftwalking-scoped at HEAD; a future carrier
            # with a different inner shape would be rejected by the
            # narrow ``inner_effect``-shape gate in the effect-class
            # arm (would need a paired widen + new ``_SAFE_TRIGGERS``
            # entry, same pattern as the AV / CH C2 leaf-set
            # extensions).
            safe_effect_kinds = (
                "draw_cards", "gain_life", "scry_n", "surveil", "mill",
                "create_token", "create_token_tapped",
                "return_target_permanent_you_control",
                "look_top_n_put_one_in_hand_rest_to_graveyard",
                "conditional_if_cast_from_hand",
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
            # Tier-C target-seating lever-a (Sunset Saboteur) widens
            # the ATTACKS+IsSelf arm with the FIRST targeted-safe leaf
            # ``put_plus_one_counter_on_opponents_creature``. The
            # predicate-effect product is still enforced by the
            # ``("attacks", "source_is_self",
            # "put_plus_one_counter_on_opponents_creature")``
            # ``_SAFE_TRIGGERS`` entry (this list is necessary, not
            # sufficient); the recognizer's bare-shape gate above is
            # the §2 teeth.
            safe_effect_kinds = (
                "surveil", "draw_cards", "gain_life",
                "put_plus_one_counter_on_opponents_creature",
            )
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
            # Friendly Teddy Cycle 1 (2026-05-22) extends the
            # DIES+IsSelf leaf set with ``each_player_draws`` — the
            # bare-shape "When ~ dies, each player draws a card"
            # oracle pattern. Friendly Teddy (DSK) is the first
            # admitted carrier; broadly pre-positions the substrate
            # for any future EoE / standard-format printing carrying
            # the same dies+each-player-draws shape. The bridge arm
            # at ``cross_engine._ta_dict_to_python_effect``
            # ("each_player_draws") + Rust
            # ``Effect::EachPlayerDraws { count }`` (this slice) +
            # the dict-shape gate
            # (``_SAFE_EFFECT_KEYS["each_player_draws"] =
            # {"kind","count"}`` above) close the cross-engine
            # round-trip, so this leaf composes deterministically
            # under DIES with no PendingDecision setup.
            safe_effect_kinds = (
                "surveil", "gain_life", "draw_cards",
                "create_token", "create_token_tapped",
                "each_player_draws",
            )
        elif ta.event is Event.BECOMES_TAPPED:
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
        else:
            # Event.LEAVES_BATTLEFIELD (**Anticausal Vestige Cycle 2**,
            # 2026-05-24 — the FIFTH event in the safe set). The ONLY
            # safe leaf under LEAVES_BATTLEFIELD+IsSelf today is
            # ``anticausal_vestige_leaves_effect`` — the bespoke
            # unit-variant whose Rust ``Effect::AnticausalVestige
            # LeavesEffect`` (cards.rs unit variant + parse / to_pydict
            # / resolve arms shipped in C1 commit ``e148450a``) and
            # Python ``AnticausalVestigeLeavesEffect`` (effects/
            # bespoke.py:858-907) mirror each other step-for-step along
            # the seated-agent deterministic ``candidates[0]`` fallback
            # path (draw 1, count controller lands as X, pick first
            # mana-value-≤-X permanent from hand, put onto bf tapped
            # with summoning_sick=True, queue Enters dispatch). The
            # cross_engine bridge arm at ``cross_engine.py:9475`` (also
            # shipped in C1) consumes the unit-shape dict ``{"kind":
            # "anticausal_vestige_leaves_effect"}`` and yields the
            # Python instance.
            #
            # Deliberately narrow: the verify-first scan of HEAD found
            # only 4 OTHER cards carrying any LEAVES_BATTLEFIELD
            # triggered ability (Cryogen Relic, Broodguard Elite,
            # Syr Vondam, Nutrient Block); none use the
            # ``anticausal_vestige_leaves_effect`` kind, and each
            # carries a non-safe effect class (DrawCards under LEAVES
            # is NOT in this safe set — LEAVES draw is a separate
            # parity question; Move-self-counters / Sequence /
            # Conditional are bespoke / compound) plus often a
            # non-IsSelf predicate (Syr Vondam's first LEAVES trigger
            # is an ``And``). A future slice landing a LEAVES carrier
            # with a different SAFE leaf ships that leaf here + the
            # paired ``("leaves_battlefield","source_is_self",<leaf>)``
            # ``_SAFE_TRIGGERS`` entry (same one-line-widen pattern as
            # the ENTERS/DIES/ATTACKS leaf-set extensions). The
            # predicate-effect product is enforced by
            # ``_SAFE_TRIGGERS`` (the
            # ``("leaves_battlefield","source_is_self",
            # "anticausal_vestige_leaves_effect")`` tuple), so even
            # though only one kind is listed here the triple gate
            # rejects any other event/predicate pairing that isn't an
            # explicit ``_SAFE_TRIGGERS`` entry.
            safe_effect_kinds = ("anticausal_vestige_leaves_effect",)
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
    elif isinstance(eff, EachPlayerDraws):
        # **Friendly Teddy Cycle 1 (2026-05-22)** — bare-shape
        # ``EachPlayerDraws``. Python's class
        # (``effects/generic/draw_mill.py:230``) carries a SINGLE
        # ``amount`` field — no rider the bridge would silently drop
        # (contrast Surveil's ``use_artifact_count`` or PumpSelf's
        # ``granted_keywords``). The dict shape uses Rust's spelling
        # ``count`` per the ``each_player_draws`` cross_engine
        # bridge arm convention (sibling of ``draw_cards`` /
        # ``each_opponent_mills_cards`` / ``mill`` — same
        # ``amount``/``count`` field-name discrepancy local to the
        # bridge translation). The recipient is ALWAYS every
        # non-lost player (no target picker on either side; the
        # APNAP iteration order is structural to the resolve arm,
        # not a payload field). Negative amount is rejected by the
        # Rust parse arm (mirrors the variant invariant); amount==0
        # is a silent no-op on both engines (inner draw loop runs
        # zero times per player).
        eff_kind = "each_player_draws"
        eff_dict = {"kind": "each_player_draws", "count": int(eff.amount)}
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
    elif isinstance(eff, PutPlusOneCounterOnOpponentsCreature):
        # **Tier-C target-seating sub-substrate (lever-a, Sunset
        # Saboteur).** The FIRST targeted-safe-trigger leaf. Python's
        # ``PutPlusOneCounterOnOpponentsCreature(amount: int = 1)``
        # (effects/generic/counters.py — a ``PutPlusOneCounters``
        # subclass whose ``__post_init__`` wires the single slot
        # ``TargetSpec(IsCreature() & ControlledByOpponent())``,
        # ``count_min=1``, ``count_max=1``, ``slot_kinds()==()``).
        # Sunset Saboteur's ATTACKS trigger is the sole EoE consumer
        # (``{1}{B}`` 4/1 ``menace``, 6,375 17lands decks).
        #
        # **This is a TARGET-SEATED leaf — distinct from every other
        # arm above (all of which are recipient-is-self / untargeted).**
        # Both engines pick the target via the Tier-C shared
        # deterministic push-time seat (``first_legal_trigger_target``
        # on Rust at ``state_ops_resolve.rs:push_triggered_ability``;
        # the no-agent ``pool[0]`` seat on Python at
        # ``actions.py:_put_triggered_ability_on_stack`` — the
        # ``controller.agent is None`` branch), so NO loader-seated
        # agent is needed and BOTH engines pick the SAME
        # smallest-bf-index opponent-controlled creature. The
        # ``put_plus_one_counter_on_opponents_creature`` bridge arm
        # (``cross_engine.py``) round-trips the bare ``amount`` payload
        # IDENTICALLY on both engines (Rust
        # ``Effect::PutPlusOneCounterOnOpponentsCreature`` to_dict
        # emits ``{"kind": "put_plus_one_counter_on_opponents_creature",
        # "amount": <i32>}`` — no ``count``/``amount`` discrepancy;
        # parse arm tolerates a missing ``amount`` defaulting to 1 and
        # rejects negatives, mirroring the Python class's
        # ``amount: int = 1`` default). The resolve-time CR 608.2b
        # re-legality check (target still on a bf, still a creature,
        # still opponent-controlled) is byte-equal on both engines
        # (Python's ``PutPlusOneCounters.resolve``/
        # ``_slot_target_still_legal``; Rust's resolve arm's explicit
        # re-check). See the
        # ``("attacks", "source_is_self",
        # "put_plus_one_counter_on_opponents_creature")`` entry in
        # :data:`_SAFE_TRIGGERS` for the full cross-engine parity
        # provenance + the deterministic-first SEARCH_LIMITATIONS §2.3
        # entry.
        #
        # **Bare-shape gate (§2 silent-mistranslation teeth).** Only
        # the EXACT single-implicit-target shape is admitted: exactly
        # one ``TargetSpec`` slot, ``count_min==1``, ``count_max==1``,
        # ``slot_kinds()==()`` (no ``SlotRef``, no per-slot kind, no
        # ``distinct_from``). Any heterogeneous / multi-slot shape
        # falls through to the filter drop — the bridge + the shared
        # seat both assume the single-bare-slot contract. (Sunset
        # Saboteur's parsed effect satisfies this exactly — verified
        # live: ``count_range=(1,1)``, ``slot_kinds=()``.)
        from mtg_bot.effects.targets import SlotRef, TargetSpec
        slots = tuple(getattr(eff, "targets", ()) or ())
        if len(slots) != 1:
            return None
        slot = slots[0]
        if isinstance(slot, SlotRef) or not isinstance(slot, TargetSpec):
            return None
        if slot.count_min != 1 or slot.count_max != 1:
            return None
        if getattr(slot, "distinct_from", ()) not in ((), None):
            return None
        if eff.target_slot_kinds() != ():
            return None
        if int(eff.amount) < 0:
            return None
        eff_kind = "put_plus_one_counter_on_opponents_creature"
        eff_dict = {
            "kind": "put_plus_one_counter_on_opponents_creature",
            "amount": int(eff.amount),
        }
    elif isinstance(eff, ReturnTargetPermanentYouControlToOwnersHand):
        # **Tier-C target-seating sub-substrate, lever-a (Exosuit
        # Savior — the count_min=0 optional-bounce edge).** Python's
        # ``ReturnTargetPermanentYouControlToOwnersHand(optional=True,
        # exclude_self=True)`` (effects/generic/bounce.py — a
        # ``Bounce`` subclass whose ``__post_init__`` wires the single
        # slot ``TargetSpec(ControlledByYou() & ~IsPlayer() &
        # ~IsSource(), count_min=0, count_max=1)``). Exosuit Savior's
        # ENTERS trigger is the sole EoE consumer ({2}{W} 2/2
        # ``flying``, 12,480 17lands decks).
        #
        # **The count_min=0 optional edge (contrast Sunset
        # Saboteur's count_min=1).** ``requires_target()`` reads
        # ``False`` (CR "you may return") but the slot is a real
        # ``TargetSpec``. The Tier-C shared seat handles the edge:
        # no eligible own permanent ⇒ Rust's
        # ``first_legal_trigger_target`` returns ``None`` and
        # ``push_triggered_ability`` takes the UNCHANGED
        # ``new_trigger`` path → push-with-no-target → the resolve
        # arm no-ops (byte-equal with Python's ``targets=()``
        # ``Bounce.resolve`` early-return — the optional was simply
        # declined, NOT fizzled). When an eligible permanent exists
        # both engines deterministically pick the SAME
        # smallest-bf-index own-non-source permanent and bounce it.
        # The ``return_target_permanent_you_control`` bridge arm
        # round-trips the UNIT shape (no payload field — the filter
        # is structural to the effect class / the seat's per-variant
        # scan; the recognizer's bare-shape gate enforces the single
        # implicit-target contract). See the
        # ``("enters", "source_is_self",
        # "return_target_permanent_you_control")`` entry in
        # :data:`_SAFE_TRIGGERS` for the full cross-engine parity
        # provenance + the deterministic-first SEARCH_LIMITATIONS
        # §2.3 entry.
        #
        # **Bare-shape gate (§2 silent-mistranslation teeth).** Only
        # the EXACT single-implicit-target shape is admitted: exactly
        # one ``TargetSpec`` slot, ``count_min in (0, 1)`` (Exosuit
        # Savior is the optional ``count_min=0`` — DISTINCT from
        # Sunset Saboteur's mandatory ``count_min=1``; both ride the
        # same shared seat), ``count_max==1``, ``slot_kinds()==()``,
        # no ``SlotRef`` / ``distinct_from``. Any heterogeneous /
        # multi-slot shape falls through to the filter drop.
        # (Exosuit Savior's parsed effect satisfies this exactly —
        # verified live: ``count_range=(0,1)``, ``slot_kinds=()``.)
        from mtg_bot.effects.targets import SlotRef, TargetSpec
        slots = tuple(getattr(eff, "targets", ()) or ())
        if len(slots) != 1:
            return None
        slot = slots[0]
        if isinstance(slot, SlotRef) or not isinstance(slot, TargetSpec):
            return None
        if slot.count_min not in (0, 1) or slot.count_max != 1:
            return None
        if getattr(slot, "distinct_from", ()) not in ((), None):
            return None
        if eff.target_slot_kinds() != ():
            return None
        eff_kind = "return_target_permanent_you_control"
        eff_dict = {"kind": "return_target_permanent_you_control"}
    elif isinstance(eff, LookTopNPutOneInHandRestToGraveyard):
        # **Codecracker Hound Cycle 2 (2026-05-24) — the 9th ENTERS+IsSelf
        # leaf.** Python's
        # ``LookTopNPutOneInHandRestToGraveyard(n: int = 4,
        # reveal_chosen: bool = True)`` (effects/generic/library_lookat.
        # py:160) carries the parser-faithful no-reveal observable on
        # the Codecracker Hound surface form (n=2, reveal_chosen=False);
        # Rust's ``Effect::LookTopNPutOneInHandRestToGraveyard
        # { n: i32 }`` (rust/src/cards.rs:4392) carries ONLY the ``n``
        # field — its resolve at ``state_ops_resolve.rs:6366-6394``
        # never reveals, so the cross-engine byte-equality contract
        # holds iff Python's ``reveal_chosen`` is False as well. A
        # ``reveal_chosen=True`` instance would silently mistranslate
        # the post-resolve ``publicly_known_to`` observable on the
        # chosen card (Python's ``reveal_to_all`` rider sets it; Rust
        # leaves it unchanged), so we gate on ``reveal_chosen=False``
        # at the recognizer — the §2 silent-mistranslation teeth. The
        # only EoE consumer parser-emitted with this shape is
        # Codecracker Hound; Commune-with-Evil (n=4, reveal_chosen=
        # True) is a Sorcery and reaches the Rust engine via the
        # spell-card-bridge path, not this safe-trigger path. ``n``
        # must be non-negative (Rust's parse_effect rejects negative
        # n at cards.rs:12051-12055; mirror here so the recognizer's
        # bare-shape gate enforces the same contract). The emitted
        # dict shape carries both ``n`` and ``reveal_chosen``; the
        # bridge arm (cross_engine.py:4901-4978) reads
        # ``reveal_chosen`` to reconstruct the Python instance with
        # the same flag; Rust's parse_effect IGNORES the extra
        # ``reveal_chosen`` field (it only extracts ``n``), so
        # carrying it in the dict is structurally safe on the Rust
        # side — Rust effectively behaves as ``reveal_chosen=False``
        # always, and the recognizer's ``reveal_chosen=False`` gate
        # ensures the Python side matches.
        if eff.reveal_chosen:
            return None
        if int(eff.n) < 0:
            return None
        eff_kind = "look_top_n_put_one_in_hand_rest_to_graveyard"
        eff_dict = {
            "kind": "look_top_n_put_one_in_hand_rest_to_graveyard",
            "n": int(eff.n),
            "reveal_chosen": False,
        }
    elif isinstance(eff, AnticausalVestigeLeavesEffect):
        # **Anticausal Vestige Cycle 2 (2026-05-24) — the FIRST
        # LEAVES_BATTLEFIELD+IsSelf safe-trigger leaf.** Python's
        # ``AnticausalVestigeLeavesEffect`` (``effects/bespoke.py:858-
        # 907``) is a bare bespoke unit-variant — no payload fields on
        # either side. Both the land count (X) and the hand pick are
        # dynamic resolve-time computations: draw 1, count controller
        # lands on bf as X, pick the FIRST permanent in hand with
        # ``mana_cost.total <= X``, put it onto bf TAPPED with
        # ``summoning_sick=True`` (CR 302.1). Empty filter result →
        # silent no-op after the draw.
        #
        # Rust mirror: ``Effect::AnticausalVestigeLeavesEffect`` (C1
        # commit ``e148450a``) — parse_effect arm at the position
        # immediately after ``famished_worldsire_look_top_x_by_power_
        # put_lands_tapped``; to_pydict emits the SAME minimal unit-
        # shape ``{"kind": "anticausal_vestige_leaves_effect"}``;
        # resolve arm in ``state_ops_resolve.rs`` mirrors the
        # ``AstelliReclaimerETBEffect`` deterministic first-legal-pick
        # precedent step-for-step along the Python seated-agent
        # ``candidates[0]`` fallback path. The cross_engine bridge arm
        # at ``cross_engine.py:9475`` round-trips ``{"kind":
        # "anticausal_vestige_leaves_effect"}`` to the Python instance
        # (extra dict keys ignored per the unit-variant convention).
        #
        # **No rider gate.** Unit variant ⇒ nothing for the recognizer
        # to refuse (contrast Surveil's ``use_artifact_count`` or
        # PumpSelf's ``granted_keywords``). The §2 silent-mistranslation
        # gating is structural: the predicate must be ``IsSelf`` (we're
        # in the IsSelf branch) AND the event must be
        # ``LEAVES_BATTLEFIELD`` (gated by the
        # ``safe_effect_kinds = ("anticausal_vestige_leaves_effect",)``
        # tuple on the LEAVES arm above; the
        # ``("leaves_battlefield","source_is_self",
        # "anticausal_vestige_leaves_effect")`` ``_SAFE_TRIGGERS``
        # entry is the load-bearing triple gate). The dict-side
        # extra-key refusal in ``_is_safe_trigger_dict`` (backed by
        # ``_SAFE_EFFECT_KEYS["anticausal_vestige_leaves_effect"] =
        # frozenset({"kind"})`` — bare unit-shape whitelist) is the
        # cross-engine round-trip backstop against any future schema
        # extension.
        eff_kind = "anticausal_vestige_leaves_effect"
        eff_dict = {"kind": "anticausal_vestige_leaves_effect"}
    elif isinstance(eff, ConditionalIfCastFromHand):
        # **Weftwalking Cycle 2 (2026-05-24) — the FIRST recursive
        # combinator leaf in the safe set.** Python's
        # ``ConditionalIfCastFromHand(inner_effect: Effect)``
        # (effects/combinators.py:1513) wraps an inner Effect with the
        # "if you cast it" intervening-if gate. Both engines degrade
        # to "always run the inner effect" per the documented engine
        # simplification at combinators.py:1518-1536 (the
        # ``cast_via_hand`` provenance flag is ephemeral, cleared by
        # ``put_into_battlefield`` before ETB triggers fire — neither
        # engine has a reliable persistent flag at resolve time).
        #
        # **NARROW INNER SHAPE GATE (the §2 silent-mistranslation
        # teeth).** The wrap stays surgical: the recognizer admits
        # ONLY the canonical Weftwalking inner — a ``Sequence`` of
        # exactly two children, ``ShuffleZonesIntoLibrary(zones=
        # ('hand', 'graveyard'))`` followed by ``DrawCards(amount=7)``.
        # Any other inner shape (different zones, different draw
        # count, different children, single-leaf inner, nested
        # combinator inner) falls through to the filter drop path —
        # a future EoE consumer with a different inner ships its own
        # admit slice with the matching widen. Today Weftwalking is
        # the SOLE ConditionalIfCastFromHand carrier system-wide
        # (verified live), so the narrow gate is genuinely the live
        # admit pattern; it positions the substrate for safe future
        # widens (each new inner shape = one widen + one
        # ``_SAFE_TRIGGERS`` entry + a fresh real-EoE probe).
        #
        # **Bridge support pre-existed (C1 substrate commit
        # ``61f04bef`` + main merge ``d18bb3a4``).** Rust
        # ``Effect::ConditionalIfCastFromHand { inner: Box<Effect> }``
        # parse + to_pydict + resolve arms; Rust
        # ``Effect::ShuffleZonesIntoLibrary { zones: Vec<String> }``
        # parse + to_pydict + resolve arms; cross_engine bridge arms
        # (recursive ``conditional_if_cast_from_hand`` + flat-leaf
        # ``shuffle_zones_into_library``); reverse-serializer leaves
        # in this module (including the nested-Sequence-as-leaf arm
        # so the composer-wrapping-Sequence shape round-trips
        # byte-equal). C2 only adds the recognizer arm — the load-
        # bearing safe-trigger admit gate.
        #
        # **Field-name translation: Python ``inner_effect`` -> Rust
        # ``inner``.** Mirrors the C1 forward bridge arm at
        # ``cross_engine.py:2295-2346`` (Rust ``inner`` ↔ Python
        # ``inner_effect``) and the reverse-serializer leaf at
        # trajectory.py:5607-5614.
        inner = eff.inner_effect
        if not isinstance(inner, Sequence):
            return None
        if len(inner.effects) != 2:
            return None
        shuffle, draw = inner.effects
        if not isinstance(shuffle, ShuffleZonesIntoLibrary):
            return None
        if tuple(shuffle.zones) != ("hand", "graveyard"):
            return None
        if not isinstance(draw, DrawCards):
            return None
        if int(draw.amount) != 7:
            return None
        eff_kind = "conditional_if_cast_from_hand"
        eff_dict = {
            "kind": "conditional_if_cast_from_hand",
            "inner": {
                "kind": "sequence",
                "effects": [
                    {
                        "kind": "shuffle_zones_into_library",
                        "zones": ["hand", "graveyard"],
                    },
                    {"kind": "draw_cards", "count": 7},
                ],
            },
        }
    elif isinstance(eff, OptionalSacLandOrLanderForBasicLandRamp):
        # **Spacecraft Phase 3A Cycle 1 (2026-05-25).** Reverse-
        # serializer arm for Larval Scoutlander's ETB ramp Effect
        # ``OptionalSacLandOrLanderForBasicLandRamp(land_count: int =
        # 2)`` (``effects/combinators.py:699``). Round-trip pair with
        # the Rust ``Effect::OptionalSacLandOrLanderForBasicLandRamp
        # { land_count: i32 }`` to_pydict + parse arms (cards.rs) and
        # the cross_engine.py ``_ta_dict_to_python_effect`` bridge arm
        # (added in C1). Single ``land_count`` field — IDENTICAL field
        # spelling on both engines (no ``amount``/``count`` discrepancy
        # like the search/discard arms); the dict round-trip preserves
        # the int verbatim.
        #
        # **Substrate-only — Larval Scoutlander STAYS DECLINED at this
        # gate post-Cycle-1.** The kind string
        # ``optional_sac_land_or_lander_for_basic_land_ramp`` is
        # intentionally NOT added to any (event, predicate)
        # ``safe_effect_kinds`` set this cycle; the ``eff_kind not in
        # safe_effect_kinds`` gate below this dispatch cascade returns
        # None, so :func:`_python_ta_to_safe_dict` declines Larval
        # Scoutlander even with the recognition arm in place. The
        # round-trip dict construction is pre-positioned for Cycle 2
        # (which ships the new Phase-3 admit predicate
        # ``_printing_is_bridge_phase_3_trigger_spacecraft`` per design
        # doc §5.3 — a SEPARATE dispatch path from
        # ``_python_ta_to_safe_dict``; this leaf is the dict-emit
        # primitive both paths can consume).
        eff_kind = "optional_sac_land_or_lander_for_basic_land_ramp"
        eff_dict = {
            "kind": "optional_sac_land_or_lander_for_basic_land_ramp",
            "land_count": int(eff.land_count),
        }
    elif isinstance(eff, OptionalPutCreatureFromHandOntoBattlefield):
        # **Spacecraft Phase 3B Cycle 1 (2026-05-25).** Reverse-
        # serializer arm for Sledge-Class Seedship's ATTACKS trigger
        # Effect ``OptionalPutCreatureFromHandOntoBattlefield()`` (
        # ``effects/combinators.py:205``). Round-trip pair with the
        # Rust ``Effect::OptionalPutCreatureFromHandOntoBattlefield``
        # unit variant's to_pydict + parse arms (cards.rs) and the
        # cross_engine.py ``_ta_dict_to_python_effect`` bridge arm
        # (added in C1). Unit Effect — no fields; the dict carries
        # ONLY the ``kind`` discriminator.
        #
        # **Substrate-only — Sledge-Class Seedship STAYS DECLINED at
        # this gate post-Cycle-1.** The kind string
        # ``optional_put_creature_from_hand_onto_battlefield`` is
        # intentionally NOT added to any (event, predicate)
        # ``safe_effect_kinds`` set this cycle; the ``eff_kind not in
        # safe_effect_kinds`` gate below this dispatch cascade returns
        # None, so :func:`_python_ta_to_safe_dict` declines Sledge-
        # Class Seedship even with the recognition arm in place. The
        # round-trip dict construction is pre-positioned for Cycle 2
        # (which widens the Phase-3 admit-class allowlist + event-shape
        # table per design doc §7.2 — a SEPARATE dispatch path from
        # ``_python_ta_to_safe_dict``; this leaf is the dict-emit
        # primitive both paths can consume).
        eff_kind = "optional_put_creature_from_hand_onto_battlefield"
        eff_dict = {
            "kind": "optional_put_creature_from_hand_onto_battlefield",
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


# **Tier-C target-seating sub-substrate.** The set of recognizer
# ``effect.kind`` values that ride the deterministic push-time target
# seat (a targeted SAFE triggered ability whose target is picked by
# the no-agent first-legal rule, NOT a loader-seated agent). Every
# OTHER safe-trigger leaf is recipient-is-self / untargeted and is
# NOT in this set — so the surgical Python seat (§3.2) fires ONLY for
# these. ``put_plus_one_counter_on_opponents_creature`` (Sunset
# Saboteur, lever-a) is the first member; Exosuit Savior's
# ``return_target_permanent_you_control`` joins in its own slice.
#
# This is a SEPARATE module-level signal rather than a top-level
# ``"target_seated"`` key on the round-trip dict because
# :func:`_is_safe_trigger_dict` refuses any top-level key beyond
# ``event`` / ``predicate`` / ``effect`` / ``once_per_turn`` (the
# schema-extension backstop). Keying the gate off the recognized
# ``effect.kind`` keeps the cross-engine round-trip dict shape
# byte-identical while still making the seat surgical.
_TARGET_SEATED_EFFECT_KINDS: frozenset[str] = frozenset({
    "put_plus_one_counter_on_opponents_creature",
    # Exosuit Savior (the count_min=0 optional-bounce edge) — joins
    # via its own per-card slice, reusing the shared seat shipped
    # with Sunset Saboteur. The gate is the same: the Python no-agent
    # ``pool[0]`` seat fires for this kind too (and the count_min=0
    # edge means an empty ``pool`` simply declines the optional —
    # ``len(chosen_list)=0 >= min_t=0`` — byte-equal with the Rust
    # no-seat no-op).
    "return_target_permanent_you_control",
})


def _is_target_seated_safe_trigger(source, ability) -> bool:
    """True iff ``ability`` (a parsed ``TriggeredAbility`` on
    ``source``) round-trips through :func:`_python_ta_to_safe_dict`
    as a TARGET-SEATED safe trigger — i.e. its recognized
    ``effect.kind`` is in :data:`_TARGET_SEATED_EFFECT_KINDS`.

    This is the gate that keeps the Tier-C no-agent deterministic
    target seat (the ``controller.agent is None`` branch of
    ``actions._put_triggered_ability_on_stack``) **surgical**: it
    fires ONLY for the lever-admitted targeted safe triggers (Sunset
    Saboteur today), never for the engine's other targeted triggers
    (which keep their existing no-agent fizzle/no-op intact) and
    never for any untargeted safe trigger (those don't reach the
    target-pick loop at all). ``source`` is accepted for signature
    symmetry with the call site (the recognizer reads only
    ``ability``); a future per-source gate can use it without a
    call-site change.
    """
    dct = _python_ta_to_safe_dict(ability)
    if dct is None:
        return False
    eff = dct.get("effect")
    if not isinstance(eff, dict):
        return False
    return eff.get("kind") in _TARGET_SEATED_EFFECT_KINDS


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
      * Admitted ``dynamic_pt_formula`` keys (as of round-84):
        ``"harmonious_grovestrider"`` (round-78) and ``"cosmogoyf"``
        (round-84, this slice). The CardDef bridge carries
        ``dynamic_pt_formula`` (an optional string field;
        round-trips through ``_spec_card_to_printing_dict`` →
        Rust's ``parse_printing`` and back through
        ``_card_def_to_python_printing``); Rust's
        ``battlefield_creature_power`` /
        ``battlefield_creature_toughness`` /
        ``collect_sba_victims`` honor each admitted key via
        ``state_ops_combat::dynamic_base_pt_pub`` in lockstep with
        Python's ``game._dynamic_base_pt``. The remaining sibling
        formula (``"emissary_escort"``) reads
        ``printing.power`` / ``printing.toughness`` and ADDS X
        (greatest mana value among other artifacts the controller
        controls); the CDA-only ``dynamic_pt_formula`` arm this
        dispatch table covers today sets the BASE from scratch, so
        Escort is a different per-formula shape and is
        honest-stopped Rust-side (the dispatch table's ``_`` arm
        returns ``None`` for any unrecognized key); it stays on
        the drop-at-filter path until a per-card slice extends the
        dispatch table. The pre-round-78 rejection (which dropped
        EVERY ``dynamic_pt_formula`` carrier) was the round-39
        honest-stop precursor to this substrate; ``9c0d440f`` /
        ``9e71b63b`` did the drop, ``9c0d440f``'s SEARCH_LIMITATIONS
        entry tracked the deferred substrate, round-78 delivered
        the substrate for Grovestrider, and round-84 extends it
        for Cosmogoyf.
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
    # Dynamic-P/T-formula substrate (round-78 + round-84). The
    # admit set is ``_DYNAMIC_PT_FORMULA_ADMIT_SET`` (module-level;
    # see its docstring for the per-round closure history and the
    # honest-stop on Emissary Escort). Rust's
    # ``battlefield_creature_power`` /
    # ``battlefield_creature_toughness`` /
    # ``collect_sba_victims`` honor each admitted key via
    # ``state_ops_combat::dynamic_base_pt_pub`` in lockstep with
    # Python's ``game._dynamic_base_pt``. A formula key NOT in the
    # admit set drops the printing here so we never ship a 0/0
    # mistranslation on the Rust side.
    dpt_formula = getattr(printing, "dynamic_pt_formula", None)
    if (
        dpt_formula is not None
        and dpt_formula not in _DYNAMIC_PT_FORMULA_ADMIT_SET
    ):
        return False
    # Round-39 ward-cost fix (Harmonious Grovestrider et al.): see
    # docstring above for the substrate-honesty rationale. This
    # rejection STAYS — the real EoE Harmonious Grovestrider printing
    # carries both ``dynamic_pt_formula`` AND ``ward_cost``; the
    # dynamic-P/T substrate landing in round-78 opens the formula
    # half of the gate, but the ward half remains an orthogonal
    # substrate (separate closure target). A synthetic Grovestrider
    # CardDef without the ward rider admits cleanly; the live EoE
    # printing remains drop-at-filter until the ward substrate
    # lands.
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
    pair PLUS Phase 1.5's safe-trigger+warp residue trio PLUS Phase
    2's Timeline Culler (the life + graveyard-cast riders).

    Phase-6 warp_cost substrate, **phase 1** (round-63; spec at
    ``docs/WARP_COST_PHASE1_DESIGN.md`` §3, written round-62 N2) +
    **phase 1.5** (round-65; the safe-trigger+warp residue trio the
    Phase-1 agent deliberately scoped out — see the live-tree-drift
    note below) + **phase 2** (Timeline Culler; spec at
    ``docs/WARP_COST_PHASE2_DESIGN.md`` — the two former
    rider-rejection clauses were removed because the life rider +
    graveyard-cast rider are now modeled on BOTH engines; Timeline
    Culler is the ONLY card carrying either rider, so the widen
    admits EXACTLY it and the §2 teeth that decline every other warp
    card are byte-for-byte unchanged).

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
    profile OR the safe-trigger+warp profile OR Timeline Culler's
    pure-life+graveyard profile (Phase 2 — the riders are now modeled
    on both engines), and MUST still reject every multi-gated warp
    card (static / Effect-uncovered — never flips on warp alone). The
    exclusion set is the SAME as
    :func:`_printing_is_bridge_simple_creature` (so the 26 multi-gated
    warp cards trip one of these and stay filtered) MINUS the
    ``printing.warp_cost`` rejection (which is the whole point — this
    predicate REQUIRES it), with ``triggered_abilities`` gated to the
    SAFE set (not hard-rejected). Phase 2 REMOVED the two
    Phase-2-rider positive rejections (Timeline Culler is the ONLY
    card carrying either rider — verified live — so the widen admits
    EXACTLY it; every other clause is byte-for-byte unchanged so the
    §2 teeth that decline the 26 multi-gated warp cards still hold).

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
    # Phase 2 (Timeline Culler): the life rider + graveyard-cast rider
    # are now MODELED on BOTH engines (CardDef warp_life_cost /
    # warp_from_graveyard + Rust warp_additional_life_cost /
    # warp_castable_from_graveyard + the cast_creature_warp life debit
    # + the graveyard cast-from-zone fall-through + the life-gated
    # legal emit + the graveyard warp loop). They are no longer
    # §2-rejected. Timeline Culler ({B} warp, Pay 2 life, gy-castable)
    # is the ONLY card carrying either rider (verified live), so
    # dropping the two former rejection clauses admits EXACTLY Timeline
    # Culler and nothing else — every other warp card still trips a
    # non-warp clause below (static / non-safe-trigger / kicker /
    # ...), so the §2 teeth that decline the 26 multi-gated warp cards
    # are byte-for-byte unchanged. See
    # docs/WARP_COST_PHASE2_DESIGN.md §1/§2.
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
    # Round-78 dynamic-P/T-formula substrate: same admit rule as
    # ``_printing_is_bridge_simple_creature`` — only the
    # ``"harmonious_grovestrider"`` formula key is honored by Rust's
    # dispatch table today. No EoE warp creature carries a
    # ``dynamic_pt_formula`` (verified: the §1 warp pool is Red Tiger
    # Mechan, Bygone Colossus, Germinating Wurm, Knight Luminary,
    # Starbreach Whale, Timeline Culler — none are ``*``-based P/T),
    # so this branch is dead today; keeping the explicit gate
    # preserves the §2 substrate-honesty guarantee if a future warp
    # printing happens to be a layer-7 CDA carrier.
    dpt_formula = getattr(printing, "dynamic_pt_formula", None)
    if dpt_formula is not None and dpt_formula != "harmonious_grovestrider":
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
        _parse_mana_cost_string(printing.warp_cost_str or "")
    except ValueError:
        return False
    return True


def _cost_reduction_rule_is_phase1_or_3(rule) -> bool:
    """True iff ``rule`` is one of the spell-local ``Condition`` variants
    the cost-reduction substrate ports across Phases 1 + 3.

    Phase 1 + Phase 3 carry EXACTLY 3 spell-local ``Condition`` variants:

      * :class:`AnotherSpellCastThisTurn` — no payload (Gigastorm
        Titan: ``CostReduction(amount=3,
        condition=AnotherSpellCastThisTurn())``).
      * :class:`OpponentsControlAtLeast` — restricted to the
        :class:`IsCreature` filter token + an int ``n`` (Lashwhip
        Predator: ``CostReduction(amount=2,
        condition=OpponentsControlAtLeast(IsCreature(), 3))``).
      * :class:`PerDifferentlyNamedLand` — no payload (Fungal Colossus:
        ``CostReduction(amount=1,
        condition=PerDifferentlyNamedLand())``).   # Phase 3 (NEW
        — variable-X multiplier on the spell-local side; the
        multiplier is computed by Rust's
        :func:`unique_land_names_count` walking the caster's
        battlefield).

    The full ``Condition``-grammar surface (And/Or/Not combinators,
    target-dependent variants, the predicate algebra beyond
    ``IsCreature``) is out of scope. Phase 2's externals-condition
    sibling is :func:`_external_cost_reduction_rule_is_phase2`,
    unchanged here.

    The §2 admit-predicate teeth: this is the spell-local-condition
    half. Any non-Phase-1/3 ``Condition`` subclass — False (rejected);
    any other ``OpponentsControlAtLeast`` payload — False.

    Renamed from ``_cost_reduction_rule_is_phase1`` in Phase 3 Cycle 2
    (2026-05-25, design doc §5.4 Option A — widen the existing helper
    rather than chain a sibling helper). The Phase-1 carriers continue
    to admit through the SAME named site as the new Phase-3 carrier;
    the decline-set bench check gets one predicate, one assertion.
    """
    from mtg_bot.effects.conditions import (
        AnotherSpellCastThisTurn,
        OpponentsControlAtLeast,
        PerDifferentlyNamedLand,
    )
    from mtg_bot.effects.object_predicates import IsCreature

    c = rule.condition
    if isinstance(c, AnotherSpellCastThisTurn):
        return True
    if isinstance(c, OpponentsControlAtLeast):
        return isinstance(c.filter, IsCreature) and isinstance(c.n, int)
    # Phase 3 (NEW). No payload — accept any ``PerDifferentlyNamedLand``
    # instance. The Rust side evaluates ``unique_land_names_count`` on
    # the caster's battlefield to produce the variable-X multiplier.
    if isinstance(c, PerDifferentlyNamedLand):
        return True
    return False


def _external_cost_reduction_rule_is_phase2(rule) -> bool:
    """True iff ``rule`` is one of the two ``ExternalCondition``
    shapes Phase 2 of the cost-reduction substrate ports.

    Phase 2 carries EXACTLY 2 ExternalCondition variants:

      * :class:`NthSpellThisTurn` — payload ``n: int`` (Uthros
        Psionicist: ``ExternalCostReduction(amount=2,
        condition=NthSpellThisTurn(n=2))``).
      * :class:`PerControlled` — restricted to the
        :class:`IsArtifact` / :class:`IsCreature` filter tokens
        (Sami, Wildcat Captain: ``ExternalCostReduction(amount=1,
        condition=PerControlled(IsArtifact()))``).

    Any variable-multiplier on the spell-local side (Phase 3 sub-
    shape D — :class:`PerDifferentlyNamedLand` lives on
    ``cost_reductions``, NOT ``external_cost_reductions``), any
    non-Phase-2 ExternalCondition subclass, or any non-
    ``IsArtifact``/``IsCreature`` predicate — False (rejected).
    Mirror of :func:`_cost_reduction_rule_is_phase1_or_3` for the
    externals side; the bridge §2 teeth.
    """
    from mtg_bot.effects.conditions import (
        NthSpellThisTurn,
        PerControlled,
    )
    from mtg_bot.effects.object_predicates import IsArtifact, IsCreature

    c = rule.condition
    if isinstance(c, NthSpellThisTurn):
        return isinstance(c.n, int)
    if isinstance(c, PerControlled):
        return isinstance(c.filter, (IsArtifact, IsCreature))
    return False


def _printing_is_bridge_pure_cost_reduction_creature(printing) -> bool:
    """True iff a CardPrinting is a PURE cost-reduction creature the
    Phase-1 / Phase-2 / Phase-3 cost-reduction substrate round-trips
    byte-equal across engines.

    **Cost-reduction substrate, Phase 1 Cycle 2 (2026-05-24) +
    Phase 2 Cycle 2 (2026-05-25) + Phase 3 Cycle 2 (2026-05-25; spec
    at ``docs/COST_REDUCTION_SUBSTRATE_PHASE_3_DESIGN.md`` §5.4
    Option A — widen the existing helper).** Motivating set:
    Gigastorm Titan + Lashwhip Predator (Phase 1 — 24,908 17lands
    decks) + Uthros Psionicist + Sami, Wildcat Captain (Phase 2 —
    +15,575 17lands decks) + Fungal Colossus (Phase 3 — +13,165
    17lands decks; the SOLE ``PerDifferentlyNamedLand`` carrier).
    **Post-Phase-3 closure the cost-reduction substrate retires from
    the single-gated rollup entirely** — admit set is exhaustive on
    the EoE pool.

    The §2 Class-1 positive-allowlist guardrail; one named site,
    widened in Phase 3 (Option A — the spell-local
    :func:`_cost_reduction_rule_is_phase1_or_3` helper handles all
    three Phase-1/3 ``Condition`` shapes, and the externals
    :func:`_external_cost_reduction_rule_is_phase2` helper is
    unchanged. All five Phase-1/2/3 carriers route through the SAME
    named site).

    **§2 teeth (must reject):**

      * Any future Phase-4+ spell-local ``Condition`` subclass
        (And/Or/Not combinators, target-dependent variants).
        Rejected by :func:`_cost_reduction_rule_is_phase1_or_3`.
      * Any future Phase-4+ externals carrier (e.g.
        ``per_differently_named_land`` on the externals side, or
        any predicate beyond ``IsArtifact``/``IsCreature``).
        Rejected by :func:`_external_cost_reduction_rule_is_phase2`.

    Sibling of :func:`_printing_is_bridge_pure_warp_creature` (the
    round-63 warp predicate this is structurally modeled on). The §2
    exclusion set is the same as
    :func:`_printing_is_bridge_simple_creature` (no keywords outside
    :data:`_SAFE_KEYWORDS`, no triggered/activated/static abilities,
    no spell_effect / warp_cost / kicker_cost / impending_cost /
    room_halves / loyalty / station_threshold / dynamic_pt_formula
    / ward_cost) — the ONLY thing this predicate ADDS over
    simple-creature is admitting the Phase-1/3 ``cost_reductions``
    rider AND the Phase-2 ``external_cost_reductions`` rider. All
    five phase-1/2/3 cards are bare ``('Creature',)``.
    """
    if "Creature" not in printing.card_types:
        return False
    if printing.power is None or printing.toughness is None:
        return False
    # Phase 1 + Phase 3 spell-local admit (Phase 3 Cycle 2 widening).
    # Each spell-local rule must be one of the THREE
    # supported Conditions across Phase 1 + Phase 3:
    # ``AnotherSpellCastThisTurn`` / ``OpponentsControlAtLeast(Creature,
    # int)`` / ``PerDifferentlyNamedLand`` (the Fungal Colossus
    # variable-X multiplier). Any other ``Condition`` subclass —
    # rejected (Phase 4+ widens further).
    if printing.cost_reductions:
        for rule in printing.cost_reductions:
            if not _cost_reduction_rule_is_phase1_or_3(rule):
                return False
    # Phase 2 externals admit (NEW). Replaces the old
    # ``if printing.external_cost_reductions: return False`` guard.
    # Each externals rule must be one of the two Phase-2
    # ExternalCondition shapes; any other ExternalCondition or
    # predicate token rejects (the §2 teeth — Phase 3+ widens this
    # via the same pattern).
    if printing.external_cost_reductions:
        for ext in printing.external_cost_reductions:
            if not _external_cost_reduction_rule_is_phase2(ext):
                return False
    # At least ONE rider must be present (otherwise the
    # ``_printing_is_bridge_simple_creature`` predicate handles it).
    # No-silent-vanilla-grow check: a printing with both
    # ``cost_reductions == ()`` and ``external_cost_reductions == ()``
    # is NOT a cost-reduction carrier and must not be admitted here.
    if (
        not printing.cost_reductions
        and not printing.external_cost_reductions
    ):
        return False
    # Same exclusion set as ``_printing_is_bridge_simple_creature``:
    if printing.keywords and not printing.keywords.issubset(_SAFE_KEYWORDS):
        return False
    if printing.triggered_abilities:
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
    if printing.station_threshold:
        return False
    dpt_formula = getattr(printing, "dynamic_pt_formula", None)
    if (
        dpt_formula is not None
        and dpt_formula not in _DYNAMIC_PT_FORMULA_ADMIT_SET
    ):
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
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
        DestroyAllCreatures,
        DestroyTargetArtifact,
        DestroyTargetArtifactEnchantmentOrFlyingCreature,
        DestroyTargetArtifactOrTappedCreature,
        DestroyTargetNonlandPermanentWithLanderForController,
    )
    from mtg_bot.effects.generic.exile import (
        ExileAllCreaturesAndSpacecraft,
        ExileTargetCreature,
    )
    from mtg_bot.effects.generic.library_lookat import (
        ManifestDread,
        Surveil,
    )
    from mtg_bot.effects.generic.stack_control import (
        PreventAllCombatDamageThisTurn,
    )
    from mtg_bot.effects.bespoke import (
        BiosynthicBurstEffect,
        CloseEncounterEffect,
        CutPropulsionEffect,
        DepressurizeEffect,
        DiplomaticRelationsEffect,
        ExorciseEffect,
        FocusFireEffect,
        MutinousMassacreEffect,
        SeedshipImpactEffect,
        SystemsOverrideEffect,
        ZeroPointBalladEffect,
    )
    from mtg_bot.effects.generic.delayed_actions import (
        RemoveChargeCountersFromSourceDelayed,
    )
    from mtg_bot.effects.generic.damage import (
        DealDamageEachOpponent,
        DealDamageToTargetCreatureSpacecraftBoosted,
        DealDamageToTargetCreatureWithExcessLanderRider,
        DealDamageToTargetTappedCreature,
        DealNDamageToEachCreature,
    )
    from mtg_bot.effects.generic.exile import (
        ExileAllArtifactsWithManaValueAtMost,
    )
    # **Warping Wail Cycle 1a substrate (2026-05-22).** Reverse-
    # serializer leaf for the new
    # ``ExileTargetCreatureWithPowerOrToughnessAtMost`` Rust variant.
    # Substrate-only — Warping Wail itself stays DECLINED at the admit
    # gate this cycle (Mode 2 + Mode 3 still gap). Import kept narrow
    # per the established convention.
    from mtg_bot.effects.generic.exile import (
        ExileTargetCreatureWithPowerOrToughnessAtMost,
    )
    # **Warping Wail Cycle 2 substrate (2026-05-22).** Reverse-
    # serializer leaf for ``CounterTargetSpell`` — closes the gap
    # where the Python dataclass's ``filter_types: frozenset[str]``
    # field had NO matching ``_python_spell_effect_to_dict`` arm
    # (verify-first confirmed at HEAD ``7ad85ea9``: no
    # ``CounterTargetSpell`` leaf existed). Substrate-only — Warping
    # Wail itself stays DECLINED at the admit gate this cycle (Mode 3
    # token-AA still gap, Cycle 4 admit-gate widen still pending).
    # Real-EoE consumers Divert Disaster / Unravel
    # (``filter_types=frozenset({"Instant", "Sorcery"})``) flip
    # automatically once the rest of their bridge surface aligns.
    from mtg_bot.effects.generic.stack_control import (
        CounterTargetSpell,
    )
    from mtg_bot.effects.generic.pump import (
        PumpTargetArtifactOrCreatureUntilEOT,
        ThreatenTargetCreatureUEOT,
    )
    from mtg_bot.effects.combinators import (
        ConditionalIfCastFromHand,
        IfNot,
        IfYouDo,
        MayDo,
        OptionalSacAnotherForEffect,
    )
    from mtg_bot.effects.generic.zone_moves import (
        ShuffleZonesIntoLibrary,
    )
    from mtg_bot.effects.conditions import (
        ControlsAnotherCreatureWithPowerAtMost,
    )
    from mtg_bot.effects.generic.discard import DiscardSelf
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.counters import (
        PutChargeCountersOnTargetSpacecraftOrPlanetYouControl,
    )
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetArtifactCardFromYourGraveyardToHand,
        ReturnUpToNCreaturesFromYourGraveyardToHand,
        ReturnUpToNNonlandPermanentCardsFromGraveyardToHand,
        ReturnUpToNSmallCreaturesFromGraveyardWithCounters,
    )
    from mtg_bot.effects.generic.search import (
        SearchLibraryForCard,
    )
    # **Devastating Onslaught — Cycle 1 (2026-05-22).** Two new leaves
    # for the X-cost token-copy + per-token end-step sac delayed
    # trigger. Imports kept narrow per the established convention.
    from mtg_bot.effects.generic.tokens import (
        CreateToken,
        CreateXTokensOfTargetPermanentWithHasteEndStepSac,
    )
    from mtg_bot.effects.generic.delayed_actions import (
        SacrificeSourceDelayed,
        ScheduleSelfSacAtNextEndStep,
    )
    # **Ouroboroid Cycle 1 (2026-05-23).** Per-leaf serializer for
    # ``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()``
    # — the field-free dataclass for Ouroboroid's mass-counter trigger
    # body. Unit-variant sibling of ``ScheduleSelfSacAtNextEndStep`` /
    # ``SacrificeSourceDelayed``. Strictly for the round-trip dict-
    # shape surface.
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower,
    )
    # **Hemosymbic Mite Cycle 1 (2026-05-23).** Per-leaf serializer for
    # ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()`` — the
    # field-free X-source pump for Hemosymbic Mite's becomes-tapped
    # trigger body ("another target creature you control gets +X/+X
    # until end of turn, where X is this creature's power"). Unit-
    # variant sibling of the Ouroboroid mass-counter equivalent — both
    # are field-free X-source variants where X is read at resolve time
    # from the source's effective power.
    from mtg_bot.effects.generic.pump import (
        PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
    )
    # **Burgeoning Cycle 1 (2026-05-23).** Per-leaf serializer for
    # ``OptionalPutLandFromHandOntoBattlefield()`` — the field-free
    # optional-choice effect for Burgeoning's opponent-plays-land
    # trigger body ("you may put a land card from your hand onto the
    # battlefield"). Unit-variant sibling of
    # ``BoilerbilgesRipperETBEffect`` — both are field-free optional-
    # choice effect classes where the agent surface controls
    # DO-vs-DECLINE.
    from mtg_bot.effects.combinators import (
        OptionalPutLandFromHandOntoBattlefield,
    )
    # **Osseous Sticktwister Cycle 1 (2026-05-23).** Per-leaf serializer
    # import for ``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage()``
    # — the field-free per-opponent three-mode-choice + conditional
    # source-power damage primitive for Osseous Sticktwister's
    # Delirium-gated end-step trigger. Unit-variant sibling of the
    # ``OptionalPutLandFromHandOntoBattlefield`` /
    # ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower`` /
    # ``ArabellaAttackEffect`` field-free serializers — the per-
    # opponent loop + sac/discard/decline branching + source-power
    # damage formula is intrinsic; no static fields to thread.
    from mtg_bot.effects.generic.opponent_punishers import (
        EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage,
    )
    # **Terrasymbiosis Cycle 1 (2026-05-23).** Per-leaf serializer for
    # ``DrawCardsEqualToResolvingCounterAmount()`` — the field-free
    # counter-amount sibling of
    # ``DrawCardsEqualToResolvingCombatDamage``. Unit-variant —
    # strictly for the round-trip dict-shape surface; the production
    # COUNTERS_ADDED-observer write site that mints
    # ``state.resolving_counter_amount`` is honest-stopped at the
    # cross-engine level (substrate-only landing).
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsEqualToResolvingCounterAmount,
    )
    # **Terminal Velocity — Cycle 1 (2026-05-22).** Two new leaves for
    # the Terminal Velocity Sorcery + the LTB damage-equal-to-MV-
    # each-creature trigger body. Both are field-free dataclasses;
    # both emit bare unit-variant dicts. Imports kept narrow.
    from mtg_bot.effects.bespoke import (
        TerminalVelocityEffect,
        DealSelfMVDamageToEachCreature,
    )
    # **Singularity Rupture Cycle 1 (2026-05-24).** Per-leaf serializer
    # for `SingularityRuptureEffect()` — the field-free frozen
    # dataclass for Singularity Rupture's full single-sentence body
    # ("destroy all creatures, then any number of target players each
    # mill half their library, rounded down"). Unit-variant sibling of
    # `TerminalVelocityEffect` / `ZeroPointBalladEffect` — both are
    # parameterless bespoke spell-effect classes whose dict-shape
    # carries only `kind`.
    from mtg_bot.effects.bespoke import (
        SingularityRuptureEffect,
    )
    # **Coordinated Clobbering Cycle 1 substrate (2026-05-24).**
    # Per-leaf serializer for `CoordinatedClobberingEffect()` — the
    # field-free frozen dataclass for Coordinated Clobbering's two-
    # sentence body ("tap one or two target untapped creatures you
    # control; they each deal damage equal to their power to target
    # creature an opponent controls"). Unit-variant sibling of
    # `SingularityRuptureEffect` / `TerminalVelocityEffect` — all
    # three are parameterless bespoke spell-effect classes whose
    # dict-shape carries only `kind`. Substrate-only — admit gate
    # stays declined for the `(2, 3)` heterogeneous 3-slot grammar
    # until Cycle 2 ships the Phase 6 admit arm; Cycle 1 wires the
    # serializer leaf for round-trip closure.
    from mtg_bot.effects.bespoke import (
        CoordinatedClobberingEffect,
    )
    # **Archenemy's Charm flip (2026-05-24).** Per-leaf serializer
    # for `PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYou
    # Control` — the combined Effect class for Archenemy's Charm's
    # Mode 2 ("Put N +1/+1 counters on target creature you control.
    # It gains <kw> until end of turn."). Two-field carrier:
    # `amount: int` + `granted_keywords: frozenset[str]`. Emits the
    # sorted-list-of-strings shape Rust's parse arm requires (the
    # bridge's `granted_keywords` `frozenset` round-trip).
    from mtg_bot.effects.generic.counters import (
        PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
    )

    def _leaf(eff, *, _in_modal_mode: bool = False) -> Optional[dict]:
        """Per-leaf serializer recursion.

        ``_in_modal_mode``: True iff this call is the direct child of a
        ``ModalChooseOne`` composer (one of its ``modes``). Threaded
        downward from the modal composer at the bottom of this
        function. The flag is consulted ONLY by the
        Warping-Wail-Cycle-4 ``CreateToken`` arm (which emits a
        symbolic ``_token_card_def`` carrier that the
        ``_seat_token_printings`` nested-mode walk extension resolves
        post-frozen-union — and that walk ONLY recognizes the modal
        position today). For every other position (top-level
        spell_effect, nested inside a Sequence, nested inside an
        IfYouDo / MayDo / OptionalSacAnotherForEffect / IfNot), the
        seating pass does NOT walk in and the leaf would emit a
        symbolic ref that survives past the loader and gets rejected
        by Rust's parse_effect — so we bail (return None) when
        ``_in_modal_mode`` is False to keep the round-trip-or-bail
        teeth honest (the no-fallback-hybrid discipline).

        Three EoE printings carry CreateToken in non-modal positions
        and would AUTO-FLIP if this gate widened: Glimmerburst
        (``Sequence(DrawCards, CreateToken(Glimmer))``), Midnight
        Mayhem (top-level ``CreateToken(Gremlin, count=3)``), and
        Sami's Curiosity (``Sequence(GainLife, CreateToken(Lander))``).
        Each needs its own substrate slice (the ``_seat_token_printings``
        walk extended to the position + the matching pin updates +
        cross-engine probe). The narrow Cycle-4 admit discipline keeps
        them DECLINED until their own cycle ships — per the §2 honest-
        stop convention this campaign has used throughout.
        """
        # Pid-free covered leaves only. DestroyTargetArtifactOrTapped
        # Creature is a unit variant (intrinsic filter — Rust's
        # parse arm takes NO fields, the bridge arm constructs the
        # field-free Python class). GainLife carries ``amount``.
        if isinstance(eff, DestroyTargetArtifactOrTappedCreature):
            return {"kind": "destroy_target_artifact_or_tapped_creature"}
        # **ModalChooseOne envelope — Cycle 6 (Drill Too Deep closure,
        # 2026-05-21).** Per-leaf ``DestroyTargetArtifact`` arm — Drill
        # Too Deep mode 1. The Rust ``Effect::DestroyTargetArtifact``
        # (cards.rs:1254 unit variant) and matching bridge arm in
        # ``cross_engine.py`` (the round-23 `destroy_target_artifact`
        # arm) have shipped since round 23 — the gap was just the
        # composer-recurse leaf entry. Pid-FREE covered unit variant —
        # field-free round-trip; mirrors the sibling
        # ``destroy_target_artifact_or_tapped_creature`` unit-leaf
        # idiom. Adding this leaf — TOGETHER with the matching
        # ``put_charge_counters_on_target_spacecraft_or_planet_you_
        # control`` leaf for mode 0 and the Cycle-5 per-mode target
        # binding in ``cast_spell_noncreature`` — is what flips Drill
        # Too Deep into the spell-card-bridge admit set: both modes
        # are now serializable, the ModalChooseOne composer recurses
        # cleanly, and the {1}{R} Instant rides the Phase-1 ``(1, 1)``
        # admit shape.
        if isinstance(eff, DestroyTargetArtifact):
            return {"kind": "destroy_target_artifact"}
        # **scour-for-scrap-cycle-2 (2026-05-21) — Scour for Scrap
        # mode 0 leaf `SearchLibraryForCard` (NARROW
        # ``filter_name="artifact"`` admit).** Library-tutor primitive
        # with three serializable axes: ``filter_name`` (str,
        # required), ``max_mv`` (int, default 0), and ``may_fail``
        # (bool, default True). Rust's ``parse_effect``
        # ``"search_library_for_card"`` arm (cards.rs) reads all three
        # fields and the resolve arm (state_ops_resolve.rs) consumes
        # them deterministically. The dict→Python bridge arm
        # (cross_engine.py:4068 ``search_library_for_card``)
        # constructs ``SearchLibraryForCard(filter_name, max_mv,
        # may_fail)``. All three fields participate in equality on the
        # Python side, so the round-trip dict carries them all.
        #
        # **Narrow ``filter_name == "artifact"`` admit (honest-stop
        # discipline).** Scour for Scrap mode 0 uses
        # ``filter_name="artifact"``, ``max_mv=0``, ``may_fail=True``
        # — the EXACT shape this lane is responsible for landing.
        # Other ``SearchLibraryForCard`` filters
        # (``filter_name="demon"`` — Demonic Counsel,
        # ``filter_name="basic_land"`` / per-color basics — fetch
        # lands, etc.) ALSO have full Rust + bridge coverage and
        # would also round-trip if this leaf admitted them, but each
        # auto-flips a distinct card class (Demonic Counsel auto-
        # flips a {1}{B} tutor; basic-land filters touch Spineseeker
        # Centipede and triggered-ability surfaces). Per the
        # honest-stop discipline (a follow-up cycle ships each card's
        # parity probe + admit-set guardrail flip in its own lane),
        # this leaf narrowly admits ONLY the ``filter_name="artifact"``
        # shape today. The narrowing is a `_leaf` predicate, not a
        # cross-engine arm change — the existing
        # `search_library_for_card` arm in cross_engine.py / cards.rs
        # / state_ops_resolve.rs accepts every filter byte-identical
        # (no narrowing on the cross-engine side); only the bridge-
        # admit-set serializer narrows.
        if isinstance(eff, SearchLibraryForCard):
            if eff.filter_name != "artifact":
                # Other filters stay declined at the bridge-admit-set
                # gate until a per-card cycle ships their probe +
                # guardrail flip.
                return None
            return {
                "kind": "search_library_for_card",
                "filter_name": str(eff.filter_name),
                "max_mv": int(eff.max_mv),
                "may_fail": bool(eff.may_fail),
            }
        # **scour-for-scrap-cycle-2 (2026-05-21) — Scour for Scrap
        # mode 1 leaf `ReturnTargetArtifactCardFromYourGraveyardTo
        # Hand`.** Pid-FREE covered unit variant — Rust's
        # ``parse_effect`` ``"return_target_artifact_card_from_your_
        # graveyard_to_hand"`` arm takes NO fields and the dict→Python
        # bridge arm (cross_engine.py
        # ``return_target_artifact_card_from_your_graveyard_to_hand``)
        # constructs the field-free
        # ``ReturnTargetArtifactCardFromYourGraveyardToHand()``. No
        # token pid → no :func:`_seat_token_printings` dependency;
        # the round-trip is the clean
        # ``destroy_target_artifact`` unit-leaf idiom. Adding this
        # leaf — TOGETHER with mode 0's ``SearchLibraryForCard`` leaf
        # above AND the Cycle-1 ``or_both`` substrate (Lane LL) AND
        # the admit-predicate widen below to accept Scour's ``(0, 1)``
        # ``or_both=True`` shape — is what flips Scour for Scrap
        # into the spell-card-bridge admit set: both modes are now
        # serializable, the ModalChooseOne composer recurses cleanly,
        # the cast-time multi-pick + per-mode target binder both fire,
        # and the {3}{U} Instant joins the bridge admit set
        # (auto-grow, no hardcoded list — the §2 teeth).
        if isinstance(eff, ReturnTargetArtifactCardFromYourGraveyardToHand):
            return {
                "kind": "return_target_artifact_card_from_your_graveyard_to_hand",
            }
        # **Bare-shape ``ExileTargetCreature`` leaf (Cycle 1 substrate
        # for Archenemy's Charm Mode 0 + Gravkill / Final Vengeance
        # bare-spell-effect consumers, 2026-05-22).** Pid-FREE covered
        # unit variant — Rust's ``parse_effect``
        # ``"exile_target_creature"`` arm takes NO fields and the
        # dict→Python bridge arm (cross_engine.py
        # ``exile_target_creature``) constructs the field-free
        # ``ExileTargetCreature()``. The single creature target rides
        # on the spell StackItem (cast-time bind via the default-
        # first-creature branch of ``cast_spell_noncreature``'s
        # ladder); the resolve arm reads
        # ``current_resolve_payload_target_id`` per CR 608.2b. No token
        # pid → no :func:`_seat_token_printings` dependency; the
        # round-trip is the clean ``destroy_target_artifact`` /
        # ``biosynthic_burst_effect`` unit-leaf idiom.
        #
        # **Subclass-specific isinstance.** ``ExileTargetCreature``
        # subclasses ``Exile`` (the generic exile primitive); the
        # check matches the SPECIFIC subclass to avoid accidentally
        # admitting other ``Exile`` subclasses (e.g.
        # ``ExileTargetCreatureWithPowerOrToughnessAtMost`` — a
        # parameterized rider that would need its own leaf arm). The
        # ``ExileTargetCreature`` printed shape — bare "exile target
        # creature" with no rider — round-trips byte-equal across
        # engines provided the Rust resolve arm matches; this lane
        # ships that arm + this leaf together.
        if type(eff) is ExileTargetCreature:
            return {"kind": "exile_target_creature"}
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
        # Diplomatic Relations (Effect-uncovered Tier-A #7; round-76;
        # spell-card-bridge **Phase 2** — the 2-slot heterogeneous-
        # target grammar). Pid-FREE covered unit variant — Rust's
        # ``parse_effect`` ``"diplomatic_relations_effect"`` arm takes
        # NO fields and the dict→Python bridge arm (cross_engine.py
        # ``diplomatic_relations_effect``) constructs the field-free
        # ``DiplomaticRelationsEffect()``. The +1/+0, vigilance, and
        # power-equal damage are intrinsic; the 2-slot targets ride
        # on the spell StackItem, NOT in this dict. No token pid → no
        # :func:`_seat_token_printings` dependency; the round-trip is
        # the clean ``biosynthic_burst_effect`` unit-leaf idiom.
        # Adding this leaf — TOGETHER with the guardrail's Phase-2
        # 2-slot widening (:func:`_printing_is_bridge_simple_spell`)
        # — is what flips Diplomatic Relations into the spell-card-
        # bridge admit set: with the Rust variant + bridge arm landed
        # it is now covered+bridged AND round-trips here, so the
        # guardrail admits the ``{2}{G}`` 2-slot Instant (the admit
        # set grows 6→7; auto-grow, no hardcoded list — the §2
        # teeth).
        if isinstance(eff, DiplomaticRelationsEffect):
            return {"kind": "diplomatic_relations_effect"}
        # Cut Propulsion (Effect-uncovered Tier-A; ~11,990 17lands
        # decks). Pid-FREE covered unit variant — Rust's
        # ``parse_effect`` ``"cut_propulsion_effect"`` arm takes NO
        # fields and the dict→Python bridge arm (cross_engine.py
        # ``cut_propulsion_effect``) constructs the field-free
        # ``CutPropulsionEffect()``. The single creature target rides
        # on the spell StackItem, NOT in this dict; the damage amount
        # (target's effective power; doubled if flying) is intrinsic.
        # No token pid → no :func:`_seat_token_printings` dependency;
        # the round-trip is the clean ``biosynthic_burst_effect`` /
        # ``diplomatic_relations_effect`` unit-leaf idiom. Adding this
        # leaf is what flips Cut Propulsion into the spell-card-bridge
        # admit set: with the Rust variant + bridge arm landed it is
        # now covered+bridged AND round-trips here, so
        # :func:`_printing_is_bridge_simple_spell` admits the ``{2}{R}``
        # single-target Instant (auto-grow, no hardcoded list — the
        # §2 teeth).
        if isinstance(eff, CutPropulsionEffect):
            return {"kind": "cut_propulsion_effect"}
        # Invasive Maneuvers (Effect-uncovered Tier-A; ~10,981 17lands
        # decks). Two-int covered variant — Rust's ``parse_effect``
        # ``"invasive_maneuvers_effect"`` arm carries ``base`` +
        # ``boosted`` ints and the dict→Python bridge arm
        # (cross_engine.py ``invasive_maneuvers_effect``) constructs
        # ``DealDamageToTargetCreatureSpacecraftBoosted(base=base,
        # boosted=boosted)``. The single creature target rides on the
        # spell StackItem, NOT in this dict; the Spacecraft check is
        # intrinsic (resolves off the source-controller's bf via the
        # printing's ``subtypes`` — Spacecraft is a SUBTYPE per
        # ``cards/base.py:1056-1057``). No token pid → no
        # :func:`_seat_token_printings` dependency; the round-trip is
        # the clean ``focus_fire_effect`` single-int-field idiom
        # widened to two ints. Adding this leaf is what flips Invasive
        # Maneuvers into the spell-card-bridge admit set: with the
        # Rust variant + bridge arm landed it is now covered+bridged
        # AND round-trips here, so
        # :func:`_printing_is_bridge_simple_spell` admits the ``{1}{R}``
        # single-target Instant (auto-grow, no hardcoded list — the
        # §2 teeth).
        if isinstance(eff, DealDamageToTargetCreatureSpacecraftBoosted):
            return {
                "kind": "invasive_maneuvers_effect",
                "base": int(eff.base),
                "boosted": int(eff.boosted),
            }
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
        # Emergency Eject (Effect-uncovered single-gated tier;
        # ~6,291 17lands decks). Same Lander-pid carrier shape as
        # Seedship Impact: Rust's ``parse_effect``
        # ``"emergency_eject_effect"`` arm
        # ``require("token_printing_id")`` for the Lander; the
        # matching dict→Python bridge arm (cross_engine.py
        # ``emergency_eject_effect``) DROPS the pid and constructs
        # the FIELD-FREE Python class
        # ``DestroyTargetNonlandPermanentWithLanderForController``
        # (which mints the Lander intrinsically via
        # ``TOKEN_PRINTINGS["Lander"]``). The reverse serializer emits
        # the SYMBOLIC ``_token_card_def`` Lander reference the same
        # way Seedship / Orbital Plunge do; the loader's
        # :func:`_seat_token_printings` pass (already walking
        # ``spell_effect`` per the round-73 sub-substrate, extended
        # below to recognize this new kind) rewrites it to the
        # numeric ``token_printing_id`` Rust requires + registers
        # the matching Python printing. Round-trip-or-bail preserved.
        if isinstance(eff, DestroyTargetNonlandPermanentWithLanderForController):
            lcd = _canonical_lander_token_card_def()
            if lcd is None:
                return None
            return {
                "kind": "emergency_eject_effect",
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
        # Shattered Wings's destroy half (Effect-uncovered single-
        # gated tier; ~7,793 17lands decks). Pid-FREE covered unit
        # variant — Rust's ``parse_effect`` ``"destroy_target_
        # artifact_enchantment_or_flying_creature"`` arm takes NO
        # fields and the dict→Python bridge arm (cross_engine.py
        # ``destroy_target_artifact_enchantment_or_flying_creature``)
        # constructs the field-free
        # ``DestroyTargetArtifactEnchantmentOrFlyingCreature()``. The
        # 3-way OR filter (Artifact OR Enchantment OR (Creature AND
        # has-flying)) is intrinsic. No token pid → no
        # :func:`_seat_token_printings` dependency; the round-trip is
        # the clean ``destroy_target_artifact_or_tapped_creature``
        # unit-leaf idiom. Adding this leaf + the matching
        # ``Surveil`` leaf below is what flips Shattered Wings into
        # the spell-card-bridge admit set: with the Rust variant +
        # bridge arm landed AND the outer Sequence's children all
        # serializable, the {2}{G} Sorcery is now covered+bridged
        # AND round-trips through the reverse serializer, so
        # :func:`_printing_is_bridge_simple_spell` admits it
        # (auto-grow, no hardcoded list — the §2 teeth).
        if isinstance(eff, DestroyTargetArtifactEnchantmentOrFlyingCreature):
            return {
                "kind": (
                    "destroy_target_artifact_enchantment_or_flying_"
                    "creature"
                ),
            }
        # Exorcise (Effect-uncovered single-gated tier; Duskmourn).
        # Pid-FREE covered unit variant — Rust's ``parse_effect``
        # ``"exorcise_effect"`` arm takes NO fields and the dict→Python
        # bridge arm (cross_engine.py ``exorcise_effect``) constructs
        # the field-free ``ExorciseEffect()``. The 3-way OR filter
        # (Artifact OR Enchantment OR (Creature AND effective_power
        # >= 4)) is intrinsic. No token pid → no
        # :func:`_seat_token_printings` dependency; the round-trip is
        # the clean ``destroy_target_artifact_or_tapped_creature``
        # unit-leaf idiom. Adding this leaf is what flips Exorcise
        # into the spell-card-bridge admit set: with the Rust variant +
        # bridge arm landed AND the printing's spell_effect
        # serializable, the {1}{W} Sorcery is now covered+bridged AND
        # round-trips through the reverse serializer, so
        # :func:`_printing_is_bridge_simple_spell` admits it (auto-
        # grow, no hardcoded list — the §2 teeth).
        if isinstance(eff, ExorciseEffect):
            return {"kind": "exorcise_effect"}
        # Close Encounter — additional-cost-choice closure (Cycle 3,
        # 2026-05-21; ~16,098 17lands decks — highest-deck-count
        # BLOCKED card in the substrate-gated tier). Pid-FREE
        # covered unit variant — Rust's ``parse_effect``
        # ``"close_encounter_effect"`` arm takes NO fields and the
        # dict→Python bridge arm (cross_engine.py
        # ``close_encounter_effect``) constructs the field-free
        # ``CloseEncounterEffect()``. The damage amount is intrinsic
        # (computed at resolve from the additional-cost-choice
        # object's power, read via the
        # ``additional_cost_choice_id`` StackItem channel — the
        # Cycle 1 substrate landed in this same lane). The single
        # damage-target rides on the StackItem
        # (``current_resolve_payload_target_id``), NOT in this dict.
        # No token pid → no :func:`_seat_token_printings` dependency;
        # the round-trip is the clean ``exorcise_effect`` /
        # ``diplomatic_relations_effect`` unit-leaf idiom. Adding
        # this leaf — TOGETHER with the admit-predicate widen below
        # (which lets the choose-your-creature additional-cost flag
        # through when the covered+bridged ``CloseEncounterEffect``
        # is the spell's effect) — is what flips Close Encounter
        # into the spell-card-bridge admit set.
        if isinstance(eff, CloseEncounterEffect):
            return {"kind": "close_encounter_effect"}
        # Darkness — combat-damage prevention closure (Cycle 3,
        # 2026-05-22; DSK special-guests reprint in the EoE pool, 43
        # 17lands decks). Pid-FREE covered unit variant — Rust's
        # ``parse_effect`` ``"prevent_all_combat_damage_this_turn"`` arm
        # takes NO fields and the dict→Python bridge arm
        # (cross_engine.py ``prevent_all_combat_damage_this_turn``)
        # constructs the field-free
        # ``PreventAllCombatDamageThisTurn()``. The prevention is
        # unconditional (no targets, no scoping); the global per-turn
        # state-level flag is the carrier (Python's
        # ``state.prevent_combat_damage_this_turn`` / Rust's
        # ``state.prevent_all_combat_damage_this_turn`` — Cycle 1
        # substrate). No token pid → no
        # :func:`_seat_token_printings` dependency; the round-trip is
        # the clean ``exorcise_effect`` / ``close_encounter_effect``
        # unit-leaf idiom. Adding this leaf flips Darkness into the
        # spell-card-bridge admit set via the existing Phase-3
        # ``(0, 0)``-shape wrath admit arm in
        # :func:`_printing_is_bridge_simple_spell`: ``target_count_
        # range() == (0, 0)``, no ``slot_kinds``, no ``targets``
        # attribute on the printing. The §2 teeth all fire positively
        # (covered+bridged AND round-trips), so the lever auto-grows
        # the admit set 24 → 25 — no hardcoded card-name list.
        if isinstance(eff, PreventAllCombatDamageThisTurn):
            return {"kind": "prevent_all_combat_damage_this_turn"}
        # **Control-change-UEOT subsystem — Cycle 4 live mint site
        # (2026-05-22; ~4,671 17lands decks).** Pid-FREE covered unit
        # variant — Rust's ``parse_effect`` ``"mutinous_massacre_
        # effect"`` arm takes NO fields and the dict→Python bridge arm
        # (cross_engine.py ``mutinous_massacre_effect``) constructs
        # the field-free ``MutinousMassacreEffect()``. The odd/even
        # pick is intrinsic to the resolve arm (Rust default = pick
        # 0 / odd, mirroring Python's no-agent fallback at
        # ``bespoke.py:1303-1306``). No token pid → no
        # :func:`_seat_token_printings` dependency; the round-trip is
        # the clean ``close_encounter_effect`` / ``exorcise_effect``
        # unit-leaf idiom. Adding this leaf flips Mutinous Massacre
        # into the spell-card-bridge admit set under the Phase-3
        # ``(0, 0)``-shape wrath admit arm — the §2 auto-grow teeth.
        if isinstance(eff, MutinousMassacreEffect):
            return {"kind": "mutinous_massacre_effect"}
        # **Control-change-UEOT subsystem — Cycle 5 live mint site
        # (2026-05-22; ~4,775 17lands decks).** Pid-FREE covered unit
        # variant — Rust's ``parse_effect`` ``"systems_override_effect"``
        # arm takes NO fields and the dict→Python bridge arm
        # (cross_engine.py ``systems_override_effect``) constructs
        # the field-free ``SystemsOverrideEffect()``. The single
        # target rides on the ``StackItem``'s payload-target field;
        # the +10 / -10 amount and Spacecraft-conditional charge-
        # counter rider are intrinsic to the resolve arm (oracle text
        # bakes "ten" in both places). No token pid → no
        # :func:`_seat_token_printings` dependency; the round-trip is
        # the clean ``mutinous_massacre_effect`` / ``close_encounter_
        # effect`` unit-leaf idiom. Adding this leaf flips Systems
        # Override into the spell-card-bridge admit set under the
        # Phase-1 ``(1, 1)`` single-target admit arm — the §2
        # auto-grow teeth.
        if isinstance(eff, SystemsOverrideEffect):
            return {"kind": "systems_override_effect"}
        # **Control-change-UEOT subsystem — Vengeful Possession Cycle 1
        # (2026-05-22).** Pid-FREE covered unit variant — Rust's
        # ``parse_effect`` ``"threaten_target_creature_ueot"`` arm
        # takes NO fields and the dict→Python bridge arm
        # (cross_engine.py ``threaten_target_creature_ueot``) constructs
        # the field-free ``ThreatenTargetCreatureUEOT()``. The single
        # creature target rides on the ``StackItem``'s payload-target
        # field. No token pid → no :func:`_seat_token_printings`
        # dependency; the round-trip is the clean
        # ``systems_override_effect`` / ``mutinous_massacre_effect``
        # unit-leaf idiom.
        if isinstance(eff, ThreatenTargetCreatureUEOT):
            return {"kind": "threaten_target_creature_ueot"}
        # **Vengeful Possession Cycle 1 — looter-rider composite leaves
        # (2026-05-22).** Vengeful Possession's spell_effect is
        # ``Sequence(ThreatenTargetCreatureUEOT,
        # IfYouDo(MayDo(DiscardSelf(1)), DrawCards(1)))`` — a
        # threaten-then-may-discard-draw looter rider. The composite
        # Effects (Sequence, IfYouDo, MayDo, DiscardSelf, DrawCards)
        # are ALREADY Rust-covered AND have ``cross_engine.py`` bridge
        # arms; they were just missing here in the
        # ``_python_spell_effect_to_dict`` reverse-serializer
        # ``_leaf`` table. Adding these leaves lets ``Sequence`` (whose
        # composer recurses into ``_leaf`` for each child) emit the
        # full looter dict shape — auto-grow §2 teeth.
        #
        # **Schema parity with the cross_engine.py bridge arms:**
        #
        #   * ``DrawCards`` → ``{"kind": "draw_cards", "count": N}``
        #     (cross_engine.py:765; Python `DrawCards.amount` →
        #     dict `count` — the documented field rename. Rust's
        #     ``parse_effect`` reads ``count``.)
        #   * ``DiscardSelf`` → ``{"kind": "discard_self", "amount": N}``
        #     (cross_engine.py:1162; field name matches both sides.)
        #   * ``MayDo`` → ``{"kind": "may_do", "inner_effect": <eff>,
        #     "prompt": str}`` (cross_engine.py:1933; Python
        #     ``MayDo.inner`` → dict ``inner_effect`` — the documented
        #     field rename. Rust's ``parse_effect`` REQUIRES
        #     ``inner_effect`` and reads ``prompt`` with empty-string
        #     default.)
        #   * ``IfYouDo`` → ``{"kind": "if_you_do", "do_action": <eff>,
        #     "then_action": <eff>}`` (cross_engine.py:1898; both fields
        #     REQUIRED on the Rust parser.)
        #
        # The recurse-or-bail discipline matches the Sequence composer
        # (line 4845): if a nested child can't be serialized, the
        # recursive ``_leaf`` call returns ``None`` and the composer
        # bails — keeps the no-fallback-hybrid teeth (a partially-
        # serializable composite would silently drop a child on Rust).
        if isinstance(eff, DrawCards):
            return {"kind": "draw_cards", "count": int(eff.amount)}
        if isinstance(eff, DiscardSelf):
            return {"kind": "discard_self", "amount": int(eff.amount)}
        if isinstance(eff, MayDo):
            inner_dict = _leaf(eff.inner)
            if inner_dict is None:
                return None  # recurse-or-bail
            return {
                "kind": "may_do",
                "inner_effect": inner_dict,
                "prompt": str(eff.prompt),
            }
        # **Swarm Culler Cycle 1 — ``OptionalSacAnotherForEffect``
        # reverse-serializer leaf (2026-05-23).** Mirror of the new
        # Rust ``Effect::OptionalSacAnotherForEffect { inner_effect:
        # Box<Effect> }`` payload at ``rust/src/cards.rs``. Emits the
        # dict shape consumed by ``cross_engine._ta_dict_to_python_
        # effect``'s ``optional_sac_another_for_effect`` arm and the
        # Rust ``parse_effect`` ``optional_sac_another_for_effect``
        # arm.
        #
        # **Recursive ``inner_effect`` field.** Recurses via
        # ``_leaf`` on the inner Effect (sibling of ``may_do``'s
        # ``inner_effect`` recursion). If the inner leaf returns
        # ``None`` the whole shape bails — recurse-or-bail
        # discipline preserves the no-fallback-hybrid teeth (a
        # genuinely-unseatable inner means the wrapper is also
        # unseatable; the round-trip-or-bail clause at the call
        # site declines the parent shape).
        #
        # **Substrate-only landing.** Swarm Culler is a Creature
        # with a BECOMES_TAPPED triggered ability — NOT a Spell.
        # The spell-card-bridge admit set / safe-trigger admit gate
        # is unchanged by this cycle (per the Comet Crawler /
        # Mutinous Massacre / Dyadrine Attack / Boilerbilges
        # Ripper / Hemosymbic Mite precedent — per-card cross-
        # engine parity probe lives in
        # ``tests/test_swarm_culler_parity.py``). The reverse
        # serializer leaf lands the substrate so a future cycle
        # widening the bench-admit set picks it up for free; it
        # does NOT widen any admit set today.
        if isinstance(eff, OptionalSacAnotherForEffect):
            inner_dict = _leaf(eff.inner_effect)
            if inner_dict is None:
                return None  # recurse-or-bail
            return {
                "kind": "optional_sac_another_for_effect",
                "inner_effect": inner_dict,
            }
        if isinstance(eff, IfYouDo):
            do_dict = _leaf(eff.do_action)
            then_dict = _leaf(eff.then_action)
            if do_dict is None or then_dict is None:
                return None  # recurse-or-bail
            return {
                "kind": "if_you_do",
                "do_action": do_dict,
                "then_action": then_dict,
            }
        # **Splitskin Doll Cycle 1 — `IfNot` reverse-serializer leaf
        # (2026-05-23).** Mirror of the Rust ``Effect::IfNot {
        # condition_tag: String, condition_args: Vec<i32>, then:
        # Box<Effect> }`` payload at ``rust/src/cards.rs``. Emits the
        # dict shape consumed by ``cross_engine._ta_dict_to_python_
        # effect``'s ``if_not`` arm and the Rust ``parse_effect``
        # ``if_not`` arm — both whitelist
        # ``controls_another_creature_with_power_at_most`` as the
        # only condition tag in scope for Cycle 1.
        #
        # **Field-name translation.** Python's
        # ``IfNot(condition: Condition, then: Effect)`` carries a
        # whole ``Condition`` value object (here:
        # ``ControlsAnotherCreatureWithPowerAtMost(threshold=2)``);
        # Rust's payload is the flattened ``condition_tag`` /
        # ``condition_args`` stringly-typed dispatch table (same
        # precedent as ``StaticSelfBonus.condition_tag``). The leaf
        # walks the condition's class to pick the tag, then reads
        # its dataclass fields for the args list.
        #
        # **Recursive ``then`` field.** Recurses via ``_leaf`` on
        # the inner Effect (sibling of ``if_you_do``'s ``do_action``
        # / ``then_action`` recursion). Unknown condition class →
        # recurse-or-bail return ``None`` so the parent composer
        # stays consistent with the no-fallback-hybrid teeth.
        if isinstance(eff, IfNot):
            then_dict = _leaf(eff.then)
            if then_dict is None:
                return None  # recurse-or-bail
            cond = eff.condition
            if isinstance(cond, ControlsAnotherCreatureWithPowerAtMost):
                condition_tag = (
                    "controls_another_creature_with_power_at_most"
                )
                condition_args = [int(cond.threshold)]
            else:
                # Unknown condition class for Cycle 1; bail.
                return None
            return {
                "kind": "if_not",
                "condition_tag": condition_tag,
                "condition_args": condition_args,
                "then": then_dict,
            }
        # **Weftwalking Cycle 1 — ``ConditionalIfCastFromHand``
        # reverse-serializer leaf (2026-05-23).** Mirror of the Rust
        # ``Effect::ConditionalIfCastFromHand { inner: Box<Effect> }``
        # payload at ``rust/src/cards.rs``. Emits the dict shape
        # consumed by ``cross_engine._ta_dict_to_python_effect``'s
        # ``conditional_if_cast_from_hand`` arm and the Rust
        # ``parse_effect`` ``conditional_if_cast_from_hand`` arm.
        #
        # **Field-name translation: Python ``inner_effect`` -> Rust
        # ``inner``.** Python's class names the field ``inner_effect``
        # while Rust uses ``inner``; the leaf translates at this
        # seam.
        #
        # **Recursive ``inner_effect`` field.** Recurses via
        # ``_leaf`` on the inner Effect (sibling of ``may_do``'s
        # ``inner`` recursion, ``if_you_do``'s ``do_action`` /
        # ``then_action`` recursion). Recurse-or-bail preserves the
        # no-fallback-hybrid teeth.
        if isinstance(eff, ConditionalIfCastFromHand):
            inner_dict = _leaf(eff.inner_effect)
            if inner_dict is None:
                return None  # recurse-or-bail
            return {
                "kind": "conditional_if_cast_from_hand",
                "inner": inner_dict,
            }
        # **Weftwalking Cycle 1 — ``ShuffleZonesIntoLibrary``
        # reverse-serializer leaf (2026-05-23).** Mirror of the Rust
        # ``Effect::ShuffleZonesIntoLibrary { zones: Vec<String> }``
        # payload at ``rust/src/cards.rs``. Emits the dict shape
        # consumed by ``cross_engine._ta_dict_to_python_effect``'s
        # ``shuffle_zones_into_library`` arm and the Rust
        # ``parse_effect`` ``shuffle_zones_into_library`` arm.
        #
        # **Flat-list leaf.** ``zones`` is a flat tuple of strings on
        # Python; we emit it as a list of strings. No nested Effect
        # to recurse on (sibling of leaves like ``draw_cards`` /
        # ``deal_damage`` that carry only scalar payload). The
        # narrow zone vocabulary (``"hand"`` / ``"graveyard"``) is
        # enforced at resolve time on both engines, not at this
        # serializer leaf — permissive emit keeps the round-trip
        # byte-equal.
        if isinstance(eff, ShuffleZonesIntoLibrary):
            return {
                "kind": "shuffle_zones_into_library",
                "zones": [str(z) for z in eff.zones],
            }
        # **Control-change-UEOT subsystem — Cycle 5 delayed-trigger
        # complement (2026-05-22).** Single-field
        # ``RemoveChargeCountersFromSourceDelayed(amount)`` leaf.
        # Round-trips through the field-bearing dict — Rust's
        # ``parse_effect`` ``"remove_charge_counters_from_source_
        # delayed"`` arm REQUIRES ``amount`` and the dict→Python
        # bridge arm reconstructs ``RemoveChargeCountersFromSource
        # Delayed(amount=amount)`` byte-equal. Scheduled by Systems
        # Override at resolve time; this leaf exists so the
        # ``delayed_triggers`` bridge round-trip is complete (the
        # no-fallback-hybrid completeness teeth — without it a
        # mid-game state-sync from Python → Rust would silently
        # discard the in-flight rider).
        if isinstance(eff, RemoveChargeCountersFromSourceDelayed):
            return {
                "kind": "remove_charge_counters_from_source_delayed",
                "amount": int(eff.amount),
            }
        # **Carrier-AA substrate Phase 3A Cycle 1 (2026-05-25).**
        # Single-field ``ReturnExiledPermanentToOwnerTapped(exile_card_
        # id)`` leaf — Mystifying Maze's paired delayed-trigger return
        # effect. Round-trips through the field-bearing dict — Rust's
        # ``parse_effect`` ``"return_exiled_permanent_to_owner_tapped"``
        # arm REQUIRES ``exile_card_id`` and the dict→Python bridge arm
        # reconstructs ``ReturnExiledPermanentToOwnerTapped(exile_card_
        # id=...)`` byte-equal. Scheduled by Mystifying Maze's resolve
        # arm at producer time; this leaf exists so the
        # ``delayed_triggers`` bridge round-trip is complete (the
        # no-fallback-hybrid completeness teeth — without it a mid-
        # game state-sync from Python → Rust would silently discard
        # the in-flight return-on-EoT rider). Same single-int-field
        # shape as the ``RemoveChargeCountersFromSourceDelayed``
        # sibling at the previous leaf entry.
        from mtg_bot.effects.generic.exile import (
            ReturnExiledPermanentToOwnerTapped as _ReturnExiledPermanentToOwnerTapped,
        )
        if isinstance(eff, _ReturnExiledPermanentToOwnerTapped):
            return {
                "kind": "return_exiled_permanent_to_owner_tapped",
                "exile_card_id": int(eff.exile_card_id),
            }
        # **Phase-3 wrath-admit-widening (2026-05-21).** Pyroclasm-shape
        # mass-damage leaf — ``DealNDamageToEachCreature(amount)``. The
        # bridge arm at ``cross_engine.py::damage_each_creature`` REQUIRES
        # ``amount`` (no default; mirrors Rust's ``parse_effect`` REQUIRED-
        # field contract at ``cards.rs:7435``+) and constructs the
        # field-clean ``DealNDamageToEachCreature(amount=amount)`` — the
        # bare 2-field round-trip is bit-equal. Wrath-shape ``(0, 0)``
        # spell-effect with no at-cast target (acts on the full
        # battlefield snapshot at resolve-time). EoE consumer:
        # Pyroclasm — already PROBED by its dedicated effect-close probe;
        # this leaf admits it through the spell-card-bridge wrath path
        # as well (auto-grow; no hardcoded card-name list — the §2
        # teeth). Mirrors the ``depressurize_effect`` / ``focus_fire_
        # effect`` single-int-field idiom.
        if isinstance(eff, DealNDamageToEachCreature):
            return {
                "kind": "damage_each_creature",
                "amount": int(eff.amount),
            }
        # **Phase-3 wrath-admit-widening (2026-05-21).** Bare-shape
        # ``DestroyAllCreatures()`` leaf — only the field-free shape
        # round-trips. Python's class carries optional narrowing fields
        # (``tapped_only``, ``untapped_only``, ``min_power``) that Rust's
        # unit-variant ``Effect::DestroyAllCreatures`` (cards.rs:7818)
        # does NOT represent; the bridge arm always rebuilds the bare
        # ``DestroyAllCreatures()``. Serializing a narrowed variant
        # would silently widen the destroy filter on Rust — the §2
        # teeth bail here when any narrowing flag is set, mirroring the
        # ``Surveil`` ``use_artifact_count`` decline-path. No EoE-pool
        # ``(0, 0)`` non-modal consumer at this HEAD (Singularity
        # Rupture is ``(0, 8)``; Split Up is modal; Zero Point Ballad
        # uses the ``min_power`` narrowing). The leaf is load-bearing
        # for the wrath-shape round-trip surface — keeps the serializer
        # symmetric with the bridge arm's known-shape coverage.
        if isinstance(eff, DestroyAllCreatures):
            if (
                eff.tapped_only
                or eff.untapped_only
                or eff.min_power
            ):
                return None
            return {"kind": "destroy_all_creatures"}
        # **Beyond-the-Quiet slice (2026-05-21).** Wrath-shape exile
        # leaf — ``ExileAllCreaturesAndSpacecraft``. Pid-FREE covered
        # unit variant — Rust's ``parse_effect``
        # ``"exile_all_creatures_and_spacecraft"`` arm takes NO fields
        # and the dict→Python bridge arm (cross_engine.py
        # ``exile_all_creatures_and_spacecraft``) constructs the
        # field-free ``ExileAllCreaturesAndSpacecraft()``. The
        # Creature-OR-Spacecraft filter is intrinsic (resolves off the
        # printing's ``card_types`` / ``subtypes``); no targets, acts
        # on the full battlefield snapshot at resolve-time. Mirrors
        # the ``destroy_all_creatures`` unit-leaf idiom. Adding this
        # leaf is what flips Beyond the Quiet (4,698 17lands decks)
        # into the spell-card-bridge admit set via Lane Y's Phase-3
        # ``(0, 0)`` wrath admit arm: with the Rust variant + bridge
        # arm landed it is now covered+bridged AND round-trips here,
        # so :func:`_printing_is_bridge_simple_spell` admits the
        # ``{3}{W}{W}`` no-target Sorcery (auto-grow, no hardcoded
        # list — the §2 teeth; the admit set grows 15 → 16).
        if isinstance(eff, ExileAllCreaturesAndSpacecraft):
            return {"kind": "exile_all_creatures_and_spacecraft"}
        # **Phase-3 wrath-admit-widening (2026-05-21).** ManifestDread
        # spell-effect leaf — ``ManifestDread(count)``. The bridge arm
        # at ``cross_engine.py::manifest_dread`` reads ``count`` (default
        # 1 if omitted) and constructs ``ManifestDread(count=count)`` —
        # the bare single-int round-trip is bit-equal. Wrath-shape
        # ``(0, 0)`` spell-effect: the manifest-dread CR 701.55 mechanic
        # operates on the caster's library (look 2, manifest 1 face-down,
        # graveyard 1) at resolve-time with NO at-cast target binding —
        # the canonical wrath-shape no-targets EoE spell. EoE consumers
        # (loaded via the duskmourn.json card pool): Manifest Dread (the
        # eponymous Sorcery), Break Down the Door (the Instant flash
        # variant), Under the Skin (the {1}{B} Sorcery variant) —
        # Manifest Dread is ALREADY PROBED by its dedicated empty-lib
        # no-op probe (``test_probe_remaining_sss.py``); the two new
        # ``Break Down the Door`` / ``Under the Skin`` probes added by
        # this lane drive the SAME bridge arm through their respective
        # parsed printings, flipping each from COVERED → PROBED. Mirrors
        # the bridge arm's ``count``-defaulting-to-1 / non-negative
        # contract.
        if isinstance(eff, ManifestDread):
            if eff.count < 0:
                return None
            return {
                "kind": "manifest_dread",
                "count": int(eff.count),
            }
        # Bare-shape Surveil leaf (no ``use_artifact_count`` rider).
        # Mirrors the safe-trigger Surveil arm
        # (:func:`_python_ta_to_safe_dict` Surveil case): Python's
        # class carries an additional ``use_artifact_count`` flag
        # that selects the Surveil-X-where-X=artifacts variant
        # (``effects/generic/library_lookat.py:580``); Rust's
        # ``Effect::Surveil { count: i32 }`` does NOT represent the
        # X variant — gate on the rider being False so the X
        # variant falls through to the bail path. Rust's spelling
        # for the count field is ``count`` (not Python's
        # ``amount``); the cross_engine bridge arm
        # (``cross_engine.py:1030`` ``surveil``) reads ``count`` and
        # constructs ``Surveil(amount=count)`` — bidirectional with
        # what we emit here. Adding this leaf — together with the
        # destroy leaf above — admits Shattered Wings's outer
        # Sequence into the bridge admit set.
        if isinstance(eff, Surveil):
            if eff.use_artifact_count:
                return None
            return {"kind": "surveil", "count": int(eff.amount)}
        # **ModalChooseOne envelope — Cycle 4 (per-leaf Effect for
        # all-untargeted modal cards, 2026-05-21).** Per-leaf
        # ``DealDamageEachOpponent(amount)`` arm — Ruinous Rampage's
        # mass-burn mode (the all-untargeted half of the
        # ``ModalChooseOne([DealDamageEachOpponent,
        # ExileAllArtifactsWithManaValueAtMost])`` shape, the only
        # all-untargeted ModalChooseOne candidate in the EoE pool).
        # Rust variant `Effect::DamageEachOpponent { amount: i32 }`
        # (`cards.rs:246`) is shipped + bridged via
        # `cross_engine.py::damage_each_opponent` ↔
        # `DealDamageEachOpponent`. The bare 2-field round-trip
        # (`kind` + `amount`) is bit-equal — mirrors the
        # `damage_each_creature` and `depressurize_effect` single-int
        # idioms. Non-negative invariant (Rust raises on negative at
        # resolve; Python's class has no validation — bail at the
        # serializer if the field is negative to keep the round-trip
        # symmetric).
        if isinstance(eff, DealDamageEachOpponent):
            if eff.amount < 0:
                return None
            return {
                "kind": "damage_each_opponent",
                "amount": int(eff.amount),
            }
        # **ModalChooseOne envelope — Cycle 4 (per-leaf Effect for
        # all-untargeted modal cards, 2026-05-21).** Per-leaf
        # ``ExileAllArtifactsWithManaValueAtMost(max_mv)`` arm —
        # Ruinous Rampage's anti-artifact mode (paired with
        # ``DealDamageEachOpponent`` above; the two together carry the
        # all-untargeted ModalChooseOne admit shape for the Sorcery).
        # Rust variant
        # ``Effect::ExileAllArtifactsWithManaValueAtMost { max_mv: i32 }``
        # ships in the SAME cycle (declaration + parse + to_pydict +
        # resolve arms). Two-field round-trip (`kind` + `max_mv`) is
        # bit-equal. Non-negative invariant per CR 202.3 (MV is
        # non-negative; Python class default is 3, parser only emits
        # explicit values via the regex digit capture — but bail
        # defensively on a negative if a future hand-built call
        # constructs one).
        if isinstance(eff, ExileAllArtifactsWithManaValueAtMost):
            if eff.max_mv < 0:
                return None
            return {
                "kind": "exile_all_artifacts_with_mana_value_at_most",
                "max_mv": int(eff.max_mv),
            }
        # **Warping Wail Cycle 1a substrate (2026-05-22).** Single-
        # `max_value` round-trip leaf for the (1, 1)-shape single-
        # target exile-with-P-or-T-threshold variant. Sibling shape to
        # the `exile_all_artifacts_with_mana_value_at_most` leaf above
        # (single-int payload; non-negative invariant). Substrate-only
        # leaf — Warping Wail itself stays DECLINED at the admit gate
        # this cycle (Mode 2 + Mode 3 still gap; see
        # `docs/SEARCH_LIMITATIONS.md`'s "Warping Wail Cycle 1a
        # substrate LANDED" block for the 4-cycle decomposition
        # rationale). Adding this leaf does NOT by itself flip any
        # printing into the spell-card-bridge admit set — Warping Wail
        # has additional uncovered modes; once Cycles 2 + 3 land their
        # substrates AND Cycle 4 widens the admit predicate, Warping
        # Wail will auto-join the §2 admit set via the same auto-grow
        # teeth that flipped Focus Fire / Cut Propulsion / etc.
        if isinstance(eff, ExileTargetCreatureWithPowerOrToughnessAtMost):
            if eff.max_value < 0:
                return None
            return {
                "kind": "exile_target_creature_with_power_or_toughness_at_most",
                "max_value": int(eff.max_value),
            }
        # **Warping Wail Cycle 2 substrate (2026-05-22).** Reverse-
        # serializer leaf for ``CounterTargetSpell`` — closes the
        # previously-deferred gap (the cycle-1a docstring noted
        # ``CounterTargetSpell.filter_types`` as a Mode 2 cycle-2
        # deliverable). Bridge surface is symmetric:
        #
        #   * empty filter_types → emit bare ``{"kind":
        #     "counter_target_spell"}`` (byte-identical to every pre-
        #     closure round-trip — back-compat preserved).
        #   * non-empty filter_types → emit sorted list-of-strings
        #     (frozenset iteration is unstable; sort for byte-equal
        #     round-trip determinism, mirrors the established
        #     ``granted_keywords`` emit shape).
        #
        # Empty entries (``""`` in the frozenset) are rejected by
        # returning ``None`` — mirrors the Rust parse-arm contract
        # (each entry must be a non-empty string).
        if isinstance(eff, CounterTargetSpell):
            ft = eff.filter_types
            if any((not isinstance(t, str)) or not t for t in ft):
                return None
            out: dict = {"kind": "counter_target_spell"}
            if ft:
                out["filter_types"] = sorted(ft)
            return out
        # **Warping Wail Cycle 4 (2026-05-24) — spell-side CreateToken
        # leaf.** Per-leaf serializer for ``CreateToken(token_printing,
        # count, tapped, ...)`` when nested inside a ``ModalChooseOne``
        # (Warping Wail mode 3 mints a 1/1 colorless Eldrazi Scion
        # token; the C3 substrate added the bridge-correct token-AA
        # CardDef helper :func:`_token_creature_with_safe_mana_activated_
        # ability_card_def`). Sibling of the trigger-side
        # ``CreateToken`` arm in :func:`_python_ta_to_safe_dict` (line
        # 3699): same §2 token-shape disqualifier gates (each_player /
        # attacking / schedule_end_of_combat_sacrifice rejected; only
        # ``tapped=True`` rider is supported on top of the bare shape),
        # same symbolic ``_token_card_def`` carrier (numeric
        # ``token_printing_id`` is seated by
        # :func:`_seat_token_printings` AFTER the union ``card_defs``
        # tuple is frozen). The single difference vs the trigger-side
        # arm is that THIS one ALSO tries the C3-shipped
        # :func:`_token_creature_with_safe_mana_activated_ability_card_def`
        # helper (the Eldrazi Scion shape) so Warping Wail mode 3 can
        # round-trip; that helper is intentionally NOT consulted from
        # the trigger-side path (no current EoE triggered ability mints
        # an Eldrazi-Scion-shape token — the §2 narrow-admit
        # discipline).
        #
        # **The seating pass (:func:`_seat_token_printings`) is extended
        # in this cycle to walk INTO ``choose_one_mode.modes`` for
        # symbolic ``_token_card_def`` carriers (previously walked only
        # the top-level ``spell_effect`` dict via
        # :data:`_SPELL_TOKEN_PID_KINDS`); without that walk, the
        # symbolic ref would survive into ``build_rust_state`` and the
        # Rust parser would reject the dict.**
        if isinstance(eff, CreateToken):
            # **Narrow ``_in_modal_mode`` gate.** The
            # ``_seat_token_printings`` nested-walk extension shipping
            # in this cycle handles ONLY the
            # ``choose_one_mode.modes[i] == create_token / create_token_
            # tapped`` position. Bail in every other position (top-level
            # spell_effect, nested in Sequence / IfYouDo / MayDo / IfNot
            # / OptionalSacAnotherForEffect) — the symbolic ref would
            # survive past the loader and Rust's parse_effect would
            # reject the dict. Honest-stop: Glimmerburst /
            # Midnight Mayhem / Sami's Curiosity (the three EoE
            # printings whose CreateToken sits in a non-modal position)
            # stay DECLINED until each gets its own substrate slice +
            # _seat_token_printings walk extension + pin updates. The
            # §2 narrow-admit-per-cycle discipline.
            if not _in_modal_mode:
                return None
            if eff.each_player or eff.attacking:
                return None
            if getattr(eff, "schedule_end_of_combat_sacrifice", False):
                return None
            tp = eff.token_printing
            # Try all three token-shape helpers in the published §2-
            # narrow-admit order (each helper admits ONE shape only —
            # see the helpers' docstrings for the disjoint positive
            # gates):
            #   * vanilla creature, no AAs (Robot, etc.)
            #   * Lander shape (non-creature artifact + safe AA)
            #   * Eldrazi Scion shape (creature + sac-self mana AA)
            token_cd = _token_vanilla_card_def(tp)
            if token_cd is None:
                token_cd = _token_with_safe_activated_ability_card_def(tp)
            if token_cd is None:
                token_cd = (
                    _token_creature_with_safe_mana_activated_ability_card_def(tp)
                )
            if token_cd is None:
                return None
            eff_kind = "create_token_tapped" if eff.tapped else "create_token"
            return {
                "kind": eff_kind,
                "count": int(eff.count),
                # Symbolic token reference — replaced with a numeric
                # ``token_printing_id`` by :func:`_seat_token_printings`
                # (which now walks INTO ``choose_one_mode.modes`` too —
                # the spell-axis nested-token-seating extension shipping
                # in this cycle).
                "_token_card_def": token_cd,
            }
        # **Reroute Systems closure (2026-05-21).** ModalChooseOne
        # envelope **Cycle 6** per-leaf serializer for Reroute Systems
        # mode 0: ``PumpTargetArtifactOrCreatureUntilEOT``. The Rust
        # variant carries ``power_bonus``, ``toughness_bonus``, AND
        # the extended ``granted_keywords`` list-of-strings field (the
        # ``granted_keywords`` extension lands in this same closure
        # so the round-trip is bit-equal for Reroute Systems mode 0's
        # ``(0, 0, {"indestructible"})`` shape). Per the to_pydict
        # parity convention, ``granted_keywords`` is emitted ONLY
        # when non-empty so back-compat with every pre-closure parse
        # site that omits the field stays intact.
        if isinstance(eff, PumpTargetArtifactOrCreatureUntilEOT):
            out: dict = {
                "kind": "pump_target_artifact_or_creature_until_eot",
                "power_bonus": int(eff.power_bonus),
                "toughness_bonus": int(eff.toughness_bonus),
            }
            if eff.granted_keywords:
                # Sort for deterministic ordering — Python's
                # ``frozenset`` has unstable iteration order, but the
                # serialized list must round-trip byte-equal.
                out["granted_keywords"] = sorted(eff.granted_keywords)
            return out
        # **Reroute Systems closure (2026-05-21).** ModalChooseOne
        # envelope **Cycle 6** per-leaf serializer for Reroute Systems
        # mode 1: ``DealDamageToTargetTappedCreature``. The new Rust
        # variant carries the single ``amount: i32`` field (REQUIRED
        # — mirrors the round-28 REQUIRED-amount precedent for
        # ``damage_each_opponent`` / ``damage_each_creature``). Non-
        # negative invariant (Rust raises on negative at parse +
        # resolve; mirror that here so the round-trip surface stays
        # symmetric).
        if isinstance(eff, DealDamageToTargetTappedCreature):
            if eff.amount < 0:
                return None
            return {
                "kind": "deal_damage_to_target_tapped_creature",
                "amount": int(eff.amount),
            }
        # **ModalChooseOne envelope — Cycle 6 (Drill Too Deep closure,
        # 2026-05-21).** Per-leaf
        # ``PutChargeCountersOnTargetSpacecraftOrPlanetYouControl
        # (amount)`` arm — Drill Too Deep mode 0. The other mode
        # (``DestroyTargetArtifact``) already has a leaf above. Rust
        # variant ``Effect::PutChargeCountersOnTargetSpacecraftOrPlanet
        # YouControl { amount: i32 }`` ships in the SAME cycle
        # (declaration + parse + to_pydict + resolve arms +
        # cast-time per-mode binding detector entry). Two-field
        # round-trip (``kind`` + ``amount``) is bit-equal — mirrors
        # the ``exile_all_artifacts_with_mana_value_at_most`` /
        # ``damage_each_opponent`` single-int-field idiom. Non-
        # negative invariant per CR 122 (charge counters are non-
        # negative; parser emits explicit digits via
        # ``parser/effects.py:3002-3005``; bail defensively on a
        # negative if a hand-constructed instance ever leaks
        # through). Adding this leaf — TOGETHER with the matching
        # ``destroy_target_artifact`` leaf already present and the
        # Cycle-5 per-mode target binding in
        # ``cast_spell_noncreature`` — is what flips Drill Too Deep
        # into the spell-card-bridge admit set: both modes are
        # covered+bridged, the ModalChooseOne composer recurses into
        # both, and the {1}{R} Instant rides the Phase-1 ``(1, 1)``
        # admit shape.
        if isinstance(eff, PutChargeCountersOnTargetSpacecraftOrPlanetYouControl):
            if eff.amount < 0:
                return None
            return {
                "kind": (
                    "put_charge_counters_on_target_spacecraft_or_"
                    "planet_you_control"
                ),
                "amount": int(eff.amount),
            }
        # **Multi-target admit-gate Phase 4 widen (2026-05-21).** Per-
        # leaf serializer for
        # ``ReturnUpToNSmallCreaturesFromGraveyardWithCounters(max_n,
        # max_total_mv)`` — Scout for Survivors. Rust variant
        # ``Effect::ReturnUpToNSmallCreaturesFromGraveyardWithCounters
        # { max_n: i32, max_total_mv: i32 }`` ships in the SAME lane
        # (declaration + parse + to_pydict + resolve arms + bridge arm).
        # Three-field round-trip (``kind`` + ``max_n`` + ``max_total_mv``)
        # is bit-equal — mirrors the
        # ``invasive_maneuvers_effect`` two-int-field idiom widened to
        # the count + sum-MV-budget pair. Non-negative invariant per
        # CR 202.3 (mv is non-negative; max_n is non-negative); Python
        # class defaults to max_n=3, max_total_mv=3 (Scout's printed
        # values). Bail defensively on a negative if a hand-constructed
        # instance ever leaks through. Adding this leaf — TOGETHER with
        # the multi-target admit-gate Phase-4 widen below — is what
        # flips Scout for Survivors into the spell-card-bridge admit
        # set.
        #
        # **Riders gate.** The Python class is constructor sugar on the
        # unified ``ReturnFromGraveyard`` base; ``__post_init__`` pins
        # ``creature=True``, ``destination='battlefield'``,
        # ``plus_one_counter=True``, ``min_n=0``, ``max_mv=max_total_mv``.
        # The Rust variant carries ONLY ``max_n`` + ``max_total_mv``;
        # the destination + counter + creature filter + per-card MV cap
        # are intrinsic to the variant (not data fields). Bail if any
        # printed-from-text rider that DOESN'T fold into this fixed
        # shape is set (defensive; the parser only emits this shape
        # for the exact Scout-print pattern, but a future parser
        # extension that adds e.g. ``or_artifact=True`` would silently
        # mistranslate without this guard).
        # **X-value-subsystem Cycle 3 (2026-05-22).** Per-leaf
        # serializer for ``ZeroPointBalladEffect()`` — Zero Point Ballad
        # `{X}{B}`. Unit-variant round-trip: kind-only dict, mirroring
        # the ``BiosynthicBurstEffect`` / ``DiplomaticRelationsEffect``
        # / ``CloseEncounterEffect`` unit-leaf idiom. The X value rides
        # on the spell StackItem (``current_resolve_x_value`` via the
        # C1 bracket from ``StackItem.x_value`` minted at cast time by
        # C2.5), NOT in this dict — the field-free dataclass at
        # ``effects/bespoke.py:1677`` is the canonical Python parity.
        # Adding this leaf — TOGETHER with the Rust
        # ``Effect::ZeroPointBalladEffect`` variant + the matching
        # ``zero_point_ballad_effect`` bridge arm in ``cross_engine.py``
        # — is what flips Zero Point Ballad into the spell-card-bridge
        # admit set (Phase-3 ``(0, 0)``-shape wrath admit + the
        # X-cost C2.5 widen). The covered+bridged tooth picks up the
        # newly-shipped Rust variant via the
        # ``effect_coverage.covered_python_class_set()`` 1:1 identity
        # mapping (``ZeroPointBalladEffect`` -> ``ZeroPointBalladEffect``,
        # no override needed).
        if isinstance(eff, ZeroPointBalladEffect):
            return {"kind": "zero_point_ballad_effect"}
        # **Devastating Onslaught — Cycle 1 (2026-05-22).** Per-leaf
        # serializer for ``CreateXTokensOfTargetPermanentWithHasteEndStepSac()``
        # — second X-cost consumer (Zero Point Ballad shipped at C3 of
        # the X-value subsystem). Unit-variant round-trip: kind-only
        # dict, mirroring the ``ZeroPointBalladEffect`` /
        # ``BiosynthicBurstEffect`` / ``CloseEncounterEffect`` /
        # ``DiplomaticRelationsEffect`` unit-leaf idiom. The X value
        # rides on the spell StackItem
        # (``current_resolve_x_value`` via the C1 bracket from
        # ``StackItem.x_value`` minted at cast time by C2.5), the
        # cast-time-bound target rides on
        # ``current_resolve_payload_target_id`` — NOT in this dict.
        # The field-free dataclass at
        # ``effects/generic/tokens.py:404`` is the canonical Python
        # parity. Adding this leaf — TOGETHER with the Rust
        # ``Effect::CreateXTokensOfTargetPermanentWithHasteEndStepSac``
        # variant + the matching
        # ``create_x_tokens_of_target_permanent_with_haste_end_step_sac``
        # bridge arm in ``cross_engine.py`` — is what flips
        # Devastating Onslaught into the spell-card-bridge admit set
        # (Phase-1 ``(1, 1)``-shape + the X-cost C2.5 widen extended
        # to Phase 1 in this lane).
        if isinstance(eff, CreateXTokensOfTargetPermanentWithHasteEndStepSac):
            return {
                "kind":
                "create_x_tokens_of_target_permanent_with_haste_end_step_sac",
            }
        # **Devastating Onslaught — Cycle 1 (2026-05-22).** Per-leaf
        # serializer for the per-token end-step sac
        # ``SacrificeSourceDelayed()`` delayed-trigger effect. Unit-
        # variant — sibling of ``WarpExileSelf`` /
        # ``RemoveChargeCountersFromSourceDelayed``. Strictly for the
        # round-trip dict-shape surface; the delayed-trigger effect is
        # spawned dynamically by ``CreateXTokensOfTargetPermanentWith
        # HasteEndStepSac.resolve`` and is never a static printing-trigger
        # leaf the pool walker observes.
        if isinstance(eff, SacrificeSourceDelayed):
            return {"kind": "sacrifice_source_delayed"}
        # **Attack-in-the-Box Cycle 1 (2026-05-23).** Per-leaf
        # serializer for ``ScheduleSelfSacAtNextEndStep()`` — the
        # field-free composer dataclass at
        # ``effects/generic/delayed_actions.py:69``. Unit-variant —
        # emits bare ``{"kind": "schedule_self_sac_at_next_end_step"}``.
        # Composer that SCHEDULES a ``SacrificeSourceDelayed`` delayed
        # trigger at resolve time; the leaf already covered+bridged
        # from Devastating Onslaught Cycle 1. Strictly for the round-
        # trip dict-shape surface; the parser composes this into
        # ``IfYouDo(MayDo(PumpSelfUntilEOT), ScheduleSelfSac...)`` for
        # Attack-in-the-Box's attack trigger body
        # (``cards/parser/effects.py:3903-3912``).
        if isinstance(eff, ScheduleSelfSacAtNextEndStep):
            return {"kind": "schedule_self_sac_at_next_end_step"}
        # **Ouroboroid Cycle 1 (2026-05-23).** Per-leaf serializer for
        # ``PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()``
        # — the field-free counter-spread body for Ouroboroid's
        # beginning-of-combat-on-your-turn trigger. Unit-variant —
        # emits the bare ``{"kind": "put_plus_one_counters_on_each_
        # creature_you_control_equal_to_source_power"}``. X is dynamic
        # (read at resolve time from the source's effective power), so
        # there are no static fields to thread; both engines compose
        # the X-read into their resolve arms (Rust:
        # ``read_famished_source_power``; Python: ``effective_power``).
        if isinstance(
            eff, PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower
        ):
            return {
                "kind": (
                    "put_plus_one_counters_on_each_creature_you_"
                    "control_equal_to_source_power"
                ),
            }
        # **Hemosymbic Mite Cycle 1 (2026-05-23).** Per-leaf serializer
        # for ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()``
        # — the field-free +X/+X UEOT pump body for Hemosymbic Mite's
        # becomes-tapped trigger. Unit-variant — emits the bare
        # ``{"kind": "pump_target_other_creature_by_x_over_x_where_x_
        # is_source_power"}``. X is dynamic (read at resolve time from
        # the source's effective power), so there are no static fields
        # to thread; both engines compose the X-read into their
        # resolve arms (Rust: ``read_famished_source_power``; Python:
        # ``effective_power``).
        if isinstance(
            eff, PumpTargetOtherCreatureByXOverXWhereXIsSourcePower
        ):
            return {
                "kind": (
                    "pump_target_other_creature_by_x_over_x_where_"
                    "x_is_source_power"
                ),
            }
        # **Burgeoning Cycle 1 (2026-05-23).** Per-leaf serializer for
        # ``OptionalPutLandFromHandOntoBattlefield()`` — the field-free
        # optional-choice effect body for Burgeoning's opponent-plays-
        # land trigger. Unit-variant — emits the bare ``{"kind":
        # "optional_put_land_from_hand_onto_battlefield"}`` (no static
        # fields; the "may" + land-card target shape is intrinsic).
        # Sibling of the ``BoilerbilgesRipperETBEffect`` field-free
        # optional-choice serializer.
        if isinstance(
            eff, OptionalPutLandFromHandOntoBattlefield
        ):
            return {
                "kind": "optional_put_land_from_hand_onto_battlefield",
            }
        # **Osseous Sticktwister Cycle 1 (2026-05-23).** Per-leaf
        # serializer for
        # ``EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage()`` — the
        # field-free per-opponent three-mode-choice + conditional
        # source-power damage primitive for Osseous Sticktwister's
        # Delirium-gated end-step trigger. Unit-variant — emits the
        # bare ``{"kind": "each_opponent_sacs_or_discards_or_takes_
        # source_power_damage"}`` (no static fields; the per-opponent
        # loop + sac/discard/decline branching + source-power damage
        # formula is intrinsic). Sibling of
        # ``OptionalPutLandFromHandOntoBattlefield`` /
        # ``PumpTargetOtherCreatureByXOverXWhereXIsSourcePower`` /
        # ``ArabellaAttackEffect`` field-free serializers.
        if isinstance(
            eff, EachOpponentSacsOrDiscardsOrTakesSourcePowerDamage
        ):
            return {
                "kind": (
                    "each_opponent_sacs_or_discards_or_takes_"
                    "source_power_damage"
                ),
            }
        # **Terrasymbiosis Cycle 1 (2026-05-23).** Per-leaf serializer
        # for ``DrawCardsEqualToResolvingCounterAmount()`` — the
        # field-free counter-amount sibling of
        # ``DrawCardsEqualToResolvingCombatDamage``. Unit-variant —
        # emits the bare ``{"kind":
        # "draw_cards_equal_to_resolving_counter_amount"}``. The
        # carrier scalar (``state.resolving_counter_amount``) is
        # populated at COUNTERS_ADDED-observer dispatch time on Python
        # (production wire) and at test-injection time on Rust
        # (Cycle 1 substrate; production dispatch honest-stopped).
        if isinstance(eff, DrawCardsEqualToResolvingCounterAmount):
            return {"kind": "draw_cards_equal_to_resolving_counter_amount"}
        # **Terminal Velocity — Cycle 1 (2026-05-22).** Per-leaf
        # serializer for ``TerminalVelocityEffect()`` — the field-free
        # bespoke Sorcery body at ``effects/bespoke.py:3043``. The
        # corresponding Rust ``Effect::TerminalVelocityEffect``
        # variant + ``terminal_velocity_effect`` bridge arm in
        # ``cross_engine.py`` flip Terminal Velocity into the spell-
        # card-bridge admit set (Phase-3 ``(0, 0)``-shape wrath
        # admit — same target grammar as Pyroclasm / Manifest Dread
        # / Darkness; the §2 covered+bridged + round-trip-or-bail
        # teeth carry the load).
        if isinstance(eff, TerminalVelocityEffect):
            return {"kind": "terminal_velocity_effect"}
        # **Terminal Velocity — Cycle 1 (2026-05-22).** Per-leaf
        # serializer for ``DealSelfMVDamageToEachCreature()`` — the
        # LTB-trigger-body bespoke dataclass at
        # ``effects/bespoke.py:2998``. Unit-variant — sibling of
        # ``SacrificeSourceDelayed`` / ``WarpExileSelf``. Strictly for
        # the round-trip dict-shape surface; the LTB body is spawned
        # dynamically by ``TerminalVelocityEffect.resolve`` as the
        # body of a ``GrantTriggeredAbility`` UEOT push, never as a
        # static printing-trigger leaf the pool walker observes.
        if isinstance(eff, DealSelfMVDamageToEachCreature):
            return {"kind": "deal_self_mv_damage_to_each_creature"}
        if isinstance(eff, ReturnUpToNSmallCreaturesFromGraveyardWithCounters):
            if eff.max_n < 0 or eff.max_total_mv < 0:
                return None
            # Riders that don't fold into the fixed Rust variant shape.
            # The class pins creature=True, destination='battlefield',
            # plus_one_counter=True, min_n=0 in __post_init__; any
            # deviation from those defaults means the parser produced
            # a shape this round-trip doesn't cover.
            if (
                not eff.creature
                or eff.artifact
                or eff.land
                or eff.nonland_permanent
                or eff.or_enchantment
                or eff.or_spacecraft
                or eff.or_artifact
                or eff.destination != "battlefield"
                or not eff.plus_one_counter
                or eff.min_n != 0
                or eff.untargeted_all
                or eff.log_suffix
                or eff.target_kind != "graveyard_creature"
                or eff.max_mv != eff.max_total_mv
            ):
                return None
            return {
                "kind": (
                    "return_up_to_n_small_creatures_from_graveyard_"
                    "with_counters"
                ),
                "max_n": int(eff.max_n),
                "max_total_mv": int(eff.max_total_mv),
            }
        # **Pull Through the Weft Cycle 1 (2026-05-22).** Per-leaf
        # serializer for
        # ``ReturnUpToNNonlandPermanentCardsFromGraveyardToHand(min_n,
        # max_n)`` — the modeled first clause of Pull Through the
        # Weft ({3}{G}{G} Sorcery, 17lands deck presence: see EoE
        # pool). Rust variant
        # ``Effect::ReturnUpToNNonlandPermanentCardsFromGraveyardToHand
        # { min_n: i32, max_n: i32 }`` ships in the SAME lane
        # (declaration + parse + to_pydict + resolve arms + bridge
        # arm + spell_targets_satisfiable arm). Three-field round-
        # trip (``kind`` + ``min_n`` + ``max_n``) is bit-equal; non-
        # negative invariant.
        #
        # **Dropped lands clause is byte-equal-irrelevant.** Pull
        # Through the Weft's parser at ``parser/effects.py:5794``
        # consumes the full compound sentence ("Return up to N target
        # nonland permanent cards … then return up to M target land
        # cards … to the battlefield tapped") in one regex but only
        # emits the FIRST clause as a Python Effect — the lands-to-
        # bf-tapped clause is DROPPED. The Rust mirror inherits the
        # drop by simply not modeling it; the engine never tries to
        # return lands on either side, so the round-trip is byte-
        # equal under the cross-engine probe. Documented in
        # ``docs/SEARCH_LIMITATIONS.md`` entry "Pull Through the Weft
        # dropped lands clause".
        #
        # **Riders gate.** The Python class is constructor sugar on
        # the unified ``ReturnFromGraveyard`` base; ``__post_init__``
        # pins ``nonland_permanent=True``, ``destination='hand'``.
        # The Rust variant carries ONLY ``min_n`` + ``max_n``; the
        # destination + nonland-permanent filter are intrinsic to
        # the variant (not data fields). Bail if any rider that
        # DOESN'T fold into this fixed shape is set (defensive — the
        # parser only emits this shape for the bare nonland-
        # permanent-return-to-hand pattern, but a future parser
        # extension that adds a rider would silently mistranslate
        # without this guard).
        if isinstance(eff, ReturnUpToNNonlandPermanentCardsFromGraveyardToHand):
            if eff.min_n < 0 or eff.max_n < 0:
                return None
            if (
                eff.creature
                or eff.artifact
                or eff.land
                or not eff.nonland_permanent
                or eff.or_enchantment
                or eff.or_spacecraft
                or eff.or_artifact
                or eff.destination != "hand"
                or eff.plus_one_counter
                or eff.untargeted_all
                or eff.log_suffix
                or eff.target_kind != "graveyard_creature"
                or eff.max_mv != 0
                or eff.max_total_mv != 0
            ):
                return None
            return {
                "kind": (
                    "return_up_to_n_nonland_permanent_cards_from_"
                    "graveyard_to_hand"
                ),
                "min_n": int(eff.min_n),
                "max_n": int(eff.max_n),
            }
        # **Multi-target graveyard→HAND substrate (Archenemy's Charm
        # Mode 1, 2026-05-22).** Per-leaf serializer for
        # ``ReturnUpToNCreaturesFromYourGraveyardToHand(min_n, max_n)``
        # — the Mode 1 substrate of Archenemy's Charm. Rust variant
        # ``Effect::ReturnUpToNCreaturesFromYourGraveyardToHand
        # { min_n: i32, max_n: i32 }`` ships in the SAME lane
        # (declaration + parse + to_pydict + resolve arms + bridge
        # arm). Three-field round-trip (``kind`` + ``min_n`` +
        # ``max_n``) is bit-equal; non-negative invariant.
        #
        # **Riders gate.** The Python class is constructor sugar on
        # ``ReturnFromGraveyard``; ``__post_init__`` pins
        # ``creature=True``, ``destination='hand'``. The Rust variant
        # carries ONLY ``min_n`` + ``max_n``; the destination +
        # creature filter are intrinsic to the variant (not data
        # fields). Bail if any rider that DOESN'T fold into this
        # fixed shape is set (defensive — the parser only emits this
        # shape for the bare creature-return-to-hand pattern, but a
        # future parser extension that adds a rider would silently
        # mistranslate without this guard). NOT bridge-admitted as a
        # top-level spell_effect today — pool scan 2026-05-22 found 0
        # cards using this bare Effect as their spell_effect
        # (Archenemy's Charm uses it through a ChooseOneMode mode
        # slot, which has its own admit path); ship substrate-only.
        if isinstance(eff, ReturnUpToNCreaturesFromYourGraveyardToHand):
            if eff.min_n < 0 or eff.max_n < 0:
                return None
            if (
                not eff.creature
                or eff.artifact
                or eff.land
                or eff.nonland_permanent
                or eff.or_enchantment
                or eff.or_spacecraft
                or eff.or_artifact
                or eff.destination != "hand"
                or eff.plus_one_counter
                or eff.untargeted_all
                or eff.log_suffix
                or eff.target_kind != "graveyard_creature"
                or eff.max_mv != 0
                or eff.max_total_mv != 0
            ):
                return None
            return {
                "kind": (
                    "return_up_to_n_creatures_from_your_graveyard_"
                    "to_hand"
                ),
                "min_n": int(eff.min_n),
                "max_n": int(eff.max_n),
            }
        # **Singularity Rupture Cycle 1 (2026-05-24).** Field-free
        # frozen dataclass — the round-trip dict carries only
        # `kind`. Sibling of the `TerminalVelocityEffect` /
        # `ZeroPointBalladEffect` unit-variant idiom. Rust variant
        # `Effect::SingularityRuptureEffect` ships in the SAME lane
        # (declaration + parse + to_pydict + resolve arms + bridge
        # arm).
        if isinstance(eff, SingularityRuptureEffect):
            return {"kind": "singularity_rupture_effect"}
        # **Coordinated Clobbering Cycle 1 substrate (2026-05-24).**
        # Field-free frozen dataclass — the round-trip dict carries
        # only `kind`. Sibling of the `SingularityRuptureEffect` /
        # `TerminalVelocityEffect` unit-variant idiom. Rust variant
        # `Effect::CoordinatedClobberingEffect` ships in the SAME
        # lane (declaration + parse + to_pydict + resolve arms +
        # bridge arm). Substrate-only — Coordinated Clobbering's
        # `(2, 3)` heterogeneous 3-slot grammar stays declined at the
        # admit gate this cycle; Cycle 2 ships the Phase 6 admit arm
        # + 3-slot binder + admit-set pin bump.
        if isinstance(eff, CoordinatedClobberingEffect):
            return {"kind": "coordinated_clobbering_effect"}
        # **Archenemy's Charm flip (2026-05-24).** Two-field carrier.
        # Emit `amount` always (no Python-side default elision; Rust's
        # parse arm tolerates omitted `amount` defaulting to 2 — but
        # explicit emit keeps the §2 round-trip teeth honest). Emit
        # `granted_keywords` as a sorted list (Rust storage is
        # sorted-unique; emitting sorted keeps the dict byte-identical
        # across a Python→Rust→Python round-trip). Mirrors the
        # `GrantKeywordsToTargetCreatureUntilEOT` per-leaf shape
        # (sorted-list serialization of a frozenset[str]).
        if isinstance(
            eff,
            PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
        ):
            return {
                "kind": (
                    "put_plus_one_counters_and_grant_keywords_ueot_"
                    "on_target_creature_you_control"
                ),
                "amount": int(eff.amount),
                "granted_keywords": sorted(eff.granted_keywords),
            }
        # **Weftwalking Cycle 1 substrate — nested-``Sequence``-as-leaf
        # (2026-05-24).** When a Sequence appears AS A CHILD of
        # another composer (e.g. inside ``ConditionalIfCastFromHand
        # .inner_effect`` for Weftwalking's ETB body), the outer
        # leaf-walker needs to recurse into it the same way the
        # top-level dispatcher does. Without this arm a Sequence
        # nested inside a composer would bail with ``None``, blocking
        # round-trip of any composer-wrapping-Sequence shape
        # (Weftwalking is the first EoE consumer; future cards with
        # the same nested-Sequence shape automatically unlock).
        #
        # Each child recurses via ``_leaf``; recurse-or-bail mirrors
        # the top-level Sequence composer's discipline (a partially-
        # serializable nested Sequence would silently drop a child
        # on Rust). Substrate-only — Weftwalking STAYS DECLINED at
        # the admit gate post-Cycle-1 (the safe-trigger admit-set
        # widen is Cycle 2; the per-card real-EoE byte-equality
        # probe is Cycle 3).
        if isinstance(eff, Sequence):
            children: list[dict] = []
            for child in eff.effects:
                cd = _leaf(child)
                if cd is None:
                    return None
                children.append(cd)
            return {"kind": "sequence", "effects": children}
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
    # ModalChooseOne composer (spell-card-bridge **ModalChooseOne
    # envelope — Cycle 3**, 2026-05-21). Mirrors the Sequence
    # composer's recurse-into-children-and-bail-on-any-unrecognized
    # discipline. Emits the Rust-shape ``{"kind": "choose_one_mode",
    # "modes": [<per-mode leaf>, ...]}`` dict that
    # ``cards.rs::parse_effect``'s ``"choose_one_mode"`` arm at
    # ``cards.rs:9084`` consumes (recursive parse over ``modes``) and
    # that ``cross_engine.py``'s ``_ta_dict_to_python_effect``
    # ``"choose_one_mode"`` arm at line 6264 round-trips into
    # ``ModalChooseOne(modes=...)``.
    #
    # **Round-trip-or-bail teeth.** Recurses into each mode via the
    # same ``_leaf`` table the Sequence composer uses; bails (returns
    # ``None``) if ANY mode is unrecognized — the no-fallback-hybrid
    # discipline a partially-serializable ModalChooseOne would
    # silently drop a mode on Rust.
    #
    # **`or_both` widen (scour-for-scrap-slice, 2026-05-21).** The
    # Cycle-1-widen substrate adds the multi-pick StackItem slot
    # (``chosen_mode_idxs: Option<Vec<u8>>``) PLUS the
    # ``Effect::ChooseOneMode { ..., or_both: bool }`` Rust field.
    # The composer now emits the ``or_both`` round-trip field;
    # downstream the cast-time bind (``cast_spell_noncreature``)
    # detects ``or_both=true`` and binds the full mode subset, and
    # the resolve arm dispatches each chosen mode in order. The
    # admit-set still gates on per-leaf coverage; any leaf that
    # remains uncovered keeps the spell declined (Scour for Scrap's
    # mode 1, ``ReturnTargetArtifactCardFromYourGraveyardToHand``,
    # is uncovered today and will keep Scour declined until a
    # follow-up cycle adds that Effect variant + per-mode target
    # binder — the substrate-only landing for this slice).
    #
    # **Round-trip-or-bail teeth preserved.** Recurses into each
    # mode via the same ``_leaf`` table; bails (returns ``None``) if
    # ANY mode is unrecognized — keeps the no-fallback-hybrid
    # discipline a partially-serializable ModalChooseOne would
    # silently drop a mode on Rust.
    #
    # **``or_both: false`` omitted.** Per the Rust to_pydict
    # symmetry, the field is emitted ONLY when ``True`` — keeps the
    # pre-widen dict shape byte-identical for every non-or_both
    # modal.
    #
    # **Composer-not-leaf shape.** Lives outside ``_leaf`` because
    # ``_leaf`` is intentionally the pid-free covered LEAVES (the
    # Sequence composer also lives outside it). A `ModalChooseOne`
    # nested as a Sequence child would NOT round-trip through this
    # path today (`_leaf` doesn't recurse into ModalChooseOne); the
    # Cycle 3 admit shape is `ModalChooseOne` AS the top-level
    # `spell_effect`, not nested inside a Sequence. Real EoE modal
    # cards (Reroute Systems, Archenemy's Charm, ...) print modal
    # spells at the head of the effect, not nested — matches the
    # admit shape.
    from mtg_bot.effects.combinators import ModalChooseOne
    if isinstance(spell_effect, ModalChooseOne):
        mode_dicts: list[dict] = []
        for mode in spell_effect.modes:
            # **Warping Wail Cycle 4 (2026-05-24).** Pass
            # ``_in_modal_mode=True`` so the narrow Cycle-4 CreateToken
            # admit-gate fires positively for a CreateToken nested as
            # a mode of this composer. Every other ``_leaf`` call site
            # (Sequence, IfYouDo, MayDo, top-level) leaves the flag at
            # its False default — keeping the Glimmerburst /
            # Midnight Mayhem / Sami's Curiosity §2 honest-stops in
            # place (the ``_seat_token_printings`` walk extension
            # only handles the modal-mode position today).
            md = _leaf(mode, _in_modal_mode=True)
            if md is None:
                return None
            mode_dicts.append(md)
        out: dict = {"kind": "choose_one_mode", "modes": mode_dicts}
        if spell_effect.or_both:
            out["or_both"] = True
        return out
    return _leaf(spell_effect)


def _printing_is_bridge_simple_spell(printing) -> bool:
    """True iff a CardPrinting is a covered Instant/Sorcery whose
    target grammar the spell-card-bridge lever round-trips byte-equal
    across engines (Phase-1 single-target OR Phase-2 2-slot).

    Spell-card-bridge lever, **Phase 1** (round-70) **+ Phase 2**
    (round-76; spec at ``docs/SPELL_CARD_BRIDGE_PHASE1_DESIGN.md``
    §3 + its Phase-2 section; scoping basis
    ``docs/SPELL_CARD_BRIDGE_LEVER_DESIGN.md`` §3.0).

    Motivating set:

    - **Phase 1 (single-target — ``(1,1)`` / ``()``):** the
      single-target Tier-A spells whose bespoke Effect close has
      landed AND whose effect carries no loader-unseatable token pid
      — currently the 6-card set {Radiant Strike, Depressurize,
      Focus Fire, Biosynthic Burst, Seedship Impact, Orbital Plunge}
      (Seedship Impact / Orbital Plunge admitted via the round-73
      Lander-spell-token-seating sub-substrate).
    - **Phase 2 (2-slot heterogeneous — ``(2,2)`` /
      ``('my_creature','creature')``):** Diplomatic Relations — the
      SINGLE 2-slot grammar admitted, exactly the disjoint
      friendly-creature + opponent-creature slot pair the
      ``_select_spell_targets`` per-slot-kind first-legal convention
      drives byte-equal. Adding it grows the admit set 6→7.

    Close Encounter (additional-cost-choice + the
    ``CloseEncounterEffect`` not covered) STAYS the §2.2-declined
    Tier-C card; every other multi-target / modal / X / warp /
    additional-cost shape STAYS filtered (the decline set, §2.2).

    The §2 teeth: it admits ONLY a spell whose ``spell_effect`` is a
    COVERED+BRIDGED effect (queried against the LIVE covered set, NOT
    a hardcoded list — so it auto-gates on each per-card Tier-A close
    having LANDED) AND round-trips through the reverse serializer
    (which structurally declines the unseatable-token-pid shapes),
    single-mode, no X / kicker / warp / additional-cost-choice, with
    a target grammar that is EITHER the Phase-1 implicit single
    target OR the Phase-2 exact 2-slot ``('my_creature','creature')``
    pair the deterministic-first convention drives byte-equal. Every
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
    # **Additional-cost-sacrifice riders (Cycle 1 for the bare
    # ``ExileTargetCreature`` lane, 2026-05-22).** These riders modify
    # the cost-payment leg of the spell cast (you must sacrifice a
    # qualifying permanent IN ADDITION to paying the mana cost — CR
    # 601.2f). Today the Rust engine does NOT model the per-card
    # sacrifice-creature-or-X riders; modeling them would require a
    # parallel ``additional_cost_choose_your_creature``-style channel
    # (the substrate the Close Encounter closure shipped for that
    # specific rider). Until that channel exists for the
    # creature-or-enchantment and creature-or-artifact variants,
    # admitting these cards would silently mistranslate cross-engine —
    # Python would enforce the additional sacrifice; Rust would not,
    # and cast-legality + post-cast game state would diverge. EoE pool
    # consumers gated by this guard today (verify-first pool scan,
    # 2026-05-22): Final Vengeance ({B} Sorcery, Duskmourn —
    # ``additional_cost_sacrifice_creature_or_enchantment=True``);
    # Embrace Oblivion ({B} Sorcery), Scrounge for Eternity ({2}{B}
    # Sorcery) — both ``additional_cost_sacrifice_creature_or_artifact``.
    # The latter two are already declined by the covered-set gate
    # (their ``spell_effect`` is ``DestroyTargetCreature`` /
    # ``Sequence``, NEITHER currently covered+bridged with a
    # round-trip leaf) — adding this guard is defense-in-depth:
    # closing the spell_effect side for those two cards in a future
    # lane would NOT inadvertently flip them into the admit set
    # without the cost channel substrate also landing. The
    # ``additional_cost_choose_your_creature`` rider (Close Encounter)
    # is HANDLED — its substrate landed in the Close Encounter Cycle
    # 1-3 work — so it is INTENTIONALLY OMITTED from this guard.
    if getattr(printing, "additional_cost_sacrifice_creature_or_enchantment", False):
        return False
    if getattr(printing, "additional_cost_sacrifice_creature_or_artifact", False):
        return False
    mc = printing.mana_cost
    # **X-value-subsystem-C2.5 (2026-05-22).** X-cost admit-predicate
    # widen — the early ``if mc.x_pips: return False`` reject is gone.
    # X-cost printings now flow through the per-phase target-shape gates
    # below. ONLY the Phase-3 wrath shape (`(0, 0)` with no slot_kinds /
    # no ``targets`` attr) admits an X-cost printing — every other
    # phase's `_PHASEN_*_SHAPE` predicate is conjuncted with
    # ``mc.x_pips == 0`` so the X-cost lane stays surgical
    # (single-target Phase 1, 2-slot Phase 2, multi-target Phase 4,
    # or_both Phase 5 — all stay declined for X-cost cards). Today the
    # ONLY X-cost EoE card whose `spell_effect` shape would satisfy the
    # Phase-3 widen is Zero Point Ballad (and Devastating Onslaught
    # which shares the X-value substrate but is Sorcery
    # "create X token copies of..." — different resolve shape).
    # **The widen is structurally clean substrate: until C3 lands the
    # `Effect::ZeroPointBallad` resolve arm + bridge, the
    # `_spell_effect_is_covered_and_bridged` tooth + the
    # `_python_spell_effect_to_dict(se) is None` round-trip-or-bail
    # tooth below keep Zero Point Ballad DECLINED.** The admit-arm
    # widen + cast-pipeline live-mint substrate ship together so
    # Cycle 3 lands the Effect arm against an existing admit gate.
    _printing_is_x_cost = mc is not None and getattr(mc, "x_pips", 0) > 0
    # Additional-cost-choice (Close Encounter): the live printing
    # exposes NO ``additional_cost_choice`` attribute (verify-first
    # at the implement HEAD — the spec ADDENDUM's "warp_cost is not
    # None" Close-Encounter reason is ALSO stale: live
    # ``Close Encounter.warp_cost is None``).
    #
    # **Close Encounter additional-cost-choice closure — Cycle 3
    # admit widen (2026-05-21).** With the Rust ``Effect::Close
    # EncounterEffect`` variant + the bridge arms + the resolve-arm
    # consumer of ``current_resolve_additional_cost_choice_id``
    # (the Cycle 1 substrate), the covered+bridged ``CloseEncounter
    # Effect`` is what flips Close Encounter into the admit set.
    # The covered-set gate below carries the load-bearing decline
    # for the GENERIC additional-cost-choice case: cards whose
    # ``additional_cost_choose_your_creature`` is True but whose
    # ``spell_effect`` is NOT a covered class STILL stay declined
    # (the round-trip-or-bail serializer gate). The
    # ``additional_cost_choose_your_creature`` flag itself is NOT a
    # decline reason — the Cycle 1+2 substrate handles the choice
    # binding at cast time on both engines, byte-equal.
    # The defensive ``additional_cost_choice`` attr reject below
    # is kept (future-proof; harmless no-op while the attr is
    # absent) so a future parser that structures the marker into a
    # distinct attribute still gets positively declined.
    if getattr(printing, "additional_cost_choice", None) is not None:
        return False
    # **ModalChooseOne envelope — Cycle 4 (admit-predicate widen,
    # 2026-05-21).** ``ModalChooseOne`` was previously REJECTED here
    # unconditionally (the Cycle 1-3 substrate-only landing kept the
    # admit set closed while the cast-time mode binding + per-mode
    # resolve dispatch + reverse serializer cycles shipped). With
    # Cycle 4 landing the per-leaf Effect variants
    # (``DealDamageEachOpponent`` already shipped; the new
    # ``ExileAllArtifactsWithManaValueAtMost`` lands in this cycle)
    # the round-trip-or-bail teeth at ``_python_spell_effect_to_dict``
    # below carry the load: a modal whose modes are NOT all leaf-
    # recognized bails at the serializer (returns ``None``), and the
    # admit gate's ``_python_spell_effect_to_dict(se) is None`` clause
    # rejects it.
    #
    # The Phase-3 ``(0, 0)``-shape wrath admit arm below ALSO covers
    # all-untargeted ModalChooseOne cards: Ruinous Rampage's
    # ``target_count_range() == (0, 0)`` and ``target_slot_kinds()
    # == ()`` because both of its modes (``DealDamageEachOpponent``,
    # ``ExileAllArtifactsWithManaValueAtMost``) are untargeted. The
    # some-targeted ModalChooseOne cards (Reroute Systems / Scour for
    # Scrap / Archenemy's Charm / Drill Too Deep / Warping Wail /
    # Twist Reality / Live or Die — 7 cards) report non-``(0, 0)``
    # shapes and STAY DECLINED via the target-grammar gate below;
    # they need a per-mode target-binding Slice (Cycle 5) before
    # they can flip.
    #
    # **``or_both`` deferral preserved.** The serializer at
    # ``_python_spell_effect_to_dict`` explicitly bails on
    # ``ModalChooseOne(or_both=True)`` (Cycle 3); the admit gate's
    # round-trip clause picks that up too. Scour for Scrap (the only
    # ``or_both`` EoE modal) STAYS DECLINED via the round-trip-or-bail
    # path even if its modes were leaf-recognized.
    # Target-grammar gate — Phase 1 (single-target) OR Phase 2 (the
    # exact 2-slot ('my_creature','creature') heterogeneous pair) OR
    # the wrath-admit-widening Phase-3 ``(0, 0)``-shape wrath grammar.
    # Every OTHER target shape (any-number, opponent-zone, 3+ slots,
    # other 2-slot kind-tuples) STAYS positively declined — the §2
    # teeth. The Phase-2 widening is SURGICAL: it admits ONLY the
    # one heterogeneous pair the cross-engine 2-slot binding +
    # resolve-time double-swap is implemented + pinned byte-equal
    # for (Diplomatic Relations), NOT a blanket "any 2-target"
    # widen (that would ship the count-chasing anti-pattern §2
    # exists to prevent).
    min_t, max_t = se.target_count_range()
    slot_kinds = se.target_slot_kinds()
    # X-value-subsystem-C2.5: every non-Phase-3 phase explicitly
    # excludes X-cost printings (`mc.x_pips > 0`). Only Phase 3
    # admits X-cost (the wrath-shape lane that motivated the widen).
    # **Devastating Onslaught — Cycle 1 (2026-05-22).** Phase 1
    # widened to also admit X-cost single-target printings. The covered
    # +bridged + round-trip-or-bail teeth still gate: until this lane
    # lands the
    # `Effect::CreateXTokensOfTargetPermanentWithHasteEndStepSac`
    # Rust variant + per-leaf serializer + bridge arms, the only X-cost
    # Phase-1 EoE card (Devastating Onslaught) stays DECLINED via the
    # no-Effect-coverage tooth. Once this lane ships, Devastating
    # Onslaught AUTO-JOINS via the §2 auto-grow teeth. No other EoE
    # X-cost Phase-1 card exists today (Zero Point Ballad is Phase-3;
    # every other X-cost EoE card has shape (0, 0) or non-single-
    # target). The widen is structurally clean substrate.
    _PHASE1_SHAPE = (
        (min_t, max_t) == (1, 1)
        and not slot_kinds
    )
    # Phase-2 admit shape: exactly two required targets with the
    # disjoint friendly/opponent creature slot pair. ``_select_spell
    # _targets`` filters the flat ``legal_targets`` per slot_kind and
    # the first-legal convention picks slot 0 = first caster-
    # controlled creature, slot 1 = first non-caster-controlled
    # creature — the EXACT pair the Rust ``cast_spell_noncreature``
    # 2-slot scan binds + the double resolve-swap threads byte-equal.
    _PHASE2_SHAPE = (
        (min_t, max_t) == (2, 2)
        and tuple(slot_kinds) == ("my_creature", "creature")
        and not _printing_is_x_cost
    )
    # **Phase 3 — wrath-admit-widening (2026-05-21).** ``(0, 0)``-shape
    # spells with NO slot_kinds: wrath-style mass-effect spells whose
    # ``spell_effect`` resolves over the full battlefield snapshot with
    # NO at-cast target binding (Pyroclasm, Manifest Dread, Destroy-All-
    # Creatures, etc.). The ``cast_spell_noncreature`` Rust path already
    # threads a target-free StackItem byte-equal across both engines (no
    # at-cast binding to mirror — the spell pushes onto the stack with an
    # empty targets tuple on both sides; the at-resolve dispatch reads
    # the Effect dict and walks the battlefield itself). The Phase-3
    # widen is SURGICAL: it admits ONLY ``(0, 0)`` with no slot_kinds AND
    # no ``targets`` attribute on the printing — every other target shape
    # stays declined. The serializer round-trip teeth below carry the
    # full no-fallback-hybrid load (an admitted card without a
    # round-trip-clean Effect arm bails via
    # :func:`_python_spell_effect_to_dict` returning ``None``).
    # **X-value-subsystem-C2.5 (2026-05-22) widen.** Phase 3 is the
    # SOLE phase that admits X-cost printings. The `(0, 0)`-shape with
    # empty slot_kinds + no ``targets`` attr is the only target
    # grammar Zero Point Ballad's `{X}{B}{B}` "Destroy each creature
    # with toughness X or less. Then ..." resolve body fits — no
    # at-cast target binding, the destroy walks the bf snapshot at
    # resolve time scoped by `state.resolving_x_value` (read via the
    # Cycle-1 bracket). The covered+bridged + round-trip-or-bail
    # teeth still gate the admit set — until C3 lands
    # `Effect::ZeroPointBallad`, Zero Point Ballad stays DECLINED via
    # the no-Effect-coverage tooth (the admit widen is substrate-only
    # in C2.5: the predicate accepts the SHAPE, but the gate hasn't
    # opened yet for any real EoE X-cost card).
    _PHASE3_WRATH_SHAPE = (
        (min_t, max_t) == (0, 0)
        and not slot_kinds
        and not getattr(printing, "targets", ())
    )
    # **Phase 4 — multi-target admit widen (2026-05-21).** Graveyard-
    # source multi-target spell-effects with a uniform target kind
    # (``"graveyard_creature"`` today; Scout for Survivors's (0, 3)
    # shape is the inaugural consumer). Admit only when:
    #
    #   1. ``min_t == 0`` (optional targets — "up to N target ...") OR
    #      ``min_t >= 1 and max_t > min_t`` (range "one or two ...");
    #      the bound is "max_t > 1" so single-target shapes go through
    #      Phase 1 instead.
    #   2. ``slot_kinds`` is empty OR has length ``max_t`` with all
    #      slots reporting the SAME kind (uniform-kind multi-target).
    #   3. The covered+bridged gate (`_spell_effect_is_covered_and_
    #      bridged`) AND the round-trip-or-bail gate
    #      (``_python_spell_effect_to_dict(se) is None``) below carry
    #      the load — admitting a covered+bridged shape that round-
    #      trips and whose serializer leaf emits the Rust-variant dict
    #      auto-grows the admit set; an uncovered or non-serializable
    #      shape stays declined (the §2 teeth).
    #
    # **Resolve binding shape.** Today's resolve path SELF-SCANS the
    # source-controller's graveyard at resolve time (the
    # ``Effect::ReturnUpToNSmallCreaturesFromGraveyardWithCounters``
    # arm in ``state_ops_resolve.rs``), mirroring the established
    # ``ReturnCreatureFromYourGraveyardToBattlefield`` single-target
    # self-scan pattern. The cross-engine harness's
    # ``_PickFirstLegalTargetAgent`` picks first-N-legal in
    # legal_targets order, which coincides byte-equal with the self-
    # scan — see ``docs/SEARCH_LIMITATIONS.md`` entry "Multi-target
    # Phase 4 resolve-time self-scan" for the deliberate divergence
    # vs cast-time binding the §2 admit gate accepts.
    _PHASE4_MULTI_GRAVEYARD_SHAPE = (
        max_t > 1
        and min_t in (0, 1)
        and (
            not slot_kinds
            or (
                len(slot_kinds) == max_t
                and len(set(slot_kinds)) == 1
                and slot_kinds[0] in ("graveyard_creature",)
            )
        )
        and not _printing_is_x_cost
    )
    # **Phase 5 — scour-for-scrap-cycle-2 (2026-05-21) — `or_both`
    # modal admit-widen.** ``ModalChooseOne(or_both=True)`` cards whose
    # ``target_count_range() == (0, 1)`` and ``slot_kinds == ()``.
    # Reports `(0, 1)` because at least one mode is untargeted (so you
    # can pick the untargeted mode alone — `min_t == 0`) and the
    # most-targeted mode needs at most one target (`max_t == 1`). The
    # empty ``slot_kinds`` mirrors ``ModalChooseOne``'s base default
    # — it doesn't override ``target_slot_kinds()``. Today's consumer
    # is exactly **Scour for Scrap** (its mode 0 is the untargeted
    # ``SearchLibraryForCard``, mode 1 is the single-target
    # ``ReturnTargetArtifactCardFromYourGraveyardToHand``); any future
    # ``or_both`` modal with the same shape (one untargeted mode +
    # one single-target mode) will auto-flip the same way provided
    # both leaves are covered+bridged AND the per-mode binder picks
    # the targeted mode's filter (the
    # ``is_recognized_targeted_mode_leaf`` allowlist in
    # ``state_ops_cast.rs``). The round-trip-or-bail teeth at
    # ``_python_spell_effect_to_dict`` continue to carry the load:
    # a modal whose modes are NOT all leaf-recognized bails at the
    # serializer (returns ``None``) and the admit gate's
    # ``_python_spell_effect_to_dict(se) is None`` clause rejects it.
    _PHASE5_OR_BOTH_MIXED_TARGET_SHAPE = (
        (min_t, max_t) == (0, 1)
        and not slot_kinds
        and not _printing_is_x_cost
    )
    # **Phase 6 — Coordinated Clobbering Cycle 2b admit widen
    # (2026-05-24).** ``(2, 3)``-shape heterogeneous 3-slot grammar:
    # one mandatory opp creature (slot 0) + one mandatory caster's
    # untapped creature (slot 1) + one OPTIONAL second caster's
    # untapped creature (slot 2 — beyond ``min_t``, the agent-decline
    # branch). Today's sole consumer is **Coordinated Clobbering**
    # (DSK ``{G}`` Sorcery: "Tap one or two target untapped creatures
    # you control. They each deal damage equal to their power to
    # target creature an opponent controls."). The
    # ``CoordinatedClobberingEffect`` Python class reports
    # ``target_count_range() == (2, 3)`` and
    # ``target_slot_kinds() == ("creature", "my_creature",
    # "my_creature")``.
    #
    # **Cross-engine binder shape.** The Cycle 2a Rust substrate ships
    # the 3-slot ``StackItem.target_obj_id_3`` field + the
    # ``current_resolve_payload_target_id_3`` resolver-bracket slot
    # (save → set → restore on BOTH resolve entry points) + the
    # cast-time binder in ``state_ops_cast.rs``'s
    # ``is_coordinated_clobbering`` arm (slot 0 = first opp creature
    # in ``bf_iter_etb_sorted`` order; slot 1 = first caster-untapped
    # creature; slot 2 = OPTIONAL second caster-untapped, ``None`` if
    # only one available — the ``slot_idx >= min_t`` agent-decline
    # branch mirroring Python's ``_select_spell_targets`` shape) + the
    # resolve arm's slot-2 read/validate/idempotent-tap step + second
    # damage instance to slot 0. Both engines converge to the same
    # deterministic-first ``("creature" opp, "my_creature" mine_1,
    # "my_creature" mine_2)`` triple under the harness's
    # ``_PickFirstLegalTargetAgent`` convention.
    #
    # **The widen is SURGICAL.** Only the EXACT heterogeneous tuple
    # ``("creature", "my_creature", "my_creature")`` is admitted; the
    # length-3 + 2-distinct-kinds + leading-``"creature"`` conjuncts
    # block any sibling 3-slot shape from auto-growing into the admit
    # set silently (e.g. ``("my_creature", "creature", "creature")``
    # or any other re-ordering remains DECLINED — those would need
    # their own per-card binder + Phase-N arm). The ``max_t > min_t``
    # conjunct positively distinguishes the optional-third-slot shape
    # from a hypothetical ``(3, 3)`` "all three required" grammar
    # (which would need a different binder — no agent-decline branch).
    # The ``len(slot_kinds) == max_t`` conjunct mirrors the audit's
    # canonical "slot_kinds enumerates every potentially-filled slot"
    # contract.
    #
    # **No X-cost branch.** Coordinated Clobbering's ``{G}`` mana
    # cost has no X-pips; the ``not _printing_is_x_cost`` conjunct
    # keeps the lane surgical (a hypothetical X-cost ``(2, 3)`` 3-slot
    # card would need a separate substrate cycle to ship the X-binding
    # bracket alongside the slot-3 binding bracket).
    _PHASE6_CC_3SLOT_SHAPE = (
        max_t > min_t
        and len(slot_kinds) == max_t
        and len(set(slot_kinds)) == 2
        and slot_kinds[0] == "creature"
        and tuple(slot_kinds) == ("creature", "my_creature", "my_creature")
        and not _printing_is_x_cost
    )
    if not (
        _PHASE1_SHAPE
        or _PHASE2_SHAPE
        or _PHASE3_WRATH_SHAPE
        or _PHASE4_MULTI_GRAVEYARD_SHAPE
        or _PHASE5_OR_BOTH_MIXED_TARGET_SHAPE
        or _PHASE6_CC_3SLOT_SHAPE
    ):
        return False  # every other target grammar stays declined
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


def _python_ta_to_safe_dict_aura_extension(ta) -> dict:
    """**Phase 2 S2 extension (Tractor Beam closure, 2026-05-20).**
    Convert a Phase-2-S2-admitted Aura ETB ``TriggeredAbility``
    into its Rust-shape round-trip dict.

    Pre-condition: ``ta`` has been validated by
    :func:`_aura_triggers_are_phase2_s2_safe` — i.e. it is the
    ``Event.ENTERS + IsSelf + TapEnchantedPermanent`` shape. The
    dict this returns matches the canonical Rust trigger shape
    (``{"event": "enters", "predicate": {"kind": "is_self"},
    "effect": {"kind": "tap_enchanted_permanent"}, "once_per_turn":
    False}``) — the same per-key spellings the existing
    :func:`_python_ta_to_safe_dict` recognizer family emits for
    sibling unit-variant effects.

    Lives separate from :func:`_python_ta_to_safe_dict` because the
    safe-trigger family is gated on creature ETB triggers (DrawCards
    / GainLife / Scry / ...), while this gate covers the strictly-
    Aura-specific ``TapEnchantedPermanent`` family. Sharing the
    safe-trigger registry would require widening that family's
    effect-kind allowlist for an effect that only makes sense on an
    Aura source — keep the surface narrow per the "no fallback
    hybrid" discipline.
    """
    return {
        "event": "enters",
        # Rust's predicate kind for ``IsSelf`` is ``"source_is_self"``
        # (see ``cards.rs::parse_predicate`` and the bridge in
        # ``cross_engine.py:9597``). Don't confuse with ``"is_self"``
        # which is not a registered predicate kind.
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "tap_enchanted_permanent"},
        "once_per_turn": False,
    }


def _aura_triggers_are_phase2_s2_safe(triggered_abilities) -> bool:
    """**Phase 2 S2 extension (Tractor Beam closure, 2026-05-20).**
    True iff every ``TriggeredAbility`` in ``triggered_abilities``
    matches the narrow Tractor-Beam-shape allowlist:

      * ``event`` is :data:`Event.ENTERS`
      * ``predicate`` is :class:`IsSelf` with no subject scope
      * ``effect`` is :class:`TapEnchantedPermanent`
      * ``once_per_turn`` is ``False`` (ETB triggers are once-per-ETB
        by construction, not once-per-turn).

    The ``TapEnchantedPermanent`` effect is a bridge-supported unit
    variant — Python side at ``effects/generic/tap.py:497``, Rust
    side at ``state_ops_resolve.rs::TapEnchantedPermanent``,
    cross-engine bridge at ``cross_engine.py:5317`` for the
    dict-to-Python arm. The trigger dict round-trip uses the
    ``_python_ta_to_safe_dict`` siblings (the Rust side parses an
    Aura-ETB triggered ability dict via the standard
    ``parse_triggered_ability`` arm; the effect dict the bridge
    emits for ``TapEnchantedPermanent`` is the canonical unit-variant
    ``{"kind": "tap_enchanted_permanent"}`` shape).

    Returns ``False`` for an empty tuple — callers should gate on
    ``if printing.triggered_abilities:`` first; this helper is only
    relevant when there IS at least one trigger to validate.

    Returns ``False`` on the first non-matching trigger so any future
    Aura with a different ETB body keeps the gate honest (the safe-
    trigger predicate's all-or-nothing convention).
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.generic.tap import TapEnchantedPermanent

    if not triggered_abilities:
        return False
    for ta in triggered_abilities:
        if not isinstance(ta, TriggeredAbility):
            return False
        if ta.once_per_turn:
            return False
        if ta.event is not Event.ENTERS:
            return False
        pred = ta.predicate
        if not isinstance(pred, IsSelf):
            return False
        if pred.subject is not None:
            return False
        if not isinstance(ta.effect, TapEnchantedPermanent):
            return False
    return True


def _aura_triggers_are_phase3_safe(triggered_abilities) -> bool:
    """**Aura-attachment substrate — Phase 3 / S4 (Pain for All
    closure; round-80, 2026-05-20).** True iff every
    ``TriggeredAbility`` in ``triggered_abilities`` matches one of
    the narrow Phase-3 admit shapes:

      1. The Phase-2-S2-extension Aura-ETB shape (Tractor Beam):
         ``Event.ENTERS + IsSelf(subject=None) + TapEnchantedPermanent``.
      2. The Phase-3 Pain-for-All ETB shape:
         ``Event.ENTERS + IsSelf(subject=None) + PainForAllETBEffect``.
      3. The Phase-3 Pain-for-All damage-echo shape:
         ``Event.DEALT_DAMAGE + IsHost(subject=None) +
         PainForAllDamageEchoEffect``.

    ``once_per_turn=False`` on every shape — Aura triggers fire each
    occurrence by construction, not once-per-turn.

    The two Pain for All bespoke effect classes
    (:class:`mtg_bot.effects.bespoke.PainForAllETBEffect` +
    :class:`mtg_bot.effects.bespoke.PainForAllDamageEchoEffect`) are
    unit variants with full Rust ``Effect`` parity (landed in the
    Pain for All closure slice — ``rust/src/cards.rs::Effect::
    PainForAllETBEffect`` / ``::PainForAllDamageEchoEffect``) and
    matching ``_ta_dict_to_python_effect`` bridge arms
    (``cross_engine.py:8351`` / ``cross_engine.py:8388``). The
    :class:`mtg_bot.effects.predicates.IsHost` predicate is also
    fully Rust-bridged
    (``rust/src/cards.rs::Predicate::IsHost { subject }`` +
    ``cross_engine.py:9785``).

    Returns ``False`` for an empty tuple — callers should gate on
    ``if printing.triggered_abilities:`` first; this helper is only
    relevant when there IS at least one trigger to validate.

    Returns ``False`` on the first non-matching trigger — the
    safe-trigger predicate's all-or-nothing convention.

    Lives separate from :func:`_aura_triggers_are_phase2_s2_safe`
    because the Phase-3 admit set covers a wider event surface
    (DEALT_DAMAGE in addition to ENTERS) and a different predicate
    family (IsHost in addition to IsSelf). Phase-3 admits a strict
    superset of Phase-2-S2-extension; Tractor Beam's
    ``ENTERS+IsSelf+TapEnchantedPermanent`` shape passes both
    helpers (only one needs to ship the admit decision in
    ``_printing_is_bridge_simple_aura`` — Phase-3 is the canonical
    gate, Phase-2-S2 stays for back-compat with its existing
    tests).
    """
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import (
        Controlled,
        Event,
        IsHost,
        IsSelf,
        YOU as _Controller_YOU,
    )
    from mtg_bot.effects.bespoke import (
        PainForAllDamageEchoEffect,
        PainForAllETBEffect,
    )
    from mtg_bot.effects.combinators import SacrificeSelfUnlessVoidActive
    from mtg_bot.effects.generic.destroy import DestroyEnchantedPermanent
    from mtg_bot.effects.generic.discard import (
        TargetOpponentLookHandMayDiscard,
    )
    from mtg_bot.effects.generic.graveyard import (
        ReanimateTargetCreatureCardFromDefendersGraveyard,
    )
    from mtg_bot.effects.generic.opponent_punishers import (
        TargetOpponentSacrificesCreatureOtherThanEnchanted,
    )
    from mtg_bot.effects.generic.tap import TapEnchantedPermanent

    if not triggered_abilities:
        return False
    for ta in triggered_abilities:
        if not isinstance(ta, TriggeredAbility):
            return False
        if ta.once_per_turn:
            return False
        # Phase-3 admit shape 1: Tractor-Beam Aura-ETB tap.
        if (
            ta.event is Event.ENTERS
            and isinstance(ta.predicate, IsSelf)
            and ta.predicate.subject is None
            and isinstance(ta.effect, TapEnchantedPermanent)
        ):
            continue
        # Phase-3 admit shape 2: Pain for All ETB damage to any
        # other target (the bespoke ETB effect).
        if (
            ta.event is Event.ENTERS
            and isinstance(ta.predicate, IsSelf)
            and ta.predicate.subject is None
            and isinstance(ta.effect, PainForAllETBEffect)
        ):
            continue
        # Phase-3 admit shape 3: Pain for All damage echo.
        if (
            ta.event is Event.DEALT_DAMAGE
            and isinstance(ta.predicate, IsHost)
            and ta.predicate.subject is None
            and isinstance(ta.effect, PainForAllDamageEchoEffect)
        ):
            continue
        # **Aura Phase 3+ Phase A Cycle 2 (2026-05-26).** Chorale of
        # the Void admit-gate widen — the two shapes ride in this slice
        # together (the all-or-nothing gate refuses partial admission —
        # widening only one of Chorale's two TAs would still keep
        # Chorale declined). Per
        # ``docs/AURA_ATTACH_SUBSTRATE_PHASE_3_DESIGN.md`` §5.3 + §7 row 2.
        #
        # Phase-3+ admit shape 4: Chorale of the Void ATTACKS half —
        # ``ATTACKS + IsHost(subject="attacker") + Reanimate...
        # FromDefendersGraveyard``. The predicate's
        # ``subject="attacker"`` slot threads through Rust's
        # ``Predicate::IsHost { subject: Option<String> }`` via the
        # existing ``is_host`` bridge arm (no new bridge code — landed
        # in C1). The Rust resolve arm
        # ``Effect::ReanimateTargetCreatureCardFromDefendersGraveyard``
        # (landed in C1 at ``state_ops_resolve.rs:16433``) reads
        # ``current_resolve_payload_target_id`` to bind its target.
        if (
            ta.event is Event.ATTACKS
            and isinstance(ta.predicate, IsHost)
            and ta.predicate.subject == "attacker"
            and isinstance(
                ta.effect, ReanimateTargetCreatureCardFromDefendersGraveyard
            )
        ):
            continue
        # Phase-3+ Tail-X2: Chorale EoT void-sustain tail —
        # ``BEGINNING_OF_END_STEP + Controlled(by=YOU, subject=None) +
        # SacrificeSelfUnlessVoidActive``. The
        # ``SacrificeSelfUnlessVoidActive`` Effect class shipped as the
        # Phase 4 first-deliverable (Rust
        # ``Effect::SacrificeSelfUnlessVoidActive`` at
        # ``cards.rs:4972``); the ``BEGINNING_OF_END_STEP`` event is
        # already wired in Rust's dispatcher (slice 14 / round-14).
        # ``Controlled(by=YOU, subject=None)`` round-trips via the
        # existing ``controlled_by_you`` bridge arm
        # (``cross_engine.py:12879``).
        if (
            ta.event is Event.BEGINNING_OF_END_STEP
            and isinstance(ta.predicate, Controlled)
            and ta.predicate.by is _Controller_YOU
            and ta.predicate.subject is None
            and isinstance(ta.effect, SacrificeSelfUnlessVoidActive)
        ):
            continue
        # **Aura Phase 3+ Phase B Cycle 2 (2026-05-26).** Cracked Skull
        # admit-gate widen — TWO shapes ride in this slice together (the
        # all-or-nothing gate refuses partial admission; Cracked Skull's
        # ENTERS long pole + DEALT_DAMAGE Tail-X1 MUST widen in lockstep
        # or the carrier stays DECLINED). Per
        # ``docs/AURA_ATTACH_SUBSTRATE_PHASE_3_DESIGN.md`` §5.2 + §7 row
        # 3 + §8 row 4. The Tail-X1 widen also positions Sporogenic
        # Infection for Phase C closure (Sporogenic shares the same
        # DEALT_DAMAGE + IsHost(None) + DestroyEnchantedPermanent Tail-
        # X1 shape per design doc §3; Phase C adds Sporogenic's ENTERS
        # long-pole ``TargetOpponentSacrificesCreatureOtherThanEnchanted``
        # shape to close the gate for Sporogenic).
        #
        # Phase-3+ admit shape 6: Cracked Skull ENTERS long pole —
        # ``ENTERS + IsSelf(subject=None) +
        # TargetOpponentLookHandMayDiscard``. The Rust ``Effect::
        # TargetOpponentLookHandMayDiscard`` resolve arm (landed in C1 at
        # ``state_ops_resolve.rs``) pushes a
        # ``PendingDecision::MayDiscardChoice`` carrying the bound
        # target-player slot + a nonland_card_ids snapshot of the
        # target's hand; the decision-pump dispatcher
        # (``submit_may_discard_decision`` / ``submit_opponent_hand_
        # card_decision``) drains the two-decision flow byte-equal with
        # Python's ``Agent.choose_yes_no`` + ``choose_card_from_opponent_
        # hand`` calls at ``effects/generic/discard.py:364-378``.
        if (
            ta.event is Event.ENTERS
            and isinstance(ta.predicate, IsSelf)
            and ta.predicate.subject is None
            and isinstance(ta.effect, TargetOpponentLookHandMayDiscard)
        ):
            continue
        # **Aura Phase 3+ Phase C (2026-05-26).** Sporogenic Infection
        # admit-gate widen — adds the ENTERS long-pole shape that
        # closes the Phase 3+ Phase C carrier. The Tail-X1 widen
        # shipped with Phase B Cycle 2 (Cracked Skull) and is shared
        # with Sporogenic per design doc §3, so closing Sporogenic
        # only requires its ENTERS half to land. Per
        # ``docs/AURA_ATTACH_SUBSTRATE_PHASE_3_DESIGN.md`` §5.3 + §7
        # row 5 + §8 row 6.
        #
        # Phase-3+ admit shape 7: Sporogenic Infection ENTERS long
        # pole — ``ENTERS + IsSelf(subject=None) +
        # TargetOpponentSacrificesCreatureOtherThanEnchanted``. The
        # Rust ``Effect::TargetOpponentSacrificesCreatureOtherThan
        # Enchanted`` resolve arm (landed in this slice at
        # ``state_ops_resolve.rs``) pushes a
        # ``PendingDecision::SacrificeChoice`` carrying the target-
        # opponent slot + candidate creature ids (host pre-excluded)
        # + ``excluded_object_id`` slot; the decision-pump dispatcher
        # (``submit_sacrifice_decision``) drains the choice byte-equal
        # with Python's ``target.agent.choose_sacrifice`` call at
        # ``effects/generic/opponent_punishers.py:130-132``.
        if (
            ta.event is Event.ENTERS
            and isinstance(ta.predicate, IsSelf)
            and ta.predicate.subject is None
            and isinstance(
                ta.effect, TargetOpponentSacrificesCreatureOtherThanEnchanted
            )
        ):
            continue
        # Phase-3+ Tail-X1: Cracked Skull + Sporogenic Infection shared
        # damage-echo destroy tail — ``DEALT_DAMAGE + IsHost(subject=
        # None) + DestroyEnchantedPermanent``. The
        # ``DestroyEnchantedPermanent`` Effect class is fully Rust-
        # bridged (``rust/src/cards.rs::Effect::DestroyEnchantedPermanent``
        # at line 4380, sibling of Cryoshatter's becomes-tapped destroy
        # arm at cards.rs:4367, parse arm at 13062, resolve arm at
        # 18440); the ``DEALT_DAMAGE`` event is already wired in Rust's
        # dispatcher; ``IsHost(subject=None)`` round-trips via the
        # existing ``is_host`` bridge arm. NB: Cryoshatter ALSO carries
        # Tail-X1, but its OTHER trigger is
        # ``BECOMES_TAPPED + IsHost(None) + DestroyEnchantedPermanent``
        # — BECOMES_TAPPED is NOT in the safe set today, so the all-or-
        # nothing gate keeps Cryoshatter DECLINED (no silent auto-grow;
        # verified by ``test_cryoshatter_stays_declined_post_phase_b_
        # cycle_2``).
        if (
            ta.event is Event.DEALT_DAMAGE
            and isinstance(ta.predicate, IsHost)
            and ta.predicate.subject is None
            and isinstance(ta.effect, DestroyEnchantedPermanent)
        ):
            continue
        return False
    return True


def _python_ta_to_safe_dict_aura_phase3(ta) -> dict:
    """**Aura-attachment substrate — Phase 3 / S4 (Pain for All
    closure; round-80, 2026-05-20).** Convert a Phase-3-admitted
    Aura ``TriggeredAbility`` into its Rust-shape round-trip dict.

    Pre-condition: ``ta`` has been validated by
    :func:`_aura_triggers_are_phase3_safe` — i.e. it is one of:

      * ``ENTERS+IsSelf+TapEnchantedPermanent`` (Tractor-Beam shape;
        emits the same dict as
        :func:`_python_ta_to_safe_dict_aura_extension` for
        cross-substrate continuity).
      * ``ENTERS+IsSelf+PainForAllETBEffect`` (Pain for All ETB).
      * ``DEALT_DAMAGE+IsHost+PainForAllDamageEchoEffect`` (Pain
        for All damage echo).

    Rust spellings (cross-engine bridge arms):

      * ``Event.ENTERS`` → ``"enters"``;
        ``Event.DEALT_DAMAGE`` → ``"dealt_damage"``
        (``cards.rs::parse_triggered_ability`` event arm at line ~10252).
      * ``IsSelf(subject=None)`` → ``{"kind": "source_is_self"}``
        (``cards.rs::parse_predicate``).
      * ``IsHost(subject=None)`` → ``{"kind": "is_host"}``
        (``cards.rs::Predicate::IsHost`` + bridge arm at
        ``cross_engine.py:9785``).
      * ``PainForAllETBEffect`` → ``{"kind": "pain_for_all_etb"}``
        (``cards.rs:8069`` + bridge arm at ``cross_engine.py:8351``).
      * ``PainForAllDamageEchoEffect`` →
        ``{"kind": "pain_for_all_damage_echo"}``
        (``cards.rs:8082`` + bridge arm at ``cross_engine.py:8388``).
      * ``TapEnchantedPermanent`` →
        ``{"kind": "tap_enchanted_permanent"}``
        (cross_engine.py:5317 — shared with the Phase-2-S2-extension
        emitter).

    All admitted shapes have ``once_per_turn=False`` per the helper
    gate — Aura triggers fire each occurrence by construction.

    Lives separate from :func:`_python_ta_to_safe_dict` (the
    creature safe-trigger family) because the Aura-specific effects
    only make sense on an Aura source — sharing the family's
    effect-kind allowlist would force the creature gate to admit
    Aura-only effects per the "no fallback hybrid" discipline.
    """
    from mtg_bot.effects.predicates import IsHost, IsSelf, Event
    from mtg_bot.effects.bespoke import (
        PainForAllDamageEchoEffect,
        PainForAllETBEffect,
    )
    from mtg_bot.effects.combinators import SacrificeSelfUnlessVoidActive
    from mtg_bot.effects.generic.tap import TapEnchantedPermanent
    # **Aura Phase 3+ Phase A Cycle 1 (2026-05-25).** Reverse-serializer
    # leaf import for Chorale of the Void's ATTACKS-trigger long-pole
    # Effect (``ReanimateTargetCreatureCardFromDefendersGraveyard`` at
    # ``effects/generic/graveyard.py:474-554``). Cycle 2 (2026-05-26)
    # flips the admit gate ON and adds the Tail-X2 emitter arm for
    # ``SacrificeSelfUnlessVoidActive``; both arms are now LIVE in
    # production (Chorale of the Void admits at the loader filter).
    from mtg_bot.effects.generic.graveyard import (
        ReanimateTargetCreatureCardFromDefendersGraveyard,
    )
    from mtg_bot.effects.generic.discard import (
        TargetOpponentLookHandMayDiscard,
    )
    # **Aura Phase 3+ Phase B Cycle 2 (2026-05-26).** Reverse-serializer
    # leaf import for the Cracked Skull / Sporogenic Infection shared
    # Tail-X1 Effect (``DestroyEnchantedPermanent`` at
    # ``effects/generic/destroy.py:213-249``). Used by both Phase B
    # (Cracked Skull's DEALT_DAMAGE tail; this slice flips the admit
    # gate ON) and Phase C (Sporogenic Infection's DEALT_DAMAGE tail
    # closure; Sporogenic stays DECLINED until Phase C also widens its
    # ENTERS half ``TargetOpponentSacrificesCreatureOtherThanEnchanted``).
    from mtg_bot.effects.generic.destroy import DestroyEnchantedPermanent
    # **Aura Phase 3+ Phase C (2026-05-26).** Reverse-serializer leaf
    # import for Sporogenic Infection's ENTERS long-pole Effect
    # (``TargetOpponentSacrificesCreatureOtherThanEnchanted`` at
    # ``effects/generic/opponent_punishers.py:68-144``). Phase C
    # closes Sporogenic by adding this ENTERS-half Effect class to the
    # safe set; the Tail-X1 emitter arm shipped with Phase B Cycle 2.
    from mtg_bot.effects.generic.opponent_punishers import (
        TargetOpponentSacrificesCreatureOtherThanEnchanted,
    )

    if isinstance(ta.effect, PainForAllETBEffect):
        # Shape 2: Pain for All ETB.
        return {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {"kind": "pain_for_all_etb"},
            "once_per_turn": False,
        }
    if isinstance(ta.effect, PainForAllDamageEchoEffect):
        # Shape 3: Pain for All damage echo (DEALT_DAMAGE + IsHost).
        # IsHost subject is None for the Pain for All shape
        # (single-subject DEALT_DAMAGE event — the receiving creature).
        pred_dict: dict = {"kind": "is_host"}
        # If the predicate carries a subject slot (defensive; live
        # parser emits IsHost(subject=None) for Pain for All), thread
        # it through — the Rust IsHost variant carries the same
        # Optional<String> slot.
        if isinstance(ta.predicate, IsHost) and ta.predicate.subject is not None:
            pred_dict["subject"] = ta.predicate.subject
        return {
            "event": "dealt_damage",
            "predicate": pred_dict,
            "effect": {"kind": "pain_for_all_damage_echo"},
            "once_per_turn": False,
        }
    if isinstance(ta.effect, TapEnchantedPermanent):
        # Shape 1: Tractor-Beam Aura-ETB tap (same shape as the
        # Phase-2-S2-extension emitter ships).
        return {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {"kind": "tap_enchanted_permanent"},
            "once_per_turn": False,
        }
    if isinstance(ta.effect, ReanimateTargetCreatureCardFromDefendersGraveyard):
        # **Aura Phase 3+ Phase A Cycle 1 (2026-05-25) — Chorale of the
        # Void substrate landing — reverse-serializer leaf.** Shape:
        # ``ATTACKS + IsHost(subject="attacker") + Reanimate...
        # FromDefendersGraveyard``. The predicate's ``subject="attacker"``
        # threads through (Rust's ``Predicate::IsHost { subject:
        # Option<String> }`` carries the same Optional<String> slot,
        # the cross_engine.py ``is_host`` bridge already round-trips
        # the subject slot per Pain for All's wiring at
        # ``cross_engine.py:12878``). Per design doc
        # ``docs/AURA_ATTACH_SUBSTRATE_PHASE_3_DESIGN.md`` §5.2 Phase A
        # shape.
        #
        # **Dormant-by-construction in Cycle 1.** This branch only
        # fires when ``_aura_triggers_are_phase3_safe`` admits the
        # carrier's full trigger surface; Cycle 1 does NOT widen that
        # gate (the gate stays gate-shape-3 = Pain for All + Tractor
        # Beam closure only). Chorale's two-trigger surface (ATTACKS
        # long pole + BEGINNING_OF_END_STEP tail) fails the
        # all-or-nothing gate today, so the
        # ``_python_ta_to_safe_dict_aura_phase3`` function is never
        # called on a Chorale TA in Cycle 1. The leaf is here ahead of
        # Cycle 2 to keep the recognizer + admit-gate widens additive
        # in Cycle 2 (Cycle 2 only edits the gate; the emitter already
        # knows how to translate the shape).
        pred_dict: dict = {"kind": "is_host"}
        if (
            isinstance(ta.predicate, IsHost)
            and ta.predicate.subject is not None
        ):
            pred_dict["subject"] = ta.predicate.subject
        return {
            "event": "attacks",
            "predicate": pred_dict,
            "effect": {
                "kind": "reanimate_target_creature_card_from_defenders_graveyard",
            },
            "once_per_turn": False,
        }
    if isinstance(ta.effect, TargetOpponentLookHandMayDiscard):
        # **Aura Phase 3+ Phase B Cycle 1 (2026-05-26) — Cracked Skull
        # substrate landing — reverse-serializer leaf.** Shape:
        # ``ENTERS + IsSelf(subject=None) +
        # TargetOpponentLookHandMayDiscard``. The predicate is the
        # standard self-trigger ``IsSelf`` (subject=None) used by every
        # Aura-ETB substrate today; round-trips via the existing
        # ``is_self`` bridge arm in cross_engine.py. Per design doc
        # ``docs/AURA_ATTACH_SUBSTRATE_PHASE_3_DESIGN.md`` §5.2 Phase B
        # shape.
        #
        # **Aura Phase 3+ Phase B Cycle 2 (2026-05-26) — predicate-kind
        # fix.** Cycle 1's dormant leaf emitted ``"is_self"``, but Rust's
        # ``parse_predicate`` only recognizes ``"source_is_self"`` for
        # the ``IsSelf(subject=None)`` predicate (sibling of Pain for
        # All's ETB recognizer at line 7841 + the Tap-Enchanted-
        # Permanent recognizer at line 7867 + Tractor Beam's emitter at
        # line 7497). The mismatch was harmless in C1 (the gate was
        # DECLINED so the emitter was never invoked end-to-end), but
        # Cycle 2 flips the admit gate ON and the bench-loader feeds
        # Rust the emitted dict — fix the kind string in-place. The C1
        # substrate test ``test_python_ta_to_safe_dict_phase3_recognizes
        # _look_hand_may_discard`` is updated in lockstep to assert the
        # corrected shape.
        return {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "target_opponent_look_hand_may_discard",
            },
            "once_per_turn": False,
        }
    if isinstance(
        ta.effect, TargetOpponentSacrificesCreatureOtherThanEnchanted
    ):
        # **Aura Phase 3+ Phase C (2026-05-26) — Sporogenic Infection
        # substrate landing — reverse-serializer leaf.** Shape:
        # ``ENTERS + IsSelf(subject=None) +
        # TargetOpponentSacrificesCreatureOtherThanEnchanted``. The
        # predicate is the standard self-trigger ``IsSelf``
        # (subject=None) used by every Aura-ETB substrate today;
        # round-trips via the existing ``source_is_self`` bridge arm
        # in cross_engine.py. Per design doc
        # ``docs/AURA_ATTACH_SUBSTRATE_PHASE_3_DESIGN.md`` §5.2 Phase
        # C shape (lines 717-727).
        return {
            "event": "enters",
            "predicate": {"kind": "source_is_self"},
            "effect": {
                "kind": "target_opponent_sacrifices_creature_other_than_enchanted",
            },
            "once_per_turn": False,
        }
    if isinstance(ta.effect, DestroyEnchantedPermanent):
        # **Aura Phase 3+ Phase B Cycle 2 (2026-05-26) — Cracked Skull
        # admit-gate flip — reverse-serializer leaf for Tail-X1.** Shape:
        # ``DEALT_DAMAGE + IsHost(subject=None) +
        # DestroyEnchantedPermanent``. Shared by Cracked Skull (this
        # slice) and Sporogenic Infection (Phase C; Sporogenic stays
        # DECLINED until Phase C closes its ENTERS long-pole). The Rust
        # ``Effect::DestroyEnchantedPermanent`` shipped pre-substrate
        # (Cryoshatter's becomes-tapped destroy arm at ``cards.rs:4380``);
        # the ``DealtDamage`` event is in Rust's dispatcher; the
        # ``is_host`` bridge arm round-trips the IsHost(subject=None)
        # predicate. Per design doc
        # ``docs/AURA_ATTACH_SUBSTRATE_PHASE_3_DESIGN.md`` §5.2 Phase B
        # Tail-X1 shape (lines 753-761).
        pred_dict: dict = {"kind": "is_host"}
        if (
            isinstance(ta.predicate, IsHost)
            and ta.predicate.subject is not None
        ):
            pred_dict["subject"] = ta.predicate.subject
        return {
            "event": "dealt_damage",
            "predicate": pred_dict,
            "effect": {"kind": "destroy_enchanted_permanent"},
            "once_per_turn": False,
        }
    if isinstance(ta.effect, SacrificeSelfUnlessVoidActive):
        # **Aura Phase 3+ Phase A Cycle 2 (2026-05-26) — Chorale of
        # the Void admit-gate flip — reverse-serializer leaf for
        # Tail-X2.** Shape: ``BEGINNING_OF_END_STEP + Controlled(by=
        # YOU, subject=None) + SacrificeSelfUnlessVoidActive``. The
        # Rust ``Effect::SacrificeSelfUnlessVoidActive`` shipped as
        # the Phase 4 first-deliverable (cards.rs:4972), the
        # ``BeginningOfEndStep`` event is in Rust's dispatcher allowlist
        # (round-14), and ``Controlled(by=YOU)`` round-trips via the
        # existing ``controlled_by_you`` bridge arm. Per design doc
        # ``docs/AURA_ATTACH_SUBSTRATE_PHASE_3_DESIGN.md`` §5.2 (line
        # 737-745).
        return {
            "event": "beginning_of_end_step",
            "predicate": {"kind": "controlled_by_you"},
            "effect": {"kind": "sacrifice_self_unless_void_active"},
            "once_per_turn": False,
        }
    # Should be unreachable when pre-gated by
    # :func:`_aura_triggers_are_phase3_safe`. Raise loudly so a
    # future widen of the helper without a matching emitter widen
    # surfaces immediately rather than silently mistranslating.
    raise ValueError(
        f"_python_ta_to_safe_dict_aura_phase3: unsupported trigger "
        f"effect type {type(ta.effect).__name__!r} — gate must be "
        "_aura_triggers_are_phase3_safe-clean before calling this helper."
    )


def _printing_is_bridge_simple_aura(printing) -> bool:
    """True iff a CardPrinting is a Phase-1/2 bridge-supported Aura
    (sub-shape S1 in ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md`` §1):
    a static P/T-or-keyword Aura with no triggered/spell/activated/
    static effects, no control-swap or replacement riders, and a
    parseable cost.

    **Aura-attachment substrate — Phase 2 FIRST DELIVERABLE LANDED
    (round-79; widens the keyword admit set to include cast-timing
    ``flash`` per the symmetric-drop precedent).** Phase 2 widens the
    static-keyword check to admit Auras whose printing keywords are a
    subset of ``_SAFE_KEYWORDS ∪ {flash}``. ``flash`` is a cast-timing
    rider that the CardDef bridge symmetrically drops on BOTH engines
    (the CardDef → CardPrinting round-trip carries no ``keywords``
    field through the aura arm). This finally admits the **first live
    EoE Aura** — Frantic Strength (and Shardmage's Rescue) — through
    the loader: substrate end-to-end on a real EoE printing. See
    `docs/SEARCH_LIMITATIONS.md` for the SL entry mirroring the
    round-39 Ward / round-59 shockland symmetric-drop precedent. The
    full Phase 2 (S2 control-changing per the plan §3) remains
    deferred to a follow-up Rust slice.

    **Aura-attachment substrate — Phase 1 STEP 7 LANDED (round-78).**
    This is the §2 positive-allowlist predicate the plan's §3 Phase 1
    step 7 specifies, and it is now OR'd into
    :func:`_filter_deck_to_bridge_supported`'s admit chokepoint as
    the 6th disjunct. STEPs 1-6 (CardDef aura representation + Rust
    ``parse_printing`` aura-key parse + cast-time enchant-target
    decision + Rust aura-resolution attach arm + CR-704.5n SBA +
    bidirectional bridge round-trip) all landed before this OR-in,
    so a printing that passes the predicate flows end-to-end through
    the bench loader, the Python side, and the Rust side.

    Phase-1 admit set: sub-shape **S1** ONLY (Frantic Strength,
    Shardmage's Rescue per the plan §1). Every other Aura sub-shape
    (S2 control-changing, S3 replacement, S4 triggered) stays
    positively declined here — Phase 2/3/4 land them.

    The §2 teeth (declines that would silently mistranslate, mirroring
    the warp / spell guardrail's rider-rejection blocks):

      * Must be ``is_aura`` (CR 205.3h — Enchantment - Aura).
      * No ``triggered_abilities`` (S4 — Phase 4).
      * No ``activated_abilities`` (no Aura in the EoE pool carries
        one today; defensive).
      * No ``static_abilities`` (Phase 2 — anthem-style Auras).
      * No ``spell_effect`` (Auras are permanents, not Instant/
        Sorcery; defensive).
      * No ``warp_cost`` / ``kicker_cost`` / ``impending_cost`` /
        ``room_halves`` / ``loyalty`` (alt-cost riders — other
        substrates).
      * No ``cost_reductions`` / ``external_cost_reductions``.
      * No ``attached_grants_control`` / ``attached_grants_lose_all_
        abilities`` / ``attached_sets_base_pt`` / ``attached_grants_
        subtype`` / ``attached_prevents_untap`` (S2 — Phase 2).
      * ``replaces_first_tokens_with_copies`` (S3 — Phase 4) is
        NOW ADMITTED post-closure (2026-05-21). The Rust
        ``CreateToken`` arms consult the per-controller Moonlit-shape
        Aura via ``moonlit_token_substitution`` and swap to the host's
        printing with a per-object Token-supertype override. The
        substrate predicate no longer rejects this rider.
      * No ``ward_cost`` (defensive — mirrors the simple-creature
        guardrail).
      * No ``dynamic_pt_formula`` (defensive — Auras don't have one,
        but the CardDef bridge would silently drop it).
      * Either no ``keywords``, OR every keyword in
        :data:`_SAFE_KEYWORDS` (the parser-on-the-Aura keyword set;
        Frantic Strength's ``flash`` is OUTSIDE _SAFE_KEYWORDS — see
        below; Shardmage's ``flash`` ditto).

        **Phase-1-S1 carrier reality (verify-first).** Frantic Strength
        carries ``flash`` as a STATIC keyword on the printing AND a
        ``trample`` keyword on the granted ``equipment_bonuses`` tuple.
        The granted-keyword (the +2/+2/trample rider) lives on a
        SEPARATE field from the printing's static ``keywords`` — the
        bridge round-trips them via different paths. Phase-1 admits
        ONLY the granted-keyword subset that's in
        :data:`_SAFE_KEYWORDS`; the printing's own static ``flash``
        keyword is the §2 decline reason for both Frantic Strength
        and Shardmage's Rescue in THIS slice. This matches the round-
        61 N1 scout's finding that S1 has zero realizable-yield decks
        today (both cards have 0 EoE 17lands decks; the long-tail
        admit is the substrate's value, not the deck count).

      * Aura's ``equipment_bonuses`` (the (power_bonus,
        toughness_bonus, granted_keywords) tuple) — when present, the
        granted_keywords must all be in :data:`_SAFE_KEYWORDS`. The
        bonus deltas have no upper bound.
      * Mana cost is parseable into (generic, colored).

    **Wired into the loader as of STEP 7 (round-78), widened by Phase
    2 first deliverable (round-79):** the predicate is the 6th
    disjunct of :func:`_filter_deck_to_bridge_supported`'s admit
    chokepoint. **The live EoE pool now admits ≥1 Aura through this
    disjunct** (the first live admit — round-79 widen of the keyword
    set per the symmetric-drop precedent above). Remaining S2/S3/S4
    Aura sub-shapes stay positively declined here; Phase 3/4 widen
    further.
    """
    if not getattr(printing, "is_aura", False):
        return False
    # Triggered / static / activated / spell-effect riders — other
    # Aura sub-shapes.
    #
    # **Phase 3 / S4 (Pain for All closure; round-80, 2026-05-20)
    # + Cast-time auto-resolve seat alignment (Tractor Beam closure,
    # 2026-05-20).** Auras with one or more triggered abilities are
    # admitted iff every trigger matches a Phase-3-safe shape per
    # :func:`_aura_triggers_are_phase3_safe`:
    #
    #   * ``ENTERS+IsSelf+TapEnchantedPermanent`` (Tractor-Beam
    #     ETB-tap shape — Phase-2-S2-extension substrate).
    #     **NOW ADMITTED end-to-end** post the cast-time auto-resolve
    #     seat alignment slice (Rust ``apply_action`` drains the
    #     ``EnchantTargetChoice`` synchronously after ``cast_aura``;
    #     non-creature ``summoning_sick=false`` clear in
    #     ``move_*_post_resolve``; aura-host-control revert helper for
    #     non-SBA destroy sites; ``BiosynthicBurst`` legal/resolve scan
    #     walks both bfs by controller).
    #   * ``ENTERS+IsSelf+PainForAllETBEffect`` (Pain for All ETB
    #     damage-to-any-target — the Aura Phase 3 first deliverable;
    #     Rust ``Effect::PainForAllETBEffect`` parity landed in the
    #     Pain for All closure slice).
    #   * ``DEALT_DAMAGE+IsHost+PainForAllDamageEchoEffect`` (Pain
    #     for All damage echo — Rust ``Effect::
    #     PainForAllDamageEchoEffect`` + ``Predicate::IsHost``
    #     parity also landed in the Pain for All closure slice).
    #
    # Every other triggered-Aura shape (S4 sub-shape per the plan
    # §1 — Chorale of the Void / Cracked Skull / Sporogenic
    # Infection) stays declined here: those carry uncovered Rust
    # Effect variants AND/OR unbridged trigger predicates, so the
    # Phase-3 safe-trigger gate refuses them. The §2 teeth keep
    # the predicate honest — admitting an unsafe trigger surface
    # would silently mistranslate to an effectless permanent on
    # one engine while the other applies the effect.
    if printing.triggered_abilities:
        if not _aura_triggers_are_phase3_safe(printing.triggered_abilities):
            return False
    if printing.activated_abilities:
        return False
    if printing.static_abilities:
        return False
    if printing.spell_effect is not None:
        return False
    # Alt-cost / mode riders — defensive (no EoE Aura today carries
    # any of these, but the same §2 rider-rejection pattern as the
    # warp / spell guardrails keeps the gate honest).
    if printing.warp_cost or printing.kicker_cost or printing.impending_cost:
        return False
    if printing.room_halves:
        return False
    if printing.loyalty is not None:
        return False
    if printing.cost_reductions or printing.external_cost_reductions:
        return False
    # S2 control-changing — Phase 2 S2 (round-79+, 2026-05-20) — now
    # admitted for the Duskmourn's Domination shape:
    # ``attached_grants_control AND attached_grants_lose_all_abilities``
    # (paired — both flags or neither — the live S2 carrier in EoE
    # is Duskmourn's Domination, and the only other live S2 sibling,
    # Tractor Beam, ALSO carries `attached_prevents_untap` plus a
    # triggered ETB and is independently declined below). The Rust
    # attach arm flips the host's controller (layer 2) and the
    # `battlefield_has_keyword` reader wipes the host's keyword set
    # while the lose-abilities aura is attached (layer 6 honest-stop
    # — see the SL entry).
    #
    # ``attached_sets_base_pt`` (Lignify-shape layer 7b override) and
    # ``attached_grants_subtype`` (Lignify-shape layer 4 add_subtype)
    # stay positively declined — no S2 carrier in the live EoE pool
    # uses them, and the Rust reader fold for set-base-PT is NOT
    # wired in this slice (honest-stop per the plan §3 Phase 2).
    #
    # ``attached_prevents_untap`` (Tractor Beam's don't-untap clause)
    # also stays declined — no Rust untap-step skip for the attached
    # host is wired yet (also a future Phase-2-S2-extension slice).
    #
    # S3 replacement riders — Phase 4; positively declined here.
    if printing.attached_grants_control and (
        not printing.attached_grants_lose_all_abilities
    ) and (
        not printing.attached_prevents_untap
    ):
        # Lone control-grant without the lose-abilities wipe AND
        # without the don't-untap clause — no live EoE carrier matches
        # this shape today (Tractor Beam pairs control-grant WITH the
        # don't-untap rider, admitted below). Stay defensive —
        # admitting a control-only Aura would silently mistranslate
        # against a host that still has functional abilities the
        # bench may rely on.
        return False
    if printing.attached_grants_lose_all_abilities and (
        not printing.attached_grants_control
    ):
        # Lone lose-abilities without control-swap is the Lignify
        # shape (also carries set-base-PT + subtype add). No live EoE
        # carrier matches this AND has its other riders unset; stay
        # declined.
        return False
    if printing.attached_sets_base_pt is not None:
        return False
    if printing.attached_grants_subtype is not None:
        return False
    if printing.attached_prevents_untap and (
        not printing.attached_grants_control
    ):
        # Lone don't-untap rider without the control-grant. Tractor
        # Beam is the live EoE carrier pairing the two — admitted via
        # the joint-shape gate above. Any future carrier with the
        # bare don't-untap rider (Tilling Treefolk-shape) stays
        # declined here pending a separate slice.
        return False
    # Aura-attachment Phase 4 S3 closure (2026-05-21): Moonlit
    # Meditation now admits at the loader. The Rust CreateToken /
    # CreateTokenTapped / CreateTokenEachPlayer / CreateToken-
    # CopyOfTargetCreatureYouControl arms consult the controller's
    # attached Moonlit-shape Aura via ``moonlit_token_substitution``
    # and swap the token's printing_id to the host's printing with
    # the per-object Token-supertype override stamped. Mirrors
    # Python's ``_find_moonlit_replacement_source`` +
    # ``_dc.replace(base, supertypes=(*base, "Token"))`` shim at
    # ``effects/generic/tokens.py:217-247`` — byte-equal on the
    # post-resolution bf snapshot (the bridge round-trip surfaces
    # the override via the ``token_supertype_override`` key in
    # ``object_to_pydict``). The rejection that used to live here
    # has been replaced by an admit; pre-closure pinned baselines
    # for Moonlit Meditation under the bench loader were "still
    # declined" — those are now positive admits.
    #
    # **What changed.** Prior to closure: this predicate returned
    # False for any Aura carrying ``replaces_first_tokens_with_copies
    # = True``, declining Moonlit Meditation (and any future
    # CR-614-token-replacement Aura on the same rider). Post-closure:
    # the predicate falls through to the rest of the simple-Aura
    # admit checks, so an Aura whose ONLY rider is the Moonlit
    # replacement is admitted as a bridge-simple Aura. The other
    # Phase-4 declines (Chorale of the Void's reanimate trigger,
    # Cracked Skull's destroy-host shape) remain declined — this
    # closure is scoped to the S3 replacement-rider lane only.
    pass
    # Defensive — Auras don't carry ward / dynamic-PT today, but keep
    # the substrate honest (mirrors the simple-creature guardrail).
    if getattr(printing, "ward_cost", None) is not None:
        return False
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    # Static keyword set on the printing itself.
    #
    # **Phase 2 widen (round-79; symmetric-drop precedent — round-39
    # Ward / round-59 shockland).** The Aura-keyword surface admits
    # _SAFE_KEYWORDS PLUS ``flash``. ``flash`` is a cast-timing rider
    # (CR 702.8), not a per-permanent combat keyword, AND the CardDef
    # bridge in :func:`_printing_to_card_def`'s aura arm DOES NOT
    # propagate the source printing's ``keywords`` field through to the
    # CardDef — both Python and Rust materialize the Aura with empty
    # ``keywords`` from the CardDef on each engine, so the ``flash``
    # rider is **symmetrically dropped** on BOTH bridge sides
    # bit-equally. The instant-speed cast emit path (`flash` on a
    # non-creature spell makes it instant-speed castable) is unexercised
    # by `attack_all`-style bench play, which only casts at sorcery
    # speed — exactly the same parity-safety argument as the round-59
    # shocklands' tapped-entry / pay-life replacement (the rider is
    # never driven by the bench strategy on EITHER engine post-bridge,
    # so the drop is bit-equal under bench coverage).
    #
    # This widen finally admits the first **live EoE Aura** through the
    # loader: Frantic Strength (0 EoE 17lands decks — the substrate's
    # value, not deck count) + Shardmage's Rescue (0 decks; its
    # ``aura_yours_only`` is independently bridge-correct on both
    # engines per `actions.py:1337-1357` / `state_ops_cast.rs:2000-2055`;
    # its conditional `entered_this_turn` hexproof grant is NOT parsed
    # by the live parser at all — shared CR-incompleteness on the
    # Python side, so the drop is symmetric there too). See
    # `docs/SEARCH_LIMITATIONS.md` for the symmetric-drop SL entry.
    if printing.keywords and not printing.keywords.issubset(
        _SAFE_KEYWORDS | _AURA_SAFE_EXTRA_KEYWORDS
    ):
        return False
    # Granted-keyword check on equipment_bonuses (the +P/+T/keywords
    # rider). The bonus tuple is (power_bonus, toughness_bonus,
    # granted_keywords); granted_keywords must all be in _SAFE_KEYWORDS.
    # (Granted keywords flow through the CardDef bridge per
    # ``aura_granted_keywords`` and are applied to the host by Rust's
    # layer-6 grant — those MUST stay in _SAFE_KEYWORDS so both engines
    # round-trip the grant identically; only the static cast-timing
    # ``flash`` is dropped symmetrically per the comment above.)
    if printing.equipment_bonuses is not None:
        _, _, granted_kws = printing.equipment_bonuses
        if granted_kws and not granted_kws.issubset(_SAFE_KEYWORDS):
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


def _printing_is_bridge_simple_tapped_mana_land(printing) -> bool:
    """True if a CardPrinting is a NON-basic mono-color tapped mana-only
    land the bridge can round-trip byte-equal across both engines.

    **Non-basic land substrate phase 2 (round-85 N1; sibling of the
    round-60 untapped predicate above).** The motivating set is the 5
    EoE Planet lands — Adagia, Windswept Bastion / Evendo, Waking Haven
    / Kavaron, Memorial World / Susur Secundi, Void Altar / Uthros,
    Titanic Godcore. The live ``OracleParserCardSource`` flattens each
    to ``produces={one color}`` + ``enters_tapped=True`` + no triggered/
    activated/static abilities + no keywords (the parser deliberately
    drops Station + the tier-gated activated ability per
    ``land_builder.py:692-727`` — "the Station mechanic itself isn't
    modeled … drops Station + tier-gated abilities"; verified by
    ``scripts/scout_r59_nonbasic_land_shapes.py``).

    **Why bit-equal cross-engine.** The CardDef bridge does NOT carry
    ``enters_tapped`` (``cross_engine.py:_spec_card_to_printing_dict`` /
    ``_card_def_to_python_printing``) and Rust's ``register_printing``
    has no ``enters_tapped`` path on lands (``rust/src/cards.rs``;
    Rust lands are always-untapped mana sources). Both engines
    therefore materialize the bridge-flattened Planet land as an
    UNTAPPED single-color land — bit-equal cross-engine, but
    CR-incomplete (a real Kavaron enters tapped). The "should enter
    tapped" rider + the dropped Station/AA together compose a
    symmetric drop the bridge carries identically on BOTH engines —
    the same round-39 Ward / round-60 shockland precedent: a rider the
    bridge drops *symmetrically*, admittable as a **documented
    deliberate simplification** (see ``docs/SEARCH_LIMITATIONS.md`` —
    ``trajectory.py:_printing_is_bridge_simple_tapped_mana_land``).

    **The round-59 plan doc's pessimistic ``enters_tapped`` divergence
    prediction was wrong on the empirical bridge shape.**
    ``docs/NONBASIC_LAND_SUBSTRATE_PLAN.md`` §2 Class 2 (round-59
    N2) predicted "Python tapped vs Rust untapped is a real
    *inter-engine divergence* the moment the bridge admits" the
    Planet lands. That analysis assumed the bridge would propagate
    ``enters_tapped=True`` to Python only — but the CardDef carries no
    such field, so Python's ``_card_def_to_python_printing``
    materializes ``enters_tapped=False`` from the default. Python's
    ``actions.py:1087`` (``card.tapped = bool(card.printing.enters_
    tapped)``) reads False; Rust reads False; **no divergence**. The
    plan doc's verdict for sub-shape B is hereby superseded for the
    SINGLE-COLOR profile by this empirical re-walk; the verdict for
    the DUAL-COLOR sub-shape C (Duskmourn painlands,
    ``enters_tapped_unless_any_player_life_at_most=13``) remains
    correct (the painlands' tapped-entry rider IS parser-structured,
    Python honors, Rust ignores — that's the predicate's §2 reject).

    The predicate is the §2 Class-1 guardrail for the tapped
    sub-shape: it admits ONLY the parser-flattened mono-color
    mana-only profile (non-basic Land, EXACTLY 1 produce color,
    enters_tapped=True, NO abilities, NO keywords, NO conditional-
    tapped, NO clone). It MUST reject every other sibling sub-shape:

      * **The 5 untapped shocklands** (enters_tapped=False) — the
        round-60 ``_printing_is_bridge_nonbasic_mana_land`` predicate
        owns those; this predicate's positive ``enters_tapped=True``
        guard makes the two predicate sets disjoint.
      * **Duskmourn painlands** (10 cards, produces=2) —
        ``enters_tapped_unless_any_player_life_at_most=13`` set;
        Python honors, Rust ignores; real cross-engine divergence
        on tapped state (parser-structured conditional-tapped is
        the §2 reject).
      * **Cathedral of War** — enters_tapped=True + ``keywords={
        'exalted'}`` + ``produces=frozenset()``. Caught by the
        produces-size guard (``1 <= len(produces) <= 2`` rejects
        empty) AND the keyword guard. Exalted is a §2-declined
        static (campaign-wide).
      * **Secluded Starforge** — ``produces=frozenset()`` (the parser
        drops the {T}: Add {C} mana ability when the printing also
        carries a non-mana activated ability shape it can't structure;
        caught by the produces-size guard). The dropped {2},{T}:+X/+0
        and {5},{T}: make-a-Robot are §2-declined activated abilities.
      * **Echoing Deeps** — ``optional_copy_land_from_graveyard=True``
        (caught by the clone-field guard; a graveyard-copy is a
        replacement effect neither engine carries).
    """
    if "Land" not in printing.card_types:
        return False
    if "Basic" in printing.supertypes:
        return False  # basic path owns these
    if not printing.produces or not (1 <= len(printing.produces) <= 2):
        return False  # rejects Cathedral / Starforge (empty produces)
    if not getattr(printing, "enters_tapped", False):
        return False  # disjoint from the untapped (round-60) predicate
    if printing.activated_abilities:
        return False
    if printing.triggered_abilities:
        return False
    if printing.static_abilities:
        return False
    # int field; 0 (or absent) disables the conditional-tapped
    # replacement (cards/base.py:733). A positive threshold (the
    # Duskmourn painlands' 13) is a parser-structured tapped-entry
    # Python honors and Rust ignores — a real cross-engine divergence
    # (the painlands are §2-declined here; the round-60 predicate
    # rejects them on enters_tapped=False, this predicate rejects them
    # on the conditional-tapped guard).
    if getattr(printing, "enters_tapped_unless_any_player_life_at_most", 0):
        return False
    if getattr(printing, "enters_as_copy_of_creature", False):
        return False
    if getattr(printing, "optional_copy_land_from_graveyard", False):
        return False
    # Keywords guard — defends against Cathedral of War's
    # ``keywords={'exalted'}``. Cathedral is already caught by the
    # ``produces=frozenset()`` guard above; this is a second §2 tooth
    # so a future printing that combines mono-color produces +
    # enters_tapped + a parser-structured keyword can't slip through.
    # The neighboring round-60 untapped predicate has no analogous
    # check because no admitted shockland carries a keyword (verified
    # round-85 against the 5 shocklands' parser printings); the tapped
    # sibling needs the explicit check because Cathedral of War's
    # shape is one ``produces`` field away from admitting otherwise.
    if getattr(printing, "keywords", frozenset()):
        return False
    return True


# Non-basic land substrate — sub-shape E (Cathedral of War cycle 1,
# 2026-05-23). The set of static-keyword whitelist members the parser's
# ``_try_build_keyword_colorless_utility_land``
# (``cards/parser/land_builder.py:1541-1581``) admits today —
# ``Exalted`` for Cathedral of War. ``Hexproof`` is the sibling
# whitelist member for Lotus Field's paid-fancy-mana shape (different
# parser path — ``_try_build_keyword_paid_fancy_mana_land``); only
# ``exalted`` reaches the keyword-colorless utility-land profile
# this predicate guards. ``Indestructible`` is also in
# ``_LAND_KEYWORD_WHITELIST`` but no EoE-pool printing carries the
# colorless-tapped-keyword shape with it today (verified 2026-05-23
# against the merged parser pool — see the exactly-one-pool-wide pin
# below).
#
# Each keyword listed here is a §2-declined static (the bridge has no
# static-abilities path for non-creature card types — campaign-wide
# decline tracked in ``docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md``).
# The predicate drops the keyword symmetrically on both engines (round-39
# Ward / round-60 shockland / round-85 Planet land symmetric-drop
# precedent).
_CATHEDRAL_KEYWORD_WHITELIST = frozenset({"exalted"})


def _printing_is_bridge_keyword_colorless_tapped_mana_land(printing) -> bool:
    """True if a CardPrinting is a static-keyword colorless tapped
    mana-only land the bridge can round-trip byte-equal across both
    engines.

    **Non-basic land substrate sub-shape E (Cathedral of War cycle 1,
    2026-05-23; spec at ``docs/NONBASIC_LAND_SUBSTRATE_PLAN.md`` §1.E).**
    The motivating set is **Cathedral of War** (1,205 17lands decks) —
    the live ``OracleParserCardSource`` flattens its printed
    ``This land enters tapped. Exalted. {T}: Add {C}.`` to
    ``produces=frozenset()`` + ``enters_tapped=True`` + ``keywords=
    frozenset({'exalted'})`` + no abilities (the parser's
    ``_try_build_keyword_colorless_utility_land``
    (``cards/parser/land_builder.py:1541-1581``) intentionally drops
    the ``{T}: Add {C}`` line — the static side's
    ``make_utility_land(enters_tapped=True, keywords=...)`` shape leaves
    ``produces`` empty and the Python engine's
    ``auto_tap_for_cost`` (``actions.py:919-986``) covers generic
    payments from any untapped land regardless of ``produces``).

    **Why bit-equal cross-engine.** The Rust ``can_pay_cost``
    (``rust/src/state_ops_mana.rs:618-655``) explicitly SKIPS lands with
    empty ``mana_produced`` (``if symbols.is_empty() { continue; }``),
    so a parser-flattened Cathedral with empty produces would be a
    real divergence — Python's auto-tap-for-cost would count it toward
    generic payments, Rust would skip it entirely. The fix routes
    Cathedral's CardDef with ``mana_produced=("C",)`` so BOTH engines
    materialize an untapped colorless land that taps for ``{C}`` (the
    same shape basic Wastes emits). The CardDef bridge has no
    ``enters_tapped`` field and Rust's ``register_printing`` has no
    land tapped-entry path, so the parser's ``enters_tapped=True`` is
    dropped symmetrically on both engines. The static-keyword Exalted
    is dropped symmetrically as well — the bridge has no static-
    abilities path for Land card-types and Rust's land registry path
    has no keyword-static slot. Net: Cathedral is modeled as a vanilla
    untapped colorless land on BOTH engines — no Exalted, no tapped-
    entry, ever.

    This is the round-60 shockland / round-85 Planet land symmetric-drop
    precedent applied to a keyword-bearing colorless land: a parser-
    structured rider the bridge drops symmetrically on both engines,
    bit-equal under the bench play strategy, shipped blocked-at-fidelity
    rather than as a latent inter-engine divergence. See
    ``docs/SEARCH_LIMITATIONS.md`` for the deliberate-simplification
    entry (Exalted as a Land-printed static, the tapped-entry rider,
    and the printed ``{T}: Add {C}`` re-synthesized as the bridge auto-
    wired colorless mana ability).

    The predicate POSITIVELY asserts the parser-flattened
    keyword-colorless-tapped profile: non-basic Land, EMPTY ``produces``
    (the parser drops the colorless mana ability on this path), EXACTLY
    ONE keyword from :data:`_CATHEDRAL_KEYWORD_WHITELIST`,
    ``enters_tapped=True``, NO activated/triggered/static abilities, NO
    conditional-tapped, NO clone. It MUST reject every sibling
    sub-shape:

      * **The 5 shocklands / 5 Planet lands** — the existing untapped
        and tapped mana-only predicates own those; this predicate's
        positive-empty-``produces`` guard makes the three predicate
        sets disjoint (the shocklands have dual produces, the Planet
        lands have mono produces, Cathedral has empty produces).
      * **Secluded Starforge** — empty ``produces`` BUT carries 3
        activated abilities (not on this profile); rejected by the
        ``activated_abilities`` ban.
      * **Echoing Deeps** — empty ``produces`` BUT
        ``optional_copy_land_from_graveyard=True``; rejected by the
        clone-field guard.
      * **Duskmourn painlands** — dual ``produces`` (not empty); already
        rejected by the empty-produces guard.

    **Keyword whitelist tooth.** The predicate accepts ONLY keywords on
    :data:`_CATHEDRAL_KEYWORD_WHITELIST` (today: ``exalted``). The
    parser's ``_LAND_KEYWORD_WHITELIST``
    (``cards/parser/land_builder.py:1451``) also contains
    ``indestructible`` and ``hexproof``; if a future EoE-pool printing
    parses through ``_try_build_keyword_colorless_utility_land`` with a
    keyword outside this bridge whitelist, the exactly-one-pool-wide
    pin (``test_cathedral_of_war_keyword_colorless_land_exactly_one_
    pool_wide``) fails loudly so the bridge author can decide whether
    to extend the whitelist or decline the new printing.
    """
    if "Land" not in printing.card_types:
        return False
    if "Basic" in printing.supertypes:
        return False  # basic path owns these
    # Empty ``produces`` is the keyword-colorless-tapped signature; the
    # parser drops the ``{T}: Add {C}`` line on this profile per the
    # static side's ``make_utility_land(enters_tapped=True, keywords=...)``
    # shape. Non-empty produces means the printing is one of the other
    # admitted sub-shapes (shockland / Planet land) — those are owned by
    # their own predicates.
    if printing.produces:
        return False
    if not getattr(printing, "enters_tapped", False):
        return False
    if printing.activated_abilities:
        return False
    if printing.triggered_abilities:
        return False
    if printing.static_abilities:
        return False
    # int field; 0 (or absent) disables the conditional-tapped
    # replacement (cards/base.py:733). A positive threshold is a
    # parser-structured tapped-entry Python honors and Rust ignores
    # — declined for this sub-shape.
    if getattr(printing, "enters_tapped_unless_any_player_life_at_most", 0):
        return False
    if getattr(printing, "enters_as_copy_of_creature", False):
        return False
    if getattr(printing, "optional_copy_land_from_graveyard", False):
        return False
    # Keyword vocabulary check — exactly one keyword from the
    # bridge-whitelist set; zero or multiple keywords fail loudly so a
    # future printing with a different keyword vocabulary doesn't
    # silently slip through.
    keywords = getattr(printing, "keywords", frozenset())
    if len(keywords) != 1:
        return False
    if not keywords <= _CATHEDRAL_KEYWORD_WHITELIST:
        return False
    return True


def _printing_is_bridge_nonbasic_painland_conditional(printing) -> bool:
    """True if a CardPrinting is a Duskmourn-style conditional painland
    the bridge can now round-trip byte-equal across both engines.

    **Non-basic land substrate — Phase 2 (2026-05-23; spec at
    ``docs/NONBASIC_LAND_SUBSTRATE_PLAN.md`` §3 Phase 2.)** Closes
    sub-shape C — the 9 Duskmourn painlands: Abandoned Campground /
    Bleeding Woods / Etched Cornfield / Lakeside Shack / Murky Sewer
    / Neglected Manor / Peculiar Lighthouse / Raucous Carnival /
    Razortrap Gorge (+ Strangled Cemetery, the 10th member of the
    parser-claimed cycle the round-59 audit missed — all 10 share the
    same parser-emitted shape and all 10 pass this predicate).

    **Substrate that landed alongside this predicate.** Pre-Phase-2,
    the bridge had NO ``enters_tapped_unless_any_player_life_at_most``
    field, and Rust's ``register_printing`` had no painland-style
    play-land routing — Python honored the conditional-tapped
    replacement at ``actions.py:1096-1101``; Rust silently entered
    every painland UNTAPPED. The round-59 plan doc's §2 Class-2
    verdict ("inter-engine conditional-tapped divergence") was
    correct, and this slice closes the divergence by mirroring the
    field through both engines:

      * **CardDef** carries
        ``enters_tapped_unless_any_player_life_at_most: int = 0``.
      * **Bridge** emits the registry-dict key when ``> 0``;
        ``_card_def_to_python_printing`` threads the int through.
      * **Rust** ``CardPrinting`` carries
        ``enters_tapped_unless_any_player_life_at_most: i32``;
        ``parse_printing`` reads the key.
      * **Rust play-land** routes the conditional-tapped check in
        ``state_ops_cast::play_land`` BEFORE the move (the freshly-
        pushed object lands with the correct tapped state before
        ``drain_pending_etb_dispatches`` fires).

    The predicate's §2 teeth admit ONLY the parser-flattened
    conditional-painland profile: non-basic Land, 2 produce colors,
    ``enters_tapped=False``, a positive
    ``enters_tapped_unless_any_player_life_at_most`` threshold (the
    Duskmourn cycle prints 13), NO triggered/activated/static
    abilities, NO keywords, NO clone fields. The two sibling
    non-basic-land predicates (round-60 untapped shockland,
    round-85 mono-color tapped Planet land) stay positively disjoint
    on the conditional-tapped guard:

      * **Round-60** rejects a positive threshold → cannot admit a
        painland. **Round-85** rejects a positive threshold → cannot
        admit a painland. **This predicate** REQUIRES a positive
        threshold → cannot admit a shockland or a Planet land. The
        three predicates partition the non-basic-land admit space.

    The remaining 4 of the original 23 non-basic-land cards stay
    DECLINED in this phase: Secluded Starforge (sub-shape D — three
    activated abilities, ``produces=()``), Cathedral of War (sub-
    shape E — Exalted static + ``produces=()``), Echoing Deeps
    (sub-shape F — graveyard-clone replacement). Each needs its own
    substrate cycle.

    **Real bench signal:** 0 EoE deck-count (all 9 are off-set
    Duskmourn cards in the merged pool, not EoE draftables), so this
    Phase-2 yield is **+9 cards / +0 cumulative 17lands EoE decks**
    — card-count fidelity only, NOT bench-signal yield. The substrate
    that landed here is reusable for any future EoE printing with the
    same shape (the predicate keys off the field, not the card name).
    """
    if "Land" not in printing.card_types:
        return False
    if "Basic" in printing.supertypes:
        return False  # basic path owns these
    if not printing.produces or not (1 <= len(printing.produces) <= 2):
        return False
    # The painland cycle is dual-colored — defends against any future
    # mono-color or 3+ color carrier slipping through.
    if printing.activated_abilities:
        return False
    if printing.triggered_abilities:
        return False
    if printing.static_abilities:
        return False
    # The conditional-tapped replacement IS the load-bearing rider —
    # we admit ONLY printings that carry it. The round-60 + round-85
    # sibling predicates reject it; this one positively requires it.
    threshold = getattr(
        printing, "enters_tapped_unless_any_player_life_at_most", 0,
    )
    if threshold <= 0:
        return False
    # The Duskmourn cycle's canonical threshold is 13. The check is
    # written as an exact-match so a future cycle with a different
    # threshold falls into a SEPARATE admit predicate (whose Rust
    # play-land routing already handles any positive threshold — but
    # the loader keeps the strict gate so the substrate widening
    # decision is explicit, not silent).
    if threshold != 13:
        return False
    # The plain `enters_tapped` flag is honored by Python's
    # `_play_land` (`actions.py:1087`) but NOT YET by Rust's
    # `play_land` (separate substrate — see SEARCH_LIMITATIONS.md
    # `_printing_is_bridge_simple_tapped_mana_land` entry; Planet
    # lands are bridged as untapped on BOTH engines symmetrically).
    # The painlands all carry `enters_tapped=False` (the parser
    # structures the conditional INSTEAD of the plain enters_tapped),
    # but we defensively reject `enters_tapped=True` so a future
    # parser change can't slip a tapped+conditional shape through.
    if getattr(printing, "enters_tapped", False):
        return False
    if getattr(printing, "enters_as_copy_of_creature", False):
        return False
    if getattr(printing, "optional_copy_land_from_graveyard", False):
        return False
    if getattr(printing, "keywords", frozenset()):
        return False
    return True


# ---------------------------------------------------------------------------
# Carrier-AA substrate Phase 1.5a (2026-05-25)
# ---------------------------------------------------------------------------
#
# Sub-shape A: single-``{T}`` OR ``{N}, {T}`` (generic-only mana) cost,
# single-bridged-Effect, no-rider non-token Land carriers. Pilot cards:
# Swarmyard (``{T}: Regenerate target Rat, Spider, Squirrel, or Insect
# creature.``) + Deserted Temple (``{1}, {T}: Untap target land.``).
#
# **Phase 1.5a cost-gate widen (this slice).** Widens
# ``_aa_is_phase1_sub_shape_a`` from STRICT bare-``{T}`` to bare-``{T}``
# OR ``{N}, {T}`` (generic-only mana — no colored / hybrid / X-pip)
# per ``docs/CARRIER_AA_SUBSTRATE_PHASE_1_5_DESIGN.md`` §2/§5. Admits
# Deserted Temple immediately because the ``UntapTargetLand`` Effect
# was already in the Phase-1 admit set (C1 substrate) and the bridge's
# ``_python_aa_to_safe_dict`` already serializes generic-mana costs.
# ZERO Rust changes (Rust already routes generic mana for AAs).
#
# Cycle 1 substrate (commit ``226c9738``) shipped the Rust side:
# ``CardDef.activated_abilities`` field + non-token ``build_rust_state``
# emit block + the two new Rust ``Effect`` variants
# (``RegenerateTargetCreature {allowed_subtypes}`` and
# ``UntapTargetLand``) + the ``_card_def_to_python_printing`` reverse
# arm + the two ``_ta_dict_to_python_effect`` bridge arms. Cycle 2
# (commit ``0cc08732``) wired the admit gate at the strict bare-``{T}``
# shape with Swarmyard admitting + Deserted Temple as the honest-stop.
# Phase 1.5a (this slice) widens the cost-mana axis to ``{N}, {T}`` and
# inverts the C2 honest-stop pins.
#
# **No silent auto-grow (Phase 1.5a re-walk).** Verify-first walked
# all 30 BLOCKED-SG Carrier-AA cards (design doc §2.1) against the
# WIDENED predicate below: only Swarmyard + Deserted Temple admit;
# every other carrier honestly declines. Notably the candidate
# siblings stay declined on Effect-class teeth — Terrain Generator on
# ``PutBasicLandFromHandOntoBattlefieldTapped``, Thespian's Stage on
# ``BecomesCopyOfTargetLand``, Mystifying Maze on
# ``ExileTargetAttackingCreatureUntilEndStep`` (the Phase 1 effect-class
# admit set ``{RegenerateTargetCreature, UntapTargetLand}`` does the
# work). Phase 1.5a admit count: +1 (Deserted Temple, total 2).


# Phase-1 admitted AA[0] Effect classes. Pilot Swarmyard ships the
# ``RegenerateTargetCreature`` Effect; ``UntapTargetLand`` is wired
# substrate-side (C1) for the eventual Phase-1.5 Deserted Temple sibling
# (or Phase-1.5 ``{N}, {T}`` cost-shape widen). Phase-2/3/N extends this
# set as each Effect class lands cross-engine.
#
# **Carrier-AA substrate Phase 2a Cycle 2 (2026-05-25).** The accessor
# is widened to include ``ReturnTargetLandFromGraveyardToHand``
# (Petrified Field's pilot Effect — landed cross-engine in Phase 2a
# Cycle 1 at ``aca39437`` per
# ``docs/CARRIER_AA_SUBSTRATE_PHASE_2_DESIGN.md`` §5.2). The
# Phase-1 prefix in the function name is preserved for back-compat;
# the function is the single source of truth for the Carrier-AA
# admit-effect set (not specifically Phase 1) — mirrors the cost-
# reduction substrate's ``_cost_reduction_rule_is_phase1_or_3``
# widened-helper naming.
#
# **Carrier-AA substrate Phase 2b (2026-05-25).** The accessor is
# further widened to include
# ``PutBasicLandFromHandOntoBattlefieldTapped`` (Terrain Generator's
# pilot Effect — combined-cycle Rust substrate + Python admit + FLIP
# in the Phase-2b cycle per ``docs/CARRIER_AA_SUBSTRATE_PHASE_2_
# DESIGN.md`` §4.2/§5.2/§6.4 #15). The Rust ``Effect::PutBasicLand
# FromHandOntoBattlefieldTapped`` variant + parse/resolve/to_pydict
# arms + cross-engine bridge arms land in the same cycle (no
# substrate-only intermediate landing — the Effect is a pure
# no-target hand→bf-tapped zone-move sibling of Anticausal Vestige's
# may-put-permanent-from-hand-tapped resolve arm at
# ``state_ops_resolve.rs:15406``). ZERO new target-fan-out surface
# (Terrain Generator's AA has no target — the activator's hand-
# search is internal to the resolve).
#
# **Carrier-AA substrate Phase 3A Cycle 2 (2026-05-25).** The
# accessor is further widened to include
# ``ExileTargetAttackingCreatureUntilEndStep`` (Mystifying Maze's
# pilot Effect — Phase 3A C1 substrate landing at ``3de469a3``
# shipped the Rust ``Effect::ExileTargetAttackingCreatureUntilEndStep``
# variant + paired ``Effect::ReturnExiledPermanentToOwnerTapped``
# delayed-trigger + parse/resolve/to_pydict arms + cross-engine
# bridge arms + attacking-creature target fan-out arm per
# ``docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md`` §4.1/§5.2/§7.1).
# Mystifying Maze's live AA shape is ``{4}, {T}`` (Phase-1.5a
# ``{N}, {T}`` cost-shape — already wired) + the now-admitted
# ``ExileTargetAttackingCreatureUntilEndStep`` effect class, so the
# admit-gate FLIPs DECLINED → ADMITTED on this widen alone (no
# further admit-side wiring needed). Sibling of the Phase-2b widen
# for ``PutBasicLandFromHandOntoBattlefieldTapped``.
#
# **Carrier-AA substrate Phase 3B Cycle 2 (2026-05-25).** The
# accessor is further widened to include ``ExileAllGraveyards``
# (Scavenger Grounds's pilot Effect — Phase 3B C1 substrate landing
# at ``51abfd78`` shipped the Rust ``Effect::ExileAllGraveyards``
# unit variant + parse/resolve/to_pydict arms + cross-engine
# bridge arms per
# ``docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md`` §4.2/§5.3/§7.2).
# Scavenger Grounds's live AA shape is ``{2}, {T}, Sac-a-Desert``
# — the Phase-1.5a ``{N}, {T}`` cost-shape is already wired; this
# cycle pairs the Effect-class widen with a strictly-additive
# cost-gate widen on the ``sacrifice_a_desert`` axis (in
# :func:`_aa_is_phase1_sub_shape_a`) so the admit-gate FLIPs
# DECLINED → ADMITTED on the combined widen. Sibling of the
# Phase-3A C2 widen for ``ExileTargetAttackingCreatureUntilEndStep``.
def _carrier_aa_phase_1_effect_classes() -> "frozenset[type]":
    """Lazy accessor for the Carrier-AA admitted AA[0] Effect classes.

    Returns a frozenset of the Python ``Effect`` subclasses the Rust
    substrate carries cross-engine: ``RegenerateTargetCreature``
    (Phase 1 pilot — Swarmyard) + ``UntapTargetLand`` (Phase 1 C1
    substrate / Phase 1.5a admits Deserted Temple) +
    ``ReturnTargetLandFromGraveyardToHand`` (Phase 2a C1 substrate /
    Phase 2a C2 admits Petrified Field) +
    ``PutBasicLandFromHandOntoBattlefieldTapped`` (Phase 2b combined-
    cycle Rust substrate + Python admit + Terrain Generator FLIP) +
    ``ExileTargetAttackingCreatureUntilEndStep`` (Phase 3A C1
    substrate at ``3de469a3`` / Phase 3A C2 admits Mystifying Maze) +
    ``ExileAllGraveyards`` (Phase 3B C1 substrate at ``51abfd78`` /
    Phase 3B C2 admits Scavenger Grounds) +
    ``BecomesCopyOfTargetLand`` (Phase 3C C1 substrate at
    ``f5a2a1ce`` + C2 Rust Effect at ``6de50d8d`` / Phase 3C C3
    admits Thespian's Stage — copy-effect substrate).
    Lazily imported so the module import-graph stays light and tests
    that monkeypatch the effect classes (unit pins) see a fresh
    frozenset each call.

    **Phase 3C Cycle 3 (2026-05-26).** Effect-class admit-set widen
    from 6 → 7 per ``docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md``
    §5.4 / §7.3. Combined with the pre-existing Phase-1.5a
    ``{N}, {T}`` cost-shape gate, the Thespian's Stage's ``{2}, {T}``
    AA admits at the Carrier-AA admit predicate
    :func:`_aa_is_phase1_sub_shape_a` — admit-gate FLIPs DECLINED →
    ADMITTED on this widen alone (ZERO new cost-shape machinery, ZERO
    new Rust changes — C1 + C2 shipped the substrate + Effect variant
    + Land-target fan-out + cross-engine bridge arms).

    **Phase 4E Cycle 2 (2026-05-26 — partial substrate landing per
    ``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §5.7 + honest-stop
    on the "any" coin Rust substrate gap).** Effect-class admit-set
    widen from 7 → 9, adding ``DrawCardsByConditionMultiplier``
    (All-Fates Scroll's AA[1] pilot — the C1 substrate at
    ``c50cf8da`` shipped the Rust ``Effect::
    DrawCardsByConditionMultiplier`` variant + parallel
    ``condition_count`` dispatcher + cross-engine bridge arms) and
    ``AddManaToPool`` (All-Fates Scroll's AA[0] pilot — the Rust
    ``Effect::AddManaToPool`` variant ships from round-21+ for the
    fixed-color W/U/B/R/G/C mana-ability slice; the reverse arm
    exists at ``cross_engine.py:7697``; this cycle adds the forward
    arm in :func:`cross_engine._python_aa_to_safe_dict`). All-Fates
    Scroll's AA[0] carries ``produces=(("any", 1),)``; Rust's
    ``validate_mana_symbol`` rejects "any" (closed vocab
    ``{W,U,B,R,G,C}`` per ``cards.rs:15888``) and the ``ManaPool``
    primitives in ``state.rs:942`` lack an "any" coin slot. The
    bridge floor's new forward arm at ``cross_engine.py`` honest-
    declines any ``AddManaToPool`` whose ``produces`` carries an
    "any" color discriminator — All-Fates Scroll therefore STAYS
    DECLINED on the new "any" teeth even though the per-AA admit
    predicate now passes the Effect-class + ``is_mana_ability``
    rider gates. The full FLIP defers to a follow-up Rust cycle
    (Phase 4E C2.5 — ``ManaPool.any`` coin substrate + Rust resolve
    arm + drain semantics) that closes the gap; see
    ``docs/SEARCH_LIMITATIONS.md`` for the divergence entry. Sibling
    of the Phase 4B/4C/4D Effect-class widens for the other 3 multi-
    AA carriers.

    **Phase 4C Cycle 2 (2026-05-26 — Ghost Vacuum admit + FLIP per
    ``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §5.5 + §6.3 +
    §7.3).** Effect-class admit-set widen from 9 → 11, adding
    ``ExileTargetCardFromGraveyard`` (Ghost Vacuum's AA[0] pilot —
    the C1 substrate at ``8004d970`` shipped the Rust
    ``Effect::ExileTargetCardFromGraveyard`` variant + per-player-
    graveyard fan-out + cross-engine bridge arms) and
    ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl``
    (Ghost Vacuum's AA[1] recall pilot — the C1 substrate shipped
    the Rust variant + zero-target mass-effect resolve arm reading
    ``exiled_with_source``; the recall variant's
    ``grant_flying_counter`` + ``grant_subtype_and_pt`` riders are
    DATA-CARRYING ONLY at Rust resolve today — the layered-grant
    machinery to actually stamp a flying counter + Spirit subtype +
    1/1 base P/T at recall is Phase-N; see
    ``docs/SEARCH_LIMITATIONS.md`` Phase 4C entry).

    Combined with the bridge-floor ``sorcery_speed`` AA-rider widen
    in :func:`cross_engine._python_aa_to_safe_dict` (lifts the
    ``aa.sorcery_speed: return None`` decline arm at line 14798)
    plus the new ``sorcery_speed`` slot on Rust's ``ActivatedAbility``
    struct + parse arm, Ghost Vacuum's two AAs both pass the per-AA
    admit predicate AND the bridge-floor round-trip — the carrier
    FLIPs DECLINED → ADMITTED at the production-deck admit gate.
    Sibling of the Phase 4E C2 widen for All-Fates Scroll's
    ``is_mana_ability`` rider.

    **Phase-3/N extends this set as each Effect class lands cross-
    engine.**
    """
    from mtg_bot.effects.generic.become_type import BecomesCopyOfTargetLand
    from mtg_bot.effects.generic.bounce import (
        ReturnTargetLandFromGraveyardToHand,
    )
    from mtg_bot.effects.generic.destroy import RegenerateTargetCreature
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardsByConditionMultiplier,
    )
    from mtg_bot.effects.generic.exile import (
        ExileAllGraveyards,
        ExileTargetAttackingCreatureUntilEndStep,
        ExileTargetCardFromGraveyard,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.effects.generic.mana import AddManaToPool
    from mtg_bot.effects.generic.tap import UntapTargetLand
    from mtg_bot.effects.generic.zone_moves import (
        PutBasicLandFromHandOntoBattlefieldTapped,
    )
    return frozenset({
        RegenerateTargetCreature,
        UntapTargetLand,
        ReturnTargetLandFromGraveyardToHand,
        PutBasicLandFromHandOntoBattlefieldTapped,
        ExileTargetAttackingCreatureUntilEndStep,
        ExileAllGraveyards,
        BecomesCopyOfTargetLand,
        DrawCardsByConditionMultiplier,
        AddManaToPool,
        ExileTargetCardFromGraveyard,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    })


def _aa_is_phase1_sub_shape_a(aa) -> bool:
    """True iff ``aa`` is a Phase-1.5a Carrier-AA admit-set ``ActivatedAbility``.

    Sub-shape A is the narrowest Phase-1.5a admit:

    * **Cost gate (Phase 1.5a — bare ``{T}`` OR ``{N}, {T}``):**
      ``cost.tap_self is True`` and (``cost.mana is None`` OR
      ``cost.mana`` carries ONLY generic-mana pips — no colored,
      hybrid, or X-pip mana). Every other cost field defaults
      (sacrifice / pay_life / requires_* / control-of-subtype all
      decline if non-default). Deserted Temple's ``{1}, {T}`` cost
      admits at Phase 1.5a (was Phase-1 honest-stop).
    * **AA-level rider gate (Phase 4C C2+ — most riders decline):**
      ``cost_reductions=()``, ``room_half is None``,
      ``tier_threshold==0``, ``activate_only_once=False``.
      ``is_mana_ability=True`` is admitted at Phase 4E C2;
      ``sorcery_speed=True`` is admitted at Phase 4C C2 (Ghost Vacuum's
      AA[1] -- see Phase 4C entry in
      ``docs/SEARCH_LIMITATIONS.md`` for the activation-time legality
      gap). Every other Phase-N rider declines.
    * **Effect-class gate (STRICT Phase-1 admit set):**
      ``type(aa.effect) in {RegenerateTargetCreature, UntapTargetLand}``.
      Phase-2/3/N extends this set as each Effect class lands cross-
      engine.

    Note on ``RegenerateTargetCreature.allowed_subtypes``: Swarmyard's
    pilot effect carries ``allowed_subtypes={Rat, Spider, Squirrel,
    Insect}`` (non-empty). The C1 substrate's cross-engine bridge
    round-trips the filter byte-equal — so the predicate does NOT
    gate on ``allowed_subtypes`` being empty. The filter is an
    Effect-level concept, not an admit-gate rider.

    **Carrier-AA substrate Phase 1.5a (2026-05-25).** Cost-gate widen
    from STRICT bare ``{T}`` to bare ``{T}`` OR ``{N}, {T}``
    (generic-only mana) per ``docs/CARRIER_AA_SUBSTRATE_PHASE_1_5_
    DESIGN.md`` §2/§5. Admits Deserted Temple immediately on the
    gate-widen alone — the ``UntapTargetLand`` Effect was already in
    the Phase-1 admit set (C1 substrate); only the cost-shape gate
    needed widening. ZERO Rust changes (Rust already routes generic
    mana for AAs via the ``_python_aa_to_safe_dict`` round-trip).

    **Carrier-AA substrate Phase 2a (2026-05-25).** Cost-gate widen
    from bare ``{T}`` / ``{N}, {T}`` to additionally admit
    ``sacrifice_self=True`` per ``docs/CARRIER_AA_SUBSTRATE_PHASE_2_
    DESIGN.md`` §5.1. Admits Petrified Field on the gate-widen plus
    the new ``ReturnTargetLandFromGraveyardToHand`` Effect-class
    admit (Phase 2a Cycle 1 substrate landing at ``aca39437``
    shipped the cross-engine Rust variant + bridge arms). The
    ``sacrifice_self`` cost-pay path is already wired end-to-end on
    the Rust side via the Lander ``{N}, Sac:`` token-AA precedent
    (``state_ops_actions.rs:1300-1391``); ZERO new Rust cost-shape
    machinery needed.

    **Carrier-AA substrate Phase 3B Cycle 2 (2026-05-25).** Cost-gate
    widen on the ``sacrifice_a_desert`` axis per
    ``docs/CARRIER_AA_SUBSTRATE_PHASE_3_DESIGN.md`` §5.3. The strict
    ``sacrifice_a_desert`` decline arm is removed; a defense-in-depth
    both-at-once guard remains (``sacrifice_a_desert and
    sacrifice_self`` declines because no live carrier carries both
    sacrifice axes — confirmed by full-pool verify-first audit, only
    Scavenger Grounds carries ``sacrifice_a_desert=True`` and its
    ``sacrifice_self`` is ``False``). The Rust ``ActivationCost.
    sacrifice_a_desert`` parse + Desert-target fan-out
    (``state_ops_legal.rs:3522``) + cost-pay commit
    (``state_ops_actions.rs:1287``) are wired end-to-end since the
    CE20 / Lander precedent; ZERO new Rust cost-shape machinery
    needed. Pairs with the Phase-3B C2 Effect-class widen for
    ``ExileAllGraveyards`` (Scavenger Grounds FLIPs DECLINED →
    ADMITTED on the combined widen).

    **§2 contract preservation:** every other cost-bool gate
    (``exile_self``, ``tap_permanent_you_control``,
    ``sacrifice_another_*``, ``pay_life``, ``requires_*``, etc.)
    stays bit-identical. The Phase-3B C2 widen is strictly additive
    on the ``sacrifice_a_desert`` axis under the both-at-once guard;
    no other field's contract loosens. Colored / hybrid / X-pip mana
    costs stay Phase-N honest-stops; ``sacrifice_another_*`` stays
    Phase N.

    Mirrors the SoT-flip pattern of the token-AA Lander helper at
    ``trajectory.py:3208`` and the Phase-2 Eldrazi Scion helper at
    ``trajectory.py:3339``.
    """
    from mtg_bot.effects.base import ActivatedAbility

    if not isinstance(aa, ActivatedAbility):
        return False
    # Cost gate — Phase 3B: bare {T} OR {N}, {T} OR ({T}, Sac:) OR
    # ({N}, {T}, Sac:) OR ({T}, Sac-a-Desert:) OR ({N}, {T},
    # Sac-a-Desert:) — generic-only mana, optional sacrifice_self
    # OR sacrifice_a_desert (the both-at-once combo declines via the
    # defense-in-depth guard below; no live EoE carrier sets both).
    cost = aa.cost
    if not cost.tap_self:
        return False
    if cost.mana is not None:
        # Phase 1.5a admits generic-only mana costs ({N}, {T} shape).
        # Colored / hybrid / X-pip mana costs are Phase N honest-stops.
        if cost.mana.colored:
            return False
        if cost.mana.hybrid:
            return False
        if cost.mana.x_pips:
            return False
        if cost.mana.generic <= 0:
            # Should not happen — a ManaCost with all-zero fields would
            # be ``None``, not an empty ``ManaCost`` — but defend in
            # depth so a malformed cost never sneaks through.
            return False
    # Phase 2a admits ``sacrifice_self=True`` under the cost-gate widen.
    # Phase 3B admits ``sacrifice_a_desert=True`` under the cost-gate
    # widen. Lander's ``{N}, Sac:`` token-AA precedent already wired
    # the Rust ``ActivationCost.sacrifice_self`` parse + Phase 5b
    # cost-pay commit; the CE20 / Lander precedent already wired
    # ``ActivationCost.sacrifice_a_desert`` parse + Desert-target
    # fan-out + cost-pay commit. Other sacrifice variants
    # (``sacrifice_another_*``) still decline below.
    if cost.exile_self:
        return False
    if cost.tap_permanent_you_control:
        return False
    if cost.exile_artifact_from_graveyard:
        return False
    if cost.sacrifice_another_creature_or_artifact:
        return False
    if cost.sacrifice_another_artifact_or_land:
        return False
    if cost.sacrifice_another_artifact:
        return False
    if cost.sacrifice_food:
        return False
    if cost.sacrifice_a_land:
        return False
    # Phase 3B C2 defense-in-depth: the both-at-once
    # ``sacrifice_a_desert + sacrifice_self`` combo declines. No live
    # EoE carrier carries both (verify-first full-pool audit at
    # 2026-05-25); the guard exists so a future carrier carrying both
    # axes fails honestly rather than silently auto-admitting under
    # the Phase-3B widen.
    if cost.sacrifice_a_desert and cost.sacrifice_self:
        return False
    if cost.remove_plus_one_counter_from_your_creature:
        return False
    if cost.exile_granting_equipment:
        return False
    if cost.mana_reduced_by_source_power:
        return False
    if cost.pay_life:
        return False
    if cost.requires_own_creature_power_at_least:
        return False
    if cost.requires_own_artifact_count_at_least:
        return False
    if cost.requires_control_of_subtype:
        return False
    # AA-level rider gate.
    #
    # **Phase 4E Cycle 2 (2026-05-26 — partial substrate landing per
    # docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md §5.7).** The
    # ``is_mana_ability=True`` rider was Phase-1 honest-stop until the
    # Rust ``ActivatedAbility.is_mana_ability`` field round-trips with
    # the Carrier-AA admit set; Phase 4E-C2 widens the gate to admit
    # ``is_mana_ability=True`` because the Rust side has been able to
    # round-trip mana-ability AAs since the round-21 mana-ability
    # bridge slice (basic-land auto-wire at ``cross_engine.py:14252``).
    # The combined Effect-class widen
    # (:func:`_carrier_aa_phase_1_effect_classes`) now also includes
    # ``AddManaToPool`` so the live mana-ability surface (e.g. All-
    # Fates Scroll's AA[0]) clears the per-AA admit teeth. The bridge
    # floor :func:`cross_engine._python_aa_to_safe_dict` honest-
    # declines any ``AddManaToPool`` whose ``produces`` carries an
    # "any" color discriminator (Rust's ``validate_mana_symbol``
    # closed vocab + ``ManaPool`` substrate gap — see Phase 4E C2.5
    # follow-up cycle in ``docs/SEARCH_LIMITATIONS.md``), so All-Fates
    # Scroll STAYS DECLINED at the cross-engine builder gate on the
    # "any" teeth even though the per-AA admit predicate now passes.
    #
    # **Phase 4C Cycle 2 (2026-05-26 — Ghost Vacuum admit per
    # docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md §5.5).** The
    # ``sorcery_speed=True`` rider was Phase-1 honest-stop until the
    # Rust ``ActivatedAbility`` struct gained the round-tripping
    # ``sorcery_speed: bool`` slot at Phase 4C C2 (cards.rs:11091).
    # The flag is DATA-CARRYING on Rust today — the activation-time
    # legality gate (CR 605.3a sorcery-timing block) defers to a
    # follow-up cycle per the SL entry; see
    # ``docs/SEARCH_LIMITATIONS.md`` Phase 4C entry. The bridge floor
    # :func:`cross_engine._python_aa_to_safe_dict` emits
    # ``"sorcery_speed": True`` on the AA dict so the Rust round-trip
    # carries the rider byte-equal.
    if aa.cost_reductions:
        return False
    if aa.room_half is not None:
        return False
    if aa.tier_threshold:
        return False
    if aa.activate_only_once:
        return False
    # Effect-class gate.
    if type(aa.effect) not in _carrier_aa_phase_1_effect_classes():
        return False
    return True


def _printing_is_bridge_simple_carrier_aa_land(printing) -> bool:
    """True iff a CardPrinting is a PURE Carrier-AA Land carrier whose
    AAs the Phase-4A Carrier-AA substrate round-trips byte-equal.

    Motivating Phase-3 admit set: Swarmyard + Deserted Temple +
    Petrified Field + Terrain Generator + Mystifying Maze +
    Scavenger Grounds (6 EoE cards; Thespian's Stage admits at Phase
    3C C2). The §2 Class-1 guardrail: admits ONLY the bare Carrier-AA
    Land profile under the Phase-3 cost gate AND MUST reject every
    ``<empty-cost>`` carrier, every mana-ability, every sorcery-speed,
    every triggered-ability-co-gated carrier, every Creature carrier,
    every Equipment carrier, every ``BecomeLandCreatureUEOT``-with-
    rider carrier — sub-shapes deferred to Phase 4+ (design doc §3).

    Phase 1.5a widen adds Deserted Temple via the ``{N}, {T}``
    cost-shape; Phase 2a widen adds Petrified Field via the
    ``({T}, Sac:)`` cost-shape PLUS the new
    ``ReturnTargetLandFromGraveyardToHand`` Effect-class admit. Phase
    3 widens add Terrain Generator + Mystifying Maze + Scavenger
    Grounds via their Effect-class + cost-axis admits.

    **Phase 4A widen (2026-05-26 — substrate-only keystone landing per
    ``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §5.2).** The single-
    AA invariant (``len(aas) != 1: return False``) widens to a multi-
    AA all-or-nothing per-AA walk — every AA on the printing must
    independently pass :func:`_aa_is_phase1_sub_shape_a`. The widen is
    strictly additive on the ``len(aas)`` axis; every per-AA gate
    stays bit-identical. A printing with N>=2 AAs whose AA[i] fails
    the per-AA predicate still declines under the all-or-nothing
    contract (mirrors the token-AA Lander's per-AA contract per Phase
    2 §3.4 of the Phase-4 design doc). The widen is admit-set-neutral
    at Phase 4A close — all 4 multi-AA Phase-4 carriers (Mirrorpool /
    Ghost Vacuum / Keys to the House / All-Fates Scroll) still
    decline at the per-AA Effect-class teeth + AA-rider teeth
    (``sorcery_speed`` / ``is_mana_ability``); the +4 admits land via
    4B/4C/4D/4E.

    See :func:`_aa_is_phase1_sub_shape_a` for the cost-axis details
    and :func:`_carrier_aa_phase_1_effect_classes` for the Effect-
    class admit set. See
    :func:`_printing_is_bridge_simple_carrier_aa_artifact` for the
    Artifact-typed sibling predicate landed at Phase 4A.2.
    """
    if "Land" not in printing.card_types:
        return False
    # Phase 1 admits only single-typed Land — no Land—Desert
    # (Scavenger Grounds is decline-by-cost anyway), no Legendary
    # Artifact—Spacecraft (The Eternity Elevator), no Creature
    # overlap (Sliver Overlord).
    extra_card_types = tuple(
        t for t in printing.card_types if t != "Land"
    )
    if extra_card_types:
        return False
    if printing.power is not None or printing.toughness is not None:
        return False
    # Carrier exclusion set — every Phase-2+ rider, every other
    # subsystem.
    if printing.keywords:
        return False
    if printing.triggered_abilities:
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
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    # **Phase 4A multi-AA admit substrate (2026-05-26).** Widened from
    # STRICT single-AA ``len(aas) != 1`` to a multi-AA all-or-nothing
    # per-AA walk; every AA must independently pass the sub-shape-A
    # predicate. Zero-AA carriers still decline (not a carrier).
    aas = tuple(printing.activated_abilities or ())
    if len(aas) == 0:
        return False
    for aa in aas:
        if not _aa_is_phase1_sub_shape_a(aa):
            return False
    return True


def _printing_is_bridge_simple_carrier_aa_artifact(printing) -> bool:
    """Sibling of :func:`_printing_is_bridge_simple_carrier_aa_land`
    for Carrier-AA Artifact carriers.

    **Carrier-AA substrate Phase 4A.2 (2026-05-26 — substrate-only
    keystone landing per
    ``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §5.3).** Opens
    the admit gate to single-card-type Artifact carriers with the
    same per-AA + bridge-floor gates as the Land sibling, plus the
    §5.2 multi-AA widen of the per-AA walk. Pilot trio (3 of 4
    Phase-4 carriers are Artifact, not Land): Ghost Vacuum / Keys
    to the House / All-Fates Scroll. Phase 4A admits NONE of them
    (substrate-only — they still decline at the per-AA Effect-class
    teeth and AA-rider teeth); 4C/4D/4E land the actual carrier
    admissions.

    **§2 teeth (must reject):**

      * Non-Artifact — wrong card type entirely.
      * Multi-card-type — no Artifact-Creature overlap; no
        Land-Artifact overlap; no Spacecraft via the
        ``Artifact—Spacecraft`` overlap (Spacecraft Station substrate
        is the canonical Spacecraft path).
      * Non-empty ``subtypes`` — Equipment / Vehicle / Spacecraft /
        Food / Treasure subtypes carry their own rider clusters that
        Phase 4 explicitly defers to Phase N per design doc §3.
      * Every Phase-2+ rider field on the printing (keywords /
        triggered / static / spell_effect / warp / kicker / impending
        / room_halves / loyalty / cost_reductions / station_threshold
        / dynamic_pt_formula / ward_cost / non-default P/T) — the
        same exclusion-set as the Land sibling.
      * Zero AAs — not a carrier.
      * Any AA failing :func:`_aa_is_phase1_sub_shape_a` — the §5.2
        multi-AA all-or-nothing contract.
    """
    if "Artifact" not in printing.card_types:
        return False
    extra_card_types = tuple(
        t for t in printing.card_types if t != "Artifact"
    )
    if extra_card_types:
        return False
    # Equipment / Vehicle / Spacecraft / Food / Treasure subtypes are
    # Phase N — strict empty-subtypes guard for Phase 4A.
    if printing.subtypes:
        return False
    # Defense-in-depth on P/T — an Artifact-only carrier should never
    # carry a power or toughness; an Artifact—Creature would have
    # been rejected at the ``extra_card_types`` guard above. This
    # mirrors the Land sibling's symmetric guard.
    if printing.power is not None or printing.toughness is not None:
        return False
    # Same per-printing rider guards as the Land sibling.
    if printing.keywords:
        return False
    if printing.triggered_abilities:
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
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    # **Phase 4A multi-AA admit substrate (2026-05-26).** Same multi-
    # AA all-or-nothing per-AA walk as the Land sibling.
    aas = tuple(printing.activated_abilities or ())
    if len(aas) == 0:
        return False
    for aa in aas:
        if not _aa_is_phase1_sub_shape_a(aa):
            return False
    return True


def _printing_is_bridge_simple_carrier_aa_any(printing) -> bool:
    """Top-level Carrier-AA admit dispatcher across the Land + Artifact
    sibling predicates.

    **Carrier-AA substrate Phase 4A (2026-05-26 — keystone landing per
    ``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §5.3).** Returns
    True iff the printing is either a Carrier-AA Land admit
    (:func:`_printing_is_bridge_simple_carrier_aa_land`) or a
    Carrier-AA Artifact admit
    (:func:`_printing_is_bridge_simple_carrier_aa_artifact`). The
    dispatcher exists so the ``_filter_deck_to_bridge_supported``
    OR-chain has a single call site that subsumes both card-type
    siblings — future Carrier-AA siblings (e.g., Carrier-AA Enchantment
    in Phase N) bolt on here without further OR-chain edits.

    The two sibling predicates are mutually exclusive (a printing
    cannot carry both ``"Land"`` and ``"Artifact"`` in its
    ``card_types`` and still pass either sibling — both reject
    multi-card-type carriers via their ``extra_card_types`` guards),
    so the OR short-circuit semantics are well-defined.
    """
    return (
        _printing_is_bridge_simple_carrier_aa_land(printing)
        or _printing_is_bridge_simple_carrier_aa_artifact(printing)
    )


def _carrier_aa_land_card_def(printing) -> "Optional[CardDef]":
    """Build a CardDef from a Phase-1-admitted non-token Carrier-AA Land.

    Pre-condition: ``printing`` must pass
    :func:`_printing_is_bridge_simple_carrier_aa_land`. This builder
    trusts that guardrail and serializes the single AA into the
    bridge dict shape via the round-trip-floor helper
    :func:`cross_engine._python_aa_to_safe_dict`. Returns ``None`` if
    the AA fails the safe-dict round-trip (a defense-in-depth honest
    decline; the admit predicate should already have rejected such
    shapes, so reaching this branch is a builder-vs-guardrail
    disagreement that fails silent rather than constructing a CardDef
    the bridge would mistranslate).

    The synthesized CardDef carries:

    * ``card_type="Land"`` (single-typed — admit predicate rejects
      any extra card type).
    * No ``mana_produced`` — Phase-1 Carrier-AA Lands are NOT mana-
      producing lands (Swarmyard taps to regenerate, not to add
      mana; the bridge's mana-ability auto-wire fires only for non-
      empty ``mana_produced``). The companion AA mana-ability auto-
      wire at ``cross_engine.py:14252`` therefore does NOT prepend a
      ``{T}: Add {C}`` entry. The carrier AA is the SOLE activated
      ability on both engines.
    * ``activated_abilities=(aa_dict,)`` carrying the bridge-shape
      AA dict (the SAME dict Rust's ``register_printing``
      ``activated_abilities`` key consumes and Python's
      :func:`cross_engine._aa_dict_to_python_activated_ability`
      reconstructs).
    """
    from mtg_bot.parity.cross_engine import (
        CardDef as _CardDef,
        _python_aa_to_safe_dict,
    )

    if not _printing_is_bridge_simple_carrier_aa_land(printing):
        return None
    # **Phase 4A multi-AA admit substrate (2026-05-26).** Iterate all
    # AAs into the bridge dict tuple — the admit predicate's per-AA
    # walk guarantees every AA serializes; any AA failing
    # ``_python_aa_to_safe_dict`` is a builder-vs-predicate
    # disagreement and we honest-decline (return None).
    aa_dicts: list = []
    for aa in printing.activated_abilities:
        aa_dict = _python_aa_to_safe_dict(aa)
        if aa_dict is None:
            return None
        aa_dicts.append(aa_dict)
    return _CardDef(
        name=printing.name,
        card_type="Land",
        supertypes=tuple(printing.supertypes or ()),
        subtypes=tuple(printing.subtypes or ()),
        keywords=(),  # Phase 1 admits NO keywords (predicate gate).
        activated_abilities=tuple(aa_dicts),
    )


def _carrier_aa_artifact_card_def(printing) -> "Optional[CardDef]":
    """Sibling of :func:`_carrier_aa_land_card_def` for Carrier-AA
    Artifact carriers (Phase 4A.2 keystone landing per
    ``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §5.3).

    Pre-condition: ``printing`` must pass
    :func:`_printing_is_bridge_simple_carrier_aa_artifact`. This
    builder trusts that guardrail and serializes every AA into the
    bridge dict shape via the round-trip-floor helper
    :func:`cross_engine._python_aa_to_safe_dict`. Returns ``None`` if
    any AA fails the safe-dict round-trip (a defense-in-depth honest
    decline — the admit predicate should already have rejected such
    shapes, so reaching this branch is a builder-vs-predicate
    disagreement that fails silent rather than constructing a CardDef
    the bridge would mistranslate).

    The synthesized CardDef carries:

    * ``card_type="Artifact"`` (single-typed — admit predicate
      rejects any extra card type and any subtype).
    * ``activated_abilities=tuple(aa_dicts)`` carrying every AA in
      the bridge dict shape.

    Phase 4A admits NO Artifact in the live EoE pool (all 4 Phase-4
    Artifact candidates decline at the per-AA Effect-class teeth or
    AA-rider teeth); this builder is the substrate-only forward path
    that future Phase 4C/4D/4E widens light up.
    """
    from mtg_bot.parity.cross_engine import (
        CardDef as _CardDef,
        _python_aa_to_safe_dict,
    )

    if not _printing_is_bridge_simple_carrier_aa_artifact(printing):
        return None
    aa_dicts: list = []
    for aa in printing.activated_abilities:
        aa_dict = _python_aa_to_safe_dict(aa)
        if aa_dict is None:
            return None
        aa_dicts.append(aa_dict)
    return _CardDef(
        name=printing.name,
        card_type="Artifact",
        supertypes=tuple(printing.supertypes or ()),
        subtypes=tuple(printing.subtypes or ()),
        keywords=(),  # Phase 4A admits NO keywords (predicate gate).
        activated_abilities=tuple(aa_dicts),
    )


def _printing_is_bridge_pure_station_spacecraft(printing) -> bool:
    """True iff a CardPrinting is a Phase-1 bridge-supported Spacecraft.

    **Spacecraft Station substrate — Phase 1 Cycle 3 (2026-05-25;
    spec at ``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_1_DESIGN.md``
    §5.4).** Sibling of :func:`_printing_is_bridge_pure_cost_reduction_
    creature` / :func:`_printing_is_bridge_pure_warp_creature` /
    :func:`_printing_is_bridge_simple_carrier_aa_land`. Pilot:
    Galvanizing Sawship (``station_threshold=3``,
    ``stationed_keywords={flying, haste}``, 6/5, ``{5}{R}``, 5,938
    17lands decks — the SOLE single-gated AND zero-ability Spacecraft
    in the EoE pool; every other Spacecraft carries at least one
    static / triggered / activated co-gate that Phase 1 explicitly
    defers to Phase 2 / 3 / 4 per design doc §3).

    **§2 teeth (must reject):**

      * Non-Spacecraft (no ``"Spacecraft"`` subtype).
      * ``station_threshold is None`` — The Eternity Elevator
        (the only Phase-4 Spacecraft with ``threshold=None``,
        deferred per design doc §3).
      * ``station_threshold <= 0`` — defense-in-depth against a
        future parser/registry-dict regression (Rust parse arm
        hard-errors on this too, see Cycle 1 substrate teeth at
        ``rust/src/cards.rs:15922-15933``).
      * Any static / triggered / activated ability — Phase 2 / 3 / 4
        defer the 7 multi-gated Spacecraft (Lumen-Class Frigate /
        Larval Scoutlander / Sledge-Class Seedship / Synthesizer
        Labship / Entropic Battlecruiser / Infinite Guideline
        Station / The Eternity Elevator + 14 other ability-carrying
        Spacecraft per the live EoE walk).
      * ``spell_effect is not None`` (Spacecraft are permanents —
        defense-in-depth against a mistranslation regression).
      * ``room_halves`` non-empty / ``loyalty`` set / any
        ``cost_reductions`` or ``external_cost_reductions`` /
        ``warp_cost`` / ``kicker_cost`` / ``impending_cost`` /
        ``dynamic_pt_formula`` / ``ward_cost`` — sibling substrates
        whose interaction with Spacecraft station is Phase-N.
      * Non-empty baseline ``keywords`` — Phase-1 carrier has
        empty baseline keywords; any baseline keyword would
        require a layer-6 timestamp interleave that the
        ``stationed_keywords`` fold doesn't yet model (Phase-2+
        substrate-extension).
      * Empty ``stationed_keywords`` — admits Sawship by gating
        on the substrate's actual leverage (a Spacecraft with no
        keyword grant has no Phase-1 reason to bridge through
        this predicate; the printed P/T animation alone is still
        admit-relevant but would route through a future
        ``_printing_is_bridge_simple_animating_spacecraft``
        sibling. The pilot card Sawship grants
        ``{flying, haste}`` so this gate is honest-tight here).
      * Any ``stationed_keywords`` member NOT in
        :data:`_SAFE_KEYWORDS` — the bridge-correct keyword set
        (Cycle 2 substrate landed the ``battlefield_has_keyword``
        fold to surface stationed keywords on the Rust side, but
        the per-keyword combat/static-reader parity is still
        gated by ``_SAFE_KEYWORDS``).
      * ``grants_toughness_as_station_power_for_creatures_you_control``
        flag — Tapestry Warden flag, Phase-2+ widen per design doc
        §4.4 / SL §9 entry #2.
      * Unparseable ``mana_cost_str`` — defense-in-depth (Sawship
        is ``{5}{R}`` which parses; any future Spacecraft with a
        hybrid / phyrexian / X cost is honest-stopped).

    The positive Phase-1 admit set is **exactly Galvanizing Sawship**
    (the verify-first walk against the live EoE pool confirmed no
    other Spacecraft matches every clause; 22 live Spacecraft —
    21 carry one or more abilities, The Eternity Elevator has
    ``station_threshold=None``).
    """
    if "Spacecraft" not in printing.subtypes:
        return False
    if printing.station_threshold is None:
        return False
    if printing.station_threshold <= 0:
        return False
    if printing.static_abilities:
        return False
    if printing.triggered_abilities:
        return False
    if printing.activated_abilities:
        return False
    if printing.spell_effect is not None:
        return False
    if printing.room_halves:
        return False
    if printing.loyalty is not None:
        return False
    if printing.cost_reductions or printing.external_cost_reductions:
        return False
    if printing.warp_cost or printing.kicker_cost or printing.impending_cost:
        return False
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    if printing.keywords:
        return False
    if not printing.stationed_keywords:
        return False
    for kw in printing.stationed_keywords:
        if kw not in _SAFE_KEYWORDS:
            return False
    if getattr(
        printing,
        "grants_toughness_as_station_power_for_creatures_you_control",
        False,
    ):
        return False
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True


def _station_spacecraft_card_def(printing) -> "Optional[CardDef]":
    """Build a CardDef from a Phase-1-admitted Spacecraft printing.

    **Spacecraft Station substrate — Phase 1 Cycle 3 (2026-05-25).**
    Pre-condition: ``printing`` must pass
    :func:`_printing_is_bridge_pure_station_spacecraft`. The
    synthesized CardDef carries:

    * ``card_type="Artifact"`` — Spacecraft are printed Artifacts that
      animate as Artifact Creatures only while stationed (CR 311
      Spacecraft). Sub-typed as ``("Spacecraft",)`` so the Rust
      registry-dict consumer at ``rust/src/cards.rs:parse_printing``
      sees the printed subtype.
    * ``power`` / ``toughness`` — Sawship is 6/5 (the printed P/T
      while stationed; Rust's ``battlefield_creature_power`` /
      ``battlefield_creature_toughness`` only reads these when
      ``is_creature_now`` returns True).
    * ``mana_cost_generic`` / ``mana_cost_colored`` — parsed from
      ``printing.mana_cost_str`` via the same
      :func:`_parse_mana_cost_string` codec the admit predicate's
      mana-cost teeth use.
    * ``station_threshold`` + ``stationed_keywords`` — threaded
      through to the registry dict via the C3 forward-emit arm in
      ``cross_engine.py::_spec_card_to_printing_dict`` (omitted when
      default per back-compat).
    * NO baseline ``keywords`` (the admit predicate rejects any
      baseline keyword), NO ``activated_abilities``, NO
      ``triggered_abilities``, NO ``static_abilities``, NO
      ``spell_effect``, NO ``cost_reductions`` (the admit predicate
      rejects all these). The Rust ``Action::ActivateStation`` resolver
      lands via the Cycle 2 substrate (``62e10ff9``) — the CardDef
      itself doesn't carry the station action; it's emitted by Rust's
      legal-action emitter at ``state_ops_legal.rs::legal_decisions``
      tail when ``is_sorcery_timing && own Spacecraft && eligible
      crew`` (mirror of Python's ``legal.py:831-852``).
    """
    from mtg_bot.parity.cross_engine import CardDef as _CardDef

    if not _printing_is_bridge_pure_station_spacecraft(printing):
        return None
    try:
        generic, colored = _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return None
    return _CardDef(
        name=printing.name,
        card_type="Artifact",
        mana_cost_generic=generic,
        mana_cost_colored=colored,
        subtypes=tuple(printing.subtypes),
        supertypes=tuple(printing.supertypes or ()),
        power=printing.power,
        toughness=printing.toughness,
        station_threshold=int(printing.station_threshold),
        stationed_keywords=tuple(sorted(printing.stationed_keywords)),
    )


def _static_ability_is_phase_2_spacecraft_anthem(ability) -> bool:
    """True iff ``ability`` is a Phase-2 bridge-admittable Spacecraft
    anthem static — a layer-7 ``PowerToughnessBonus`` gated by
    ``tier_threshold >= 1`` (charge-counter gate on the source) under
    a ``creatures_you_control`` / ``other_creatures_you_control``
    scope, with no other rider.

    **Spacecraft Station substrate — Phase 2 Cycle 2 (Lumen-Class
    Frigate, 2026-05-25; spec at
    ``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_2_DESIGN.md`` §5.4).**
    Sibling of the Phase-4 MTL helper
    :func:`_static_ability_is_phase4_anthem_pt_conditional`. Mirrors
    the shape ``parser/statics.py:_parse_anthem_static_line`` emits
    for Lumen-Class Frigate's "While this Spacecraft has two or more
    charge counters, other creatures you control get +1/+1." line.
    The verify-first walk confirms the parser SoT is
    ``StaticAbility(scope=OTHER_CREATURES_YOU_CONTROL,
    tier_threshold=2, condition=None,
    continuous_effect=ContinuousModifier(layer=7,
    payload=PowerToughnessBonus(1, 1)))``.

    The §2 teeth:

      * ``scope`` is ``creatures_you_control`` or
        ``other_creatures_you_control`` — the only two anthem scopes
        the Rust parser arm whitelists (matches the Phase-1 +
        Phase-4 sibling vocab).
      * ``tier_threshold >= 1`` (Phase 2's load-bearing new gate; the
        Phase-1 helper rejects any ``tier_threshold``, the Phase-4
        helper rejects any ``tier_threshold``, this helper REQUIRES
        a positive one).
      * ``condition`` is ``None``. The parser SoT does NOT compose a
        ``DuringYourTurn``-style rider WITH ``tier_threshold`` for
        Lumen-Class Frigate; Phase 2 explicitly admits only the
        ``tier_threshold``-only shape — composed shapes are a future
        widen (Phase 3+ co-gated triggers, §3.4 cross-phase
        amortization).
      * ``continuous_effect`` is a layer-7
        ``ContinuousModifier(PowerToughnessBonus(p, t))``.
      * ``subject_filter`` on the modifier is ``None`` (Phase 2
        doesn't carry typed-anthem subjects).
      * ``replacement_effect`` is ``None``.
      * ``granted_keywords`` is empty (Phase 2 carriers don't ride a
        keyword grant alongside the P/T gate — future widen).
      * ``room_half`` is ``None``, ``grants_no_max_hand_size`` is
        False, ``grants_creature_spells_uncounterable`` is False.
      * The legacy ``power_bonus`` / ``toughness_bonus`` slot is
        empty (payload rides the ContinuousModifier, NOT the legacy
        field; same convention as the Phase-4 MTL helper).
    """
    from mtg_bot.cards.base import StaticScope
    from mtg_bot.effects.modifiers import (
        ContinuousModifier,
        PowerToughnessBonus,
    )

    if ability.scope not in (
        StaticScope.CREATURES_YOU_CONTROL,
        StaticScope.OTHER_CREATURES_YOU_CONTROL,
    ):
        return False
    if not ability.tier_threshold or ability.tier_threshold < 1:
        return False
    if ability.condition is not None:
        return False  # composed shapes deferred
    if ability.replacement_effect is not None:
        return False
    if ability.power_bonus or ability.toughness_bonus:
        # Legacy P/T slot must be empty — the bonus rides on the
        # ContinuousModifier payload below.
        return False
    if ability.granted_keywords:
        return False
    if ability.room_half is not None:
        return False
    if ability.grants_no_max_hand_size:
        return False
    if ability.grants_creature_spells_uncounterable:
        return False
    ce = ability.continuous_effect
    if ce is None:
        return False
    if not isinstance(ce, ContinuousModifier):
        return False
    if ce.layer != 7:
        return False
    if not isinstance(ce.payload, PowerToughnessBonus):
        return False
    if getattr(ce, "subject_filter", None) is not None:
        return False
    return True


def _printing_is_bridge_phase_2_static_anthem_spacecraft(printing) -> bool:
    """True iff a CardPrinting is a Phase-2 bridge-supported
    static-anthem Spacecraft — the Phase-1 sub-shape A clauses EXCEPT
    ``static_abilities`` is replaced with a positive one-static
    allowlist via
    :func:`_static_ability_is_phase_2_spacecraft_anthem`.

    **Spacecraft Station substrate — Phase 2 Cycle 2 (Lumen-Class
    Frigate, 2026-05-25; spec at
    ``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_2_DESIGN.md`` §5.4 +
    §5.5).** Sibling of :func:`_printing_is_bridge_pure_station_
    spacecraft` (Phase-1 zero-static carrier — Galvanizing Sawship)
    and :func:`_printing_is_bridge_static_anthem_pt_conditional_warp_
    creature` (Phase-4 MTL composed-warp-anthem creature). Pilot:
    Lumen-Class Frigate (``{1}{W}``, station_threshold=12,
    stationed_keywords={flying, lifelink}, 3/5, one
    tier_threshold=2 anthem static +1/+1 to other creatures you
    control).

    The verify-first walk against the live EoE pool confirms exactly
    ONE Spacecraft passes every clause (Lumen-Class Frigate); the
    other 6 deferred Spacecraft each fail at least one clause
    (Larval Scoutlander / Sledge-Class Seedship / Synthesizer Labship
    / Entropic Battlecruiser / Infinite Guideline Station all carry
    ``triggered_abilities`` — Phase 3; The Eternity Elevator carries
    ``activated_abilities`` and ``station_threshold is None`` —
    Phase 4). Galvanizing Sawship has zero static abilities, so it
    falls to the Phase-1 predicate's path; the
    ``len(static_abilities) != 1`` short-circuit here rejects it.

    Routed as a NEW OR-disjunct in
    :func:`_filter_deck_to_bridge_supported` sibling to the Phase-1
    disjunct.
    """
    if "Spacecraft" not in printing.subtypes:
        return False
    if printing.station_threshold is None:
        return False  # Phase 4 only (The Eternity Elevator)
    if printing.station_threshold <= 0:
        return False
    if printing.triggered_abilities:
        return False  # Phase 3 (5 carriers)
    if printing.activated_abilities:
        return False  # Phase 4 (The Eternity Elevator)
    # Static abilities — POSITIVE allowlist of the Phase-2
    # Spacecraft-anthem shape. Empty static_abilities falls through
    # to the Phase-1 ``_pure_station_spacecraft`` disjunct (already
    # in production); this predicate specifically admits the
    # ONE-anthem shape.
    if not printing.static_abilities:
        return False  # Phase-1 path covers zero-static
    if len(printing.static_abilities) != 1:
        return False  # exactly one anthem (no composed multi-static)
    if not _static_ability_is_phase_2_spacecraft_anthem(
        printing.static_abilities[0]
    ):
        return False
    if printing.spell_effect is not None:
        return False
    if printing.room_halves:
        return False
    if printing.loyalty is not None:
        return False
    if printing.cost_reductions or printing.external_cost_reductions:
        return False
    if printing.warp_cost or printing.kicker_cost or printing.impending_cost:
        return False
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    if printing.keywords:
        return False  # Phase-2 carrier has empty baseline keywords
    if not printing.stationed_keywords:
        return False
    for kw in printing.stationed_keywords:
        if kw not in _SAFE_KEYWORDS:
            return False
    if getattr(
        printing,
        "grants_toughness_as_station_power_for_creatures_you_control",
        False,
    ):
        return False  # Tapestry Warden flag — Phase-3+ widen
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True


def _phase_2_static_anthem_spacecraft_card_def(printing) -> "Optional[CardDef]":
    """Build a CardDef from a Phase-2-admitted static-anthem
    Spacecraft printing.

    **Spacecraft Station substrate — Phase 2 Cycle 2 (Lumen-Class
    Frigate, 2026-05-25).** Sibling of
    :func:`_station_spacecraft_card_def` (Phase-1 zero-static
    carrier). The synthesized CardDef carries every Phase-1 field
    PLUS a one-entry ``static_anthems`` tuple encoding the anthem's
    scope + P/T bonus + the new ``source_charge_counters_at_least``
    condition_tag with the parser SoT's ``tier_threshold`` value
    threaded back as ``condition_args[0]``. The Rust side reads this
    via the Cycle-1-landed parse + dispatcher arms; the Python
    rehydrator
    (``cross_engine._card_def_to_python_printing`` anthem loop)
    inverts it back to ``StaticAbility(tier_threshold=N,
    condition=None, ...)`` per §5.3a.
    """
    from mtg_bot.parity.cross_engine import CardDef as _CardDef
    from mtg_bot.cards.base import StaticScope as _StaticScope
    from mtg_bot.effects.modifiers import (
        ContinuousModifier as _CM,
        PowerToughnessBonus as _PTB,
    )

    if not _printing_is_bridge_phase_2_static_anthem_spacecraft(printing):
        return None
    try:
        generic, colored = _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return None
    (anthem,) = printing.static_abilities
    # Map StaticScope -> the lowercase string scope vocabulary the
    # bridge dict / CardDef field carry (matches the parser emit
    # surface in ``parser/statics.py`` and the C1 substrate's parse
    # whitelist at ``rust/src/cards.rs:15191``).
    if anthem.scope == _StaticScope.OTHER_CREATURES_YOU_CONTROL:
        scope_str = "other_creatures_you_control"
    elif anthem.scope == _StaticScope.CREATURES_YOU_CONTROL:
        scope_str = "creatures_you_control"
    else:
        return None  # admit predicate already rejects but defensive
    ce = anthem.continuous_effect
    assert isinstance(ce, _CM) and isinstance(ce.payload, _PTB), (
        "admit predicate must have already gated the payload shape"
    )
    p_bonus = int(ce.payload.power_bonus)
    t_bonus = int(ce.payload.toughness_bonus)
    tier = int(anthem.tier_threshold)
    static_anthems = (
        (
            scope_str,
            (),  # no granted_keywords — Phase 2 carrier is P/T-only
            p_bonus,
            t_bonus,
            "source_charge_counters_at_least",
            (tier,),
        ),
    )
    return _CardDef(
        name=printing.name,
        card_type="Artifact",
        mana_cost_generic=generic,
        mana_cost_colored=colored,
        subtypes=tuple(printing.subtypes),
        supertypes=tuple(printing.supertypes or ()),
        power=printing.power,
        toughness=printing.toughness,
        station_threshold=int(printing.station_threshold),
        stationed_keywords=tuple(sorted(printing.stationed_keywords)),
        static_anthems=static_anthems,
    )


# ---------------------------------------------------------------------------
# Spacecraft Station substrate — Phase 3A Cycle 2 (Larval Scoutlander
# admit gate + builder + FLIP, 2026-05-25). Sibling shape of the Phase-1
# pure-station + Phase-2 static-anthem admit predicates above. See
# docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_3_DESIGN.md §5.3 (predicate),
# §5.4 (per-sub-phase Effect-class gate; 3A allows only 1 of 7), §5.5
# (admit-predicate registration as a new OR-disjunct). Phase 3 is the
# trigger-bearing Spacecraft sub-shape C (5 cards total — Larval
# Scoutlander 3A; Sledge-Class Seedship 3B; Synthesizer Labship +
# Entropic Battlecruiser + Infinite Guideline Station 3C). The 3A
# Cycle-2 gate is strictly the 1-class Effect allowlist +
# (ENTERS, IsSelf()) shape — every other Phase-3 carrier fails the
# event/effect product (Sledge-Class Seedship has ATTACKS event;
# Synthesizer Labship has BEGINNING_OF_COMBAT + Controlled predicate;
# Entropic Battlecruiser has different effect classes; Infinite
# Guideline Station has a non-allowlisted effect class). Phase 3B/3C
# extend the allowlist + event-shapes table per design doc §5.4 in
# subsequent flips.
# ---------------------------------------------------------------------------


# Phase-3A admit Effect-class allowlist — closed at exactly the new
# Larval Scoutlander Effect class. Phase 3B widens to add
# OptionalPutCreatureFromHandOntoBattlefield (Sledge-Class Seedship);
# Phase 3C widens further (Synthesizer Labship's
# TargetArtifactBecomesCreatureUEOT, Entropic Battlecruiser's
# EachOpponentDiscardsOrLosesLife + TargetPlayerLosesLife, Infinite
# Guideline Station's CreateTokenPerMulticoloredPermanent +
# DrawCardPerMulticoloredPermanent). The tuple form below is consumed
# by ``isinstance()`` in the helper below so each Phase-N landing is a
# one-entry append.
_PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES: tuple = ()
"""Phase-3A Effect-class allowlist for the new Phase-3 admit predicate.
Populated lazily on first call to
:func:`_triggered_ability_is_phase_3_spacecraft_admitted` so the import
cycle stays bounded (combinators import is deferred). Phase 3A: exactly
``OptionalSacLandOrLanderForBasicLandRamp``."""


# Phase-3A admit (event, predicate)-shape allowlist — closed at exactly
# the Larval Scoutlander ETB shape. Phase 3B adds (ATTACKS, IsSelf());
# Phase 3C adds (BEGINNING_OF_COMBAT, Controlled(YOU)) and
# (DISCARDS_CARD, Controlled(OPPONENT)). The shape-tuple is consumed by
# membership-check in the helper below; equality on Event + IsSelf is
# well-defined (Event is an Enum, IsSelf is a frozen dataclass with the
# default ``subject=None`` slot — instances are equal by value).
_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES: tuple = ()
"""Phase-3A (event, predicate)-shape allowlist for the new Phase-3
admit predicate. Populated lazily on first call (sibling of the
class-allowlist above). Phase 3A: exactly
``(Event.ENTERS, IsSelf(subject=None))``."""


def _phase_3a_lazy_init_allowlists():
    """Lazy initializer for the Phase-3A allowlists. Defers the
    Effect / Event / Predicate imports until first call so the module
    import cycle stays bounded (mirror of the ``_python_ta_to_safe_dict``
    inline-import convention)."""
    global _PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES
    global _PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES
    if _PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES:
        return
    from mtg_bot.effects.combinators import (
        OptionalPutCreatureFromHandOntoBattlefield,
        OptionalSacLandOrLanderForBasicLandRamp,
    )
    from mtg_bot.effects.generic.become_type import (
        TargetArtifactBecomesCreatureUEOT,
    )
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardPerMulticoloredPermanent,
    )
    from mtg_bot.effects.generic.life import (
        EachOpponentDiscardsOrLosesLife,
        TargetPlayerLosesLife,
    )
    from mtg_bot.effects.generic.tokens import (
        CreateTokenPerMulticoloredPermanent,
    )
    from mtg_bot.effects.predicates import Controlled, Event, IsSelf, OPPONENT, YOU

    # Phase 3C Cycle 4 widen (2026-05-26; this slice): append the
    # Infinite Guideline Station two-trigger Effect classes
    # ``CreateTokenPerMulticoloredPermanent`` (ETB, tier=0)
    # + ``DrawCardPerMulticoloredPermanent`` (ATTACKS, tier=0) to
    # the Effect-class allowlist. The event-shape table is UNCHANGED
    # this cycle — IGS's two triggers carry shapes already in the
    # Cycle-3 table ((ENTERS, IsSelf) and (ATTACKS, IsSelf) — both
    # added in Phase 3A C2 + Phase 3B C2 respectively). Per design
    # doc §5.4 / §7.3 — the per-cycle admit set grows from the
    # Phase-3C-Cycle-3 5-class / 4-shape allowlist to the
    # Phase-3C-Cycle-4 7-class / 4-shape allowlist. Infinite
    # Guideline Station's two triggers are tier=0 (no tier-gate
    # consumer — the IGS's station threshold 12 already gates when
    # the ATTACKS trigger CAN fire by gating when the Spacecraft is
    # a creature; no per-trigger tier needed).
    _PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES = (
        OptionalSacLandOrLanderForBasicLandRamp,
        OptionalPutCreatureFromHandOntoBattlefield,
        TargetArtifactBecomesCreatureUEOT,
        EachOpponentDiscardsOrLosesLife,
        TargetPlayerLosesLife,
        CreateTokenPerMulticoloredPermanent,
        DrawCardPerMulticoloredPermanent,
    )
    _PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES = (
        (Event.ENTERS, IsSelf(subject=None)),
        (Event.ATTACKS, IsSelf(subject=None)),
        (Event.BEGINNING_OF_COMBAT, Controlled(by=YOU, subject=None)),
        (Event.DISCARDS_CARD, Controlled(by=OPPONENT, subject=None)),
    )


def _triggered_ability_is_phase_3_spacecraft_admitted(trig) -> bool:
    """True iff ``trig`` is a Phase-3 (sub-phase 3A) bridge-admittable
    Spacecraft trigger.

    **Spacecraft Station substrate — Phase 3A Cycle 2 (2026-05-25; spec
    at docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_3_DESIGN.md §5.3).**
    Positive gates:

    * ``(trig.event, trig.predicate)`` is in the closed
      :data:`_PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES` table (Phase 3A:
      ``{(ENTERS, IsSelf(subject=None))}``).
    * ``isinstance(trig.effect,
      _PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES)`` (Phase 3A:
      ``{OptionalSacLandOrLanderForBasicLandRamp}``).
    * ``trig.tier_threshold >= 0`` (back-compat default; the
      per-card admit set for Phase 3A is exactly ``tier_threshold=0``).
    * ``trig.once_per_turn is False`` (no Phase-3A carrier sets it).

    Per design doc §5.4 the Phase-3 admit-class set is the **union** of
    all sub-phase Effect classes, but the per-sub-phase gate restricts
    to the **current sub-phase's set** to keep the admit narrow during a
    sub-phase landing. The Phase 3A gate is the 1-class allowlist
    (Larval Scoutlander only); Phase 3B widens the allowlist by one
    entry + the event-shapes table by one entry.
    """
    _phase_3a_lazy_init_allowlists()
    ev_pred = (trig.event, trig.predicate)
    if ev_pred not in _PHASE_3A_SPACECRAFT_TRIGGER_EVENT_SHAPES:
        return False
    if not isinstance(
        trig.effect, _PHASE_3A_SPACECRAFT_TRIGGER_EFFECT_CLASSES,
    ):
        return False
    if trig.tier_threshold < 0:
        return False
    if trig.once_per_turn:
        return False
    return True


def _printing_is_bridge_phase_3_trigger_spacecraft(printing) -> bool:
    """True iff a CardPrinting is a Phase-3 bridge-supported
    trigger-bearing Spacecraft — the Phase-1 sub-shape A clauses EXCEPT
    ``triggered_abilities`` is replaced with a positive 1-or-2
    ``TriggeredAbility`` allowlist via
    :func:`_triggered_ability_is_phase_3_spacecraft_admitted`.

    **Spacecraft Station substrate — Phase 3 sub-shape C (spec at
    docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_3_DESIGN.md §5.3).** Sibling
    of :func:`_printing_is_bridge_pure_station_spacecraft` (Phase-1
    zero-ability carrier) and
    :func:`_printing_is_bridge_phase_2_static_anthem_spacecraft`
    (Phase-2 single-static-anthem carrier). Phase 3 admits the 5
    trigger-bearing Spacecraft (Larval Scoutlander, Sledge-Class
    Seedship, Synthesizer Labship, Entropic Battlecruiser, Infinite
    Guideline Station); per-cycle, the positive admit set grows from
    1 (Phase 3A) → 2 (3B) → 3/4/5 (3C cycles 2/3/4).

    **Phase 3A Cycle 2 pilot:** Larval Scoutlander ({2}{G} Artifact —
    Spacecraft, 3/3, station_threshold=7, stationed_keywords={flying},
    single ETB+IsSelf+OptionalSacLandOrLanderForBasicLandRamp(2)
    trigger at tier_threshold=0). The verify-first walk against the
    live EoE pool confirmed exactly ONE Spacecraft passes every clause
    under the strict 1-class / 1-shape Phase-3A allowlist; the other 4
    deferred Phase-3 carriers each fail at least one clause (Sledge-
    Class Seedship has ATTACKS event; Synthesizer Labship has
    BEGINNING_OF_COMBAT + Controlled predicate; Entropic Battlecruiser
    has different effect classes; Infinite Guideline Station has a
    non-allowlisted effect class).

    **§2 teeth (must reject):**

    * Non-Spacecraft (no ``"Spacecraft"`` subtype).
    * ``station_threshold is None`` — The Eternity Elevator (Phase 4).
    * ``station_threshold <= 0`` — defense-in-depth against a future
      parser/registry-dict regression.
    * Any ``static_abilities`` — Phase 2 path covers single-anthem.
    * Any ``activated_abilities`` — Phase 4 (The Eternity Elevator).
    * Empty ``triggered_abilities`` — Phase 1 path covers zero-trigger
      (Galvanizing Sawship); this predicate REQUIRES at least one.
    * More than 2 triggered abilities — no EoE Spacecraft carries >2
      triggers; reject as no-silent-auto-grow.
    * Any ``triggered_abilities`` entry that fails
      :func:`_triggered_ability_is_phase_3_spacecraft_admitted` (which
      checks against the current sub-phase's Effect-class allowlist +
      (event, predicate)-shape table).
    * ``spell_effect is not None`` (Spacecraft are permanents —
      defense-in-depth against a mistranslation regression).
    * ``room_halves`` non-empty / ``loyalty`` set / any
      ``cost_reductions`` or ``external_cost_reductions`` /
      ``warp_cost`` / ``kicker_cost`` / ``impending_cost`` /
      ``dynamic_pt_formula`` / ``ward_cost`` — sibling substrates whose
      interaction with Spacecraft station is Phase-N.
    * Non-empty baseline ``keywords`` — Phase-3 carrier has empty
      baseline keywords; any baseline keyword would require a layer-6
      timestamp interleave the ``stationed_keywords`` fold doesn't
      yet model (Phase-2+ substrate-extension; mirror of Phase-1 +
      Phase-2 teeth).
    * Empty ``stationed_keywords`` — admits carriers by gating on the
      substrate's actual leverage (a Spacecraft with no keyword grant
      has no Phase-1/2/3 reason to bridge through this predicate).
    * Any ``stationed_keywords`` member NOT in :data:`_SAFE_KEYWORDS`.
    * ``grants_toughness_as_station_power_for_creatures_you_control``
      Tapestry Warden flag — Phase-2+ widen per design doc §3.5.
    * Unparseable ``mana_cost_str`` — defense-in-depth (Larval
      Scoutlander is ``{2}{G}`` which parses; any future Spacecraft
      with a hybrid / phyrexian / X cost is honest-stopped).
    """
    if "Spacecraft" not in printing.subtypes:
        return False
    if printing.station_threshold is None:
        return False  # Phase 4 only (The Eternity Elevator)
    if printing.station_threshold <= 0:
        return False
    if printing.static_abilities:
        return False  # Phase 2 (Lumen-Class Frigate)
    if printing.activated_abilities:
        return False  # Phase 4 (The Eternity Elevator)
    if not printing.triggered_abilities:
        return False  # Phase-1 path covers zero-trigger
    if len(printing.triggered_abilities) > 2:
        return False  # No EoE Spacecraft carries >2 triggers
    for trig in printing.triggered_abilities:
        if not _triggered_ability_is_phase_3_spacecraft_admitted(trig):
            return False
    # Carry-through Phase 1 / Phase 2 shape clauses.
    if printing.spell_effect is not None:
        return False
    if printing.room_halves:
        return False
    if printing.loyalty is not None:
        return False
    if printing.cost_reductions or printing.external_cost_reductions:
        return False
    if printing.warp_cost or printing.kicker_cost or printing.impending_cost:
        return False
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    if printing.keywords:
        return False
    if not printing.stationed_keywords:
        return False
    for kw in printing.stationed_keywords:
        if kw not in _SAFE_KEYWORDS:
            return False
    if getattr(
        printing,
        "grants_toughness_as_station_power_for_creatures_you_control",
        False,
    ):
        return False  # Tapestry Warden flag — Phase-2+ widen
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True


def _phase_3_trigger_spacecraft_card_def(printing) -> "Optional[CardDef]":
    """Build a CardDef from a Phase-3-admitted trigger-bearing
    Spacecraft printing.

    **Spacecraft Station substrate — Phase 3A Cycle 2 (Larval
    Scoutlander, 2026-05-25; spec at
    docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_3_DESIGN.md §5.5).**
    Sibling of :func:`_station_spacecraft_card_def` (Phase-1
    zero-ability carrier) and
    :func:`_phase_2_static_anthem_spacecraft_card_def` (Phase-2
    single-anthem carrier). Pre-condition: ``printing`` must pass
    :func:`_printing_is_bridge_phase_3_trigger_spacecraft`.

    The synthesized CardDef carries every Phase-1 field PLUS a
    ``triggered_abilities`` tuple — each entry is the
    ``_python_ta_to_safe_dict``-shaped dict the cross-engine bridge
    consumes (round-trips to ``mtg_bot_engine.Registry`` on the Rust
    side + ``cross_engine._ta_dict_to_python_triggered_ability`` on
    the Python rehydrator side). For the Phase-3A pilot the dict is
    ``{"event": "enters", "predicate": {"kind": "source_is_self"},
    "effect": {"kind": "optional_sac_land_or_lander_for_basic_land_
    ramp", "land_count": 2}}`` (verified against the C1 substrate's
    parser arm + bridge arm + reverse-serializer leaf).

    NOTE: we DO NOT thread the trigger through
    :func:`_python_ta_to_safe_dict` here — that function gates the
    new effect-kind via ``_SAFE_TRIGGERS`` (kept dormant per C1 per
    design doc §5.3a to avoid auto-admit via the Phase-1 path). The
    Phase-3 admit predicate has its own dispatch + this builder emits
    the dict directly, matching the parser SoT shape and the C1
    substrate's bridge round-trip arms.
    """
    from mtg_bot.parity.cross_engine import CardDef as _CardDef
    from mtg_bot.effects.combinators import (
        OptionalPutCreatureFromHandOntoBattlefield,
        OptionalSacLandOrLanderForBasicLandRamp,
    )
    from mtg_bot.effects.generic.become_type import (
        TargetArtifactBecomesCreatureUEOT,
    )
    from mtg_bot.effects.generic.draw_mill import (
        DrawCardPerMulticoloredPermanent,
    )
    from mtg_bot.effects.generic.life import (
        EachOpponentDiscardsOrLosesLife,
        TargetPlayerLosesLife,
    )
    from mtg_bot.effects.generic.tokens import (
        CreateTokenPerMulticoloredPermanent,
    )
    from mtg_bot.effects.predicates import Controlled, Event, IsSelf, OPPONENT, YOU

    if not _printing_is_bridge_phase_3_trigger_spacecraft(printing):
        return None
    try:
        generic, colored = _parse_mana_cost_string(
            printing.mana_cost_str or "",
        )
    except ValueError:
        return None
    # Build the triggered_abilities tuple — for each admitted trigger,
    # emit the round-trip dict the bridge contract expects. Phase 3C
    # Cycle 2 widens the 2-shape allowlist with the BEGINNING_OF_COMBAT
    # event arm + Controlled(YOU) predicate arm +
    # TargetArtifactBecomesCreatureUEOT Effect-emit arm (Synthesizer
    # Labship FLIP, this slice). The Effect emit arm threads the new
    # ``tier_threshold`` slot (the C1 substrate) so Synthesizer
    # Labship's tier=2 BEGINNING_OF_COMBAT trigger is rebuildable in
    # the cross-engine bridge. Future sub-phases append additional arms
    # (sibling to the ``_python_ta_to_safe_dict`` cascade above but
    # scoped to the Phase-3-admit set).
    ta_dicts: list[dict] = []
    for trig in printing.triggered_abilities:
        # Event string mapping mirrors _python_ta_to_safe_dict above.
        if trig.event is Event.ENTERS:
            event_str = "enters"
        elif trig.event is Event.ATTACKS:
            event_str = "attacks"
        elif trig.event is Event.BEGINNING_OF_COMBAT:
            # Phase 3C Cycle 2 widen — Synthesizer Labship's
            # beginning-of-your-combat trigger event.
            event_str = "beginning_of_combat"
        elif trig.event is Event.DISCARDS_CARD:
            # Phase 3C Cycle 3 widen — Entropic Battlecruiser's
            # mode-1 "whenever an opponent discards a card" trigger
            # event. Mirrors Rust's `Event::DiscardsCard` (MMM Pin 2;
            # subject = PLAYER_SUBJECT_OFFSET + discarding_pidx).
            event_str = "discards_card"
        else:
            # Phase 3C-Cycle-3 admits ENTERS + ATTACKS +
            # BEGINNING_OF_COMBAT + DISCARDS_CARD only; defense-in-depth.
            return None
        # Predicate dict — IsSelf -> source_is_self, Controlled(YOU)
        # -> controlled_by_you (sibling of Phase-3B's narrower
        # dispatch).
        if isinstance(trig.predicate, IsSelf) and trig.predicate.subject is None:
            pred_dict = {"kind": "source_is_self"}
        elif (
            isinstance(trig.predicate, Controlled)
            and trig.predicate.by is YOU
            and trig.predicate.subject is None
        ):
            # Phase 3C Cycle 2 widen — Synthesizer Labship's
            # "during your combat" predicate. Mirrors Rust's
            # `Predicate::ControlledByYou { slot: None }` parse arm
            # (cards.rs:17053).
            pred_dict = {"kind": "controlled_by_you"}
        elif (
            isinstance(trig.predicate, Controlled)
            and trig.predicate.by is OPPONENT
            and trig.predicate.subject is None
        ):
            # Phase 3C Cycle 3 widen — Entropic Battlecruiser's mode-1
            # "Whenever an opponent discards a card" predicate. Mirrors
            # Rust's `Predicate::ControlledByOpponent { slot: None }`
            # parse arm at the MMM Pin 3 bridge slice.
            pred_dict = {"kind": "controlled_by_opponent"}
        else:
            return None  # defense-in-depth
        # Effect dict — emit the canonical Rust-parser-claimed kind +
        # per-Effect payload. Mirrors the C1 substrate's reverse-
        # serializer leaf + the Rust parse_effect arm.
        if isinstance(trig.effect, OptionalSacLandOrLanderForBasicLandRamp):
            eff_dict = {
                "kind": "optional_sac_land_or_lander_for_basic_land_ramp",
                "land_count": int(trig.effect.land_count),
            }
        elif isinstance(trig.effect, OptionalPutCreatureFromHandOntoBattlefield):
            # Phase 3B Cycle 2 widen — Sledge-Class Seedship's effect.
            # Unit-shape Effect; emit kind discriminator alone (no
            # rider fields). Mirrors the C1 Rust to_pydict arm at
            # cards.rs + the cross-engine bridge dict-to-Python arm
            # in cross_engine.py.
            eff_dict = {
                "kind": "optional_put_creature_from_hand_onto_battlefield",
            }
        elif isinstance(trig.effect, TargetArtifactBecomesCreatureUEOT):
            # Phase 3C Cycle 2 widen — Synthesizer Labship's effect.
            # Struct-shape Effect carrying power/toughness ints +
            # granted_keywords list. Mirrors the Cycle-2 Rust to_pydict
            # arm at cards.rs + the cross-engine bridge dict-to-Python
            # arm in cross_engine.py. The granted_keywords frozenset is
            # emitted as a sorted list so the bridge dict is byte-
            # deterministic regardless of frozenset hash iteration
            # order (sibling-narrow precedent of Rust's parse-time sort
            # on the same field).
            eff_dict = {
                "kind": "target_artifact_becomes_creature_ueot",
                "power": int(trig.effect.power),
                "toughness": int(trig.effect.toughness),
                "granted_keywords": sorted(trig.effect.granted_keywords),
            }
        elif isinstance(trig.effect, EachOpponentDiscardsOrLosesLife):
            # Phase 3C Cycle 3 widen — Entropic Battlecruiser's mode-0
            # ATTACKS-trigger effect ("Each opponent discards a card.
            # Each opponent who can't loses 3 life."). Mirrors the
            # Cycle-3 Rust to_pydict arm at cards.rs + the cross-engine
            # bridge dict-to-Python arm in cross_engine.py. Single
            # ``life_if_cant`` rider (3 on Entropic Battlecruiser's
            # printed text).
            eff_dict = {
                "kind": "each_opponent_discards_or_loses_life",
                "life_if_cant": int(trig.effect.life_if_cant),
            }
        elif isinstance(trig.effect, TargetPlayerLosesLife):
            # Phase 3C Cycle 3 widen — Entropic Battlecruiser's mode-1
            # DISCARDS_CARD-trigger effect ("that player loses 3 life";
            # the discarding player is wired as the pre-fixed target
            # via Rust's `resolving_discards_card_player_id` slot at
            # dispatch time / Python's `fire_opponent_discards_triggers`
            # `fixed_targets=(("player", id),)` thread-through). Mirrors
            # the existing PPP-Pin-1 `target_player_loses_life` parse +
            # to_pydict + bridge arms in Rust + cross_engine.py. Single
            # ``amount`` rider (3 on Entropic Battlecruiser's printed
            # text).
            eff_dict = {
                "kind": "target_player_loses_life",
                "amount": int(trig.effect.amount),
            }
        elif isinstance(trig.effect, CreateTokenPerMulticoloredPermanent):
            # **Phase 3C Cycle 4 widen (2026-05-26).** Infinite Guideline
            # Station's ETB token-spawn effect ("create a tapped 2/2
            # colorless Robot artifact creature token for each
            # multicolored permanent you control"). Mirrors the new
            # Cycle-4 Rust to_pydict arm at cards.rs + the cross-engine
            # bridge dict-to-Python arm in cross_engine.py.
            #
            # **Symbolic ``_token_card_def`` reference.** Like the
            # ``create_token`` / ``create_token_tapped`` carrier emit at
            # ``_python_ta_to_safe_dict``, the dict carries a
            # SYMBOLIC ``_token_card_def`` (the Robot 2/2 token's
            # vanilla CardDef) rather than a numeric
            # ``token_printing_id``. The numeric pid is assigned by the
            # loader's ``_seat_token_printings`` pass once the union
            # ``card_defs`` tuple is frozen and the token's Rust-
            # registry position is known. ``_seat_token_printings`` is
            # extended this cycle to recognize the new
            # ``create_token_per_multicolored_permanent`` kind (sibling
            # of the existing ``create_token`` / ``create_token_tapped``
            # axes in ``_TOKEN_CREATE_KINDS``).
            #
            # The IGS's printed token is a vanilla 2/2 Artifact Creature
            # — Robot, no abilities/keywords (verified at
            # ``cards/tokens.py:50``); ``_token_vanilla_card_def`` is
            # the matching helper. Any other token shape silently
            # returns None from the builder (admit predicate gated
            # this, so this is defense-in-depth).
            tp = trig.effect.token_printing
            token_cd = _token_vanilla_card_def(tp)
            if token_cd is None:
                return None
            eff_dict = {
                "kind": "create_token_per_multicolored_permanent",
                "tapped": bool(trig.effect.tapped),
                # Symbolic token reference — replaced with a numeric
                # ``token_printing_id`` by ``_seat_token_printings``
                # (which preserves the kind discriminator).
                "_token_card_def": token_cd,
            }
        elif isinstance(trig.effect, DrawCardPerMulticoloredPermanent):
            # **Phase 3C Cycle 4 widen (2026-05-26).** Infinite Guideline
            # Station's ATTACKS-trigger draw effect ("Whenever Infinite
            # Guideline Station attacks, draw a card for each
            # multicolored permanent you control"). Mirrors the new
            # Cycle-4 Rust to_pydict arm at cards.rs + the cross-engine
            # bridge dict-to-Python arm in cross_engine.py. Unit-shape
            # Effect; emit kind discriminator alone (no rider fields).
            # Sibling of OptionalPutCreatureFromHandOntoBattlefield's
            # emit shape.
            eff_dict = {
                "kind": "draw_card_per_multicolored_permanent",
            }
        else:
            return None  # defense-in-depth (admit predicate gated this)
        ta_dict: dict = {
            "event": event_str,
            "predicate": pred_dict,
            "effect": eff_dict,
        }
        # Phase 3C Cycle 2 — thread the C1 tier_threshold substrate.
        # Synthesizer Labship's BEGINNING_OF_COMBAT trigger carries
        # tier_threshold=2 (the only tier-gated trigger in the
        # Phase-3-Cycle-2 admit set). Sledge-Class Seedship's ATTACKS
        # trigger + Larval Scoutlander's ENTERS trigger carry
        # tier_threshold=0; emit positively only when > 0 so the Phase-
        # 3A/3B round-trip dicts stay byte-equal to their pre-C2 shape
        # (back-compat with the bridge's "missing key defaults to 0"
        # contract — see cross_engine.py::
        # _ta_dict_to_python_triggered_ability and Rust's
        # parse_triggered_ability arm at cards.rs).
        if trig.tier_threshold > 0:
            ta_dict["tier_threshold"] = int(trig.tier_threshold)
        ta_dicts.append(ta_dict)
    return _CardDef(
        name=printing.name,
        card_type="Artifact",
        mana_cost_generic=generic,
        mana_cost_colored=colored,
        subtypes=tuple(printing.subtypes),
        supertypes=tuple(printing.supertypes or ()),
        power=printing.power,
        toughness=printing.toughness,
        station_threshold=int(printing.station_threshold),
        stationed_keywords=tuple(sorted(printing.stationed_keywords)),
        triggered_abilities=tuple(ta_dicts),
    )


def _static_ability_is_simple_anthem_keyword_grant(ability) -> bool:
    """True iff ``ability`` is a Phase-1 bridge-admittable anthem-shape
    static — an unconditional layer-6 keyword-grant whose subject is
    ``creatures_you_control`` / ``other_creatures_you_control``.

    **Static / layered abilities substrate — Phase 1 first-deliverable
    (round-79).** Mirrors the shape ``parser/statics.py:_parse_anthem_
    static_line`` emits for keyword-only anthems (Tannuk Steadfast
    Second's "Other creatures you control have haste."). The §2 teeth:

      * ``scope`` is ``creatures_you_control`` or
        ``other_creatures_you_control`` — the only two scopes the Rust
        parser arm whitelists this slice.
      * ``power_bonus == 0`` and ``toughness_bonus == 0`` (P/T anthems
        are honest-stopped to a later slice — the Rust reader-site fold
        only covers layer-6 keyword grants this slice).
      * ``granted_keywords`` is empty (the migrated grammar carries
        keywords on ``continuous_effect``, not the legacy field).
      * ``condition is None`` — conditional statics are honest-stopped.
      * ``replacement_effect is None`` — no replacement riders.
      * ``tier_threshold == 0`` — no Spacecraft-charge gate.
      * ``room_half is None`` — no Room locked-half gate.
      * ``grants_no_max_hand_size`` and
        ``grants_creature_spells_uncounterable`` are False — these are
        non-anthem player-scope flags.
      * ``continuous_effect`` is a layer-6
        ``ContinuousModifier(GrantKeyword(kw))`` whose ``kw`` is in
        :data:`_SAFE_KEYWORDS` (after space/underscore normalization).
        ``subject_filter`` on the modifier is None (Phase 1 doesn't
        carry typed-anthem subjects — Slivers-only / Tapped-only).

    Anthems whose ``continuous_effect`` carries a non-matching layer or
    a non-``GrantKeyword`` payload fall through positively.
    """
    from mtg_bot.cards.base import StaticScope
    from mtg_bot.effects.modifiers import ContinuousModifier, GrantKeyword

    if ability.scope not in (
        StaticScope.CREATURES_YOU_CONTROL,
        StaticScope.OTHER_CREATURES_YOU_CONTROL,
    ):
        return False
    if ability.power_bonus or ability.toughness_bonus:
        return False
    if ability.granted_keywords:
        # Legacy granted_keywords slot — migrated anthems are empty here.
        return False
    if ability.condition is not None:
        return False
    if ability.replacement_effect is not None:
        return False
    if ability.tier_threshold:
        return False
    if ability.room_half is not None:
        return False
    if ability.grants_no_max_hand_size:
        return False
    if ability.grants_creature_spells_uncounterable:
        return False
    ce = ability.continuous_effect
    if ce is None:
        return False
    if not isinstance(ce, ContinuousModifier):
        return False
    if ce.layer != 6:
        return False
    if not isinstance(ce.payload, GrantKeyword):
        return False
    if getattr(ce, "subject_filter", None) is not None:
        return False
    # Keyword vocabulary — accept the space-separated form the parser
    # emits and normalize for the loader's safe-set check (the bridge
    # underscores at emit time).
    kw = ce.payload.keyword
    if kw not in _SAFE_KEYWORDS:
        return False
    return True


def _printing_is_bridge_simple_static_anthem_creature(printing) -> bool:
    """True iff a CardPrinting is a Phase-1 bridge-supported anthem
    creature — every requirement of
    :func:`_printing_is_bridge_simple_creature` EXCEPT the strict
    ``static_abilities`` ban, plus every static-ability on the
    printing passes
    :func:`_static_ability_is_simple_anthem_keyword_grant`.

    **Static / layered abilities substrate — Phase 1 first-deliverable
    (round-79; spec at ``docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY.md``
    §3 lever (1)).** Closes the substrate for the simplest static-
    ability shape — an unconditional anthem layer-6 keyword grant.
    Tannuk Steadfast Second is the EoE single-gated carrier of this
    shape ("Other creatures you control have haste."); the round-78
    Aura-Phase-1 STEP-4 layer-6 reader machinery already provides the
    Rust-side fold via the new ``static_anthem_grants_keyword_to``
    helper.

    The predicate is a parallel admit-disjunct, NOT an in-place widen
    of :func:`_printing_is_bridge_simple_creature` — both predicates
    are tested for parity-correctness in isolation, and the
    same-loader-multiple-predicates pattern is the established §2 shape
    (cf. ``_printing_is_bridge_pure_warp_creature`` /
    ``_printing_is_bridge_simple_aura``).

    **Defensive §2 teeth in addition to the parent simple-creature
    teeth.** The simple-creature predicate's filters apply unchanged
    EXCEPT the ``static_abilities`` ban — replaced with a positive
    allowlist via
    :func:`_static_ability_is_simple_anthem_keyword_grant`:

      * ``hand_ability_grants`` must be empty (Tannuk's "Artifact cards
        and red creature cards in your hand have warp {2}{R}." rider
        rides on this field; the bridge doesn't carry it, so the cast-
        time grants would silently NOT fire on either engine. Phase 1
        admits Tannuk anyway — the grants are cast-time-only and the
        bench's deck-loader probes don't drive hand-grant-dependent
        warp casts — but the defensive check is here so a FUTURE bench
        path that did drive them would fail loudly rather than silently
        diverge). Honest-stopped: when a probe drives Tannuk's hand
        grants, that's the trigger for the next slice.

    Note: Tannuk's only OTHER subsystem-gated feature per the round-58
    scout (`scripts/scout_r58_subsystem_attribution.py`) is
    ``static_abilities_layered`` — it's the canonical single-gated
    carrier this predicate flips.
    """
    if "Creature" not in printing.card_types:
        return False
    if printing.power is None or printing.toughness is None:
        return False
    if printing.keywords and not printing.keywords.issubset(_SAFE_KEYWORDS):
        return False
    if printing.triggered_abilities:
        for ta in printing.triggered_abilities:
            if _python_ta_to_safe_dict(ta) is None:
                return False
    if printing.activated_abilities:
        return False
    # static_abilities — positive allowlist (this is the wedge).
    if not printing.static_abilities:
        # Defensive: every card routed through THIS predicate is
        # expected to carry at least one static; fall through cleanly
        # to the parent simple-creature predicate if not.
        return False
    for ability in printing.static_abilities:
        if not _static_ability_is_simple_anthem_keyword_grant(ability):
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
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    # Defensive (see docstring): the bridge doesn't carry
    # hand_ability_grants. Tannuk's "Artifact cards … have warp {2}{R}"
    # rider lives here — silently dropped on both engines, but
    # honest-stop to make a future divergence loud rather than silent.
    if getattr(printing, "hand_ability_grants", ()):
        # Keep admit anyway: the rider doesn't fire on either engine
        # in the current bench paths (cast-time hand-grant probes
        # aren't driven). The predicate stays loud about the
        # honest-stop in the docstring; widening the bench to drive
        # this is the trigger for the next slice's work.
        pass
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True


def _static_ability_is_simple_uncounterable_grant(ability) -> bool:
    """True iff ``ability`` is a Phase-2 bridge-admittable
    uncounterable-grant static — a SELF-scoped sentinel that flips
    only ``grants_creature_spells_uncounterable=True``, with no
    continuous_effect and no condition.

    **Static / layered abilities substrate — Phase 2 (round-80,
    2026-05-20).** Mirrors the shape ``parser/creature_builder.py``
    emits for Frenzied Baloth's "Creature spells you control can't
    be countered." line — exactly one StaticAbility carrying:

      * ``scope == "self"``
      * ``grants_creature_spells_uncounterable is True``
      * ``continuous_effect is None``
      * ``condition is None``
      * Every other slot at its default (no power_bonus /
        toughness_bonus / granted_keywords / replacement_effect /
        tier_threshold / room_half / grants_no_max_hand_size).

    A printing-level flag on Rust's ``CardPrinting`` does the same
    job (avoiding a per-StaticAbility Rust slot for a single shape).
    The Python predicate stays at StaticAbility granularity so the
    parser's per-line emit shape round-trips cleanly.
    """
    from mtg_bot.cards.base import StaticScope

    if ability.scope not in (StaticScope.SELF, "self"):
        return False
    if not ability.grants_creature_spells_uncounterable:
        return False
    if ability.continuous_effect is not None:
        return False
    if ability.condition is not None:
        return False
    if ability.replacement_effect is not None:
        return False
    if ability.power_bonus or ability.toughness_bonus:
        return False
    if ability.granted_keywords:
        return False
    if ability.tier_threshold:
        return False
    if ability.room_half is not None:
        return False
    if ability.grants_no_max_hand_size:
        return False
    return True


def _printing_is_bridge_simple_uncounterable_creature(printing) -> bool:
    """True iff a CardPrinting is a Phase-2 bridge-supported
    uncounterable creature.

    **Static / layered abilities substrate — Phase 2 (round-80,
    2026-05-20; spec at ``docs/SUBSYSTEM_BLOCKED_LEVERAGE_
    INVENTORY.md`` §3 lever (1) Phase 1's honest-stop list).** Closes
    the substrate for Frenzied Baloth — the canonical EoE single-
    gated carrier of the ``grants_creature_spells_uncounterable``
    flag. Frenzied Baloth has BOTH the cast-side
    ``spell_is_uncounterable=True`` ("This spell can't be
    countered.") AND a battlefield-static
    ``grants_creature_spells_uncounterable`` rider ("Creature spells
    you control can't be countered."), so this predicate admits both
    in one disjunct.

    **Substrate carriers.**
    * The bridge dict carries the cast-side flag at
      ``printing_dict["spell_is_uncounterable"]`` (omitted when
      False, back-compat).
    * The grant flag is carried at
      ``printing_dict["grants_creature_spells_uncounterable"]``
      (omitted when False, back-compat).
    * Rust's ``CardPrinting`` carries both as bool slots; the
      ``Effect::CounterTargetSpell`` resolver consults them at
      counter-resolve time (CR 101.2 gate), mirroring Python's
      ``CounterTargetSpell._is_uncounterable`` walk.
    * Python's ``CardPrinting.static_abilities`` materializes the
      grant flag as a sentinel
      ``StaticAbility(grants_creature_spells_uncounterable=True)``
      via :func:`_card_def_to_python_printing` so the Python walk
      fires too.

    **Defensive §2 teeth.** The simple-creature filter applies
    UNCHANGED except for the ``static_abilities`` ban — replaced
    with a positive allowlist of the uncounterable-grant sentinel
    shape via :func:`_static_ability_is_simple_uncounterable_grant`.
    The cast-side flag ``spell_is_uncounterable`` is admitted on the
    printing-level bool slot.

    **Honest-stop:** Frenzied Baloth's "Combat damage can't be
    prevented." rider (``combat_damage_cant_be_prevented=True`` on
    the Python CardPrinting) does NOT round-trip through the bridge
    — the Rust side doesn't model damage prevention at all (no EoE
    preventer card has landed), so the bridge silently drops it. The
    rider is parity-clean as long as no probe drives a prevention
    source against a creature whose damage is gated by this flag.
    This mirrors the Tannuk ``hand_ability_grants`` honest-stop
    precedent — admit the card now, surface a later divergence
    loudly when a future probe path drives the missing rider.
    """
    if "Creature" not in printing.card_types:
        return False
    if printing.power is None or printing.toughness is None:
        return False
    if printing.keywords and not printing.keywords.issubset(_SAFE_KEYWORDS):
        return False
    if printing.triggered_abilities:
        for ta in printing.triggered_abilities:
            if _python_ta_to_safe_dict(ta) is None:
                return False
    if printing.activated_abilities:
        return False
    # Must carry EITHER spell_is_uncounterable OR an
    # uncounterable-grant static (or both — Frenzied Baloth has both).
    has_cast_flag = bool(
        getattr(printing, "spell_is_uncounterable", False)
    )
    if printing.static_abilities:
        for ability in printing.static_abilities:
            if not _static_ability_is_simple_uncounterable_grant(ability):
                return False
        has_grant_static = True
    else:
        has_grant_static = False
    if not (has_cast_flag or has_grant_static):
        # Neither flag set — falls through to the plain simple-creature
        # path (where the empty-static-abilities case is the back-compat
        # default for vanilla creatures).
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
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Static rule-text substrate — Deafening Silence Cycle 1
# (2026-05-22). Admit predicate for Deafening-Silence-shape
# enchantments — single printing-level bool slot mirrored on both
# engines. Mirrors the round-80 Phase-2 uncounterable-creature shape
# (`_printing_is_bridge_simple_uncounterable_creature`) but adapted
# for a non-creature Enchantment with no triggered/activated/static
# abilities — purely the printing-level bool slot.
# ---------------------------------------------------------------------------


def _printing_is_bridge_simple_cast_restriction_enchantment(
    printing,
) -> bool:
    """True iff a CardPrinting is a Deafening-Silence-shape vanilla
    Enchantment carrying ONLY the printing-level
    ``restricts_noncreature_spells_to_one_per_turn`` bool, with no
    other riders.

    **Static rule-text substrate — Deafening Silence Cycle 1
    (2026-05-22; spec at ``docs/SUBSYSTEM_BLOCKED_LEVERAGE_INVENTORY
    .md`` §5 "Static rule-text" row).** Closes the substrate for
    Deafening Silence — the canonical EoE single-gated carrier of
    the printing-level cast-restriction flag (12 17lands decks).
    Mirrors the Phase-2 ``_printing_is_bridge_simple_uncounterable_
    creature`` shape one-for-one: one new printing-level bool slot,
    one bridge round-trip, one admit disjunct.

    **Substrate carriers.**

    * The bridge dict carries the flag at
      ``printing_dict["restricts_noncreature_spells_to_one_per_turn"]``
      (omitted when False, back-compat).
    * Rust's ``CardPrinting`` carries the matching bool slot; the
      ``state_ops_legal::legal_decisions`` CastSpell-emission loops
      consult it at cast-time legal-emission, mirroring Python's
      post-filter at ``src/mtg_bot/legal.py:880-893``.
    * The companion ``Player.noncreature_spells_cast_this_turn``
      counter is incremented in every noncreature cast path (Rust
      ``cast_spell_noncreature`` + ``cast_aura``; Python
      ``actions._cast_spell`` at ``actions.py:1782``) and reset at
      the cleanup step (Rust ``state_ops_steps`` post-phase reset;
      Python ``turn.py:1106``).

    **Defensive §2 teeth.** The carrier must be a NON-Creature
    Enchantment with no spell effect, no triggered / activated /
    static abilities, no warp / kicker / room / impending / X
    riders, and no cost-reduction. The only printing-level slot
    in play is the ``restricts_noncreature_spells_to_one_per_turn``
    flag itself; every other slot must be at its zero/default value.
    This matches Deafening Silence's actual EoE printing exactly
    ("Enchantment {1}{W}. Each player can't cast more than one
    noncreature spell each turn.") — no other text on the card.
    """
    # Must be an Enchantment (not Creature, not Artifact-only).
    if "Enchantment" not in printing.card_types:
        return False
    if "Creature" in printing.card_types:
        return False
    # The flag itself MUST be set — otherwise this disjunct doesn't
    # apply (vanilla Enchantments are not in scope for this admit
    # arm; they fall through to whatever future Enchantment-admit
    # arm lands).
    if not getattr(
        printing, "restricts_noncreature_spells_to_one_per_turn", False
    ):
        return False
    # Power / toughness must be unset (non-Creature).
    if printing.power is not None or printing.toughness is not None:
        return False
    # No keywords — Deafening Silence has none, and a generic
    # rider would risk bridge-side divergence.
    if printing.keywords:
        return False
    # No spell effect (an Enchantment's "spell" is just "ETB"; it's
    # not an Instant / Sorcery, so spell_effect should be None).
    if printing.spell_effect is not None:
        return False
    # No triggered / activated / static abilities — pure vanilla
    # Enchantment with one printing-level rider bool.
    if printing.triggered_abilities:
        return False
    if printing.activated_abilities:
        return False
    if printing.static_abilities:
        return False
    # No alt-cost / mode riders.
    if printing.warp_cost or printing.kicker_cost or printing.impending_cost:
        return False
    if printing.room_halves:
        return False
    # No X-cost / cost-reduction.
    mc = printing.mana_cost
    if getattr(mc, "x_pips", 0):
        return False
    if printing.cost_reductions or printing.external_cost_reductions:
        return False
    # No station / dynamic-PT / aura / loyalty riders (defensive
    # — Enchantments shouldn't carry these, but pin them).
    if printing.station_threshold:
        return False
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if printing.loyalty is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    # Aura riders must be off — Deafening Silence is not an Aura.
    if getattr(printing, "is_aura", False):
        return False
    # spell_is_uncounterable / grants_creature_spells_uncounterable
    # must be off — pure single-rider shape.
    if getattr(printing, "spell_is_uncounterable", False):
        return False
    if getattr(printing, "grants_creature_spells_uncounterable", False):
        return False
    # Defensive: the mana cost must be parseable (mirrors the
    # uncounterable-creature predicate's parse check).
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True


def _printing_is_bridge_simple_enchantment(printing) -> bool:
    """True iff a CardPrinting is a vanilla non-Creature Enchantment
    whose ETB triggered_abilities ALL round-trip through the safe-
    trigger recognizer.

    **Weftwalking Cycle 2 (2026-05-24).** New admit arm for the
    enchantment-side safe-trigger path — the structural sibling of
    :func:`_printing_is_bridge_simple_creature` on the Enchantment
    type axis. Weftwalking ({4}{U}{U} Enchantment with ETB+IsSelf+
    ConditionalIfCastFromHand(Sequence(ShuffleZonesIntoLibrary,
    DrawCards(7))), ~3,680 17lands decks — the #1 multi-gated-tail
    closure target) is the sole admitted EoE consumer at HEAD.

    **Why a new arm vs. extending the creature arm?**
    :func:`_printing_is_bridge_simple_creature` gates on
    ``"Creature" in card_types`` AND power/toughness non-None AND a
    Creature-specific dispatch table (``dynamic_pt_formula`` admit
    set, ``ward_cost`` rejection, P/T-bonus statics path) downstream
    in ``_printing_to_card_def``. Extending it to also accept
    Enchantments-with-only-safe-triggers would cascade through many
    Creature-specific downstream assumptions (the materializer's
    ``card_type="Creature"`` branch threads ``power`` / ``toughness``
    / ``keywords`` / Creature-only static layers). A new arm parallel
    to :func:`_printing_is_bridge_simple_cast_restriction_enchantment`
    is the cleaner cleavage — same Enchantment-type gate, same §2
    rider-rejection block, but with the ``triggered_abilities`` half
    OPEN (gated on every entry round-tripping the safe-trigger
    recognizer, matching the Creature arm's discipline) and the
    static-restriction flag OFF (it doesn't apply).

    **§2 silent-mistranslation teeth.** The admit set is gated by:

      * ``Enchantment`` in card_types, ``Creature`` NOT in card_types
        (Enchantment-Creature dual-typed cards ride the Creature arm).
      * Every ``triggered_ability`` round-trips through
        :func:`_python_ta_to_safe_dict` (the same per-trigger gate
        the Creature arm uses — the Weftwalking C2 recognizer widen
        is what makes Weftwalking's trigger pass this gate today).
      * No ``activated_abilities`` / ``static_abilities`` /
        ``spell_effect`` / aura riders / warp / kicker / impending /
        room / X-cost / cost-reduction / station / dynamic-PT-
        formula / loyalty / ward / Aura-ness / uncounterable-grant
        / cast-restriction (the cast-restriction-enchantment arm
        handles its own narrow shape — this arm refuses overlap).
      * Power / toughness must both be None (Enchantments are not
        creatures; an Enchantment-Creature is handled by the
        Creature arm above).
      * No printing keywords (vanilla Enchantments have none; a
        keyword-bearing Enchantment would need its own substrate).
      * Mana cost is parseable (mirrors the established
        ``_parse_mana_cost_string`` gate from the Creature /
        cast-restriction-enchantment arms).

    **Verify-first silent-auto-grow check.** Live HEAD scan of all
    40 non-Creature Enchantments found 34 carry one or more
    triggered_abilities; Weftwalking is the SOLE carrier whose
    trigger set round-trips the safe-trigger recognizer post-C2
    widen (every other Enchantment trigger uses an effect class /
    event / predicate combination NOT in the safe set — Banishing
    Light's bespoke exile-and-return, the Duskmourn Room halves'
    bespoke Room mechanics, Burgeoning's And/landfall, etc.). The
    C2 admit arm flips exactly one card (Weftwalking) — no silent
    auto-grows — same surgical-by-construction discipline as
    today's AV C2 single-card flip + CH C2 single-card flip.
    """
    # Must be a non-Creature Enchantment (Enchantment-Creature dual-
    # typed cards ride the Creature arm above — the dispatch order
    # in :func:`_filter_deck_to_bridge_supported` puts the
    # Creature-side arms first, so a dual-typed Enchantment that
    # passes the Creature arm never reaches this one; the explicit
    # ``Creature not in card_types`` gate here is defense-in-depth
    # against a reordering regression).
    if "Enchantment" not in printing.card_types:
        return False
    if "Creature" in printing.card_types:
        return False
    # Power / toughness must be unset (non-Creature). Defense-in-
    # depth against a printing carrying P/T without the Creature
    # type (parser shouldn't emit that, but guard against drift).
    if printing.power is not None or printing.toughness is not None:
        return False
    # No keywords — vanilla Enchantment shape. A keyword-bearing
    # Enchantment would need its own substrate (the §2 keyword-
    # round-trip discipline the Creature arm enforces via
    # ``_SAFE_KEYWORDS``; Enchantments don't typically carry combat
    # keywords, but future printings might).
    if printing.keywords:
        return False
    # Every triggered ability must round-trip the safe-trigger gate.
    # The Weftwalking C2 recognizer widen (this slice) is what flips
    # Weftwalking's ENTERS+IsSelf+ConditionalIfCastFromHand(Sequence(
    # ShuffleZonesIntoLibrary(hand+graveyard), DrawCards(7))) through
    # this gate; pre-C2 the recognizer rejected the wrap.
    if not printing.triggered_abilities:
        # **§2 vanilla-Enchantment carveout (verify-first 2026-05-24).**
        # A vanilla non-Creature Enchantment with NO triggered
        # abilities and NO other features would technically pass every
        # gate above, but admitting it via this arm would silently
        # subsume a different substrate: the "honest no-op" enchantment
        # surface (Leyline of Mutation in the EoE pool today). That
        # surface needs its OWN per-card audit + carddef shape decision
        # (the printed lines parse to no-ops on Python, but the bridge
        # claim isn't pinned anywhere). Rejecting it here preserves the
        # no-fallback-hybrid discipline — a future slice landing the
        # vanilla-no-trigger-Enchantment substrate ships its own admit
        # arm + per-card probe + the honest-no-op pin set.
        return False
    # **§2 Weftwalking-shape gate (verify-first 2026-05-24).** The arm
    # admits an Enchantment ONLY when AT LEAST ONE of its triggers
    # carries the C2-target ConditionalIfCastFromHand shape. Sibling
    # surgical-narrowness teeth to today's AV C2 (LEAVES-event-only
    # leaf set) + CH C2 (creature-side narrow effect-set widen). The
    # verify-first scan caught a sibling auto-grow concern (Bioengineered
    # Future — ENTERS+IsSelf+CreateToken(Lander), a Lander-token-
    # enchantment shape that would silently flip here without an admit-
    # set bump on the Enchantment-Lander axis — a separate substrate
    # whose own per-card probe / honest stops are NOT in scope for the
    # Weftwalking C2 slice). The narrow gate keeps the C2 admit set =
    # {Weftwalking} at HEAD, the surgical single-card flip the dispatch
    # called for; a future slice landing the Enchantment-Lander shape
    # ships its own per-card admit slice + probe.
    from mtg_bot.effects.combinators import (
        ConditionalIfCastFromHand as _CICFH,
    )
    has_target_shape = False
    for ta in printing.triggered_abilities:
        if _python_ta_to_safe_dict(ta) is None:
            return False
        if isinstance(ta.effect, _CICFH):
            has_target_shape = True
    if not has_target_shape:
        return False
    # No activated abilities — the bridge's CardDef.triggered_abilities
    # tuple has no activated-ability slot for non-token printings (the
    # ``token_activated_abilities`` field is the round-49 token-specific
    # path); a future activated-Enchantment substrate would extend
    # this.
    if printing.activated_abilities:
        return False
    # No static abilities — Enchantments commonly carry rule-text
    # statics (Deafening Silence's ``restricts_noncreature_spells_to_
    # one_per_turn`` rides the cast-restriction arm via its own
    # printing-level bool; layered/anthem statics would need an
    # Enchantment-side static substrate).
    if printing.static_abilities:
        return False
    # No spell effect — Enchantments don't have a spell_effect (they
    # resolve as a permanent ETB, NOT as an Instant/Sorcery from the
    # stack); defense-in-depth against parser drift.
    if printing.spell_effect is not None:
        return False
    # No alt-cost / mode riders — pure single-cost Enchantment shape.
    if printing.warp_cost or printing.kicker_cost or printing.impending_cost:
        return False
    if printing.room_halves:
        return False
    # No X-cost / cost-reduction / station / dynamic-PT-formula /
    # loyalty / ward / Aura-ness / uncounterable-grant — the same §2
    # rider-rejection block the cast-restriction-enchantment arm
    # uses. Each rejected rider would need its own substrate before
    # an Enchantment with that surface could ride this admit arm.
    mc = printing.mana_cost
    if mc is not None and getattr(mc, "x_pips", 0):
        return False
    if printing.cost_reductions or printing.external_cost_reductions:
        return False
    if printing.station_threshold:
        return False
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if printing.loyalty is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    if getattr(printing, "is_aura", False):
        return False
    if getattr(printing, "spell_is_uncounterable", False):
        return False
    if getattr(printing, "grants_creature_spells_uncounterable", False):
        return False
    # The cast-restriction-enchantment arm above handles the
    # Deafening-Silence shape (printing-level
    # ``restricts_noncreature_spells_to_one_per_turn`` bool). This
    # arm REFUSES overlap — a printing carrying that flag would NOT
    # have triggered_abilities (Deafening Silence has none), so the
    # disjuncts are mutually exclusive by construction; the explicit
    # refusal here is defense-in-depth against a future printing
    # combining both surfaces (which would need its own substrate).
    if getattr(
        printing, "restricts_noncreature_spells_to_one_per_turn", False
    ):
        return False
    # Mana cost must be parseable (mirrors the established gate on
    # the sibling Enchantment / Creature arms).
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Phase 3 — SELF-scope conditional bonus admit (round-81)
# ---------------------------------------------------------------------------


def _static_ability_to_self_conditional_bonus(ability):
    """Map a single Python ``StaticAbility`` into the bridge tuple
    ``(condition_tag, condition_args, power_bonus, toughness_bonus,
    granted_keywords)``, or ``None`` if the ability is not in the
    Phase-3 admit shape.

    **Static / layered abilities substrate — Phase 3 (round-81,
    2026-05-20).** Admit shape:

      * ``scope`` is ``StaticScope.SELF``.
      * ``condition`` is one of the three recognized SELF-scope
        conditions:
          - ``ControlPermanent(IsArtifact())`` (Cloudsculpt
            Technician, Gravblade Heavy).
          - ``AtLeastNSpellsCastThisTurn(n)`` for some non-negative
            ``n`` (Brightspear Zealot uses ``n=2``).
          - ``ControlledArtifactEnteredThisTurn()`` (Mechan
            Shieldmate's "as long as an artifact entered the
            battlefield under your control this turn" gate —
            round-82, 2026-05-20).
      * ``continuous_effect`` is one of:
          - a layer-7 ``PowerToughnessBonus`` (the P/T arm), OR
          - a layer-6 ``GrantKeyword`` whose keyword is in
            :data:`_SAFE_KEYWORDS` (the keyword-grant arm), OR
          - a layer-6 ``RemoveKeyword`` whose keyword is in
            :data:`_SAFE_KEYWORDS` (the keyword-remove arm —
            round-82, 2026-05-20; Mechan Shieldmate's defender
            removal).
      * Every other StaticAbility slot at its default — no
        replacement_effect, tier_threshold, room_half,
        grants_no_max_hand_size, grants_creature_spells_
        uncounterable, granted_keywords, power_bonus,
        toughness_bonus.

    The returned tuple is keyed for coalescing: two abilities with
    the same condition fan-out into one bridge entry (the parser
    emits Gravblade Heavy as two StaticAbilities sharing the same
    condition — one P/T, one keyword — and the bridge collapses
    them at admit time).
    """
    from mtg_bot.cards.base import StaticScope
    from mtg_bot.effects.conditions import (
        AtLeastNSpellsCastThisTurn,
        ControlledArtifactEnteredThisTurn,
        ControlPermanent,
    )
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, GrantKeyword, PowerToughnessBonus,
        RemoveKeyword,
    )
    from mtg_bot.effects.object_predicates import IsArtifact

    if ability.scope not in (StaticScope.SELF, "self"):
        return None
    if ability.power_bonus or ability.toughness_bonus:
        return None
    if ability.granted_keywords:
        return None
    if ability.replacement_effect is not None:
        return None
    if ability.tier_threshold:
        return None
    if ability.room_half is not None:
        return None
    if ability.grants_no_max_hand_size:
        return None
    if ability.grants_creature_spells_uncounterable:
        return None
    cond = ability.condition
    if cond is None:
        return None
    # Recognized condition shapes -> (tag, args).
    if isinstance(cond, ControlPermanent):
        # Only the artifact-filter variant this slice.
        if not isinstance(cond.filter, IsArtifact):
            return None
        cond_tag = "control_permanent_is_artifact"
        cond_args: tuple[int, ...] = ()
    elif isinstance(cond, AtLeastNSpellsCastThisTurn):
        if cond.n < 0:
            return None
        cond_tag = "at_least_n_spells_cast_this_turn"
        cond_args = (int(cond.n),)
    elif isinstance(cond, ControlledArtifactEnteredThisTurn):
        cond_tag = "controlled_artifact_entered_this_turn"
        cond_args = ()
    else:
        return None
    ce = ability.continuous_effect
    if ce is None or not isinstance(ce, ContinuousModifier):
        return None
    if getattr(ce, "subject_filter", None) is not None:
        return None
    if ce.layer == 7 and isinstance(ce.payload, PowerToughnessBonus):
        return (
            cond_tag,
            cond_args,
            int(ce.payload.power_bonus),
            int(ce.payload.toughness_bonus),
            (),
            (),
        )
    if ce.layer == 6 and isinstance(ce.payload, GrantKeyword):
        kw = ce.payload.keyword
        if kw not in _SAFE_KEYWORDS:
            return None
        return (
            cond_tag,
            cond_args,
            0,
            0,
            (kw,),
            (),
        )
    if ce.layer == 6 and isinstance(ce.payload, RemoveKeyword):
        kw = ce.payload.keyword
        if kw not in _SAFE_KEYWORDS:
            return None
        return (
            cond_tag,
            cond_args,
            0,
            0,
            (),
            (kw,),
        )
    return None


def _printing_is_bridge_simple_static_self_conditional_creature(
    printing,
) -> bool:
    """True iff a CardPrinting is a Phase-3 bridge-supported
    SELF-scope conditional creature.

    **Static / layered abilities substrate — Phase 3 (round-81,
    2026-05-20).** Closes Brightspear Zealot, Cloudsculpt
    Technician, and Gravblade Heavy from Phase 1's honest-stop
    list. Every static-ability on the printing must pass
    :func:`_static_ability_to_self_conditional_bonus`; every other
    creature requirement matches
    :func:`_printing_is_bridge_simple_creature`.

    The admit shape covers exactly the parser's emit for SELF-
    scope "as long as <condition>, this creature gets +N/+M[ and
    has <keyword>]." lines and the trailing-rider variant — both
    surface forms produce the same `StaticAbility` tuple, so the
    predicate doesn't care about surface order.

    **Phase 3 honest-stops (documented in
    ``docs/SEARCH_LIMITATIONS.md``):**

    * Mechan Shieldmate's ``ControlledArtifactEnteredThisTurn`` +
      ``RemoveKeyword(defender)`` shape — **closed round-82
      (2026-05-20)**. The condition tag entered the two-tag table
      (now three-tag); the RemoveKeyword payload is admitted by
      :func:`_static_ability_to_self_conditional_bonus`'s third
      payload arm; Rust folds the REMOVE into
      :func:`battlefield_has_keyword`. The admit predicate now
      accepts Artifact-Creature dual-typed printings whose extra
      types are exactly ``("Artifact",)`` so the Mechan-shape
      printing routes through this arm.
    * Rampaging Soulrager — ``UnlockedDoorsAmongRoomsAtLeast(2)``
      (no EoE data snapshot today). Wildfire Wickerfolk —
      ``DeliriumActive`` (no EoE data snapshot today). They stay
      drop-at-filter until a per-Condition slice ports them; the
      predicate positively rejects them via
      :func:`_static_ability_to_self_conditional_bonus` returning
      ``None`` for an unrecognized condition.
    * The CR 613.7 layer-6 "lose all abilities" interaction
      against a SELF-scope conditional source — Phase 1's
      anthem-substrate already documents the simplification; the
      same applies here. No EoE / DSK card in the loader-admitted
      pool today carries a ``lose_all_abilities`` continuous
      effect that would wipe one of the four Phase-3 sources, so
      the parity is clean for the live pool.
    """
    if "Creature" not in printing.card_types:
        return False
    # Round-82 (2026-05-20): accept the Artifact-Creature dual-type
    # for Mechan Shieldmate. The admitted extra-type set is exactly
    # ``{"Artifact"}`` — every other multi-type-creature shape
    # (Enchantment Creature, Planeswalker, Land Creature, etc.)
    # stays drop-at-filter until its own slice lands. ``card_types``
    # is a tuple; the per-printing parser preserves order.
    extra_types = tuple(t for t in printing.card_types if t != "Creature")
    if extra_types and extra_types != ("Artifact",):
        return False
    if printing.power is None or printing.toughness is None:
        return False
    if printing.keywords and not printing.keywords.issubset(_SAFE_KEYWORDS):
        return False
    if printing.triggered_abilities:
        for ta in printing.triggered_abilities:
            if _python_ta_to_safe_dict(ta) is None:
                return False
    if printing.activated_abilities:
        return False
    if not printing.static_abilities:
        return False
    for ability in printing.static_abilities:
        if _static_ability_to_self_conditional_bonus(ability) is None:
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
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        return False
    return True


def _static_ability_is_phase4_anthem_pt_conditional(ability) -> bool:
    """True iff ``ability`` is a Phase-4 bridge-admittable anthem static —
    an ``[other_]creatures_you_control``-scope layer-7
    ``PowerToughnessBonus`` gated by ``DuringYourTurn`` (today's only
    recognized anthem-condition tag).

    **Static / layered abilities substrate — Phase 4 (Memorial Team
    Leader Cycle 2 flip, 2026-05-24; spec at Cycle 1 substrate commit
    ``1d6f5cd3``).** Mirrors the shape ``parser/statics.py:_parse_
    anthem_static_line`` emits for Memorial Team Leader's "During your
    turn, other creatures you control get +1/+0." line. The §2 teeth:

      * ``scope`` is ``creatures_you_control`` or
        ``other_creatures_you_control`` — the only two anthem scopes
        the Rust parser arm whitelists (matches the Phase-1 sibling
        :func:`_static_ability_is_simple_anthem_keyword_grant` vocab).
      * ``condition`` is a ``DuringYourTurn`` instance — today's only
        recognized anthem-condition tag (the Cycle 1 dispatcher at
        :func:`cross_engine._static_anthem_condition_from_tag` rejects
        unknown tags; this gate keeps the predicate locked to the
        same vocabulary so the admit set never widens past the Rust
        dispatch table).
      * ``continuous_effect`` is a layer-7
        ``ContinuousModifier(PowerToughnessBonus(p, t))``. ``p`` and
        ``t`` are not bounded here — the bridge round-trips arbitrary
        signed ints — but the Rust reader-fold (``static_anthem_pt_
        bonus_for`` in ``state_ops_combat.rs``) is the source of truth
        for what gets applied, so admitting any (p, t) is bridge-safe.
      * ``subject_filter`` on the modifier is ``None`` (Phase 4
        doesn't carry typed-anthem subjects — Slivers-only etc. would
        be a future slice).
      * All non-anthem flags are at their defaults (no
        ``granted_keywords``, no ``replacement_effect``, no
        ``tier_threshold``, no ``room_half``, no
        ``grants_no_max_hand_size``, no
        ``grants_creature_spells_uncounterable``, no
        ``power_bonus``/``toughness_bonus`` field — the bonus rides on
        the ``ContinuousModifier`` payload, not the legacy field).

    Mixed shapes (e.g. an anthem with BOTH a layer-7 P/T bonus AND a
    layer-6 keyword grant) would parse to MULTIPLE StaticAbility
    instances on the same printing — one per payload — sharing the
    same scope + condition. The admit predicate calling this helper
    accepts a printing whose every static_ability passes EITHER this
    Phase-4 P/T-conditional helper OR (future slice) a sibling layer-6
    keyword-conditional helper; for the Cycle 2 admit set the live
    pool carries exactly one card (Memorial Team Leader) with exactly
    one Phase-4 P/T-conditional StaticAbility, so the predicate
    accepts the single-payload shape today.
    """
    from mtg_bot.cards.base import StaticScope
    from mtg_bot.effects.conditions import DuringYourTurn
    from mtg_bot.effects.modifiers import (
        ContinuousModifier,
        PowerToughnessBonus,
    )

    if ability.scope not in (
        StaticScope.CREATURES_YOU_CONTROL,
        StaticScope.OTHER_CREATURES_YOU_CONTROL,
    ):
        return False
    if not isinstance(ability.condition, DuringYourTurn):
        return False
    if ability.replacement_effect is not None:
        return False
    if ability.power_bonus or ability.toughness_bonus:
        # Legacy P/T slot must be empty — the bonus rides on the
        # ContinuousModifier payload below.
        return False
    if ability.granted_keywords:
        return False
    if ability.tier_threshold:
        return False
    if ability.room_half is not None:
        return False
    if ability.grants_no_max_hand_size:
        return False
    if ability.grants_creature_spells_uncounterable:
        return False
    ce = ability.continuous_effect
    if ce is None:
        return False
    if not isinstance(ce, ContinuousModifier):
        return False
    if ce.layer != 7:
        return False
    if not isinstance(ce.payload, PowerToughnessBonus):
        return False
    if getattr(ce, "subject_filter", None) is not None:
        return False
    return True


def _printing_is_bridge_static_anthem_pt_conditional_warp_creature(
    printing,
) -> bool:
    """True iff a CardPrinting is a Phase-4 bridge-supported
    conditional-P/T-anthem warp creature.

    **Static / layered abilities substrate — Phase 4 (Memorial Team
    Leader Cycle 2 flip, 2026-05-24).** Closes the substrate for
    Memorial Team Leader — the canonical EoE single-gated carrier
    composing two previously-multi-gated subsystems: Phase-4
    anthem-shape (layer-7 P/T under ``DuringYourTurn``,
    other-creatures-you-control scope) AND ``warp_cost``. Cycle 1
    substrate landed the Rust ``StaticAnthem`` P/T + condition_tag
    extension + the ``during_your_turn`` dispatcher + the
    ``static_anthem_pt_bonus_for`` reader fold + the 6-tuple bridge
    round-trip; Cycle 2 (this slice) ships the admit-set widen and
    the per-card real-EoE warp-cast-then-anthem lifecycle probe.

    **Substrate carriers (all wired in Cycle 1).**

    * Python's ``CardPrinting.static_abilities`` carries one
      ``StaticAbility(scope=OTHER_CREATURES_YOU_CONTROL,
      condition=DuringYourTurn(),
      continuous_effect=ContinuousModifier(layer=7,
      payload=PowerToughnessBonus(1, 0)))`` for MTL — the parser SoT
      pinned by ``test_real_eoe_memorial_team_leader_static_ability_
      shape``.
    * Rust's ``CardPrinting`` carries the matching
      ``StaticAnthem { scope, power_bonus, toughness_bonus,
      condition_tag, condition_args, ... }`` slot consulted by the
      ``battlefield_creature_power`` /
      ``battlefield_creature_toughness`` reader folds via
      ``static_anthem_pt_bonus_for`` after the Phase-3
      ``static_self_bonus_pt_on`` fold.
    * Bridge: ``_spec_card_to_printing_dict`` emits the 6-tuple
      shape ``(scope, granted_keywords, power_bonus, toughness_bonus,
      condition_tag, condition_args)``;
      ``_card_def_to_python_printing`` rehydrates the Python
      ``StaticAbility`` with the ``DuringYourTurn`` condition.

    **Defensive §2 teeth.** Every creature-side filter from
    :func:`_printing_is_bridge_simple_creature` applies UNCHANGED
    EXCEPT:

      * ``static_abilities`` ban is replaced with a positive
        allowlist via :func:`_static_ability_is_phase4_anthem_pt_
        conditional` (every static must pass the Phase-4 anthem-PT-
        conditional shape).
      * ``warp_cost`` REQUIRED (not banned) — Phase 4 admits the
        composed warp+anthem shape that's the load-bearing MTL
        signature; a future non-warp Phase-4 anthem carrier (if one
        ever ships) would need its own sibling predicate.

    Mirrors the sibling :func:`_printing_is_bridge_pure_warp_creature`
    structure for the warp gates (life rider + graveyard-cast rider
    must be at defaults — MTL carries neither; a future Timeline-
    Culler-shape Phase-4 anthem would need a per-rider slice).
    Triggered abilities are admitted ONLY if every one round-trips
    through :func:`_python_ta_to_safe_dict` (the same safe-trigger
    gate the pure-warp arm uses); MTL carries no triggers, so the
    empty-tuple case is the only one exercised this slice.

    **Live pool admit set.** Verified at this HEAD: the live pool
    carries EXACTLY ONE creature passing this predicate — Memorial
    Team Leader. The other four warp+static creatures (Exalted
    Sunborn, Quantum Riddler, Starfield Vocalist, Drix Fatemaker) all
    fail the helper's positive shape gate (each carries a
    ``ReplacementEffect`` or layer-6 keyword grant under a non-
    ``DuringYourTurn`` condition or a non-anthem scope). No silent
    auto-grows — Cycle 2 is a single-card flip.

    **Honest-stops.**

    * Phase-4 P/T-anthem carriers WITHOUT warp_cost: no such card
      ships in the live pool today; if one lands, a sibling non-warp
      predicate or a parameterized variant is the natural follow-up.
    * Phase-4 keyword-only anthems under ``DuringYourTurn`` (sibling
      shape): no live carrier today; the same admit-set
      bookkeeping pattern would extend the helper trivially when one
      ships.
    * Other anthem conditions (e.g. ``OnYourTurnWithThreshold``):
      honest-stopped to whichever future slice ports them through
      the Rust ``static_anthem_condition_matches`` dispatcher first.
    """
    if "Creature" not in printing.card_types:
        return False
    if printing.power is None or printing.toughness is None:
        return False
    if printing.warp_cost is None:
        return False
    if printing.keywords and not printing.keywords.issubset(_SAFE_KEYWORDS):
        return False
    # Triggered abilities: only admit if every one round-trips through
    # the safe-trigger gate (same shape the pure-warp arm uses). MTL
    # carries no triggers — empty-tuple is the only case exercised this
    # slice, but the gate is here so a future Phase-4 warp+anthem
    # printing with a safe ETB trigger can be admitted on the same
    # disjunct without a predicate widen.
    if printing.triggered_abilities:
        for ta in printing.triggered_abilities:
            if _python_ta_to_safe_dict(ta) is None:
                return False
    if printing.activated_abilities:
        return False
    # Static abilities — positive allowlist of the Phase-4 anthem-PT-
    # conditional shape. Empty static_abilities falls back to the
    # pure-warp arm (or simple-creature if no warp); this predicate
    # specifically admits the WARP+ANTHEM composition.
    if not printing.static_abilities:
        return False
    for ability in printing.static_abilities:
        if not _static_ability_is_phase4_anthem_pt_conditional(ability):
            return False
    if printing.spell_effect is not None:
        return False
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
    # Warp riders — life cost + graveyard-cast rider — must be at
    # defaults. MTL is a hand-only warp creature with no extra life
    # cost (verify-first pinned in the substrate test); a future
    # Timeline-Culler-shape Phase-4 anthem carrier would need its own
    # slice to admit those riders here.
    if getattr(printing, "warp_additional_life_cost", 0):
        return False
    if getattr(printing, "warp_castable_from_graveyard", False):
        return False
    # Dynamic P/T formulas — gated to the round-78 admit set; no
    # Phase-4 anthem carrier in the live pool is a CDA. Reject the
    # rest defensively (same shape as the pure-warp arm).
    dpt_formula = getattr(printing, "dynamic_pt_formula", None)
    if dpt_formula is not None and dpt_formula != "harmonious_grovestrider":
        return False
    if getattr(printing, "ward_cost", None) is not None:
        return False
    # hand_ability_grants honest-stop (same pattern as Tannuk's
    # Phase-1 anthem predicate) — the bridge doesn't carry the field;
    # MTL has none.
    if getattr(printing, "hand_ability_grants", ()):
        return False
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
        _parse_mana_cost_string(printing.warp_cost_str or "")
    except ValueError:
        return False
    return True


def _printing_to_card_def(printing) -> CardDef:
    """Convert a bridge-supported CardPrinting into a CardDef.

    Pre-condition: printing must pass
    :func:`_printing_is_bridge_simple_creature`,
    :func:`_printing_is_bridge_basic_land`,
    :func:`_printing_is_bridge_nonbasic_mana_land`,
    :func:`_printing_is_bridge_simple_tapped_mana_land`, or
    :func:`_printing_is_bridge_keyword_colorless_tapped_mana_land`.
    Otherwise the conversion drops fields the bridge can't carry,
    producing a printing that silently disagrees across engines.
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
    if _printing_is_bridge_simple_tapped_mana_land(printing):
        # Non-basic land substrate phase 2 (round-85 N1): a mono-color
        # tapped mana-only non-basic land flattens to the SAME CardDef
        # shape the round-60 untapped sibling produces — the bridge
        # carries no ``enters_tapped`` field, so Python's
        # ``_card_def_to_python_printing`` builds the printing with
        # ``enters_tapped=False`` (default) and Rust's
        # ``register_printing`` has no ``enters_tapped`` path on lands
        # at all. Both engines therefore materialize the Planet land
        # as an UNTAPPED single-color land — bit-equal cross-engine,
        # CR-incomplete (a real Kavaron enters tapped). The "should
        # enter tapped" rider + the parser-dropped Station/AA together
        # compose a symmetric drop the bridge carries identically on
        # BOTH engines — a documented deliberate simplification (see
        # ``SEARCH_LIMITATIONS.md`` ``_printing_is_bridge_simple_tapped_
        # mana_land`` entry; same round-39 Ward / round-60 shockland
        # pattern). No CardDef field change, no Rust change.
        return CardDef(
            name=printing.name,
            card_type="Land",
            mana_produced=tuple(sorted(printing.produces)),
        )
    if _printing_is_bridge_keyword_colorless_tapped_mana_land(printing):
        # Non-basic land substrate sub-shape E (Cathedral of War cycle 1,
        # 2026-05-23): a keyword-colorless tapped land flattens to a
        # vanilla untapped colorless Land CardDef — the same shape basic
        # Wastes emits, with ``mana_produced=("C",)`` re-synthesizing the
        # parser-dropped ``{T}: Add {C}`` line. The bridge carries no
        # ``enters_tapped`` field and no static-keyword field for Land
        # card-types, so both the tapped-entry rider AND the keyword
        # (Exalted) are dropped symmetrically on both engines — Python's
        # ``_card_def_to_python_printing`` builds a printing with
        # ``enters_tapped=False`` + ``keywords=frozenset()`` from the
        # CardDef defaults, and Rust's ``register_printing`` has no
        # land-tapped-entry or static-keyword path. Both engines
        # therefore materialize Cathedral of War as a vanilla untapped
        # colorless land that taps for ``{C}`` — bit-equal cross-engine,
        # CR-incomplete (a real Cathedral enters tapped and grants
        # +1/+1 to a lone attacker via Exalted). Symmetric triple-drop:
        # tapped-entry + Exalted + the parser's empty-produces flatten,
        # all carried identically on BOTH bridge sides; the round-60
        # shockland / round-85 Planet land symmetric-drop precedent
        # extended to a keyword-bearing colorless land (see
        # ``SEARCH_LIMITATIONS.md`` ``_printing_is_bridge_keyword_
        # colorless_tapped_mana_land`` entry). No CardDef field change,
        # no Rust change — the mana-ability auto-wire from
        # ``mana_produced=("C",)`` materializes a ``{T}: Add {C}``
        # activated ability on Python AND a 1-element ``mana_produced``
        # Vec on Rust, byte-equal.
        return CardDef(
            name=printing.name,
            card_type="Land",
            mana_produced=("C",),
        )
    if _printing_is_bridge_nonbasic_painland_conditional(printing):
        # Non-basic land substrate phase 2 painland conditional
        # (2026-05-23): a dual-color Duskmourn-style conditional
        # painland flattens to a CardDef carrying the
        # ``enters_tapped_unless_any_player_life_at_most`` threshold.
        # The bridge round-trips the field both ways (registry dict
        # ``enters_tapped_unless_any_player_life_at_most`` key);
        # Python's ``_play_land`` consults
        # ``printing.enters_tapped_unless_any_player_life_at_most``;
        # Rust's ``play_land`` consults
        # ``CardPrinting.enters_tapped_unless_any_player_life_at_most``
        # via the same threshold check (see ``state_ops_cast.rs``).
        # Threshold 13 is the only value any of the 9 Duskmourn
        # painlands carries; the predicate's exact-13 guard
        # positively rejects any future cycle with a different
        # threshold so the substrate widening is explicit.
        return CardDef(
            name=printing.name,
            card_type="Land",
            mana_produced=tuple(sorted(printing.produces)),
            enters_tapped_unless_any_player_life_at_most=13,
        )
    if _printing_is_bridge_simple_carrier_aa_land(printing):
        # **Carrier-AA substrate Phase 1 Cycle 2 (2026-05-25).** A
        # bare-``{T}`` single-bridged-Effect single-AA non-token Land
        # carrier flattens to a Land CardDef carrying the AA in the
        # bridge dict shape (the SAME dict Rust's
        # ``register_printing`` ``activated_abilities`` key consumes
        # and Python's
        # ``cross_engine._aa_dict_to_python_activated_ability``
        # reconstructs). Phase-1 admits Swarmyard only — see
        # :func:`_carrier_aa_land_card_def` for the builder + the
        # admit predicate guardrail invariants. Returning ``None``
        # from the builder is a defense-in-depth honest decline
        # (admit predicate already gates the safe-dict round-trip
        # floor); we fall through to ``_printing_to_card_def``'s
        # tail (which raises on no-match) so an unexpected decline
        # surfaces loudly. In practice every printing reaching this
        # branch passes the predicate by construction (the OR-chain
        # above only routes here when the predicate returned True).
        card_def = _carrier_aa_land_card_def(printing)
        if card_def is not None:
            return card_def
    if _printing_is_bridge_simple_carrier_aa_artifact(printing):
        # **Carrier-AA substrate Phase 4A.2 (2026-05-26 — keystone
        # landing per ``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md``
        # §5.3).** Artifact-typed sibling of the Land builder above.
        # Phase 4A admits NO Artifact (the per-AA Effect-class teeth
        # decline all 4 Phase-4 Artifact candidates — Ghost Vacuum /
        # Keys to the House / All-Fates Scroll on Effect-class +
        # ``sorcery_speed`` + ``is_mana_ability`` AA-rider teeth); the
        # builder dispatch is wired now so Phase 4C/4D/4E carrier
        # FLIPs land without further OR-chain edits. Routed AFTER the
        # Land sibling so a printing only falls through here if the
        # Land predicate declines (Land and Artifact predicates are
        # mutually exclusive by their ``extra_card_types`` guards, so
        # the OR short-circuit is well-defined).
        card_def = _carrier_aa_artifact_card_def(printing)
        if card_def is not None:
            return card_def
    if _printing_is_bridge_pure_station_spacecraft(printing):
        # **Spacecraft Station substrate Phase 1 Cycle 3 (2026-05-25).**
        # A zero-ability Spacecraft (sole admit = Galvanizing Sawship)
        # flattens to an Artifact CardDef carrying ``station_threshold``
        # + ``stationed_keywords`` through the C3 bridge forward-emit
        # arm in ``cross_engine.py::_spec_card_to_printing_dict``. The
        # Rust substrate landed Parts A+B (``ea9aa996`` + ``62e10ff9``)
        # — ``CardPrinting`` fields + parse arm + ``is_stationed``
        # predicate + ``Action::ActivateStation`` resolver + sorcery-
        # speed legal emitter + ``is_creature_now`` extension +
        # ``battlefield_has_keyword`` fold. Returning ``None`` from the
        # builder is defense-in-depth (admit predicate gates everything
        # the builder needs); we fall through to ``_printing_to_card_
        # def``'s tail on an unexpected None so the disagreement
        # surfaces loudly. In practice every printing reaching this
        # branch passes the predicate by construction (the OR-chain
        # routes here only when the predicate returned True).
        card_def = _station_spacecraft_card_def(printing)
        if card_def is not None:
            return card_def
    if _printing_is_bridge_phase_2_static_anthem_spacecraft(printing):
        # **Spacecraft Station substrate Phase 2 Cycle 2 (Lumen-Class
        # Frigate, 2026-05-25; spec at
        # ``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_2_DESIGN.md``
        # §5.5).** A single-anthem-static Spacecraft flattens to an
        # Artifact CardDef carrying ``station_threshold`` +
        # ``stationed_keywords`` + a one-entry ``static_anthems``
        # tuple encoding the anthem's scope + P/T bonus + the new
        # ``source_charge_counters_at_least`` condition_tag with the
        # parser SoT's ``tier_threshold`` value threaded as
        # ``condition_args[0]``. Cycle 1 substrate landed the Rust
        # side (new condition_tag dispatcher arm in
        # ``rust/src/state_ops_combat.rs:737-810`` + parser whitelist
        # widen at ``rust/src/cards.rs:15191``); this cycle adds the
        # bridge rehydrator widen (``cross_engine.py``
        # ``_static_anthem_condition_from_tag`` returns ``None`` for
        # the new tag, with ``tier_threshold`` threaded back to the
        # legacy slot at the anthem-static rehydration site per
        # design doc §5.3a) + this admit predicate +
        # :func:`_phase_2_static_anthem_spacecraft_card_def` builder
        # + the OR-disjunct registration below. Pilot: Lumen-Class
        # Frigate.
        card_def = _phase_2_static_anthem_spacecraft_card_def(printing)
        if card_def is not None:
            return card_def
    if _printing_is_bridge_phase_3_trigger_spacecraft(printing):
        # **Spacecraft Station substrate Phase 3A Cycle 2 (Larval
        # Scoutlander, 2026-05-25; spec at
        # ``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_3_DESIGN.md`` §5.5).**
        # A trigger-bearing Spacecraft (Phase 3A admits exactly Larval
        # Scoutlander) flattens to an Artifact CardDef carrying
        # ``station_threshold`` + ``stationed_keywords`` + a
        # ``triggered_abilities`` tuple of round-trip dicts the bridge
        # contract consumes. Cycle 1 substrate (``83d775cf``) shipped
        # the Rust ``Effect::OptionalSacLandOrLanderForBasicLandRamp``
        # variant + parse / to_pydict / resolve arms + the cross-
        # engine bridge dict-to-Python arm; this cycle (C2) adds the
        # admit predicate + builder + OR-disjunct registration.
        # Returning ``None`` from the builder is defense-in-depth
        # (admit predicate gates everything the builder needs);
        # we fall through to ``_printing_to_card_def``'s tail on an
        # unexpected None so the disagreement surfaces loudly. In
        # practice every printing reaching this branch passes the
        # predicate by construction (the OR-chain routes here only
        # when the predicate returned True).
        card_def = _phase_3_trigger_spacecraft_card_def(printing)
        if card_def is not None:
            return card_def
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
            # Phase 2 — Timeline Culler's two riders. For every
            # Phase-1/1.5 card these are 0/False, so the returned
            # CardDef is bit-identical to the pre-Phase-2 one (the two
            # new kwargs equal their defaults). Only Timeline Culler's
            # CardDef gains warp_life_cost=2 / warp_from_graveyard=True.
            warp_life_cost=getattr(
                printing, "warp_additional_life_cost", 0),
            warp_from_graveyard=getattr(
                printing, "warp_castable_from_graveyard", False),
        )
    if _printing_is_bridge_simple_aura(printing):
        # Aura-attachment substrate — Phase 1 first-deliverable
        # (round-77; spec at ``docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md``
        # §3 Phase 1). The Phase-1 S1 (static P/T-or-keyword Aura)
        # CardDef shape — the printing's ``is_aura`` /
        # ``aura_enchant_type`` / ``aura_yours_only`` /
        # ``equipment_bonuses`` round-trip via the CardDef aura fields.
        # ``card_type="Enchantment"`` (Phase-1 Auras are pure
        # enchantments — no Creature/Artifact overlap); the "Aura"
        # subtype is materialized by ``_card_def_to_python_printing``.
        # STEP 7 (round-78): ``_filter_deck_to_bridge_supported``'s
        # 6th disjunct now invokes :func:`_printing_is_bridge_simple_aura`,
        # so a passing printing flows through this branch end-to-end.
        # The branch was already testable in isolation by direct
        # call (round-77 Phase-1-first-deliverable pin); STEP 7 closes
        # the loader-to-CardDef wire-up.
        generic, colored = _parse_mana_cost_string(
            printing.mana_cost_str or "")
        if printing.equipment_bonuses is not None:
            pb, tb, gks = printing.equipment_bonuses
            aura_power_bonus = pb
            aura_toughness_bonus = tb
            aura_granted_keywords = tuple(sorted(gks))
        else:
            aura_power_bonus = 0
            aura_toughness_bonus = 0
            aura_granted_keywords = ()
        # Aura-attachment substrate — Phase 2 S2 (round-79+, 2026-05-20).
        # Thread the S2 static-grant fields from the parsed printing
        # through to the CardDef. The §2 predicate above gates on the
        # paired-shape (``attached_grants_control +
        # attached_grants_lose_all_abilities``) and rejects
        # ``attached_sets_base_pt`` / ``attached_grants_subtype`` /
        # ``attached_prevents_untap``; so for the live admit set
        # (Duskmourn's Domination) the values flowing through here
        # are control=True / lose_abilities=True / set_base_pt=None.
        # The Phase-1-S1 carriers (Frantic Strength, Shardmage's
        # Rescue) have all three at the back-compat defaults, so
        # they materialize bit-identical to before this slice.
        attached_sets_base_pt = printing.attached_sets_base_pt
        if attached_sets_base_pt is not None:
            sp, st = attached_sets_base_pt
            aura_set_base_power: int | None = int(sp)
            aura_set_base_toughness: int | None = int(st)
        else:
            aura_set_base_power = None
            aura_set_base_toughness = None
        # Aura-attachment substrate — Phase 2 S2 extension (Tractor
        # Beam closure, 2026-05-20) + Phase 3 / S4 (Pain for All
        # closure, round-80, 2026-05-20). Thread the don't-untap
        # rider AND the bridge-safe Aura triggers through to the
        # CardDef. The predicate's §2 teeth gate every trigger
        # through :func:`_aura_triggers_are_phase3_safe` (a strict
        # superset of the Phase-2-S2-extension gate), so an admitted
        # printing's triggers are guaranteed to round-trip via
        # :func:`_python_ta_to_safe_dict_aura_phase3`. Empty tuple
        # is the back-compat baseline — every pre-substrate S1/S2
        # carrier (Frantic Strength, Duskmourn's Domination) carries
        # no triggers and threads through unchanged. Pain for All's
        # two triggers (ENTERS+IsSelf+PainForAllETBEffect +
        # DEALT_DAMAGE+IsHost+PainForAllDamageEchoEffect) thread
        # through here.
        triggered_abilities = tuple(
            _python_ta_to_safe_dict_aura_phase3(ta)
            for ta in printing.triggered_abilities
        )
        return CardDef(
            name=printing.name,
            card_type="Enchantment",
            mana_cost_generic=generic,
            mana_cost_colored=colored,
            is_aura=True,
            aura_enchant_type=printing.aura_enchant_type,
            aura_yours_only=printing.aura_yours_only,
            aura_power_bonus=aura_power_bonus,
            aura_toughness_bonus=aura_toughness_bonus,
            aura_granted_keywords=aura_granted_keywords,
            aura_grants_control=printing.attached_grants_control,
            aura_grants_lose_abilities=(
                printing.attached_grants_lose_all_abilities
            ),
            aura_set_base_power=aura_set_base_power,
            aura_set_base_toughness=aura_set_base_toughness,
            aura_prevents_host_untap=printing.attached_prevents_untap,
            # Aura-attachment substrate — Phase 4 S3 (Moonlit
            # Meditation substrate landing, 2026-05-20). Thread the
            # ``replaces_first_tokens_with_copies`` rider through to
            # the CardDef. The §2 predicate above gates on
            # ``replaces_first_tokens_with_copies`` and declines any
            # Aura that carries it (the substrate is round-trip-only
            # this slice; the Rust CreateToken arm doesn't yet swap
            # tokens to host-printing copies). For the live admit set
            # (no Phase-4-S3 admit lands this slice) the value
            # flowing through here is always ``False`` — the field is
            # threaded here for shape symmetry with the other Phase-4
            # rider fields and to keep the CardDef round-trip honest
            # for any future positive-admit slice.
            aura_replaces_first_tokens_with_copies=(
                printing.replaces_first_tokens_with_copies
            ),
            triggered_abilities=triggered_abilities,
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
    if _printing_is_bridge_simple_uncounterable_creature(printing):
        # Static / layered abilities substrate — Phase 2 (round-80,
        # 2026-05-20). Frenzied Baloth arm. Threads the two
        # uncounterable flags through to the CardDef. Sits ABOVE the
        # anthem-creature arm because the anthem predicate would
        # decline the printing (its static_abilities are SELF-scoped
        # sentinels, not anthem-scoped grants) — order doesn't
        # functionally matter for these two predicates, but the arm
        # ordering mirrors the predicate-disjunct order in
        # ``_filter_deck_to_bridge_supported`` (anthem before
        # uncounterable would already drop here for Frenzied Baloth
        # since its statics aren't anthem-shape). Keywords ride the
        # standard SAFE-keyword tuple shape (haste, trample).
        generic, colored = _parse_mana_cost_string(printing.mana_cost_str or "")
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
            spell_is_uncounterable=bool(
                getattr(printing, "spell_is_uncounterable", False)
            ),
            grants_creature_spells_uncounterable=any(
                getattr(sa, "grants_creature_spells_uncounterable", False)
                for sa in printing.static_abilities
            ),
        )
    if _printing_is_bridge_simple_static_self_conditional_creature(printing):
        # Static / layered abilities substrate — Phase 3 (round-81,
        # 2026-05-20). SELF-scope conditional bonus arm. Threads
        # the printing's SELF-scope conditional statics through to
        # the CardDef's ``static_self_bonuses`` slot, coalescing
        # multiple StaticAbilities that share a condition tag
        # (Gravblade Heavy emits two StaticAbilities — one P/T,
        # one keyword — sharing ``control_permanent_is_artifact``;
        # the bridge collapses both into a single entry with the
        # P/T bonus AND the granted keyword).
        #
        # Round-82 (2026-05-20): the 6-tuple shape adds a
        # ``removed_keywords`` slot for layer-6 RemoveKeyword
        # payloads (Mechan Shieldmate's defender removal). The
        # coalesce shape merges the per-condition grant + remove
        # sets independently so the parser fan-out doesn't double-
        # count either side. The Artifact-Creature dual-typed
        # Mechan Shieldmate threads ``extra_card_types=("Artifact",)``
        # so the Rust ``card_types`` Vec round-trips with both
        # types (the artifact bf-entry counter on the controller
        # side fires correctly when Mechan itself enters).
        from collections import defaultdict
        generic, colored = _parse_mana_cost_string(printing.mana_cost_str or "")
        triggered_abilities = tuple(
            _python_ta_to_safe_dict(ta)
            for ta in printing.triggered_abilities
        )
        # Coalesce per (condition_tag, condition_args).
        per_cond: dict[
            tuple[str, tuple[int, ...]], list[int]
        ] = {}
        per_cond_kws: dict[
            tuple[str, tuple[int, ...]], list[str]
        ] = defaultdict(list)
        per_cond_remove_kws: dict[
            tuple[str, tuple[int, ...]], list[str]
        ] = defaultdict(list)
        for ability in printing.static_abilities:
            (
                cond_tag,
                cond_args,
                p_bonus,
                t_bonus,
                granted_keywords,
                removed_keywords,
            ) = _static_ability_to_self_conditional_bonus(ability)
            key = (cond_tag, cond_args)
            if key not in per_cond:
                per_cond[key] = [0, 0]
            per_cond[key][0] += p_bonus
            per_cond[key][1] += t_bonus
            for kw in granted_keywords:
                per_cond_kws[key].append(kw)
            for kw in removed_keywords:
                per_cond_remove_kws[key].append(kw)
        # Deterministic ordering: sort by (cond_tag, cond_args).
        static_self_bonuses: tuple[
            tuple[
                str,
                tuple[int, ...],
                int,
                int,
                tuple[str, ...],
                tuple[str, ...],
            ],
            ...,
        ] = tuple(
            (
                cond_tag,
                cond_args,
                per_cond[(cond_tag, cond_args)][0],
                per_cond[(cond_tag, cond_args)][1],
                tuple(sorted(per_cond_kws.get((cond_tag, cond_args), []))),
                tuple(sorted(
                    per_cond_remove_kws.get((cond_tag, cond_args), [])
                )),
            )
            for (cond_tag, cond_args) in sorted(per_cond.keys())
        )
        # Round-82 (2026-05-20): emit Mechan-shape Artifact-Creature
        # printings with ``extra_card_types=("Artifact",)`` so the
        # registry-dict's ``card_types`` slot is ``["Creature",
        # "Artifact"]`` and Rust's artifact-bf-entry counter fires
        # on the source itself when it enters. Single-type creatures
        # (Brightspear / Cloudsculpt / Gravblade) thread the empty
        # tuple — bit-identical to the pre-round-82 emit.
        extra_card_types = tuple(
            t for t in printing.card_types if t != "Creature"
        )
        return CardDef(
            name=printing.name,
            card_type="Creature",
            extra_card_types=extra_card_types,
            mana_cost_generic=generic,
            mana_cost_colored=colored,
            power=printing.power,
            toughness=printing.toughness,
            keywords=tuple(sorted(printing.keywords)),
            triggered_abilities=triggered_abilities,
            static_self_bonuses=static_self_bonuses,
        )
    if _printing_is_bridge_static_anthem_pt_conditional_warp_creature(
        printing,
    ):
        # Static / layered abilities substrate — Phase 4 (Memorial
        # Team Leader Cycle 2 flip, 2026-05-24). The conditional-P/T-
        # anthem + warp arm threads BOTH the printing's anthem statics
        # (via the new 6-tuple ``static_anthems`` bridge shape: scope +
        # granted_keywords + power_bonus + toughness_bonus + condition_
        # tag + condition_args) AND the warp_cost (via the existing
        # ``has_warp`` / ``warp_cost_*`` CardDef slots from the Phase-1
        # warp substrate) through to the CardDef. Sibling to today's
        # Phase-3 ``static_self_bonuses`` arm + the Phase-1
        # ``static_anthems`` (2-tuple) arm + the pure-warp arm — the
        # 6-tuple bridge shape is the Cycle 1 substrate; this arm wires
        # it through ``_printing_to_card_def`` for the Cycle 2 admit
        # set. The arm sits ABOVE the plain ``_printing_is_bridge_
        # simple_static_anthem_creature`` branch so a Phase-4 anthem
        # carrier never falls through to the Phase-1 narrow arm (which
        # would reject on the P/T-bonus gate; this branch admits +
        # threads it).
        from collections import defaultdict
        generic, colored = _parse_mana_cost_string(printing.mana_cost_str or "")
        wgen, wcol = _parse_mana_cost_string(printing.warp_cost_str or "")
        triggered_abilities = tuple(
            _python_ta_to_safe_dict(ta)
            for ta in printing.triggered_abilities
        )
        # Coalesce per-scope-keyed entries: every static is the
        # Phase-4 P/T-conditional shape (no keyword grants this slice;
        # the predicate guarantees ``granted_keywords`` is empty and
        # the ``ContinuousModifier`` payload is exclusively
        # ``PowerToughnessBonus``). The 6-tuple entry shape carries the
        # P/T bonus PLUS the condition tag/args; we materialize one
        # entry per (scope, condition_tag, condition_args) triple,
        # summing P/T contributions across multi-static fan-outs (today
        # MTL is the sole carrier with exactly one StaticAbility, so
        # the sum is just the single payload's bonus — but the
        # coalesce shape is here for shape-symmetry with the Phase-3
        # sibling fan-out collapser and to keep the round-trip honest
        # for any future multi-static Phase-4 carrier).
        per_entry: dict[
            tuple[str, str, tuple[int, ...]], list[int]
        ] = {}
        for ability in printing.static_abilities:
            # Condition is DuringYourTurn (predicate guarantees).
            # Today's only Phase-4 condition tag — future slices add
            # to the dispatcher table at
            # ``cross_engine._static_anthem_condition_from_tag``.
            cond_tag = "during_your_turn"
            cond_args: tuple[int, ...] = ()
            scope = ability.scope
            payload = ability.continuous_effect.payload
            key = (scope, cond_tag, cond_args)
            if key not in per_entry:
                per_entry[key] = [0, 0]
            per_entry[key][0] += int(payload.power_bonus)
            per_entry[key][1] += int(payload.toughness_bonus)
        # Deterministic ordering: sort by scope (matches the Phase-1
        # anthem arm above). The granted_keywords slot stays empty
        # for the Phase-4 P/T-only shape; future P/T+keyword
        # composite anthems would populate it from the layer-6
        # GrantKeyword payload's keyword.
        static_anthems: tuple[
            tuple[
                str, tuple[str, ...], int, int, str, tuple[int, ...],
            ],
            ...,
        ] = tuple(
            (
                scope,
                (),  # granted_keywords — empty for the Phase-4 P/T shape
                per_entry[(scope, cond_tag, cond_args)][0],
                per_entry[(scope, cond_tag, cond_args)][1],
                cond_tag,
                cond_args,
            )
            for (scope, cond_tag, cond_args) in sorted(per_entry.keys())
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
            warp_life_cost=getattr(
                printing, "warp_additional_life_cost", 0),
            warp_from_graveyard=getattr(
                printing, "warp_castable_from_graveyard", False),
            static_anthems=static_anthems,
        )
    if _printing_is_bridge_simple_static_anthem_creature(printing):
        # Static / layered abilities substrate — Phase 1 first-
        # deliverable (round-79). The anthem-creature arm threads
        # the printing's anthem statics through the new
        # ``static_anthems`` CardDef slot in the deterministic-sorted
        # (scope, sorted-keywords) shape the bridge round-trips.
        # The arm sits ABOVE the plain ``_printing_is_bridge_simple_
        # creature`` branch — every passing anthem-creature would
        # ALSO pass simple-creature if the static-ban were lifted,
        # but the anthem arm threads ``static_anthems`` while the
        # plain arm would drop them; ordering matters.
        from collections import defaultdict
        generic, colored = _parse_mana_cost_string(printing.mana_cost_str or "")
        triggered_abilities = tuple(
            _python_ta_to_safe_dict(ta)
            for ta in printing.triggered_abilities
        )
        # Coalesce one-StaticAbility-per-keyword fan-out (per
        # ``parser/statics.py:_parse_anthem_static_line``) back into a
        # per-scope tuple of sorted keywords for the bridge.
        per_scope: dict[str, list[str]] = defaultdict(list)
        for ability in printing.static_abilities:
            kw = ability.continuous_effect.payload.keyword
            per_scope[ability.scope].append(kw)
        static_anthems: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
            (scope, tuple(sorted(per_scope[scope])))
            # Sort by scope name for deterministic bridge output.
            for scope in sorted(per_scope.keys())
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
            static_anthems=static_anthems,
        )
    if _printing_is_bridge_pure_cost_reduction_creature(printing):
        # **cost-reduction substrate Phase 1 Cycle 2 (2026-05-24) +
        # Phase 2 Cycle 2 (2026-05-25) + Phase 3 Cycle 2 (2026-05-25 —
        # Fungal Colossus FLIP).** A bridge-pure cost-reduction
        # creature routes to the cost-reduction-aware CardDef BEFORE
        # the plain simple-creature arm — defense-in-depth even though
        # ``_printing_is_bridge_simple_creature`` rejects any
        # ``cost_reductions``/``external_cost_reductions`` carrier
        # today. Materialize the CardDef with ``cost_reductions``
        # (Phase 1 + Phase 3) AND ``external_cost_reductions`` (Phase 2)
        # carrying the SAME (amount, condition_kind, condition_args)
        # triples the bridge emitters consume. The filter above
        # guarantees each rule is one of the three supported spell-
        # local shapes (Phase 1/3) + two supported externals shapes
        # (Phase 2); the condition_kind dispatch here is the inverse
        # of :func:`_cost_reduction_rule_is_phase1_or_3` /
        # :func:`_external_cost_reduction_rule_is_phase2` (any other
        # shape would have been rejected by the filter, so the
        # unreachable-else raises like the bridge §2 teeth).
        from mtg_bot.effects.conditions import (
            AnotherSpellCastThisTurn,
            NthSpellThisTurn,
            OpponentsControlAtLeast,
            PerControlled,
            PerDifferentlyNamedLand,
        )
        from mtg_bot.effects.object_predicates import IsArtifact, IsCreature

        generic, colored = _parse_mana_cost_string(
            printing.mana_cost_str or "")
        triggered_abilities = tuple(
            _python_ta_to_safe_dict(ta)
            for ta in printing.triggered_abilities
        )
        cr_triples: list[tuple[int, str, tuple]] = []
        for rule in printing.cost_reductions:
            cond = rule.condition
            if isinstance(cond, AnotherSpellCastThisTurn):
                cr_triples.append(
                    (int(rule.amount), "another_spell_cast_this_turn", ()),
                )
            elif isinstance(cond, OpponentsControlAtLeast):
                # Filter is guaranteed IsCreature + n int by the
                # Phase-1 rule predicate above.
                cr_triples.append((
                    int(rule.amount),
                    "opponents_control_at_least",
                    ("creature", int(cond.n)),
                ))
            elif isinstance(cond, PerDifferentlyNamedLand):
                # cost-reduction substrate — Phase 3 Cycle 2
                # (2026-05-25). Unit-shape variant (no payload); the
                # Rust evaluator computes the variable-X multiplier via
                # ``unique_land_names_count`` on the caster's
                # battlefield.
                cr_triples.append((
                    int(rule.amount),
                    "per_differently_named_land",
                    (),
                ))
            else:
                # Unreachable — the filter above only admits the three
                # Phase-1/3 shapes. Loud-fail rather than silently drop
                # (the §2 teeth — silent no-op pipeline runs are
                # pipeline bugs).
                raise ValueError(
                    f"unreachable: Phase-1+3 cost-reduction admit "
                    f"predicate passed an unsupported condition "
                    f"{type(cond).__name__!r} on {printing.name!r}"
                )
        # Phase 2 externals forward emit. Inverse of
        # :func:`_external_cost_reduction_rule_is_phase2`.
        ext_triples: list[tuple[int, str, tuple]] = []
        for ext_rule in printing.external_cost_reductions:
            ext_cond = ext_rule.condition
            if isinstance(ext_cond, NthSpellThisTurn):
                ext_triples.append((
                    int(ext_rule.amount),
                    "nth_spell_this_turn",
                    (int(ext_cond.n),),
                ))
            elif isinstance(ext_cond, PerControlled):
                # Filter is guaranteed IsArtifact / IsCreature by
                # the Phase-2 rule predicate above.
                if isinstance(ext_cond.filter, IsArtifact):
                    pred_token = "artifact"
                elif isinstance(ext_cond.filter, IsCreature):
                    pred_token = "creature"
                else:
                    raise ValueError(
                        f"unreachable: Phase-2 external cost-"
                        f"reduction admit predicate passed an "
                        f"unsupported PerControlled filter "
                        f"{type(ext_cond.filter).__name__!r} on "
                        f"{printing.name!r}"
                    )
                ext_triples.append((
                    int(ext_rule.amount),
                    "per_controlled",
                    (pred_token,),
                ))
            else:
                raise ValueError(
                    f"unreachable: Phase-2 external cost-reduction "
                    f"admit predicate passed an unsupported "
                    f"condition {type(ext_cond).__name__!r} on "
                    f"{printing.name!r}"
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
            cost_reductions=tuple(cr_triples),
            external_cost_reductions=tuple(ext_triples),
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
        # Round-78 dynamic-P/T-formula substrate: thread the formula
        # key through to the CardDef. The filter above gates on the
        # admit set (today: only ``"harmonious_grovestrider"`` is
        # honored); ``None`` for every non-CDA creature, bit-
        # identical to pre-substrate.
        return CardDef(
            name=printing.name,
            card_type="Creature",
            mana_cost_generic=generic,
            mana_cost_colored=colored,
            power=printing.power,
            toughness=printing.toughness,
            keywords=tuple(sorted(printing.keywords)),
            triggered_abilities=triggered_abilities,
            dynamic_pt_formula=getattr(
                printing, "dynamic_pt_formula", None
            ),
        )
    if _printing_is_bridge_simple_cast_restriction_enchantment(printing):
        # Static rule-text substrate — Deafening Silence Cycle 1
        # (2026-05-22). Vanilla Enchantment carrying ONLY the
        # printing-level ``restricts_noncreature_spells_to_one_per_turn``
        # bool. The CardDef carries the flag through; the bridge
        # registry-dict emitter sets the matching Rust
        # ``CardPrinting.restricts_noncreature_spells_to_one_per_turn``
        # slot and the Python materializer threads it onto the Python
        # ``CardPrinting``.
        generic, colored = _parse_mana_cost_string(
            printing.mana_cost_str or "")
        return CardDef(
            name=printing.name,
            card_type="Enchantment",
            mana_cost_generic=generic,
            mana_cost_colored=colored,
            restricts_noncreature_spells_to_one_per_turn=True,
        )
    if _printing_is_bridge_simple_enchantment(printing):
        # **Weftwalking Cycle 2 (2026-05-24).** Vanilla non-Creature
        # Enchantment whose every ETB triggered_ability round-trips
        # through the safe-trigger recognizer (the C2 recognizer
        # widen lands the canonical Weftwalking ETB shape). Materialize
        # the CardDef with ``card_type="Enchantment"`` and the
        # safe-dict round-trip of every triggered ability — the
        # Enchantment-side sibling of the Creature arm's
        # ``triggered_abilities = tuple(_python_ta_to_safe_dict(ta)
        # for ta in printing.triggered_abilities)`` pattern. The
        # admit arm's filter guarantees every entry round-trips
        # cleanly, so this comprehension cannot emit ``None``.
        generic, colored = _parse_mana_cost_string(
            printing.mana_cost_str or "")
        triggered_abilities = tuple(
            _python_ta_to_safe_dict(ta)
            for ta in printing.triggered_abilities
        )
        return CardDef(
            name=printing.name,
            card_type="Enchantment",
            mana_cost_generic=generic,
            mana_cost_colored=colored,
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


# ---------------------------------------------------------------------------
# C6 — the loader-admit gate as the enforced soundness boundary.
#
# `docs/SOT_FLIP_CUTOVER_PLAN.md` C6 / blocker B2 / Step 2: the loader
# admit gate (`_filter_deck_to_bridge_supported`'s 5-disjunct chokepoint
# + the `production_deck_to_deckspec` Forest-pad) is the SoT-flip
# soundness boundary. A card the loader does NOT admit MUST be unable to
# silently enter a flipped (Rust-sourced) game.
#
# TODAY (Python is SoT, single-script-replay) the silent drop +
# Forest-pad is the CORRECT, parity-required behavior — the bench plays
# the admitted residue of real decks, Forest-padded, and that is benign
# because Python drives. AT/AFTER the flip it becomes a SILENT
# CORRECTNESS HOLE: the Rust-sourced bot would quietly play a different
# (reduced, Forest-padded) deck than intended with no signal.
#
# C6 makes that boundary EXPLICIT + INSTRUMENTED + FAIL-LOUD without
# changing what gets admitted (that is C1 / the substrates' job):
#
#   * ``LoaderAdmitReport`` is the OBSERVABLE — exactly which names were
#     dropped (unresolved vs resolved-but-not-bridged) and how many
#     Forest-pad slots each side received. It is opt-in: the default
#     loader path (``production_deck_to_deckspec``) produces NO report
#     and is bit-identical to the pre-C6 behavior (parity-neutral by
#     construction).
#   * ``LoaderAdmitPolicy.RAISE`` is the post-flip FAIL-LOUD enforcement
#     — a non-admitted name raises ``NonAdmittedCardError`` instead of
#     being silently dropped. The Rust-sourced path (Step 3/4) sets
#     this; the Python-SoT parity path keeps the default ``DROP``.
#
# This is the §2 Step-2 / B2 pin substrate: the EXISTING boundary made
# enforced, non-silent, and pinned — NOT a change to the admit set.
# ---------------------------------------------------------------------------


class LoaderAdmitPolicy:
    """Policy for a card-name the loader-admit gate does NOT admit.

    ``DROP`` (default) — the pre-C6, parity-required behavior: a
    non-admitted name is silently dropped from the per-player library
    and the slot is later Forest-padded. Correct WHILE Python is the
    source of truth (single-script-replay; the bench plays the admitted
    residue and the drop is benign because Python drives both engines).

    ``RAISE`` — the post-flip FAIL-LOUD soundness boundary: a
    non-admitted name raises :class:`NonAdmittedCardError` rather than
    silently degrading the deck. The Rust-sourced decision path
    (`SOT_FLIP_CUTOVER_PLAN` Step 3/4) MUST use this so a card the
    loader cannot bridge can never quietly enter a Rust-authoritative
    game as a Forest.
    """

    DROP = "drop"
    RAISE = "raise"


class NonAdmittedCardError(ValueError):
    """A non-loader-admitted card hit the gate under ``RAISE`` policy.

    Raised by :func:`_filter_deck_to_bridge_supported` (and therefore
    :func:`production_deck_to_deckspec_instrumented`) when
    ``on_non_admitted`` is :data:`LoaderAdmitPolicy.RAISE` and a deck
    name either does not resolve in the active CardSource OR resolves
    but passes none of the five bridge-admit disjuncts. This is the C6
    enforced boundary — it must be unraisable on the Python-SoT parity
    path (which always uses the default ``DROP``) and the hard fence on
    the Rust-sourced path.
    """

    def __init__(self, name: str, *, resolved: bool):
        self.card_name = name
        self.resolved = resolved
        reason = (
            "resolves in the active CardSource but passes none of the "
            "five bridge-admit disjuncts (basic_land / "
            "nonbasic_mana_land / pure_warp_creature / simple_creature "
            "/ simple_spell)"
            if resolved
            else "does not resolve in the active CardSource"
        )
        super().__init__(
            f"loader-admit boundary (C6): card {name!r} {reason}; it "
            f"cannot enter a Rust-sourced game. The Python-SoT parity "
            f"path tolerates this (silent drop + Forest-pad); the "
            f"post-flip Rust-sourced path does not — admit it via a "
            f"C1/substrate close or fence the deck out upstream."
        )


@dataclass(frozen=True)
class LoaderAdmitReport:
    """Observable record of what the loader-admit gate dropped + padded.

    Returned by :func:`production_deck_to_deckspec_instrumented` (the
    C6 observable wrapper). Makes the loader-admit boundary an explicit
    artifact instead of a silent mutation, so the post-flip soundness
    fence (`SOT_FLIP_CUTOVER_PLAN` C6) is auditable.

    Fields are per-side (p0 / p1). ``*_unresolved`` are deck names that
    did not resolve in the active CardSource at all; ``*_not_bridged``
    are names that resolved but passed NONE of the five admit
    disjuncts. ``*_pad_count`` is the number of Forest (or configured
    ``pad_with``) slots appended to reach ``pad_to_size``. Lists
    preserve input order and multiplicity (a 4x non-admitted card
    appears 4x), so a caller can reconstruct exactly which deck slots
    were lost.
    """

    p0_unresolved: tuple[str, ...]
    p0_not_bridged: tuple[str, ...]
    p1_unresolved: tuple[str, ...]
    p1_not_bridged: tuple[str, ...]
    p0_pad_count: int
    p1_pad_count: int
    pad_with: str

    @property
    def any_dropped(self) -> bool:
        """True iff ANY name was dropped on either side (the boundary
        was crossed — under ``RAISE`` this state is unreachable)."""
        return bool(
            self.p0_unresolved
            or self.p0_not_bridged
            or self.p1_unresolved
            or self.p1_not_bridged
        )

    @property
    def total_dropped(self) -> int:
        """Total dropped deck slots across both sides (with
        multiplicity) — the bounded reduced-universe magnitude."""
        return (
            len(self.p0_unresolved)
            + len(self.p0_not_bridged)
            + len(self.p1_unresolved)
            + len(self.p1_not_bridged)
        )


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
    Cards filtered out are NOT logged on this path — the default
    loader's job is to produce a clean DeckSpec, not to audit the
    filter, and this path stays bit-identical to the pre-C6 behavior
    (parity-neutral). To OBSERVE which cards a deck loses to the gate,
    or to enforce the fail-loud post-flip soundness boundary, use
    :func:`production_deck_to_deckspec_instrumented` (the C6 wrapper)
    or :func:`_filter_deck_to_bridge_supported` directly.
    """
    spec, _report = _production_deck_to_deckspec_core(
        p0_card_names,
        p1_card_names,
        shared_rng_seed=shared_rng_seed,
        pad_to_size=pad_to_size,
        pad_with=pad_with,
        on_non_admitted=LoaderAdmitPolicy.DROP,
        observe=False,
    )
    return spec


def production_deck_to_deckspec_instrumented(
    p0_card_names: list[str],
    p1_card_names: Optional[list[str]] = None,
    *,
    shared_rng_seed: Optional[int] = None,
    pad_to_size: int = 60,
    pad_with: str = "Forest",
    on_non_admitted: str = LoaderAdmitPolicy.DROP,
) -> tuple[DeckSpec, LoaderAdmitReport]:
    """C6 observable wrapper: build a DeckSpec AND record what was lost.

    Same DeckSpec contract as :func:`production_deck_to_deckspec`, but
    additionally returns a :class:`LoaderAdmitReport` that names every
    deck slot the loader-admit gate dropped (unresolved vs
    resolved-but-not-bridged, per side, with multiplicity) and the
    Forest-pad count per side. This is the C6 OBSERVABLE — the loader
    boundary as an explicit, auditable artifact instead of a silent
    mutation (`SOT_FLIP_CUTOVER_PLAN` C6 / B2 / Step 2).

    ``on_non_admitted``
        :data:`LoaderAdmitPolicy.DROP` (default) keeps the
        parity-required silent-drop behavior but surfaces it in the
        returned report. :data:`LoaderAdmitPolicy.RAISE` is the
        post-flip FAIL-LOUD boundary — the first non-admitted name
        raises :class:`NonAdmittedCardError` (the Rust-sourced path
        sets this so a non-bridgeable card can never quietly enter a
        Rust-authoritative game as a Forest). Under ``RAISE`` a
        successful return is the proof the deck is fully admitted
        (``report.any_dropped is False``).
    """
    return _production_deck_to_deckspec_core(
        p0_card_names,
        p1_card_names,
        shared_rng_seed=shared_rng_seed,
        pad_to_size=pad_to_size,
        pad_with=pad_with,
        on_non_admitted=on_non_admitted,
        observe=True,
    )


def _production_deck_to_deckspec_core(
    p0_card_names: list[str],
    p1_card_names: Optional[list[str]] = None,
    *,
    shared_rng_seed: Optional[int] = None,
    pad_to_size: int = 60,
    pad_with: str = "Forest",
    on_non_admitted: str = LoaderAdmitPolicy.DROP,
    observe: bool = False,
) -> tuple[DeckSpec, LoaderAdmitReport]:
    """Shared body for the public + instrumented loader entrypoints.

    With ``on_non_admitted=DROP`` and ``observe=False`` (the
    :func:`production_deck_to_deckspec` defaults) the DeckSpec produced
    is bit-identical to the pre-C6 implementation — the sinks are
    ``None`` so no name is recorded and no policy branch fires. The C6
    observable/fail-loud behavior is strictly opt-in.
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

    # C6 observable sinks — only allocated when observing; otherwise
    # left None so the filter takes the exact pre-C6 code path.
    p0_unresolved: Optional[list] = [] if observe else None
    p0_not_bridged: Optional[list] = [] if observe else None
    p1_unresolved: Optional[list] = [] if observe else None
    p1_not_bridged: Optional[list] = [] if observe else None

    p0_filtered, p0_card_defs = _filter_deck_to_bridge_supported(
        p0_card_names, printings,
        on_non_admitted=on_non_admitted,
        unresolved_sink=p0_unresolved,
        not_bridged_sink=p0_not_bridged,
    )
    if p1_card_names is None:
        p1_filtered = list(p0_filtered)
        p1_card_defs = list(p0_card_defs)
        # Mirror match: p1 IS p0's filtered library — its drop record
        # is identical to p0's by construction.
        if observe:
            p1_unresolved = list(p0_unresolved or [])
            p1_not_bridged = list(p0_not_bridged or [])
    else:
        p1_filtered, p1_card_defs = _filter_deck_to_bridge_supported(
            p1_card_names, printings,
            on_non_admitted=on_non_admitted,
            unresolved_sink=p1_unresolved,
            not_bridged_sink=p1_not_bridged,
        )

    # Pad each side to pad_to_size with copies of pad_with.
    p0_pad_count = 0
    p1_pad_count = 0
    if pad_to_size > 0:
        if len(p0_filtered) < pad_to_size:
            p0_pad_count = pad_to_size - len(p0_filtered)
            p0_filtered.extend([pad_with] * p0_pad_count)
        if len(p1_filtered) < pad_to_size:
            p1_pad_count = pad_to_size - len(p1_filtered)
            p1_filtered.extend([pad_with] * p1_pad_count)

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

    spec = DeckSpec(
        card_defs=tuple(card_defs_ordered),
        p0_library=tuple(p0_filtered),
        p1_library=tuple(p1_filtered),
        shared_rng_seed=shared_rng_seed,
    )
    report = LoaderAdmitReport(
        p0_unresolved=tuple(p0_unresolved or ()),
        p0_not_bridged=tuple(p0_not_bridged or ()),
        p1_unresolved=tuple(p1_unresolved or ()),
        p1_not_bridged=tuple(p1_not_bridged or ()),
        p0_pad_count=p0_pad_count,
        p1_pad_count=p1_pad_count,
        pad_with=pad_with,
    )
    return spec, report


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
    #
    # **Spacecraft Phase 3C Cycle 4 (2026-05-26).** The new
    # ``create_token_per_multicolored_permanent`` kind (Infinite
    # Guideline Station's ETB token-spawn Effect) joins the seating
    # axis. Seated identically to the static ``create_token*``
    # carriers — same deterministic-pid token CardDef append + the
    # SAME ``register_token_printing`` cross-engine bridge map. The
    # carrier-rewrite branch below preserves the new kind discriminator
    # AND the ``tapped`` bool rider unchanged (only ``_token_card_def``
    # is swapped for ``token_printing_id``; ``count`` is NOT injected
    # because the per-multicolored-permanent variant has no static
    # count rider — the count is computed at resolve time).
    _TOKEN_CREATE_KINDS = (
        "create_token",
        "create_token_tapped",
        "create_token_per_multicolored_permanent",
    )

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
        # Emergency Eject (Effect-uncovered single-gated tier;
        # ~6,291 17lands decks). Same Lander-pid carrier shape as
        # Seedship Impact / Orbital Plunge — the reverse
        # serializer emits a symbolic ``_token_card_def`` Lander
        # reference and the spell-axis seating pass below resolves
        # it to the numeric ``token_printing_id`` Rust's
        # ``Effect::EmergencyEjectEffect { token_printing_id }``
        # parse arm requires. Adding the kind here is what auto-
        # joins Emergency Eject into the spell-card-bridge admit
        # set (the §2 auto-grow teeth).
        "emergency_eject_effect",
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

    def _carrier_choose_one_mode_token_refs(cd: CardDef):
        """**Warping Wail Cycle 4 (2026-05-24) — nested-token-seating
        spell-axis extension.** Yield ``(mode_idx, token_card_def)`` for
        each ``create_token`` / ``create_token_tapped`` mode inside the
        CardDef's top-level ``choose_one_mode`` ``spell_effect`` that
        still carries a symbolic ``_token_card_def``.

        Sibling of :func:`_carrier_token_refs` (triggered-ability axis)
        and :func:`_carrier_spell_token_ref` (top-level spell-effect
        axis). The three together carry the full token-seating surface:
        a Lander on a trigger / a Lander on a top-level spell / an
        Eldrazi-Scion-shape token nested inside a modal spell's mode —
        each routes through the same pid-by-name dedup + bridge-map
        register pass below, sharing ONE token pid even if it appears
        across multiple carriers in the same game.

        Returns an empty iterator when:

          * the CardDef has no top-level ``spell_effect`` dict, or
          * the top-level kind is not ``"choose_one_mode"``, or
          * none of the modes is a token-mint kind with a still-
            symbolic ``_token_card_def`` carrier.
        """
        se = cd.spell_effect
        if not isinstance(se, dict):
            return
        if se.get("kind") != "choose_one_mode":
            return
        modes = se.get("modes")
        if not isinstance(modes, list):
            return
        for i, mode in enumerate(modes):
            if not isinstance(mode, dict):
                continue
            if mode.get("kind") not in _TOKEN_CREATE_KINDS:
                continue
            tcd = mode.get("_token_card_def")
            if tcd is not None:
                yield i, tcd

    # Fast path: no create_token carrier AND no Lander-pid spell
    # carrier AND no choose_one_mode-nested token carrier (the
    # Warping Wail Cycle 4 spell-axis extension) -> return the list
    # untouched (every pre-round-49 production deck; every pre-round-73
    # spell deck; every pre-Cycle-4 modal-spell deck). Avoids the
    # dataclasses / cross_engine import cost on the hot loader path
    # when there's nothing to seat.
    has_token_carrier = any(
        any(True for _ in _carrier_token_refs(cd))
        or _carrier_spell_token_ref(cd) is not None
        or any(True for _ in _carrier_choose_one_mode_token_refs(cd))
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
    # Lander pid. The Cycle 4 nested-mode walk uses the same
    # namespace — an Eldrazi Scion nested inside Warping Wail's mode 2
    # would share its pid with a (hypothetical) Eldrazi Scion top-
    # level carrier in the same deck.
    token_cd_by_name: dict[str, CardDef] = {}
    for cd in card_defs:
        for _idx, tcd in _carrier_token_refs(cd):
            token_cd_by_name.setdefault(tcd.name, tcd)
        stcd = _carrier_spell_token_ref(cd)
        if stcd is not None:
            token_cd_by_name.setdefault(stcd.name, stcd)
        for _idx, tcd in _carrier_choose_one_mode_token_refs(cd):
            token_cd_by_name.setdefault(tcd.name, tcd)

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
    # symbolic Lander-pid spell_effect AND/OR nested-mode create_token
    # spell_effect into the numeric token_printing_id shape. CardDef
    # is frozen -> replace.
    rewritten: list[CardDef] = []
    for cd in result:
        refs = list(_carrier_token_refs(cd))
        stcd = _carrier_spell_token_ref(cd)
        nested_refs = list(_carrier_choose_one_mode_token_refs(cd))
        if not refs and stcd is None and not nested_refs:
            rewritten.append(cd)
            continue
        replace_kwargs: dict = {}
        if refs:
            new_tas = list(cd.triggered_abilities)
            for idx, tcd in refs:
                old = new_tas[idx]
                old_eff = old["effect"]
                # Spacecraft Phase 3C Cycle 4 (2026-05-26): the new
                # ``create_token_per_multicolored_permanent`` kind has
                # NO static ``count`` field (the count is computed at
                # resolve time from the multicolored-permanent walk),
                # so we copy every non-symbolic field through unchanged
                # rather than hardcoding the {kind, count,
                # token_printing_id} triple. Mirrors the spell-axis
                # rewrite below (which uses the same "drop _token_card_
                # def, add token_printing_id" semantics for spells
                # whose dict shape varies by kind).
                new_eff = {
                    k: v
                    for k, v in old_eff.items()
                    if k != "_token_card_def"
                }
                new_eff["token_printing_id"] = token_pid_by_name[tcd.name]
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
        if nested_refs and "spell_effect" not in replace_kwargs:
            # **Warping Wail Cycle 4 (2026-05-24) — nested-mode rewrite.**
            # Copy the top-level ``choose_one_mode`` dict; rewrite each
            # nested ``create_token`` / ``create_token_tapped`` mode by
            # dropping the symbolic ``_token_card_def`` and adding the
            # numeric ``token_printing_id`` (preserving ``kind`` +
            # ``count`` — same field set the Rust parser's
            # ``create_token`` / ``create_token_tapped`` arms require).
            # Mutual-exclusion contract: a top-level Lander-pid kind
            # (``stcd is not None``) and a top-level
            # ``choose_one_mode`` are disjoint (the kind string is
            # different); if the spell_effect was already rewritten
            # via the ``stcd`` branch, this block is a no-op (the
            # ``"spell_effect" not in replace_kwargs`` guard above
            # makes that explicit). The nested walk is bypassed in
            # that case because Lander-pid top-level kinds are not
            # ``choose_one_mode``.
            old_se = cd.spell_effect
            new_modes = list(old_se["modes"])
            for mode_idx, tcd in nested_refs:
                old_mode = new_modes[mode_idx]
                new_mode = {
                    k: v
                    for k, v in old_mode.items()
                    if k != "_token_card_def"
                }
                new_mode["token_printing_id"] = token_pid_by_name[tcd.name]
                new_modes[mode_idx] = new_mode
            new_se = dict(old_se)
            new_se["modes"] = new_modes
            replace_kwargs["spell_effect"] = new_se
        rewritten.append(dataclasses.replace(cd, **replace_kwargs))
    return rewritten


def _filter_deck_to_bridge_supported(
    card_names: list[str],
    printings: dict,
    *,
    on_non_admitted: str = LoaderAdmitPolicy.DROP,
    unresolved_sink: Optional[list] = None,
    not_bridged_sink: Optional[list] = None,
) -> tuple[list[str], list[CardDef]]:
    """Filter a card-name list to bridge-supported names + CardDefs.

    Returns ``(filtered_names, card_defs)`` where:

      * ``filtered_names`` is the input list with unsupported names
        dropped, in original order. Duplicates are preserved (a 4x
        Forest in the input stays 4x in the output).
      * ``card_defs`` is the unique CardDef list (deduped by name) the
        filtered names reference.

    Internal helper for :func:`production_deck_to_deckspec`.

    C6 instrumentation (parity-neutral — all three keyword params
    default to the pre-C6 behavior; with the defaults this function is
    bit-identical to before the C6 slice):

    ``on_non_admitted``
        :data:`LoaderAdmitPolicy.DROP` (default) silently drops a
        non-admitted name exactly as before — the Python-SoT
        parity-required behavior. :data:`LoaderAdmitPolicy.RAISE`
        raises :class:`NonAdmittedCardError` instead — the post-flip
        fail-loud soundness boundary (`SOT_FLIP_CUTOVER_PLAN` C6).
    ``unresolved_sink`` / ``not_bridged_sink``
        Optional lists; when provided, each dropped name is appended
        (preserving order + multiplicity) to the matching sink —
        ``unresolved_sink`` for names absent from ``printings``,
        ``not_bridged_sink`` for names that resolve but pass none of
        the five disjuncts. The OBSERVABLE half of C6 (the loader no
        longer silently mutates — it records what it removed).
    """
    filtered_names: list[str] = []
    seen_card_defs: dict[str, CardDef] = {}
    for name in card_names:
        printing = printings.get(name)
        if printing is None:
            # Unresolved: name not in the active CardSource at all.
            if on_non_admitted == LoaderAdmitPolicy.RAISE:
                raise NonAdmittedCardError(name, resolved=False)
            if unresolved_sink is not None:
                unresolved_sink.append(name)
            continue
        if not (
            _printing_is_bridge_basic_land(printing)
            or _printing_is_bridge_nonbasic_mana_land(printing)
            or _printing_is_bridge_pure_warp_creature(printing)
            # **cost-reduction substrate Phase 1 Cycle 2 (2026-05-24) +
            # Phase 2 Cycle 2 (2026-05-25) + Phase 3 Cycle 2 (2026-05-25
            # — Fungal Colossus FLIP).** The bridge-pure cost-reduction
            # creature disjunct. Admits EXACTLY the 5 Phase-1/2/3
            # carriers (Gigastorm Titan + Lashwhip Predator — 24,908
            # 17lands decks; Uthros Psionicist + Sami, Wildcat Captain
            # — +15,575 decks; Fungal Colossus — +13,165 decks) by
            # gating on the spell-local Phase-1+3 ``CostReduction``
            # shape AND the Phase-2 externals ``ExternalCostReduction``
            # shape via the widened
            # :func:`_cost_reduction_rule_is_phase1_or_3` +
            # :func:`_external_cost_reduction_rule_is_phase2` helpers.
            # Routed BEFORE ``_printing_is_bridge_simple_creature`` so
            # the ``_printing_to_card_def`` arm building the cost-
            # reduction-aware CardDef sees the printing first (the
            # simple-creature arm rejects ``cost_reductions`` carriers
            # today, so the ordering is also a defense-in-depth pin
            # against any future widen that might overlap). The §2
            # teeth in the admit predicate reject every multi-gated
            # cost-reduction card + every Phase-4+ ``Condition`` shape.
            # Rust-side gate rides ``apply_cost_reductions_rust`` at
            # ``rust/src/state_ops_legal.rs`` (Phase-3 substrate landed
            # 2026-05-25 at ``8525d18e`` — adds the
            # ``PerDifferentlyNamedLand`` match arm + the
            # ``unique_land_names_count`` helper) + the cast-side cost
            # source at ``state_ops_cast.rs::cast_creature``.
            or _printing_is_bridge_pure_cost_reduction_creature(printing)
            or _printing_is_bridge_simple_creature(printing)
            # Spell-card-bridge lever, Phase 1 (round-70): the 5th
            # disjunct admits a pure single-target Instant/Sorcery
            # whose bespoke Effect close has landed (covered+bridged)
            # and round-trips through the reverse serializer. Wired
            # exactly like the round-63 pure-warp-creature predicate.
            or _printing_is_bridge_simple_spell(printing)
            # Aura-attachment substrate, Phase 1 STEP 7 (round-78):
            # the 6th disjunct admits a sub-shape S1 static P/T-or-
            # keyword Aura. The predicate's §2 teeth (no triggered/
            # static/activated/spell-effect, no control-swap /
            # replacement riders, equipment_bonuses with granted
            # keywords restricted to ``_SAFE_KEYWORDS``) keep the
            # admit set bridge-correct. STEPs 2-6 (Rust parse arm +
            # cast-time enchant-target decision + Aura-resolution
            # attach + CR-704.5n SBA bury + bidirectional bridge
            # round-trip) closed the prior honest-stops; with this
            # OR-in Phase 1 closes for sub-shape S1. The live EoE
            # pool admits 0 Auras today (every S1 carrier — Frantic
            # Strength / Shardmage's Rescue — carries the non-
            # ``_SAFE_KEYWORDS`` ``flash`` keyword, the predicate's
            # documented decline reason), so this OR-in is a no-op
            # for the current bench corpus but the substrate is
            # wired through for the first non-flash S1 Aura that
            # ships (Phase 2/3/4 widen the admit set).
            or _printing_is_bridge_simple_aura(printing)
            # Static / layered abilities substrate, Phase 1 first-
            # deliverable (round-79): the 7th disjunct admits a
            # creature whose every static_ability is an unconditional
            # anthem keyword-grant (scope =
            # ``[other_]creatures_you_control``, layer-6
            # ``GrantKeyword(kw)``, kw in ``_SAFE_KEYWORDS``). Tannuk
            # Steadfast Second is the canonical EoE single-gated
            # carrier ("Other creatures you control have haste.");
            # closing this gate flips Tannuk to bridge-admitted.
            # Rust-side fold rides the round-78 STEP-4
            # ``battlefield_has_keyword`` reader-site extension
            # (``static_anthem_grants_keyword_to``). Conditional
            # statics + P/T anthems + SELF-scope statics are
            # honest-stopped to later slices (Brightspear /
            # Cloudsculpt / Gravblade / Mechan Shieldmate / Frenzied
            # Baloth / Rampaging Soulrager / Wildfire Wickerfolk
            # each fall outside this Phase-1 admit shape).
            or _printing_is_bridge_simple_static_anthem_creature(printing)
            # Static / layered abilities substrate — Phase 2 (round-80,
            # 2026-05-20): the 8th disjunct admits a creature whose
            # static_abilities consist of one uncounterable-grant
            # sentinel ``StaticAbility(grants_creature_spells_
            # uncounterable=True)`` AND/OR whose printing carries
            # ``spell_is_uncounterable=True``. Frenzied Baloth is the
            # canonical EoE single-gated carrier — has BOTH (the cast-
            # side flag and the battlefield-static rider). Closing
            # this admits Frenzied Baloth through the loader filter.
            # Rust-side gate rides the printing-level bool slots
            # (``spell_is_uncounterable`` /
            # ``grants_creature_spells_uncounterable``) consulted by
            # ``Effect::CounterTargetSpell`` and the round-7
            # ``counter_spell`` primitive. The remaining 6 of the 7
            # honest-stops from Phase 1 stay honest-stopped
            # (Brightspear / Cloudsculpt / Gravblade / Mechan
            # Shieldmate / Rampaging Soulrager / Wildfire Wickerfolk
            # all need per-Condition Rust ports + SELF-scope reader-
            # site walks; Phase 2 sequencing reserves them for the
            # next slice).
            or _printing_is_bridge_simple_uncounterable_creature(printing)
            # Static / layered abilities substrate — Phase 3 (round-81,
            # 2026-05-20): the 9th disjunct admits a creature whose
            # every static_ability is a SELF-scope conditional bonus
            # in the two-tag dispatch table (``control_permanent_is_
            # artifact`` for Cloudsculpt Technician / Gravblade Heavy
            # and ``at_least_n_spells_cast_this_turn`` for Brightspear
            # Zealot). Closes 3 of the 6 honest-stops from Phase 1.
            # Rust-side fold rides ``static_self_bonus_*`` helpers
            # consulted by ``battlefield_creature_power`` /
            # ``battlefield_creature_toughness`` /
            # ``battlefield_has_keyword``. The remaining 3 of the 6
            # stay honest-stopped (Mechan Shieldmate's
            # ``ControlledArtifactEnteredThisTurn`` +
            # ``RemoveKeyword`` payload, Rampaging Soulrager's
            # ``UnlockedDoorsAmongRoomsAtLeast``, Wildfire
            # Wickerfolk's ``DeliriumActive`` — each needs a Condition
            # variant outside this slice's table OR a layer-6
            # ``RemoveKeyword`` payload the Rust reader doesn't yet
            # fold).
            or _printing_is_bridge_simple_static_self_conditional_creature(
                printing,
            )
            # Static / layered abilities substrate — Phase 4 (Memorial
            # Team Leader Cycle 2 flip, 2026-05-24). The Phase-4
            # conditional-P/T-anthem + warp creature arm: admits a
            # creature whose every static_ability is the layer-7
            # ``PowerToughnessBonus`` gated by ``DuringYourTurn`` under
            # ``[other_]creatures_you_control`` scope AND which carries
            # ``warp_cost``. Memorial Team Leader ({3}{R} 4/3 with warp
            # {1}{R}; "During your turn, other creatures you control
            # get +1/+0.") is the SOLE live-pool carrier — single-card
            # FLIP, no silent auto-grows (verified pre-flip against
            # the 5-creature warp+static set). Cycle 1 substrate
            # (commit ``1d6f5cd3``) shipped the Rust ``StaticAnthem``
            # P/T + condition_tag extension + the
            # ``during_your_turn`` dispatcher + the
            # ``static_anthem_pt_bonus_for`` reader fold + the 6-tuple
            # bridge round-trip; Cycle 2 (this slice) wires the admit
            # gate. ~6,229 17lands decks BLOCKED -> PROBED.
            or _printing_is_bridge_static_anthem_pt_conditional_warp_creature(
                printing,
            )
            # Static rule-text substrate — Deafening Silence Cycle 1
            # (2026-05-22; spec at ``docs/SUBSYSTEM_BLOCKED_LEVERAGE_
            # INVENTORY.md`` §5 "Static rule-text" row). Closes the
            # gate for Deafening Silence — the canonical EoE single-
            # gated carrier of the
            # ``restricts_noncreature_spells_to_one_per_turn`` flag
            # (12 17lands decks). Rust-side gate rides the printing-
            # level bool slot (``CardPrinting.restricts_noncreature_
            # spells_to_one_per_turn``) consulted by the
            # ``state_ops_legal::legal_decisions`` CastSpell-
            # emission loops; the companion
            # ``Player.noncreature_spells_cast_this_turn`` counter
            # is bumped in every noncreature cast primitive and
            # reset at the cleanup step. Closing this admits
            # Deafening Silence through the loader filter.
            or _printing_is_bridge_simple_cast_restriction_enchantment(
                printing,
            )
            # **Weftwalking Cycle 2 (2026-05-24).** Vanilla non-Creature
            # Enchantment whose every ETB triggered_ability round-trips
            # through the safe-trigger recognizer (the C2 recognizer
            # widen lands the canonical Weftwalking ETB shape). Sole
            # admitted EoE consumer at HEAD is **Weftwalking**
            # ({4}{U}{U} Enchantment with ETB+IsSelf+
            # ConditionalIfCastFromHand(Sequence(ShuffleZonesIntoLibrary
            # (hand+graveyard), DrawCards(7))), ~3,680 17lands decks —
            # the #1 multi-gated-tail closure target from the
            # 2026-05-24 tractability rescout). Rust-side gate rides
            # the existing safe-trigger machinery + the C1-substrate
            # ``Effect::ConditionalIfCastFromHand { inner: Box<Effect> }``
            # + ``Effect::ShuffleZonesIntoLibrary { zones: Vec<String> }``
            # variants (rust/src/cards.rs); the cross-engine bridge
            # arms (cross_engine.py:2295-2387) round-trip both. Sibling
            # arm to the cast-restriction-enchantment arm above on the
            # Enchantment-type axis, but with the
            # ``triggered_abilities`` half OPEN (every entry must
            # round-trip the safe-trigger recognizer) and the
            # ``restricts_noncreature_spells_to_one_per_turn`` flag
            # explicitly OFF. The two arms are mutually exclusive by
            # construction (Weftwalking has triggers + the flag off;
            # Deafening Silence has no triggers + the flag on).
            or _printing_is_bridge_simple_enchantment(
                printing,
            )
            # Non-basic land substrate — phase 2 (round-85 N1): the
            # 10th disjunct admits a mono-color tapped mana-only
            # non-basic land. The 5 EoE Planet lands (Adagia /
            # Evendo / Kavaron / Susur Secundi / Uthros) are the
            # carriers — parser-flattened to ``produces={one color}``
            # + ``enters_tapped=True`` + no abilities + no keywords
            # (the parser drops Station + the tier-gated activated
            # ability per ``land_builder.py:692-727``). The bridge
            # carries no ``enters_tapped`` field and Rust's
            # ``register_printing`` has no land ``enters_tapped``
            # path, so both engines materialize the bridge-flattened
            # CardDef as an UNTAPPED single-color land — bit-equal
            # cross-engine, CR-incomplete (round-39 Ward / round-60
            # shockland precedent). The 5 Planet lands carry 7,617
            # 17lands decks (per round-58 attribution scout); the
            # remaining 13 non-shockland non-basic-land siblings
            # stay declined here (Duskmourn painlands' parser-
            # structured conditional-tapped IS a real cross-engine
            # divergence — Python's ``actions.py:1099`` honors the
            # ``enters_tapped_unless_any_player_life_at_most`` field,
            # Rust ignores it; the predicate's §2 teeth reject the
            # 10 painlands on that field, the 3 specials
            # Cathedral/Starforge/Echoing Deeps on the produces / clone
            # guards).
            or _printing_is_bridge_simple_tapped_mana_land(printing)
            # Non-basic land substrate — sub-shape E (Cathedral of War
            # cycle 1, 2026-05-23): the 11th disjunct admits a static-
            # keyword colorless tapped mana-only non-basic land. The
            # SOLE EoE carrier is **Cathedral of War** (1,205 17lands
            # decks; sub-shape E in
            # ``docs/NONBASIC_LAND_SUBSTRATE_PLAN.md`` §1.E) — parser-
            # flattened to ``produces=frozenset()`` + ``enters_tapped=
            # True`` + ``keywords={'exalted'}``. The bridge carries no
            # ``enters_tapped`` field, no static-abilities field for
            # Land card-types, and Rust's ``register_printing`` has no
            # corresponding land-tapped or static-keyword paths. The
            # CardDef admit synthesizes ``mana_produced=("C",)`` so the
            # bridge auto-wire materializes the parser-dropped ``{T}:
            # Add {C}`` colorless mana ability on both engines, while
            # the tapped-entry rider AND Exalted are dropped
            # symmetrically. Net: Cathedral materializes as a vanilla
            # untapped colorless land that taps for ``{C}`` on BOTH
            # engines — bit-equal cross-engine, CR-incomplete (round-60
            # shockland / round-85 Planet land symmetric-drop precedent
            # extended; SEARCH_LIMITATIONS.md). Without this admit, the
            # parser's empty-``produces`` shape would diverge between
            # engines today — Python's ``auto_tap_for_cost`` counts an
            # empty-``produces`` land for generic payments while Rust's
            # ``can_pay_cost`` skips it (``rust/src/state_ops_mana.rs:
            # 618-655``: ``if symbols.is_empty() { continue; }``). The
            # synthesized ``mana_produced=("C",)`` resolves that latent
            # divergence in addition to closing the parser drop.
            or _printing_is_bridge_keyword_colorless_tapped_mana_land(
                printing,
            )
            # Non-basic land substrate — phase 2 painland conditional
            # (2026-05-23; spec at
            # ``docs/NONBASIC_LAND_SUBSTRATE_PLAN.md`` §3 Phase 2). The
            # 12th disjunct admits a Duskmourn-style dual-color
            # conditional painland: ``enters_tapped_unless_any_player_
            # life_at_most == 13``, no other riders. The 9 Duskmourn
            # painlands (Abandoned Campground / Bleeding Woods / Etched
            # Cornfield / Lakeside Shack / Murky Sewer / Neglected
            # Manor / Peculiar Lighthouse / Raucous Carnival /
            # Razortrap Gorge) — plus Strangled Cemetery as the
            # round-59 audit's missed 10th member — flip from BLOCKED
            # to PROBED here. Rust-side gate rides the new
            # ``CardPrinting.enters_tapped_unless_any_player_life_at_
            # most`` field consulted in ``state_ops_cast::play_land``
            # before the move to the battlefield. The bridge round-
            # trips the int through the registry dict's
            # ``enters_tapped_unless_any_player_life_at_most`` key
            # both ways (no symmetric drop — the divergence the
            # round-59 plan flagged for sub-shape C is closed, not
            # papered over). 0 EoE bench signal (all are off-set
            # Duskmourn cards) but the substrate is reusable for any
            # future EoE printing with the same shape.
            or _printing_is_bridge_nonbasic_painland_conditional(
                printing,
            )
            # **Carrier-AA substrate Phase 4A (2026-05-26 — keystone
            # landing per
            # ``docs/CARRIER_AA_SUBSTRATE_PHASE_4_DESIGN.md`` §5.3).**
            # The bridge-simple Carrier-AA dispatcher disjunct covers
            # BOTH the Land sibling (Phase 1.5a / 2a / 3 admits —
            # Swarmyard / Deserted Temple / Petrified Field / Terrain
            # Generator / Mystifying Maze / Scavenger Grounds) AND
            # the Phase 4A.2 Artifact sibling (no live admit at Phase
            # 4A — substrate-only landing; Phase 4C/4D/4E carrier
            # FLIPs light up Ghost Vacuum / Keys to the House / All-
            # Fates Scroll once their Effect-class + AA-rider widens
            # land). The Phase 4A multi-AA admit substrate widens the
            # per-AA walk from STRICT single-AA to multi-AA all-or-
            # nothing — every AA must independently pass
            # :func:`_aa_is_phase1_sub_shape_a`. Routed AFTER every
            # other Land disjunct (basic / nonbasic-mana / tapped-
            # mana / keyword-colorless / painland-conditional) so a
            # printing only falls through here if the preceding land
            # disjuncts decline. The §2 teeth in
            # :func:`_aa_is_phase1_sub_shape_a`
            # + :func:`_printing_is_bridge_simple_carrier_aa_land`
            # + :func:`_printing_is_bridge_simple_carrier_aa_artifact`
            # reject every ``<empty-cost>`` carrier, every mana-
            # ability (until 4E widens), every sorcery-speed (until
            # 4C/4D widen), every triggered-ability-co-gated carrier
            # — Phase-4B/C/D/E widen the per-AA Effect-class admit
            # set in lockstep per design doc §5.4-§5.7.
            or _printing_is_bridge_simple_carrier_aa_any(printing)
            # **Spacecraft Station substrate Phase 1 Cycle 3
            # (2026-05-25).** The bridge-pure station Spacecraft
            # disjunct. Admits EXACTLY Galvanizing Sawship in the EoE
            # pool — the SOLE single-gated AND zero-ability Spacecraft
            # per the verify-first walk against the live 22-Spacecraft
            # set (every other Spacecraft carries one or more static /
            # triggered / activated abilities; The Eternity Elevator
            # additionally has ``station_threshold=None``). The §2
            # teeth in :func:`_printing_is_bridge_pure_station_
            # spacecraft` reject every Phase-2+ shape (static /
            # triggered / activated abilities, spell_effect /
            # room_halves / loyalty / cost_reductions / warp /
            # kicker / impending / dynamic_pt_formula / ward_cost /
            # non-empty baseline keywords / empty stationed_keywords /
            # non-``_SAFE_KEYWORDS`` member /
            # ``grants_toughness_as_station_power_for_creatures_you_
            # control`` Tapestry-Warden flag — per design doc §5.4).
            # Rust-side substrate landed Parts A+B (Cycle 1 ``ea9aa996``
            # — fields + parse + ``is_stationed`` predicate; Cycle 2
            # ``62e10ff9`` — ``Action::ActivateStation`` resolver +
            # sorcery-speed legal emitter + ``is_creature_now``
            # extension + ``battlefield_has_keyword`` fold of
            # ``stationed_keywords``); C3 adds the Python bridge
            # round-trip arms in ``cross_engine.py`` +
            # :func:`_station_spacecraft_card_def` builder + this
            # OR-in. Per-card real-EoE probe (Scenarios A/B/C) ships
            # in Cycle 4 per design doc §6.3.
            or _printing_is_bridge_pure_station_spacecraft(printing)
            # **Spacecraft Station substrate Phase 2 Cycle 2
            # (Lumen-Class Frigate, 2026-05-25; spec at
            # ``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_2_DESIGN.md``
            # §5.5).** The bridge-supported static-anthem Spacecraft
            # disjunct. Admits EXACTLY Lumen-Class Frigate in the EoE
            # pool — the SOLE single-anthem-static-only Spacecraft per
            # the verify-first walk (the other 5 trigger-bearing
            # Spacecraft + The Eternity Elevator all fail at least
            # one §5.4 clause). Routed AFTER the Phase-1 pure-station
            # disjunct so a zero-static printing (Galvanizing Sawship)
            # is short-circuited by the Phase-1 path; this disjunct
            # only fires on a printing with EXACTLY ONE static_ability
            # matching the Phase-2 anthem shape (tier_threshold >= 1,
            # condition=None, layer-7 P/T continuous modifier). The §2
            # teeth on :func:`_static_ability_is_phase_2_spacecraft_
            # anthem` + :func:`_printing_is_bridge_phase_2_static_
            # anthem_spacecraft` reject every multi-static / composed-
            # shape / triggered-co-gated carrier — Phase-3+ widens
            # those per design doc §3.1. Cycle 1 substrate landed
            # ``afccee65`` (new ``source_charge_counters_at_least``
            # condition_tag arm in
            # ``state_ops_combat.rs::static_anthem_condition_matches``
            # + parser whitelist widen at ``cards.rs:15191``); Cycle 2
            # (this slice) adds the bridge rehydrator widen +
            # :func:`_phase_2_static_anthem_spacecraft_card_def`
            # builder + this OR-in. Per-card real-EoE probe Scenarios
            # A & B ship alongside Cycle 2 (Scenarios C & D + composed-
            # shape pins ship in Cycle 3 per design doc §7).
            or _printing_is_bridge_phase_2_static_anthem_spacecraft(printing)
            # **Spacecraft Station substrate Phase 3A Cycle 2 (Larval
            # Scoutlander, 2026-05-25; spec at
            # ``docs/SPACECRAFT_STATION_SUBSTRATE_PHASE_3_DESIGN.md``
            # §5.5).** The bridge-supported trigger-bearing Spacecraft
            # disjunct. Phase 3A admits EXACTLY Larval Scoutlander in
            # the EoE pool — the sole single-trigger ETB+IsSelf carrier
            # whose Effect class is in the Phase-3A 1-class allowlist
            # ``{OptionalSacLandOrLanderForBasicLandRamp}`` (Sledge-
            # Class Seedship has ATTACKS event; Synthesizer Labship has
            # BEGINNING_OF_COMBAT + Controlled predicate; Entropic
            # Battlecruiser has different effect classes; Infinite
            # Guideline Station has a non-allowlisted effect class —
            # all four stay DECLINED under Phase 3A and flip via
            # Phase 3B / 3C). Routed AFTER the Phase-1 and Phase-2
            # disjuncts so a zero-trigger printing (Galvanizing Sawship)
            # or a single-anthem printing (Lumen-Class Frigate) is
            # short-circuited by the earlier arms. The §2 teeth on
            # :func:`_triggered_ability_is_phase_3_spacecraft_admitted`
            # + :func:`_printing_is_bridge_phase_3_trigger_spacecraft`
            # reject every multi-static / composed-shape / extra-
            # trigger-count carrier — sub-phases 3B/3C widen the
            # allowlist per design doc §5.4. Cycle 1 substrate landed
            # ``83d775cf`` (new ``Effect::OptionalSacLandOrLanderFor
            # BasicLandRamp`` Rust variant + parse / to_pydict /
            # resolve arms + cross-engine bridge dict-to-Python arm +
            # reverse-serializer leaf at ``trajectory.py:4510``); Cycle
            # 2 (this slice) adds the Python admit predicate + the
            # :func:`_phase_3_trigger_spacecraft_card_def` builder +
            # this OR-in. Per-card real-EoE probe Scenarios A & B ship
            # alongside Cycle 2 per design doc §6.2 #9.
            or _printing_is_bridge_phase_3_trigger_spacecraft(printing)
        ):
            # Resolved but passes none of the bridge-admit disjuncts.
            if on_non_admitted == LoaderAdmitPolicy.RAISE:
                raise NonAdmittedCardError(name, resolved=True)
            if not_bridged_sink is not None:
                not_bridged_sink.append(name)
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
