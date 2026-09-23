"""Canonical run-label / run_id derivation for the iterate pipeline.

Every id the AlphaZero iterate loop writes into ``runs.db`` (and
every progress-JSON / replay-dir name derived from one) is built
here so the producers agree byte-for-byte:

- ``mtg_bot.cli.iterate`` (the loop itself) derives its per-iteration
  ids from ``iterate_state.json``'s ``iterations_completed`` counter.
- ``mtg_bot.launcher.config`` (the unified launcher) independently
  derives the SAME cycle id from ``[iter].target_iter`` and
  pre-registers it via ``/run/start_or_restart`` before spawning
  iterate. If the two formulas ever drift, the launcher registers
  one row and iterate writes a different one -- the UI then shows a
  stale ``running`` card forever.

Historically both sites hard-coded ``f"iter_{n:03d}_cycle"``. This
module is the single source of truth they now share.

Lineage prefixes
----------------

A ``label_prefix`` namespaces a whole training lineage. The
coordinator's ``runs.db`` is global: run ids are the PRIMARY KEY and
``/run/start_or_restart`` returns HTTP 409 when a row with the same
id already exists in ``running`` / ``completed`` status. A second
lineage (a fresh ``trained_weights_s2/`` registry whose
``iterate_state.json`` restarts at ``iterations_completed = 0``)
would therefore collide with the first lineage's ``iter_001_cycle``
on its very first cycle.

Passing ``label_prefix="s2_"`` (``mtg_bot iterate
--run-label-prefix s2_``) shifts every generated id into its own
namespace::

    s2_iter_001_cycle
    s2_iter_001_self_play_v1
    s2_iter_001_train_v2
    s2_iter_001_eval_v2_vs_v1

The default is the empty string, which reproduces the pre-existing
ids exactly -- the original lineage is bit-identical.

Prefixes are normalised by :func:`normalize_label_prefix`: a
trailing underscore is added when missing (so ``s2`` and ``s2_``
mean the same thing) and the charset is restricted to
``[A-Za-z0-9-]`` plus internal underscores, because these strings
end up in filenames, SQL ``LIKE`` patterns and glob patterns.
"""

from __future__ import annotations

import re

__all__ = [
    "ITER_LABEL_RE",
    "LABEL_PREFIX_HELP",
    "InvalidLabelPrefix",
    "cycle_id",
    "eval_run_id",
    "eval_run_id_prefix",
    "iter_label",
    "normalize_label_prefix",
    "npz_name_prefix",
    "parse_iter_label",
    "self_play_run_id",
    "sentinel_glob_prefix",
    "sql_like_prefixes",
    "train_run_id",
]


class InvalidLabelPrefix(ValueError):
    """Raised when a run-label prefix contains characters that would
    break a filename / glob / SQL ``LIKE`` pattern."""


# A normalised prefix is either empty or ``<token>_`` where token is
# alnum plus ``-`` and ``_`` (no leading/trailing dash, no path
# separators, no glob metacharacters, no SQL wildcards).
_PREFIX_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

# Matches ``<prefix>iter_<NNN>`` at the start of a label / run_id.
# ``prefix`` is greedy-free: ``iter_`` is anchored as the LAST
# ``iter_`` that is followed by digits, so ``s2_iter_001`` yields
# prefix ``s2_`` and index 1.
ITER_LABEL_RE = re.compile(
    r"^(?P<prefix>(?:[A-Za-z0-9][A-Za-z0-9-]*_)*?)"
    r"iter_(?P<idx>\d+)(?P<rest>.*)$",
)

LABEL_PREFIX_HELP = (
    "Namespace prefix for EVERY run label this loop generates "
    "(cycle id, self-play / train / eval stage ids, progress-JSON "
    "filenames, replay dir names). Default '' reproduces the "
    "historical ``iter_NNN_*`` ids exactly. Pass e.g. ``s2_`` to "
    "run a SECOND training lineage (its own registry root + "
    "iterate_state.json restarting at iteration 1) against the same "
    "coordinator runs.db without colliding with the first "
    "lineage's rows -- ids become ``s2_iter_001_cycle`` etc. A "
    "trailing underscore is added when missing."
)


def normalize_label_prefix(prefix: "str | None") -> str:
    """Return the canonical form of a lineage prefix.

    ``None`` / ``""`` / whitespace -> ``""`` (the historical,
    un-prefixed lineage). Anything else is stripped, gets a trailing
    ``_`` when it doesn't already have one, and is validated against
    :data:`_PREFIX_TOKEN_RE`.

    Raises :class:`InvalidLabelPrefix` on a prefix that would break a
    filename / glob / SQL ``LIKE`` pattern -- failing loudly here is
    far cheaper than discovering it as a half-written runs.db row.
    """
    if prefix is None:
        return ""
    token = str(prefix).strip()
    if not token:
        return ""
    token = token.rstrip("_")
    if not token:
        # A bare ``"_"`` (or ``"__"``) carries no lineage -- treat it
        # as "no prefix" rather than erroring on an empty token.
        return ""
    if not _PREFIX_TOKEN_RE.match(token):
        raise InvalidLabelPrefix(
            f"invalid run-label prefix {prefix!r}: expected an "
            f"alphanumeric token (``-`` and ``_`` allowed inside, "
            f"e.g. 's2' or 's2_'); the prefix ends up in filenames, "
            f"glob patterns and SQL LIKE patterns."
        )
    return f"{token}_"


def iter_label(iter_idx_one_based: int, label_prefix: str = "") -> str:
    """``<prefix>iter_NNN`` -- the per-iteration label every stage id
    is built from. ``iter_idx_one_based`` is
    ``iterations_completed + 1`` on the iterate side and
    ``[iter].target_iter`` on the launcher side."""
    prefix = normalize_label_prefix(label_prefix)
    return f"{prefix}iter_{int(iter_idx_one_based):03d}"


def cycle_id(iter_idx_one_based: int, label_prefix: str = "") -> str:
    """``<prefix>iter_NNN_cycle`` -- the parent runs.db row id.

    THE coherence point: the launcher pre-registers this id and
    iterate re-registers the same id (its ``start_run`` returns
    ``conflict`` and it rides the launcher's row). Both call here.
    """
    return f"{iter_label(iter_idx_one_based, label_prefix)}_cycle"


def self_play_run_id(
    iter_idx_one_based: int,
    best_version: str,
    label_prefix: str = "",
) -> str:
    """``<prefix>iter_NNN_self_play_<best_version>``."""
    label = iter_label(iter_idx_one_based, label_prefix)
    return f"{label}_self_play_{best_version}"


def train_run_id(
    iter_idx_one_based: int,
    trained_version: str,
    label_prefix: str = "",
) -> str:
    """``<prefix>iter_NNN_train_<trained_version>``."""
    label = iter_label(iter_idx_one_based, label_prefix)
    return f"{label}_train_{trained_version}"


def eval_run_id(
    iter_idx_one_based: int,
    new_version: str,
    old_version: str,
    label_prefix: str = "",
) -> str:
    """``<prefix>iter_NNN_eval_<new>_vs_<old>``."""
    label = iter_label(iter_idx_one_based, label_prefix)
    return f"{label}_eval_{new_version}_vs_{old_version}"


def eval_run_id_prefix(
    iter_idx_one_based: int,
    new_version: str,
    label_prefix: str = "",
) -> str:
    """The ``<prefix>iter_NNN_eval_<new>_vs_`` stem used to GLOB the
    eval progress card when the opponent version isn't known (crash
    reconciliation -- see ``iterate._find_eval_progress``)."""
    label = iter_label(iter_idx_one_based, label_prefix)
    return f"{label}_eval_{new_version}_vs_"


def npz_name_prefix(label_prefix: str = "") -> str:
    """``<prefix>iter_`` -- the basename prefix every self-play npz
    the loop writes starts with. ``find_foreign_npzs`` uses this to
    tell the loop's own data from stray debug npzs that would poison
    the training mix."""
    return f"{normalize_label_prefix(label_prefix)}iter_"


def sentinel_glob_prefix(
    iter_idx_one_based: int, label_prefix: str = "",
) -> "tuple[str, ...]":
    """Glob patterns matching the STOP sentinels for one iteration.

    Both the zero-padded (``iter_003``) and the historical
    non-padded (``iter_3``) forms are returned so a UI-side residue
    sweep catches drift either way.
    """
    prefix = normalize_label_prefix(label_prefix)
    n = int(iter_idx_one_based)
    return (
        f".STOP_{prefix}iter_{n:03d}_*",
        f".STOP_{prefix}iter_{n}_*",
    )


def sql_like_prefixes(
    iter_idx_one_based: int, label_prefix: str = "",
) -> "tuple[str, ...]":
    """SQL ``LIKE`` patterns matching every runs.db row belonging to
    one iteration of one lineage.

    Load-bearing for lineage isolation: without the prefix, a UI
    re-launch of the ``s2_`` lineage at iteration 1 would sweep the
    ORIGINAL lineage's ``iter_001_*`` rows out of runs.db.
    """
    prefix = normalize_label_prefix(label_prefix)
    n = int(iter_idx_one_based)
    return (
        f"{prefix}iter_{n:03d}_%",
        f"{prefix}iter_{n}_%",
    )


def parse_iter_label(label: str) -> "tuple[str, int, str] | None":
    """Split ``<prefix>iter_<NNN><rest>`` into
    ``(prefix, iter_idx, rest)``; ``None`` when the label doesn't
    match. Prefix-tolerant replacement for ``label.startswith
    ("iter_")`` checks."""
    if not label:
        return None
    m = ITER_LABEL_RE.match(label)
    if m is None:
        return None
    return m.group("prefix"), int(m.group("idx")), m.group("rest")
