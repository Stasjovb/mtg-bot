"""End-to-end smoke test for ``scripts/train_deck_belief.py``.

Drives the CLI on a tiny synthetic corpus to exercise the full
training + evaluation + report-writing pipeline. The real
corpus-based training run is invoked manually for headline metrics;
the unit-test gate covers the wiring.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import random
from pathlib import Path

import numpy as np
import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "train_deck_belief.py"
)


def _load_script_module():
    """Load ``scripts/train_deck_belief.py`` as a module for direct testing."""
    spec = importlib.util.spec_from_file_location(
        "_train_deck_belief", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tiny_corpus(tmp_path: Path) -> Path:
    """Write a tiny gzipped 17lands-shaped corpus to disk."""
    rng = random.Random(0)
    archetypes = [
        ["Mountain"] * 5 + ["Bolt"] * 3 + ["Goblin"] * 2,
        ["Island"] * 5 + ["Counter"] * 3 + ["Drake"] * 2,
        ["Plains"] * 3 + ["Mountain"] * 3 + ["Bolt"] * 2 + ["Soldier"] * 2,
        ["Island"] * 3 + ["Swamp"] * 3 + ["Counter"] * 2 + ["Wraith"] * 2,
    ]
    decks = []
    flavor = ["Wandering Eye", "Lost Soul", "Mystery"]
    for i in range(40):
        for base in archetypes:
            deck = list(base) + [rng.choice(flavor)]
            decks.append(
                {
                    "draft_id": f"draft_{i}",
                    "build_index": 0,
                    "cards": deck,
                    "main_colors": "RG",
                    "splash_colors": "",
                    "total_games": 2,
                    "total_wins": 1,
                }
            )
    path = tmp_path / "tiny_decks.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(decks, f)
    return path


def test_train_deck_belief_main_end_to_end(
    tiny_corpus: Path, tmp_path: Path, capsys
) -> None:
    """Run the full main() with a small corpus, assert outputs exist."""
    mod = _load_script_module()
    output_dir = tmp_path / "models"
    report_path = tmp_path / "report.json"

    rc = mod.main(
        [
            "--corpus",
            str(tiny_corpus),
            "--output",
            str(output_dir),
            "--report-path",
            str(report_path),
            "--val-fraction",
            "0.2",
            "--prefixes-per-deck",
            "3",
            "--nn-hidden-dim",
            "16",
            "--nn-n-layers",
            "1",
            "--nn-epochs",
            "2",
            "--nn-batch-size",
            "32",
            "--seed",
            "0",
        ]
    )
    assert rc == 0

    # Models exist.
    assert (output_dir / "baseline.npz").exists()
    assert (output_dir / "nn.pt").exists()

    # Report exists and has expected schema.
    report = json.loads(report_path.read_text())
    assert report["corpus"] == str(tiny_corpus)
    assert report["n_train_decks"] > 0
    assert report["n_val_decks"] > 0
    assert report["vocab_size"] > 0
    assert "baseline" in report
    assert "nn" in report
    assert report["best_model"] in ("baseline", "nn")
    for key in ("recall_at_5", "recall_at_10", "recall_at_20", "brier", "ece"):
        assert key in report["baseline"]
        assert key in report["nn"]
    assert isinstance(report["baseline"]["calibration_bins"], list)

    # Stdout report mentions the sections.
    captured = capsys.readouterr().out
    assert "Baseline" in captured
    assert "NN MLP" in captured
    assert "recall@10" in captured


def test_train_deck_belief_skip_nn(
    tiny_corpus: Path, tmp_path: Path
) -> None:
    """``--skip-nn`` produces only the baseline."""
    mod = _load_script_module()
    output_dir = tmp_path / "models"
    report_path = tmp_path / "report.json"

    rc = mod.main(
        [
            "--corpus",
            str(tiny_corpus),
            "--output",
            str(output_dir),
            "--report-path",
            str(report_path),
            "--val-fraction",
            "0.2",
            "--prefixes-per-deck",
            "3",
            "--skip-nn",
        ]
    )
    assert rc == 0
    assert (output_dir / "baseline.npz").exists()
    assert not (output_dir / "nn.pt").exists()
    report = json.loads(report_path.read_text())
    assert "nn" not in report
    assert report["best_model"] == "baseline"


def test_train_deck_belief_respects_limit(
    tiny_corpus: Path, tmp_path: Path
) -> None:
    """``--limit`` truncates the corpus before splitting."""
    mod = _load_script_module()
    rc = mod.main(
        [
            "--corpus",
            str(tiny_corpus),
            "--output",
            str(tmp_path / "models"),
            "--report-path",
            str(tmp_path / "report.json"),
            "--val-fraction",
            "0.2",
            "--limit",
            "20",
            "--skip-nn",
        ]
    )
    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["n_train_decks"] + report["n_val_decks"] == 20


def test_split_corpus_deterministic() -> None:
    mod = _load_script_module()
    decks = [["A"], ["B"], ["C"], ["D"], ["E"]]
    train1, val1 = mod._split_corpus(decks, 0.4, seed=42)
    train2, val2 = mod._split_corpus(decks, 0.4, seed=42)
    assert train1 == train2
    assert val1 == val2
    assert len(train1) + len(val1) == 5
    # No overlap between train and val.
    assert not (set(map(tuple, train1)) & set(map(tuple, val1)))


def test_split_corpus_min_one_val() -> None:
    mod = _load_script_module()
    # 5 decks, val_fraction=0.01 → floor would be 0, but we floor to 1.
    train, val = mod._split_corpus(
        [["A"], ["B"], ["C"], ["D"], ["E"]], 0.01, seed=0
    )
    assert len(val) == 1
    assert len(train) == 4


def test_json_default_numpy_types() -> None:
    mod = _load_script_module()
    assert mod._json_default(np.int64(42)) == 42
    assert mod._json_default(np.float32(1.5)) == 1.5
    assert mod._json_default(np.array([1, 2, 3])) == [1, 2, 3]
    with pytest.raises(TypeError):
        mod._json_default(object())
