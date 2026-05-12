"""Offline deck-belief model — supervised deck completion.

This module implements **Step 2** of the NN representation roadmap
(see ``docs/NN_REPRESENTATION_ROADMAP.md``). Given a multi-hot vector
of cards the opponent has revealed during play, predict a probability
distribution over which other cards are in the rest of their deck.

The model is fully offline. The training signal is 17lands decklists
in ``data/17lands/eoe_decks.json.gz``: for each decklist we sample
prefixes of varying sizes ``k`` as "revealed", with the remaining
``len(deck) - k`` cards as "rest of deck". This is the same pattern as
poker range tracking — Bayesian posterior over a fixed but unknown
private deck given a sequence of observations.

The deck-belief output feeds PIMC determinization sampling (importance
sampling over opponent worlds, ReBeL / DeepStack pattern), but the
PIMC integration is **out of scope of this module**. This file only
provides the model + I/O + training-tuple generator.

Two implementations sharing the same input/output contract:

- :class:`BaselineDeckBeliefModel` — co-occurrence counts with
  Beta-Binomial Bayesian smoothing. Pure numpy, no torch. Functional
  on its own and serves as a sanity floor for the NN. The principled
  baseline:

      P(card X in rest | revealed) =
          (alpha + #decks containing X among decks matching revealed)
          / (alpha + beta + #decks matching revealed)

  where "matching revealed" is co-occurrence on each revealed card.
  We implement this as a Bayesian update over the marginal base rate
  using a per-card Beta(alpha_x, beta_x) prior derived from the
  global per-card base rate, then a likelihood from co-occurrence
  statistics.

- :class:`NNDeckBeliefModel` — a small MLP. Input: multi-hot[vocab]
  revealed vector. Hidden: 128-256 dim, ReLU, 1-2 layers. Output:
  vocab-dim with sigmoid (per-card independent Bernoulli). Trained
  with masked binary cross-entropy that ignores the revealed slice
  (we never predict revealed cards as "rest of deck").

Both implementations expose:

- ``fit(deck_corpus)`` — build the vocabulary and learn from a list
  of decks (each a list of printing-id strings, may contain
  duplicates).
- ``predict_rest_of_deck(revealed)`` — return ``dict[card_id, prob]``
  for the unrevealed cards (or, for the multiset view, expected
  copies remaining).
- ``save(path)`` / ``load(path)`` — round-trip the trained model.

Vocabulary is built from observed cards in the training corpus — we
don't waste output dimensions on cards that never appear in any
decklist.

The 17lands deck format is a list of dicts with keys ``draft_id``,
``build_index``, ``cards`` (40-card list, may have duplicates),
``main_colors``, ``splash_colors``, ``total_games``, ``total_wins``.
Cards are identified by their printing name (a string, e.g.
``"Atmospheric Greenhouse"``). The vocabulary in this module is over
these name strings; the caller is responsible for mapping engine
``printing.id`` values to names if integrating with the live engine
later.
"""

from __future__ import annotations

import gzip
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np


# Card-identity type alias. Today the 17lands corpus uses names, but
# the module is agnostic to the string content — any stable string ID
# works.
CardId = str


# --------------------------------------------------------------------------- #
# Corpus loading + training-tuple generation
# --------------------------------------------------------------------------- #


def load_deck_corpus(path: str | Path) -> list[list[CardId]]:
    """Load the 17lands EOE decks file into a list of card lists.

    Each entry is the ``cards`` field of one deck (40 cards, may
    contain duplicates).

    Supports plain JSON and gzip-compressed JSON, picked by file
    extension.
    """
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        with open(path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(
            f"deck corpus at {path!s} is not a JSON list; got {type(data).__name__}"
        )
    decks: list[list[CardId]] = []
    for entry in data:
        cards = entry.get("cards") if isinstance(entry, dict) else None
        if not isinstance(cards, list) or not cards:
            continue
        decks.append([str(c) for c in cards])
    return decks


def build_vocab(decks: Sequence[Sequence[CardId]]) -> list[CardId]:
    """Build a deterministic sorted vocabulary from observed cards.

    Sorted by name so save/load round-trips have stable indexing.
    """
    seen: set[CardId] = set()
    for deck in decks:
        seen.update(deck)
    return sorted(seen)


def deck_to_multihot(
    deck: Sequence[CardId],
    card_to_idx: dict[CardId, int],
) -> np.ndarray:
    """Return a multi-hot vector with copy counts at each card's index.

    Unknown cards (not in ``card_to_idx``) are silently dropped. The
    output is shape ``(vocab_size,)`` with dtype float32 so it can be
    used directly as torch input.
    """
    vec = np.zeros(len(card_to_idx), dtype=np.float32)
    for card in deck:
        idx = card_to_idx.get(card)
        if idx is not None:
            vec[idx] += 1.0
    return vec


def generate_training_tuples(
    decks: Sequence[Sequence[CardId]],
    card_to_idx: dict[CardId, int],
    *,
    prefixes_per_deck: int = 10,
    rng: Optional[random.Random] = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample (revealed, rest) multi-hot pairs from each decklist.

    For each deck:

    - Shuffle the card list.
    - Sample ``prefixes_per_deck`` prefix sizes uniformly in
      ``{0, 1, ..., len(deck) - 1}``. Prefix size 0 means "nothing
      revealed yet", which the model must still handle.
    - The first ``k`` cards become the "revealed" multi-hot, the rest
      become the "rest of deck" multi-hot.

    Returns:

    - ``X`` of shape ``(n_tuples, vocab_size)`` — revealed multi-hot.
    - ``Y`` of shape ``(n_tuples, vocab_size)`` — rest-of-deck
      multi-hot. Values are copy counts (0, 1, 2, ...).
    """
    if rng is None:
        rng = random.Random(0)
    vocab_size = len(card_to_idx)
    rows: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    for deck in decks:
        deck_len = len(deck)
        if deck_len == 0:
            continue
        shuffled = list(deck)
        rng.shuffle(shuffled)
        for _ in range(prefixes_per_deck):
            k = rng.randint(0, deck_len - 1)
            revealed = shuffled[:k]
            rest = shuffled[k:]
            rows.append(deck_to_multihot(revealed, card_to_idx))
            targets.append(deck_to_multihot(rest, card_to_idx))
    if not rows:
        return (
            np.zeros((0, vocab_size), dtype=np.float32),
            np.zeros((0, vocab_size), dtype=np.float32),
        )
    return np.stack(rows), np.stack(targets)


# --------------------------------------------------------------------------- #
# Model interface
# --------------------------------------------------------------------------- #


class DeckBeliefModel:
    """Abstract interface for deck-belief models.

    Subclasses must implement :meth:`fit`,
    :meth:`predict_rest_of_deck_array`, :meth:`save`, and the
    classmethod :meth:`load`. The shared interface gives both the
    baseline and the NN model the same contract so downstream callers
    can swap them without code changes.
    """

    vocab: list[CardId]
    card_to_idx: dict[CardId, int]

    def predict_rest_of_deck(
        self,
        revealed: Sequence[CardId],
    ) -> dict[CardId, float]:
        """Predict P(card in rest of deck) for every unrevealed card.

        Cards in the ``revealed`` list are masked out of the output
        (we never predict revealed cards as "rest"). Unknown cards in
        ``revealed`` are silently dropped — they don't affect the
        prediction because they carry no information the model was
        trained on.

        Returns a dict keyed by card id, restricted to the model's
        vocabulary minus the revealed slice. Probabilities are
        clipped to ``[0, 1]``.
        """
        self._validate_revealed(revealed)
        revealed_idx = {self.card_to_idx[c] for c in revealed if c in self.card_to_idx}
        revealed_mh = deck_to_multihot(revealed, self.card_to_idx)
        probs = self.predict_rest_of_deck_array(revealed_mh)
        out: dict[CardId, float] = {}
        for card, idx in self.card_to_idx.items():
            if idx in revealed_idx:
                continue
            out[card] = float(np.clip(probs[idx], 0.0, 1.0))
        return out

    # Subclasses implement these.

    def fit(self, decks: Sequence[Sequence[CardId]]) -> None:
        raise NotImplementedError

    def predict_rest_of_deck_array(self, revealed_mh: np.ndarray) -> np.ndarray:
        """Return per-card P(in rest of deck) over the full vocab.

        Shape: ``(vocab_size,)``. Values may be unclipped — the
        public :meth:`predict_rest_of_deck` clips at the dict level.
        Revealed cards' slots in the input vector are NOT masked
        here; the caller (or :meth:`predict_rest_of_deck`) masks
        revealed cards out of the user-facing output.
        """
        raise NotImplementedError

    def save(self, path: str | Path) -> None:
        raise NotImplementedError

    @classmethod
    def load(cls, path: str | Path) -> "DeckBeliefModel":
        raise NotImplementedError

    # Shared helpers.

    def _validate_revealed(self, revealed: Sequence[CardId]) -> None:
        if (
            not hasattr(self, "card_to_idx")
            or self.card_to_idx is None
            or len(self.card_to_idx) == 0
        ):
            raise RuntimeError(
                "model has not been fit; call fit() or load() before predict"
            )


# --------------------------------------------------------------------------- #
# Baseline: co-occurrence + Beta-Binomial smoothing
# --------------------------------------------------------------------------- #


@dataclass
class BaselineDeckBeliefModel(DeckBeliefModel):
    """Baseline model: per-card base rates with Bayesian update.

    Math:

    - Let :math:`b_x = P(card x in a random deck)` be the empirical
      base rate (deck-level — number of decks containing at least
      one copy of x divided by total decks). This is the marginal.
    - Let :math:`m_x = E[copies of x | x in deck]` be the mean copy
      count conditioned on presence. This lifts the model from "in
      deck" (Bernoulli) to "expected copies remaining" (Poisson-ish).
    - Co-occurrence: for each pair of cards ``(x, y)``,
      :math:`p(x | y) = ` (decks containing both x and y) / (decks
      containing y), with **Beta(alpha, beta) smoothing** so a single
      observation of ``y`` doesn't push ``p(x | y)`` to 0 or 1:

        :math:`p(x | y) \\approx (n_{xy} + \\alpha) / (n_y + \\alpha + \\beta)`

      with the prior pulling toward the marginal base rate (so a
      card y we've never seen with x falls back to ``b_x``).

    - For multi-card revealed ``Y = {y_1, ..., y_k}``, we combine the
      per-card conditionals in log-odds space with a small fixed
      weight per observation (Naive-Bayes-ish), which avoids the
      degenerate "every revealed card pulls toward a single deck's
      idiosyncrasies" failure mode.

      Specifically: ``log_odds(x | Y) = log_odds_prior(x) + sum_y
      [log_odds(x | y) - log_odds_prior(x)] * weight``.

      With ``weight = 1 / k`` this is just averaging the per-card
      log-odds shifts, which keeps the posterior in a sensible
      range even when many cards are revealed.

    Expected-copies prediction: ``E[copies of x in rest] =
    P(x in deck | Y) * m_x - copies_already_revealed(x)``,
    clipped to ``[0, deck_size]``. The default behavior of
    :meth:`predict_rest_of_deck` returns the **probability that at
    least one more copy of x is in the rest of the deck**, which is
    the natural Bernoulli interpretation. For expected-copies, use
    :meth:`predict_expected_copies`.

    Parameters
    ----------
    alpha, beta
        Beta prior hyperparameters for co-occurrence smoothing.
        ``alpha=1, beta=1`` is Laplace (uniform). For the EoE corpus
        we use a data-driven prior matched to the global base rate
        with a strength of ``prior_strength`` virtual observations.
    prior_strength
        Effective sample size of the per-card prior. Higher = more
        smoothing toward the marginal.
    """

    alpha: float = 1.0
    beta: float = 10.0
    prior_strength: float = 10.0

    def __post_init__(self) -> None:
        # Filled in by fit().
        self.vocab: list[CardId] = []
        self.card_to_idx: dict[CardId, int] = {}
        self.n_decks: int = 0
        # Per-card deck-level presence count (1 if in deck, 0 otherwise).
        self._presence: Optional[np.ndarray] = None  # shape (V,), int
        # Per-card sum of copies across all decks (for mean copies | present).
        self._copy_sum: Optional[np.ndarray] = None  # shape (V,), int
        # Co-presence matrix: cooc[i, j] = # decks containing both card i and card j.
        self._cooc: Optional[np.ndarray] = None  # shape (V, V), int32

    # ---- training ----

    def fit(self, decks: Sequence[Sequence[CardId]]) -> None:
        """Compute co-occurrence statistics + marginal base rates."""
        if not decks:
            raise ValueError("cannot fit on an empty deck corpus")
        self.vocab = build_vocab(decks)
        self.card_to_idx = {c: i for i, c in enumerate(self.vocab)}
        V = len(self.vocab)
        self.n_decks = len(decks)

        presence = np.zeros(V, dtype=np.int64)
        copy_sum = np.zeros(V, dtype=np.int64)
        # V can be up to ~300 for EoE; V*V = ~90k int32 = ~360KB — fine.
        cooc = np.zeros((V, V), dtype=np.int64)

        for deck in decks:
            counts = np.zeros(V, dtype=np.int64)
            for card in deck:
                idx = self.card_to_idx.get(card)
                if idx is None:
                    continue
                counts[idx] += 1
            present = (counts > 0).astype(np.int64)
            presence += present
            copy_sum += counts
            # Outer product of presence with itself = co-occurrence
            # (1 per deck containing both). This double-counts the
            # diagonal as `presence` itself, which is the right
            # convention: cooc[i, i] = n_decks containing card i.
            cooc += np.outer(present, present)

        self._presence = presence
        self._copy_sum = copy_sum
        self._cooc = cooc

    # ---- prediction ----

    def _base_rate(self) -> np.ndarray:
        """Per-card P(in random deck), shape (V,)."""
        assert self._presence is not None
        return self._presence.astype(np.float64) / max(1, self.n_decks)

    def _mean_copies_when_present(self) -> np.ndarray:
        """Per-card E[copies | in deck], shape (V,)."""
        assert self._presence is not None and self._copy_sum is not None
        out = np.zeros_like(self._presence, dtype=np.float64)
        nonzero = self._presence > 0
        out[nonzero] = (
            self._copy_sum[nonzero].astype(np.float64)
            / self._presence[nonzero].astype(np.float64)
        )
        # For cards never seen present, fall back to 1.0 — this
        # branch is only used if a revealed card somehow has zero
        # presence in training, which doesn't happen in practice
        # because vocab is built from the same corpus.
        out[~nonzero] = 1.0
        return out

    def _conditional_in_deck(
        self,
        revealed_idx: Sequence[int],
    ) -> np.ndarray:
        """P(card x in deck | each revealed card seen at least once).

        Returns shape ``(V,)``. Uses log-odds averaging across the
        revealed cards to avoid overconfident posteriors.
        """
        assert self._presence is not None and self._cooc is not None
        base = self._base_rate()
        # Clip base rate so log-odds is finite even for unseen
        # cards. Adding 1/(2N) and 1-1/(2N) is a standard "Laplace
        # smoothing for the marginal" trick.
        eps = 0.5 / max(1, self.n_decks)
        base_clipped = np.clip(base, eps, 1.0 - eps)
        prior_logodds = np.log(base_clipped) - np.log(1.0 - base_clipped)

        if not revealed_idx:
            return base.astype(np.float64)

        # For each revealed card y, compute P(x | y) with Beta
        # smoothing. n_y = presence[y], n_xy = cooc[x, y]. The
        # smoothed posterior is
        #     (n_xy + alpha_eff) / (n_y + alpha_eff + beta_eff)
        # where the prior (alpha_eff / (alpha_eff + beta_eff))
        # equals the marginal base rate for x, with
        # ``prior_strength`` virtual observations.
        log_odds = prior_logodds.copy()
        k = len(revealed_idx)
        weight = 1.0 / k

        for y in revealed_idx:
            n_y = int(self._presence[y])
            if n_y == 0:
                # Unseen revealed card — no information, skip.
                continue
            n_xy = self._cooc[:, y].astype(np.float64)  # shape (V,)
            # Prior in alpha-beta form, matching the global base rate.
            alpha_eff = base * self.prior_strength + self.alpha
            beta_eff = (1.0 - base) * self.prior_strength + self.beta
            p_x_given_y = (n_xy + alpha_eff) / (
                n_y + alpha_eff + beta_eff
            )
            p_x_given_y = np.clip(p_x_given_y, eps, 1.0 - eps)
            lo_given_y = np.log(p_x_given_y) - np.log(1.0 - p_x_given_y)
            log_odds = log_odds + (lo_given_y - prior_logodds) * weight

        # Convert back to probability.
        probs = 1.0 / (1.0 + np.exp(-log_odds))
        return probs

    def predict_rest_of_deck_array(self, revealed_mh: np.ndarray) -> np.ndarray:
        """Per-card P(at least one more copy in rest), shape (V,)."""
        if revealed_mh.shape != (len(self.vocab),):
            raise ValueError(
                f"revealed multi-hot must have shape ({len(self.vocab)},); "
                f"got {revealed_mh.shape}"
            )
        revealed_idx = [int(i) for i in np.flatnonzero(revealed_mh > 0)]
        return self._conditional_in_deck(revealed_idx)

    def predict_expected_copies(
        self,
        revealed: Sequence[CardId],
    ) -> dict[CardId, float]:
        """Expected copies of each card remaining in the rest of deck.

        ``E[copies in rest | revealed] = P(x in deck | revealed) *
        E[copies | x in deck] - copies_already_revealed(x)``, clipped
        to ``[0, infinity)``. Includes revealed cards (since you can
        have multiple copies of the same common).
        """
        self._validate_revealed(revealed)
        revealed_mh = deck_to_multihot(revealed, self.card_to_idx)
        in_deck = self.predict_rest_of_deck_array(revealed_mh)
        mean_copies = self._mean_copies_when_present()
        expected_total = in_deck * mean_copies
        expected_rest = np.clip(expected_total - revealed_mh, 0.0, None)
        return {
            card: float(expected_rest[idx])
            for card, idx in self.card_to_idx.items()
        }

    # ---- I/O ----

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._presence is None:
            raise RuntimeError("cannot save an unfit model")
        np.savez_compressed(
            path,
            vocab=np.array(self.vocab, dtype=object),
            presence=self._presence,
            copy_sum=self._copy_sum,
            cooc=self._cooc,
            n_decks=np.int64(self.n_decks),
            alpha=np.float64(self.alpha),
            beta=np.float64(self.beta),
            prior_strength=np.float64(self.prior_strength),
        )

    @classmethod
    def load(cls, path: str | Path) -> "BaselineDeckBeliefModel":
        data = np.load(path, allow_pickle=True)
        model = cls(
            alpha=float(data["alpha"]),
            beta=float(data["beta"]),
            prior_strength=float(data["prior_strength"]),
        )
        model.vocab = [str(c) for c in data["vocab"].tolist()]
        model.card_to_idx = {c: i for i, c in enumerate(model.vocab)}
        model.n_decks = int(data["n_decks"])
        model._presence = data["presence"]
        model._copy_sum = data["copy_sum"]
        model._cooc = data["cooc"]
        return model


# --------------------------------------------------------------------------- #
# NN: small MLP with sigmoid per-card head
# --------------------------------------------------------------------------- #


@dataclass
class NNDeckBeliefModel(DeckBeliefModel):
    """Small MLP deck-belief model.

    Architecture:

    - Input: multi-hot[vocab] of revealed cards (copy counts, float).
    - Hidden: ``hidden_dim`` units, ReLU, ``n_layers`` layers.
    - Output: vocab-dim logits, applied sigmoid for per-card
      P(card in rest of deck) — independent Bernoulli per card.

    Training:

    - Masked binary cross-entropy: revealed slots are zeroed out of
      the loss because the target there is "more copies" not "in
      deck", which the Bernoulli framing doesn't capture cleanly.
    - Targets are derived from the rest-of-deck multi-hot: any
      positive copy count clamps to 1 (presence of at least one
      copy remaining).
    - Adam optimizer, configurable lr / batch size / epochs.
    - Optional device override; defaults to CPU because the model is
      tiny and the spawn-time overhead of moving to CUDA for one
      training run isn't worth it. For longer training the caller
      can pass ``device="cuda"``.

    The vocabulary is set in :meth:`fit` and frozen afterwards;
    swapping vocab requires retraining.
    """

    hidden_dim: int = 256
    n_layers: int = 2
    dropout: float = 0.1
    lr: float = 1e-3
    batch_size: int = 256
    epochs: int = 5
    weight_decay: float = 1e-5
    prefixes_per_deck: int = 10
    device: str = "cpu"
    seed: int = 0
    # Internal training-loss history, set by fit().
    _losses: list[float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.vocab: list[CardId] = []
        self.card_to_idx: dict[CardId, int] = {}
        self._net = None  # torch nn.Module, set in fit/load
        self._losses = []

    # ---- training ----

    def _build_net(self, vocab_size: int):
        import torch
        from torch import nn

        layers: list = []
        prev = vocab_size
        for _ in range(self.n_layers):
            layers.append(nn.Linear(prev, self.hidden_dim))
            layers.append(nn.ReLU())
            if self.dropout > 0:
                layers.append(nn.Dropout(self.dropout))
            prev = self.hidden_dim
        layers.append(nn.Linear(prev, vocab_size))
        return nn.Sequential(*layers)

    def fit(self, decks: Sequence[Sequence[CardId]]) -> None:
        """Train the MLP on multi-hot (revealed, rest) pairs."""
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, TensorDataset

        if not decks:
            raise ValueError("cannot fit on an empty deck corpus")

        self.vocab = build_vocab(decks)
        self.card_to_idx = {c: i for i, c in enumerate(self.vocab)}
        V = len(self.vocab)

        rng = random.Random(self.seed)
        X, Y = generate_training_tuples(
            decks,
            self.card_to_idx,
            prefixes_per_deck=self.prefixes_per_deck,
            rng=rng,
        )
        # Bernoulli target: at least one copy remaining.
        Y_bin = (Y > 0).astype(np.float32)
        # Revealed mask: 1 where the card was revealed (so we don't
        # supervise on that output dim — it's "in rest" by
        # construction, which is dominated by deck-construction
        # combinatorics, not co-occurrence). Loss is summed over the
        # complement.
        mask = (X == 0).astype(np.float32)

        torch.manual_seed(self.seed)
        device = torch.device(self.device)
        self._net = self._build_net(V).to(device)
        opt = torch.optim.Adam(
            self._net.parameters(),
            lr=self.lr,
            weight_decay=self.weight_decay,
        )

        X_t = torch.from_numpy(X)
        Y_t = torch.from_numpy(Y_bin)
        M_t = torch.from_numpy(mask)
        loader = DataLoader(
            TensorDataset(X_t, Y_t, M_t),
            batch_size=self.batch_size,
            shuffle=True,
            drop_last=False,
        )

        loss_fn = nn.BCEWithLogitsLoss(reduction="none")
        self._losses = []
        for _epoch in range(self.epochs):
            epoch_loss = 0.0
            n_batches = 0
            for xb, yb, mb in loader:
                xb = xb.to(device)
                yb = yb.to(device)
                mb = mb.to(device)
                logits = self._net(xb)
                per_elem = loss_fn(logits, yb)
                # Mean over unmasked elements.
                denom = mb.sum().clamp(min=1.0)
                loss = (per_elem * mb).sum() / denom
                opt.zero_grad()
                loss.backward()
                opt.step()
                epoch_loss += float(loss.detach().cpu())
                n_batches += 1
            self._losses.append(epoch_loss / max(1, n_batches))
        # Put the network in eval mode so dropout is disabled for
        # subsequent predict_rest_of_deck calls (and so save/load
        # round-trips reproduce predictions exactly).
        self._net.eval()

    # ---- prediction ----

    def predict_rest_of_deck_array(self, revealed_mh: np.ndarray) -> np.ndarray:
        import torch

        if self._net is None:
            raise RuntimeError(
                "model has not been fit; call fit() or load() before predict"
            )
        if revealed_mh.shape != (len(self.vocab),):
            raise ValueError(
                f"revealed multi-hot must have shape ({len(self.vocab)},); "
                f"got {revealed_mh.shape}"
            )
        device = next(self._net.parameters()).device
        x = torch.from_numpy(revealed_mh.astype(np.float32)).unsqueeze(0).to(device)
        with torch.no_grad():
            logits = self._net(x)
            probs = torch.sigmoid(logits).cpu().numpy()[0]
        return probs.astype(np.float64)

    # ---- I/O ----

    def save(self, path: str | Path) -> None:
        import torch

        if self._net is None:
            raise RuntimeError("cannot save an unfit model")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "vocab": self.vocab,
                "state_dict": self._net.state_dict(),
                "config": {
                    "hidden_dim": self.hidden_dim,
                    "n_layers": self.n_layers,
                    "dropout": self.dropout,
                    "lr": self.lr,
                    "batch_size": self.batch_size,
                    "epochs": self.epochs,
                    "weight_decay": self.weight_decay,
                    "prefixes_per_deck": self.prefixes_per_deck,
                    "seed": self.seed,
                },
                "losses": self._losses,
            },
            path,
        )

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        device: str = "cpu",
    ) -> "NNDeckBeliefModel":
        import torch

        ckpt = torch.load(path, map_location=device, weights_only=False)
        cfg = ckpt["config"]
        model = cls(
            hidden_dim=cfg["hidden_dim"],
            n_layers=cfg["n_layers"],
            dropout=cfg["dropout"],
            lr=cfg["lr"],
            batch_size=cfg["batch_size"],
            epochs=cfg["epochs"],
            weight_decay=cfg["weight_decay"],
            prefixes_per_deck=cfg["prefixes_per_deck"],
            device=device,
            seed=cfg["seed"],
        )
        model.vocab = [str(c) for c in ckpt["vocab"]]
        model.card_to_idx = {c: i for i, c in enumerate(model.vocab)}
        model._net = model._build_net(len(model.vocab))
        model._net.load_state_dict(ckpt["state_dict"])
        model._net.to(torch.device(device))
        model._net.eval()
        model._losses = list(ckpt.get("losses", []))
        return model


# --------------------------------------------------------------------------- #
# Validation metrics
# --------------------------------------------------------------------------- #


def recall_at_k(
    model: DeckBeliefModel,
    held_out: Sequence[Sequence[CardId]],
    *,
    k: int,
    rng: Optional[random.Random] = None,
    revealed_fraction: float = 0.5,
) -> float:
    """Mean recall@k over held-out decks.

    For each deck, reveal a random ``revealed_fraction`` of cards,
    predict the rest, take the top-``k`` predicted cards. Recall is
    ``|top_k ∩ rest_of_deck_unique| / |rest_of_deck_unique|`` per
    deck, averaged.

    "Unique" because the model predicts P(at least one more copy);
    multi-copy targets aren't double-counted.
    """
    if rng is None:
        rng = random.Random(0)
    if not held_out:
        return 0.0
    recalls: list[float] = []
    for deck in held_out:
        deck_len = len(deck)
        if deck_len < 2:
            continue
        n_reveal = max(1, int(deck_len * revealed_fraction))
        n_reveal = min(n_reveal, deck_len - 1)
        shuffled = list(deck)
        rng.shuffle(shuffled)
        revealed = shuffled[:n_reveal]
        rest = shuffled[n_reveal:]
        rest_set = set(rest)
        # rest is non-empty by construction (n_reveal capped at
        # deck_len - 1 above), so rest_set is non-empty.
        preds = model.predict_rest_of_deck(revealed)
        if not preds:
            continue
        top_k = sorted(preds.items(), key=lambda kv: -kv[1])[:k]
        top_k_set = {c for c, _ in top_k}
        # Only count cards from rest that are in the vocab.
        rest_in_vocab = {c for c in rest_set if c in model.card_to_idx}
        if not rest_in_vocab:
            continue
        hit = len(top_k_set & rest_in_vocab)
        recalls.append(hit / len(rest_in_vocab))
    if not recalls:
        return 0.0
    return float(np.mean(recalls))


def calibration_bins(
    model: DeckBeliefModel,
    held_out: Sequence[Sequence[CardId]],
    *,
    n_bins: int = 10,
    rng: Optional[random.Random] = None,
    revealed_fraction: float = 0.5,
    max_decks: Optional[int] = None,
) -> list[dict]:
    """Compute (predicted-prob, empirical-frequency) calibration bins.

    Returns a list of dicts with keys ``bin_low``, ``bin_high``,
    ``mean_predicted``, ``mean_empirical``, ``count``. Bins with zero
    counts are omitted.
    """
    if rng is None:
        rng = random.Random(0)
    if not held_out:
        return []
    if max_decks is not None:
        held_out = list(held_out)[:max_decks]
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_pred_sum = np.zeros(n_bins)
    bin_emp_sum = np.zeros(n_bins)
    bin_count = np.zeros(n_bins, dtype=np.int64)

    for deck in held_out:
        deck_len = len(deck)
        if deck_len < 2:
            continue
        n_reveal = max(1, int(deck_len * revealed_fraction))
        n_reveal = min(n_reveal, deck_len - 1)
        shuffled = list(deck)
        rng.shuffle(shuffled)
        revealed = shuffled[:n_reveal]
        rest = shuffled[n_reveal:]
        rest_set = {c for c in rest if c in model.card_to_idx}
        preds = model.predict_rest_of_deck(revealed)
        if not preds:
            continue
        for card, prob in preds.items():
            # Clip to inside [0, 1) so the right-edge case lands in
            # the top bin, not out of range.
            clipped = min(0.9999999, max(0.0, prob))
            bin_idx = int(np.digitize(clipped, bin_edges) - 1)
            bin_idx = max(0, min(n_bins - 1, bin_idx))
            bin_pred_sum[bin_idx] += prob
            bin_emp_sum[bin_idx] += 1.0 if card in rest_set else 0.0
            bin_count[bin_idx] += 1

    out = []
    for i in range(n_bins):
        if bin_count[i] == 0:
            continue
        out.append(
            {
                "bin_low": float(bin_edges[i]),
                "bin_high": float(bin_edges[i + 1]),
                "mean_predicted": float(bin_pred_sum[i] / bin_count[i]),
                "mean_empirical": float(bin_emp_sum[i] / bin_count[i]),
                "count": int(bin_count[i]),
            }
        )
    return out


def brier_score(
    model: DeckBeliefModel,
    held_out: Sequence[Sequence[CardId]],
    *,
    rng: Optional[random.Random] = None,
    revealed_fraction: float = 0.5,
    max_decks: Optional[int] = None,
) -> float:
    """Mean Brier score across all (card, deck) predictions.

    Brier = ``(p_predicted - 1[in rest])^2`` averaged across all
    unrevealed-card predictions across all held-out decks. Lower is
    better; perfectly calibrated random-guess at the base rate
    ``b`` is ``b * (1 - b)``.
    """
    if rng is None:
        rng = random.Random(0)
    if not held_out:
        return 0.0
    if max_decks is not None:
        held_out = list(held_out)[:max_decks]
    total = 0.0
    n = 0
    for deck in held_out:
        deck_len = len(deck)
        if deck_len < 2:
            continue
        n_reveal = max(1, int(deck_len * revealed_fraction))
        n_reveal = min(n_reveal, deck_len - 1)
        shuffled = list(deck)
        rng.shuffle(shuffled)
        revealed = shuffled[:n_reveal]
        rest = shuffled[n_reveal:]
        rest_set = {c for c in rest if c in model.card_to_idx}
        preds = model.predict_rest_of_deck(revealed)
        for card, prob in preds.items():
            y = 1.0 if card in rest_set else 0.0
            total += (prob - y) ** 2
            n += 1
    if n == 0:
        return 0.0
    return total / n


def expected_calibration_error(
    bins: Sequence[dict],
) -> float:
    """Weighted absolute gap between predicted and empirical per bin.

    ECE = sum_b (n_b / N) * |mean_predicted_b - mean_empirical_b|.
    """
    if not bins:
        return 0.0
    total = sum(b["count"] for b in bins)
    if total == 0:
        return 0.0
    return float(
        sum(
            (b["count"] / total) * abs(b["mean_predicted"] - b["mean_empirical"])
            for b in bins
        )
    )
