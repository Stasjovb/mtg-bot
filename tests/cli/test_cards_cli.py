"""``mtg_bot cards`` (card IR export / round-trip check)."""

from __future__ import annotations

import json

import pytest

from mtg_bot.cli import cards as cards_cli
from mtg_bot.cli import main as cli_main


def test_export_ir_writes_document_and_schema(tmp_path, capsys):
    rc = cards_cli.main(["export-ir", "--pool", "cube", "--out", str(tmp_path)])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["cards"] == 546 and summary["pool"] == "cube"
    doc = json.loads((tmp_path / "powerlsv.ir.json").read_text(encoding="utf-8"))
    schema = json.loads((tmp_path / "powerlsv.schema.json").read_text(encoding="utf-8"))
    assert doc["schema_sha256"] == summary["schema_sha256"]
    assert schema["format"] == "mtg-bot-card-ir-schema"
    assert 0 < summary["ir_gzip_bytes"] < summary["ir_bytes"]


def test_export_ir_name_override_and_dispatcher(tmp_path):
    cli_main(["cards", "export-ir", "--pool", "cube", "--out", str(tmp_path), "--name", "x"])
    assert (tmp_path / "x.ir.json").exists() and (tmp_path / "x.schema.json").exists()


def test_python_dash_m_mtg_bot_dispatches(tmp_path):
    from mtg_bot.__main__ import main

    main(["cards", "export-ir", "--pool", "cube", "--out", str(tmp_path)])
    assert (tmp_path / "powerlsv.ir.json").exists()


def test_roundtrip_reports_ok(capsys):
    assert cards_cli.main(["roundtrip", "--pool", "cube"]) == 0
    assert "cube: 546 cards" in capsys.readouterr().out


def test_roundtrip_reports_mismatches(monkeypatch):
    from mtg_bot.cards import ir

    monkeypatch.setattr(ir, "strict_equal", lambda a, b: False)
    problems = cards_cli.roundtrip(["cube"])
    assert problems and "differ after decode" in problems[0]
    assert cards_cli.main(["roundtrip", "--pool", "cube"]) == 1


def test_unknown_action_is_an_argparse_error():
    with pytest.raises(SystemExit):
        cards_cli.main(["frobnicate"])
