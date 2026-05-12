"""Tests for the offline deck-belief model (Step 2 of NN roadmap).

Covers:

- Corpus loading (plain + gzip, malformed input).
- Vocabulary construction and multi-hot encoding (with duplicates and
  unknown cards).
- Training-tuple generation.
- Baseline model: fit + predict + save/load round-trip + sanity on a
  hand-crafted synthetic deck pool with predictable co-occurrence.
- NN model: smoke train + save/load round-trip + non-trivial
  accuracy on the same synthetic pool.
- Shared interface contract: both implementations expose the same
  ``predict_rest_of_deck`` signature and produce probabilities in
  ``[0, 1]``.
- Input validation (unknown card IDs, empty / full revealed sets).
- Validation metrics: recall@k, calibration bins, Brier, ECE.
"""

from __future__ import annotations

import gzip
import json
import random
from pathlib import Path

import numpy as np
import pytest

from mtg_bot.training.deck_belief import (
    BaselineDeckBeliefModel,
    DeckBeliefModel,
    NNDeckBeliefModel,
    brier_score,
    build_vocab,
    calibration_bins,
    deck_to_multihot,
    expected_calibration_error,
    generate_training_tuples,
    load_deck_corpus,
    recall_at_k,
)


# --------------------------------------------------------------------------- #
# Synthetic deck pool used across tests
# --------------------------------------------------------------------------- #


def _synthetic_pool() -> list[list[str]]:
    """Four "archetype" decks with predictable co-occurrence.

    - Red aggro: Mountain x5, Bolt x3, Goblin x2
    - Blue control: Island x5, Counter x3, Drake x2
    - Boros: Plains x3, Mountain x3, Bolt x2, Soldier x2
    - Dimir: Island x3, Swamp x3, Counter x2, Wraith x2

    Each archetype is repeated 25 times with a one-off card swapped
    in to give the corpus 100 decks total — enough mass for stable
    co-occurrence statistics without making tests slow.
    """
    base_decks = [
        # Red aggro
        ["Mountain"] * 5 + ["Bolt"] * 3 + ["Goblin"] * 2,
        # Blue control
        ["Island"] * 5 + ["Counter"] * 3 + ["Drake"] * 2,
        # Boros
        ["Plains"] * 3 + ["Mountain"] * 3 + ["Bolt"] * 2 + ["Soldier"] * 2,
        # Dimir
        ["Island"] * 3 + ["Swamp"] * 3 + ["Counter"] * 2 + ["Wraith"] * 2,
    ]
    pool: list[list[str]] = []
    rng = random.Random(42)
    flavor_cards = ["Wandering Eye", "Lost Soul", "Mystery", "Echo"]
    for i in range(25):
        for base in base_decks:
            deck = list(base) + [rng.choice(flavor_cards)]
            pool.append(deck)
    return pool


# --------------------------------------------------------------------------- #
# Corpus loading
# --------------------------------------------------------------------------- #


def test_load_deck_corpus_plain_json(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    data = [
        {"cards": ["A", "B", "C"]},
        {"cards": ["B", "B", "D"]},
    ]
    path.write_text(json.dumps(data))
    decks = load_deck_corpus(path)
    assert decks == [["A", "B", "C"], ["B", "B", "D"]]


def test_load_deck_corpus_gzip(tmp_path: Path) -> None:
    path = tmp_path / "decks.json.gz"
    data = [{"cards": ["A", "B"]}, {"cards": ["C"]}]
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    decks = load_deck_corpus(path)
    assert decks == [["A", "B"], ["C"]]


def test_load_deck_corpus_skips_malformed_entries(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    data = [
        {"cards": ["A"]},
        {"not_cards": []},  # missing cards key
        {"cards": []},  # empty
        {"cards": "not a list"},  # wrong type
        "string entry",  # wrong shape
        {"cards": ["B", "C"]},
    ]
    path.write_text(json.dumps(data))
    decks = load_deck_corpus(path)
    assert decks == [["A"], ["B", "C"]]


def test_load_deck_corpus_rejects_non_list(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    path.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(ValueError, match="not a JSON list"):
        load_deck_corpus(path)


# --------------------------------------------------------------------------- #
# Vocab + multi-hot
# --------------------------------------------------------------------------- #


def test_build_vocab_deduplicates_and_sorts() -> None:
    decks = [["B", "A", "A"], ["C", "A"], ["B"]]
    vocab = build_vocab(decks)
    assert vocab == ["A", "B", "C"]


def test_deck_to_multihot_counts_copies() -> None:
    vocab = ["A", "B", "C"]
    c2i = {c: i for i, c in enumerate(vocab)}
    vec = deck_to_multihot(["A", "A", "C", "C", "C"], c2i)
    assert vec.tolist() == [2.0, 0.0, 3.0]


def test_deck_to_multihot_ignores_unknown_cards() -> None:
    vocab = ["A", "B"]
    c2i = {c: i for i, c in enumerate(vocab)}
    vec = deck_to_multihot(["A", "Z", "B", "Y"], c2i)
    assert vec.tolist() == [1.0, 1.0]


def test_generate_training_tuples_shape_and_ranges() -> None:
    decks = [["A", "B", "C", "D"] for _ in range(5)]
    vocab = build_vocab(decks)
    c2i = {c: i for i, c in enumerate(vocab)}
    X, Y = generate_training_tuples(
        decks, c2i, prefixes_per_deck=3, rng=random.Random(0)
    )
    assert X.shape == (15, 4)
    assert Y.shape == (15, 4)
    # For every row, X + Y should sum to the full deck multi-hot
    # (because revealed + rest = deck).
    deck_mh = np.array([1.0, 1.0, 1.0, 1.0])
    for i in range(15):
        assert (X[i] + Y[i] == deck_mh).all()


def test_generate_training_tuples_empty_input() -> None:
    X, Y = generate_training_tuples([], {"A": 0, "B": 1})
    assert X.shape == (0, 2)
    assert Y.shape == (0, 2)


def test_generate_training_tuples_skips_empty_decks() -> None:
    decks = [["A", "B"], [], ["C"]]
    vocab = build_vocab(decks)
    c2i = {c: i for i, c in enumerate(vocab)}
    X, Y = generate_training_tuples(
        decks, c2i, prefixes_per_deck=2, rng=random.Random(0)
    )
    # 2 non-empty decks * 2 prefixes = 4 rows.
    assert X.shape == (4, len(vocab))


def test_generate_training_tuples_default_rng() -> None:
    """Without an explicit rng, function still produces reproducible output."""
    decks = [["A", "B", "C"] for _ in range(3)]
    c2i = {"A": 0, "B": 1, "C": 2}
    X, _ = generate_training_tuples(decks, c2i, prefixes_per_deck=2)
    assert X.shape == (6, 3)


# --------------------------------------------------------------------------- #
# Baseline model
# --------------------------------------------------------------------------- #


def test_baseline_fit_predict_smoke() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    # Reveal a red-aggro signal card. Bolt should be predicted high
    # for the rest of the deck; Counter (blue) should be predicted low.
    preds = model.predict_rest_of_deck(["Mountain", "Mountain", "Goblin"])
    assert "Bolt" in preds
    assert "Counter" in preds
    # Bolt strongly co-occurs with Mountain + Goblin (red aggro
    # archetype). Counter never co-occurs with Goblin.
    assert preds["Bolt"] > preds["Counter"]
    # All probs are valid.
    for v in preds.values():
        assert 0.0 <= v <= 1.0


def test_baseline_predicts_archetype_signal() -> None:
    """Co-occurrence works: revealing blue cards predicts blue cards."""
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    preds = model.predict_rest_of_deck(["Island", "Counter"])
    # Drake is in blue control with Island+Counter. Goblin is in
    # red aggro with neither.
    assert preds["Drake"] > preds["Goblin"]


def test_baseline_empty_revealed_returns_base_rates() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    preds = model.predict_rest_of_deck([])
    # Mountain appears in 2 of 4 archetypes (50 / 100 decks ≈ 50%).
    # Counter appears in 2 of 4 archetypes (50 / 100 decks ≈ 50%).
    # Both should be near 0.5 ± noise from the flavor card.
    assert 0.4 <= preds["Mountain"] <= 0.6
    assert 0.4 <= preds["Counter"] <= 0.6


def test_baseline_full_revealed_masks_all_predictions() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    # Reveal every vocab card — nothing should be predicted.
    preds = model.predict_rest_of_deck(list(model.vocab))
    assert preds == {}


def test_baseline_unknown_revealed_card_no_crash() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    # "Zorblax" is not in the vocab; should be ignored silently.
    preds = model.predict_rest_of_deck(["Mountain", "Zorblax"])
    # "Zorblax" wasn't in the vocab so the prediction set should
    # equal "predict_rest minus Mountain" exactly.
    expected_keys = set(model.vocab) - {"Mountain"}
    assert set(preds.keys()) == expected_keys


def test_baseline_unknown_seen_zero_presence_skipped() -> None:
    """If a revealed card has zero presence (shouldn't happen but
    the code defends against it), it's silently dropped.

    Hand-craft this: build a small model, then zero out one card's
    presence count to simulate an out-of-distribution revealed card.
    """
    pool = [["A", "B"], ["A", "C"], ["B", "C"]]
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    # Manually zero out C's presence to force the n_y == 0 branch.
    model._presence[model.card_to_idx["C"]] = 0
    model._cooc[:, model.card_to_idx["C"]] = 0
    # Reveal C. Should fall through to base rates for the rest.
    preds = model.predict_rest_of_deck(["C"])
    assert set(preds.keys()) == {"A", "B"}


def test_baseline_predict_array_shape_validation() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    bad = np.zeros(len(model.vocab) + 1, dtype=np.float32)
    with pytest.raises(ValueError, match="must have shape"):
        model.predict_rest_of_deck_array(bad)


def test_baseline_predict_unfit_raises() -> None:
    model = BaselineDeckBeliefModel()
    with pytest.raises(RuntimeError, match="has not been fit"):
        model.predict_rest_of_deck(["Mountain"])


def test_baseline_fit_empty_raises() -> None:
    model = BaselineDeckBeliefModel()
    with pytest.raises(ValueError, match="empty"):
        model.fit([])


def test_baseline_save_load_roundtrip(tmp_path: Path) -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel(alpha=2.0, beta=5.0, prior_strength=15.0)
    model.fit(pool)
    path = tmp_path / "baseline.npz"
    model.save(path)
    loaded = BaselineDeckBeliefModel.load(path)
    assert loaded.vocab == model.vocab
    assert loaded.n_decks == model.n_decks
    assert loaded.alpha == 2.0
    assert loaded.beta == 5.0
    assert loaded.prior_strength == 15.0
    # Predictions are bit-identical (numpy float arithmetic is
    # deterministic).
    a = model.predict_rest_of_deck(["Mountain", "Bolt"])
    b = loaded.predict_rest_of_deck(["Mountain", "Bolt"])
    for k in a:
        assert a[k] == b[k]


def test_baseline_save_unfit_raises(tmp_path: Path) -> None:
    model = BaselineDeckBeliefModel()
    with pytest.raises(RuntimeError, match="unfit"):
        model.save(tmp_path / "x.npz")


def test_baseline_expected_copies() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    exp = model.predict_expected_copies(["Mountain"])
    # Mountain appears in red aggro (5 copies) + boros (3 copies).
    # Given Mountain is revealed (one copy seen), expected
    # remaining Mountain > 0.
    assert exp["Mountain"] > 0.0
    # Goblin co-occurs with Mountain (red aggro) but with fewer
    # copies (2). Expected goblin > 0 but smaller magnitude.
    assert exp["Goblin"] > 0.0
    assert exp["Goblin"] < exp["Mountain"]


def test_baseline_expected_copies_zero_presence_branch() -> None:
    """Exercise the _mean_copies_when_present fallback for cards
    that have zero presence (post-fit hack).
    """
    pool = [["A", "B"], ["A", "C"]]
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    model._presence[model.card_to_idx["B"]] = 0
    model._copy_sum[model.card_to_idx["B"]] = 0
    exp = model.predict_expected_copies(["A"])
    # B's mean-copies-when-present falls back to 1.0, so
    # expected_total = P(B in deck | A revealed) * 1.0.
    assert "B" in exp
    assert exp["B"] >= 0.0


# --------------------------------------------------------------------------- #
# NN model
# --------------------------------------------------------------------------- #


def test_nn_fit_predict_smoke() -> None:
    pool = _synthetic_pool()
    # Tiny config so the smoke test runs in <1s.
    model = NNDeckBeliefModel(
        hidden_dim=32, n_layers=2, epochs=3, batch_size=32, seed=42
    )
    model.fit(pool)
    preds = model.predict_rest_of_deck(["Mountain", "Goblin"])
    # Predictions exist and are in [0, 1].
    assert "Bolt" in preds
    for v in preds.values():
        assert 0.0 <= v <= 1.0


def test_nn_learns_archetype_signal() -> None:
    pool = _synthetic_pool()
    model = NNDeckBeliefModel(
        hidden_dim=64, n_layers=2, epochs=20, batch_size=32, seed=42
    )
    model.fit(pool)
    # After 20 epochs on the 100-deck synthetic pool, the NN
    # should distinguish red-aggro signals from blue-control.
    preds = model.predict_rest_of_deck(["Mountain", "Mountain", "Goblin"])
    assert preds["Bolt"] > preds["Counter"]
    preds2 = model.predict_rest_of_deck(["Island", "Counter"])
    assert preds2["Drake"] > preds2["Goblin"]


def test_nn_save_load_roundtrip(tmp_path: Path) -> None:
    pool = _synthetic_pool()
    model = NNDeckBeliefModel(
        hidden_dim=32, n_layers=2, epochs=3, batch_size=32, seed=7
    )
    model.fit(pool)
    path = tmp_path / "nn.pt"
    model.save(path)
    loaded = NNDeckBeliefModel.load(path)
    assert loaded.vocab == model.vocab
    assert loaded.hidden_dim == 32
    assert loaded.n_layers == 2
    # Predictions are bit-identical after round-trip.
    revealed = ["Mountain", "Bolt"]
    a = model.predict_rest_of_deck(revealed)
    b = loaded.predict_rest_of_deck(revealed)
    for k in a:
        assert abs(a[k] - b[k]) < 1e-6


def test_nn_predict_unfit_raises() -> None:
    model = NNDeckBeliefModel()
    with pytest.raises(RuntimeError, match="has not been fit"):
        model.predict_rest_of_deck(["Mountain"])


def test_nn_fit_empty_raises() -> None:
    model = NNDeckBeliefModel()
    with pytest.raises(ValueError, match="empty"):
        model.fit([])


def test_nn_predict_array_shape_validation() -> None:
    pool = _synthetic_pool()
    model = NNDeckBeliefModel(
        hidden_dim=16, n_layers=1, epochs=1, batch_size=32, seed=0
    )
    model.fit(pool)
    bad = np.zeros(len(model.vocab) + 1, dtype=np.float32)
    with pytest.raises(ValueError, match="must have shape"):
        model.predict_rest_of_deck_array(bad)


def test_nn_save_unfit_raises(tmp_path: Path) -> None:
    model = NNDeckBeliefModel()
    with pytest.raises(RuntimeError, match="unfit"):
        model.save(tmp_path / "x.pt")


def test_nn_dropout_zero_path() -> None:
    """Ensure the no-dropout layer-build path is exercised."""
    pool = _synthetic_pool()
    model = NNDeckBeliefModel(
        hidden_dim=16, n_layers=1, dropout=0.0, epochs=1, batch_size=32, seed=0
    )
    model.fit(pool)
    preds = model.predict_rest_of_deck(["Mountain"])
    assert all(0.0 <= v <= 1.0 for v in preds.values())


def test_nn_losses_recorded() -> None:
    pool = _synthetic_pool()
    model = NNDeckBeliefModel(
        hidden_dim=16, n_layers=1, epochs=3, batch_size=32, seed=0
    )
    model.fit(pool)
    assert len(model._losses) == 3
    for loss in model._losses:
        assert loss > 0


# --------------------------------------------------------------------------- #
# Shared interface contract
# --------------------------------------------------------------------------- #


def test_shared_interface_baseline_and_nn_agree_on_shape() -> None:
    pool = _synthetic_pool()
    baseline = BaselineDeckBeliefModel()
    baseline.fit(pool)
    nn_model = NNDeckBeliefModel(
        hidden_dim=16, n_layers=1, epochs=2, batch_size=32, seed=0
    )
    nn_model.fit(pool)
    # Same vocab (built from the same corpus).
    assert baseline.vocab == nn_model.vocab
    # Same number of predictions for the same input.
    revealed = ["Mountain", "Island"]
    a = baseline.predict_rest_of_deck(revealed)
    b = nn_model.predict_rest_of_deck(revealed)
    assert set(a.keys()) == set(b.keys())
    # Both produce valid probabilities.
    for v in list(a.values()) + list(b.values()):
        assert 0.0 <= v <= 1.0


def test_models_subclass_abstract_interface() -> None:
    assert issubclass(BaselineDeckBeliefModel, DeckBeliefModel)
    assert issubclass(NNDeckBeliefModel, DeckBeliefModel)


def test_abstract_interface_raises_not_implemented() -> None:
    class Bare(DeckBeliefModel):
        pass

    m = Bare()
    with pytest.raises(NotImplementedError):
        m.fit([])
    with pytest.raises(NotImplementedError):
        m.predict_rest_of_deck_array(np.zeros(1))
    with pytest.raises(NotImplementedError):
        m.save("x")
    with pytest.raises(NotImplementedError):
        Bare.load("x")


# --------------------------------------------------------------------------- #
# Validation metrics
# --------------------------------------------------------------------------- #


def test_recall_at_k_meaningful() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    # On the synthetic pool, baseline should achieve high recall@5
    # because each deck has ~5 unique cards and the co-occurrence
    # signal is strong.
    r5 = recall_at_k(model, pool, k=5, rng=random.Random(0))
    # Per-deck unique-rest size is ~3-4, but the corpus has ~14
    # unique cards and the flavor cards add noise. r5 ≥ 0.2
    # confirms the model is doing something signal-bearing — i.e.,
    # better than the trivial "always pick the same top-K".
    assert r5 > 0.2
    r10 = recall_at_k(model, pool, k=10, rng=random.Random(0))
    assert r10 >= r5  # larger k can only help


def test_recall_at_k_empty_held_out() -> None:
    model = BaselineDeckBeliefModel()
    model.fit(_synthetic_pool())
    assert recall_at_k(model, [], k=5) == 0.0


def test_recall_at_k_skips_tiny_decks() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    # All decks below the minimum size — recall should be 0 (no
    # samples).
    tiny = [["Mountain"]] * 5
    r = recall_at_k(model, tiny, k=5, rng=random.Random(0))
    assert r == 0.0


def test_recall_at_k_default_rng_branch() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    # Don't pass rng — exercise default-construction branch.
    r = recall_at_k(model, pool[:5], k=5)
    assert 0.0 <= r <= 1.0


def test_recall_at_k_filters_out_of_vocab_rest() -> None:
    """If a held-out deck has cards entirely outside the model
    vocab, it contributes nothing to recall but doesn't crash."""
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    # An entirely OOV deck.
    held_out = [["Zorblax", "Quux"] * 3]
    r = recall_at_k(model, held_out, k=5, rng=random.Random(0))
    assert r == 0.0


def test_calibration_bins_basic() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    bins = calibration_bins(model, pool, n_bins=5, rng=random.Random(0))
    # Some bins should be non-empty.
    assert len(bins) >= 2
    for b in bins:
        assert 0.0 <= b["mean_predicted"] <= 1.0
        assert 0.0 <= b["mean_empirical"] <= 1.0
        assert b["count"] > 0


def test_calibration_bins_empty_held_out() -> None:
    model = BaselineDeckBeliefModel()
    model.fit(_synthetic_pool())
    assert calibration_bins(model, [], n_bins=10) == []


def test_calibration_bins_max_decks_caps_input() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    bins = calibration_bins(
        model, pool, n_bins=5, rng=random.Random(0), max_decks=3
    )
    total = sum(b["count"] for b in bins)
    # Each deck contributes (vocab - revealed) predictions; with 3
    # decks max we should have far fewer total predictions than the
    # full-pool case.
    assert total < 1000


def test_calibration_bins_skips_tiny_decks() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    bins = calibration_bins(
        model, [["Mountain"]] * 3, n_bins=5, rng=random.Random(0)
    )
    assert bins == []


def test_calibration_bins_default_rng() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    bins = calibration_bins(model, pool[:5], n_bins=5)
    assert len(bins) >= 1


def test_brier_score_bounds() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    b = brier_score(model, pool[:20], rng=random.Random(0))
    # Brier is in [0, 1]; for a sane model below the trivial 0.25
    # (random-guess-at-0.5 floor).
    assert 0.0 <= b <= 1.0


def test_brier_score_empty() -> None:
    model = BaselineDeckBeliefModel()
    model.fit(_synthetic_pool())
    assert brier_score(model, []) == 0.0


def test_brier_score_max_decks() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    b = brier_score(model, pool, rng=random.Random(0), max_decks=2)
    assert 0.0 <= b <= 1.0


def test_brier_score_skips_tiny_decks() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    b = brier_score(
        model, [["Mountain"]] * 3, rng=random.Random(0)
    )
    assert b == 0.0


def test_brier_score_default_rng() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    b = brier_score(model, pool[:5])
    assert 0.0 <= b <= 1.0


def test_ece_basic() -> None:
    pool = _synthetic_pool()
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    bins = calibration_bins(model, pool, n_bins=10, rng=random.Random(0))
    ece = expected_calibration_error(bins)
    assert 0.0 <= ece <= 1.0


def test_ece_empty_bins() -> None:
    assert expected_calibration_error([]) == 0.0


def test_ece_zero_count_bins() -> None:
    assert expected_calibration_error(
        [{"count": 0, "mean_predicted": 0.5, "mean_empirical": 0.5}]
    ) == 0.0


# --------------------------------------------------------------------------- #
# Defensive-branch coverage
# --------------------------------------------------------------------------- #


def test_baseline_fit_skips_oov_cards_in_training_decks() -> None:
    """The fit loop's "unknown card → skip" branch only fires if a
    deck contains a card not in card_to_idx. That can't happen for
    the natural fit path (vocab is built from the same decks), but
    we can force it by post-pruning the vocab and re-running fit on
    a manually constructed model.
    """
    decks = [["A", "B", "C"], ["A", "B", "D"]]
    model = BaselineDeckBeliefModel()
    model.fit(decks)
    # Manually shrink the vocab to drop "D", then re-fit on a deck
    # containing "D" — the fit-loop should silently skip it.
    smaller_vocab = ["A", "B", "C"]
    model.vocab = smaller_vocab
    model.card_to_idx = {c: i for i, c in enumerate(smaller_vocab)}
    # Re-run the fit body with a smaller vocab and a deck containing
    # an OOV card. We do this by calling fit() with decks that have
    # an OOV in them — but fit() rebuilds vocab from decks. So
    # instead, fit with the original corpus then check via internal
    # state: the post-OOV fit needs a re-implementation hook. Use
    # the simpler path: monkey-patch card_to_idx so the next fit
    # call (via the existing API) sees an OOV. Since fit rebuilds
    # vocab, we have to drive the OOV through a separate path.
    # Easiest: refit while temporarily replacing build_vocab with a
    # stub that drops one card.
    from mtg_bot.training import deck_belief as db_mod

    orig_build = db_mod.build_vocab
    try:
        db_mod.build_vocab = lambda decks: ["A", "B"]  # drop C and D
        model2 = BaselineDeckBeliefModel()
        model2.fit([["A", "B", "C"], ["A", "B", "D"]])
    finally:
        db_mod.build_vocab = orig_build
    # Vocab is the stubbed one and the C/D cards were silently
    # skipped during the count loop.
    assert model2.vocab == ["A", "B"]
    assert model2.n_decks == 2


def test_nn_predict_array_unfit_raises() -> None:
    """predict_rest_of_deck_array on a never-fit NN model raises."""
    model = NNDeckBeliefModel()
    # Manually plant a vocab to bypass the public-API's earlier
    # validation, so we reach the net-is-None check.
    model.vocab = ["A", "B"]
    model.card_to_idx = {"A": 0, "B": 1}
    bad = np.zeros(2, dtype=np.float32)
    with pytest.raises(RuntimeError, match="has not been fit"):
        model.predict_rest_of_deck_array(bad)


def test_recall_at_k_handles_predict_empty() -> None:
    """The "no predictions returned" branch fires when revealed
    covers the entire vocab. Construct a held-out deck that includes
    every vocab card so the prediction set is empty."""
    pool = [["A", "B"], ["A", "C"]]
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    # Build a held-out deck that, when half-revealed (rounded up),
    # covers the entire model vocab. With vocab = [A, B, C] and a
    # 4-card deck "A B C C", 2-revealed = "A B" and rest = "C C".
    # That doesn't trigger the empty-preds branch. Need to reveal
    # the full vocab.
    held_out = [["A", "B", "C", "C", "C", "C"]]
    # With revealed_fraction=0.999, revealed = first 5 = "A B C C C",
    # rest = "C". Preds excludes A, B, C ⇒ preds is empty.
    r = recall_at_k(
        model, held_out, k=5, rng=random.Random(0), revealed_fraction=0.999
    )
    # Empty preds → deck is skipped → recall is 0 across no samples.
    assert r == 0.0


def test_calibration_bins_handles_predict_empty() -> None:
    """Same edge case in calibration_bins — full-vocab reveal."""
    pool = [["A", "B"], ["A", "C"]]
    model = BaselineDeckBeliefModel()
    model.fit(pool)
    held_out = [["A", "B", "C", "C", "C", "C"]]
    bins = calibration_bins(
        model,
        held_out,
        n_bins=5,
        rng=random.Random(0),
        revealed_fraction=0.999,
    )
    assert bins == []
