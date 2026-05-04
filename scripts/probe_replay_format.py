"""Phase 6 audit: probe one captured replay's actual on-disk schema.

Generates a single replay using the real data-gen path with
``capture_every=1`` so we capture every game, then introspects the
serialized snapshots to confirm the audit findings against ground truth
rather than just code reading.

Run:
    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
        scripts/probe_replay_format.py
"""
from __future__ import annotations

import gzip
import json
import sys
import tempfile
from pathlib import Path

from mtg_bot.replay import load_replay
from mtg_bot.training.data_gen import (
    ReplayCaptureConfig,
    _generate_one_game_data,
)
import random as _random

from mtg_bot.search.strategy import RandomChoice


def random_factory(seed: int):
    return RandomChoice(rng=_random.Random(seed))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ReplayCaptureConfig(
            save_dir=tmp,
            capture_every=1,
            filename_prefix="probe",
        )
        # Tiny game: just play through with random strategies, low cap.
        _generate_one_game_data(
            game_idx=0,
            p0_factory=random_factory,
            p1_factory=random_factory,
            base_seed=42,
            decision_cap=80,
            sample_every=1,
            replay_config=cfg,
            deck_pool=None,
            enable_mulligans=False,
        )
        files = sorted(Path(tmp).glob("*.json.gz"))
        if not files:
            print("ERROR: no replay file written")
            return 1
        path = files[0]
        replay = load_replay(path)
        print(f"=== Replay path: {path.name} ===")
        print(f"format_version: {replay.format_version}")
        print(f"metadata keys: {sorted(replay.metadata.keys())}")
        print(f"metadata: {json.dumps(replay.metadata, default=str)}")
        print(f"n_snapshots: {len(replay.snapshots)}")

        if replay.snapshots:
            snap0 = replay.snapshots[0]
            print(f"\n=== Top-level snapshot[0] keys ===")
            for k in sorted(snap0.keys()):
                v = snap0[k]
                t = type(v).__name__
                if isinstance(v, list):
                    sub = type(v[0]).__name__ if v else "?"
                    print(f"  {k}: list[{sub}] (len={len(v)})")
                else:
                    print(f"  {k}: {t} = {v!r}"[:120])

            # Per-player keys
            if snap0.get("players"):
                p0 = snap0["players"][0]
                print(f"\n=== players[0] keys ===")
                for k in sorted(p0.keys()):
                    v = p0[k]
                    t = type(v).__name__
                    if isinstance(v, list):
                        sub = type(v[0]).__name__ if v else "?"
                        print(f"  {k}: list[{sub}] (len={len(v)})")
                    else:
                        print(f"  {k}: {t} = {v!r}"[:120])

            # Stack contents (pick a snapshot where stack is non-empty)
            for i, s in enumerate(replay.snapshots):
                if s.get("stack"):
                    print(f"\n=== stack[0] keys (from snap {i}) ===")
                    for k, v in sorted(s["stack"][0].items()):
                        print(f"  {k}: {type(v).__name__} = {v!r}"[:120])
                    break
            # Hand cards
            for s in replay.snapshots:
                if s["players"][0].get("hand"):
                    print(f"\n=== players[0].hand[0] keys ===")
                    for k, v in sorted(s["players"][0]["hand"][0].items()):
                        print(f"  {k}: {type(v).__name__} = {v!r}"[:120])
                    break
            # Battlefield permanent
            for s in replay.snapshots:
                for p in s["players"]:
                    if p.get("battlefield"):
                        print(f"\n=== players[*].battlefield[0] keys ===")
                        for k, v in sorted(p["battlefield"][0].items()):
                            print(f"  {k}: {type(v).__name__} = {v!r}"[:120])
                        break
                else:
                    continue
                break

            # Look for any of these absent fields the audit cares about:
            print(f"\n=== Phase 6 absence checks ===")
            checks = [
                ("snapshot has 'decision' (action taken)", "decision" in snap0),
                ("snapshot has 'action' (action taken)", "action" in snap0),
                ("snapshot has 'priority_player_id' (vs idx)", "priority_player_id" in snap0),
                ("snapshot has 'rng_state'", "rng_state" in snap0),
                ("snapshot has 'continuous_effects'", "continuous_effects" in snap0),
                ("snapshot has 'delayed_triggers'", "delayed_triggers" in snap0),
                ("snapshot has 'next_object_id'", "next_object_id" in snap0),
                ("snapshot has 'once_per_turn_fired'", "once_per_turn_fired" in snap0),
                ("snapshot has 'extra_turn_queue'", "extra_turn_queue" in snap0),
                ("snapshot has 'pending_end_of_combat_sacrifices'",
                 "pending_end_of_combat_sacrifices" in snap0),
                ("metadata has 'decision_history'", "decision_history" in replay.metadata),
                ("metadata has 'actions'", "actions" in replay.metadata),
                ("metadata has 'p0_deck'", "p0_deck" in replay.metadata),
                ("metadata has 'p1_deck'", "p1_deck" in replay.metadata),
            ]
            for label, present in checks:
                mark = "PRESENT" if present else "ABSENT"
                print(f"  [{mark}] {label}")

            # Compressed size
            with gzip.open(path, "rb") as f:
                raw = f.read()
            print(f"\n=== Sizes ===")
            print(f"  on-disk gz: {path.stat().st_size} bytes")
            print(f"  decompressed JSON: {len(raw)} bytes")
            print(f"  snapshots:        {len(replay.snapshots)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
