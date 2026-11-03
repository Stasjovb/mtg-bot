"""Website feedback reports (``mtg_bot.feedback``, ``POST /api/feedback``):
text + screenshots + game context saved to a timestamped folder, and an
unchecked line appended to REVIEW_LIST.md."""

from __future__ import annotations

import base64
import json
from datetime import datetime

import pytest

from mtg_bot import feedback as fb

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 16


def _url(data: bytes, mime: str = "image/png") -> dict:
    return {"data": f"data:{mime};base64," + base64.b64encode(data).decode()}


NOW = datetime(2026, 11, 3, 1, 2, 3)


def test_saves_text_images_context_and_review_line(tmp_path):
    folder = fb.save_feedback(
        tmp_path,
        {
            "text": "Dandân attacked without an Island\nmore detail",
            "images": [_url(PNG), _url(JPG, "image/jpeg")],
            "context": {"tab": "play", "session_id": "abc", "seed": 3,
                        "evil": "x", "snapshot_idx": True},
        },
        server_context={"turn": 4},
        now=NOW,
    )
    assert folder == tmp_path / "2026-11-03_010203"
    report = json.loads((folder / "feedback.json").read_text(encoding="utf-8"))
    assert report["images"] == ["image-1.png", "image-2.jpg"]
    assert report["client_context"] == {"tab": "play", "session_id": "abc", "seed": 3}
    assert report["server_context"] == {"turn": 4}
    assert (folder / "image-1.png").read_bytes() == PNG
    review = (tmp_path / fb.REVIEW_LIST).read_text(encoding="utf-8")
    assert review.endswith(
        f"- [ ] 2026-11-03 01:02:03 Dandân attacked without an Island -> {folder}\n"
    )


def test_same_second_reports_get_their_own_folders(tmp_path):
    a = fb.save_feedback(tmp_path, {"text": "one"}, now=NOW)
    b = fb.save_feedback(tmp_path, {"text": "two"}, now=NOW)
    assert a != b and b.name == "2026-11-03_010203_2"
    lines = (tmp_path / fb.REVIEW_LIST).read_text(encoding="utf-8").splitlines()
    assert [ln for ln in lines if ln.startswith("- [ ]")][-2:] == [
        f"- [ ] 2026-11-03 01:02:03 one -> {a}",
        f"- [ ] 2026-11-03 01:02:03 two -> {b}",
    ]


@pytest.mark.parametrize("data", [GIF, WEBP])
def test_gif_and_webp_are_accepted(tmp_path, data):
    folder = fb.save_feedback(tmp_path, {"images": [_url(data)]}, now=NOW)
    assert len(list(folder.glob("image-1.*"))) == 1


@pytest.mark.parametrize("body, message", [
    ("not a dict", "JSON object"),
    ({"text": 5}, "text must be a string"),
    ({"text": "x" * (fb.MAX_TEXT_CHARS + 1)}, "longer than"),
    ({"text": "x", "images": "nope"}, "must be a list"),
    ({"images": [_url(PNG)] * (fb.MAX_IMAGES + 1)}, "at most"),
    ({"text": "  "}, "write something"),
    ({"images": ["x"]}, "data URL"),
    ({"images": [{"data": "data:text/html;base64,PGI+"}]}, "data:image"),
    ({"images": [{"data": "data:image/png;base64,***"}]}, "base64"),
    ({"images": [_url(b"<svg onload=alert(1)>", "image/svg+xml")]}, "only PNG"),
    ({"images": [_url(b"MZ\x90\x00 an exe", "image/png")]}, "only PNG"),
])
def test_rejects_bad_reports_and_writes_nothing(tmp_path, body, message):
    with pytest.raises(fb.FeedbackError, match=message):
        fb.save_feedback(tmp_path, body, now=NOW)
    assert list(tmp_path.iterdir()) == []


def test_rejects_an_oversized_image(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "MAX_IMAGE_BYTES", 16)
    with pytest.raises(fb.FeedbackError, match="larger than"):
        fb.save_feedback(tmp_path, {"images": [_url(PNG)]}, now=NOW)


def test_client_text_never_becomes_a_path(tmp_path):
    folder = fb.save_feedback(
        tmp_path,
        {"text": "../../evil\n- [x] fake", "context": {"session_id": "../../x"}},
        now=NOW,
    )
    assert folder.parent == tmp_path
    review = (tmp_path / fb.REVIEW_LIST).read_text(encoding="utf-8")
    assert "- [x]" not in review
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "2026-11-03_010203", fb.REVIEW_LIST,
    ]


def test_first_line_is_cleaned_and_capped():
    assert fb.first_line("\n\n  hi\tthere \nnext") == "hi there"
    assert fb.first_line("") == "(no text)"
    assert fb.first_line("y" * 150) == "y" * 100 + "..."


def test_snapshot_context_and_default_root(monkeypatch, tmp_path):
    snap = {"turn_number": 5, "step": "upkeep", "log": [str(i) for i in range(50)]}
    ctx = fb.snapshot_context(snap)
    assert ctx["turn"] == 5 and ctx["recent_log"][0] == "10" and ctx["snapshot"] is snap
    assert fb.snapshot_context(None) == {}
    monkeypatch.setenv(fb.ENV_DIR, str(tmp_path))
    assert fb.default_root() == tmp_path.resolve()



@pytest.fixture
def client(tmp_path):
    from flask import Flask

    app = Flask(__name__)
    sessions = {"s1": {"turn_number": 7, "step": "draw", "log": ["a", "b"]}}
    games = {("g1", 2): {"turn_number": 3, "log": ["x"]}}
    fb.register_feedback_routes(
        app, root=lambda: tmp_path,
        session_snapshot=sessions.get,
        game_snapshot=lambda g, i: games.get((g, i)),
    )
    return app.test_client()


def test_route_saves_with_the_play_sessions_snapshot(client, tmp_path):
    r = client.post("/api/feedback", json={
        "text": "bug", "context": {"tab": "play", "session_id": "s1"},
    })
    assert r.status_code == 200 and r.get_json()["saved"]
    report = json.loads(
        (tmp_path / r.get_json()["folder"] / "feedback.json").read_text(encoding="utf-8"),
    )
    assert report["server_context"]["turn"] == 7
    assert report["server_context"]["recent_log"] == ["a", "b"]


def test_route_uses_the_watch_snapshot(client, tmp_path):
    r = client.post("/api/feedback", json={
        "text": "bug", "context": {"game_id": "g1", "snapshot_idx": 2},
    })
    folder = tmp_path / r.get_json()["folder"]
    report = json.loads((folder / "feedback.json").read_text(encoding="utf-8"))
    assert report["server_context"]["turn"] == 3


def test_route_rejects_bad_input_and_huge_bodies(client, monkeypatch):
    assert client.post("/api/feedback", json={"text": ""}).status_code == 400
    assert client.post("/api/feedback", data="junk").status_code == 400
    monkeypatch.setattr(fb, "MAX_REQUEST_BYTES", 10)
    assert client.post("/api/feedback", json={"text": "long enough"}).status_code == 413
