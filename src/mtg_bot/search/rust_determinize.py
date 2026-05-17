"""Determinization-via-Rust — the B3-S3 hidden-info sampler for the
Rust-sourced search (spec §3.4).

The Python determinizer (``search/determinize.py``) permutes
``card.printing`` among the hidden-zone ``GameObject``s of a **Python**
``GameState``. Post-flip the search drives a **Rust** state, so the
same hidden-info sampling must be applied to the Rust state's
hidden-zone objects.

**The split (spec §3.4): the epistemic policy stays Python; only the
data plumbing is Rust.** ``viewer_knows`` (which cards the viewer can
identify) is the hidden-information *model*, NOT engine rules — it
stays Python here, mirroring ``determinize.viewer_knows``. The Rust
side supplies exactly two bounded, NON-rules extraction surfaces:

* read: the existing ``hand_snapshot`` / ``library_snapshot`` /
  ``graveyard_snapshot`` / ``exile_snapshot`` pymethods give per-zone
  object dicts (id + ``printing_id`` + zone) — the hidden-zone
  listing.
* write: ``set_object_printing_id(obj_id, new_printing_id)`` (the
  B3-pre-EXT write half added by this slice, ``state_ops_zones.rs``)
  — the Rust analog of the Python determinizer's ``card.printing =
  new_printing`` reassignment. CoW-safe (``Arc::make_mut``), so
  cloning then determinizing the clone leaves the source god-view
  state pristine across PIMC samples.

Algorithm — a faithful mirror of ``determinize._determinize_player``:
for each player, pool the ``printing_id``s of every hand+library card
the viewer doesn't know, shuffle the pool, and reassign via
``set_object_printing_id``. Zones, ids, owners, per-zone counts are
all preserved; only which ``printing_id`` each hidden object carries
is permuted — exactly the per-card-flag epistemic model.

**SCOPED FINDING (honest, SL-recorded — NOT papered over).** The
Python ``viewer_knows`` has 3 conditions
(``determinize.py:37-61``): (1) ``viewer in
card.publicly_known_to`` (explicit reveal tracking), (2)
``card.zone`` is a public zone, (3) card is in the viewer's own
hand. The Rust ``GameObject`` does NOT model ``publicly_known_to``
(no such field — verified live; reveal-tracking is a non-
bridge-expressible mechanic, loader-DECLINED on the admitted
surface, the same C1/§1.4 scoping). On the loader-admitted /
C6-fenced flip population ``publicly_known_to`` is always empty, so
``viewer_knows`` reduces to conditions (2)+(3) — which the Rust
snapshots fully expose (``zone`` + the per-player snapshot
identifying the owning player). This is the C1-style "scope to the
live surface, forward-note the rest" discipline; the precise
follow-up (a Rust ``publicly_known_to`` field + snapshot key, needed
ONLY if a reveal-tracking carrier becomes loader-admitted) is named
in ``docs/SEARCH_LIMITATIONS.md``. C6 makes a non-admitted card
unreachable on the flip population by construction.
"""

from __future__ import annotations

import random
from typing import Any, Optional

# Rust ZONE constants (rust/src/state_ops_zones.rs:40-47). Mirrored
# here so viewer_knows can classify a snapshot's `zone` int without a
# Rust round-trip.
_ZONE_HAND = 0
_ZONE_LIBRARY = 1
_ZONE_BATTLEFIELD = 2
_ZONE_GRAVEYARD = 3
_ZONE_STACK = 4
_ZONE_EXILE = 5
_PUBLIC_ZONES = frozenset(
    {_ZONE_BATTLEFIELD, _ZONE_GRAVEYARD, _ZONE_EXILE, _ZONE_STACK}
)


def _rust_viewer_knows(obj_dict: dict, owner_pid: int, viewer_id: int) -> bool:
    """Rust-snapshot analog of ``determinize.viewer_knows`` — the
    epistemic policy, kept Python. ``obj_dict`` is one
    ``*_snapshot`` per-object dict; ``owner_pid`` is the player whose
    snapshot it came from (the owner, since snapshots are per-player).

    True when: the card is in a public zone OR it is in the viewer's
    own hand. The ``publicly_known_to`` explicit-reveal condition is
    omitted (not modeled in Rust; empty on the loader-admitted
    surface — see module docstring's SCOPED FINDING)."""
    zone = int(obj_dict["zone"])
    if zone in _PUBLIC_ZONES:
        return True
    if zone == _ZONE_HAND and owner_pid == viewer_id:
        return True
    return False


def rust_determinize(
    rust_state: Any,
    viewer_id: int,
    rng: Optional[random.Random] = None,
) -> Any:
    """Permute hidden-zone ``printing_id``s of ``rust_state`` so the
    result is consistent with what ``viewer_id`` knows. Mutates
    ``rust_state`` IN PLACE (the caller clones first if it must
    preserve the god-view — same contract as PIMC's
    ``_determinize(sub.engine_state, ..., in_place=True)``; the
    provider's ``clone()`` is the CoW boundary). Returns
    ``rust_state`` for call-chaining.

    Faithful mirror of ``determinize._determinize_player``: pool
    hand+library cards the viewer doesn't know, shuffle the
    ``printing_id`` tuple, reassign via ``set_object_printing_id``.
    """
    if rng is None:
        rng = random.Random()
    for pid in (0, 1):
        _determinize_player(rust_state, pid, viewer_id, rng)
    return rust_state


def _determinize_player(
    rust_state: Any, owner_pid: int, viewer_id: int,
    rng: random.Random,
) -> None:
    """Permute ``printing_id`` among ``owner_pid``'s hand+library
    cards the viewer doesn't know. Counts/zones/ids/owners are
    unchanged — only ``printing_id`` is shuffled, exactly the
    Python determinizer's per-card-flag model."""
    hidden_ids: list[int] = []
    hidden_pids: list[int] = []
    # Hand then library, mirroring determinize._determinize_player's
    # pool order (it pools hand first, then library).
    for d in rust_state.hand_snapshot(owner_pid):
        dd = dict(d)
        if not _rust_viewer_knows(dd, owner_pid, viewer_id):
            hidden_ids.append(int(dd["id"]))
            hidden_pids.append(int(dd["printing_id"]))
    for d in rust_state.library_snapshot(owner_pid):
        dd = dict(d)
        if not _rust_viewer_knows(dd, owner_pid, viewer_id):
            hidden_ids.append(int(dd["id"]))
            hidden_pids.append(int(dd["printing_id"]))
    if len(hidden_ids) <= 1:
        # 0 or 1 hidden cards — nothing to permute (matches the
        # Python determinizer's `if len(hidden) <= 1: return`).
        return
    shuffled = list(hidden_pids)
    rng.shuffle(shuffled)
    for obj_id, new_pid in zip(hidden_ids, shuffled):
        ok = rust_state.set_object_printing_id(obj_id, new_pid)
        if not ok:
            # The id came straight from the snapshot — a miss is a
            # Rust contract violation, surfaced loudly (never a
            # silent skip; feedback_silent_noop_pipelines).
            raise RuntimeError(
                f"rust_determinize: set_object_printing_id miss for "
                f"obj {obj_id} (it was in the snapshot — Rust "
                f"zone-listing/write contract violation)"
            )
