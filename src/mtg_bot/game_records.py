"""Records of games played on the website, kept for training.

A record holds what is needed to play the game again: the seed, the decks,
the seats and the starting player, every answer a person gave (in order,
with the decision's type and sequence number), and the result. The bot's
choices are not stored: its choices come from a seed, so the same game
replays the same way. Records are written only for games the players chose
to record (the Play form's "Record this game" box).

Records are plain JSON files, one per game, in ``$MTG_BOT_GAME_RECORDS``
(default ``fish-data/human_games`` in the working folder). They stay outside
git.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ENV_DIR = "MTG_BOT_GAME_RECORDS"
RECORD_VERSION = 1
_write_lock = threading.Lock()


def records_dir() -> Path:
    """``$MTG_BOT_GAME_RECORDS``, else ``fish-data/human_games`` in the working folder."""
    return Path(os.environ.get(ENV_DIR) or Path("fish-data") / "human_games")


class GameRecorder:
    """Collects one game's answers and writes its record when the game ends."""

    def __init__(self, session_id: str, meta: dict, root: Optional[Path] = None):
        self.session_id = session_id
        self.meta = dict(meta)
        self.root = Path(root) if root is not None else records_dir()
        self.decisions: list[dict] = []
        self._lock = threading.Lock()

    def answer(self, seat: int, pending: dict, response) -> None:
        """Keep one answer a person gave, with the decision it answers."""
        with self._lock:
            self.decisions.append({
                "seat": seat,
                "seq": pending.get("seq"),
                "type": pending.get("type"),
                "response": response,
            })

    def finish(self, result: dict) -> Path:
        """Write the record. Called once, when the game ends."""
        with self._lock:
            decisions = list(self.decisions)
        record = {
            "version": RECORD_VERSION,
            "session_id": self.session_id,
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **self.meta,
            "result": result,
            "decisions": decisions,
        }
        path = self.root / f"{self.session_id}.json"
        with _write_lock:
            self.root.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8",
            )
        return path


def load_record(path) -> dict:
    """Read a record back. Refuses a record of another version."""
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    if record.get("version") != RECORD_VERSION:
        raise ValueError(f"unknown record version {record.get('version')!r}")
    return record
