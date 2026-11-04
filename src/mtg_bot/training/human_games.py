"""Training rows from recorded website games (see ``mtg_bot.game_records``).

``replay_record`` plays a record again on the engine: the record's seed,
decks, seats and starting player; each person's answers come from the record,
in order; the bot's choices come from its seed, as in the live game. Before a
person's answer is applied, the replay keeps the rows the self-play generator
keeps for that decision: one row per viewer (the viewer's board tokens and
features) and, for the person's own row, a one-hot policy target over the
legal slots, the answer they chose. The value label is the game's outcome for
that viewer, as in the generator.

Known gap: the rows carry no action-history tokens. The replay drives the
engine directly, while the self-play generator tracks the history through
``MtgGameStateAdapter``. So a human row sees an empty history. Fixing that
means replaying through the adapter.

``records_to_shard`` writes the rows of many records into one ``.npz`` shard
that the trainer reads (``data_gen.save_dataset``).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional

import numpy as np

from mtg_bot.agents import RandomAgent
from mtg_bot.features import extract_features
from mtg_bot.formats import get_format
from mtg_bot.game_records import load_record
from mtg_bot.interactive import InteractiveAgent, bot_rng


class ReplayMismatch(ValueError):
    """The engine asks something the record does not answer, or the answers
    differ from the record. The record cannot be replayed."""


def _decision_rows(state: Any, seat: int, chosen: Any) -> list[dict]:
    """The rows for one decision of ``seat``, before its answer is applied."""
    from mtg_bot.training.action_encoding import (
        ACTION_VOCAB_SIZE, EncodingOverflowError, encode, legal_action_mask,
    )
    from mtg_bot.training.state_tokenizer import tokenize_state

    slot = None
    mask = None
    if chosen is not None:
        try:
            slot = encode(chosen, state, seat)
            mask = legal_action_mask(state, seat)
        except EncodingOverflowError:
            slot = None  # the choice is not representable: no policy row
    rows = []
    for viewer in (0, 1):
        policy = np.zeros(ACTION_VOCAB_SIZE, dtype=np.float32)
        action_mask = np.zeros(ACTION_VOCAB_SIZE, dtype=np.bool_)
        if viewer == seat and slot is not None:
            policy[slot] = 1.0
            action_mask = mask
        struct = tokenize_state(state, viewer_id=viewer)
        struct["root_value"] = np.float32(np.nan)
        rows.append({
            "viewer": viewer,
            "features": extract_features(state, viewer),
            "policy": policy,
            "mask": action_mask,
            "struct": struct,
        })
    return rows


class _ReplayAgent(InteractiveAgent):
    """One person's seat in a replay. The answers come from the record, in
    order, instead of from a browser."""

    def __init__(self, n2id: dict, seat: int, answers: list[dict], rows: list):
        super().__init__(n2id)
        self._seat = seat
        self._answers = answers
        self._rows = rows
        self._asks = 0
        self._legal: Optional[list] = None

    def choose_action(self, state, player_id, legal):
        self._legal = legal
        return super().choose_action(state, player_id, legal)

    def _ask(self, state, pending):
        self._asks += 1
        if self._asks > len(self._answers):
            raise ReplayMismatch(f"seat {self._seat} is asked more than the record answers")
        answer = self._answers[self._asks - 1]
        if answer.get("seq") != self._asks or answer.get("type") != pending.get("type"):
            raise ReplayMismatch(
                f"seat {self._seat} decision {self._asks} differs from the record",
            )
        chosen = None
        if pending.get("type") == "choose_action" and self._legal is not None:
            chosen = self._legal[int(answer["response"]["idx"])]
        self._rows.extend(_decision_rows(state, self._seat, chosen))
        return answer["response"]


def replay_record(record: dict, n2id: dict) -> tuple[list[dict], Optional[int]]:
    """Play ``record`` again. Returns its rows and the winner (None for a
    draw). Raises :class:`ReplayMismatch` when the replay ends differently
    from the record."""
    from mtg_bot.simulate import simulate_game

    seed = int(record["seed"])
    seats = set(record["human_seats"])
    answers: dict[int, list[dict]] = {0: [], 1: []}
    for decision in record["decisions"]:
        answers[decision["seat"]].append(decision)
    rows: list[dict] = []
    agents = [
        _ReplayAgent(n2id, seat, answers[seat], rows) if seat in seats
        else RandomAgent(rng=bot_rng(seed))
        for seat in (0, 1)
    ]
    decks = record.get("decks")
    state = simulate_game(
        agents=agents,
        colors=record["colors"] if decks is None else None,
        decks=decks,
        game_format=get_format(record["format"]),
        seed=seed,
        max_turns=int(record["max_turns"]),
        starting_player_idx=int(record["starting_player_idx"]),
    )
    winner = state.winner_id
    recorded = record.get("result", {})
    if "winner_id" in recorded and recorded["winner_id"] != winner:
        raise ReplayMismatch(
            f"the replay ended with winner {winner}, the record says {recorded['winner_id']}",
        )
    return rows, winner


def _outcome(winner: Optional[int], viewer: int) -> float:
    if winner is None:
        return 0.0
    return 1.0 if winner == viewer else -1.0


def records_to_shard(paths: list[Path], out_path: Path, n2id: dict) -> int:
    """Write the rows of the records at ``paths`` to one shard. Returns the
    number of rows. Raises ``ValueError`` when there is nothing to learn from."""
    from mtg_bot.training.data_gen import _pad_and_stack_structured_rows, save_dataset

    features, outcomes, policies, masks, structs, game_ids = [], [], [], [], [], []
    for game_idx, path in enumerate(paths):
        rows, winner = replay_record(load_record(path), n2id)
        for row in rows:
            features.append(row["features"])
            outcomes.append(_outcome(winner, row["viewer"]))
            policies.append(row["policy"])
            masks.append(row["mask"])
            structs.append(row["struct"])
            game_ids.append(game_idx)
    if not features:
        raise ValueError("no human decisions in these records: nothing to learn from")
    padded = _pad_and_stack_structured_rows(structs)
    save_dataset(
        np.stack(features).astype(np.float32),
        np.asarray(outcomes, dtype=np.float32),
        out_path,
        policy_targets=np.stack(policies),
        action_masks=np.stack(masks),
        structured_token_type=padded["structured_token_type"],
        structured_token_emb_ids=padded["structured_token_emb_ids"],
        structured_token_scalars=padded["structured_token_scalars"],
        structured_attention_mask=padded["structured_attention_mask"],
        game_ids=np.asarray(game_ids, dtype=np.int32),
    )
    return len(features)


def main(argv: Optional[list[str]] = None) -> None:  # pragma: no cover - CLI
    from mtg_bot.art import CardIndex

    parser = argparse.ArgumentParser(description="Turn recorded games into a training shard.")
    parser.add_argument("records", nargs="+", type=Path, help="record .json files")
    parser.add_argument("--out", type=Path, required=True, help="the shard .npz to write")
    args = parser.parse_args(argv)
    index = CardIndex.load()
    n2id = {name: card["id"] for name, card in index.by_name.items()}
    rows = records_to_shard(args.records, args.out, n2id)
    print(f"wrote {rows} rows from {len(args.records)} games to {args.out}")


if __name__ == "__main__":  # pragma: no cover
    main()
