"""Round-trip + error-path tests for the Python <-> Rust card bridge.

Each test builds a card definition as a plain Python dict, registers
it through `mtg_bot_engine.Registry.register_printing`, then queries
the registry to make sure the parsed-and-re-emitted dict matches the
input shape. The bridge is the single point of validation, so the
error cases below cover each rejection path.
"""

from __future__ import annotations

import pytest

mtg_bot_engine = pytest.importorskip(
    "mtg_bot_engine",
    reason="rust extension not built; run `maturin develop --release -m rust/Cargo.toml`",
)


SHOCK = {
    "name": "Shock",
    "mana_cost": {"R": 1},
    "effects": [
        {"kind": "deal_damage", "amount": 2, "target": {"kind": "any_creature"}}
    ],
}

LIGHTNING_BOLT_ISH = {
    "name": "Lightning Bolt-ish",
    "mana_cost": {"R": 1},
    "effects": [
        {"kind": "deal_damage", "amount": 3, "target": {"kind": "any_player"}}
    ],
}

VANILLA_BLANK = {
    "name": "Blank Card",
}


def test_registry_starts_empty():
    reg = mtg_bot_engine.Registry()
    assert len(reg) == 0


def test_register_printing_returns_sequential_ids():
    reg = mtg_bot_engine.Registry()
    assert reg.register_printing(SHOCK) == 0
    assert reg.register_printing(LIGHTNING_BOLT_ISH) == 1
    assert reg.register_printing(VANILLA_BLANK) == 2
    assert len(reg) == 3


def test_round_trip_shock():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(SHOCK)
    assert reg.get_printing_name(pid) == "Shock"
    assert dict(reg.get_printing_mana_cost(pid)) == {"R": 1}
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert len(effects) == 1
    e = effects[0]
    assert e["kind"] == "deal_damage"
    assert e["amount"] == 2
    assert dict(e["target"]) == {"kind": "any_creature"}


def test_round_trip_any_player_target():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(LIGHTNING_BOLT_ISH)
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert dict(effects[0]["target"]) == {"kind": "any_player"}


def test_vanilla_card_with_no_mana_cost_or_effects():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(VANILLA_BLANK)
    assert reg.get_printing_name(pid) == "Blank Card"
    assert dict(reg.get_printing_mana_cost(pid)) == {}
    assert reg.get_printing_effects(pid) == []


def test_multi_color_mana_cost_round_trips():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Niv-Mizzet-ish",
            "mana_cost": {"generic": 4, "U": 1, "R": 1},
        }
    )
    assert dict(reg.get_printing_mana_cost(pid)) == {"generic": 4, "U": 1, "R": 1}


def test_zero_mana_cost_keys_are_omitted_on_round_trip():
    """Round-trip drops zero counts — `{R: 0}` registers as nothing."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing({"name": "Zero", "mana_cost": {"R": 0, "G": 2}})
    assert dict(reg.get_printing_mana_cost(pid)) == {"G": 2}


def test_multiple_effects_preserve_order():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Two Bolts",
            "effects": [
                {"kind": "deal_damage", "amount": 1, "target": {"kind": "any_player"}},
                {"kind": "deal_damage", "amount": 2, "target": {"kind": "any_creature"}},
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert [e["amount"] for e in effects] == [1, 2]
    assert [dict(e["target"])["kind"] for e in effects] == [
        "any_player",
        "any_creature",
    ]


# --- error paths -------------------------------------------------


def test_missing_name_raises_key_error():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="name"):
        reg.register_printing({"mana_cost": {"R": 1}})


def test_missing_effect_kind_raises_key_error():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="kind"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"amount": 2}]}
        )


def test_unknown_effect_kind_raises_value_error():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="unknown effect kind"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "summon_unicorn"}]}
        )


def test_unknown_target_kind_raises_value_error():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="unknown target filter kind"):
        reg.register_printing(
            {
                "name": "Broken",
                "effects": [
                    {
                        "kind": "deal_damage",
                        "amount": 2,
                        "target": {"kind": "any_planeswalker"},
                    }
                ],
            }
        )


def test_unknown_mana_color_raises_value_error():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="unknown mana_cost key"):
        reg.register_printing({"name": "Broken", "mana_cost": {"Q": 1}})


def test_lookup_out_of_range_id_raises_key_error():
    reg = mtg_bot_engine.Registry()
    reg.register_printing(SHOCK)
    with pytest.raises(KeyError, match="no printing with id 99"):
        reg.get_printing_name(99)
    with pytest.raises(KeyError):
        reg.get_printing_mana_cost(99)
    with pytest.raises(KeyError):
        reg.get_printing_effects(99)


def test_target_must_be_a_dict():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="target must be a dict"):
        reg.register_printing(
            {
                "name": "Broken",
                "effects": [{"kind": "deal_damage", "amount": 2, "target": "any"}],
            }
        )


def test_mana_cost_value_must_be_non_negative_integer():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="non-negative integer"):
        reg.register_printing({"name": "Broken", "mana_cost": {"R": "hot"}})


# --- bench helper ------------------------------------------------


def test_register_n_times_micros_returns_positive():
    reg = mtg_bot_engine.Registry()
    micros = reg.register_n_times_micros(SHOCK, 100)
    assert micros > 0.0
    # Sanity bound: parsing one Shock-like dict shouldn't exceed
    # ~50us even on a slow box; release-mode CPython is usually
    # under 5us.
    assert micros < 200.0, f"register too slow: {micros:.2f}us"
