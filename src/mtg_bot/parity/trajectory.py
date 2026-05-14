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

import random
from dataclasses import dataclass
from typing import Optional

from mtg_bot.parity.cross_engine import (
    DeckSpec,
    build_matched_states,
)


__all__ = [
    "setup_matched_game",
    "MulliganDeterministicAgent",
    "RealGameCombatAgent",
    "CombatStrategy",
    "drive_combat_phase",
]


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
        gate (untapped + unsick + not-already-attacking Creature
        controlled by the active player):

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
            and not o.summoning_sick
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
