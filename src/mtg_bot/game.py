"""Game state: zones, game objects, players, stack, and GameState."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Optional

from mtg_bot.cards import CardPrinting
from mtg_bot.effects.modifiers import (
    active_static_abilities as _active_static_abilities_impl,
)

if TYPE_CHECKING:
    from mtg_bot.agents import Agent
    from mtg_bot.effects import ActivatedAbility, TriggeredAbility
    from mtg_bot.turn import Step


class Zone(Enum):
    LIBRARY = "library"
    HAND = "hand"
    BATTLEFIELD = "battlefield"
    GRAVEYARD = "graveyard"
    EXILE = "exile"
    STACK = "stack"
    # CR 408 — the command zone. Emblems (CR 114) live here. The only
    # command-zone object kind the engine models today is the emblem;
    # an emblem is a synthetic ``GameObject`` carrying a synthetic
    # ``CardPrinting`` whose sole content is the emblem's ability set,
    # held in ``GameState.emblems`` (see the ``CreateEmblem`` effect +
    # the emblem-sourced begin-combat trigger dispatch).
    COMMAND = "command"


class _CowList(list):
    """Copy-on-write list used for the library, graveyard, and exile zones.

    Why this exists
    ---------------
    ``GameState.clone()`` is the search hot path. Profiling showed that
    the per-card ``clone_obj`` call inside ``[clone_obj(o) for o in
    p.library]`` dominates clone time — most cards in those three zones
    are never touched during a given rollout, so deep-cloning them is
    pure waste.

    A naive "share the GameObjects, copy the list" approach (the original
    cow-library commit ``73df2ab`` plus its graveyard/exile follow-up
    ``52f4389``) was reverted in ``2864cc2``: the engine's draw / mill /
    exile-from-library / etc. paths do ``card = p.library.pop(0);
    p.hand.append(card); card.zone = HAND``. The in-place mutation
    ``card.zone = HAND`` happened on a GameObject that was *also* in the
    parent state's library list — so the parent state silently
    corrupted, and a downstream ``apply_action`` blew up with
    ``ValueError: card N not castable by PX``.

    The fix
    -------
    A list subclass that tracks per-instance ownership state and, on
    first in-place mutation, isolates ``self`` from its sibling
    sharers. The non-obvious bit is the FORK DIRECTION:

    A naive design (what an earlier attempt at f57125c did) clones
    ``self``'s elements into ``self``'s own backing storage. That
    fixes the simple ``card = p.library.pop(0); card.zone = HAND``
    pattern (because ``pop`` returns the freshly-cloned element), but
    it does NOT fix the very common ``card = next(c for c in p.exile
    if ...); p.exile.remove(card); card.zone = HAND`` pattern: the
    caller's ``card`` reference predates the fork, so it points at
    the OLD shared GameObject, and the subsequent ``card.zone = HAND``
    leaks to every sibling state.

    The fix here is to fork in the OPPOSITE direction: ``self`` keeps
    its original element identities, and the SIBLINGS get fresh
    cloned copies. The caller's ``card`` reference stays valid (it
    points into ``self``'s storage, which never changed identity).
    Mutations on those caller-held elements only affect ``self``'s
    state; siblings hold independent fresh clones and are unaffected.

    Per-instance state:

    - ``_owned``: ``True`` for an independent (no-share) backing
      storage. ``False`` for a "shared view" — there exist one or
      more sibling ``_CowList``s whose contents are the same Python
      GameObject instances as ours.

    - ``_clone_each``: when shared, the per-element clone function
      called for siblings during fork. ``None`` once owned.

    - ``_share_group``: when shared, the (mutable) list of all
      sibling ``_CowList`` instances — typically a source list and
      its clones. The list is THE SAME OBJECT across every member of
      the group, so adding a new clone is O(1) (one ``append``) and
      bookkeeping cost doesn't scale with the share-group size. On
      fork, we filter ``self`` out by identity, install fresh clones
      into the remaining peers, and re-tie those peers into a new
      shared group of one-smaller size.

    Every list mutator (``append``, ``pop``, ``remove``,
    ``__setitem__``, etc.) starts with ``_fork_if_shared``. Reads
    (``__getitem__``, ``__iter__``, ``__len__``, ``__contains__``,
    slicing) pass through to ``list``'s C implementations unchanged —
    sharing is transparent for read-only access, the common case
    during MCTS expansion / evaluation.

    Invariant for a clone-time pair
    -------------------------------
    Right after ``GameState.clone()``:

        source.library:  _CowList shared view, _owned=False
        clone.library:   _CowList shared view, _owned=False
        # both reference the same GameObject instances; both
        # ``_share_group`` slots point at the SAME ``[source.library,
        # clone.library]`` list.

    The first one to mutate — say the clone — calls
    ``_fork_if_shared``: build cloned elements, install them in the
    SOURCE (peer), mark source ``_owned=True``, and self
    ``_owned=True`` (self kept the originals). The caller's
    references into ``self`` remain valid; the source has its own
    independent fresh GameObjects.

    Multi-clone support: when a third clone is created off the same
    source (3-way share), it joins the same ``_share_group`` list via
    one ``append``. On fork, the mutator removes itself from the
    group, clones for the other two members, and re-ties them into a
    new shared group of size 2.

    Caveat: direct attribute mutation through pure iteration
    --------------------------------------------------------
    A pattern like::

        for card in p.library:
            card.printing = something_else  # no list-level mutation

    will NOT trigger the fork because the iteration doesn't go
    through any of the list mutators. The only such site in the
    engine today is
    ``mtg_bot.search.determinize._determinize_player`` (printing
    permutation for hidden-information sampling). That path doesn't
    cause the original ``ValueError: card N not castable`` failure
    in practice — see the cow-redux session notes.

    Why not hand / mana_pool
    ------------------------
    Hand cards routinely get mutated in place during the cast pipeline
    (cost prep, additional-cost flags, alt-cost selections). Forking
    the hand on every cast attempt would defeat the optimization.
    Mana pool is small (typically empty or a handful of coins) so
    indirection overhead would outweigh the win. Both stay deep-cloned
    in ``GameState.clone``.
    """

    # ``__slots__`` on a ``list`` subclass: CPython allows it only if
    # we also include ``__dict__`` (list has variable-size internal
    # storage and the subclass inherits that layout). Skip slots and
    # rely on the regular instance dict — the two attrs are tiny and
    # the perf cost is negligible vs. the work each mutator already
    # does.
    _owned: bool
    _clone_each: Optional[Callable[[Any], Any]]
    # When shared, ``_share_group`` is the (mutable) list of all
    # ``_CowList`` instances — typically a source list and one or
    # more clones of it — that currently hold the same GameObject
    # references. The list is the SAME object across every member of
    # the group, so adding a new clone is O(1) (one ``append``) and
    # group bookkeeping doesn't scale with the number of clones. Each
    # member's own slot in the list is the canonical "self" entry —
    # we exclude it on fork by identity. ``None`` once owned. See
    # ``_fork_if_shared``.
    _share_group: Optional[list]

    def __init__(self, iterable=()):
        super().__init__(iterable)
        self._owned = True
        self._clone_each = None
        self._share_group = None

    @classmethod
    def _new_uninitialized(cls, iterable):
        """Build a ``_CowList`` skipping the default-attr init.

        ``GameState.clone`` immediately overwrites ``_owned``,
        ``_clone_each``, and ``_share_group`` after construction.
        The default ``__init__`` writes those three attrs only to
        have them stomped a few lines later — pure waste in the hot
        clone path. This factory does the underlying ``list.__init__``
        and leaves the three attrs unset; the caller is responsible
        for assigning them.

        DO NOT use this outside the clone path: the resulting
        instance has no ``_owned`` attr, so any read before the
        caller assigns one will ``AttributeError``.
        """
        new = cls.__new__(cls)
        list.__init__(new, iterable)
        return new

    def _fork(self) -> None:
        """Slow-path fork: caller has already checked ``_owned`` is False.

        Performs the actual peer-direction clone (``self`` keeps its
        original element identities; peers get fresh clones) — see
        ``fork()`` and the class docstring for the why.

        The peers split: after the fork they get a fresh shared pool of
        cloned elements. If only one peer remains it becomes owned
        outright; otherwise the peers form a new (one-smaller) share
        group. ``self`` is removed from the group.

        Optimization invariant: this method is called from the inlined
        fast-path checks in each mutator (``if not self._owned:
        self._fork()``). Callers MUST guarantee ``self._owned is False``
        before calling — calling ``_fork`` on an already-owned list
        would corrupt sibling state by re-cloning peers' GameObjects
        out from under them. See ``_fork_if_shared`` for the safe-but-
        slightly-slower wrapper that keeps the owned-check.

        Performance notes vs the previous (single-method) form:

        - The fast-path check is now inlined into every mutator, saving
          a Python method call (~13ns / pair on 3.13) on the 90%+ of
          calls that hit the owned branch.
        - The post-fork ``self._clone_each = None`` write from the
          previous form was pure hygiene cost: ``_clone_each`` is only
          READ on the slow path, which is gated behind ``_owned``, so
          once ``self._owned = True`` is committed it's unreachable
          from public API. Dropping the write saves an attribute store
          per fork on self plus one per peer that becomes solo-owned.
          ``_share_group`` IS still nulled (on self and on the peers
          that become owned) — leaving it set creates a self ↔ group
          ↔ peer reference cycle that the cyclic GC has to walk on
          dropoff, measurably slowing the per-iteration ISMCTS fork
          loop in micro-bench (~50% regression observed when the
          nulling was removed).
        - The 2-member share group (the clone-time pair: source ↔
          clone) is the common case in MCTS — handled inline without
          materializing a separate ``peers`` list filter or a
          ``len(peers) == 1`` branch. The 3+-member case (transposition
          merging or multi-rollout siblings) keeps the original
          ``[q for q in group if q is not self]`` filter and re-ties
          the remaining peers into a fresh shared group.
        """
        clone_each = self._clone_each
        group = self._share_group
        if clone_each is None or group is None:
            # Defensive: a shared list with no cloner / group is a
            # programming error. Treat as already-owned to avoid
            # silent corruption.
            self._owned = True
            return
        if len(group) == 2:
            # Common case (a clone-time pair: source ↔ clone, only one
            # peer). Skip the ``peers = [...]`` walk: find the single
            # peer by identity, build the clone pool, install. ``self``
            # keeps its original element identities; the peer becomes
            # owned outright.
            #
            # Note on the ``peer._share_group = None`` cleanup: the
            # group list is now a 2-cycle (group[0] -> group, group[1]
            # -> group, and group itself holds refs back to the two
            # peers via the listcomp). Once ``self`` and ``peer`` go
            # out of scope without breaking the cycle, GC has to walk
            # the cyclic refs in a generational collection rather than
            # reclaiming via simple refcount drop. Nulling the
            # ``_share_group`` slots lets the group list's last
            # references die when the holder dies, which measurably
            # speeds up workloads that fork in a tight loop (the per-
            # iteration ISMCTS case). Same rationale applies to ``self``
            # at the end of this method.
            peer = group[0] if group[0] is not self else group[1]
            list.__init__(peer, [clone_each(o) for o in self])
            peer._owned = True
            peer._share_group = None
            self._owned = True
            self._share_group = None
            return
        # 3+-member share group: materialize the clone pool once so
        # every peer receives the SAME GameObject identities (they
        # form a fresh shared pool that will fork again on the next
        # mutation among themselves).
        cloned = [clone_each(o) for o in self]
        # Identity filter — ``GameObject.__eq__`` could (in theory)
        # ever be made value-based; we always want identity exclusion.
        new_group = [q for q in group if q is not self]
        for peer in new_group:
            list.__init__(peer, cloned)
            peer._share_group = new_group
            # ``_owned`` and ``_clone_each`` already correct (they
            # were set when the peer joined the prior group).
        self._owned = True
        # Drop ``self``'s ref to the prior (now-orphaned) share group
        # so it can be reclaimed without a generational GC pass once
        # all 3+-member peers also re-tie to ``new_group``. Same GC-
        # cycle-avoidance rationale as the 2-member fast path above.
        self._share_group = None

    def _fork_if_shared(self) -> None:
        """Fork ``self`` from its share group if currently shared.

        Public entry point for the share-then-mutate pattern: callers
        that mutate elements in place WITHOUT going through a list
        mutator must call this first to isolate ``self`` from peers.

        Use case: ``search.determinize._determinize_player`` rewrites
        ``card.printing`` directly on GameObjects in ``player.library``.
        That's an in-place mutation on the element, not on the list,
        so the share group never forks naturally — leaving the mutation
        visible to peers. Calling ``library.fork()`` (this method's
        public alias) before the mutation isolates ``self`` first, same
        semantics as a list mutator's implicit fork.

        Internal mutators (``append``, ``pop``, ``__setitem__``, etc.)
        inline the ``if not self._owned`` check directly and call
        ``_fork()`` on the slow path, skipping this method's stack
        frame. This wrapper exists for external callers (``fork()``
        and direct test access) where the inline form isn't available.

        No-op when already owned, so callers can opt in unconditionally.
        """
        if self._owned:
            return
        self._fork()

    def fork(self) -> None:
        """Public alias for ``_fork_if_shared``. See its docstring."""
        if self._owned:
            return
        self._fork()

    # --- mutators: inline the fast-path check, fork on the slow path ----
    #
    # Each mutator inlines ``if not self._owned: self._fork()`` instead
    # of calling ``_fork_if_shared()``. On the 90%+ of calls that hit
    # the owned fast-path this skips a Python method-call frame
    # (measured ~1.2x speedup on a tight append+pop micro-bench). The
    # behavior is identical: ``_fork`` requires-and-asserts the
    # not-owned precondition that's checked here.

    def append(self, item):
        if not self._owned:
            self._fork()
        list.append(self, item)

    def extend(self, iterable):
        if not self._owned:
            self._fork()
        list.extend(self, iterable)

    def insert(self, index, item):
        if not self._owned:
            self._fork()
        list.insert(self, index, item)

    def remove(self, item):
        if not self._owned:
            self._fork()
        list.remove(self, item)

    def pop(self, index=-1):
        if not self._owned:
            self._fork()
        return list.pop(self, index)

    def clear(self):
        if not self._owned:
            self._fork()
        list.clear(self)

    def reverse(self):
        if not self._owned:
            self._fork()
        list.reverse(self)

    def sort(self, *args, **kwargs):
        if not self._owned:
            self._fork()
        list.sort(self, *args, **kwargs)

    def __setitem__(self, index, value):
        if not self._owned:
            self._fork()
        list.__setitem__(self, index, value)

    def __delitem__(self, index):
        if not self._owned:
            self._fork()
        list.__delitem__(self, index)

    def __iadd__(self, other):
        if not self._owned:
            self._fork()
        return list.__iadd__(self, other)

    def __imul__(self, n):
        if not self._owned:
            self._fork()
        return list.__imul__(self, n)

    # --- pickling support ----------------------------------------------

    def __reduce_ex__(self, protocol):
        # Pickle as a plain ``_CowList`` with ``_owned=True`` (a fork has
        # already been forced by serialization, conceptually). The list
        # contents go through ``list``'s native pickling.
        return (
            self.__class__,
            (list(self),),
        )


def _make_shallow_cloner(cls, list_fields: tuple[str, ...] = ()):
    """Generate a fast shallow-copy fn for a ``slots=True`` dataclass.

    The class loses ``__dict__`` under slots, so the previous
    ``__dict__.copy()`` fast path no longer applies. We generate a
    function that does direct per-slot assignment via ``exec`` —
    each ``new.foo = o.foo`` compiles to a single ``LOAD_ATTR`` /
    ``STORE_ATTR`` pair that hits the slot descriptors at C level,
    skipping any Python-level loop overhead.

    ``list_fields`` are slots whose values are mutable lists that
    must be duplicated rather than shared with the source instance.
    They emit ``new.<name> = list(o.<name>)`` — the rest emit a plain
    reference assignment.
    """
    src_lines = ["def _clone(o, _new=cls.__new__, _list=list, _cls=cls):",
                 "    new = _new(_cls)"]
    for slot in cls.__slots__:
        if slot in list_fields:
            src_lines.append(f"    new.{slot} = _list(o.{slot})")
        else:
            src_lines.append(f"    new.{slot} = o.{slot}")
    src_lines.append("    return new")
    src = "\n".join(src_lines)
    ns: dict = {"cls": cls}
    exec(src, ns)
    fn = ns["_clone"]
    fn.__qualname__ = f"_clone_{cls.__name__}"
    return fn


@dataclass(slots=True)
class GameObject:
    """An instance of a card in the game. Uniquely identified by ``id``."""

    id: int
    printing: CardPrinting
    owner_id: int
    controller_id: int
    zone: Zone
    tapped: bool = False
    damage: int = 0
    summoning_sick: bool = True
    attacking: bool = False
    blocking: Optional[int] = None
    blocked_by: list[int] = field(default_factory=list)
    # Marked lethal by a deathtouch source this turn — destroyed by SBAs
    # regardless of damage vs toughness. Cleared when damage is cleared.
    marked_lethal: bool = False
    # "Was this creature dealt damage this turn?" — set True at every site
    # that applies damage (combat damage, _apply_damage, bespoke pingers).
    # Cleared at cleanup. Used by effects with riders gated on
    # "if that creature wasn't dealt damage this turn" (Faller's Faithful).
    damaged_this_turn: bool = False
    # +1/+1 counters raise effective power and toughness by equal amounts.
    # Persist across turns (never wear off on their own).
    plus_one_counters: int = 0
    # -1/-1 counters lower effective power and toughness by equal
    # amounts. Persist across turns. CR 704.5n: at the next SBA
    # check, +1/+1 and -1/-1 counters cancel pairwise — N pairs
    # of each remove min(+1/+1, -1/-1) from each side. The
    # cancellation runs in ``state_based_actions``; the readers
    # in ``_compute_effective_pt`` use the post-cancellation
    # values via this field.
    minus_one_counters: int = 0
    # "You may play this card this turn" — set on cards exiled by
    # impulse-style effects (Territorial Bruntar landfall, Memorial
    # Vault activated). Cleared at cleanup. legal_actions honors it
    # for cast-from-exile at normal cost.
    playable_from_exile_this_turn: bool = False
    # Persistent cast-from-exile permission gated on the controller
    # controlling a Kavu. Set on cards exiled by Possibility
    # Technician's ETB / Kavu observer trigger ("for as long as that
    # card remains exiled, you may play it if you control a Kavu").
    # NOT cleared at cleanup — persists until the card leaves exile.
    # legal_actions honors it for cast-from-exile at normal cost when
    # the controller currently controls at least one Kavu.
    play_from_exile_requires_kavu: bool = False
    # Lightstall Inquisitor exile-from-hand grant: the card's owner may
    # play it from exile for as long as it remains exiled, but each spell
    # cast this way costs {1} more and each land played this way enters
    # tapped.  Set on cards exiled by EachOpponentExilesCardFromHandWithCastPermission;
    # NOT cleared at cleanup — persists until the card leaves exile.
    # Cleared in _cast_spell / _play_land on use.
    cast_from_exile_with_lightstall_surcharge: bool = False
    # Warp-cast state. ``cast_via_warp`` is set True when this card was cast
    # for its warp cost (from hand or, for Timeline Culler, from graveyard).
    # The end-step exile is scheduled as a proper delayed triggered ability
    # on ``state.delayed_triggers`` at cast time (see ``_cast_spell``); this
    # flag is read by effects that key off "if cast via warp" — Astelli
    # Reclaimer's X computation and the ``granted_keywords_if_warp_cast``
    # rider on pump effects (Full Bore). Cleared by ``WarpExileSelf`` when
    # the delayed trigger fires.
    # ``warped`` is set True when this card sits in exile having been exiled
    # via that trigger — it can be cast from exile at its normal cost.
    cast_via_warp: bool = False
    warped: bool = False
    # EoE Spacecraft charge counters. A Spacecraft at ``station_threshold`` or
    # more is a creature (see ``is_creature_now``).
    charge_counters: int = 0
    # Duskmourn Impending: time counters on the permanent and a flag
    # indicating the printed creature type is suppressed. When a card
    # is cast for its impending cost, ``time_counters`` is initialized
    # to ``printing.impending_count`` and ``impending_active`` is set
    # True at ETB. While ``impending_active`` is True ``is_creature_now``
    # returns False even on a printed-creature card type — the
    # permanent is the enchantment half only (no combat, no creature-
    # type targeting). The end-step turn-based action
    # ``run_impending_decrement_turn_based_action`` removes one time
    # counter from each impending-active permanent the active player
    # controls; when the count hits 0 it clears ``impending_active``
    # and the permanent becomes a creature.
    time_counters: int = 0
    impending_active: bool = False
    # Set True at cast time when ``use_impending=True`` so
    # ``put_into_battlefield`` can initialize time counters and
    # ``impending_active`` as the permanent transitions onto the
    # battlefield. Cleared at ETB after the counter init runs (so
    # a blink-and-recast under the printed cost doesn't reactivate
    # the suppression). Mirrors the ``cast_via_warp`` precedent.
    cast_via_impending: bool = False
    # Set True at cast time when this card was cast from its
    # controller's hand (the normal cast path), distinct from casts
    # originating from exile (warped, impulse, Possibility-Technician),
    # the top of the library (Mm'menon grant), or the graveyard
    # (Timeline Culler warp-from-graveyard). Cleared at ETB after the
    # cast-from-hand-only ETB hooks read it (so a blink-and-recast
    # path doesn't carry stale provenance). Consumed by the
    # ``enters_with_minus_one_counters_from_hand_cast`` ETB
    # replacement (Patched Plaything). Default False — only the
    # ``actions._cast_spell`` cast-from-hand branch flips it on.
    cast_via_hand: bool = False
    # Stun counters: a permanent with stun counters doesn't untap during
    # its controller's untap step — instead one stun counter is removed.
    stun_counters: int = 0
    # Silver counters (Karn, Scion of Urza exiles a card "with a silver
    # counter on it"; his -1 returns such a card). Carried on the card
    # object while it sits in exile.
    silver_counters: int = 0
    # Until-end-of-turn bonuses applied by pump effects (e.g. "+3/+0 until
    # end of turn"). Cleared on the cleanup step. Stacked additively when
    # multiple pumps hit the same object.
    temp_power_bonus: int = 0
    temp_toughness_bonus: int = 0
    # The legacy ``extended_temp_power_bonus`` /
    # ``extended_temp_toughness_bonus`` / ``extended_temp_keywords`` /
    # ``extended_temp_expires_at_player_id`` fields ("until your next
    # turn" mirrors keyed on the casting controller) have been retired.
    # P/T deltas at that lifetime now flow through layer-7 ``pump_pt``
    # registry entries with ``expires_at="controller_untap"`` (read by
    # ``_compute_effective_pt``); keyword grants ride
    # ``ApplyEffect(GrantKeywords(...), EndOfYourNextTurn())`` (layer-6
    # ``grant_keyword`` entries under the same lifetime). Both expire
    # via ``run_untap_step``'s
    # ``expire_continuous_effects("controller_untap", player_id=ap.id)``
    # call. ``temp_keywords`` was retired on the same sweep — keyword
    # UEOT grants ride ``grant_keyword`` registry entries with
    # ``expires_at="cleanup"``.
    # Equipment attachment: if this object is Equipment, ``attached_to``
    # is the id of the creature it's attached to (or None if unattached).
    # Plays no role if the object isn't Equipment.
    attached_to: Optional[int] = None
    # Oblivion-Ring-style "until X leaves the battlefield" tracking: when
    # a card is exiled by a specific source, its ``exiled_by_source`` is
    # set to that source's id. When the source leaves the battlefield,
    # move_off_battlefield returns all cards tagged with its id from
    # exile back to their owner's battlefield.
    exiled_by_source: Optional[int] = None
    # Baseline controller captured the first time a layer-2
    # control-change continuous effect targets this permanent
    # (Tractor Beam attaching, or a UEOT control-change like Mutinous
    # Massacre / Systems Override / Threaten). When the registry has
    # no ``"control_change"`` entries for this object,
    # ``effective_controller`` falls back to this value. Cleared by
    # ``move_off_battlefield``'s revert path and by
    # ``run_cleanup_step``'s controller refresh when the last
    # control-grant entry is removed. The legacy
    # ``temp_original_controller_id`` UEOT-revert field has been retired
    # — UEOT control-grants now flow through
    # ``grant_control_change_ueot``'s layer-2 registry entry +
    # baseline-capture, expiring at cleanup.
    controller_id_before_any_aura_swap: Optional[int] = None
    # Planeswalker loyalty counters. Initialized to printing.loyalty
    # when a planeswalker enters the battlefield. State-based actions
    # send planeswalkers with 0 loyalty to the graveyard.
    loyalty_counters: int = 0
    # ``state.turn_number`` at the moment this object last entered the
    # battlefield (stamped by ``actions.put_into_battlefield``). 0 for
    # objects that never entered. Read by "as long as ~ entered this
    # turn" gates (The Wandering Emperor's instant-speed loyalty
    # abilities) -- distinct from ``summoning_sick``, which persists
    # until the controller's NEXT untap step rather than ending with
    # the turn the object entered.
    entered_battlefield_turn: int = 0
    # Saga lore counters. Sagas would get a lore counter at the
    # start of each precombat main phase as a turn-based action;
    # the state-based action (CR 704.5r in audit numbering)
    # sacrifices a saga whose ``lore_counters >=
    # printing.chapter_count``. The chapter-triggered abilities
    # that fire when the lore counter advances aren't modeled in
    # scope.
    lore_counters: int = 0
    # Snapshot of this object's original CardPrinting, taken the first
    # time a "becomes a copy of target X" effect mutates ``printing``.
    # Restored on cleanup? No — "becomes a copy" is a continuous effect
    # with no end condition, so the mutation persists. The snapshot is
    # kept so a second copy activation can re-derive "retained own
    # abilities" (Thespian's Stage: "except it has this ability").
    original_printing: Optional["CardPrinting"] = None
    # Regenerate shield: "The next time this creature would be
    # destroyed this turn, instead remove all damage from it, tap it,
    # and remove it from combat." Set by RegenerateTargetCreature;
    # consumed by state_based_actions when destruction is averted;
    # cleared at cleanup if unconsumed (regeneration is UEOT).
    regeneration_shield: bool = False
    # Phasing — "treat it and anything attached to it as though they
    # don't exist until its controller's next turn." While True, this
    # object is skipped in combat damage assignment. Set by
    # PhaseOutEquippedCreature (Robe of Stars) and cleared at the
    # start of its controller's untap step. Simplification: only
    # combat-damage resolution filters phased objects — triggers,
    # anthems, and legal_actions targeting don't (yet) hide them.
    phased_out: bool = False
    # Reveal-tracking for hidden-information determinization. Each
    # player id in this set has been shown this card's identity in a
    # way that gives them perfect knowledge of where it currently is —
    # e.g. it's their own card, it's in a public zone, or they were
    # shown it as part of resolution (tutor reveal, look-at-hand,
    # cast-from-exile-revealed). When the card moves into a face-down
    # zone whose ordering becomes uncertain (library shuffle, hand
    # mixed back into library), this is reset to ``frozenset()`` to
    # avoid the engine making misinformed claims about what other
    # players still know. See ``docs/HIDDEN_INFO_MODEL.md`` for the
    # design rationale and the under-informed edge cases this
    # representation cannot capture (multi-zone positional uncertainty,
    # cardinality constraints).
    publicly_known_to: frozenset[int] = field(default_factory=frozenset)
    # Timestamp (= ``state.next_timestamp`` snapshot) at the moment
    # this object entered the battlefield. Used to assign a stable
    # "static-effect timestamp" to layered effects that are
    # generated by a permanent's static ability rather than written
    # to the registry directly. The ``effective_subtypes`` walker
    # uses this for Magus-of-the-Moon and Dryad-of-the-Ilysian-Grove
    # ordering: each source's static contributes synthetic layer-4
    # entries with ``timestamp == source.etb_timestamp`` so the
    # within-layer timestamp order matches CR 613.4. 0 means "not
    # yet entered" — orders before any registry entry.
    etb_timestamp: int = 0
    # Painter's Servant: the color chosen as the printing's
    # ``paints_all_objects_chosen_color_at_etb`` ETB resolves.
    # Stored on the GameObject because the choice is per-instance.
    # Consumed by ``effective_colors`` when synthesizing layer-5
    # ``"add_colors"`` entries from this Painter source.
    painter_chosen_color: Optional[str] = None
    # Player chosen "as this enters" (``chooses_player_as_enters``).
    chosen_player_id: Optional[int] = None
    # Face-down marker. CR 701.34 / 707.2: a face-down permanent has
    # no name, no subtypes, and no abilities; it's a 2/2 creature.
    # We keep ``printing`` intact (so ``TurnFaceUp`` can read the
    # underlying card's mana cost and properties), but the engine's
    # effective_* helpers (``effective_power`` / ``effective_toughness``
    # / ``effective_keywords`` / ``effective_subtypes`` /
    # ``is_creature_now``) short-circuit to the face-down 2/2 vanilla
    # view when this flag is True. Set by the ``ManifestDread`` effect
    # at the moment a card becomes a face-down permanent; cleared by
    # the ``TurnFaceUp`` action.
    face_down: bool = False
    # Basic land type chosen as this permanent entered ("As this land
    # enters, choose a basic land type." — Multiversal Passage). Set by
    # ``actions.apply_land_etb_replacements`` on every entry; read by
    # ``effective_subtypes`` for printings with
    # ``is_chosen_basic_land_type`` while the object is on the
    # battlefield.
    chosen_basic_land_type: Optional[str] = None
    # Exerted (CR 701.39): this permanent won't untap during its
    # controller's next untap step. Set by the ``exert_self`` activation
    # cost; ``run_untap_step`` consumes it.
    exerted: bool = False
    # Counters of kinds without a dedicated field ("mining" — Gemstone
    # Mine), as an immutable ``((kind, count), ...)`` tuple so the fast
    # slot-cloner can share it safely. Read / written through
    # ``named_counter_count`` / ``set_named_counters``. Kinds that DO
    # have a dedicated field (+1/+1, charge, time, stun, loyalty, lore)
    # never live here.
    named_counters: tuple = ()
    # DSK Rooms: set of half-names currently unlocked on this Room
    # permanent. When a Room is cast for half A's mana cost, the
    # entering permanent has ``unlocked_halves = frozenset({A})``;
    # ``UnlockRoomHalf`` adds the named half to the set. Locked
    # halves' abilities are filtered out by the effective-ability
    # iterators (``effective_triggered_abilities`` /
    # ``effective_activated_abilities`` / static iteration). When
    # ``len(unlocked_halves) == len(printing.room_halves)``, the Room
    # is fully unlocked — the cast/unlock sites log "Room fully
    # unlocked" so a future Eerie hook can observe it (Eerie itself
    # isn't wired yet). Empty frozenset for non-Room objects.
    unlocked_halves: frozenset[str] = field(default_factory=frozenset)
    # DSK Enduring cycle (Enduring Innocence / Curiosity / Tenacity /
    # Courage / Vitality): when an Enduring creature dies, its
    # ``When this creature dies`` trigger returns the card to the
    # battlefield "as an enchantment" — its printed Creature card type
    # is suppressed for the return. The printing still carries
    # ``"Creature"`` in ``card_types``; this per-instance flag is the
    # in-game suppression marker. Set by the resolving Enduring
    # effect (``EnduringDiesReturnAsEnchantmentEffect``) at the moment
    # the card transits graveyard → battlefield; consumed by
    # ``is_creature_now``, which short-circuits to ``False`` when
    # the flag is True so the returned permanent counts as an
    # enchantment only. Mirrors the ``impending_active`` precedent —
    # same shape (printing keeps the type, GameObject suppresses it
    # at runtime), different mechanic.
    enduring_returned_as_enchantment: bool = False
    # DSK Ghost Vacuum / "flying counter" custom counter type. CR 122
    # recognizes named counters whose name and printed wording grant the
    # named keyword to the bearer ("a flying counter"); engine-side we
    # carry the count as its own integer field on ``GameObject`` parallel
    # to ``plus_one_counters`` / ``stun_counters`` etc. ``effective_keywords``
    # adds ``"flying"`` to the bearer's keyword set whenever this is
    # ``> 0`` so combat / blocker rules pick the granted keyword up
    # automatically — same write-through-cache shape the +1/+1 counter
    # pump path uses for layer-7d P/T contributions.
    flying_counters: int = 0
    # Goad (CR 701.38): id of the player who goaded this creature, or
    # ``None``. A goaded creature attacks each combat if able until the
    # goader's next turn (cleared at the goader's untap step). See
    # ``mtg_bot.designations``.
    goaded_by: Optional[int] = None
    # DSK Haunted Screen "Activate only once" tracking. The printed
    # rider on Haunted Screen's ``{7}: …`` activation reads "Activate
    # only once." which the engine simulates by latching this flag to
    # ``True`` the first time the bespoke ``HauntedScreenActivatedEffect``
    # resolves; subsequent activations of the same ability silently
    # no-op at resolve time. The flag is per-``GameObject`` so a
    # blink-and-recast (a fresh ``GameObject`` instance) gets a fresh
    # one-shot — matches CR 706.2 ("a permanent that has changed zones
    # is a new object").
    has_activated_once_only_ability: bool = False
    # Layer-4 ``add_type "creature"`` write-through cache. Set by
    # ``BecomeType`` whenever it adds the "creature" type (Haunted
    # Screen's "It becomes a 0/0 Spirit creature in addition to its
    # other types." — permanent — and the UEOT manland-animation flow
    # via ``ApplyEffect(BecomeType(...), EndOfTurn())``).
    # ``is_creature_now`` reads this cache; ``run_cleanup_step`` rebuilds
    # it from the registry after expiring cleanup-scoped entries, so a
    # finite-lifetime ``BecomeType`` correctly reverts the cache when
    # its registry entry expires. Indefinite-lifetime entries persist
    # across cleanup so a permanent type-change survives.
    permanent_is_creature: bool = False
    # CR 702.34a: set while a spell cast with flashback is on the stack;
    # the card is exiled instead of going anywhere else when it leaves
    # the stack (``actions.move_spell_off_stack``).
    cast_via_flashback: bool = False
    # The Flashback card: "Target instant or sorcery card in your
    # graveyard gains flashback until end of turn. The flashback cost is
    # equal to its mana cost." Set on the graveyard card; cleared at
    # cleanup and when the card is cast.
    flashback_granted_until_eot: bool = False
    # A copy of a spell on the stack (storm, Chain of Smog). Not a card:
    # it isn't in any zone list and ceases to exist when it leaves the
    # stack (CR 707.10a).
    is_spell_copy: bool = False
    # A modal DFC played as its back face: the front-face printing to
    # restore when the permanent leaves the battlefield (CR 712.8).
    mdfc_front_printing: Optional["CardPrinting"] = None
    # Plot: the turn number the card was plotted (exiled face up) on;
    # -1 when not plotted. Castable for free from exile on a later turn.
    plotted_turn: int = -1
    # "If that creature would leave the battlefield, exile it instead of
    # putting it anywhere else." (From the Catacombs) — honored by every
    # leave-battlefield path while the object stays on the battlefield.
    exile_instead_of_leaving: bool = False


def restore_mdfc_front(obj: "GameObject") -> None:
    """Turn a modal DFC that was played as its back face front-face up
    again (every zone but the battlefield / stack shows the front)."""
    if obj.mdfc_front_printing is not None:
        obj.printing = obj.mdfc_front_printing
        obj.mdfc_front_printing = None


# Fast shallow cloner generated once at module load. ``blocked_by`` is the
# only mutable per-instance field that must be duplicated; every other slot
# is either an immutable scalar / frozenset / Enum or a reference to the
# frozen ``CardPrinting`` (safe to share across clones). Hot-path: called
# ~120× per ``GameState.clone``.
_clone_game_object = _make_shallow_cloner(GameObject, list_fields=("blocked_by",))


def is_void_active(state: GameState) -> bool:
    """EoE Void condition: a nonland permanent left the battlefield this turn
    OR a spell was warped this turn."""
    return (
        state.permanent_left_battlefield_this_turn
        or state.spell_warped_this_turn
    )


# The static-ability surface has exactly ONE accessor, which lives in
# ``effects.modifiers`` next to the CR 613 / CR 614 dispatchers that
# also consume it (``walk_continuous_modifiers`` /
# ``_collect_replacement_effects``). Before this was unified, the
# dispatchers read ``printing.static_abilities`` raw while the layer-6 /
# layer-7c walks here read it through the Room-gated helper: two readers
# of one slot that disagreed both about Room half-locking and about how
# a malformed printing surfaces. ``_active_static_abilities`` stays
# bound here as the in-module name every existing call site uses.
_active_static_abilities = _active_static_abilities_impl


def reveal_to(obj: GameObject, *player_ids: int) -> None:
    """Mark ``obj`` as publicly known to each of ``player_ids``.

    Idempotent. Use this whenever a card's identity is shown to a
    specific set of players in a way that gives them perfect knowledge
    of where the card currently is — e.g. an opponent looks at your
    hand (reveal_to(card, looker_id)) or you tutor with a reveal step
    and put the card into your hand publicly (reveal_to_all(state, card)).

    See ``docs/HIDDEN_INFO_MODEL.md`` for the design and its caveats.
    """
    if not player_ids:
        return
    obj.publicly_known_to = obj.publicly_known_to | frozenset(player_ids)


def reveal_to_all(state: GameState, obj: GameObject) -> None:
    """Mark ``obj`` as publicly known to every player in ``state``.

    Use at every site where a card is revealed publicly — bounce
    (battlefield → hand), tutor-with-reveal landing in hand, casting
    a spell from a private zone (it briefly transits the public
    stack), etc.
    """
    obj.publicly_known_to = frozenset(p.id for p in state.players)


def reset_public_knowledge(obj: GameObject) -> None:
    """Drop everyone from ``obj.publicly_known_to``.

    Call at "disturbance" sites — library shuffles, hand mixed back
    into library, scry-then-shuffle. Conservatively forgets all
    revealed-knowledge state; the bot becomes under-informed rather
    than misinformed about what other players still know.
    """
    obj.publicly_known_to = frozenset()


def reset_library_public_knowledge(state: GameState, player_id: int) -> None:
    """After shuffling ``player_id``'s library, forget who knew what
    about each card in it. Convenience wrapper around
    ``reset_public_knowledge`` for the common "shuffle the whole
    library" case.
    """
    p = state.player_by_id(player_id)
    for card in p.library:
        reset_public_knowledge(card)


def shuffle_library(state: GameState, player_id: int) -> None:
    """Shuffle ``player_id``'s library and reset reveal-tracking on
    every card in it.

    Always use this helper instead of calling ``state.rng.shuffle``
    directly on a library — it keeps shuffle and knowledge-reset paired
    so the engine can never produce a state where the determinizer
    "remembers" a card whose position was actually scrambled.
    """
    p = state.player_by_id(player_id)
    state.rng.shuffle(p.library)
    for card in p.library:
        reset_public_knowledge(card)


def is_stationed(obj: GameObject) -> bool:
    """True when this Spacecraft has enough charge counters to be a creature."""
    threshold = obj.printing.station_threshold
    return threshold is not None and obj.charge_counters >= threshold


def is_creature_now(obj: GameObject) -> bool:
    """Whether ``obj`` currently counts as a creature on the battlefield.

    True for printed creatures, for Spacecraft whose charge-counter
    threshold has been crossed (they're artifact creatures while
    stationed), and for any object whose layer-4 ``add_type "creature"``
    write-through cache (``permanent_is_creature``) is set — covers both
    UEOT manland animations (via ``ApplyEffect(BecomeType, EndOfTurn())``,
    rebuilt to False at cleanup once the registry entry expires) and
    indefinite type-changes (Haunted Screen's "becomes a 0/0 Spirit
    creature in addition to its other types").

    A face-down permanent (``obj.face_down=True``, set by Manifest
    Dread / Morph) is always a 2/2 creature regardless of the
    underlying printing's types — CR 701.34. Face-down identity
    masking takes precedence over Impending suppression below.

    Impending-cast permanents (Duskmourn Overlord cycle) suppress
    the printed creature type while ``impending_active`` is True —
    the printing's ``card_types`` still includes "Creature" but
    this helper returns False until the last time counter is
    removed at the controller's end step (see
    ``run_impending_decrement_turn_based_action``). Impending takes
    precedence over ``is_stationed`` so a future card animating an
    impending Overlord wouldn't wake it early — those are independent
    mechanics.
    """
    if obj.face_down:
        return True
    if obj.impending_active:
        return False
    # DSK Enduring cycle: after the dies-trigger has returned the card
    # to the battlefield "as an enchantment", the printing's Creature
    # card type is suppressed at runtime. The flag is sticky for the
    # remainder of the object's life on the battlefield (CR 400.7 — a
    # new object once it changes zones; clearing happens at the next
    # zone change implicitly via a fresh GameObject instance).
    if obj.enduring_returned_as_enchantment:
        return False
    return (
        obj.printing.is_creature
        or is_stationed(obj)
        or obj.permanent_is_creature
    )


def _source_layer6_wiped(
    state: "GameState", source: "GameObject"
) -> bool:
    """True if the source has any layer-6 ``"lose_all_abilities"``
    registry entry. Used to gate post-layer-6 reads (layer 7c P/T
    bonuses from a static anthem) — by the time layer 7 runs, layer
    6 has wiped the source's abilities, so its static doesn't
    generate the layer-7c effect anymore.

    Layer-6 effects (keyword grants, ability grants) still apply
    via the within-layer dependency rule even when this returns
    True — the dependency reorders the wipe and the grant within
    layer 6 so the recipients keep the granted abilities.

    Memoized per ``(source.id, state._layered_cache_version)`` —
    called inside the doubly-nested ``_static_bonuses`` walk
    (~850k times in a self-play game per the 2026-05-02 perf
    audit). The cache lives on ``state`` and is invalidated by
    every site that mutates ``state.continuous_effects``.
    """
    sid = source.id
    cv = state._layered_cache_version
    cache = state._layer6_wiped_cache
    cached = cache.get(sid)
    if cached is not None and cached[0] == cv:
        return cached[1]
    # Explicit loop, not ``any(<genexp>)``: a genexp that reads ``sid``
    # makes ``sid`` a CELL variable of this function, and cells share
    # the frame's ``localsplus`` array with the fast locals. See the
    # ``_static_bonuses`` "closure-free hot path" note for why that
    # matters on CPython 3.13.
    wiped = False
    for ce in state.continuous_effects:
        if (
            ce.layer == 6
            and ce.kind == "lose_all_abilities"
            and ce.target_id == sid
        ):
            wiped = True
            break
    cache[sid] = (cv, wiped)
    return wiped


def _static_bonuses(
    state: GameState, obj: GameObject
) -> tuple[int, int, frozenset[str]]:
    """Walk the battlefield for static abilities that buff ``obj``.

    Returns (power_bonus, toughness_bonus, granted_keywords). Used by
    the effective_* helpers. Also folds in bonuses from any
    Equipment attached to ``obj``.

    Bifurcated by layer:

    - Granted keywords (Sliver lord's "Slivers have haste/double
      strike", Equipment riders) are layer-6 effects. A Lignified
      / Humility'd source STILL contributes them via the CR 613.7
      within-layer dependency rule — the wipe targets the source,
      not the recipients of its grants.
    - P/T bonuses (Lord of Atlantis's "+1/+1 to other Merfolk",
      Memorial Team Leader's "+1/+0 to other creatures",
      Bonesplitter's equipped-creature +3/+0) are layer-7c effects.
      By the time layer 7c is computed, layer 6 has run and the
      source's static doesn't exist anymore — so a Lignified
      source DOES NOT contribute its P/T bonus.

    The famous case: Lord of Atlantis + Humility. Coralhelm
    Commander becomes 1/1, not 2/2 — the Lord's +1/+1 doesn't
    apply because the Lord's static is wiped before layer 7c.

    Modifier-grammar layer-7c contributions (PR D continuous-effects):
    in addition to the legacy per-StaticAbility ``power_bonus`` /
    ``toughness_bonus`` reads above, also walk every active
    ``ContinuousModifier`` declared on a printing's static abilities
    via :func:`mtg_bot.effects.modifiers.walk_continuous_modifiers`
    and fold in any ``PowerToughnessBonus`` payloads at layer 7. The
    Lignify-skip discipline applies to this path too — a wiped source
    contributes zero. Today no migrated card declares a
    ``ContinuousModifier(layer=7, payload=PowerToughnessBonus(...))``,
    so this walk is a no-op contributor; the wiring is here so PR-D
    anthem migrations can drop ``power_bonus``/``toughness_bonus``
    fields and produce ``ContinuousModifier`` declarations instead.

    Closure-free hot path (CPython 3.13 mitigation)
    -----------------------------------------------
    This function, ``_source_layer6_wiped`` and ``_compute_effective_pt``
    deliberately use explicit loops instead of generator expressions /
    comprehensions that read an enclosing local. A genexp that reads an
    enclosing local turns that local into a CELL variable, and cells
    live in the same ``localsplus`` array as the frame's fast locals
    (immediately after ``co_nlocals`` entries). This is one of the
    hottest functions in the engine (~850k calls per self-play game),
    so it is a prime target for the specializing interpreter.

    Two production self-play crashes point at exactly that array:

    - ``AttributeError: 'cell' object has no attribute 'attached_to'``
      raised at the ``source.attached_to`` read in the Equipment walk
      below — i.e. the loop variable ``source`` came back holding this
      frame's closure cell. No engine code can put a ``cell`` into
      ``state.battlefield``.
    - ``TypeError: 'ContinuousModifier' object is not iterable`` raised
      from ``walk_continuous_modifiers``' read of
      ``source.printing.static_abilities`` — while the FIRST walk below
      (``_active_static_abilities``), which reads the same slot off the
      same list in the same frame, had just succeeded. A genuinely
      malformed printing raises at the first walk; verified by
      construction.

    ``search/mcts.py`` documents the same class of defect (intermittent
    ``NameError`` / ``AttributeError`` from CPython 3.13's specializing
    interpreter against a dataclass-mutation hot loop) and works around
    it the same way — by removing the pattern rather than the symptom.
    This is a MITIGATION, not a proven fix: it removes the buggy fast
    path's precondition from these frames. Keep new code in this call
    tree closure-free.
    """
    from mtg_bot.effects.modifiers import (
        PowerToughnessBonus, walk_continuous_modifiers,
    )

    power_bonus = 0
    toughness_bonus = 0
    granted: set[str] = set()
    for source in state.battlefield:
        wiped = _source_layer6_wiped(state, source)
        for ability in _active_static_abilities(source):
            if not ability.applies_to(source, obj, state):
                continue
            granted |= ability.granted_keywords
            if not wiped:
                if ability.bonus_per_condition_count:
                    per = ability.condition.multiplier(
                        state, source.controller_id,
                    )
                    power_bonus += ability.power_bonus * per
                    toughness_bonus += ability.toughness_bonus * per
                else:
                    power_bonus += ability.power_bonus
                    toughness_bonus += ability.toughness_bonus
    # Equipment attached to obj contributes its equipment_bonuses.
    # The keyword grants and P/T bonuses on the equipment riders
    # follow the same layer split as static abilities above.
    for source in state.battlefield:
        if source.attached_to != obj.id:
            continue
        eb = source.printing.equipment_bonuses
        if eb is None:
            continue
        ep, et, ek = eb
        granted |= ek
        if not _source_layer6_wiped(state, source):
            power_bonus += ep
            toughness_bonus += et
    # Modifier-grammar layer-7c contributions (PR D continuous-effects
    # path). Currently a no-op contributor — no migrated card
    # declares a layer-7 PowerToughnessBonus continuous modifier yet.
    for src_id, mod in walk_continuous_modifiers(state, obj):
        if mod.layer != 7 or not isinstance(mod.payload, PowerToughnessBonus):
            continue
        source = None
        for candidate in state.battlefield:
            if candidate.id == src_id:
                source = candidate
                break
        if source is None or _source_layer6_wiped(state, source):
            continue
        power_bonus += mod.payload.power_bonus
        toughness_bonus += mod.payload.toughness_bonus
    return power_bonus, toughness_bonus, frozenset(granted)


def effective_controller(state: GameState, obj: GameObject) -> int:
    """Return the controller id of ``obj`` after applying CR 613
    layer 2 (control-changing effects).

    Walks ``state.continuous_effects`` for entries with
    ``layer == 2`` and ``kind == "control_change"`` whose
    ``target_id`` matches ``obj.id``; the latest-timestamp entry
    wins (most recently created control-grant). When no entries
    apply, returns ``obj.controller_id_before_any_aura_swap`` if set
    (the captured-baseline controller from the first time a control
    grant was applied), else ``obj.controller_id`` (the printed
    baseline).

    Phase 2 of the layered-effects refactor: this replaces the
    bespoke ``aura_control_grants`` LIFO stack on GameObject. The
    stored ``obj.controller_id`` field is now a write-through cache
    of this function's value — every registry-mutating site
    (``apply_aura_static_grants_on_attach``,
    ``move_off_battlefield``'s revert path) calls
    ``_recompute_obj_controller`` to keep the cache in sync, so
    existing reads of ``obj.controller_id`` continue to return the
    right value.
    """
    # Layer 2 runs before layer 6 in CR 613.1 strict layer order, so
    # a Humility / Lignify wipe of the source (layer 6) does NOT
    # retroactively undo this layer-2 control grant: the layer-2
    # effect was already applied. We do NOT skip on
    # _source_abilities_suppressed here.
    latest: int | None = None
    latest_ts: int = -1
    for ce in state.continuous_effects:
        if (
            ce.layer == 2
            and ce.kind == "control_change"
            and ce.target_id == obj.id
            and ce.timestamp > latest_ts
        ):
            latest_ts = ce.timestamp
            latest = ce.params[0]
    if latest is not None:
        return latest
    if obj.controller_id_before_any_aura_swap is not None:
        return obj.controller_id_before_any_aura_swap
    return obj.controller_id


def _layer6_entries_for(
    state: "GameState", obj: "GameObject",
) -> list["ContinuousEffect"]:
    """Collect every layer-6 continuous-effect entry that targets
    ``obj`` — both real registry entries AND synthesized entries
    from static-anthem sources on the battlefield. Synthesized
    entries carry the source's ``etb_timestamp`` so the within-
    layer-6 timestamp walk in ``effective_keywords`` /
    ``effective_activated_abilities`` /
    ``effective_triggered_abilities`` interleaves them correctly
    with registry-based grants and ``"lose_all_abilities"`` wipes.

    Synthesized sources:
    - Static anthems with ``granted_keywords`` (Sliver lord style).
    - Equipment ``equipment_bonuses`` keyword riders attached to
      ``obj``. The Equipment's ``etb_timestamp`` is the rider's
      timestamp.
    - Humility-style global wipes: when any source on the
      battlefield has the ``wipes_all_creature_abilities`` flag
      and ``obj`` is a creature, synthesize a
      ``"lose_all_abilities"`` entry sourced by that permanent
      with its ``etb_timestamp``.
    """
    from mtg_bot.effects.modifiers import GrantKeyword

    entries: list["ContinuousEffect"] = [
        ce for ce in state.continuous_effects
        if ce.layer == 6 and ce.target_id == obj.id
    ]
    # Static-anthem keyword grants from sources on the battlefield.
    for source in state.battlefield:
        for ability in _active_static_abilities(source):
            if not ability.applies_to(source, obj, state):
                continue
            for kw in ability.granted_keywords:
                entries.append(ContinuousEffect(
                    source_id=source.id,
                    layer=6,
                    timestamp=source.etb_timestamp,
                    kind="grant_keyword",
                    target_id=obj.id,
                    params=(kw,),
                    description=(
                        f"{source.printing.name} grants {kw}"
                    ),
                ))
            # PR D continuous-effects: anthem keyword grants migrated to
            # ``ContinuousModifier(layer=6, GrantKeyword)`` declarations
            # are synthesized into layer-6 entries here too so the
            # within-layer-6 timestamp walk interleaves them with
            # ``lose_all_abilities`` wipes correctly. The legacy
            # ``granted_keywords`` walk above stays for non-migrated
            # callers (Equipment riders contribute via equipment_bonuses
            # below; SELF-scope statics still use granted_keywords).
            ce_mod = ability.continuous_effect
            if ce_mod is None or ce_mod.layer != 6:
                continue
            if not isinstance(ce_mod.payload, GrantKeyword):
                continue
            if ce_mod.subject_filter is not None and not ce_mod.subject_filter.test(
                obj, state,
            ):
                continue
            entries.append(ContinuousEffect(
                source_id=source.id,
                layer=6,
                timestamp=source.etb_timestamp,
                kind="grant_keyword",
                target_id=obj.id,
                params=(ce_mod.payload.keyword,),
                description=(
                    f"{source.printing.name} grants "
                    f"{ce_mod.payload.keyword}"
                ),
            ))
    # Equipment keyword riders.
    for source in state.battlefield:
        if source.attached_to != obj.id:
            continue
        eb = source.printing.equipment_bonuses
        if eb is None:
            continue
        _, _, ek = eb
        for kw in ek:
            entries.append(ContinuousEffect(
                source_id=source.id,
                layer=6,
                timestamp=source.etb_timestamp,
                kind="grant_keyword",
                target_id=obj.id,
                params=(kw,),
                description=(
                    f"{source.printing.name} grants {kw} via equip"
                ),
            ))
    # Humility-style global wipe: applies only to creatures.
    if is_creature_now(obj):
        for source in state.battlefield:
            if source.printing.wipes_all_creature_abilities:
                entries.append(ContinuousEffect(
                    source_id=source.id,
                    layer=6,
                    timestamp=source.etb_timestamp,
                    kind="lose_all_abilities",
                    target_id=obj.id,
                    params=(),
                    description=(
                        f"{source.printing.name}: "
                        f"creatures lose all abilities"
                    ),
                ))
    return entries


def effective_keywords(state: GameState, obj: GameObject) -> frozenset[str]:
    """Keywords in effect right now, computed in CR-613 layer-6
    timestamp order.

    Base set (treated as before any layer-6 entry, since these
    inherent properties don't carry a layer-6 timestamp in our
    model):
    - ``obj.printing.keywords``
    - ``obj.printing.stationed_keywords`` if stationed

    Layer-6 entries (real + synthesized via
    ``_layer6_entries_for``) walked in timestamp order:
    - ``"lose_all_abilities"`` clears the set entirely.
    - ``"grant_keyword"`` adds ``params[0]``. UEOT grants carry
      ``expires_at="cleanup"`` (dropped at this turn's cleanup);
      "until your next turn" grants carry
      ``expires_at="controller_untap"`` with the controller's id
      (dropped at that controller's next untap step).

    Static-anthem keyword grants from a Sliver-lord-style source
    are synthesized as layer-6 ``grant_keyword`` entries with the
    source's ``etb_timestamp``. So a Lignify-OLDER-than-lord
    correctly grants the keyword (Sliver lord's anthem applies
    after the older Lignify wipe). Similarly Equipment keyword
    riders carry the equipment's etb_timestamp.

    A face-down permanent (CR 701.34 / 707.2) has no abilities,
    so it carries no keywords — short-circuit before walking the
    layer-6 entries.
    """
    if obj.face_down:
        return frozenset()
    kws: set[str] = set(obj.printing.keywords)
    if is_stationed(obj):
        kws |= set(obj.printing.stationed_keywords)
    layer6 = sorted(_layer6_entries_for(state, obj), key=lambda ce: ce.timestamp)
    for ce in layer6:
        if ce.kind == "lose_all_abilities":
            kws.clear()
        elif ce.kind == "grant_keyword" and ce.params:
            kws.add(ce.params[0])
    # ContinuousModifier contributions from StaticAbility declarations.
    # Walked after the registry-based layer-6 pass so the existing
    # grant_keyword / lose_all_abilities ordering is preserved. Only
    # ``RemoveKeyword`` payloads are folded in here — ``GrantKeyword``
    # payloads are already synthesized into the layer-6 timestamp walk
    # above (via ``_layer6_entries_for``), so re-adding them here would
    # re-grant a wiped keyword.  RemoveKeyword has no lose_all_abilities
    # interaction in the current EoE pool (Mechan Shieldmate
    # RemoveKeyword("defender") never overlaps with a layer-6 wipe), so
    # post-walk application is CR-correct.
    from mtg_bot.effects.modifiers import RemoveKeyword, walk_continuous_modifiers
    for _src_id, mod in walk_continuous_modifiers(state, obj):
        if isinstance(mod.payload, RemoveKeyword):
            kws.discard(mod.payload.keyword)
    # CR 122 named counters that grant keywords — currently just the
    # "flying counter" custom counter type (DSK Ghost Vacuum). The
    # counter is its own integer field on ``GameObject``; a positive
    # count contributes the matching keyword to the bearer regardless
    # of how the counter got there. Folded in AFTER the layer-6 walk so
    # a Lignify wipe on the bearer doesn't cancel the counter's grant
    # — counters are not abilities (CR 122) so layer-6 ``lose_all_
    # abilities`` doesn't touch them. A future named-counter type
    # (haste counter, shield counter, …) lands as a sibling field
    # with the same shape rather than a generalized counter-name map,
    # mirroring the per-counter-type field precedent (``stun_counters``
    # / ``time_counters`` / ``charge_counters``).
    if obj.flying_counters > 0:
        kws.add("flying")
    return frozenset(kws)


def is_cant_be_blocked(state: GameState, obj: GameObject) -> bool:
    """Return True iff ``obj`` currently has the "can't be blocked"
    continuous effect — the structural counterpart to
    :func:`effective_keywords` for the can't-be-blocked restriction.

    "Unblockable" is NOT a keyword in MTG — it's a layer-6 continuous
    effect that imposes a gameplay-action restriction (CR 509.1b
    blocker-declaration rejects the assignment). The bot models it
    via two parallel sources, mirroring how
    :func:`effective_keywords` walks both registry entries and
    ``ContinuousModifier`` declarations:

    1. Registry-side: layer-6 ``cant_be_blocked`` continuous-effect
       entries (written by :class:`GrantUnblockable` and the manland
       / Atomic Microsizer animation paths).
    2. Modifier-grammar side: layer-6 ``ContinuousModifier`` whose
       payload is :class:`CantBeBlocked`, walked via
       :func:`walk_continuous_modifiers` (Illvoi Infiltrator's printed
       conditional-unblockable static).

    A face-down permanent has no abilities (CR 701.34 / 707.2) and
    therefore can't carry continuous-effect declarations from its
    own static abilities; registry entries written by other sources
    still apply, mirroring the asymmetry on the keyword side.
    """
    for ce in state.continuous_effects:
        if (
            ce.layer == 6
            and ce.kind == "cant_be_blocked"
            and ce.target_id == obj.id
        ):
            return True
    if obj.face_down:
        return False
    from mtg_bot.effects.modifiers import (
        CantBeBlocked, walk_continuous_modifiers,
    )
    for _src_id, mod in walk_continuous_modifiers(state, obj):
        if isinstance(mod.payload, CantBeBlocked):
            return True
    return False


def effective_ward_cost(
    state: GameState, obj: GameObject
) -> tuple["ManaCost | None", str]:  # noqa: F821
    """Return ``(ward_cost, ward_cost_str)`` currently in effect on
    ``obj`` — the printed ward stacked with any ward riders granted by
    Auras/Equipment attached to it (Hardlight Containment's "Enchanted
    permanent has ward {1}").

    Multiple ward instances stack additively (CR 702.21d "Multiple
    instances of ward on the same object are each separate triggered
    abilities."). This implementation aggregates them into a single
    additional cost since the simplified ward model auto-pays the whole
    sum at cast time. Returns ``(None, "")`` when nothing has ward.
    """
    from mtg_bot.cards.base import ManaCost  # local: avoid cycle

    parts: list[tuple[ManaCost, str]] = []
    if obj.printing.ward_cost is not None:
        parts.append((obj.printing.ward_cost, obj.printing.ward_cost_str))
    for source in state.battlefield:
        if source.attached_to != obj.id:
            continue
        granted = source.printing.attached_grants_ward_cost
        if granted is None:
            continue
        parts.append((granted, source.printing.attached_grants_ward_str))
    if not parts:
        return None, ""
    if len(parts) == 1:
        return parts[0]
    # Sum components across all ward instances. ManaCost stores generic
    # as an int and per-color counts in a (color, n) tuple — combine both.
    generic = sum(c.generic for c, _ in parts)
    x_pips = sum(c.x_pips for c, _ in parts)
    color_totals: dict[str, int] = {}
    for c, _ in parts:
        for color, n in c.colored:
            color_totals[color] = color_totals.get(color, 0) + n
    colored = tuple(sorted(color_totals.items()))
    total = ManaCost(generic=generic, colored=colored, x_pips=x_pips)
    label = " + ".join(s for _, s in parts if s)
    return total, label


def _dynamic_base_pt(
    state: GameState, obj: GameObject
) -> tuple[int, int] | None:
    """Return (base_power, base_toughness) for dynamic-P/T creatures,
    or None if this creature has no dynamic formula and should use
    its printed P/T.
    """
    formula = obj.printing.dynamic_pt_formula
    if formula is None:
        return None
    if formula == "cosmogoyf":
        # Cards owned in exile (by the creature's controller).
        controller = state.player_by_id(obj.controller_id)
        n = len(controller.exile)
        return n, n + 1
    if formula == "harmonious_grovestrider":
        # P = T = number of lands the controller controls.
        n = sum(
            1 for o in state.battlefield
            if o.controller_id == obj.controller_id and o.printing.is_land
        )
        return n, n
    if formula == "emissary_escort":
        # "Gets +X/+0 where X is the greatest mana value among other
        # artifacts you control." We encode that as a dynamic base
        # derived from printed P/T plus X on power only.
        mvs = [
            o2.printing.mana_cost.total
            for o2 in state.battlefield
            if o2.controller_id == obj.controller_id
            and o2.printing.is_artifact
            and o2.id != obj.id
        ]
        x = max(mvs) if mvs else 0
        printed_p = obj.printing.power or 0
        printed_t = obj.printing.toughness or 0
        return printed_p + x, printed_t
    return None  # pragma: no cover - defensive fallback


def gain_life(state: "GameState", player_id: int, amount: int) -> int:
    """Add ``amount`` life to ``player_id`` and track it in
    life_gained_this_turn. Returns the amount actually gained (same as
    ``amount`` for non-negative values; zero for non-positive).

    Use this helper instead of mutating ``p.life`` directly whenever
    an effect "gains life" — keys like Ragost's "if you gained life
    this turn" rely on the tracker being kept up-to-date.
    """
    if amount <= 0:
        return 0
    p = state.player_by_id(player_id)
    p.life += amount
    p.life_gained_this_turn += amount
    return amount


_BASIC_LAND_TYPE_TO_COLOR: dict[str, str] = {
    "Plains": "W",
    "Island": "U",
    "Swamp": "B",
    "Mountain": "R",
    "Forest": "G",
}


def named_counter_count(obj: "GameObject", kind: str) -> int:
    """How many ``kind`` counters (a ``named_counters`` kind) are on
    ``obj``."""
    for k, n in obj.named_counters:
        if k == kind:
            return n
    return 0


def set_named_counters(obj: "GameObject", kind: str, count: int) -> None:
    """Set the number of ``kind`` counters on ``obj`` (0 removes the
    entry). Rebuilds the immutable tuple."""
    rest = tuple((k, n) for k, n in obj.named_counters if k != kind)
    obj.named_counters = rest + (((kind, count),) if count > 0 else ())


def effective_subtypes(
    state: "GameState", obj: "GameObject"
) -> tuple[str, ...]:
    """Return ``obj``'s subtypes after applying CR-613 layer 3 and
    layer 4 effects in order on top of the printed subtype list.

    Sources walked:

    - Static "artifacts you control are Foods" (Ragost). Adds "Food"
      to artifacts; not registry-driven (predates the refactor).
    - Layer 3 ``"replace_basic_land_type"`` registry entries
      (Magical Hack), in timestamp order — substitutes one basic
      land type for another in the subtype list.
    - Layer 4 entries, walked together in CR 613.4 timestamp order:
        - Real registry ``"add_subtype"`` entries (Lignify
          granting Treefolk).
        - Synthesized ``"set_basic_land_subtype"`` entries from
          permanents with ``nonbasic_lands_are_mountains=True``
          (Magus of the Moon / Blood Moon) — REPLACES all
          basic-land-type subtypes with "Mountain". Synthesized
          per call with ``timestamp == source.etb_timestamp``.
        - Synthesized ``"add_subtype"`` entries from permanents
          with ``grants_all_basic_land_types_to_lands_you_control
          =True`` (Dryad of the Ilysian Grove) — adds all five
          basic land types to lands you control. Synthesized
          per call with ``timestamp == source.etb_timestamp``.

    The Dryad-vs-Magus interaction is the famous case this models:
    older Magus + newer Dryad = Mountain replaced first, then five
    basics added on top, so all 5 colors. Older Dryad + newer
    Magus = five basics added first, then SET to Mountain, so just
    Mountain.

    Face-down permanents have no subtypes (CR 701.34) — short-circuit
    the layered walk.
    """
    if obj.face_down:
        return ()
    subtypes = list(obj.printing.subtypes)
    # "This land is the chosen type." (Multiversal Passage) — the
    # entry-time choice, applied as a characteristic of the permanent
    # before the layer-3/4 walk (so Blood Moon's later set-type still
    # overrides it).
    if (
        getattr(obj.printing, "is_chosen_basic_land_type", False)
        and obj.chosen_basic_land_type is not None
        and obj.zone == Zone.BATTLEFIELD
        and obj.chosen_basic_land_type not in subtypes
    ):
        subtypes.append(obj.chosen_basic_land_type)
    if obj.printing.is_artifact:
        for o in state.battlefield:
            if o.id == obj.id:
                continue
            if o.controller_id != obj.controller_id:
                continue
            # Ragost's "artifacts you control are Foods" is a layer-4
            # type-changing effect. Layer 4 runs before layer 6 (CR
            # 613.1), so a Lignified Ragost still contributes the
            # Food subtype add — strict layer order, no source-
            # suppression check here.
            if o.printing.grants_food_to_your_artifacts:
                if "Food" not in subtypes:
                    subtypes.append("Food")
                break
    layer3 = sorted(
        (
            ce for ce in state.continuous_effects
            if ce.layer == 3
            and ce.kind == "replace_basic_land_type"
            and ce.target_id == obj.id
        ),
        key=lambda ce: ce.timestamp,
    )
    for ce in layer3:
        if not ce.params or len(ce.params) != 2:
            continue
        old, new = ce.params
        subtypes = [new if s == old else s for s in subtypes]
    layer4: list[ContinuousEffect] = [
        ce for ce in state.continuous_effects
        if ce.layer == 4
        and ce.kind in ("add_subtype", "set_basic_land_subtype")
        and ce.target_id == obj.id
    ]
    # Synthesize Magus-of-the-Moon / Blood Moon entries: nonbasic
    # lands get a layer-4 set_basic_land_subtype("Mountain") effect
    # sourced by each Magus permanent on the battlefield.
    #
    # Strict layer order (CR 613.1): layer 4 runs before layer 6, so
    # a Lignified / Humility'd Magus STILL contributes its layer-4
    # type-changing effect — layer 6 hasn't run yet to wipe its
    # ability. The famous Dryad + Humility ruling: lands keep the
    # basic land types Dryad granted, even after Humility removes
    # Dryad's ability, because layer 4 already applied.
    if obj.printing.is_land and not obj.printing.is_basic_land:
        for src in state.battlefield:
            if src.printing.nonbasic_lands_are_mountains:
                layer4.append(ContinuousEffect(
                    source_id=src.id, layer=4,
                    timestamp=src.etb_timestamp,
                    kind="set_basic_land_subtype",
                    target_id=obj.id,
                    params=("Mountain",),
                    description=(
                        f"{src.printing.name}: nonbasic lands are Mountains"
                    ),
                ))
    # Synthesize Dryad-of-the-Ilysian-Grove entries: any land its
    # controller controls gets layer-4 add_subtype effects for all
    # five basic land types, sourced by Dryad with its etb_timestamp.
    # Same strict-layer-order reasoning — a Lignified Dryad still
    # contributes (layer 4 < layer 6).
    if obj.printing.is_land:
        for src in state.battlefield:
            if (
                src.printing.grants_all_basic_land_types_to_lands_you_control
                and src.controller_id == obj.controller_id
            ):
                for basic in (
                    "Plains", "Island", "Swamp", "Mountain", "Forest"
                ):
                    layer4.append(ContinuousEffect(
                        source_id=src.id, layer=4,
                        timestamp=src.etb_timestamp,
                        kind="add_subtype",
                        target_id=obj.id,
                        params=(basic,),
                        description=(
                            f"{src.printing.name}: lands are {basic}"
                        ),
                    ))
    # Synthesize Urborg-Tomb-of-Yawgmoth / Yavimaya-Cradle-of-Growth
    # entries: any land on the battlefield gets a layer-4 add_subtype
    # entry for the named basic land type, sourced by the
    # ``grants_basic_land_type_to_all_lands`` permanent.
    #
    # CR 613.7 within-layer dependency: if the source is itself
    # subject to a layer-4 ``set_basic_land_subtype`` effect (Blood
    # Moon / Magus targeting it as a nonbasic land), CR 305.6 wipes
    # the source's ability and the contribution is suppressed.
    # This is the famous "Blood Moon beats Urborg" ruling — Blood
    # Moon ALWAYS wins regardless of timestamps because Urborg's
    # ability depends on Blood Moon's effect.
    if obj.printing.is_land:
        for src in state.battlefield:
            granted = src.printing.grants_basic_land_type_to_all_lands
            if granted is None:
                continue
            if _has_basic_land_type_set_effect(state, src):
                continue  # CR 613.7 dependency suppresses
            layer4.append(ContinuousEffect(
                source_id=src.id, layer=4,
                timestamp=src.etb_timestamp,
                kind="add_subtype",
                target_id=obj.id,
                params=(granted,),
                description=(
                    f"{src.printing.name}: each land is a {granted}"
                ),
            ))
    layer4.sort(key=lambda ce: ce.timestamp)
    for ce in layer4:
        if ce.kind == "set_basic_land_subtype":
            new_sub = ce.params[0] if ce.params else None
            if new_sub is None:
                continue
            # Drop existing basic-land-type subtypes and add the new
            # one (preserves non-basic-land subtypes unchanged).
            subtypes = [
                s for s in subtypes
                if s not in _BASIC_LAND_TYPE_TO_COLOR
            ]
            if new_sub not in subtypes:
                subtypes.append(new_sub)
        elif ce.kind == "add_subtype":
            sub = ce.params[0] if ce.params else None
            if sub and sub not in subtypes:
                subtypes.append(sub)
    return tuple(subtypes)


def effective_colors(
    state: "GameState", obj: "GameObject"
) -> frozenset[str]:
    """Return ``obj``'s effective colors as a frozenset of color
    letters (W/U/B/R/G), applying CR 613 layer 5 (color-changing
    effects). Base colors come from ``printing.mana_cost.colors``.

    Layer-5 entries are walked in timestamp order:
      - ``kind="set_colors"`` REPLACES the color set with
        ``params[0]`` (frozenset). Matches Scuttlemutt's "Target
        creature becomes the color or colors of your choice UEOT".
      - ``kind="add_colors"`` UNIONS ``params[0]`` into the current
        color set. Matches Painter's Servant-style "is the chosen
        color in addition to its other colors" clauses.
    """
    # Devoid (CR 702.114a): the object is colorless regardless of cost.
    base_cost_colors = (
        () if "devoid" in obj.printing.keywords
        else obj.printing.mana_cost.colors
    )
    colors: set[str] = set(base_cost_colors) | set(
        obj.printing.color_indicator
    )
    # Real registry layer-5 entries on this object.
    layer5: list[ContinuousEffect] = [
        ce for ce in state.continuous_effects
        if ce.layer == 5 and ce.target_id == obj.id
    ]
    # Synthesize Painter's-Servant-style ``add_colors`` entries from
    # any source on the battlefield with the painter flag and a
    # captured chosen color. Source's ``etb_timestamp`` is the
    # entry timestamp so it interleaves with Scuttlemutt-style
    # ``set_colors`` per CR 613 layer-5 timestamp rules.
    for src in state.battlefield:
        if (
            src.printing.paints_all_objects_chosen_color_at_etb
            and src.painter_chosen_color
        ):
            layer5.append(ContinuousEffect(
                source_id=src.id,
                layer=5,
                timestamp=src.etb_timestamp,
                kind="add_colors",
                target_id=obj.id,
                params=(frozenset({src.painter_chosen_color}),),
                description=(
                    f"{src.printing.name} paints "
                    f"{src.painter_chosen_color}"
                ),
            ))
    layer5.sort(key=lambda ce: ce.timestamp)
    for ce in layer5:
        if not ce.params:
            continue
        added = ce.params[0]
        if not isinstance(added, (frozenset, set)):
            continue
        if ce.kind == "set_colors":
            colors = set(added)
        elif ce.kind == "add_colors":
            colors |= set(added)
    return frozenset(colors)


def effective_protection_from_colors(
    state: "GameState", obj: "GameObject"
) -> frozenset[str]:
    """Return the colors ``obj`` has protection from.

    Sources:
    - Printing's ``protection_from_color`` field (single color).
    - Layer-3 ``"replace_color_word"`` registry entries on this
      object (Sleight of Mind, Mind Bend) — substitute one color
      letter for another, in timestamp order so the most-recent
      rewrite wins for chained substitutions.

    Returned as a frozenset for clean set-intersection in
    ``can_block`` and for future extension to multi-color
    protection.
    """
    pc = obj.printing.protection_from_color
    if not pc:
        return frozenset()
    layer3 = sorted(
        (
            ce for ce in state.continuous_effects
            if ce.layer == 3
            and ce.kind == "replace_color_word"
            and ce.target_id == obj.id
        ),
        key=lambda ce: ce.timestamp,
    )
    current = pc
    for ce in layer3:
        if not ce.params or len(ce.params) != 2:
            continue
        old, new = ce.params
        if current == old:
            current = new
    return frozenset({current})


def magus_of_the_moon_active(state: "GameState") -> bool:
    """True when any permanent on the battlefield has the
    ``nonbasic_lands_are_mountains`` flag. Thin wrapper kept for
    backward compatibility with code that wants a quick "is any
    Magus / Blood Moon source on the battlefield" check.

    Strict layer order (CR 613.1) puts layer 4 before layer 6, so
    a Lignified / Humility'd Magus STILL applies its layer-4
    nonbasic-lands-are-Mountains effect — its abilities haven't
    been wiped yet at layer 4 walking time. No source-suppression.
    """
    return any(
        o.printing.nonbasic_lands_are_mountains for o in state.battlefield
    )


def revert_printing_if_no_layer1_copies(
    state: "GameState", obj: "GameObject"
) -> None:
    """Restore ``obj.printing`` from ``obj.original_printing`` when
    no layer-1 ``"is_copy"`` registry entries remain on it.

    Used by:
    - ``run_cleanup_step``: after ``expire_continuous_effects(
      "cleanup")`` drops UEOT layer-1 entries (Cytoshape, Mirage
      Mirror), revert printing on creatures still on the
      battlefield.
    - ``move_off_battlefield``: when a permanent leaves play, its
      layered effects stop applying. The leaving object's printing
      reverts to its printed self before the zone change so a
      future reanimation enters as the printed object (CR
      400.7-style "becomes a new object on zone change").

    No-op if ``original_printing`` is unset (the object was never
    a copy) or if at least one layer-1 ``is_copy`` entry on
    ``obj`` is still active (a longer-lived copy effect like
    Clone's persistent ``expires_at=None`` entry).
    """
    if obj.original_printing is None:
        return
    has_layer1 = any(
        ce.layer == 1
        and ce.kind == "is_copy"
        and ce.target_id == obj.id
        for ce in state.continuous_effects
    )
    if has_layer1:
        return
    obj.printing = obj.original_printing
    obj.original_printing = None


def _has_basic_land_type_set_effect(
    state: "GameState", obj: "GameObject"
) -> bool:
    """True if any layer-4 ``"set_basic_land_subtype"`` effect
    (real registry entry or synthesized from a Magus-of-the-Moon /
    Blood Moon flag source) targets ``obj``. Per CR 305.6, when a
    land's basic land type is set by an effect, it loses abilities
    derived from its rules text and its previous land types — the
    suppression is part of layer-4 type-changing semantics, not a
    separate layer-6 ability wipe.

    Used by ``effective_activated_abilities`` to gate nonbasic
    lands' activated abilities under Magus / Blood Moon. Routes
    through the same registry/synthesis path as
    ``effective_subtypes`` so the two stay consistent.
    """
    # Real registry entries (no card writes these directly today,
    # but the path is open for future cards).
    for ce in state.continuous_effects:
        if (
            ce.layer == 4
            and ce.kind == "set_basic_land_subtype"
            and ce.target_id == obj.id
        ):
            return True
    # Synthesized Magus / Blood Moon entries: per the
    # ``effective_subtypes`` synthesis, these target nonbasic lands.
    if obj.printing.is_land and not obj.printing.is_basic_land:
        for src in state.battlefield:
            if src.printing.nonbasic_lands_are_mountains:
                return True
    return False


def effective_land_produces(
    state: "GameState", land_obj: "GameObject"
) -> frozenset[str]:
    """Return the effective colors a land taps for.

    Computed from ``effective_subtypes`` whenever any layer-3 or
    layer-4 effect is changing the land's basic-land-type subtypes
    — Magical Hack rewrites, Magus of the Moon ("nonbasic lands
    are Mountains"), and Dryad of the Ilysian Grove ("lands are
    every basic land type") all flow through that path. The
    produced color is derived from the resulting basic-land-type
    subtype set via ``_BASIC_LAND_TYPE_TO_COLOR``.

    Falls back to printed ``produces`` for lands whose effective
    subtypes contain no basic land type (e.g., colorless utility
    lands like Strip Mine without any layer-4 effect on them).
    """
    eff_subtypes = effective_subtypes(state, land_obj)
    produced = {
        _BASIC_LAND_TYPE_TO_COLOR[s]
        for s in eff_subtypes
        if s in _BASIC_LAND_TYPE_TO_COLOR
    }
    if produced:
        return frozenset(produced)
    return land_obj.printing.produces


def effective_activated_abilities(
    state: "GameState", obj: "GameObject"
) -> tuple:
    """Return ``obj``'s activated abilities plus any granted.

    Current grants:
    - Ragost: artifacts you control gain {2}, {T}, Sac: gain 3 life.
    - Mm'menon, the Right Hand: artifacts you control gain {T}: Add {U}
      with the "cast_from_outside_hand" spend restriction.
    - The Dominion Bracelet: the equipped creature gains the
      control-opponent-next-turn activated ability.

    Magus of the Moon: nonbasic lands lose their activated abilities
    entirely (their {T}: Add {R} tap is handled via
    ``effective_land_produces``, not as an activated ability).

    Lignify-style "lose all abilities" (layer 6) is processed in
    CR-613 timestamp order alongside ``grant_activated_ability``
    entries: an older lose-all-abilities followed by a newer grant
    re-adds the granted ability; a newer lose-all-abilities wipes
    everything that came before within layer 6.
    """
    from mtg_bot.cards import (
        DOMINION_BRACELET_GRANTED_ABILITY,
        MMNEMON_BLUE_MANA_GRANTED_ABILITY,
        RAGOST_FOOD_GRANTED_ABILITY,
    )

    # CR 305.6: a land whose basic land type has been SET by a
    # layer-4 effect (Magus / Blood Moon set_basic_land_subtype)
    # loses its abilities derived from rules text and old land
    # types. Routes through the same registry/synthesis path as
    # ``effective_subtypes`` so the two stay consistent.
    if (
        obj.printing.is_land
        and _has_basic_land_type_set_effect(state, obj)
    ):
        return ()

    # DSK Rooms: filter out activated abilities whose ``room_half``
    # is not in ``obj.unlocked_halves`` — those halves are locked,
    # so their abilities are inert. Non-Room abilities (room_half ==
    # None) are never filtered.
    if obj.printing.is_room:
        base = [
            a for a in obj.printing.activated_abilities
            if getattr(a, "room_half", None) is None
            or a.room_half in obj.unlocked_halves
        ]
    else:
        base = list(obj.printing.activated_abilities)
    if obj.printing.is_artifact:
        seen_ragost = False
        seen_mmnemon = False
        for o in state.battlefield:
            if o.id == obj.id:
                continue
            if o.controller_id != obj.controller_id:
                continue
            # Static-driven artifact-ability grants from sources like
            # Ragost / Mm'menon are layer-6 effects; per CR 613.7
            # within-layer dependency, they apply even when their
            # source has been Humility'd / Lignified — the wipe
            # targets the source, not the recipients of the grant.
            if (
                not seen_ragost
                and o.printing.grants_food_ability_to_your_artifacts
            ):
                base.append(RAGOST_FOOD_GRANTED_ABILITY)
                seen_ragost = True
            if (
                not seen_mmnemon
                and o.printing.grants_blue_mana_ability_to_your_artifacts
            ):
                base.append(MMNEMON_BLUE_MANA_GRANTED_ABILITY)
                seen_mmnemon = True
            if seen_ragost and seen_mmnemon:
                break
    # Equipment-granted abilities: walk attached equipment. The
    # equipment-keyword grant is layer 6 just like the static
    # anthem grants above — it survives a Lignify on the equipment
    # itself by the same dependency logic.
    for o in state.battlefield:
        if o.attached_to != obj.id:
            continue
        if o.printing.grants_control_opponent_ability_when_equipped:
            base.append(DOMINION_BRACELET_GRANTED_ABILITY)
    # Walk layer-6 entries in timestamp order, applying
    # lose_all_abilities (clears) and grant_activated_ability (adds).
    # UEOT-granted activated abilities (manland animations) live here
    # via ApplyEffect(GrantActivatedAbility(...), EndOfTurn()).
    layer6 = sorted(
        (
            ce for ce in state.continuous_effects
            if ce.layer == 6 and ce.target_id == obj.id
        ),
        key=lambda ce: ce.timestamp,
    )
    for ce in layer6:
        if ce.kind == "lose_all_abilities":
            base.clear()
        elif ce.kind == "grant_activated_ability" and ce.params:
            base.append(ce.params[0])
    # Filter out tier-gated activated abilities (Spacecraft charge-counter
    # gate, e.g. The Eternity Elevator's ``20+ | {T}: Add X mana``).
    # An ability with ``tier_threshold=0`` is always usable (default).
    base = [
        a for a in base
        if not getattr(a, "tier_threshold", 0)
        or obj.charge_counters >= a.tier_threshold
    ]
    return tuple(base)


def effective_triggered_abilities(
    state: "GameState", obj: "GameObject",
) -> tuple:
    """Return the printing's triggered abilities + any UEOT-granted
    triggered abilities from layer-6 registry entries.

    Callers that previously iterated ``obj.temp_triggered_abilities``
    directly should go through this helper so registry-granted
    triggers (Requiem Monolith's UEOT trigger, Raging Ravine's
    animated attack trigger, Perigee Beckoner's granted dies-rider)
    are picked up.

    Lignify-style "lose all abilities" (layer 6) is processed in
    CR-613 timestamp order alongside grant_triggered_ability
    entries: an older lose-all-abilities followed by a newer grant
    re-adds the granted trigger; a newer lose-all-abilities wipes
    everything that came before within layer 6.
    """
    # DSK Rooms: filter out triggered abilities whose ``room_half``
    # is not in ``obj.unlocked_halves`` — those halves are locked,
    # so their abilities are inert. Non-Room abilities (room_half ==
    # None) are never filtered.
    if obj.printing.is_room:
        base = [
            a for a in obj.printing.triggered_abilities
            if getattr(a, "room_half", None) is None
            or a.room_half in obj.unlocked_halves
        ]
    else:
        base = list(obj.printing.triggered_abilities)
    layer6 = sorted(
        (
            ce for ce in state.continuous_effects
            if ce.layer == 6 and ce.target_id == obj.id
        ),
        key=lambda ce: ce.timestamp,
    )
    for ce in layer6:
        if ce.kind == "lose_all_abilities":
            base.clear()
        elif ce.kind == "grant_triggered_ability" and ce.params:
            base.append(ce.params[0])
    return tuple(base)


def effective_draw_count(
    state: "GameState", player_id: int, base_count: int
) -> int:
    """Effective number of cards a "draw N" event should draw for
    ``player_id``, accounting for active CR 614 replacement effects.

    Routes through :func:`mtg_bot.effects.modifiers
    .dispatch_replacement` on ``WOULD_DRAW_CARDS``. The legacy
    Quantum-Riddler-shape flag (``replaces_draw_with_extra_when_hand
    _at_most_one``) synthesises an ``AddToCount(1)`` replacement
    gated on the drawing player's hand size ≤ 1; future replacement
    effects (Quantum-Riddler-style or otherwise) layer on by adding
    a ``ReplacementEffect`` to the printing without touching this
    site.
    """
    if base_count < 1:
        return base_count
    from mtg_bot.effects.modifiers import dispatch_replacement
    from mtg_bot.effects.predicates import Event

    p = state.player_by_id(player_id)
    out = dispatch_replacement(
        state, Event.WOULD_DRAW_CARDS,
        affected_player_id=player_id,
        subjects={"player": p},
        payload={"count": base_count},
    )
    if out.get("prevented"):
        return 0
    return out.get("count", base_count)


def etb_trigger_multiplier(state: "GameState", controller_id: int) -> int:
    """Return how many times an ETB-caused triggered ability on a
    permanent controlled by ``controller_id`` should fire.

    Routes through :func:`mtg_bot.effects.modifiers
    .dispatch_replacement` on ``TRIGGERED_ABILITY_TRIGGERS`` with a
    base ``instances=1`` payload. Starfield-Vocalist-shape doublers
    ride a SELF-scope StaticAbility with
    ``ReplacementEffect(AddInstances(1))``; the dispatcher's implicit
    "source.controller_id == affected_player_id" gate keys them on
    the carrier's controller. The post-replacement ``instances`` count
    drives the per-trigger fire loop.
    """
    from mtg_bot.effects.modifiers import dispatch_replacement
    from mtg_bot.effects.predicates import Event

    # The "ability_source" subject is what gates the replacement.
    # Our caller doesn't know the source object yet (this helper
    # answers a per-controller question), so we synthesise a
    # placeholder: a sentinel object whose controller_id matches
    # the question. The synthesizer reads ``ability_source
    # .controller_id`` off it. This keeps the Starfield-Vocalist
    # match shape consistent with how a real source-aware caller
    # would pass the ETB-target permanent.
    class _SourceSentinel:
        def __init__(self, controller_id):
            self.controller_id = controller_id
    sentinel = _SourceSentinel(controller_id)
    out = dispatch_replacement(
        state, Event.TRIGGERED_ABILITY_TRIGGERS,
        affected_player_id=controller_id,
        subjects={"ability_source": sentinel, "triggering_obj": sentinel},
        payload={"instances": 1},
    )
    return out.get("instances", 1)


def _counter_doubling_factor(state: GameState, obj: GameObject) -> int:
    """Return the post-replacement factor for +1/+1 counters being
    placed on ``obj``.

    Routes through :func:`mtg_bot.effects.modifiers
    .dispatch_replacement` on ``WOULD_PLACE_COUNTER`` with a base
    ``count=1`` payload; the post-replacement count IS the factor.
    Loading-Zone-shape doublers ride a SELF-scope StaticAbility with
    a ``ReplacementEffect(MultiplyCount(2))`` on
    ``WOULD_PLACE_COUNTER``. The dispatcher's implicit
    "source.controller_id == affected_player_id" gate fires the
    doubler when the recipient's controller matches the doubler's
    controller. Recipients that aren't creatures or Spacecraft
    (Loading Zone's printed scope) short-circuit to 1 — the dispatch
    is skipped entirely so future replacements with broader scopes
    don't accidentally fire.
    """
    if not (obj.printing.is_creature or obj.printing.is_spacecraft):
        return 1
    from mtg_bot.effects.modifiers import dispatch_replacement
    from mtg_bot.effects.predicates import Event

    out = dispatch_replacement(
        state, Event.WOULD_PLACE_COUNTER,
        affected_player_id=obj.controller_id,
        subjects={"obj": obj, "kind": "+1/+1"},
        payload={"count": 1},
    )
    return out.get("count", 1)


def add_plus_one_counters(
    state: GameState, obj: GameObject, amount: int
) -> int:
    """Add ``amount`` +1/+1 counters to ``obj``, applying Loading Zone-
    style doubling replacement effects for each active doubler
    controlled by the recipient. Only applies to creatures and
    Spacecraft (the Planet type isn't modeled yet) — matches the real
    Loading Zone scope.

    Fires "whenever you put one or more +1/+1 counters on a creature
    you control" observer triggers (Terrasymbiosis) for counters added
    to creatures.

    Returns the effective count actually added (after doubling). Safe
    when amount <= 0 (no-op).
    """
    if amount <= 0:
        return 0
    effective = amount * _counter_doubling_factor(state, obj)
    obj.plus_one_counters += effective
    if obj.printing.is_creature and effective > 0:
        from mtg_bot.turn import fire_counters_added_to_your_creature_triggers
        fire_counters_added_to_your_creature_triggers(
            state, obj.controller_id, effective, obj=obj,
        )
    return effective


def add_minus_one_counters(
    state: GameState, obj: GameObject, amount: int
) -> int:
    """Add ``amount`` -1/-1 counters to ``obj``. Counters reduce
    effective P/T by 1 per counter (layer 7d). +1/+1 and -1/-1
    counters cancel pairwise via the CR 704.5n state-based
    action — the cancellation runs in ``state_based_actions``,
    not here.

    No doubling applied (no in-pool doublers target -1/-1
    counters). Safe when amount <= 0.
    """
    if amount <= 0:
        return 0
    obj.minus_one_counters += amount
    return amount


def add_charge_counters(
    state: GameState, obj: GameObject, amount: int
) -> int:
    """Add ``amount`` charge counters to ``obj``. Charge counters are
    Spacecraft-only in the EoE engine, so doubling via Loading Zone
    applies (Spacecraft is in scope). Returns the effective count
    actually added.
    """
    if amount <= 0:
        return 0
    effective = amount * _counter_doubling_factor(state, obj)
    obj.charge_counters += effective
    return effective


def add_stun_counters(
    state: GameState, obj: GameObject, amount: int
) -> int:
    """Add ``amount`` stun counters to ``obj``, applying Loading Zone
    doubling when ``obj`` is in scope (creature/Spacecraft). Returns
    the effective count actually added.
    """
    if amount <= 0:
        return 0
    effective = amount * _counter_doubling_factor(state, obj)
    obj.stun_counters += effective
    return effective


def _registry_set_base_pt(
    state: "GameState", obj: "GameObject"
) -> "tuple[int, int] | None":
    """Highest-timestamp layer-7 sublayer-1 ``"set_base_pt"`` entry
    targeting ``obj``, or None if no such entry exists.

    Walks both real registry entries (Lignify, manland animation,
    Atomic Microsizer) AND synthesized entries from Humility-style
    sources on the battlefield (any permanent with the
    ``sets_all_creature_pt_to_1_1`` flag synthesizes a 1/1 set on
    every creature with the source's ``etb_timestamp``). The most-
    recent timestamp wins (CR 613 within-sublayer rule).
    """
    matches: list[ContinuousEffect] = [
        ce for ce in state.continuous_effects
        if ce.layer == 7
        and ce.sublayer == 1
        and ce.kind == "set_base_pt"
        and ce.target_id == obj.id
    ]
    # Synthesize Humility-style global 1/1 set for creatures.
    if is_creature_now(obj):
        for source in state.battlefield:
            if source.printing.sets_all_creature_pt_to_1_1:
                matches.append(ContinuousEffect(
                    source_id=source.id,
                    layer=7, sublayer=1, kind="set_base_pt",
                    target_id=obj.id,
                    params=(1, 1),
                    description=(
                        f"{source.printing.name}: creatures are 1/1"
                    ),
                    timestamp=source.etb_timestamp,
                ))
    if not matches:
        return None
    matches.sort(key=lambda ce: ce.timestamp)
    return matches[-1].params  # (power, toughness)


def _compute_effective_pt(
    state: GameState, obj: GameObject
) -> tuple[int, int]:
    """Compute (effective_power, effective_toughness) walking layer 7
    sublayers in CR-613 order:

      - 7b (sublayer 1): set base P/T — most-recent registry
        ``"set_base_pt"`` wins; falls back to dynamic P/T formula,
        then printed.
      - 7c (sublayer 2): modify P/T — anthem static bonuses, UEOT
        pump bonuses (legacy ``temp_*`` field cache), and
        "until your next turn" pump bonuses (registry walk over
        ``pump_pt`` entries with ``expires_at="controller_untap"``).
      - 7d (sublayer 3): counters — +1/+1 counters add equally.
      - 7e (sublayer 4): switch P/T — each layer-7 sublayer-4
        ``"switch_pt"`` registry entry contributes one swap, walked
        in timestamp order (so two swaps cancel; three swaps =
        one swap).

    Single function returning both so the sublayer walk happens
    once per query — saves the duplicate work of the prior
    ``effective_power`` / ``effective_toughness`` split.

    A face-down permanent (CR 701.34) is a 2/2 vanilla creature.
    +1/+1 / -1/-1 counters still modify the printed-2/2 base, so
    we apply layer 7d on top; layers 7b (set base) and 7c (anthem
    pumps from this source's ignored static abilities) don't apply
    because face-down objects have no abilities and no name to
    anchor static effects that target by name.
    """
    if obj.face_down:
        # 2/2 base + counters (layer 7d). Switch entries (7e) still
        # affect a face-down permanent — a swap is a creature-state
        # mutation, not an ability. Anthems applying to "creatures
        # you control" still pump face-down creatures (they're
        # creatures), so we still walk static bonuses, but the
        # face-down object's OWN granted_keywords contributions are
        # already filtered out via ``effective_keywords`` /
        # ``_static_bonuses`` reading the printing's static_abilities
        # — those abilities are wiped by face-down (CR 707.2). So
        # we apply only counters here and skip anthems too: anthem
        # contributions from OTHER sources are correctly handled by
        # ``_static_bonuses`` walking the battlefield, but applying
        # them here would mismatch the "no abilities" reading. Keep
        # this simple: face-down = 2/2 plus +1/+1 counters, with
        # external anthems and switches optionally folded.
        base_p, base_t = 2, 2
        # External anthems still buff a face-down creature (it IS a
        # creature, and the anthem applies to "creatures you
        # control"). The face-down source's own static abilities
        # are already gated by being-face-down everywhere they
        # matter, so this is the sole non-counter contributor here.
        power_bonus, toughness_bonus, _ = _static_bonuses(state, obj)
        p = base_p + power_bonus
        t = base_t + toughness_bonus
        p += obj.plus_one_counters - obj.minus_one_counters
        t += obj.plus_one_counters - obj.minus_one_counters
        # Layer 7e switches. Each entry contributes a single swap, so
        # only the COUNT matters (the old ``sorted(...)`` by timestamp
        # was ordering a sequence whose order it then discarded).
        # Counted with an explicit loop — see the "closure-free hot
        # path" note on ``_static_bonuses``.
        n_switch = 0
        for ce in state.continuous_effects:
            if (
                ce.layer == 7 and ce.sublayer == 4
                and ce.kind == "switch_pt"
                and ce.target_id == obj.id
            ):
                n_switch += 1
        if n_switch % 2:
            p, t = t, p
        return p, t
    # 7b: base P/T.
    layer7b = _registry_set_base_pt(state, obj)
    if layer7b is not None:
        base_p, base_t = layer7b
    else:
        dynamic = _dynamic_base_pt(state, obj)
        if dynamic is not None:
            base_p, base_t = dynamic
        else:
            base_p = obj.printing.power or 0
            base_t = obj.printing.toughness or 0
    # 7c: modify P/T (anthems, pumps).
    power_bonus, toughness_bonus, _ = _static_bonuses(state, obj)
    # Layer-7c registry pumps: ``"pump_pt"`` entries with
    # ``expires_at="controller_untap"`` carry the "until your next
    # turn" P/T deltas (Mouth of the Storm). UEOT pump entries
    # (``expires_at="cleanup"``) still flow through the
    # ``temp_power_bonus`` / ``temp_toughness_bonus`` field-mirror
    # path; that migration is a separate sweep tracked by the audit.
    extended_pump_p = 0
    extended_pump_t = 0
    for ce in state.continuous_effects:
        if (
            ce.layer == 7
            and ce.sublayer == 2
            and ce.kind == "pump_pt"
            and ce.target_id == obj.id
            and ce.expires_at == "controller_untap"
        ):
            extended_pump_p += ce.params[0]
            extended_pump_t += ce.params[1]
    p = (
        base_p + power_bonus
        + obj.temp_power_bonus + extended_pump_p
    )
    t = (
        base_t + toughness_bonus
        + obj.temp_toughness_bonus + extended_pump_t
    )
    # 7d: counters. +1/+1 and -1/-1 are normally cancelled out by
    # the CR 704.5n SBA before this read, but if they coexist
    # transiently (between counter additions and the next SBA pass)
    # we still apply both signs.
    p += obj.plus_one_counters - obj.minus_one_counters
    t += obj.plus_one_counters - obj.minus_one_counters
    # 7e: switches. Each entry contributes a single swap, so an even
    # count cancels out and only the parity matters. Counted with an
    # explicit loop — see the "closure-free hot path" note on
    # ``_static_bonuses``.
    n_switch = 0
    for ce in state.continuous_effects:
        if (
            ce.layer == 7 and ce.sublayer == 4
            and ce.kind == "switch_pt"
            and ce.target_id == obj.id
        ):
            n_switch += 1
    if n_switch % 2:
        p, t = t, p
    return p, t


def effective_power(state: GameState, obj: GameObject) -> int:
    """Power after walking layer 7 sublayers (see
    ``_compute_effective_pt`` for the full ordering)."""
    return _compute_effective_pt(state, obj)[0]


def effective_toughness(state: GameState, obj: GameObject) -> int:
    """Toughness after walking layer 7 sublayers (see
    ``_compute_effective_pt`` for the full ordering)."""
    return _compute_effective_pt(state, obj)[1]


@dataclass(slots=True)
class StackItem:
    """A spell or triggered ability on the stack.

    When ``ability`` is None the stack item represents a spell being cast;
    resolving it moves ``source`` to the battlefield. When ``ability`` is set,
    the item represents a triggered ability; resolving it runs the effect.

    ``targets`` holds (kind, id) pairs chosen when the ability went on the
    stack — empty for spells and for untargeted abilities.
    """

    source: GameObject
    controller_id: int
    # Either a TriggeredAbility or an ActivatedAbility — both have an
    # ``.effect`` attribute and resolve the same way.
    ability: "object | None" = None
    targets: tuple[tuple[str, int], ...] = ()
    # True when the spell was countered at cast time (currently by unpaid
    # Ward). A countered spell resolves as a no-op, with the card going
    # to its owner's graveyard (for instants/sorceries) or vanishing
    # (for permanents) without firing any effects/ETBs.
    countered: bool = False
    # The value chosen for {X} in this spell's cost (0 for non-X spells).
    # Set by _cast_spell via agent.choose_x; exposed to the resolving
    # effect via state.resolving_x_value.
    x_value: int = 0
    # True when the spell was cast with its kicker cost paid. Exposed
    # to the resolving effect via state.resolving_kicked.
    kicked: bool = False
    # Id of the creature the caster designated as a
    # choose-your-creature additional cost. None for spells that
    # don't have such a cost. Mirrored to
    # state.resolving_additional_cost_choice_id during resolution.
    additional_cost_choice_id: Optional[int] = None
    # Combat damage amount carried by a combat-damage-triggered ability
    # while it sits on the stack. Mirrored to
    # state.resolving_combat_damage_amount during resolution so effects
    # like DrawCardsEqualToResolvingCombatDamage can read "that many"
    # even though the ability resolves after the damage step ends.
    # 0 for non-combat-damage triggers and for spells.
    combat_damage_amount: int = 0
    # Controller id of the creature dealing combat damage in a
    # combat-damage-triggered ability while it sits on the stack.
    # Mirrored to state.resolving_combat_damage_source_controller_id
    # during resolution so observer effects like Contested War Zone's
    # ChangeControllerToCombatDamageSource can read the attacker's
    # controller without having to thread it through the targets tuple.
    # None for non-combat-damage triggers.
    combat_damage_source_controller_id: Optional[int] = None
    # Counter amount carried by a counters-added-to-creature observer
    # trigger. Mirrored to state.resolving_counter_amount during
    # resolution so effects like Terrasymbiosis ("draw that many cards")
    # can read the count even though the ability resolves later.
    counter_amount: int = 0
    # Modal-spell mode picks chosen at cast time (CR 601.2e: modes
    # are picked BEFORE total cost is determined at 601.2f). For a
    # plain "Choose one" this is a 1-tuple; for "Choose one or both"
    # it's a 1- or 2-tuple in resolution order. Empty for non-modal
    # spells. Mirrored to state.resolving_modes during resolution so
    # ModalChooseOne.resolve can read the pre-picked choice instead
    # of prompting the agent again at resolve time.
    chosen_modes: tuple[int, ...] = ()
    # DSK Rooms: when a Room spell is cast, the half-name the
    # controller chose to cast for. Resolved into
    # ``GameObject.unlocked_halves`` when the Room enters the
    # battlefield. ``None`` for non-Room spells.
    cast_room_half: "str | None" = None
    # GameObjects paid as part of this ability/spell's activation cost
    # (sacrificed permanents, exiled-from-graveyard cards, etc.). For
    # an activated ability whose cost includes ``Sacrifice another
    # artifact``, this tuple holds one element: the artifact that was
    # sacrificed (as it now sits in its owner's graveyard, since
    # cost-payment moves it off the battlefield before the stack item
    # is built). Mirrored to ``state.resolving_cost_paid_objects``
    # during resolution so effects and formulas (e.g.
    # ``MVOfCostPaidObjectPlus``) can read per-object properties of
    # the paid objects without zone-walking heuristics. Empty for
    # activations with no discrete-object cost atom (pure mana / tap)
    # and for spells.
    cost_paid_objects: tuple["GameObject", ...] = ()
    # Buyback (CR 702.27) was paid: the spell returns to its owner's
    # hand as it resolves instead of going to the graveyard.
    buyback_paid: bool = False
    # Divided damage (CR 601.2d): the per-target split announced while
    # casting, aligned with ``targets``.
    division: tuple[int, ...] = ()
    # Splice (CR 702.47): ``(printing, targets)`` for each card spliced
    # onto this spell; their effects resolve after the spell's own.
    spliced: tuple = ()


# Fast shallow cloner. ``source`` and ``cost_paid_objects`` carry GameObject
# refs that the caller remaps via ``clone_obj``; everything else is an
# immutable scalar / tuple. No mutable lists.
_clone_stack_item = _make_shallow_cloner(StackItem)


@dataclass(slots=True)
class Player:
    id: int
    life: int = 20
    # Starting life total — used by effects that reference it directly
    # (e.g. "your life total becomes half your starting life total").
    # Defaults to 20 (MTG standard); adjust for alternate formats.
    starting_life: int = 20
    # Poison counters (MTG rule 704.5c). A player with 10+ poison
    # counters loses the game — enforced via state-based actions.
    poison_counters: int = 0
    library: list[GameObject] = field(default_factory=list)
    hand: list[GameObject] = field(default_factory=list)
    graveyard: list[GameObject] = field(default_factory=list)
    exile: list[GameObject] = field(default_factory=list)
    lands_played_this_turn: int = 0
    # Number of lands that have entered the battlefield under this player's
    # control during the current turn. Distinct from lands_played_this_turn
    # (which counts the per-turn land-drop action only): incremented for
    # *every* land ETB, including basics fetched by Lander tokens or other
    # search-and-put-onto-battlefield effects. Reset at cleanup. Used by
    # cards that read "for each land that entered the battlefield under your
    # control this turn" (Bioengineered Future).
    lands_entered_this_turn: int = 0
    # Number of spells this player has cast in the current turn. Reset at
    # cleanup. Used by "whenever you cast your Nth spell each turn" triggers.
    spells_cast_this_turn: int = 0
    # Spells this player has cast this game (Once Upon a Time's "If this
    # spell is the first spell you've cast this game").
    spells_cast_this_game: int = 0
    # Yawgmoth's Will: "Until end of turn, you may play lands and cast
    # spells from your graveyard." Cleared at cleanup.
    may_play_from_graveyard_this_turn: bool = False
    # Yawgmoth's Will: "If a card would be put into your graveyard from
    # anywhere this turn, exile that card instead." Active while True;
    # cleared at cleanup (see ``turn.apply_graveyard_exile_replacement``).
    graveyard_exile_replacement_this_turn: bool = False
    # Ids of cards already in the graveyard when that replacement began
    # (they stay; anything newer is exiled by the catch-all sweep).
    graveyard_exile_snapshot: frozenset = frozenset()
    # Number of noncreature spells this player has cast this turn. Reset
    # at cleanup. Used by the Deafening Silence restriction ("each player
    # can't cast more than one noncreature spell each turn") — legal_actions
    # gates additional noncreature casts when any permanent on the
    # battlefield has ``restricts_noncreature_spells_to_one_per_turn``.
    noncreature_spells_cast_this_turn: int = 0
    # The ``GameObject``s this player has declared as attackers this
    # turn (in declaration order). Populated by
    # ``combat.declare_attackers`` immediately after each attacker has
    # ``attacking=True`` set. Reset at the cleanup step in
    # ``turn.run_cleanup_step``. Drives the
    # ``AttackedWithThisTurn(filter)`` cost-reduction condition — the
    # condition filters this list at evaluation time, so any future
    # "you attacked with a [type] this turn" gate composes by swapping
    # the filter rather than adding a new latch.
    attacked_this_turn: list["GameObject"] = field(default_factory=list)
    # Number of artifacts that entered the battlefield under this
    # player's control this turn. Reset at cleanup. Incremented by
    # ``actions.put_into_battlefield`` whenever an artifact (including
    # artifact creatures and artifact tokens) enters under their
    # control. Read by ``ControlledArtifactEnteredThisTurn`` condition
    # which gates Mechan Shieldmate's defender-removing
    # ``ContinuousModifier`` via ``effective_keywords``.
    artifacts_entered_under_your_control_this_turn: int = 0
    # Number of cards this player has drawn this turn (every draw via
    # ``turn.draw_card``, draw step included). Reset at cleanup. Read
    # by the "each opponent can't draw more than one card each turn"
    # restriction (Narset, Parter of Veils).
    cards_drawn_this_turn: int = 0
    has_lost: bool = False
    lost_reason: str = ""
    agent: Optional["Agent"] = None
    # Mana pool: list of ManaCoin entries (color + optional spend
    # restriction). Populated by mana-ability activations; consumed
    # before lands when paying costs; emptied at cleanup step.
    mana_pool: list["ManaCoin"] = field(default_factory=list)
    # Total life gained this turn. Reset at cleanup. Consumed by
    # effects that key on "if you gained life this turn" (Ragost,
    # Deft Gastronaut's end-step untap). Incremented by gain_life().
    life_gained_this_turn: int = 0
    # Designations (``mtg_bot.designations``): the monarch (CR 724),
    # the initiative (CR 725) and the player's Undercity venture marker
    # (CR 309; ``None`` = not in a dungeon) + completed-dungeon count
    # ("if you've completed a dungeon").
    # Energy counters (CR 122.1, ``{E}``): gained by "you get {E}",
    # spent by "Pay {E}" costs.
    energy: int = 0
    is_monarch: bool = False
    has_initiative: bool = False
    dungeon_room: Optional[str] = None
    dungeons_completed: int = 0
    # Pending agent swap scheduled by The Dominion Bracelet's
    # "You control target opponent during their next turn". When set,
    # run_untap_step installs the override at the start of this
    # player's next turn (saving the original agent in
    # ``agent_override_saved`` so cleanup can revert).
    scheduled_agent_override: Optional["Agent"] = None
    scheduled_agent_override_by: Optional[int] = None
    agent_override_saved: Optional["Agent"] = None
    # How many turns this player has begun (incremented at the start of
    # each of their untap steps, extra turns included). Read by
    # ``YourTurnOfGameAtMost`` — Starting Town's "unless it's your
    # first, second, or third turn of the game".
    turns_started: int = 0


# Fast shallow cloner. The 6 mutable list/zone fields (library, hand,
# graveyard, exile, mana_pool, attacked_this_turn) are overwritten by
# ``GameState.clone`` immediately after this returns, so they're shared
# briefly by reference here — same semantics as the previous
# ``__dict__.copy()`` fast path.
_clone_player = _make_shallow_cloner(Player)


@dataclass(slots=True)
class ManaCoin:
    """A unit of mana in a player's pool.

    ``color`` is one of "W", "U", "B", "R", "G", "C" (colorless), or
    "any" (a wildcard produced by effects like All-Fates Scroll's
    "{T}: Add one mana of any color"). An "any" coin can satisfy any
    colored requirement; colorless coins only satisfy generic
    requirements.

    ``spend_restriction`` gates what the coin can pay for. None =
    unrestricted. Known values:
      - "artifact_spell" — Steelswarm Operator / Power Depot
        ("Spend this mana only to cast an artifact spell").
      - "artifact_activation" — Steelswarm Operator's second mana
        ability ("Spend this mana only to activate abilities of
        artifact sources").
      - "colorless_eldrazi" — Eldrazi Temple's second mana ability
        ("Spend this mana only to cast colorless Eldrazi spells or
        activate abilities of colorless Eldrazi").
      - "legendary_spell" — Plaza of Heroes's second mana ability
        ("Spend this mana only to cast a legendary spell").
      - "legendary_permanent_ability" — Plaza of Heroes's third mana
        ability ("Add one mana of any color among legendary
        permanents you control").
      - "land_activation" — Sunken Citadel's second mana ability
        ("Spend this mana only to activate abilities of land
        sources").
      - "cast_from_outside_hand" — Mm'menon, the Right Hand's
        artifact-grant mana ability ("Spend this mana only to cast a
        spell from anywhere other than your hand").
    See ``actions._coin_satisfies_context`` for how each tag matches
    a payment context.
    """

    color: str
    spend_restriction: Optional[str] = None
    # "If any of that mana is spent on a creature spell, it gains haste
    # until end of turn." (Arena of Glory) — ``_cast_spell`` grants the
    # creature spell haste UEOT when a coin with this flag pays for it.
    grants_haste_to_creature_spell: bool = False


_clone_mana_coin = _make_shallow_cloner(ManaCoin)


class LogBuffer(list[str]):
    """A list[str] with a global silent-mode switch.

    ``append(msg)`` early-returns when ``enabled`` is False. All other
    list operations behave exactly like a normal ``list``. The engine
    appends to ``state.log`` from hundreds of sites; turning this
    buffer off lets search/rollout code skip those string allocations
    without touching any call site.

    Reads still work — tests that inspect log contents continue to
    pass while the buffer is enabled (the default).
    """

    enabled: bool = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.enabled = True

    def append(self, msg: str) -> None:  # type: ignore[override]
        if not self.enabled:
            return
        list.append(self, msg)


@dataclass(frozen=True)
class ContinuousEffect:
    """A continuous effect record in the layered-effects registry.

    Models CR 613's "active continuous effects." Effects are stored
    as data (not closures) so the registry survives ``GameState.clone``
    and pickling for MCTS spawn. The layer-walker (Phase 2+)
    dispatches on ``kind`` to compute characteristics.

    Fields:

    - ``source_id``: the GameObject that produced this effect (the
      aura, the static-ability source, the spell that resolved it).
      When the source leaves play (or for one-shots that complete,
      when explicitly removed), the entry is dropped from the
      registry.
    - ``layer``: 1–7 per CR 613.1. 1=copy, 2=control, 3=text,
      4=type, 5=color, 6=ability, 6.5=ability-modifying-PT (aka
      part of layer 7 but historically grouped), 7=P/T.
    - ``sublayer``: 0 by default. For layer 7 the spec defines
      a–d (we use 0–3): 0 = base P/T set, 1 = base P/T modified
      by counters/effects, 2 = +N/+N modifications, 3 = switch
      P/T. Within the same (layer, sublayer), ties resolve by
      ``timestamp``.
    - ``timestamp``: monotonically increasing per ``GameState``;
      lower = older = applied first within a layer.
    - ``kind``: dispatch key, e.g. ``"control_change"``,
      ``"grant_keyword"``, ``"set_base_pt"``, ``"pump_pt"``,
      ``"add_subtype"``. Layer-2 control-change is the first kind
      that will get migrated in Phase 2.
    - ``target_filter``: predicate name describing which permanents
      this effect applies to. Empty means ``params`` carries an
      explicit ``target_id``. Examples:
      ``"self"`` (the source), ``"attached_to_source"`` (the
      permanent the source is attached to — auras),
      ``"creatures_you_control"``, ``"all_artifacts_you_control"``.
    - ``params``: tuple of kind-specific values. For
      ``"control_change"`` the tuple is ``(new_controller_id,)``.
      For ``"grant_keyword"`` it's ``(keyword_str,)``. Etc.
    - ``description``: human-readable summary for log lines and
      debugging.
    """

    source_id: int
    layer: int
    timestamp: int
    kind: str
    sublayer: int = 0
    target_filter: str = ""
    target_id: Optional[int] = None
    params: tuple = ()
    description: str = ""
    # Lifetime marker. None = entry persists until the source leaves
    # the battlefield (the default for static abilities — Tractor
    # Beam's control grant). Other values:
    #   - "cleanup": drop at the active player's cleanup step (UEOT
    #     pump-grants — Squire's Lightblade's first strike, manland
    #     animation, granted-triggers UEOT, etc.).
    #   - "controller_untap": drop at the source-controller's next
    #     untap step (extended-temporal pumps — Mouth of the Storm).
    #     ``expires_at_player_id`` carries the controller id whose
    #     untap step terminates the entry.
    expires_at: Optional[str] = None
    expires_at_player_id: Optional[int] = None


@dataclass(slots=True)
class GameState:
    players: list[Player] = field(default_factory=list)
    battlefield: list[GameObject] = field(default_factory=list)
    stack: list[StackItem] = field(default_factory=list)
    active_player_idx: int = 0
    priority_player_idx: int = 0
    turn_number: int = 1
    step: Optional["Step"] = None
    next_object_id: int = 0
    # Layered-effects registry (CR 613). Phase 1 introduces it as
    # additive scaffolding — the list is empty by default and no
    # current code consults it. Phase 2 will start migrating
    # field-mutation-based continuous effects (aura control swaps,
    # anthem statics, manland animation, granted abilities, etc.)
    # to live as ``ContinuousEffect`` records here, with
    # ``effective_*`` helpers walking the registry in layer +
    # timestamp order. ``next_timestamp`` is the monotonic counter
    # allocated by ``add_continuous_effect``; lower = older = applied
    # first within a layer.
    continuous_effects: list[ContinuousEffect] = field(default_factory=list)
    next_timestamp: int = 0
    log: LogBuffer = field(default_factory=LogBuffer)
    # Canonical game-wide RNG. Engine sites that need randomness (library
    # shuffles from Nexus, tutor shuffles, ward random-discard, etc.) pull
    # from ``state.rng`` so a run is reproducible from a single seed and
    # so search can fork a clone's RNG cleanly. ``simulate.setup_game``
    # seeds this from the caller-supplied seed.
    rng: random.Random = field(default_factory=random.Random)
    winner_id: Optional[int] = None
    is_draw: bool = False
    # EoE "Void" turn-state flags. Both are reset on cleanup (end of turn).
    # ``permanent_left_battlefield_this_turn`` is set whenever any nonland
    # permanent leaves the battlefield (destroy, exile, bounce, cease-to-
    # exist, warp-exile). ``spell_warped_this_turn`` is set when a spell
    # was cast via its warp alt-cost. The ``is_void_active`` helper returns
    # True when either flag is set, which is the Void trigger condition.
    permanent_left_battlefield_this_turn: bool = False
    spell_warped_this_turn: bool = False
    # Tracks (source_id, ability_index) pairs for triggered abilities that
    # have already fired this turn under the ``once_per_turn`` restriction.
    # Reset by run_cleanup_step.
    once_per_turn_fired: set[tuple[int, int]] = field(default_factory=set)
    # Tracks (controller_id, source_id) pairs for planeswalkers that have
    # had a loyalty ability activated this turn (CR 606.3 — "a player may
    # activate a loyalty ability of a planeswalker they control only if no
    # player has activated a loyalty ability of that planeswalker this
    # turn"). Per-walker, not per-ability: once ANY of a walker's loyalty
    # abilities fires, ALL of its activated abilities are gated off for the
    # rest of the turn. Mirrors Rust's ``loyalty_activated_this_turn``
    # HashSet (state.rs). Reset by run_cleanup_step.
    loyalty_activated_this_turn: set[tuple[int, int]] = field(
        default_factory=set
    )
    # Command zone (CR 408) — emblem objects (CR 114). Each entry is a
    # synthetic ``GameObject`` (``zone == Zone.COMMAND``) whose
    # ``printing`` is a synthetic ``CardPrinting`` carrying ONLY the
    # emblem's ability set (no characteristics other than its abilities,
    # CR 114.3) and whose ``controller_id`` / ``owner_id`` is the player
    # who "gets" the emblem. Emblems never leave the command zone and
    # can't be removed (CR 114.5), so there is no zone-transition
    # plumbing — they are created by the ``CreateEmblem`` effect, cloned
    # in ``clone()``, surfaced via ``emblems_snapshot``, and scanned as
    # an additional trigger SOURCE by ``dispatch_event`` for the
    # begin-combat (and any future emblem-sourced) event. Empty by
    # default — almost every state has no emblems, so the field
    # contributes to the parity fingerprint ONLY when non-empty
    # (``hash_state`` appends an emblems slot iff the list is non-empty),
    # keeping every pre-emblem pinned baseline byte-identical. Mirrors
    # Rust's ``GameState.emblems: Vec<Emblem>``.
    emblems: list[GameObject] = field(default_factory=list)
    # Delayed triggered abilities scheduled for a future end step. Each
    # entry is a dict: {"fire_at_turn": int, "controller_id": int,
    # "action": str, "target_id": int}.
    # Actions currently supported: "sacrifice".
    delayed_triggers: list[dict] = field(default_factory=list)
    # Source GameObject of the currently-resolving ability, if any. Set by
    # resolve_top_of_stack during ability resolution so effects like
    # "put a +1/+1 counter on this creature" can reach the source without
    # having to thread it through every resolve() signature.
    resolving_source: Optional[GameObject] = None
    # The instant / sorcery / Aura spell currently resolving (the card
    # object), or ``None``. Distinct from ``resolving_source`` (which
    # is only set for abilities, and which many effects read as "this
    # permanent"). Consumed by the protection damage-prevention check
    # (``keyword_rules.current_damage_source``) so a red burn spell's
    # damage to a creature with protection from red is prevented.
    resolving_spell: Optional[GameObject] = None
    # Controller id pinned for the current legal-targets enumeration.
    # Set transiently by ``Effect._enumerate_for_filter`` (and by
    # any peer call that consults a ``TargetFilter``) so controller-
    # aware atoms (``ControlledByOpponent`` / ``ControlledByYou``)
    # can compare an object's ``controller_id`` against the spell /
    # ability's controller without threading the id through every
    # ``ObjectPredicate.test`` signature. Cleared back to ``None``
    # after the enumeration unwinds.
    resolving_controller_id: Optional[int] = None
    # Value of {X} for the currently-resolving spell or ability. Mirrors
    # StackItem.x_value during resolution so effects can read X without
    # threading it through every resolve() signature. 0 when no X spell
    # is resolving.
    resolving_x_value: int = 0
    # Mirrors StackItem.kicked during resolution so effects can branch
    # on whether the spell was kicked without threading it through
    # every resolve() signature. False outside resolution.
    resolving_kicked: bool = False
    # Mirrors StackItem.chosen_modes during resolution so a modal
    # spell's resolve() reads the cast-time pick (CR 601.2e) rather
    # than prompting the agent again at resolve time. Empty tuple
    # outside modal-spell resolution.
    resolving_modes: tuple[int, ...] = ()
    # Mirrors StackItem.additional_cost_choice_id during resolution so
    # effects (e.g. Close Encounter) can read the creature the caster
    # designated as an additional cost. None outside resolution.
    resolving_additional_cost_choice_id: Optional[int] = None
    # Amount of combat damage dealt by the source that is currently
    # firing a combat-damage trigger. 0 outside combat-trigger
    # resolution. Used by effects like Starwinder's "may draw that
    # many cards" that need to know the damage amount.
    resolving_combat_damage_amount: int = 0
    # Controller id of the creature dealing combat damage in a
    # currently-firing combat-damage-to-you trigger. None outside such
    # resolution. Used by Contested War Zone's "that creature's
    # controller gains control of this land".
    resolving_combat_damage_source_controller_id: Optional[int] = None
    # Number of +1/+1 counters being added during a resolving
    # counters-added observer trigger (Terrasymbiosis: "draw that many
    # cards"). 0 outside such resolution.
    resolving_counter_amount: int = 0
    # GameObjects that were paid as part of the cost when the
    # currently-resolving activated ability was activated. Mirrors
    # ``StackItem.cost_paid_objects`` during resolution so effects /
    # formulas that reference "the sacrificed artifact" / "the
    # sacrificed creature" / "the discarded card" can read the paid
    # object(s) without scanning zones for a heuristic match. Empty
    # outside resolution and for activations whose cost paid no
    # discrete objects (pure mana / tap costs). Each entry is a
    # GameObject reference; for sacrificed permanents it points at the
    # object as it now sits in its owner's graveyard (move-off-
    # battlefield runs during cost payment, before the StackItem is
    # built). Used by ``MVOfCostPaidObjectPlus`` and any future formula
    # that reads a per-object property of a cost-paid object.
    resolving_cost_paid_objects: tuple[GameObject, ...] = ()
    # The instant / sorcery card currently resolving (None otherwise).
    # Read by effects that refer to "this spell" as an object, e.g.
    # Time Spiral's "Exile Time Spiral." (``ExileThisSpell``).
    resolving_spell: Optional[GameObject] = None
    # The resolving spell's announced damage division (``StackItem.division``).
    resolving_division: tuple[int, ...] = ()
    # Number of cards moved by the most recent
    # ``MoveEachExiledWithSourceToOwnersGraveyard`` resolve in the
    # current resolving ability. Lets a follow-up
    # ``CreateNTokensFromLastExileRecall`` (used by Pinnacle Starcage's
    # "create one Robot per moved card" sequence step) read the count
    # without coupling the two effects into one combined class. Set
    # by the recall effect at the start of every resolve (so a stale
    # value from a prior ability never leaks); reset to 0 by
    # ``resolve_top_of_stack`` after each ability resolves so it never
    # bleeds across ability boundaries.
    last_exile_recall_count: int = 0
    # When set to a source-object id, the engine's
    # ``_release_exiled_until_leaves`` on-leave hook (turn.py) suppresses
    # the auto-return of cards exiled with that source — for the next
    # leave-the-battlefield event on that source only. Used by
    # ``SacrificeSelfPreservingExileLink``: Sothera, the Supervoid's
    # end-step recall reads the cards "exiled with it" BEFORE Sothera
    # is sacrificed (so the controller can pick which one to recall),
    # then sacs the source; without the suppression flag, the on-leave
    # hook would race in and auto-return every remaining tagged card
    # to its owner's battlefield, which the printed text doesn't say.
    # Cleared by the on-leave hook itself once a leave event for the
    # matching source has been observed (one-shot suppression).
    suppress_exiled_by_source_on_leave_for: int | None = None
    # IDs of permanents scheduled to be sacrificed at end of combat.
    # Cleared during clear_combat_state after processing.
    # Used by Kavaron Harrier's attack token.
    pending_end_of_combat_sacrifices: list[int] = field(default_factory=list)
    # Player ids who have already created one or more tokens this turn.
    # Gates "the first time you would create tokens each turn"
    # replacement effects (Moonlit Meditation). Cleared at cleanup.
    players_who_created_tokens_this_turn: set[int] = field(default_factory=set)
    # Per-turn counter of how many times a tagged ability has resolved.
    # Keys are effect-specific labels (typically ("tag", source_id)).
    # Reset by run_cleanup_step. Used by Tannuk, Memorial Ensign's
    # "if this is the second time this ability has resolved" rider.
    ability_resolutions_this_turn: dict = field(default_factory=dict)
    # When True, combat damage assignment in combat._resolve_damage_step
    # is skipped entirely for the remainder of the turn. Set by Darkness
    # ({B} instant) and reset by run_cleanup_step. Non-combat damage
    # (direct damage spells, pingers, infect from non-combat sources)
    # is unaffected.
    prevent_combat_damage_this_turn: bool = False
    # FIFO queue of player ids scheduled to take an extra turn after
    # the current one wraps up. Populated by TakeExtraTurnAfterThisOne
    # (Nexus of Fate). Consumed by simulate.simulate_game between
    # turns: if the queue is non-empty, the next turn's active player
    # is the head of the queue instead of the natural next alive player.
    extra_turn_queue: list[int] = field(default_factory=list)
    # Per-turn count of creatures that have died (moved from battlefield
    # to graveyard while reading as creatures) regardless of controller.
    # Incremented in ``turn.move_off_battlefield`` for every dies event
    # the engine fires. Reset by ``run_cleanup_step``. Consumed by
    # ETB replacement effects keyed on ``a creature died this turn``
    # (Cackling Slasher's printed +1/+1 counter rider). The tracker
    # COUNTS deaths from any player — the printed clause doesn't
    # specify "you control", so a dies on either side suffices.
    creatures_died_this_turn: int = 0
    # Layered-walk memoization. Bumped by ``_invalidate_layered_cache``
    # whenever ``continuous_effects`` mutates. Cache entries store
    # ``(version_at_compute, result)``; on lookup, an entry whose
    # version doesn't match the current ``_layered_cache_version`` is
    # treated as stale and recomputed. Per-state (not shared across
    # clones — clone defaults to fresh empty cache + version=0).
    # Currently caches ``_source_layer6_wiped`` only (~5% of profile
    # at a single source.id; called 850k times in a single self-play
    # game inside the doubly-nested ``_static_bonuses`` walk). The
    # mechanism is general — future memoizations of ``_static_bonuses``
    # / ``_compute_effective_pt`` / ``effective_keywords`` will reuse
    # the same version counter and add their own per-key cache slots.
    _layered_cache_version: int = 0
    _layer6_wiped_cache: dict[int, tuple[int, bool]] = field(
        default_factory=dict
    )

    def _invalidate_layered_cache(self) -> None:
        """Invalidate every cached layered-walk result. Called by every
        site that mutates ``continuous_effects``. Cheap: just bumps a
        counter — stale dict entries are dropped lazily on the next
        lookup miss."""
        self._layered_cache_version += 1

    def active_player(self) -> Player:
        return self.players[self.active_player_idx]

    def player_by_id(self, player_id: int) -> Player:
        for p in self.players:
            if p.id == player_id:
                return p
        raise KeyError(f"no player with id={player_id}")

    def index_of(self, player_id: int) -> int:
        for i, p in enumerate(self.players):
            if p.id == player_id:
                return i
        raise KeyError(f"no player with id={player_id}")

    def new_object(
        self, printing: CardPrinting, owner_id: int, zone: Zone
    ) -> GameObject:
        obj = GameObject(
            id=self.next_object_id,
            printing=printing,
            owner_id=owner_id,
            controller_id=owner_id,
            zone=zone,
        )
        self.next_object_id += 1
        return obj

    def is_over(self) -> bool:
        return self.winner_id is not None or self.is_draw

    def add_continuous_effect(
        self,
        *,
        source_id: int,
        layer: int,
        kind: str,
        sublayer: int = 0,
        target_filter: str = "",
        target_id: Optional[int] = None,
        params: tuple = (),
        description: str = "",
        expires_at: Optional[str] = None,
        expires_at_player_id: Optional[int] = None,
    ) -> ContinuousEffect:
        """Allocate a fresh timestamp and append a continuous-effect
        record to the registry. Returns the appended record so callers
        can hold onto it (e.g., to reference its source_id later).
        ``expires_at`` defaults to None (lives until the source
        leaves play); pass ``"cleanup"`` for UEOT effects, or
        ``"controller_untap"`` (with ``expires_at_player_id`` set to
        the relevant controller id) for extended-temporal pumps.
        """
        ts = self.next_timestamp
        self.next_timestamp += 1
        effect = ContinuousEffect(
            source_id=source_id,
            layer=layer,
            timestamp=ts,
            kind=kind,
            sublayer=sublayer,
            target_filter=target_filter,
            target_id=target_id,
            params=params,
            description=description,
            expires_at=expires_at,
            expires_at_player_id=expires_at_player_id,
        )
        self.continuous_effects.append(effect)
        self._invalidate_layered_cache()
        return effect

    def grant_pt_pump_ueot(
        self,
        *,
        source_id: int,
        target_id: int,
        power: int,
        toughness: int,
        description: str = "",
    ) -> ContinuousEffect:
        """Helper for the layer-7 sublayer-2 ``"pump_pt"`` UEOT-grant
        pattern. Writes a single registry entry with
        ``params=(power_delta, toughness_delta)`` and
        ``expires_at="cleanup"``, AND mirrors the deltas onto the
        target's ``temp_power_bonus`` / ``temp_toughness_bonus``
        fields as a write-through cache. ``effective_power`` /
        ``effective_toughness`` continue to read from the field
        (the cache is the read path), while the registry holds the
        layer-7 metadata for future layer-aware ordering work.
        ``run_cleanup_step`` zeros both. No-op when both deltas
        are zero."""
        if power == 0 and toughness == 0:
            return None  # type: ignore[return-value]
        target = next(
            (o for o in self.battlefield if o.id == target_id), None,
        )
        if target is not None:
            target.temp_power_bonus += power
            target.temp_toughness_bonus += toughness
        return self.add_continuous_effect(
            source_id=source_id,
            layer=7,
            sublayer=2,
            kind="pump_pt",
            target_id=target_id,
            params=(power, toughness),
            expires_at="cleanup",
            description=description,
        )

    def grant_set_base_pt_ueot(
        self,
        *,
        source_id: int,
        target_id: int,
        power: int,
        toughness: int,
        description: str = "",
    ) -> "ContinuousEffect":
        """Helper for the layer-7 sublayer-1 ``"set_base_pt"`` UEOT-grant
        pattern: "target creature has base power and toughness N/N until
        end of turn." (CR layer 7b — sets, not adds.)

        Writes a registry entry with ``layer=7``, ``sublayer=1``,
        ``kind="set_base_pt"``, ``params=(power, toughness)``, and
        ``expires_at="cleanup"``. ``_compute_effective_pt``'s layer-7b
        path reads the registry directly via ``_registry_set_base_pt``,
        so no field mirror is needed — the registry entry expires at
        cleanup via ``expire_continuous_effects("cleanup")``.
        """
        return self.add_continuous_effect(
            source_id=source_id,
            layer=7,
            sublayer=1,
            kind="set_base_pt",
            target_id=target_id,
            params=(power, toughness),
            expires_at="cleanup",
            description=description,
        )

    def grant_pt_pump_until_player_next_turn(
        self,
        *,
        source_id: int,
        target_id: int,
        power: int,
        toughness: int,
        until_player_id: int,
        description: str = "",
    ) -> ContinuousEffect:
        """Helper for the layer-7 sublayer-2 ``"pump_pt"`` extended-
        temporal grant — "until your next turn" pumps. Mouth of the
        Storm's "creatures your opponents control get -3/-0 until
        your next turn" is the canonical case. Writes a single
        registry entry with ``expires_at="controller_untap"`` and
        ``expires_at_player_id=until_player_id``; ``_compute_effective_pt``
        walks the registry directly for these entries, so no field
        mirror is needed (``extended_temp_*`` was retired in this
        sweep). The entry expires at ``until_player_id``'s next
        untap step — ``run_untap_step`` calls
        ``expire_continuous_effects("controller_untap", player_id=ap.id)``."""
        if power == 0 and toughness == 0:
            return None  # type: ignore[return-value]
        return self.add_continuous_effect(
            source_id=source_id,
            layer=7,
            sublayer=2,
            kind="pump_pt",
            target_id=target_id,
            params=(power, toughness),
            expires_at="controller_untap",
            expires_at_player_id=until_player_id,
            description=description,
        )

    def grant_control_change_ueot(
        self,
        *,
        source_id: int,
        target_id: int,
        new_controller_id: int,
        description: str = "",
    ) -> None:
        """Helper for "Until end of turn, you gain control of target
        permanent" effects (Mutinous Massacre, Systems Override,
        Threaten / Act of Treason shape).

        Writes a layer-2 ``"control_change"`` registry entry with
        ``params=(new_controller_id,)`` and
        ``expires_at="cleanup"``. Captures the captured-baseline
        controller in ``controller_id_before_any_aura_swap`` if
        this is the first control-grant on the target, mirroring
        ``apply_aura_static_grants_on_attach``'s logic so the
        revert-to-baseline machinery in
        ``move_off_battlefield`` and ``run_cleanup_step``'s
        controller refresh works uniformly.

        Updates the ``target.controller_id`` write-through cache
        immediately via ``effective_controller`` so downstream
        reads (haste grants, attack eligibility) see the new
        controller right away.
        """
        target = next(
            (o for o in self.battlefield if o.id == target_id), None,
        )
        if target is None:
            return
        if effective_controller(self, target) == new_controller_id:
            return
        has_prior_grant = any(
            ce.layer == 2
            and ce.kind == "control_change"
            and ce.target_id == target.id
            for ce in self.continuous_effects
        )
        if not has_prior_grant:
            target.controller_id_before_any_aura_swap = target.controller_id
        self.add_continuous_effect(
            source_id=source_id,
            layer=2,
            kind="control_change",
            target_id=target.id,
            params=(new_controller_id,),
            expires_at="cleanup",
            description=description,
        )
        target.controller_id = effective_controller(self, target)

    def expire_continuous_effects(
        self, expires_at: str, *, player_id: Optional[int] = None,
    ) -> list[ContinuousEffect]:
        """Drop every registry entry whose ``expires_at`` matches
        the given marker (``"cleanup"`` for UEOT, ``"controller_untap"``
        for extended-temporal). Returns the dropped entries — useful
        for tests and for downstream cleanup hooks that need to react
        to specific kinds going away.

        For ``"controller_untap"`` the caller passes ``player_id`` —
        only entries whose ``expires_at_player_id`` matches are
        dropped (a Mouth-of-the-Storm-style "until your next turn"
        effect ends at the controller's untap step, not just any
        untap step). For ``"cleanup"`` the player_id is ignored
        because cleanup is a once-per-turn event tied to whoever
        the active player is at end-of-turn.
        """
        kept: list[ContinuousEffect] = []
        dropped: list[ContinuousEffect] = []
        for ce in self.continuous_effects:
            if ce.expires_at != expires_at:
                kept.append(ce)
                continue
            if (
                expires_at == "controller_untap"
                and player_id is not None
                and ce.expires_at_player_id != player_id
            ):
                kept.append(ce)
                continue
            dropped.append(ce)
        self.continuous_effects = kept
        self._invalidate_layered_cache()
        return dropped

    def remove_continuous_effects_from_source(
        self, source_id: int, *, only_static: bool = False,
    ) -> list[ContinuousEffect]:
        """Drop every registry entry produced by ``source_id`` (called
        when that source leaves the battlefield, or when a one-shot
        effect's window closes). Returns the dropped entries — useful
        for log/debug and for tests that want to assert which effects
        were torn down.

        ``only_static`` (default False): when True, only drop entries
        with ``expires_at is None`` — the static-while-source-on-the-
        battlefield kind (Tractor Beam's control grant, Mm'menon's
        ability grant, etc.). UEOT entries (``expires_at="cleanup"``)
        survive the source leaving — they end at the next cleanup
        step regardless of whether the granting source is still on
        the battlefield. ``move_off_battlefield`` uses
        ``only_static=True`` so a UEOT-grant from a permanent that
        subsequently dies still fires its dependent triggers /
        queries before cleanup wipes it (Perigee Beckoner's granted
        dies-rider being the canonical case).
        """
        kept: list[ContinuousEffect] = []
        dropped: list[ContinuousEffect] = []
        for ce in self.continuous_effects:
            matches = ce.source_id == source_id
            if only_static and ce.expires_at is not None:
                matches = False
            if matches:
                dropped.append(ce)
            else:
                kept.append(ce)
        self.continuous_effects = kept
        self._invalidate_layered_cache()
        return dropped

    def creatures_controlled_by(self, player_id: int) -> list[GameObject]:
        return [
            o for o in self.battlefield
            if o.controller_id == player_id and o.printing.is_creature
        ]

    def lands_controlled_by(self, player_id: int) -> list[GameObject]:
        return [
            o for o in self.battlefield
            if o.controller_id == player_id and o.printing.is_land
        ]

    def clone(self) -> "GameState":
        """Return an independent deep copy of this state, suitable for
        search rollouts.

        Semantics vs. ``copy.deepcopy(state)``:

        - CardPrinting refs are shared (frozen dataclasses with no
          mutable state). Same for frozensets and tuples of primitives.
        - All GameObjects are deep-copied. A ``{old_id: new_obj}`` map
          drives cross-reference rewiring so ``state.stack``'s StackItem
          sources and ``state.resolving_source`` point at the cloned
          objects.
        - Every zone list (battlefield + each player's library / hand /
          graveyard / exile / mana_pool) is a fresh list containing the
          cloned GameObjects.
        - ``state.log`` is a fresh empty ``LogBuffer`` with the same
          ``enabled`` flag — search rollouts don't need log history.
        - ``state.rng`` is a fresh ``random.Random`` seeded from the
          original's state, so the clone advances independently but
          deterministically.
        - ``Player.agent`` is **not** cloned — agents are decision-
          policy objects, not game state, and cloning them would both
          be wasteful and break mutable-agent contracts (RandomAgent's
          RNG, scheduled agent overrides). Search callers that need
          to vary the policy per rollout should swap the agent ref
          on the clone after calling ``.clone()``.

        GameObject integer id references (``attached_to``,
        ``exiled_by_source``) carry integer ids — those stay valid
        without remapping because the new objects keep the same id.

        Performance: this is a search hot path (thousands of clones
        per MCTS decision). Per-object cloning uses a shallow
        ``object.__new__`` + ``__dict__`` copy rather than the
        dataclass __init__ with 30+ kwargs — the latter spends
        almost all its time in name-resolution overhead.
        ``GameObject.blocked_by`` is the only mutable per-object
        field; we duplicate that explicitly. Every other field is
        either an int / bool / None / frozenset / Enum (immutable)
        or a reference to a frozen-dataclass CardPrinting (also
        safe to share).
        """
        # Build the id->new_obj map by deep-copying every GameObject
        # referenced anywhere in the state. Bulk paths
        # (battlefield + each player's hand) populate the map
        # directly without per-call ``get`` lookups since those zones
        # are mutually disjoint by construction. Cross-zone aliases
        # appear only on rare references — ``stack[i].source``,
        # ``resolving_source``, ``resolving_cost_paid_objects`` —
        # which call the closure below; the closure consults ``id_map``
        # to share the existing clone with the battlefield/hand walk
        # when the object lives in either zone.
        id_map: dict[int, GameObject] = {}

        def clone_obj(o: GameObject) -> GameObject:
            existing = id_map.get(o.id)
            if existing is not None:
                return existing
            # Fast slot-cloner: explicit per-slot assignment via the
            # exec'd ``_clone_game_object``; ``blocked_by`` is the only
            # list field that needs duplication.
            new = _clone_game_object(o)
            id_map[o.id] = new
            return new

        # Clone players (and every zone list on each player). The
        # exec'd slot-cloners are per-slot assignment fns generated at
        # module load; agent is shared (not game state). ManaCoin is a
        # slots dataclass whose two immutable string fields are never
        # mutated post-creation in the engine, so the same fast path
        # applies.
        new_players: list[Player] = []
        for p in self.players:
            np = _clone_player(p)
            # Library / graveyard / exile use a copy-on-write list
            # (see ``_CowList``). Both the source's list and the
            # clone's start out pointing at the same GameObject
            # instances; the first one to mutate any of those zones
            # forks (deep-cloning each element via ``_clone_game_object``)
            # and the other keeps the originals. Reads pass through
            # unchanged. Hand and mana_pool stay deep-cloned — hand
            # cards are routinely mutated in-place during the cast
            # pipeline, and the mana pool is small enough that
            # indirection wouldn't pay.
            #
            # We have to wrap the SOURCE list too, not just the
            # clone's: an in-place mutation on either side would leak
            # to the other if it isn't intercepted. The first wrap
            # promotes ``p.library`` from a plain ``list`` to a
            # ``_CowList`` — the rest of the engine sees a list
            # subclass and behaves identically.
            #
            # ``_clone_game_object`` (not the ``clone_obj`` closure)
            # is used as the fork callback: cross-references between
            # GameObjects are integer ids (``attached_to``,
            # ``blocked_by``, ``exiled_by_source``), so no cross-zone
            # ``id_map`` memoization is required at fork time. Using
            # the bare slot cloner avoids keeping the per-clone
            # ``id_map`` alive past the end of this clone() call.
            src_lib = p.library
            if not isinstance(src_lib, _CowList):
                src_lib = _CowList(src_lib)
                p.library = src_lib
            src_gy = p.graveyard
            if not isinstance(src_gy, _CowList):
                src_gy = _CowList(src_gy)
                p.graveyard = src_gy
            src_ex = p.exile
            if not isinstance(src_ex, _CowList):
                src_ex = _CowList(src_ex)
                p.exile = src_ex

            # Splice each new (clone-side) list into its source-side
            # sibling's share group (creating one if absent). The
            # share group is a single mutable list referenced by every
            # member, so adding the new clone-side is O(1) — one
            # ``append`` — regardless of how many clones already exist.
            # The first mutator on any group member clones the
            # elements into the OTHER members (see ``_fork_if_shared``
            # for why) and the mutator keeps the originals —
            # preserving caller-held element references.
            #
            # ``_new_uninitialized`` skips the default-attr init that
            # the regular ``_CowList`` constructor would do; we
            # overwrite those three attrs immediately below anyway.
            new_lib = _CowList._new_uninitialized(src_lib)
            new_gy = _CowList._new_uninitialized(src_gy)
            new_ex = _CowList._new_uninitialized(src_ex)
            new_lib._clone_each = _clone_game_object
            new_lib._owned = False
            new_gy._clone_each = _clone_game_object
            new_gy._owned = False
            new_ex._clone_each = _clone_game_object
            new_ex._owned = False
            for clone_side, src_side in (
                (new_lib, src_lib),
                (new_gy, src_gy),
                (new_ex, src_ex),
            ):
                if src_side._owned:
                    # First share: create a fresh group containing
                    # both members.
                    group = [src_side, clone_side]
                    src_side._owned = False
                    src_side._clone_each = _clone_game_object
                    src_side._share_group = group
                else:
                    # src_side is already in a share group; just
                    # append. Every other member sees the new entry
                    # immediately because they all reference the same
                    # list object.
                    group = src_side._share_group
                    group.append(clone_side)
                clone_side._share_group = group
            np.library = new_lib
            np.graveyard = new_gy
            np.exile = new_ex
            # Hand objects are guaranteed unique within (and across)
            # players (a card lives in exactly one zone at any moment
            # in MTG), so the per-call ``id_map.get`` lookup is dead
            # work. Skip the closure: clone directly and populate
            # ``id_map`` in the same pass so a stack-source / resolving-
            # source reference into the hand still resolves to the
            # same instance.
            new_hand = []
            for o in p.hand:
                new_o = _clone_game_object(o)
                id_map[o.id] = new_o
                new_hand.append(new_o)
            np.hand = new_hand
            np.mana_pool = [_clone_mana_coin(c) for c in p.mana_pool]
            new_players.append(np)

        # Same disjointness argument applies to battlefield: an object
        # is in exactly one of (battlefield, hand, library, graveyard,
        # exile, stack) at any moment, so the bulk battlefield walk
        # writes directly into ``id_map`` without redundant lookups.
        new_battlefield = []
        for o in self.battlefield:
            new_o = _clone_game_object(o)
            id_map[o.id] = new_o
            new_battlefield.append(new_o)

        # Stack items must point at the cloned GameObject for their
        # source. All other fields are immutable; share by reference.
        # ``cost_paid_objects`` likewise carries GameObject refs and
        # must be remapped through ``clone_obj`` so search rollouts see
        # cloned objects (sacrificed permanents now sitting in a player
        # graveyard) rather than stale originals.
        if self.stack:
            new_stack: list[StackItem] = []
            for item in self.stack:
                ni = _clone_stack_item(item)
                ni.source = clone_obj(item.source)
                if item.cost_paid_objects:
                    ni.cost_paid_objects = tuple(
                        clone_obj(o) for o in item.cost_paid_objects
                    )
                new_stack.append(ni)
        else:
            new_stack = []

        new_log = LogBuffer()
        new_log.enabled = self.log.enabled

        # ``random.Random()`` runs the C-level seed routine that draws
        # from os.urandom — ~5us on Windows. We're about to overwrite
        # the state with ``setstate`` anyway, so the seed is dead work.
        # Bypass ``__init__`` via ``__new__`` and load state directly.
        new_rng = random.Random.__new__(random.Random)
        new_rng.setstate(self.rng.getstate())

        new_resolving_source = (
            clone_obj(self.resolving_source)
            if self.resolving_source is not None else None
        )
        new_resolving_cost_paid_objects: tuple[GameObject, ...] = (
            tuple(clone_obj(o) for o in self.resolving_cost_paid_objects)
            if self.resolving_cost_paid_objects else ()
        )

        # Fast path: bypass the dataclass ``__init__`` and assign each
        # slot directly. The dataclass-generated ``__init__`` walks 30+
        # kwargs, runs default-factory callables for any unspecified
        # field, and re-validates against the slot descriptors —
        # ~1.6us. ``__new__`` + manual slot assignment is ~0.5us, and
        # we get to skip allocating empty containers when the source
        # has no entries (the common case during search: an idle
        # decision-point state has empty ``stack`` /
        # ``continuous_effects`` / ``once_per_turn_fired`` / etc.).
        new_state = GameState.__new__(GameState)
        new_state.players = new_players
        new_state.battlefield = new_battlefield
        new_state.stack = new_stack
        new_state.active_player_idx = self.active_player_idx
        new_state.priority_player_idx = self.priority_player_idx
        new_state.turn_number = self.turn_number
        new_state.step = self.step
        new_state.next_object_id = self.next_object_id
        # Empty-collection short-circuit: ``list()`` on an empty list
        # still allocates a fresh list object — ~0.05us each. With
        # ~5 such fields, that's ~0.25us we recover when they're
        # empty (the common case).
        new_state.continuous_effects = (
            list(self.continuous_effects) if self.continuous_effects else []
        )
        new_state.next_timestamp = self.next_timestamp
        new_state.log = new_log
        new_state.rng = new_rng
        new_state.winner_id = self.winner_id
        new_state.is_draw = self.is_draw
        new_state.permanent_left_battlefield_this_turn = (
            self.permanent_left_battlefield_this_turn
        )
        new_state.spell_warped_this_turn = self.spell_warped_this_turn
        new_state.once_per_turn_fired = (
            set(self.once_per_turn_fired) if self.once_per_turn_fired else set()
        )
        new_state.loyalty_activated_this_turn = (
            set(self.loyalty_activated_this_turn)
            if self.loyalty_activated_this_turn
            else set()
        )
        # Command-zone emblems: deep-clone each synthetic emblem
        # GameObject (same slot-cloner the battlefield walk uses) so the
        # clone owns independent emblem objects. Empty-list short-circuit
        # keeps the common (no-emblem) clone path allocation-free.
        new_state.emblems = (
            [_clone_game_object(e) for e in self.emblems]
            if self.emblems else []
        )
        new_state.delayed_triggers = (
            [dict(d) for d in self.delayed_triggers]
            if self.delayed_triggers else []
        )
        new_state.resolving_source = new_resolving_source
        new_state.resolving_spell = (
            clone_obj(self.resolving_spell)
            if self.resolving_spell is not None else None
        )
        new_state.resolving_controller_id = self.resolving_controller_id
        new_state.resolving_x_value = self.resolving_x_value
        new_state.resolving_kicked = self.resolving_kicked
        new_state.resolving_modes = self.resolving_modes
        new_state.resolving_additional_cost_choice_id = (
            self.resolving_additional_cost_choice_id
        )
        new_state.resolving_combat_damage_amount = (
            self.resolving_combat_damage_amount
        )
        new_state.resolving_combat_damage_source_controller_id = (
            self.resolving_combat_damage_source_controller_id
        )
        new_state.resolving_counter_amount = self.resolving_counter_amount
        new_state.resolving_cost_paid_objects = new_resolving_cost_paid_objects
        new_state.resolving_division = self.resolving_division
        new_state.resolving_spell = (
            clone_obj(self.resolving_spell)
            if self.resolving_spell is not None else None
        )
        new_state.last_exile_recall_count = self.last_exile_recall_count
        new_state.suppress_exiled_by_source_on_leave_for = (
            self.suppress_exiled_by_source_on_leave_for
        )
        new_state.pending_end_of_combat_sacrifices = (
            list(self.pending_end_of_combat_sacrifices)
            if self.pending_end_of_combat_sacrifices else []
        )
        new_state.players_who_created_tokens_this_turn = (
            set(self.players_who_created_tokens_this_turn)
            if self.players_who_created_tokens_this_turn else set()
        )
        new_state.ability_resolutions_this_turn = (
            dict(self.ability_resolutions_this_turn)
            if self.ability_resolutions_this_turn else {}
        )
        new_state.prevent_combat_damage_this_turn = (
            self.prevent_combat_damage_this_turn
        )
        new_state.extra_turn_queue = (
            list(self.extra_turn_queue) if self.extra_turn_queue else []
        )
        new_state.creatures_died_this_turn = self.creatures_died_this_turn
        # Layered-walk memo cache is per-state and intentionally NOT
        # shared with the source: the cache gets repopulated lazily
        # on the new state's next walk. Same-shape default the
        # dataclass __init__ would have produced.
        new_state._layered_cache_version = 0
        new_state._layer6_wiped_cache = {}
        return new_state
