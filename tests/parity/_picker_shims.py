"""Shared picker-agent shims for Phase 5 parity probes.

Each probe in ``tests/test_parity_smoke.py`` installs a custom
``Agent`` subclass on one of the players to mirror Rust's
deterministic at-resolve target-pick / discard-pick behavior. The
same shim shapes were copy-pasted across many probes; this module
hoists them so a single edit propagates to every probe.

Naming convention: shims that pick targets are
``_PickFirst<Filter>Agent``; the one discard shim is
``_DiscardFirstAgent``. Where two probes used the same name with
slightly different logic, the variants get disambiguated names
rather than collapsing them — see
``_PickFirstOpponentTargetCreaturePreferredAgent`` (the Pinnacle
Kill-Ship variant that prefers creatures over players) vs the
plain ``_PickFirstOpponentTargetAgent`` (Nebula Dragon shape).

This is a pure code-motion module: behaviors are bit-identical to
the inline definitions they replace. Do not change semantics here
without auditing every importer.
"""

from __future__ import annotations

from mtg_bot.agents import Agent


class _PickFirstOpponentTargetAgent(Agent):
    """Pick the first opponent-controlled / opponent-player target.

    Mirrors Rust's ``Effect::DealDamageAnyTarget`` deterministic
    target selection: scan defender's bf for first creature, else
    defender-player. For a probe driven by p0 (active_player) on
    an empty p1 bf, both engines pick the p1 player.

    Used by: Nebula Dragon, Debris Field Crusher, Nova Hellkite
    (DealDamageAnyTarget / DealDamageToOpponentCreature shapes).
    """

    def choose_target(self, state, player_id, legal_targets):
        if not legal_targets:
            return None
        for kind, target_id in legal_targets:
            if kind == "player":
                if target_id != player_id:
                    return (kind, target_id)
            else:
                # Creature / planeswalker / battle / permanent --
                # check controller via the battlefield object lookup.
                obj = next(
                    (
                        o
                        for o in state.battlefield
                        if o.id == target_id
                    ),
                    None,
                )
                if obj is not None and obj.controller_id != player_id:
                    return (kind, target_id)
        # No opponent-side legal target found. Fall back to the
        # first legal target (defensive; the harness scenario
        # always has at least p1 as a player target since
        # any_target_filter admits players).
        return legal_targets[0]


class _PickFirstOpponentTargetCreaturePreferredAgent(Agent):
    """Pick the first opponent-controlled creature, else the
    first opponent player.

    Mirrors Rust's ``Effect::DealDamageAnyTarget`` deterministic
    target selection where the bf-first scan order is load-bearing:
    creatures are preferred over players (mirroring Rust's scan
    order across the defender's bf before falling back to the
    defender player).

    Used by: Pinnacle Kill-Ship probe (with bait Bear on p1's bf,
    the agent must pick the Bear, not the p1 player).
    """

    def choose_target(self, state, player_id, legal_targets):
        if not legal_targets:
            return None
        for kind, target_id in legal_targets:
            if kind == "player":
                continue  # Prefer creatures over players to
                          # mirror Rust's bf-first scan order.
            obj = next(
                (
                    o
                    for o in state.battlefield
                    if o.id == target_id
                ),
                None,
            )
            if obj is not None and obj.controller_id != player_id:
                return (kind, target_id)
        # Fall back to first opponent-side player target if no
        # opponent creature found.
        for kind, target_id in legal_targets:
            if kind == "player" and target_id != player_id:
                return (kind, target_id)
        return legal_targets[0]


class _PickFirstControlledCreatureAgent(Agent):
    """Pick the first own-side creature target.

    Mirrors Rust's ``Effect::PumpTargetCreatureUntilEOT``
    deterministic target selection: scan the SOURCE CONTROLLER's
    battlefield for the first creature; silent fizzle if none.
    For a probe driven by p0 with a single creature on p0's bf,
    both engines pick that creature.

    Used by: Dubious Delicacy, Rayblade Trooper.
    """

    def choose_target(self, state, player_id, legal_targets):
        if not legal_targets:
            return None
        for kind, target_id in legal_targets:
            if kind != "creature":
                continue
            obj = next(
                (
                    o
                    for o in state.battlefield
                    if o.id == target_id
                ),
                None,
            )
            if obj is not None and obj.controller_id == player_id:
                return (kind, target_id)
        # No same-side creature target found. Fall back to the
        # first legal target (defensive; the probe scenario
        # always has a same-side creature).
        return legal_targets[0]


class _PickFirstLegalTargetAgent(Agent):
    """Pick ``legal_targets[0]``.

    Mirrors Rust's iterator-order graveyard scan
    (``Effect::ReturnCreatureFromYourGraveyardToHand`` and rider
    variants — picks the first creature card in source-controller's
    graveyard insertion order). The Python bridge's
    ``legal_targets`` walks the same graveyard in the same order
    so ``legal_targets[0]`` is the iterator-order first.

    Used by: ETB-Recur-Bear probe, Interceptor Mechan or_artifact
    probe.
    """

    def choose_target(self, state, player_id, legal_targets):
        if not legal_targets:
            return None
        return legal_targets[0]

    def choose_surveil(self, state, player_id, top_card_id):
        """Keep every surveilled card on top of the library (return
        False — do NOT mill).

        Byte-equal cross-engine contract (round-73). This agent is the
        one the bench installs on BOTH Python players whenever a spell
        may be cast (``bench_trajectory_parity._try_cast_one_creature``
        — installed only when ``spells`` is non-empty). Rust's
        ``resolve_top_of_stack`` / ``_pause`` terminally invoke
        ``auto_resolve_pending(self, "keep_all_on_top")``
        (``state_ops_resolve.rs`` 11180/11313), and Python's
        ``Surveil.resolve`` keep-on-top default is the ``p.agent is
        None`` short-circuit (``library_lookat.py:605``). A non-None
        bench agent BYPASSES that short-circuit, so to stay byte-equal
        with Rust's keep_all_on_top default it MUST answer ``False``
        (keep on top) — NOT ``True`` (mill), which would diverge from
        Rust's no-mill default (see the cross-engine default-strategy
        contract documented at ``cross_engine.py`` ~line 750). Before
        round-73 this was a latent gap (the base ``Agent.choose_
        surveil`` raises ``NotImplementedError``): no real bench game
        cast a spell AND lived long enough to fire a surveil ETB
        (e.g. Thawbringer's enters→surveil 1). The Lander-spell-token-
        seating sub-substrate admits Seedship Impact / Orbital Plunge,
        extending such games past the surveil trigger — surfacing
        (NOT introducing) the gap. Returning ``False`` is the
        byte-equal fix (the keep_all_on_top mirror), not a fallback
        hybrid.
        """
        return False


class _PickFirstBattlefieldCreatureEitherSideAgent(Agent):
    """Pick the creature with the SMALLEST ``state.battlefield`` index
    from whatever (already slot-kind-filtered) pool it is offered.

    Mirrors Rust's
    ``Effect::TwoSubjectPumpAndDebuffByArtifactCount`` deterministic
    per-side scan (state_ops_resolve.rs): source side = FIRST creature
    on the source-controller's bf (smallest Vec index); opponent side
    = FIRST creature on the opponent's bf (smallest Vec index).

    The agent-driven real Monoist Circuit-Feeder card parses to
    ``PairedTargetPumpDebuffUEOT`` whose two-slot push (actions.py:
    3233-3255) calls ``choose_target`` ONCE PER SLOT with the pool
    already restricted to that slot's declared kind
    (``my_creature`` then ``creature``). So this shim only needs to
    return, from the offered pool, the candidate whose battlefield
    object has the lowest insertion index — which is exactly Rust's
    first-creature-on-that-side pick. Picking by battlefield index
    (not pool order) makes the choice independent of however
    ``legal_targets`` happens to order the pool, keeping the
    cross-engine probe byte-equal regardless of legal-target
    enumeration order.

    Used by: the genuine real-EoE Monoist Circuit-Feeder probe (the
    deterministic bridge sibling
    ``PumpYoursAndDebuffOpponentByArtifactCountUntilEOT`` on the Rust
    side; the agent-driven ``PairedTargetPumpDebuffUEOT`` on the
    Python side, shim-constrained to the same first-creature picks).
    """

    def choose_target(self, state, player_id, legal_targets):
        if not legal_targets:
            return None
        # Index every battlefield object by its insertion position so
        # we can pick the lowest-index candidate (= Rust's FIRST
        # creature on that side).
        bf_index = {o.id: i for i, o in enumerate(state.battlefield)}
        best = None
        best_idx = None
        for kind, target_id in legal_targets:
            idx = bf_index.get(target_id)
            if idx is None:
                continue
            if best_idx is None or idx < best_idx:
                best_idx = idx
                best = (kind, target_id)
        # Defensive fallback: if no candidate maps to a bf object
        # (should not happen for the creature-target pools this shim
        # serves), keep the offered order's first entry.
        return best if best is not None else legal_targets[0]


class _PickFirstLibraryOptionAgent(Agent):
    """Pick ``option_ids[0]`` for a ``choose_card_from_library`` hook.

    Mirrors Rust's ``auto_resolve_pending_decisions("reveal_yes")``
    strategy for ``PendingDecision::LookAtTopNRevealOrCounterChoice``
    (state_ops_decisions.rs:425-442): it scans the examined ``cards``
    in popped order and picks the FIRST one matching the filter. The
    Python ``LookAtTopNRevealOrCounter.resolve``
    (effects/generic/library_lookat.py:84-89) pre-filters
    ``examined`` to ``options = [c for c in examined if
    self._matches(c.printing)]`` (same popped order) and passes
    ``[c.id for c in options]`` to ``choose_card_from_library``.
    Returning ``option_ids[0]`` therefore selects the SAME first
    filter-matching examined card Rust's reveal_yes strategy picks —
    keeping the reveal path byte-equal on probes that stage the same
    library prefix on both engines.

    Used by: the genuine real-EoE Pulsar Squadron Ace reveal-path
    divergence-pin probe (which drives the Spacecraft-reveal arm to
    surface the Rust ``card_matches_filter`` ``card_types``-vs-
    ``subtypes`` mismatch — see
    ``docs/SEARCH_LIMITATIONS.md`` round-55 entry). Reusable by any
    future LookAtTopNRevealOrCounter / tutor-style probe whose Rust
    mirror is the first-filter-match auto-resolve.
    """

    def choose_card_from_library(self, state, player_id, option_ids):
        return option_ids[0] if option_ids else None


class _SacrificeFirstAgent(Agent):
    """Pick the first legal sacrifice id.

    Mirrors Rust's ``Effect::EachOpponentSacrificesCreature``
    deterministic opponent-bf-first-creature pick
    (state_ops_resolve.rs:6529-6539). Python's
    ``EachOpponentSacrificesCreature`` calls
    ``p.agent.choose_sacrifice(state, p.id, [o.id for o in legal])``
    where ``legal`` is the opponent's bf filtered to creatures (and
    nontoken on the Python side). Returning ``legal_object_ids[0]``
    matches Rust's bf-iter-first-creature pick exactly when both
    engines see the same bf composition in the same order.

    Used by: Susurian Dirgecraft probe (seated on p1, the
    sacrificing opponent -- not on the source's controller).
    """

    def choose_sacrifice(self, state, player_id, legal_object_ids):
        assert legal_object_ids, "agent called with empty legal pool"
        return legal_object_ids[0]


class _DiscardFirstAgent(Agent):
    """Pick the first card in hand to discard.

    Mirrors Rust's ``Effect::EachOpponentDiscards`` deterministic
    opponent-hand[0] pick (state_ops_resolve.rs:3489).

    Used by: Virus Beetle probe (seated on p1, the discarding
    opponent — not on the source's controller).
    """

    def choose_discard(self, state, player_id, hand_ids):
        assert hand_ids, "agent called with empty hand"
        return hand_ids[0]


class _SurveilSendAllAgent(Agent):
    """Mill every observed surveil card to the graveyard.

    Mirrors Rust's ``auto_resolve_pending_decisions(
    "send_all_to_graveyard")`` strategy: every card carried by the
    SurveilChoice gets routed to the controller's graveyard in popped
    order. Python's ``Surveil.resolve``
    (effects/generic/library_lookat.py:591) walks
    ``examined = p.library[:n]`` in order and invokes
    ``p.agent.choose_surveil(state, p.id, card.id)`` once per card;
    returning ``True`` removes the card from the library and pushes
    it onto the graveyard. Returning ``True`` unconditionally drives
    every observed card to the graveyard, matching Rust's
    send_all_to_graveyard strategy bit-for-bit on probes that build
    the same library prefix on both engines.

    Used by: Starbreach Whale surveil-mill probe (the
    keep_all_on_top default's mirror; this drives the
    send_all_to_graveyard branch of the surveil substrate).
    """

    def choose_surveil(self, state, player_id, top_card_id):
        return True


class _PickBottomLibraryAgent(Agent):
    """Pick "bottom" when offered a top-vs-bottom library mode choice.

    Mirrors Rust's
    ``Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary``
    deterministic bottom pick (state_ops_resolve.rs:5266 uses
    ``lib_mut.push(obj)`` -- end of the Vec is the bottom of the
    library per the post-CE3 Vec convention). Python's
    ``OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary.resolve``
    (effects/generic/zone_moves.py:87-93) calls
    ``owner.agent.choose_mode(state, owner_id, ["top of library",
    "bottom of library"])`` with mode index 0 = top, 1 = bottom.
    Returning 1 unconditionally drives the bounced permanent to the
    OWNER's library bottom, matching Rust's first-slice deterministic
    bottom pick bit-for-bit.

    Seated on the OWNER of the bait permanent (NOT the source's
    controller) since CR 401.1 routes the card to the owner's library
    and the choose_mode hook is called on the owner's agent. In the
    cross-controller probe shape (source on P1, bait owned by P0),
    this means seating ``_PickBottomLibraryAgent`` on P0.

    Used by: I78 cross-controller probe
    (owner_puts_target_artifact_or_creature_on_top_or_bottom_of_library).
    """

    def choose_mode(self, state, player_id, mode_descriptions):
        # mode 0 = "top of library", mode 1 = "bottom of library".
        # Return 1 to mirror Rust's first-slice deterministic bottom
        # pick (cards.rs:1151-1158 docstring + state_ops_resolve.rs:5266).
        return 1


class _PayOptionalSacFirstAgent(Agent):
    """The OPTIONAL-COST MIRROR shim: drive ``Optional…ForEffect``'s
    agent-decision leg IDENTICALLY to Rust's deterministic resolve so
    the optional-cost wrapper is byte-equal cross-engine.

    THE CROSS-ENGINE ASYMMETRY THIS NEUTRALISES
    -------------------------------------------
    ``Effect::OptionalSacArtifactForEffect`` (Selfcraft-Mechan shape:
    "When this enters, you may sacrifice an artifact. If you do,
    [inner]") resolves the may-leg with NO agent ambiguity on the Rust
    side: ``state_ops_resolve.rs:5551-5630`` auto-says-YES and picks
    the FIRST artifact on the source-controller's battlefield
    (insertion / Vec order — no PendingDecision, no pause). Python's
    ``OptionalSacArtifactForEffect.resolve``
    (``effects/combinators.py:299``) instead asks the controller's
    ``Agent.choose_yes_no`` and, on yes, ``Agent.choose_sacrifice``.
    Left to the default base ``Agent``, ``choose_sacrifice`` raises
    ``NotImplementedError`` — so a cross-engine probe of any real
    ``OptionalSacArtifactForEffect`` card cannot even run, let alone be
    byte-equal. This shim makes Python take the EXACT branch Rust takes
    deterministically:

      * ``choose_yes_no`` → ``True`` (Rust always pays the optional
        sacrifice when ≥1 artifact is available — there is no
        "decline" path in its resolve arm).
      * ``choose_sacrifice`` → ``legal_object_ids[0]`` — the FIRST
        offered id. The probe seats the artifacts so that the
        battlefield-insertion order on BOTH engines makes ``[0]`` the
        SAME object (the established ``_SacrificeFirstAgent`` /
        ``OptionalSacArtifact`` bridge-docstring convention at
        ``cross_engine.py:3567-3578``: seat the intended sacrifice
        FIRST so Rust's bf-iter-first pick and Python's offered-[0]
        pick coincide).

    BYTE-EQUAL-SAFETY (no Python-vs-Rust asymmetry introduced)
    ----------------------------------------------------------
    This shim does NOT make a choice Rust wouldn't — it forces Python
    onto Rust's single deterministic branch (yes + first), exactly the
    canon the ``_PickFirst*`` / ``_SacrificeFirstAgent`` shims follow
    (force the Python agent onto Rust's lone at-resolve path). It adds
    NO degree of freedom: Rust has exactly one behaviour here and this
    shim reproduces it. The optional-cost WRAPPER is therefore
    byte-equal by construction — the sacrificed artifact leaves the
    battlefield to its owner's graveyard on BOTH engines (verified:
    a synthetic ``OptionalSacArtifactForEffect(draw_cards{1})`` carrier
    yields ``compare_fields == []``; the focused self-test
    ``test_optional_cost_mirror_idiom_self_test_byte_equal`` pins this).

    WHAT THIS SHIM DELIBERATELY DOES NOT CLAIM (honest scope)
    ---------------------------------------------------------
    It mirrors the optional-cost WRAPPER only. If the wrapped inner
    effect itself carries a SEPARATE, pre-documented Python/Rust
    asymmetry, that asymmetry is NOT this shim's to launder and the
    probe must document it as a targeted-delta — never paper it over.
    Concretely: Selfcraft Mechan's real inner is
    ``Sequence([PutPlusOneCounterOnTargetCreature, DrawCards])``; the
    ``PutPlusOneCounterOnTargetCreature`` leg has the
    independently-documented bare-``add_counters`` target-filter
    asymmetry (``cross_engine.py:6722-6732``: Rust's first-slice
    ``AnyCreature`` picker takes ``bf[0]`` blindly while Python's
    ``IsCreature()`` slot filter narrows — divergent when a non-creature
    artifact precedes a creature on the bf, which the sacrifice setup
    necessarily creates). The genuine Selfcraft Mechan probe asserts
    the WRAPPER observable byte-equal (the sacrificed artifact → owner
    graveyard on BOTH) and carries a strict, precisely-scoped
    targeted-delta for ONLY those inner-leg fields, FAIL-loud on any
    other divergence (regression detection preserved). The
    ``OptionalManaCostThenEffect`` cards (Oreplate Pangolin / Kavaron
    Harrier) need no agent at all — their byte-equal mirror is the
    no-mana DECLINE branch (a deterministic both-engines-no-op; see the
    probe module docstring).

    Used by: the genuine real-EoE optional-cost-mirror probe batch
    (``tests/test_probe_idiom_unlocked_optional_cost_mirror.py``):
    Selfcraft Mechan (the ``OptionalSacArtifactForEffect`` consumer).
    """

    def choose_yes_no(self, state, player_id, prompt):
        # Rust's OptionalSacArtifactForEffect resolve has no decline
        # path — it always pays when ≥1 artifact exists. Mirror that.
        return True

    def choose_sacrifice(self, state, player_id, legal_object_ids):
        assert legal_object_ids, (
            "optional-cost mirror: agent called with empty legal "
            "sacrifice pool — the probe must seat ≥1 artifact"
        )
        # Rust picks the FIRST artifact in bf-insertion order; the
        # probe seats the intended sacrifice FIRST so offered-[0]
        # coincides with Rust's bf-iter-first pick.
        return legal_object_ids[0]

    def choose_target(self, state, player_id, legal_targets):
        # Forwarded inner-effect targeting (e.g. the Selfcraft Mechan
        # inner Sequence's PutPlusOneCounterOnTargetCreature leg). Pick
        # the first legal target — deterministic; the inner-leg
        # filter-asymmetry (if any) is documented as a targeted-delta
        # by the consuming probe, NOT hidden here.
        return legal_targets[0] if legal_targets else None
