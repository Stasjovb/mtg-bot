"""``mtg_bot.cube_decks`` + ``scripts/build_cube_deck_pool.py``."""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

import pytest

from mtg_bot import cube_decks as cd
from mtg_bot.decks import decks_from_json

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_cube_deck_pool.py"


def _card(name, colors, mana_cost="", type_line="Creature — Test"):
    return {"name": name, "color_identity": list(colors), "mana_cost": mana_cost, "type_line": type_line}


def _pool(n_per_color=5):
    cards = []
    for c in cd.COLORS:
        for i in range(n_per_color):
            cards.append(_card(f"{c}{i}", c, mana_cost=f"{{{i}}}{{{c}}}"))
    for i in range(n_per_color):
        cards.append(_card(f"A{i}", "", mana_cost=f"{{{i}}}", type_line="Artifact"))
    cards.append(_card("WU gold", "WU", mana_cost="{W}{U}"))
    cards.append(_card("Dual", "WU", type_line="Land"))
    cards.append(_card("MDFC", "W", mana_cost="{W}", type_line="Creature — Cleric // Land"))
    return cards


def test_colored_pips_counts_hybrid_and_ignores_generic():
    pips = cd.colored_pips("{2}{W}{W}{U/B}{X}{C}")
    assert pips == {"W": 2, "U": 1, "B": 1}
    assert cd.colored_pips("") == {}


def test_is_land_front_face_only():
    assert cd.is_land(_card("L", "", type_line="Land"))
    assert not cd.is_land(_card("M", "W", type_line="Creature — X // Land"))


def test_eligible_spells_filters_claimed_color_and_lands():
    cards = _pool(2)
    claimed = {c["name"] for c in cards} - {"W0"}
    names = {c["name"] for c in cd.eligible_spells(cards, "WU", claimed)}
    assert names == {"W1", "U0", "U1", "A0", "A1", "WU gold", "MDFC"}


def test_basic_land_split_proportional_and_exact():
    spells = [_card("a", "W", "{W}{W}{W}"), _card("b", "U", "{U}")]
    lands = cd.basic_land_split(spells, "WU", 17)
    assert len(lands) == 17
    assert lands.count("Plains") == 12 and lands.count("Island") == 5


def test_basic_land_split_no_pips_is_even():
    lands = cd.basic_land_split([_card("a", "", "{3}")], "BR", 17)
    assert sorted({lands.count("Swamp"), lands.count("Mountain")}) == [8, 9]


def test_feasibility_reports():
    cards = _pool(5)
    reports = cd.feasibility(cards, [c["name"] for c in cards], combos=("WU", "BR"), n_spells=12)
    by = {r.colors: r for r in reports}
    assert by["WU"].eligible == 17 and by["WU"].feasible  # 5+5+5 artifacts+gold+MDFC
    assert by["BR"].eligible == 15 and by["BR"].feasible


def test_build_deck_shape_and_singleton():
    cards = _pool(6)
    claimed = [c["name"] for c in cards]
    deck = cd.build_deck(cards, "UG", claimed, random.Random(1), n_spells=12, n_lands=8, deck_id="d")
    assert deck.card_count == 20 and deck.main_colors == "UG" and deck.draft_id == "d"
    spells = [n for n in deck.cards if n not in ("Island", "Forest")]
    assert len(spells) == 12 and len(set(spells)) == 12
    assert "Dual" not in deck.cards
    assert deck.cards == sorted(deck.cards)


def test_build_deck_insufficient_is_loud():
    cards = _pool(2)
    with pytest.raises(cd.InsufficientCoverageError, match="WU: only"):
        cd.build_deck(cards, "WU", [c["name"] for c in cards], random.Random(0), n_spells=23)


def test_build_deck_pool_cycles_and_is_deterministic():
    cards = _pool(6)
    claimed = [c["name"] for c in cards]
    a = cd.build_deck_pool(cards, claimed, n_decks=4, seed=7, combos=("WU", "BR"), n_spells=10, n_lands=7)
    b = cd.build_deck_pool(cards, claimed, n_decks=4, seed=7, combos=("WU", "BR"), n_spells=10, n_lands=7)
    assert [d.cards for d in a] == [d.cards for d in b]
    assert [d.main_colors for d in a] == ["WU", "BR", "WU", "BR"]
    assert [d.draft_id for d in a] == ["cube-WU-00000", "cube-BR-00001", "cube-WU-00002", "cube-BR-00003"]


def test_build_deck_pool_rejects_any_infeasible_combo():
    cards = _pool(6)
    claimed = [c["name"] for c in cards if not c["name"].startswith("B")]
    # BR has R0-5 + A0-5 = 12 eligible; WU has 20.
    with pytest.raises(cd.InsufficientCoverageError, match="1 of 2 color combos.*BR=12/13"):
        cd.build_deck_pool(cards, claimed, n_decks=2, combos=("WU", "BR"), n_spells=13)


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("_build_cube_deck_pool_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_script_report_mode(script, capsys):
    rc = script.main(["--report", "--combos", "UR", "--n-spells", "5"])
    out = capsys.readouterr().out
    assert rc == 0 and "ok  UR" in out and "claimed cube cards:" in out


def test_script_writes_pool_when_feasible(script, tmp_path):
    out = tmp_path / "decks.json.gz"
    rc = script.main(["--combos", "UR", "UG", "--n-spells", "5", "--n-lands", "3",
                      "--n-decks", "4", "--out", str(out)])
    assert rc == 0
    decks = decks_from_json(out)
    assert len(decks) == 4 and all(d.card_count == 8 for d in decks)


def test_script_infeasible_fails_loudly(script, tmp_path, capsys):
    out = tmp_path / "decks.json.gz"
    rc = script.main(["--combos", "WB", "--n-spells", "500", "--out", str(out)])
    assert rc == 1 and not out.exists()
    assert "ERROR" in capsys.readouterr().err
