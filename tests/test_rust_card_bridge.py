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


def test_round_trip_draw_cards_effect():
    """Round-8 bridge extension: DrawCards { count } effect."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Concentrate-ish",
            "mana_cost": {"U": 2, "generic": 2},
            "card_types": ["Sorcery"],
            "effects": [{"kind": "draw_cards", "count": 3}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert len(effects) == 1
    e = effects[0]
    assert e["kind"] == "draw_cards"
    assert e["count"] == 3


def test_round_trip_gain_life_effect():
    """Round-8 bridge extension: GainLife { amount } effect."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Healing Salve-ish",
            "mana_cost": {"W": 1},
            "card_types": ["Instant"],
            "effects": [{"kind": "gain_life", "amount": 3}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert len(effects) == 1
    e = effects[0]
    assert e["kind"] == "gain_life"
    assert e["amount"] == 3


def test_round_trip_multiple_effect_kinds_preserve_order():
    """Round-8 sanity: multiple variants of Effect can land on one card."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Mixed Spell",
            "effects": [
                {"kind": "draw_cards", "count": 1},
                {"kind": "gain_life", "amount": 2},
                {"kind": "deal_damage", "amount": 1, "target": {"kind": "any_player"}},
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert [e["kind"] for e in effects] == ["draw_cards", "gain_life", "deal_damage"]


def test_draw_cards_missing_count_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="count"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "draw_cards"}]}
        )


def test_gain_life_missing_amount_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="amount"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "gain_life"}]}
        )


def test_round_trip_return_to_hand_effect():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Unsummon-ish",
            "mana_cost": {"U": 1},
            "card_types": ["Instant"],
            "effects": [
                {"kind": "return_to_hand", "target": {"kind": "any_creature"}}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "return_to_hand"
    assert dict(effects[0]["target"]) == {"kind": "any_creature"}


def test_round_trip_mill_effect():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Tome Scour-ish",
            "mana_cost": {"U": 1},
            "card_types": ["Sorcery"],
            "effects": [{"kind": "mill", "count": 5}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "mill", "count": 5}


def test_return_to_hand_missing_target_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="target"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "return_to_hand"}]}
        )


def test_mill_missing_count_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="count"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "mill"}]}
        )


def test_round_trip_exile_target_effect():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Path-ish",
            "mana_cost": {"W": 1},
            "card_types": ["Instant"],
            "effects": [
                {"kind": "exile_target", "target": {"kind": "any_creature"}}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "exile_target"
    assert dict(effects[0]["target"]) == {"kind": "any_creature"}


def test_exile_target_missing_target_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="target"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "exile_target"}]}
        )


def test_round_trip_tap_target_effect():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Twiddle-ish",
            "mana_cost": {"U": 1},
            "card_types": ["Instant"],
            "effects": [
                {"kind": "tap_target", "target": {"kind": "any_creature"}}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "tap_target"
    assert dict(effects[0]["target"]) == {"kind": "any_creature"}


def test_tap_target_missing_target_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="target"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "tap_target"}]}
        )


def test_round_trip_untap_target_effect():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Untap-ish",
            "mana_cost": {"U": 1},
            "card_types": ["Instant"],
            "effects": [
                {"kind": "untap_target", "target": {"kind": "any_creature"}}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "untap_target"
    assert dict(effects[0]["target"]) == {"kind": "any_creature"}


def test_untap_target_missing_target_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="target"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "untap_target"}]}
        )


def test_round_trip_sacrifice_effect():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Sacrifice-ish",
            "mana_cost": {"B": 1},
            "card_types": ["Instant"],
            "effects": [
                {"kind": "sacrifice", "target": {"kind": "any_creature"}}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "sacrifice"
    assert dict(effects[0]["target"]) == {"kind": "any_creature"}


def test_sacrifice_missing_target_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="target"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "sacrifice"}]}
        )


def test_round_trip_add_counters_effect():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Counterspell-ish-buff",
            "mana_cost": {"G": 1},
            "card_types": ["Instant"],
            "effects": [
                {"kind": "add_counters", "count": 2, "target": {"kind": "any_creature"}}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "add_counters"
    assert effects[0]["count"] == 2
    assert dict(effects[0]["target"]) == {"kind": "any_creature"}


def test_add_counters_missing_count_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="count"):
        reg.register_printing(
            {
                "name": "Broken",
                "effects": [
                    {"kind": "add_counters", "target": {"kind": "any_creature"}}
                ],
            }
        )


def test_add_counters_missing_target_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="target"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "add_counters", "count": 1}]}
        )


def test_round_trip_discard_card_effect():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Distress-ish",
            "mana_cost": {"B": 1},
            "card_types": ["Sorcery"],
            "effects": [
                {"kind": "discard_card", "target": {"kind": "any_player"}}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "discard_card"
    assert dict(effects[0]["target"]) == {"kind": "any_player"}


def test_discard_card_missing_target_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="target"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "discard_card"}]}
        )


def test_negative_add_counters_round_trips():
    """-1/-1 counters via negative count — same Effect, same dispatch."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Wither-ish",
            "effects": [
                {"kind": "add_counters", "count": -1, "target": {"kind": "any_creature"}}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["count"] == -1


def test_round_trip_scry_n_effect():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Preordain-ish",
            "mana_cost": {"U": 1},
            "card_types": ["Sorcery"],
            "effects": [{"kind": "scry_n", "count": 2}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "scry_n"
    assert effects[0]["count"] == 2


def test_scry_n_missing_count_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="count"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "scry_n"}]}
        )


def test_scry_n_zero_count_round_trips():
    """Scry 0 is a degenerate but legal value — should round-trip."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "ScryZero",
            "effects": [{"kind": "scry_n", "count": 0}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["count"] == 0


def test_round_trip_destroy_target_effect():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Doom-Blade-ish",
            "mana_cost": {"B": 1, "generic": 1},
            "card_types": ["Instant"],
            "effects": [
                {"kind": "destroy_target", "target": {"kind": "any_creature"}}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "destroy_target"
    assert dict(effects[0]["target"]) == {"kind": "any_creature"}


def test_destroy_target_missing_target_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="target"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "destroy_target"}]}
        )


def test_round_trip_damage_each_opponent_effect():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Pyroclasm-vs-Players-ish",
            "mana_cost": {"R": 1, "generic": 2},
            "card_types": ["Sorcery"],
            "effects": [{"kind": "damage_each_opponent", "amount": 2}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "damage_each_opponent"
    assert effects[0]["amount"] == 2


def test_damage_each_opponent_missing_amount_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="amount"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "damage_each_opponent"}]}
        )


def test_destroy_target_anyplayer_round_trips_for_validation_at_dispatch():
    """Bridge accepts AnyPlayer for destroy_target — the runtime
    semantic rejection (you can't destroy a player) lives in
    apply_effect, not the parser."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "InvalidTargetPersists",
            "effects": [
                {"kind": "destroy_target", "target": {"kind": "any_player"}}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert dict(effects[0]["target"]) == {"kind": "any_player"}


def test_round_trip_damage_each_creature_effect():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Pyroclasm-ish",
            "mana_cost": {"R": 1, "generic": 1},
            "card_types": ["Sorcery"],
            "effects": [{"kind": "damage_each_creature", "amount": 2}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "damage_each_creature"
    assert effects[0]["amount"] == 2


def test_damage_each_creature_missing_amount_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="amount"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "damage_each_creature"}]}
        )


def test_damage_each_creature_zero_amount_round_trips():
    """Damage 0 to each creature is a degenerate but legal value."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "ZeroPyro",
            "effects": [{"kind": "damage_each_creature", "amount": 0}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["amount"] == 0


def test_round_trip_create_token_effect():
    """CR 701.6 — Servo/Soldier maker pattern.

    The token's stats live on a pre-registered token-printing; the
    effect just references it by id. Mirrors how creatures and
    instants reference their printings.
    """
    reg = mtg_bot_engine.Registry()
    # Pre-register the token printing (1/1 white Soldier, no cost).
    token_pid = reg.register_printing(
        {
            "name": "Soldier Token",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 1,
        }
    )
    # Register a sorcery that makes 2 Soldier tokens.
    sorcery_pid = reg.register_printing(
        {
            "name": "Conscript",
            "mana_cost": {"W": 1, "generic": 1},
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind": "create_token",
                    "count": 2,
                    "token_printing_id": token_pid,
                }
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(sorcery_pid)]
    assert effects[0]["kind"] == "create_token"
    assert effects[0]["count"] == 2
    assert effects[0]["token_printing_id"] == token_pid


def test_create_token_missing_count_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="count"):
        reg.register_printing(
            {
                "name": "Broken",
                "effects": [{"kind": "create_token", "token_printing_id": 0}],
            }
        )


def test_create_token_missing_printing_id_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="token_printing_id"):
        reg.register_printing(
            {
                "name": "Broken",
                "effects": [{"kind": "create_token", "count": 1}],
            }
        )


# --- AddManaToPool (round-23 effect-coverage slice) -----------------


def test_round_trip_add_mana_to_pool_effect():
    """CR 106.1 — mana ability resolution. Mana-rocks and basic-land
    mana abilities all flow through this Effect. Round-trip a single
    `{"kind": "add_mana_to_pool", "color": "G", "amount": 1}` entry
    on an EoE-shaped Forest-like printing."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Forest Mana Ability",
            "effects": [
                {"kind": "add_mana_to_pool", "color": "G", "amount": 1}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "add_mana_to_pool"
    assert effects[0]["color"] == "G"
    assert effects[0]["amount"] == 1


def test_round_trip_add_mana_to_pool_colorless():
    """A Mind-Stone-shaped mana-rock minting a single colorless coin —
    "C" is in the closed mana vocab and round-trips end-to-end."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Mind Stone Mana Ability",
            "effects": [
                {"kind": "add_mana_to_pool", "color": "C", "amount": 1}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {
        "kind": "add_mana_to_pool",
        "color": "C",
        "amount": 1,
    }


def test_add_mana_to_pool_missing_color_raises():
    """Schema validation: `color` is required, missing it raises
    KeyError loudly (no silent default-to-colorless fallback)."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="color"):
        reg.register_printing(
            {
                "name": "Broken",
                "effects": [{"kind": "add_mana_to_pool", "amount": 1}],
            }
        )


def test_add_mana_to_pool_missing_amount_raises():
    """Schema validation: `amount` is required, missing it raises
    KeyError loudly."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="amount"):
        reg.register_printing(
            {
                "name": "Broken",
                "effects": [{"kind": "add_mana_to_pool", "color": "G"}],
            }
        )


def test_add_mana_to_pool_invalid_color_raises():
    """Schema validation: `color` must be in W/U/B/R/G/C closed vocab.
    "X" is the protection-from-X target color, not a mana color —
    surface as ValueError at register time."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="unknown mana symbol"):
        reg.register_printing(
            {
                "name": "Broken",
                "effects": [
                    {"kind": "add_mana_to_pool", "color": "X", "amount": 1}
                ],
            }
        )


def test_add_mana_to_pool_negative_amount_raises_at_register_time():
    """Register-time guard on negative amounts (matches the
    apply_effect guard, surfaced earlier in the pipeline)."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(
            {
                "name": "Broken",
                "effects": [
                    {"kind": "add_mana_to_pool", "color": "G", "amount": -1}
                ],
            }
        )


# --- SearchLibraryForBasicLandTapped (round-23 effect-coverage slice) -


def test_round_trip_search_library_for_basic_land_tapped_effect():
    """CR 701.19 search + 701.22 shuffle — Rampant Growth /
    Beamsaw Prospector / Kavaron Harrier pattern. Round-trip the
    default-count effect through the bridge."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Rampant Growth-ish",
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind": "search_library_for_basic_land_tapped",
                    "count": 1,
                }
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {
        "kind": "search_library_for_basic_land_tapped",
        "count": 1,
    }


def test_round_trip_search_library_for_basic_land_tapped_count_two():
    """A Larval Scoutlander-shaped count=2 entry — bicycle/skyshroud
    pattern — round-trips with its count preserved."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Larval-ish",
            "effects": [
                {
                    "kind": "search_library_for_basic_land_tapped",
                    "count": 2,
                }
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "search_library_for_basic_land_tapped"
    assert effects[0]["count"] == 2


def test_search_library_for_basic_land_tapped_default_count_is_one():
    """Python's `SearchLibraryForBasicLandTapped(count: int = 1)`
    dataclass has count default to 1. The Rust parser mirrors that:
    an entry with no `count` key registers as count=1 and round-trips
    that way."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Default Count",
            "effects": [
                {"kind": "search_library_for_basic_land_tapped"}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {
        "kind": "search_library_for_basic_land_tapped",
        "count": 1,
    }


def test_search_library_for_basic_land_tapped_negative_count_raises():
    """Register-time guard on negative count (matches the
    apply_effect guard, surfaced earlier in the pipeline). Mirrors
    AddManaToPool's negative-amount register-time check."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(
            {
                "name": "Broken",
                "effects": [
                    {
                        "kind": "search_library_for_basic_land_tapped",
                        "count": -1,
                    }
                ],
            }
        )


# --- PutPlusOneCounterOnSelf (round-23 effect-coverage slice) --------


def test_round_trip_put_plus_one_counter_on_self_effect():
    """CR 122.6 + 701.13 — Blade of the Swarm / Atomic Microsizer
    pattern. Round-trip the default-amount effect through the bridge."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Self-Counter",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 1,
            "effects": [
                {
                    "kind": "put_plus_one_counter_on_self",
                    "amount": 1,
                }
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {
        "kind": "put_plus_one_counter_on_self",
        "amount": 1,
    }


def test_round_trip_put_plus_one_counter_on_self_amount_two():
    """An explicit amount=2 entry — for cards that drop two counters
    on themselves per activation — round-trips with its amount
    preserved."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Double Self-Counter",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 1,
            "effects": [
                {
                    "kind": "put_plus_one_counter_on_self",
                    "amount": 2,
                }
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "put_plus_one_counter_on_self"
    assert effects[0]["amount"] == 2


def test_put_plus_one_counter_on_self_default_amount_is_one():
    """Python's `PutPlusOneCounterOnSelf(amount: int = 1)` dataclass
    has amount default to 1. The Rust parser mirrors that: an entry
    with no `amount` key registers as amount=1 and round-trips that
    way."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Default Amount",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 1,
            "effects": [
                {"kind": "put_plus_one_counter_on_self"}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {
        "kind": "put_plus_one_counter_on_self",
        "amount": 1,
    }


def test_put_plus_one_counter_on_self_negative_amount_raises():
    """Register-time guard on negative amount (matches the
    apply_effect guard, surfaced earlier in the pipeline). Mirrors
    SearchLibraryForBasicLandTapped's / AddManaToPool's negative
    register-time check."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Creature"],
                "power": 1,
                "toughness": 1,
                "effects": [
                    {
                        "kind": "put_plus_one_counter_on_self",
                        "amount": -1,
                    }
                ],
            }
        )


def test_round_trip_surveil_effect():
    """CR 701.42 — Appendage Amalgam-style surveil N. Round-trip the
    happy-path effect through the bridge with count=2."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Surveil",
            "card_types": ["Sorcery"],
            "mana_cost": {"U": 1},
            "effects": [{"kind": "surveil", "count": 2}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "surveil", "count": 2}


def test_round_trip_surveil_count_zero():
    """Surveil 0 is a degenerate but legal value — should round-trip."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Surveil Zero",
            "effects": [{"kind": "surveil", "count": 0}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "surveil"
    assert effects[0]["count"] == 0


def test_round_trip_surveil_count_four():
    """A larger Surveil 4 (cycling-tier surveil) round-trips with its
    count preserved."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Big Surveil",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "surveil", "count": 4}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "surveil"
    assert effects[0]["count"] == 4


def test_surveil_missing_count_raises():
    """count is required at register time (no first-slice default —
    every printed Surveil has an explicit N). Mirrors ScryN's
    missing-count KeyError shape."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="count"):
        reg.register_printing(
            {"name": "Broken", "effects": [{"kind": "surveil"}]}
        )


def test_surveil_negative_count_raises():
    """Register-time guard on negative count (defense-in-depth; the
    apply_effect guard re-checks). Mirrors ScryN /
    SearchLibraryForBasicLandTapped's register-time negative check."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(
            {
                "name": "Broken Surveil",
                "effects": [{"kind": "surveil", "count": -1}],
            }
        )


def test_round_trip_counter_target_spell_effect():
    """CR 701.5 — Annul/Cancel-style counter-target-spell. Unit variant,
    no fields. Round-trip the happy-path effect dict through the
    bridge."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Annul",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
            "effects": [{"kind": "counter_target_spell"}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "counter_target_spell"}


def test_round_trip_counter_target_spell_ignores_extra_keys():
    """Python's `CounterTargetSpell.filter_types` is intentionally NOT
    mirrored in the Rust first slice — extra keys on the dict are
    silently ignored, matching the silent-drop convention elsewhere in
    the parser. Confirms the unit-variant shape doesn't accidentally
    require fields."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Counter With Filter",
            "card_types": ["Instant"],
            "mana_cost": {"U": 1},
            "effects": [
                {
                    "kind": "counter_target_spell",
                    "filter_types": ["Artifact", "Enchantment"],
                }
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    # Round-trip drops the unrecognized field — first slice doesn't
    # model filter_types, the round-trip is the unit-variant shape.
    assert effects[0] == {"kind": "counter_target_spell"}


def test_counter_target_spell_in_unknown_kind_error_string():
    """Defense-in-depth: the unknown-kind error message lists
    `counter_target_spell` in its valid-kinds enumeration so a future
    mis-typed kind helpfully surfaces the right name."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="counter_target_spell"):
        reg.register_printing(
            {
                "name": "Broken",
                "effects": [{"kind": "counter_unicorn_spell"}],
            }
        )


def test_round_trip_return_creature_from_your_graveyard_to_battlefield():
    """CR 400.7 + 302.1 — reanimation. Powers Emerge from the Cocoon
    pattern (8 EoE cards). Unit variant, no fields. Round-trip the
    happy-path effect dict through the bridge."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Reanimate",
            "card_types": ["Sorcery"],
            "mana_cost": {"B": 1},
            "effects": [
                {"kind": "return_creature_from_your_graveyard_to_battlefield"}
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {
        "kind": "return_creature_from_your_graveyard_to_battlefield"
    }


def test_round_trip_return_creature_from_graveyard_ignores_extra_keys():
    """Python's `ReturnCreatureFromYourGraveyardToBattlefield` inherits
    optional widening / capping fields (`or_enchantment`, `max_mv`,
    etc.) from `ReturnFromGraveyard`. These are intentionally NOT
    mirrored in the Rust first slice — extra keys on the dict are
    silently ignored, matching the silent-drop convention elsewhere
    in the parser. Confirms the unit-variant shape doesn't accidentally
    require fields."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Reanimate With Filter",
            "card_types": ["Sorcery"],
            "mana_cost": {"B": 1},
            "effects": [
                {
                    "kind": "return_creature_from_your_graveyard_to_battlefield",
                    "max_mv": 3,
                    "or_enchantment": True,
                }
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    # Round-trip drops the unrecognized fields — first slice doesn't
    # model the widening / capping shape, the round-trip is the
    # unit-variant shape.
    assert effects[0] == {
        "kind": "return_creature_from_your_graveyard_to_battlefield"
    }


def test_return_creature_from_graveyard_in_unknown_kind_error_string():
    """Defense-in-depth: the unknown-kind error message lists
    `return_creature_from_your_graveyard_to_battlefield` in its
    valid-kinds enumeration so a future mis-typed kind helpfully
    surfaces the right name."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(
        ValueError, match="return_creature_from_your_graveyard_to_battlefield"
    ):
        reg.register_printing(
            {
                "name": "Broken",
                "effects": [{"kind": "return_unicorn_from_graveyard"}],
            }
        )


def test_round_trip_discard_self_default_amount_is_one():
    """CR 701.8 — "you discard a card." Powers Irreverent Gremlin
    pattern (8 EoE cards). Python's
    `DiscardSelf(amount: int = 1)` dataclass has amount default to 1;
    the Rust parser mirrors that: an entry with no `amount` key
    registers as amount=1 and round-trips that way. Mirrors
    PutPlusOneCounterOnSelf's default-handling round-trip shape."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Irreverent Gremlin",
            "card_types": ["Creature"],
            "power": 1,
            "toughness": 1,
            "effects": [{"kind": "discard_self"}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "discard_self", "amount": 1}


def test_round_trip_discard_self_amount_two():
    """An explicit amount=2 entry — for cards that force two discards
    on resolution — round-trips with its amount preserved."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Double Discard",
            "card_types": ["Sorcery"],
            "mana_cost": {"B": 1},
            "effects": [{"kind": "discard_self", "amount": 2}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "discard_self", "amount": 2}


def test_discard_self_negative_amount_raises():
    """Register-time guard on negative amount (matches the
    apply_effect guard, surfaced earlier in the pipeline). Mirrors
    PutPlusOneCounterOnSelf / SearchLibraryForBasicLandTapped /
    AddManaToPool negative register-time check."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Sorcery"],
                "effects": [{"kind": "discard_self", "amount": -1}],
            }
        )


def test_discard_self_in_unknown_kind_error_string():
    """Defense-in-depth: the unknown-kind error message lists
    `discard_self` in its valid-kinds enumeration so a future
    mis-typed kind helpfully surfaces the right name."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="discard_self"):
        reg.register_printing(
            {
                "name": "Broken",
                "effects": [{"kind": "discard_themself"}],
            }
        )


# --- round-26: EachOpponentLosesLife round-trip + error paths --------
#
# CR 118.4 — life loss (not damage). Powers Balemurk Leech pattern
# (6 EoE cards). Distinct from DamageEachOpponent — life-loss isn't
# reducible by damage-prevention effects; two-player engine first
# slice end-state matches DamageEachOpponent on the defender's life,
# but the variants stay separate to mirror Python's
# `EachOpponentLosesLife(amount: int)` dataclass shape.


def test_round_trip_each_opponent_loses_life_amount_two():
    """Happy path: amount=2 round-trips faithfully. Mirrors Python's
    `EachOpponentLosesLife(amount: int)` dataclass shape — required
    `amount` field with no default."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Balemurk Leech",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"B": 1, "generic": 1},
            "effects": [{"kind": "each_opponent_loses_life", "amount": 2}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "each_opponent_loses_life", "amount": 2}


def test_round_trip_each_opponent_loses_life_amount_zero():
    """amount=0 is a legal no-op shape (mirrors GainLife / DrawCards /
    Mill / DamageEachOpponent / DiscardSelf zero-amount round-trip
    conventions). Registers and round-trips without error."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Zero Drain",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "each_opponent_loses_life", "amount": 0}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "each_opponent_loses_life", "amount": 0}


def test_each_opponent_loses_life_missing_amount_raises():
    """Python's `EachOpponentLosesLife(amount: int)` has no default —
    the Rust parser mirrors that: omitting `amount` raises KeyError
    at register time (defense-in-depth, surfaced earlier in the
    pipeline than the resolve guard). Distinct from DiscardSelf /
    PutPlusOneCounterOnSelf which default to amount=1."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="amount"):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Sorcery"],
                "effects": [{"kind": "each_opponent_loses_life"}],
            }
        )


def test_each_opponent_loses_life_negative_amount_raises():
    """Register-time guard on negative amount (matches the
    apply_effect guard, surfaced earlier in the pipeline). Mirrors
    DamageEachOpponent / DiscardSelf / PutPlusOneCounterOnSelf
    negative register-time check shape — 'lose -2 life' is schema
    nonsense."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Sorcery"],
                "effects": [{"kind": "each_opponent_loses_life", "amount": -1}],
            }
        )


# --- LoseLife round-trip + error paths -----------------------------
#
# CR 118.4 — life loss (not damage). Powers the Decode Transmissions
# pattern (7 EoE cards) — the SOURCE's controller pays a life cost on
# resolution. Distinct from `each_opponent_loses_life` (round 26): the
# round-trip shape is identical (required `amount` field), but the
# DISPATCH subtracts from the source's CONTROLLER's life, not the
# opponent's. Mirrors Python's `LoseLife(amount: int)` dataclass shape.


def test_round_trip_lose_life_amount_two():
    """Happy path: amount=2 round-trips faithfully. Mirrors Python's
    `LoseLife(amount: int)` dataclass shape — required `amount` field
    with no default."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Decode Transmissions",
            "card_types": ["Sorcery"],
            "mana_cost": {"U": 1, "generic": 2},
            "effects": [{"kind": "lose_life", "amount": 2}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "lose_life", "amount": 2}


def test_round_trip_lose_life_amount_zero():
    """amount=0 is a legal no-op shape (mirrors GainLife / DrawCards /
    Mill / EachOpponentLosesLife / DiscardSelf zero-amount round-trip
    conventions). Registers and round-trips without error."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Zero Drawback",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "lose_life", "amount": 0}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "lose_life", "amount": 0}


def test_lose_life_missing_amount_raises():
    """Python's `LoseLife(amount: int)` has no default — the Rust
    parser mirrors that: omitting `amount` raises KeyError at register
    time (defense-in-depth, surfaced earlier than the resolve guard).
    Mirrors EachOpponentLosesLife / DamageEachOpponent shape — distinct
    from DiscardSelf / PutPlusOneCounterOnSelf which default to
    amount=1."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="amount"):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Sorcery"],
                "effects": [{"kind": "lose_life"}],
            }
        )


def test_lose_life_negative_amount_raises():
    """Register-time guard on negative amount (matches the apply_effect
    guard, surfaced earlier in the pipeline). Mirrors
    EachOpponentLosesLife / DamageEachOpponent / DiscardSelf negative
    register-time check shape — 'lose -2 life' is schema nonsense
    (use GainLife for raising life totals)."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Sorcery"],
                "effects": [{"kind": "lose_life", "amount": -1}],
            }
        )


# --- DestroyTargetNonlandPermanent round-trip ---------------------
#
# Round-25 bridge ext: closed-vocabulary unit variant mirroring
# Python's `DestroyTargetNonlandPermanent` (a `Destroy` subclass with
# the filter `~IsLand() & ~IsPlayer()` baked in). 2 cards in the EoE
# pool per round-20 measurement (Drag to the Roots / Drill Too Deep
# pattern). Distinct from round-17 `destroy_target` by applying a
# Land-skip filter at scan time on the dispatch side.


def test_round_trip_destroy_target_nonland_permanent_unit_variant():
    """Happy path: unit-variant round-trips as a single `kind` key
    with no extra fields. Mirrors `counter_target_spell` /
    `return_creature_from_your_graveyard_to_battlefield` unit-variant
    round-trip shape."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Drag to the Roots",
            "card_types": ["Sorcery"],
            "mana_cost": {"G": 1, "generic": 2},
            "effects": [{"kind": "destroy_target_nonland_permanent"}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "destroy_target_nonland_permanent"}


def test_round_trip_destroy_target_nonland_permanent_extra_keys_ignored():
    """Silent-drop convention for unrecognized keys on a unit variant
    (matches `counter_target_spell` /
    `return_creature_from_your_graveyard_to_battlefield`'s parser
    shape). An accidental `target` key on the registered dict does NOT
    raise — the parser ignores it and round-trips a bare unit dict."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Drill Too Deep",
            "card_types": ["Instant"],
            "mana_cost": {"B": 1, "generic": 2},
            "effects": [
                {
                    "kind": "destroy_target_nonland_permanent",
                    "target": {"kind": "any_creature"},  # ignored
                }
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "destroy_target_nonland_permanent"}


def test_destroy_target_nonland_permanent_in_multi_effect_list():
    """Multiple effects in the printing's effect list preserve order —
    the unit variant slots cleanly alongside a sibling parameterized
    effect. Mirrors `test_multiple_effects_preserve_order` for the new
    variant."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Compound",
            "card_types": ["Sorcery"],
            "effects": [
                {"kind": "draw_cards", "count": 1},
                {"kind": "destroy_target_nonland_permanent"},
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "draw_cards", "count": 1}
    assert effects[1] == {"kind": "destroy_target_nonland_permanent"}


# --- DealDamageAnyTarget round-trip --------------------------------
#
# Bridge ext: Lightning Bolt-style "any target" damage (CR 701.4).
# 7 cards in the EoE pool per round-20 measurement (Debris Field
# Crusher etc.). Mirrors Python's `DealDamageAnyTarget(DealDamage)`
# constructor sugar — the "any target" filter is intrinsic to the
# variant. Distinct from `deal_damage` which requires a `target`
# dict; this variant's parser arm takes only `amount`.


def test_round_trip_deal_damage_any_target_amount_three():
    """Happy path: amount=3 round-trips faithfully. Mirrors Python's
    `DealDamageAnyTarget(amount=N)` constructor sugar — the "any
    target" filter is intrinsic (no `target` dict to round-trip)."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Debris Field Crusher",
            "card_types": ["Sorcery"],
            "mana_cost": {"R": 1, "generic": 2},
            "effects": [{"kind": "deal_damage_any_target", "amount": 3}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "deal_damage_any_target", "amount": 3}


def test_round_trip_deal_damage_any_target_amount_zero():
    """amount=0 is a legal no-op shape (mirrors GainLife / DrawCards /
    Mill / DamageEachOpponent zero-amount round-trip conventions).
    Registers and round-trips without error."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Fizzle Bolt",
            "card_types": ["Instant"],
            "effects": [{"kind": "deal_damage_any_target", "amount": 0}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "deal_damage_any_target", "amount": 0}


def test_deal_damage_any_target_missing_amount_raises():
    """Python's `DealDamageAnyTarget` inherits `amount` from `DealDamage`
    with no default — the Rust parser mirrors that: omitting `amount`
    raises KeyError at register time (defense-in-depth, surfaced
    earlier than the resolve guard)."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError, match="amount"):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Instant"],
                "effects": [{"kind": "deal_damage_any_target"}],
            }
        )


def test_deal_damage_any_target_negative_amount_raises():
    """Register-time guard on negative amount (matches the apply_effect
    guard, surfaced earlier in the pipeline). Mirrors EachOpponentLosesLife
    / DamageEachOpponent / DiscardSelf negative register-time check
    shape — 'deal -1 damage to any target' is schema nonsense."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Instant"],
                "effects": [{"kind": "deal_damage_any_target", "amount": -1}],
            }
        )


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


# --- power / toughness / mana_produced (round-3 extension) ------


GRIZZLY_BEARS = {
    "name": "Grizzly Bears",
    "mana_cost": {"generic": 1, "G": 1},
    "power": 2,
    "toughness": 2,
}

FOREST_PRINTING = {
    "name": "Forest",
    "mana_produced": ["G"],
}


def test_round_trip_creature_power_toughness():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(GRIZZLY_BEARS)
    assert reg.get_printing_power(pid) == 2
    assert reg.get_printing_toughness(pid) == 2
    # Non-creature default for the same call surface returns None.
    sid = reg.register_printing(SHOCK)
    assert reg.get_printing_power(sid) is None
    assert reg.get_printing_toughness(sid) is None


def test_round_trip_mana_produced_forest():
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(FOREST_PRINTING)
    assert reg.get_printing_mana_produced(pid) == ["G"]


def test_mana_produced_default_is_none():
    """Spells (and creatures without mana production) round-trip as None."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(SHOCK)
    assert reg.get_printing_mana_produced(pid) is None


def test_negative_power_round_trips():
    """`power: i16` permits negatives (no real card has them by
    print, but anthem-like effects produce them on objects; the
    field bound is intentionally i16 so the bridge doesn't need
    to grow another type later)."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {"name": "Pseudo", "power": -1, "toughness": 0}
    )
    assert reg.get_printing_power(pid) == -1
    assert reg.get_printing_toughness(pid) == 0


def test_mana_produced_multi_pip_round_trip():
    """Vec<String> tolerates >1-pip producers at the bridge level
    even though `tap_for_mana` declines to commit on them this slice."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {"name": "Hypothetical Bicycle Land", "mana_produced": ["G", "G"]}
    )
    assert reg.get_printing_mana_produced(pid) == ["G", "G"]


# --- error paths for the new fields ------------------------------


def test_invalid_mana_symbol_in_mana_produced_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="unknown mana symbol"):
        reg.register_printing({"name": "Broken", "mana_produced": ["Q"]})


def test_lowercase_mana_symbol_in_mana_produced_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="unknown mana symbol"):
        reg.register_printing({"name": "Broken", "mana_produced": ["g"]})


def test_non_iterable_mana_produced_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError):
        reg.register_printing({"name": "Broken", "mana_produced": 7})


def test_non_string_mana_produced_entry_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="must be strings"):
        reg.register_printing({"name": "Broken", "mana_produced": [1]})


def test_non_integer_power_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="power must be an integer"):
        reg.register_printing({"name": "Broken", "power": "huge"})


def test_non_integer_toughness_raises():
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="toughness must be an integer"):
        reg.register_printing({"name": "Broken", "toughness": "small"})


# --- round-24: DestroyAllCreatures round-trip ---------------------
#
# Unit variant — no fields. Python's `DestroyAllCreatures` carries
# optional narrowing fields (tapped_only / untapped_only / min_power)
# that the Rust first slice intentionally drops. Any extra dict keys
# are silently dropped, mirroring CounterTargetSpell /
# ReturnCreatureFromYourGraveyardToBattlefield.


def test_round_trip_destroy_all_creatures_effect():
    """Wrath-of-God-shaped sorcery: unit variant, round-trips through
    the dict bridge with just `kind`."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Wrath of God",
            "card_types": ["Sorcery"],
            "mana_cost": {"W": 2, "generic": 2},
            "effects": [{"kind": "destroy_all_creatures"}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert len(effects) == 1
    assert effects[0]["kind"] == "destroy_all_creatures"
    # Unit variant has no other keys.
    assert set(effects[0].keys()) == {"kind"}


def test_destroy_all_creatures_extra_keys_silently_dropped():
    """Python's `DestroyAllCreatures` carries optional narrowing
    fields (tapped_only / untapped_only / min_power). The Rust first
    slice drops them — extra keys on the dict are silently ignored,
    matching the silent-drop convention for unrecognized keys
    elsewhere in the parser (e.g. CounterTargetSpell.filter_types,
    ReturnCreatureFromYourGraveyardToBattlefield.or_enchantment).
    """
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Split Up (narrowed shape ignored)",
            "card_types": ["Sorcery"],
            "effects": [
                {
                    "kind": "destroy_all_creatures",
                    "tapped_only": True,
                    "min_power": 3,
                }
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0]["kind"] == "destroy_all_creatures"
    # Bridge emits only the unit-variant shape on the way back out —
    # narrowed fields were dropped at parse time.
    assert "tapped_only" not in effects[0]
    assert "min_power" not in effects[0]


def test_destroy_all_creatures_in_effects_vec_alongside_other_effects():
    """Mixed effect Vec: Wrath + DrawCards round-trips both. Verifies
    the dispatcher inside `parse_printing` correctly threads the unit
    variant through alongside more-complex variants."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Sweep-and-Draw",
            "card_types": ["Sorcery"],
            "mana_cost": {"W": 2, "U": 1, "generic": 3},
            "effects": [
                {"kind": "destroy_all_creatures"},
                {"kind": "draw_cards", "count": 2},
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert len(effects) == 2
    assert effects[0]["kind"] == "destroy_all_creatures"
    assert effects[1]["kind"] == "draw_cards"
    assert effects[1]["count"] == 2


def test_lookup_oob_for_new_getters_raises():
    reg = mtg_bot_engine.Registry()
    reg.register_printing(GRIZZLY_BEARS)
    with pytest.raises(KeyError):
        reg.get_printing_power(99)
    with pytest.raises(KeyError):
        reg.get_printing_toughness(99)
    with pytest.raises(KeyError):
        reg.get_printing_mana_produced(99)


# --- bench helper ------------------------------------------------


def test_register_n_times_micros_returns_positive():
    reg = mtg_bot_engine.Registry()
    micros = reg.register_n_times_micros(SHOCK, 100)
    assert micros > 0.0
    # Sanity bound: parsing one Shock-like dict shouldn't exceed
    # ~50us even on a slow box; release-mode CPython is usually
    # under 5us.
    assert micros < 200.0, f"register too slow: {micros:.2f}us"


# --- TargetOpponentLosesLife round-trip + error paths -----------------
#
# CR 118.4 — life loss (not damage). Powers the Dubious Delicacy pattern
# (2 EoE cards). Distinct from `each_opponent_loses_life` (round 26):
# the round-trip shape is identical in 2-player land (same `amount`
# field) and the runtime behavior collapses to the same opponent life
# subtraction, but the variants stay separate to mirror Python's
# `TargetOpponentLosesLife(amount: int = 1)` dataclass shape (targeted
# vs each-opponent semantics).


def test_round_trip_target_opponent_loses_life_amount_two():
    """Happy path: amount=2 round-trips faithfully. Mirrors Python's
    `TargetOpponentLosesLife(amount: int = 1)` dataclass shape — `amount`
    field with default 1, so explicit values round-trip cleanly."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Dubious Delicacy",
            "card_types": ["Artifact"],
            "mana_cost": {"generic": 2},
            "effects": [{"kind": "target_opponent_loses_life", "amount": 3}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "target_opponent_loses_life", "amount": 3}


def test_round_trip_target_opponent_loses_life_amount_zero():
    """amount=0 is a legal no-op shape (mirrors GainLife / DrawCards /
    Mill / EachOpponentLosesLife / LoseLife zero-amount round-trip
    conventions). Registers and round-trips without error."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Zero Targeted Drain",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "target_opponent_loses_life", "amount": 0}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "target_opponent_loses_life", "amount": 0}


def test_round_trip_target_opponent_loses_life_default_amount_one():
    """Python's `TargetOpponentLosesLife(amount: int = 1)` carries a
    default of 1. Mirror the default-handling shape from
    PutPlusOneCounterOnSelf / DiscardSelf: omitting `amount` registers
    as amount=1 (NOT a KeyError, unlike EachOpponentLosesLife / LoseLife
    which have no default and require the field)."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Default Drain",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "target_opponent_loses_life"}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "target_opponent_loses_life", "amount": 1}


def test_target_opponent_loses_life_negative_amount_raises():
    """Register-time guard on negative amount (matches the apply_effect
    guard, surfaced earlier in the pipeline). Mirrors
    EachOpponentLosesLife / LoseLife / DamageEachOpponent /
    DiscardSelf negative register-time check shape — 'target opponent
    loses -2 life' is schema nonsense (use GainLife on the opponent
    for raising life totals, if that ever becomes a thing)."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Sorcery"],
                "effects": [
                    {"kind": "target_opponent_loses_life", "amount": -1}
                ],
            }
        )


# --- MillTargetPlayer round-trip + error paths ------------------------
#
# CR 701.13b — "mill" (a player puts the top N cards of their library
# into their graveyard). Powers the Scrabbling Skullcrab pattern (2 EoE
# cards per round-20 measurement). Distinct from `mill` (round-10): that
# arm mills the CONTROLLER's library; `mill_target_player` mills a
# TARGET player (= defender in 2-player land).


def test_round_trip_mill_target_player_count_three():
    """Happy path: count=3 round-trips faithfully. Mirrors the existing
    `mill` arm's `count` field shape — Scrabbling Skullcrab is mill-2,
    larger variants exist in the broader format pool."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Scrabbling Skullcrab",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 1, "U": 1},
            "effects": [{"kind": "mill_target_player", "count": 3}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "mill_target_player", "count": 3}


def test_round_trip_mill_target_player_count_zero():
    """count=0 is a legal no-op shape (mirrors GainLife / DrawCards /
    Mill / EachOpponentLosesLife / LoseLife zero-count round-trip
    conventions). Registers and round-trips without error."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Zero Targeted Mill",
            "card_types": ["Sorcery"],
            "effects": [{"kind": "mill_target_player", "count": 0}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "mill_target_player", "count": 0}


def test_mill_target_player_missing_count_raises():
    """`count` has no first-slice default — mirrors the `mill` arm's
    required-field shape (Surveil / EachOpponentLosesLife / LoseLife
    convention rather than the PutPlusOneCounterOnSelf / DiscardSelf /
    SearchLibraryForBasicLandTapped default-1 convention). Missing
    `count` surfaces as a KeyError at register time."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(KeyError):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Sorcery"],
                "effects": [{"kind": "mill_target_player"}],
            }
        )


def test_mill_target_player_negative_count_raises():
    """Register-time guard on negative count (matches the apply_effect
    guard, surfaced earlier in the pipeline). Mirrors Surveil /
    SearchLibraryForBasicLandTapped / TargetOpponentLosesLife negative
    register-time check shape — 'mill target player -2 cards' is
    schema nonsense (use the reverse mill direction with a future
    library-restore effect if that ever lands)."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Sorcery"],
                "effects": [{"kind": "mill_target_player", "count": -1}],
            }
        )


# --- EachOpponentDiscards round-trip + error paths -------------------
#
# CR 701.8 — discard. Powers the "Let's Play a Game" pattern (2 EoE
# cards). Distinct from `discard_card` (round 15): DiscardCard targets
# the DEFENDING player (caller-targeted, Mind Rot shape); this variant
# fires on the SOURCE's controller's opponents (source-relative). In a
# 2-player engine both collapse to "the one opponent discards hand[0]"
# but the variants stay separate to mirror Python's
# `EachOpponentDiscards(count: int = 1)` dataclass shape. Default-
# handling mirrors DiscardSelf / TargetOpponentDiscards (count
# defaults to 1) rather than EachOpponentLosesLife's required-amount
# shape.


def test_round_trip_each_opponent_discards_default_count_is_one():
    """Omitting `count` defaults to 1 (Python parity:
    `EachOpponentDiscards(count: int = 1)` dataclass has count
    default to 1; mirrors DiscardSelf / TargetOpponentDiscards
    default-handling shape rather than EachOpponentLosesLife's
    required-amount shape)."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Lets Play a Game",
            "card_types": ["Sorcery"],
            "mana_cost": {"B": 1, "generic": 2},
            "effects": [{"kind": "each_opponent_discards"}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "each_opponent_discards", "count": 1}


def test_round_trip_each_opponent_discards_count_two():
    """Happy path: count=2 round-trips faithfully. Mirrors Python's
    `EachOpponentDiscards(count: int = 1)` dataclass shape — `count`
    field with default 1, can be overridden."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Heavy Discard",
            "card_types": ["Sorcery"],
            "mana_cost": {"B": 1, "generic": 3},
            "effects": [{"kind": "each_opponent_discards", "count": 2}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "each_opponent_discards", "count": 2}


def test_each_opponent_discards_negative_count_raises():
    """Register-time guard on negative count (matches the apply_effect
    guard, surfaced earlier in the pipeline). Mirrors DiscardSelf /
    EachOpponentLosesLife / TargetOpponentLosesLife negative
    register-time check shape — 'each opponent discards -1 cards' is
    schema nonsense."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="non-negative"):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Sorcery"],
                "effects": [
                    {"kind": "each_opponent_discards", "count": -1}
                ],
            }
        )


def test_each_opponent_discards_in_unknown_kind_error_string():
    """The unknown-kind error string enumerates the valid kinds —
    `each_opponent_discards` must appear so a future regression that
    accidentally drops the parser arm surfaces with a helpful error."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="each_opponent_discards"):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Sorcery"],
                "effects": [{"kind": "obviously_not_a_real_kind"}],
            }
        )


# --- DestroyTargetArtifact round-trip -------------------------------
#
# Bridge ext: Drill Too Deep / Scour for Scrap shape — "destroy target
# artifact" (CR 701.7, artifact filter). 2 cards in the EoE pool per
# round-20 measurement. Mirrors Python's
# `DestroyTargetArtifact(Destroy)` constructor sugar with
# `targets=(TargetSpec(IsArtifact()),)`. Unit variant — no fields;
# the artifact filter is intrinsic to the variant. Round-trip is a
# bare `{"kind": "destroy_target_artifact"}` dict.


def test_round_trip_destroy_target_artifact_unit_variant():
    """Happy path: unit-variant round-trips as a single `kind` key
    with no extra fields. Mirrors `destroy_target_nonland_permanent`
    / `counter_target_spell` unit-variant round-trip shape."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Drill Too Deep",
            "card_types": ["Instant"],
            "mana_cost": {"B": 1, "generic": 2},
            "effects": [{"kind": "destroy_target_artifact"}],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "destroy_target_artifact"}


def test_round_trip_destroy_target_artifact_extra_keys_ignored():
    """Silent-drop convention for unrecognized keys on a unit variant
    (matches `destroy_target_nonland_permanent` parser shape). An
    accidental `target` key on the registered dict does NOT raise —
    the parser ignores it and round-trips a bare unit dict."""
    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Test Scour for Scrap",
            "card_types": ["Sorcery"],
            "mana_cost": {"R": 1, "generic": 1},
            "effects": [
                {
                    "kind": "destroy_target_artifact",
                    "target": {"kind": "any_creature"},  # ignored
                }
            ],
        }
    )
    effects = [dict(e) for e in reg.get_printing_effects(pid)]
    assert effects[0] == {"kind": "destroy_target_artifact"}


def test_destroy_target_artifact_in_unknown_kind_error_string():
    """The unknown-kind error string enumerates the valid kinds —
    `destroy_target_artifact` must appear so a future regression that
    accidentally drops the parser arm surfaces with a helpful error."""
    reg = mtg_bot_engine.Registry()
    with pytest.raises(ValueError, match="destroy_target_artifact"):
        reg.register_printing(
            {
                "name": "Broken",
                "card_types": ["Sorcery"],
                "effects": [{"kind": "obviously_not_a_real_kind"}],
            }
        )
