import subprocess
from pathlib import Path

import pytest

from mtg_bot import ui
from mtg_bot.art import CardIndex
from mtg_bot.ui import (
    CliArgs,
    GameCache,
    _enrich_snapshot,
    create_app,
    describe_urls,
    detect_tailscale_ip,
    main,
    parse_args,
)


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _fake_index() -> CardIndex:
    alpha = {
        "id": "id-1",
        "name": "Alpha",
        "mana_cost": "{1}{U}",
        "type_line": "Creature — Alien",
        "oracle_text": "Flying.",
        "power": "2",
        "toughness": "1",
        "colors": ["U"],
        "image_uris": {
            "small": "https://example.test/s/id-1.jpg",
            "normal": "https://example.test/n/id-1.jpg",
        },
    }
    beta = {"id": "id-2", "name": "Beta"}  # no image_uris
    return CardIndex(
        by_name={"Alpha": alpha, "Beta": beta},
        by_id={"id-1": alpha, "id-2": beta},
    )


@pytest.fixture
def fake_index():
    return _fake_index()


@pytest.fixture
def fake_fetcher():
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return b"IMGBYTES"

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


@pytest.fixture
def img_client(tmp_path, fake_index, fake_fetcher):
    app = create_app(
        card_index=fake_index,
        image_root=tmp_path,
        image_fetcher=fake_fetcher,
    )
    app.config["TESTING"] = True
    return app.test_client()


def test_index_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_index_has_form_and_color_options(client):
    html = client.get("/").get_data(as_text=True)
    assert "<form" in html
    for color in ["W", "U", "B", "R", "G"]:
        assert f'value="{color}"' in html


def test_index_references_static_assets(client):
    html = client.get("/").get_data(as_text=True)
    assert "app.css" in html
    assert "app.js" in html


def test_static_app_js_is_served(client):
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    assert b"fetchJSON" in resp.data


def test_static_app_js_ships_scrubber_code(client):
    js = client.get("/static/app.js").get_data(as_text=True)
    # Spot-check the scrubber control surface is actually in the bundle.
    for token in ("goTo", "startPlay", "stopPlay", "snapCache"):
        assert token in js, f"missing {token!r} in app.js"


def test_static_app_js_ships_step_turn_navigation(client):
    js = client.get("/static/app.js").get_data(as_text=True)
    for token in ("findNextStepIdx", "findPrevStepIdx",
                  "findNextTurnIdx", "findPrevTurnIdx",
                  "btn-prev-turn", "btn-next-turn",
                  "btn-prev-step", "btn-next-step",
                  "snapshots_index",
                  "ArrowLeft", "ArrowRight"):
        assert token in js, f"missing {token!r} in app.js"


def test_static_app_js_ships_phase_tracker(client):
    js = client.get("/static/app.js").get_data(as_text=True)
    for token in ("renderPhaseTracker", "PHASE_STEPS",
                  "precombat_main", "declare_attackers",
                  "phase-tracker", "phase-step"):
        assert token in js, f"missing {token!r} in app.js"


def test_static_app_css_styles_phase_tracker(client):
    css = client.get("/static/app.css").get_data(as_text=True)
    for sel in (".phase-tracker", ".phase-list", ".phase-step",
                ".phase-step.current", ".phase-step.past"):
        assert sel in css, f"missing {sel!r} in app.css"


def test_index_html_has_phase_tracker_dom(client):
    html = client.get("/").get_data(as_text=True)
    for eid in ("phase-tracker", "phase-list"):
        assert f'id="{eid}"' in html, f"missing id={eid!r} in index.html"


def test_static_app_js_ships_zone_modal(client):
    js = client.get("/static/app.js").get_data(as_text=True)
    for token in ("openZoneModal", "closeZoneModal", "zone-modal",
                  "graveyard", "exile"):
        assert token in js, f"missing {token!r} in app.js"


def test_static_app_css_styles_zone_modal(client):
    css = client.get("/static/app.css").get_data(as_text=True)
    for sel in (".zone-modal", ".zone-modal-inner", ".zone-modal-cards",
                ".zone-box.clickable"):
        assert sel in css, f"missing {sel!r} in app.css"


def test_index_html_has_zone_modal_dom(client):
    html = client.get("/").get_data(as_text=True)
    for eid in ("zone-modal", "zone-modal-title", "zone-modal-cards",
                "zone-modal-close"):
        assert f'id="{eid}"' in html, f"missing id={eid!r} in index.html"


def test_static_app_js_ships_face_down_card(client):
    js = client.get("/static/app.js").get_data(as_text=True)
    for token in ("faceDownCardEl", "face-down"):
        assert token in js, f"missing {token!r} in app.js"


def test_static_app_css_styles_face_down_card(client):
    css = client.get("/static/app.css").get_data(as_text=True)
    assert ".card.face-down" in css


def test_index_html_has_reveal_select(client):
    html = client.get("/").get_data(as_text=True)
    assert 'name="reveal"' in html
    for opt in ("all", "p0", "p1", "none"):
        assert f'value="{opt}"' in html


def test_static_app_js_ships_station_badge(client):
    js = client.get("/static/app.js").get_data(as_text=True)
    for token in ("station-bar", "is_spacecraft", "station_threshold"):
        assert token in js, f"missing {token!r} in app.js"


def test_static_app_css_styles_station_bar(client):
    css = client.get("/static/app.css").get_data(as_text=True)
    for sel in (".station-bar", ".station-bar.stationed"):
        assert sel in css, f"missing {sel!r} in app.css"


def test_static_app_js_ships_decision_panel_code(client):
    js = client.get("/static/app.js").get_data(as_text=True)
    # The unified Decision panel replaces the old engine-recs panel.
    # It still calls /api/recommend (as a fallback when there's no
    # search annotation), but no longer uses the old toggleEngine/
    # renderEngineRecs path.
    for token in ("renderSearchPanel", "_renderRecommendFallback",
                  "_renderSearchAnnotation", "/api/recommend/"):
        assert token in js, f"missing {token!r} in app.js"
    for absent in ("toggleEngine", "refreshEngine", "renderEngineRecs",
                   "engine-panel", "engine-recs"):
        assert absent not in js, f"{absent!r} should be gone from app.js"


def test_static_app_css_styles_decision_panel(client):
    css = client.get("/static/app.css").get_data(as_text=True)
    for sel in (".search-panel", ".search-table", ".search-row.chosen",
                ".search-toggle", ".right-col"):
        assert sel in css, f"missing {sel!r} in app.css"


def test_index_html_has_decision_panel_elements(client):
    html = client.get("/").get_data(as_text=True)
    for eid in ("search-panel", "search-toggle", "search-body",
                "search-chosen", "search-budget", "search-rows"):
        assert f'id="{eid}"' in html, f"missing id={eid!r} in index.html"
    # And the old engine-panel section is gone.
    for absent in ("engine-panel", "engine-recs", "btn-engine",
                   "engine-player", "engine-name"):
        assert f'id="{absent}"' not in html, (
            f"id={absent!r} should be removed from index.html")


def test_index_html_has_step_turn_buttons(client):
    html = client.get("/").get_data(as_text=True)
    for eid in ("btn-prev-turn", "btn-prev-step", "btn-next-step", "btn-next-turn"):
        assert f'id="{eid}"' in html, f"missing id={eid!r} in index.html"


def test_static_app_js_ships_tier1_renderers(client):
    js = client.get("/static/app.js").get_data(as_text=True)
    # Mana pool + new badge renderers are wired up.
    for token in ("manaPoolEl", "loyalty-badge", "stun-badge", "attached-to"):
        assert token in js, f"missing {token!r} in app.js"


def test_static_app_css_styles_tier1_elements(client):
    css = client.get("/static/app.css").get_data(as_text=True)
    for selector in (".mana-coin", ".loyalty-badge", ".stun-badge", ".attached-to"):
        assert selector in css, f"missing {selector!r} in app.css"


def test_static_app_js_ships_tier2_renderers(client):
    js = client.get("/static/app.js").get_data(as_text=True)
    # Poison + stack metadata renderers + per-step log highlight.
    for token in ("poisonEl", "x-value", "kicked", "countered", "targets",
                  "log_since_last", "this-step"):
        assert token in js, f"missing {token!r} in app.js"


def test_static_app_js_ships_stack_card_layout(client):
    js = client.get("/static/app.js").get_data(as_text=True)
    for token in ("stackItemEl", "stack-item-img", "stack-item-text",
                  "ability-desc"):
        assert token in js, f"missing {token!r} in app.js"


def test_static_app_css_styles_stack_card_layout(client):
    css = client.get("/static/app.css").get_data(as_text=True)
    for selector in (".stack-item-img", ".stack-item-text",
                     ".stack-item-name", ".stack-item .ability-desc"):
        assert selector in css, f"missing {selector!r} in app.css"


def test_static_app_js_ships_tier3_combat_arrows(client):
    js = client.get("/static/app.js").get_data(as_text=True)
    for token in ("drawCombatArrows", "arrow-head-attack", "arrow-head-block",
                  "attacking_defender", "blocked_by"):
        assert token in js, f"missing {token!r} in app.js"


def test_static_app_css_styles_combat_arrows(client):
    css = client.get("/static/app.css").get_data(as_text=True)
    for selector in (".combat-overlay", ".combat-arrow", ".combat-arrow.block"):
        assert selector in css, f"missing {selector!r} in app.css"


def test_index_includes_combat_overlay_svg(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="combat-overlay"' in html
    # Marker definitions shipped in the template.
    assert 'id="arrow-head-attack"' in html
    assert 'id="arrow-head-block"' in html


def test_static_app_css_styles_tier2_elements(client):
    css = client.get("/static/app.css").get_data(as_text=True)
    for selector in (".poison-row", ".poison-count", ".stack-item .x-value",
                     ".stack-item .kicked", ".stack-item .countered",
                     ".stack-item .targets"):
        assert selector in css, f"missing {selector!r} in app.css"


def test_index_has_scrubber_elements(client):
    html = client.get("/").get_data(as_text=True)
    for eid in ("scrubber", "scrub-slider", "scrub-label", "scrub-counter",
                "btn-first", "btn-prev", "btn-play", "btn-next", "btn-last"):
        assert f'id="{eid}"' in html, f"missing id={eid!r} in index.html"


def test_static_app_css_is_served(client):
    resp = client.get("/static/app.css")
    assert resp.status_code == 200
    assert b".card" in resp.data


def test_play_html_route_is_removed(client):
    # /play was the old server-rendered page; the JS frontend consumes
    # /api/play now, so the HTML route no longer exists.
    resp = client.get("/play")
    assert resp.status_code == 404


# ------------------------------------------------------------------------
# CLI + Tailscale helpers
# ------------------------------------------------------------------------


def test_parse_args_defaults():
    args = parse_args([])
    assert args == CliArgs(
        host="127.0.0.1", port=5002, replays_root=None,
    )


def test_parse_args_overrides():
    args = parse_args(["--host", "0.0.0.0", "--port", "8080"])
    assert args == CliArgs(
        host="0.0.0.0", port=8080, replays_root=None,
    )


def test_parse_args_replays_root():
    args = parse_args(["--replays-root", "some/dir"])
    assert args.replays_root == Path("some/dir")


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str):
        self.returncode = returncode
        self.stdout = stdout


def test_detect_tailscale_ip_success(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _FakeCompletedProcess(0, "100.64.0.1\n"),
    )
    assert detect_tailscale_ip() == "100.64.0.1"


def test_detect_tailscale_ip_not_installed(monkeypatch):
    def raise_fnf(*a, **kw):
        raise FileNotFoundError
    monkeypatch.setattr(subprocess, "run", raise_fnf)
    assert detect_tailscale_ip() is None


def test_detect_tailscale_ip_timeout(monkeypatch):
    def raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="tailscale", timeout=5)
    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert detect_tailscale_ip() is None


def test_detect_tailscale_ip_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _FakeCompletedProcess(1, ""),
    )
    assert detect_tailscale_ip() is None


def test_detect_tailscale_ip_empty_stdout(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _FakeCompletedProcess(0, "\n"),
    )
    assert detect_tailscale_ip() is None


def test_detect_tailscale_ip_os_error(monkeypatch):
    def raise_os(*a, **kw):
        raise OSError("permission denied")
    monkeypatch.setattr(subprocess, "run", raise_os)
    assert detect_tailscale_ip() is None


def test_describe_urls_specific_host_skips_detection(monkeypatch):
    # If host is specific, detect_tailscale_ip must NOT be called.
    monkeypatch.setattr(
        ui, "detect_tailscale_ip",
        lambda: pytest.fail("detection should not run for specific host"),
    )
    assert describe_urls("127.0.0.1", 5000) == ["http://127.0.0.1:5000"]


def test_describe_urls_all_interfaces_with_tailscale(monkeypatch):
    monkeypatch.setattr(ui, "detect_tailscale_ip", lambda: "100.64.0.1")
    urls = describe_urls("0.0.0.0", 5000)
    assert "http://localhost:5000" in urls
    assert any("100.64.0.1" in u and "Tailscale" in u for u in urls)


def test_describe_urls_all_interfaces_without_tailscale(monkeypatch):
    monkeypatch.setattr(ui, "detect_tailscale_ip", lambda: None)
    assert describe_urls("0.0.0.0", 5000) == ["http://localhost:5000"]


# ------------------------------------------------------------------------
# JSON API: /api/play and /api/snapshot
# ------------------------------------------------------------------------


def test_api_play_returns_json_game_summary(client):
    resp = client.get("/api/play?seed=0&c1=G&c2=R&max_turns=3")
    assert resp.status_code == 200
    assert resp.is_json
    body = resp.get_json()
    assert isinstance(body["game_id"], str) and len(body["game_id"]) > 0
    assert body["snapshot_count"] > 0
    assert body["colors"] == ["G", "R"]
    assert body["seed"] == 0
    assert isinstance(body["turn_number"], int)


def test_api_play_invalid_c1_400(client):
    resp = client.get("/api/play?c1=ZZ")
    assert resp.status_code == 400


def test_api_play_invalid_c2_400(client):
    resp = client.get("/api/play?c2=ZZ")
    assert resp.status_code == 400


def test_api_play_default_granularity_is_step(client):
    body = client.get("/api/play?seed=0&max_turns=4").get_json()
    assert body["granularity"] == "step"


def test_api_play_granularity_priority_returns_more_snapshots(client):
    step = client.get("/api/play?seed=0&max_turns=6&granularity=step").get_json()
    pri  = client.get("/api/play?seed=0&max_turns=6&granularity=priority").get_json()
    assert pri["granularity"] == "priority"
    assert pri["snapshot_count"] > step["snapshot_count"]


def test_api_play_invalid_granularity_400(client):
    resp = client.get("/api/play?granularity=bogus")
    assert resp.status_code == 400


def test_api_play_invalid_max_turns_400(client):
    resp = client.get("/api/play?max_turns=0")
    assert resp.status_code == 400


# Reveal-hands toggle (--reveal=all|p0|p1|none)


def test_api_play_default_reveal_is_all(client):
    body = client.get("/api/play?seed=0&max_turns=4").get_json()
    assert body["reveal"] == "all"


def test_api_play_reveal_none_strips_both_hands(client):
    play = client.get("/api/play?seed=0&max_turns=4&reveal=none").get_json()
    snap = client.get(f"/api/snapshot/{play['game_id']}/0").get_json()
    for p in snap["players"]:
        assert p["hand"] == []
        # hand_size still tells us how many are hidden
        assert p["hand_size"] >= 0


def test_api_play_reveal_p0_strips_p1_hand_only(client):
    play = client.get("/api/play?seed=0&max_turns=4&reveal=p0").get_json()
    snap = client.get(f"/api/snapshot/{play['game_id']}/0").get_json()
    p0 = next(p for p in snap["players"] if p["id"] == 0)
    p1 = next(p for p in snap["players"] if p["id"] == 1)
    assert len(p0["hand"]) == p0["hand_size"]
    assert p1["hand"] == []
    assert p1["hand_size"] > 0


def test_api_play_reveal_p1_strips_p0_hand_only(client):
    play = client.get("/api/play?seed=0&max_turns=4&reveal=p1").get_json()
    snap = client.get(f"/api/snapshot/{play['game_id']}/0").get_json()
    p0 = next(p for p in snap["players"] if p["id"] == 0)
    p1 = next(p for p in snap["players"] if p["id"] == 1)
    assert p0["hand"] == []
    assert len(p1["hand"]) == p1["hand_size"]


def test_api_play_invalid_reveal_400(client):
    resp = client.get("/api/play?reveal=both")
    assert resp.status_code == 400


def test_api_play_invalid_seed_returns_400(client):
    resp = client.get("/api/play?seed=not-a-number")
    assert resp.status_code == 400


def test_api_play_invalid_max_turns_non_integer_returns_400(client):
    resp = client.get("/api/play?max_turns=abc")
    assert resp.status_code == 400


def test_api_play_empty_seed_uses_default(client):
    resp = client.get("/api/play?seed=")
    assert resp.status_code == 200


def test_api_play_is_deterministic_on_seed(client):
    a = client.get("/api/play?seed=42&c1=G&c2=R").get_json()
    b = client.get("/api/play?seed=42&c1=G&c2=R").get_json()
    # Different game_ids (UUIDs) but same play outcome shape.
    assert a["turn_number"] == b["turn_number"]
    assert a["winner_id"] == b["winner_id"]
    assert a["is_draw"] == b["is_draw"]
    assert a["snapshot_count"] == b["snapshot_count"]


# ------------------------------------------------------------------------
# API integration flows — multi-endpoint round trips
# ------------------------------------------------------------------------


def test_api_integration_log_partition_covers_full_log(client):
    """Each snapshot carries log_since_last (events since the previous
    snapshot). Concatenating those partitions across the whole stream must
    exactly equal the final snapshot's cumulative log."""
    play = client.get("/api/play?seed=0&max_turns=6").get_json()
    partitions: list[str] = []
    final_log: list[str] = []
    for i in range(play["snapshot_count"]):
        snap = client.get(f"/api/snapshot/{play['game_id']}/{i}").get_json()
        assert isinstance(snap["log_since_last"], list)
        partitions.extend(snap["log_since_last"])
        final_log = snap["log"]
    assert partitions == final_log


def test_api_integration_first_snapshot_log_since_last_matches_initial_log(client):
    """The very first snapshot fires right after setup; log_since_last should
    equal whatever setup actions have put into the log so far (typically
    zero entries — deck building and shuffling are silent)."""
    play = client.get("/api/play?seed=0&max_turns=3").get_json()
    snap0 = client.get(f"/api/snapshot/{play['game_id']}/0").get_json()
    assert snap0["log_since_last"] == snap0["log"]


def test_api_integration_every_snapshot_has_valid_schema(client):
    """Play a short game, then walk every snapshot and verify invariants hold
    across the whole stream."""
    play = client.get("/api/play?seed=0&max_turns=8").get_json()
    for i in range(play["snapshot_count"]):
        snap = client.get(f"/api/snapshot/{play['game_id']}/{i}").get_json()
        assert isinstance(snap["turn_number"], int) and snap["turn_number"] >= 1
        assert len(snap["players"]) == 2
        assert {p["id"] for p in snap["players"]} == {0, 1}
        for p in snap["players"]:
            assert isinstance(p["life"], int)
            assert isinstance(p["hand_size"], int) and p["hand_size"] == len(p["hand"])
            for card in p["hand"] + p["exile"]:
                assert "name" in card and "scryfall_id" in card
            for obj in p["battlefield"]:
                assert "name" in obj and "scryfall_id" in obj
        for item in snap["stack"]:
            assert "name" in item and "scryfall_id" in item
        # Consistency: if game is over, either winner set or draw flagged.
        if snap["is_over"]:
            assert snap["is_draw"] or snap["winner_id"] is not None


def test_api_integration_multiple_games_remain_fetchable(client):
    """Two back-to-back /api/play calls both leave fetchable snapshot streams."""
    a = client.get("/api/play?seed=0&max_turns=5").get_json()
    b = client.get("/api/play?seed=1&max_turns=5").get_json()
    assert a["game_id"] != b["game_id"]
    assert client.get(f"/api/snapshot/{a['game_id']}/0").status_code == 200
    assert client.get(f"/api/snapshot/{b['game_id']}/0").status_code == 200
    assert client.get(f"/api/snapshot/{a['game_id']}/{a['snapshot_count'] - 1}").status_code == 200
    assert client.get(f"/api/snapshot/{b['game_id']}/{b['snapshot_count'] - 1}").status_code == 200


def test_api_integration_card_image_for_real_game_card(tmp_path):
    """End-to-end: play a real game, pick an enriched card, fetch its image,
    then fetch again and verify the cache hit (no second network call)."""
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return b"FAKE_JPG_BYTES"

    app = create_app(image_root=tmp_path, image_fetcher=fetcher)
    app.config["TESTING"] = True
    c = app.test_client()

    play = c.get("/api/play?seed=0&max_turns=10").get_json()
    # Walk snapshots until we find any card with a resolved scryfall_id.
    real_id = None
    for i in range(play["snapshot_count"]):
        snap = c.get(f"/api/snapshot/{play['game_id']}/{i}").get_json()
        for p in snap["players"]:
            for card in p["hand"] + p["battlefield"]:
                if card.get("scryfall_id"):
                    real_id = card["scryfall_id"]
                    break
            if real_id:
                break
        if real_id:
            break
    assert real_id, "expected at least one enriched card in a real game"

    # First fetch: downloads.
    resp = c.get(f"/card_image/{real_id}/small")
    assert resp.status_code == 200
    assert resp.data == b"FAKE_JPG_BYTES"
    assert len(calls) == 1

    # Second fetch: served from the disk cache, fetcher NOT called again.
    resp2 = c.get(f"/card_image/{real_id}/small")
    assert resp2.status_code == 200
    assert len(calls) == 1


def test_api_integration_game_cache_eviction_returns_404(tmp_path):
    """If an old game ages out of the LRU cache, its snapshots 404 cleanly."""
    cache = GameCache(max_entries=2)
    app = create_app(
        game_cache=cache, image_root=tmp_path,
        image_fetcher=lambda _u: b"x",
    )
    app.config["TESTING"] = True
    c = app.test_client()

    first = c.get("/api/play?seed=0&max_turns=3").get_json()
    c.get("/api/play?seed=1&max_turns=3").get_json()
    c.get("/api/play?seed=2&max_turns=3").get_json()  # evicts `first`
    resp = c.get(f"/api/snapshot/{first['game_id']}/0")
    assert resp.status_code == 404


def test_api_play_enriches_cards_with_scryfall_id(client):
    play = client.get("/api/play?seed=0&c1=G&c2=R&max_turns=6").get_json()
    # Find a snapshot that has some cards in hand.
    for idx in range(play["snapshot_count"]):
        snap = client.get(f"/api/snapshot/{play['game_id']}/{idx}").get_json()
        for p in snap["players"]:
            for c in p["hand"]:
                assert "scryfall_id" in c, "hand cards must carry scryfall_id"
                # Real EoE cards resolve to a uuid-like hex id; tokens / synthetic
                # fallbacks map to None.
                if c["scryfall_id"] is not None:
                    assert len(c["scryfall_id"]) == 36  # 8-4-4-4-12 uuid
                    return  # one confirmed hit is enough
    # If no hand was ever non-empty across the whole short game, that's the
    # failure — the scryfall_id path never got exercised.
    raise AssertionError("no hand cards appeared in any snapshot of the short game")


def test_api_snapshot_roundtrip_returns_state_dict(client):
    play = client.get("/api/play?seed=0&max_turns=3").get_json()
    game_id = play["game_id"]
    count = play["snapshot_count"]

    # First snapshot: turn 1, players set up, no battlefield.
    first = client.get(f"/api/snapshot/{game_id}/0").get_json()
    assert first["turn_number"] == 1
    assert len(first["players"]) == 2

    # Last snapshot: game_over or draw flag set.
    last = client.get(f"/api/snapshot/{game_id}/{count - 1}").get_json()
    assert last["is_over"] or last["is_draw"]


def test_api_snapshot_unknown_game_id_404(client):
    resp = client.get("/api/snapshot/deadbeef/0")
    assert resp.status_code == 404


def test_api_snapshots_index_returns_turn_and_step_per_snapshot(client):
    play = client.get("/api/play?seed=0&max_turns=5").get_json()
    idx = client.get(f"/api/snapshots_index/{play['game_id']}").get_json()
    assert isinstance(idx, list)
    assert len(idx) == play["snapshot_count"]
    for entry in idx:
        assert "turn_number" in entry
        assert "step" in entry
    # Turn numbers never decrease.
    turns = [e["turn_number"] for e in idx]
    assert all(b >= a for a, b in zip(turns, turns[1:]))


def test_api_snapshots_index_log_size_grows_monotonically(client):
    """Each index entry exposes log_size (cumulative len(state.log)) so the
    UI can binary-search "which snapshot first introduced log entry N"
    without fetching every snapshot's payload. Logs only grow, so the
    sequence must be non-decreasing."""
    play = client.get("/api/play?seed=0&max_turns=5").get_json()
    idx = client.get(f"/api/snapshots_index/{play['game_id']}").get_json()
    sizes = [e["log_size"] for e in idx]
    assert all(b >= a for a, b in zip(sizes, sizes[1:]))
    # And the final snapshot's log_size must match the actual final log
    # length, otherwise the binary search would miss late entries.
    last = client.get(
        f"/api/snapshot/{play['game_id']}/{play['snapshot_count'] - 1}"
    ).get_json()
    assert sizes[-1] == len(last["log"])


def test_api_snapshots_index_unknown_game_id_404(client):
    assert client.get("/api/snapshots_index/deadbeef").status_code == 404


def test_api_log_returns_full_game_log(client):
    """The viewer fetches the whole game's log once at activation so it
    can render every event (including future ones) with each line
    clickable to skip forward. Returns the final snapshot's log as
    the canonical full log."""
    play = client.get("/api/play?seed=0&max_turns=5").get_json()
    full = client.get(f"/api/log/{play['game_id']}").get_json()
    assert isinstance(full, list)
    assert all(isinstance(line, str) for line in full)
    # Final snapshot's log must match exactly.
    last = client.get(
        f"/api/snapshot/{play['game_id']}/{play['snapshot_count'] - 1}"
    ).get_json()
    assert full == last["log"]


def test_api_log_unknown_game_id_404(client):
    assert client.get("/api/log/deadbeef").status_code == 404


# ------------------------------------------------------------------------
# /api/recommend — engine-recommendation endpoint (stubbed)
# ------------------------------------------------------------------------


def test_api_recommend_returns_contract_shape(client):
    play = client.get("/api/play?seed=0&max_turns=4").get_json()
    resp = client.get(f"/api/recommend/{play['game_id']}/0")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["snapshot_idx"] == 0
    assert isinstance(body["priority_player_id"], int)
    assert isinstance(body["recommendations"], list)
    # The play endpoint now captures engine state clones, so the
    # recommend endpoint serves the PIMC-driven path. The legacy
    # "stub" engine is still reachable when a caller pre-populates
    # the cache without engine states (covered separately in
    # test_recommend.py).
    assert body["engine"] == "pimc"


def test_api_recommend_default_n_is_three(client):
    play = client.get("/api/play?seed=0&max_turns=4").get_json()
    # Find a snapshot where the priority player has a full hand so we
    # actually have options to rank.
    for i in range(play["snapshot_count"]):
        body = client.get(f"/api/recommend/{play['game_id']}/{i}").get_json()
        if len(body["recommendations"]) >= 3:
            assert len(body["recommendations"]) == 3
            return
    # If we never hit 3, the contract still holds (length <= n).


def test_api_recommend_respects_n_param(client):
    play = client.get("/api/play?seed=0&max_turns=4").get_json()
    body = client.get(f"/api/recommend/{play['game_id']}/0?n=1").get_json()
    assert len(body["recommendations"]) <= 1


def test_api_recommend_unknown_game_id_404(client):
    assert client.get("/api/recommend/deadbeef/0").status_code == 404


def test_api_recommend_out_of_range_idx_404(client):
    play = client.get("/api/play?seed=0&max_turns=4").get_json()
    resp = client.get(f"/api/recommend/{play['game_id']}/9999")
    assert resp.status_code == 404


def test_api_recommend_invalid_n_400(client):
    play = client.get("/api/play?seed=0&max_turns=4").get_json()
    assert client.get(f"/api/recommend/{play['game_id']}/0?n=abc").status_code == 400
    assert client.get(f"/api/recommend/{play['game_id']}/0?n=0").status_code == 400
    assert client.get(f"/api/recommend/{play['game_id']}/0?n=51").status_code == 400


def test_api_snapshot_out_of_range_404(client):
    play = client.get("/api/play?seed=0&max_turns=3").get_json()
    resp = client.get(f"/api/snapshot/{play['game_id']}/9999")
    assert resp.status_code == 404


def test_api_snapshot_negative_idx_404(client):
    # int converter in Flask rejects negative via URL parsing (no match).
    play = client.get("/api/play?seed=0&max_turns=3").get_json()
    resp = client.get(f"/api/snapshot/{play['game_id']}/-1")
    assert resp.status_code == 404


# ------------------------------------------------------------------------
# _enrich_snapshot (unit)
# ------------------------------------------------------------------------


def test_enrich_snapshot_tags_all_zones():
    name_to_id = {"Alpha": "sid-1", "Beta": "sid-2", "Gamma": "sid-3",
                  "Delta": "sid-4", "Epsilon": "sid-5"}
    snap = {
        "players": [
            {
                "hand": [{"name": "Alpha"}],
                "graveyard": [{"name": "Epsilon"}],
                "exile": [{"name": "Beta"}],
                "battlefield": [{"name": "Gamma"}],
            },
            {"hand": [], "graveyard": [], "exile": [], "battlefield": []},
        ],
        "stack": [{"name": "Delta"}],
    }
    out = _enrich_snapshot(snap, name_to_id)
    assert out["players"][0]["hand"][0]["scryfall_id"] == "sid-1"
    assert out["players"][0]["graveyard"][0]["scryfall_id"] == "sid-5"
    assert out["players"][0]["exile"][0]["scryfall_id"] == "sid-2"
    assert out["players"][0]["battlefield"][0]["scryfall_id"] == "sid-3"
    assert out["stack"][0]["scryfall_id"] == "sid-4"


def test_enrich_snapshot_unknown_name_maps_to_none():
    snap = {
        "players": [{"hand": [{"name": "Mystery"}], "graveyard": [],
                     "exile": [], "battlefield": []}],
        "stack": [],
    }
    out = _enrich_snapshot(snap, {"Alpha": "sid-1"})
    assert out["players"][0]["hand"][0]["scryfall_id"] is None


# ------------------------------------------------------------------------
# JSON API: /api/card
# ------------------------------------------------------------------------


def test_api_card_returns_metadata(fake_index, tmp_path):
    app = create_app(card_index=fake_index, image_root=tmp_path,
                     image_fetcher=lambda _u: b"X")
    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.get("/api/card/id-1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["name"] == "Alpha"
    assert body["mana_cost"] == "{1}{U}"
    assert body["colors"] == ["U"]
    assert body["image_sizes"] == ["normal", "small"]


def test_api_card_unknown_id_404(fake_index, tmp_path):
    app = create_app(card_index=fake_index, image_root=tmp_path,
                     image_fetcher=lambda _u: b"X")
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.get("/api/card/nope").status_code == 404


def test_api_card_missing_fields_default_to_none_or_empty(fake_index, tmp_path):
    app = create_app(card_index=fake_index, image_root=tmp_path,
                     image_fetcher=lambda _u: b"X")
    app.config["TESTING"] = True
    client = app.test_client()
    body = client.get("/api/card/id-2").get_json()  # Beta has no image/power/colors
    assert body["name"] == "Beta"
    assert body["power"] is None
    assert body["colors"] == []
    assert body["image_sizes"] == []


# ------------------------------------------------------------------------
# /card_image/<scryfall_id>/<size>
# ------------------------------------------------------------------------


def test_card_image_downloads_and_serves_bytes(img_client, tmp_path):
    resp = img_client.get("/card_image/id-1/small")
    assert resp.status_code == 200
    assert resp.data == b"IMGBYTES"
    # File was cached on disk.
    assert (tmp_path / "small" / "id-1.jpg").exists()


def test_card_image_cache_hit_does_not_refetch(img_client, tmp_path):
    # First request populates the cache.
    img_client.get("/card_image/id-1/small")
    # Overwrite the file so we can detect a refetch.
    (tmp_path / "small" / "id-1.jpg").write_bytes(b"CACHED")
    resp = img_client.get("/card_image/id-1/small")
    assert resp.status_code == 200
    assert resp.data == b"CACHED"


def test_card_image_bad_size_400(img_client):
    resp = img_client.get("/card_image/id-1/jumbo")
    assert resp.status_code == 400


def test_card_image_unknown_card_404(img_client):
    resp = img_client.get("/card_image/nope/small")
    assert resp.status_code == 404


def test_card_image_card_has_no_image_404(img_client):
    # Beta has no image_uris.
    resp = img_client.get("/card_image/id-2/small")
    assert resp.status_code == 404


# ------------------------------------------------------------------------
# GameCache (LRU semantics)
# ------------------------------------------------------------------------


def test_game_cache_stores_and_fetches():
    cache = GameCache()
    cache.store("a", [{"n": 1}])
    game = cache.get("a")
    assert game.snapshots == [{"n": 1}]
    assert game.engine_states == [None]  # default when not provided


def test_game_cache_miss_returns_none():
    assert GameCache().get("nope") is None


def test_game_cache_evicts_oldest_past_max():
    cache = GameCache(max_entries=2)
    cache.store("a", [{"x": "A"}])
    cache.store("b", [{"x": "B"}])
    cache.store("c", [{"x": "C"}])
    assert len(cache) == 2
    assert cache.get("a") is None
    assert cache.get("b") is not None
    assert cache.get("c") is not None


def test_game_cache_get_marks_as_recent():
    cache = GameCache(max_entries=2)
    cache.store("a", [{"x": "A"}])
    cache.store("b", [{"x": "B"}])
    cache.get("a")  # refresh A's recency
    cache.store("c", [{"x": "C"}])
    # Now B should have been evicted (oldest), not A.
    assert cache.get("a") is not None
    assert cache.get("b") is None
    assert cache.get("c") is not None


def test_game_cache_repeated_store_of_same_key_refreshes():
    cache = GameCache(max_entries=2)
    cache.store("a", [{"x": "A"}])
    cache.store("b", [{"x": "B"}])
    cache.store("a", [{"x": "A2"}])  # overwrite + promote
    cache.store("c", [{"x": "C"}])
    # Eviction kicks out B, not A.
    assert cache.get("a").snapshots == [{"x": "A2"}]
    assert cache.get("b") is None
    assert cache.get("c") is not None


def test_game_cache_stores_paired_engine_states():
    """When the caller passes engine_states alongside snapshots, both
    survive the round-trip and stay positionally aligned."""
    cache = GameCache()
    cache.store(
        "a",
        snapshots=[{"i": 0}, {"i": 1}],
        engine_states=["state-0", "state-1"],
    )
    game = cache.get("a")
    assert game.snapshots == [{"i": 0}, {"i": 1}]
    assert game.engine_states == ["state-0", "state-1"]


def test_game_cache_rejects_mismatched_lengths():
    import pytest
    cache = GameCache()
    with pytest.raises(ValueError, match="length"):
        cache.store(
            "a",
            snapshots=[{"i": 0}, {"i": 1}],
            engine_states=["just-one"],
        )


# ------------------------------------------------------------------------
# Back to the existing CLI + Tailscale tests
# ------------------------------------------------------------------------


def test_main_starts_app_with_cli_args(monkeypatch, capsys):
    captured: dict = {}

    def fake_run(self, host, port, debug):
        captured["host"] = host
        captured["port"] = port
        captured["debug"] = debug

    import flask
    monkeypatch.setattr(flask.Flask, "run", fake_run)
    monkeypatch.setattr(ui, "detect_tailscale_ip", lambda: None)

    main(["--host", "0.0.0.0", "--port", "9999"])

    assert captured == {"host": "0.0.0.0", "port": 9999, "debug": False}
    out = capsys.readouterr().out
    assert "http://localhost:9999" in out


# =====================================================================
# Replay loading endpoints (/api/list_replays, /api/load_replay)
# =====================================================================


def _fixture_replay_dir(tmp_path):
    """Drop a couple of valid replay files into a tmp dir for the
    list/load endpoints to discover."""
    from mtg_bot.replay import REPLAY_FORMAT_VERSION, Replay, save_replay
    replays_dir = tmp_path / "replays"
    save_replay(
        Replay(
            format_version=REPLAY_FORMAT_VERSION,
            metadata={"game_idx": 0, "winner": 0},
            snapshots=[
                {"turn_number": 1, "step": "untap", "is_over": False,
                 "players": [
                     {"id": 0, "life": 20, "hand": [], "graveyard": [],
                      "exile": [], "battlefield": []},
                     {"id": 1, "life": 20, "hand": [], "graveyard": [],
                      "exile": [], "battlefield": []},
                 ],
                 "stack": [], "log": []},
            ],
        ),
        replays_dir / "game_seed0_idx0000.json.gz",
    )
    save_replay(
        Replay(
            format_version=REPLAY_FORMAT_VERSION,
            metadata={"game_idx": 1, "winner": 1},
            snapshots=[
                {"turn_number": 1, "step": "untap", "is_over": False,
                 "players": [
                     {"id": 0, "life": 20, "hand": [], "graveyard": [],
                      "exile": [], "battlefield": []},
                     {"id": 1, "life": 20, "hand": [], "graveyard": [],
                      "exile": [], "battlefield": []},
                 ],
                 "stack": [], "log": []},
            ],
        ),
        replays_dir / "game_seed0_idx0001.json.gz",
    )
    return replays_dir


def _replay_client(tmp_path, fake_index):
    """Test client wired to a replay-aware app with the fixture dir."""
    replays_dir = _fixture_replay_dir(tmp_path)
    app = create_app(card_index=fake_index, replays_root=replays_dir)
    app.config["TESTING"] = True
    return app.test_client(), replays_dir


def test_list_replays_returns_filenames_in_order(tmp_path, fake_index):
    client, replays_dir = _replay_client(tmp_path, fake_index)
    body = client.get("/api/list_replays").get_json()
    assert body["replays"] == [
        "game_seed0_idx0000.json.gz",
        "game_seed0_idx0001.json.gz",
    ]
    assert body["root"] == str(replays_dir.resolve())


def test_list_replays_empty_when_no_dir(tmp_path, fake_index):
    """If replays_root doesn't exist, the endpoint should return
    {replays: []} rather than 404 — easier on the UI."""
    nonexistent = tmp_path / "nope"
    app = create_app(card_index=fake_index, replays_root=nonexistent)
    app.config["TESTING"] = True
    body = app.test_client().get("/api/list_replays").get_json()
    assert body["replays"] == []


def test_load_replay_creates_game_in_cache(tmp_path, fake_index):
    client, _ = _replay_client(tmp_path, fake_index)
    resp = client.get("/api/load_replay/game_seed0_idx0000.json.gz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "game_id" in body
    assert body["snapshot_count"] == 1
    assert body["metadata"]["game_idx"] == 0
    # Subsequent /api/snapshot/<game_id>/0 works (replay went into cache).
    snap = client.get(
        f"/api/snapshot/{body['game_id']}/0",
    ).get_json()
    assert snap["turn_number"] == 1


def test_load_replay_rejects_nonexistent_file(tmp_path, fake_index):
    client, _ = _replay_client(tmp_path, fake_index)
    resp = client.get("/api/load_replay/nope.json.gz")
    assert resp.status_code == 404


def test_load_replay_rejects_path_traversal(tmp_path, fake_index):
    client, _ = _replay_client(tmp_path, fake_index)
    # Forward slash, backslash, and leading-dot path components all
    # blocked at the validation layer.
    for bad in ("../escape.json.gz", "..\\escape.json.gz",
                ".hidden.json.gz"):
        resp = client.get(f"/api/load_replay/{bad}")
        assert resp.status_code == 400, (
            f"expected 400 for {bad!r}, got {resp.status_code}"
        )


def test_load_replay_rejects_wrong_extension(tmp_path, fake_index):
    client, _ = _replay_client(tmp_path, fake_index)
    resp = client.get("/api/load_replay/foo.txt")
    assert resp.status_code == 400


def test_list_replays_recursive_finds_subdir_files(tmp_path, fake_index):
    """iterate_alphazero writes replays into per-run subdirectories
    (replays/iter_001_self_play_v6/foo.json.gz). list_replays must
    surface them as POSIX-style relative subpaths so the load route
    can route through ``<path:filename>`` cleanly on any host OS."""
    from mtg_bot.replay import REPLAY_FORMAT_VERSION, Replay, save_replay
    replays_dir = tmp_path / "replays"
    sub = replays_dir / "iter_001_self_play_v6"
    sub.mkdir(parents=True)
    save_replay(
        Replay(
            format_version=REPLAY_FORMAT_VERSION,
            metadata={"game_idx": 0, "winner": 0},
            snapshots=[
                {"turn_number": 1, "step": "untap", "is_over": False,
                 "players": [
                     {"id": 0, "life": 20, "hand": [], "graveyard": [],
                      "exile": [], "battlefield": []},
                     {"id": 1, "life": 20, "hand": [], "graveyard": [],
                      "exile": [], "battlefield": []},
                 ],
                 "stack": [], "log": []},
            ],
        ),
        sub / "game_seed42_idx0000.json.gz",
    )
    app = create_app(card_index=fake_index, replays_root=replays_dir)
    app.config["TESTING"] = True
    body = app.test_client().get("/api/list_replays").get_json()
    assert "iter_001_self_play_v6/game_seed42_idx0000.json.gz" \
        in body["replays"]


def test_load_replay_accepts_subpath(tmp_path, fake_index):
    """Loading a per-run subpath like ``iter_001_self_play_v6/foo.json.gz``
    must succeed and put the replay in the cache."""
    from mtg_bot.replay import REPLAY_FORMAT_VERSION, Replay, save_replay
    replays_dir = tmp_path / "replays"
    sub = replays_dir / "iter_001_self_play_v6"
    sub.mkdir(parents=True)
    save_replay(
        Replay(
            format_version=REPLAY_FORMAT_VERSION,
            metadata={"game_idx": 0, "winner": 0},
            snapshots=[
                {"turn_number": 1, "step": "untap", "is_over": False,
                 "players": [
                     {"id": 0, "life": 20, "hand": [], "graveyard": [],
                      "exile": [], "battlefield": []},
                     {"id": 1, "life": 20, "hand": [], "graveyard": [],
                      "exile": [], "battlefield": []},
                 ],
                 "stack": [], "log": []},
            ],
        ),
        sub / "game_seed42_idx0000.json.gz",
    )
    app = create_app(card_index=fake_index, replays_root=replays_dir)
    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.get(
        "/api/load_replay/iter_001_self_play_v6/game_seed42_idx0000.json.gz",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "game_id" in body
    assert body["snapshot_count"] == 1


def test_load_replay_rejects_dotdot_component(tmp_path, fake_index):
    """Even though forward slashes are now allowed, an explicit ..
    component must still be rejected (defense in depth)."""
    client, _ = _replay_client(tmp_path, fake_index)
    resp = client.get("/api/load_replay/sub/../game_seed0_idx0000.json.gz")
    # Werkzeug may normalize the URL before routing; either 400 or
    # 404 is acceptable as long as the request doesn't succeed.
    assert resp.status_code in (400, 404)
