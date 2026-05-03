"""Small utilities used only by ``scripts/iterate_alphazero.py``.

Lives under ``mtg_bot.training`` so it's importable from tests
without the sys.path-manipulating script preamble. Today this
module is one helper — the foreign-npz guard that prevents the
trainer from co-globbing stale debug npzs into the iterate loop's
training mix (the bug that exploded v7's policy CE on the first
iter run with deck_pool + replay capture).
"""

from __future__ import annotations

from pathlib import Path


def find_foreign_npzs(data_dir: Path) -> list[str]:
    """Return ``.npz`` filenames under ``data_dir`` that don't match
    the ``iter_*.npz`` pattern. iterate writes its self-play files
    as ``iter_NNN_<bootstrap>_<utc>.npz``, and ``train_nn.py`` globs
    every ``.npz`` in the dir it's pointed at. Anything else is a
    landmine: foreign npzs may have been written by older code paths
    where the policy/action-mask invariants didn't hold, and even a
    few hundred mask-mismatched rows are enough to blow CE through
    the roof and corrupt the next-iteration model.

    Returns sorted basenames; empty list when the dir is clean. The
    caller decides whether to fail (recommended) or just warn.
    """
    if not data_dir.is_dir():
        return []
    return sorted(
        p.name for p in data_dir.glob("*.npz")
        if not p.name.startswith("iter_")
    )
