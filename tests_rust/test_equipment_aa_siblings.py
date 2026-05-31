"""Rust-engine pins for the Equipment-AA family siblings (Saw, Atomic
Microsizer, Auxiliary Boosters) — 2026-05-31,
``feature/equipment-aa-siblings``.

These siblings share the Equipment-attached-carrier ATTACKS / ETB
trigger substrate the Baseball Bat closure landed (`tests_rust/
test_tap.py` covers Baseball Bat's `Effect::TapUpToOneTargetCreature`).
Each sibling adds ONE new Rust `Effect` variant; the pins here drive
each variant through the genuine Equipment attach + declare_attacker /
ETB path and assert the observable.
"""

from __future__ import annotations

ZONE_HAND = 0
ZONE_LIBRARY = 1
ZONE_BATTLEFIELD = 2
ZONE_GRAVEYARD = 3


# ===================== Saw (2026-05-31) =====================
# `Effect::SawAttacksOptionalSacDrawEffect`: the ATTACKS +
# IsHost(attacker) "you may sacrifice a permanent other than that
# creature or this Equipment; if you do, draw a card" rider. NOT a
# targeted effect — the sacrifice pool is the source-controller's
# permanents excluding source + host; the no-agent deterministic seat
# ACCEPTS and sacrifices options[0] then draws.


def _saw_dict():
    return {
        "name": "Synthetic Saw",
        "card_types": ["Artifact"],
        "subtypes": ["Equipment"],
        "supertypes": [],
        "keywords": [],
        "effects": [],
        "triggered_abilities": [
            {
                "event": "attacks",
                "predicate": {"kind": "is_host", "subject": "attacker"},
                "effect": {"kind": "saw_attacks_optional_sac_draw_effect"},
            },
        ],
    }


def _trinket_dict(name):
    return {
        "name": name,
        "card_types": ["Artifact"],
        "subtypes": [],
        "supertypes": [],
        "keywords": [],
        "effects": [],
    }


def test_register_saw_attacks_optional_sac_draw_effect(engine):
    """The effect kind round-trips through register → to_pydict."""
    reg = engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Synthetic Saw Spell",
            "card_types": ["Instant"],
            "mana_cost": {"generic": 1},
            "effects": [{"kind": "saw_attacks_optional_sac_draw_effect"}],
        }
    )
    eff = reg.get_printing_effects(pid)[0]
    assert eff["kind"] == "saw_attacks_optional_sac_draw_effect"


def test_saw_sacs_first_controlled_permanent_and_draws_on_host_attack(
    synthetic_state,
):
    """Equip Saw to p0's first Bears, seed a clean state, declare the
    host as attacker → the ATTACKS+IsHost(attacker) trigger fires → the
    no-agent seat ACCEPTS and sacrifices the FIRST p0-controlled
    permanent excluding source + host (the first Forest in the
    synthetic state, id 0 — lowest ETB) and draws one card."""
    snap = synthetic_state.battlefield_snapshot()
    p0_first_bear_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Grizzly Bears"
    )
    # The first p0-controlled permanent excluding source + host: the
    # lowest-id Forest (synthetic state seeds 5 Forests at ids 0-4).
    first_forest_id = next(
        d["id"] for d in snap
        if d["controller_id"] == 0 and d["printing_name"] == "Forest"
    )
    equip_id = synthetic_state.register_and_inject_object(
        _saw_dict(), 0, ZONE_BATTLEFIELD
    )
    assert synthetic_state.attach(equip_id, p0_first_bear_id) is True
    synthetic_state.clear_summoning_sick_for_player(0)

    hand_before = len(synthetic_state.hand_snapshot(0))

    assert synthetic_state.declare_attacker(p0_first_bear_id) is True
    assert synthetic_state.stack_size() == 1
    synthetic_state.resolve_top_of_stack()
    assert synthetic_state.stack_size() == 0

    # The first Forest was sacrificed (now in p0's graveyard, off bf);
    # the host + the Saw remain.
    bf_ids = {d["id"] for d in synthetic_state.battlefield_snapshot()}
    assert first_forest_id not in bf_ids
    assert p0_first_bear_id in bf_ids
    assert equip_id in bf_ids
    gy_ids = {d["id"] for d in synthetic_state.graveyard_snapshot(0)}
    assert first_forest_id in gy_ids
    # And p0 drew exactly one card.
    assert len(synthetic_state.hand_snapshot(0)) == hand_before + 1


def test_saw_empty_pool_declines_no_sac_no_draw(engine):
    """With NO sacrificable permanent (only the host + the Saw on p0's
    bf — the host excluded as 'that creature', the Saw as 'this
    Equipment'), the optional trigger's pool is EMPTY → silent no-op:
    no sacrifice, no draw, no raise. Built on a clean 2-player state
    (the default synthetic state has Forests that would be sacrificed,
    so use an empty-battlefield state here)."""
    rs = engine.make_synthetic_state()
    snap = rs.battlefield_snapshot()
    # Remove every p0 permanent except one bear (the host).
    p0_objs = [d for d in snap if d["controller_id"] == 0]
    host_id = next(
        d["id"] for d in p0_objs if d["printing_name"] == "Grizzly Bears"
    )
    state = rs.clone_once()
    for d in p0_objs:
        if d["id"] != host_id:
            state.move_object(d["id"], ZONE_GRAVEYARD, 0)
    equip_id = state.register_and_inject_object(
        _saw_dict(), 0, ZONE_BATTLEFIELD
    )
    assert state.attach(equip_id, host_id) is True
    state.clear_summoning_sick_for_player(0)

    # Move every other-zone clutter aside is unnecessary; just snapshot
    # the pre-attack hand + graveyard for p0.
    hand_before = len(state.hand_snapshot(0))
    gy_before = len(state.graveyard_snapshot(0))

    assert state.declare_attacker(host_id) is True
    while state.stack_size() > 0:
        state.resolve_top_of_stack()

    # The host + the Saw both remain (neither is a legal sacrifice pool
    # member); no draw occurred; graveyard unchanged by the trigger
    # (the only legal pool was empty).
    bf_ids = {d["id"] for d in state.battlefield_snapshot()}
    assert host_id in bf_ids
    assert equip_id in bf_ids
    assert len(state.hand_snapshot(0)) == hand_before
    assert len(state.graveyard_snapshot(0)) == gy_before
