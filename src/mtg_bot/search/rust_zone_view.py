"""Rust-backed zone-view shim — the B3-S2 codec slot-source switch.

The action-encoding codec (``training/action_encoding.py``) maps a
``Decision`` to a fixed policy slot by indexing a card's *position
within the viewer's zone*. Today it reads those positions from the
**Python** engine via ``_engine_state(state) ->
eng.player_by_id(viewer).hand`` etc. (``action_encoding.py:316-497``).
Post-flip the position source must be the **Rust** state's zones.

**The v-chain-SAFE design (spec §3.2).** This module presents the
EXACT interface the codec already consumes — ``.player_by_id(viewer)``
with ``.hand`` / ``.graveyard`` / ``.exile`` / ``.library`` lists, a
flat ``.battlefield`` list, and per-card ``.id`` / ``.printing`` /
``.controller_id`` / ``.attacking`` + the canonical_v2 modifier
attributes — but reads the zone membership + ordering from the Rust
``*_snapshot`` pymethods. The codec body then runs **completely
unchanged**: same positions, same v1 raw / v2 ``_canonical_zone_sort_
key`` sort, same ``card.id`` tiebreak, same caps, same variant flags.
**The slot mapping is bit-identical — only its data source moved.**
This is precisely the spec's "trained v17 weights keep working; the
slot mapping is unchanged" requirement, and it does NOT touch the
``positional_v1`` / ``canonical_v2`` axis.

**B3-pre-EXT is already satisfied — NO new Rust pymethod.** The spec
§3.2 anticipated a new Rust zone-listing micro-slice. Verify-first
against live ``main``: the existing ``hand_snapshot`` /
``graveyard_snapshot`` / ``exile_snapshot`` / ``library_snapshot`` /
``battlefield_snapshot`` pymethods (``rust/src/state_ops_snapshot.rs:
98-220``) ALREADY return per-object dicts in zone order carrying
``id`` + ``printing_name``, which is exactly the (name, id) tuple the
codec's positional + canonical_v2 sort needs. B3-S2 is therefore a
**pure-Python** wiring slice — no ``rust/src/`` change.

**Printing semantics stay Python (flip architecture).** Per
``SOT_FLIP_CUTOVER_PLAN.md`` §5 the card parser/loader stays Python.
The shim resolves each card's ``printing`` to the real Python
``CardPrinting`` via the resolver the ``RustGameStateAdapter`` was
constructed with (built from the same ``DeckSpec``'s ``CardDef``s the
Rust state was built from, through the SAME
``_card_def_to_python_printing`` path ``build_python_state`` uses) —
so ``printing.name`` / ``.is_creature`` / ``.is_spacecraft`` /
``.room_halves`` are byte-identical to the Python path.

**Canonical_v2 modifier-flag scope (HONEST, NOT papered over).** The
codec's ``_canonical_zone_sort_key`` reads 6 boolean modifier flags
(``warped`` / ``cast_via_warp`` / ``face_down`` /
``playable_from_exile_this_turn`` / ``play_from_exile_requires_kavu``
/ ``cast_from_exile_with_lightstall_surcharge``) via
``getattr(card, ..., False)``. The Rust ``object_to_pydict``
(``state_ops_snapshot.rs:68``) does NOT carry these. **On the
loader-admitted flip population (C6-fenced) every one of these is
False** — they are the warp / manifest / alt-cost-exile-recast axes,
all loader-DECLINED on the admitted surface (the same C1/§1.4
scoping). So a shim card simply omitting them ⇒ ``getattr(...,
False)`` ⇒ the canonical_v2 sort key is byte-identical to the Python
path on the admitted surface. This is a **bounded, documented,
admitted-surface-exact** simplification (the C1-style "scope to the
live surface, forward-note the rest" discipline), NOT a silent gap:
it is recorded in ``docs/SEARCH_LIMITATIONS.md`` and the precise
follow-up (a Rust snapshot extension carrying the 6 flags, needed
ONLY when an alt-cost carrier becomes loader-admitted) is named
there. A non-admitted card cannot enter a Rust-sourced game (C6 hard
boundary, ``66485d6d``), so the simplification is unreachable on the
flip population by construction.
"""

from __future__ import annotations

from typing import Any, Optional


class _RustPrintingView:
    """Adapts a Python ``CardPrinting`` to the attribute surface the
    codec touches (``.name`` / ``.is_creature`` / ``.is_spacecraft`` /
    ``.room_halves``). It IS the real Python ``CardPrinting`` when the
    resolver supplies one; the wrapper exists only to give a
    deterministic fallback (name-only) if a printing is unresolved
    (an unresolved printing on the admitted surface is a hard error,
    surfaced loudly — never silently mis-slotted)."""

    __slots__ = ("_p", "_name")

    def __init__(self, name: str, printing: Optional[Any]) -> None:
        self._name = name
        self._p = printing

    @property
    def name(self) -> str:
        # The codec sorts by printing.name; the Rust snapshot's
        # printing_name is the SoT for the name axis even if the
        # full printing is unresolved.
        return self._name if self._p is None else self._p.name

    @property
    def is_creature(self) -> bool:
        if self._p is None:
            raise RustZoneViewError(
                f"printing {self._name!r} unresolved — cannot answer "
                f"is_creature (a non-admitted card must not reach a "
                f"Rust-sourced codec call; C6 hard boundary)"
            )
        return bool(self._p.is_creature)

    @property
    def is_spacecraft(self) -> bool:
        if self._p is None:
            raise RustZoneViewError(
                f"printing {self._name!r} unresolved — cannot answer "
                f"is_spacecraft"
            )
        return bool(self._p.is_spacecraft)

    @property
    def room_halves(self):
        if self._p is None:
            return ()
        return self._p.room_halves


class RustZoneViewError(RuntimeError):
    """A Rust zone-view lookup failed loudly (e.g. an unresolved
    printing on the admitted surface). Raised rather than silently
    mis-slotting — ``feedback_no_fallback_hybrids`` /
    ``feedback_silent_noop_pipelines``."""


class _RustCardView:
    """One card in a Rust zone, presenting the codec's per-card
    attribute surface. Modifier flags (``warped`` / ``face_down`` /
    …) are intentionally ABSENT so ``getattr(card, flag, False)``
    yields ``False`` — exact on the loader-admitted / C6-fenced
    surface (see module docstring)."""

    __slots__ = ("id", "printing", "controller_id", "attacking")

    def __init__(
        self,
        obj_id: int,
        printing: _RustPrintingView,
        controller_id: int,
        attacking: bool = False,
    ) -> None:
        self.id = obj_id
        self.printing = printing
        self.controller_id = controller_id
        self.attacking = attacking


class _RustPlayerView:
    """The ``eng.player_by_id(viewer)`` surface — ``.hand`` /
    ``.graveyard`` / ``.exile`` / ``.library`` lists of
    ``_RustCardView`` in Rust zone-insertion order (the codec applies
    its own v1-raw / v2-sorted ordering on top, unchanged)."""

    __slots__ = ("id", "hand", "graveyard", "exile", "library")

    def __init__(self, pid: int) -> None:
        self.id = pid
        self.hand: list = []
        self.graveyard: list = []
        self.exile: list = []
        self.library: list = []


class RustZoneView:
    """The ``_engine_state`` stand-in for a ``RustGameStateAdapter``.

    Presents ``.player_by_id(viewer)`` + a flat ``.battlefield`` list
    sourced from the Rust ``*_snapshot`` pymethods. Built lazily per
    codec call from the live Rust state so it always reflects the
    current zones (the codec is called once per decision moment; the
    snapshot cost is the same order as the Python ``player_by_id``
    walk it replaces).
    """

    def __init__(
        self,
        rust_state: Any,
        printing_resolver: Optional[dict] = None,
    ) -> None:
        self._rust = rust_state
        self._resolver = printing_resolver or {}
        self._players: dict[int, _RustPlayerView] = {}
        self._battlefield: list = []
        self._build()

    def _printing(self, name: str) -> _RustPrintingView:
        return _RustPrintingView(name, self._resolver.get(name))

    def _card(self, d: dict, *, attacking: bool = False) -> _RustCardView:
        name = d.get("printing_name", "")
        return _RustCardView(
            obj_id=int(d["id"]),
            printing=self._printing(name),
            controller_id=int(d["controller_id"]),
            attacking=attacking,
        )

    def _build(self) -> None:
        for pid in (0, 1):
            pv = _RustPlayerView(pid)
            for d in self._rust.hand_snapshot(pid):
                pv.hand.append(self._card(dict(d)))
            for d in self._rust.graveyard_snapshot(pid):
                pv.graveyard.append(self._card(dict(d)))
            for d in self._rust.exile_snapshot(pid):
                pv.exile.append(self._card(dict(d)))
            # library_snapshot is bottom-first; top = last (round-1
            # convention, state_ops_snapshot.rs:116-118). The codec
            # only reads library[0] as "library top" — but the Python
            # engine's ``library[0]`` IS the top. Reverse so index 0
            # is the top, matching the Python ``player.library``
            # convention the codec was written against.
            lib = [self._card(dict(d)) for d in
                   self._rust.library_snapshot(pid)]
            pv.library = list(reversed(lib))
            self._players[pid] = pv
        # battlefield_snapshot is a single flat list across BOTH
        # players ordered by etb_timestamp (CE4) — exactly the
        # Python ``state.battlefield`` centralized append-order the
        # codec's ``_own_battlefield`` / ``_own_creatures`` /
        # ``_own_spacecraft`` / ``_attacking_creatures`` filter on.
        #
        # B3-S3: ``object_to_pydict`` does NOT carry ``attacking``
        # (verified live, state_ops_snapshot.rs:68); the codec's
        # ``_attacking_creatures(eng)`` (the BlockerDecision-slot
        # path) reads ``o.attacking``. We derive the declared-attacker
        # set from the Rust combat state via ``get_attackers()``
        # (``state_ops_combat.rs:837`` — the Vec the active player
        # committed during DECLARE_ATTACKERS) and stamp ``attacking``
        # on the matching battlefield cards. ``_attacking_creatures``
        # then sorts them by id (its own convention), so this is
        # byte-identical to the Python adapter's
        # ``[o for o in battlefield if o.attacking]`` source for the
        # codec's blocker-slot encode.
        try:
            attacker_ids = set(int(i) for i in self._rust.get_attackers())
        except Exception:
            # Defensive: if the combat accessor is unavailable for a
            # given build, fall back to no-attackers (the S2
            # priority-window axis never reads .attacking). Never a
            # silent wrong-slot — _attacking_creatures would just be
            # empty, and the BlockerDecision encode path raises
            # EncodingOverflowError loudly (codec contract) rather
            # than mis-slotting.
            attacker_ids = set()
        for d in self._rust.battlefield_snapshot():
            dd = dict(d)
            self._battlefield.append(
                self._card(
                    dd, attacking=(int(dd["id"]) in attacker_ids)
                )
            )

    # ---- the codec-facing surface ------------------------------------

    def player_by_id(self, pid: int) -> _RustPlayerView:
        return self._players[int(pid)]

    @property
    def battlefield(self) -> list:
        return self._battlefield
