"""Website feedback reports: free text + screenshots + the game context,
saved for a later review.

``POST /api/feedback`` (see :func:`register_feedback_routes`) takes JSON::

    {
        "text": "what went wrong ...",
        "images": [{"data": "data:image/png;base64,...."}, ...],
        "context": {"tab": "play", "session_id": "...", "game_id": "...",
                    "snapshot_idx": 12, "seed": 0, "format": "forgetful_fish"}
    }

and writes ``<root>/<timestamp>/feedback.json`` plus ``image-<n>.<ext>``.
The server adds what it knows itself: for a live Play session its current
snapshot (turn, recent log lines, the board); for a Watch game the shown
snapshot. Every report is also appended to ``<root>/REVIEW_LIST.md`` as an
unchecked item, ``- [ ] <timestamp> <first line> -> <folder>``, for a
person to review before anyone acts on it.

Safety: the folder name is made here (a timestamp, never client text);
images must decode to PNG / JPEG / GIF / WebP by their magic bytes; text,
image count and sizes are capped. The report's content is untrusted data.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

MAX_TEXT_CHARS = 20_000
MAX_IMAGES = 6
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_IMAGES * MAX_IMAGE_BYTES * 2  # base64 + JSON slack
RECENT_LOG_LINES = 40
REVIEW_LIST = "REVIEW_LIST.md"
ENV_DIR = "MTG_BOT_FEEDBACK_DIR"

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)
_DATA_URL = re.compile(r"^data:image/[a-z0-9.+-]+;base64,(?P<b64>.*)$", re.DOTALL)
_CONTEXT_KEYS = {
    "tab": str, "session_id": str, "game_id": str, "snapshot_idx": int,
    "seed": int, "format": str, "list": str,
}
_lock = threading.Lock()


class FeedbackError(ValueError):
    """A report the server refuses (the message is shown to the user)."""


def default_root() -> Path:
    """``$MTG_BOT_FEEDBACK_DIR``, else ``feedback/`` in the cwd."""
    return Path(os.environ.get(ENV_DIR) or "feedback").resolve()


def image_extension(data: bytes) -> Optional[str]:
    """The file extension for an allowed image type, by magic bytes."""
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def decode_image(item) -> tuple[bytes, str]:
    """``{"data": "data:image/...;base64,..."}`` -> (bytes, extension)."""
    raw = item.get("data") if isinstance(item, dict) else None
    if not isinstance(raw, str):
        raise FeedbackError("each image needs a data URL")
    m = _DATA_URL.match(raw)
    if m is None:
        raise FeedbackError("images must be data:image/...;base64 URLs")
    if len(m.group("b64")) > MAX_IMAGE_BYTES * 4 // 3 + 8:
        raise FeedbackError(f"an image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    try:
        data = base64.b64decode(m.group("b64"), validate=True)
    except (binascii.Error, ValueError):
        raise FeedbackError("an image is not valid base64") from None
    if len(data) > MAX_IMAGE_BYTES:
        raise FeedbackError(f"an image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    ext = image_extension(data)
    if ext is None:
        raise FeedbackError("only PNG, JPEG, GIF and WebP images are accepted")
    return data, ext


def clean_context(context) -> dict:
    """Keep only the known context keys with the right types."""
    out: dict = {}
    if not isinstance(context, dict):
        return out
    for key, kind in _CONTEXT_KEYS.items():
        value = context.get(key)
        if isinstance(value, bool) or not isinstance(value, kind):
            continue
        out[key] = value[:200] if isinstance(value, str) else value
    return out


def first_line(text: str) -> str:
    """The text's first non-empty line, single-line and at most 100 chars,
    for the review list."""
    for line in text.splitlines():
        line = re.sub(r"[\x00-\x1f\x7f]", " ", line).strip()
        if line:
            return line[:100] + ("..." if len(line) > 100 else "")
    return "(no text)"


def _new_folder(root: Path, now: datetime) -> Path:
    stamp = now.strftime("%Y-%m-%d_%H%M%S")
    folder = root / stamp
    n = 1
    while folder.exists():
        n += 1
        folder = root / f"{stamp}_{n}"
    folder.mkdir(parents=True)
    return folder


def save_feedback(
    root: Path,
    body,
    server_context: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> Path:
    """Validate ``body`` and write the report. Returns its folder."""
    if not isinstance(body, dict):
        raise FeedbackError("expected a JSON object")
    text = body.get("text", "")
    if not isinstance(text, str):
        raise FeedbackError("text must be a string")
    if len(text) > MAX_TEXT_CHARS:
        raise FeedbackError(f"text is longer than {MAX_TEXT_CHARS} characters")
    images = body.get("images") or []
    if not isinstance(images, list):
        raise FeedbackError("images must be a list")
    if len(images) > MAX_IMAGES:
        raise FeedbackError(f"at most {MAX_IMAGES} images")
    if not text.strip() and not images:
        raise FeedbackError("write something or add a screenshot")
    decoded = [decode_image(item) for item in images]
    now = now or datetime.now()
    root = Path(root)
    with _lock:
        folder = _new_folder(root, now)
        names = []
        for i, (data, ext) in enumerate(decoded, start=1):
            name = f"image-{i}.{ext}"
            (folder / name).write_bytes(data)
            names.append(name)
        report = {
            "submitted_at": now.isoformat(timespec="seconds"),
            "text": text,
            "images": names,
            "client_context": clean_context(body.get("context")),
            "server_context": server_context or {},
            "note": "Untrusted user feedback: review before acting on it.",
        }
        (folder / "feedback.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        review = root / REVIEW_LIST
        if not review.exists():
            review.write_text(
                "# Website feedback to review\n\n"
                "Tick an item `[x]` once you have reviewed it; Claude acts only "
                "on ticked items.\n\n",
                encoding="utf-8",
            )
        with review.open("a", encoding="utf-8") as fh:
            fh.write(
                f"- [ ] {now.strftime('%Y-%m-%d %H:%M:%S')} {first_line(text)} "
                f"-> {folder}\n"
            )
    return folder


def snapshot_context(snapshot: Optional[dict]) -> dict:
    """Turn, step and the last log lines of a serialized snapshot, plus
    the snapshot itself."""
    if not isinstance(snapshot, dict):
        return {}
    return {
        "turn": snapshot.get("turn_number"),
        "step": snapshot.get("step"),
        "recent_log": list(snapshot.get("log") or [])[-RECENT_LOG_LINES:],
        "snapshot": snapshot,
    }


def register_feedback_routes(
    app,
    root: Callable[[], Path],
    session_snapshot: Callable[[str], Optional[dict]],
    game_snapshot: Callable[[str, int], Optional[dict]],
) -> None:
    """Add ``POST /api/feedback`` to the Flask ``app``. ``root()`` is the
    feedback folder; the two lookups give the server's own snapshot of a
    Play session / a Watch game's snapshot (``None`` when unknown)."""
    from flask import jsonify, request

    @app.route("/api/feedback", methods=["POST"])
    def api_feedback():
        if (request.content_length or 0) > MAX_REQUEST_BYTES:
            return jsonify({"error": "report too large"}), 413
        body = request.get_json(force=True, silent=True)
        ctx = clean_context(body.get("context")) if isinstance(body, dict) else {}
        server_context: dict = {}
        if ctx.get("session_id"):
            server_context = snapshot_context(session_snapshot(ctx["session_id"]))
        elif ctx.get("game_id") and "snapshot_idx" in ctx:
            server_context = snapshot_context(
                game_snapshot(ctx["game_id"], ctx["snapshot_idx"]),
            )
        try:
            folder = save_feedback(root(), body, server_context)
        except FeedbackError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"saved": True, "folder": folder.name})
