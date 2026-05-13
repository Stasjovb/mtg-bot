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
