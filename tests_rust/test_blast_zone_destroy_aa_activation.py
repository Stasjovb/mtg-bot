"""Rust-engine pins for Blast Zone's destroy ACTIVATED ability driven by
the GENUINE ``ActivateAbility`` cost path (mana ``{3}`` + tap-self +
sacrifice-self), NOT the ETB-trigger shim the cross-engine probe used
before ``feature/blast-zone-aa-cost``.

These pins exercise the Rust ``Action::ActivateAbility`` arm
(``state_ops_actions.rs``) end-to-end for the
``DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters`` payoff:

- Phase 4 (mana pay): ``auto_tap_pay_for_cost`` debits ``{3}`` from the
  controller's pool.
- Phase 5 (tap_self): the source taps.
- Phase 5b (sacrifice_self): the source moves to its controller's
  graveyard. **Critically, this commit does NOT zero ``charge_counters``**
  (it only zeros the ``+1/+1`` ``counters`` scalar) — so the count
  survives as last-known-info.
- Phase 6: a ``new_trigger`` StackItem carrying ``source_obj_id`` is
  pushed; ``resolve_top_of_stack`` then fires the wipe, whose resolve
  arm (``state_ops_resolve.rs``) scans all zones (incl. the graveyard)
  for ``source_obj_id`` and reads its surviving ``charge_counters`` as
  the MV filter.

No new Rust cost atom is introduced — the ``{3}`` + ``tap_self`` +
``sacrifice_self`` shape is exactly what the CE20 activated-ability
substrate + the Lander sacrifice-self cost-commit already support. These
pins lock the activation-side byte-equality the cross-engine probe in
``tests/test_blast_zone_parity.py`` asserts against Python.

Companion: ``tests/test_blast_zone_parity.py`` (cross-engine probe),
``docs/SEARCH_LIMITATIONS.md`` (Blast Zone entry).
"""

from __future__ import annotations

import pytest


ZONE_BATTLEFIELD = 2

_DESTROY_KIND = (
    "destroy_each_nonland_permanent_with_mv_equal_to_source_charge_counters"
)


def _blast_zone_source_dict():
    """A Blast-Zone-shaped Land carrying the destroy AA at index 0,
    cost ``{3}`` mana + tap-self + sacrifice-self, is_mana_ability=False
    (the wipe goes through the stack, CR 605/113.3b)."""
    return {
        "name": "Blast Zone Source",
        "card_types": ["Land"],
        "effects": [],
        "activated_abilities": [
            {
                "cost": {
                    "mana": {"generic": 3},
                    "tap_self": True,
                    "sacrifice_self": True,
                },
                "effect": {"kind": _DESTROY_KIND},
                "is_mana_ability": False,
            },
        ],
    }


def _artifact_dict(name, mv):
    return {
        "name": name,
        "card_types": ["Artifact"],
        "mana_cost": {"generic": mv},
        "effects": [],
    }


def _names_on_bf(rs, controller_id):
    return sorted(
        d["printing_name"]
        for d in rs.battlefield_snapshot()
        if d["controller_id"] == controller_id
    )


def _names_in_gy(rs, player_id):
    return sorted(d["printing_name"] for d in rs.graveyard_snapshot(player_id))


def test_blast_zone_destroy_aa_pays_cost_and_pushes(synthetic_state):
    """Activating the destroy AA pays the full cost and pushes the
    wipe onto the stack:

    - ``{3}`` is debited from the pool (we pre-fund 3 colorless).
    - The source is sacrificed (off the battlefield, in p0's graveyard)
      with its ``charge_counters`` surviving the move.
    - Exactly one StackItem (the wipe) is pushed; the wipe has NOT
      fired yet (the MV-2 victim still on its bf).
    """
    rs = synthetic_state
    src = rs.register_and_inject_object(
        _blast_zone_source_dict(), 0, ZONE_BATTLEFIELD
    )
    rs.set_charge_counters(src, 2)
    rs.register_and_inject_object(_artifact_dict("MV2 victim", 2), 0, ZONE_BATTLEFIELD)
    rs.add_mana(0, "C", 3)

    stack_before = rs.stack_size()
    rs.apply_action(
        {"kind": "activate_ability", "source_id": src, "ability_index": 0}
    )

    # Pool drained of the {3} cost.
    pool = rs.get_mana_pool(0)
    assert pool["C"] == 0, f"pool should be drained of {{3}}; got {pool}"

    # Source sacrificed to p0's graveyard (no longer on the bf).
    assert "Blast Zone Source" not in _names_on_bf(rs, 0)
    assert "Blast Zone Source" in _names_in_gy(rs, 0)

    # Exactly one new StackItem (the wipe), not yet resolved.
    assert rs.stack_size() == stack_before + 1
    assert "MV2 victim" in _names_on_bf(rs, 0), (
        "victim must still be on the bf before the wipe resolves"
    )


def test_blast_zone_destroy_aa_resolves_wipe_via_lki_counters(synthetic_state):
    """Full real-AA drive: activate, then resolve — the wipe reads the
    sacrificed source's surviving ``charge_counters`` (2) as the MV
    filter and destroys MV-2 nonland permanents on both bfs, sparing
    MV-1/MV-3 and lands. Pins the last-known-info charge-counter read
    from the graveyard (Phase 5b sacrifice does NOT zero it)."""
    rs = synthetic_state
    src = rs.register_and_inject_object(
        _blast_zone_source_dict(), 0, ZONE_BATTLEFIELD
    )
    rs.set_charge_counters(src, 2)
    rs.register_and_inject_object(_artifact_dict("MV2 P0 victim", 2), 0, ZONE_BATTLEFIELD)
    rs.register_and_inject_object(_artifact_dict("MV1 P0 survivor", 1), 0, ZONE_BATTLEFIELD)
    rs.register_and_inject_object(_artifact_dict("MV2 P1 victim", 2), 1, ZONE_BATTLEFIELD)
    rs.register_and_inject_object(_artifact_dict("MV3 P1 survivor", 3), 1, ZONE_BATTLEFIELD)
    rs.add_mana(0, "C", 3)

    rs.apply_action(
        {"kind": "activate_ability", "source_id": src, "ability_index": 0}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    # MV-2 victims destroyed (own controller's graveyard); MV-1/MV-3
    # survive on the bf. The default synthetic Forests (lands) are
    # untouched — assert on the injected artifacts only.
    p0_bf = _names_on_bf(rs, 0)
    assert "MV2 P0 victim" not in p0_bf
    assert "MV1 P0 survivor" in p0_bf
    assert "Blast Zone Source" not in p0_bf  # sacrificed

    p1_bf = _names_on_bf(rs, 1)
    assert "MV2 P1 victim" not in p1_bf
    assert "MV3 P1 survivor" in p1_bf

    # Victims + the sacrificed source land in the right graveyards.
    p0_gy = _names_in_gy(rs, 0)
    assert "MV2 P0 victim" in p0_gy
    assert "Blast Zone Source" in p0_gy
    assert "MV2 P1 victim" in _names_in_gy(rs, 1)


def test_blast_zone_destroy_aa_zero_counters_wipes_mv0(synthetic_state):
    """At ``charge_counters = 0`` the wipe destroys MV-0 nonland
    permanents and spares MV-1. The source is sacrificed at count 0;
    the resolve reads 0 from the graveyard (LKI) and wipes MV-0."""
    rs = synthetic_state
    src = rs.register_and_inject_object(
        _blast_zone_source_dict(), 0, ZONE_BATTLEFIELD
    )
    # count 0 -> no set_charge_counters call (default is 0).
    rs.register_and_inject_object(_artifact_dict("MV0 victim", 0), 0, ZONE_BATTLEFIELD)
    rs.register_and_inject_object(_artifact_dict("MV1 survivor", 1), 1, ZONE_BATTLEFIELD)
    rs.add_mana(0, "C", 3)

    rs.apply_action(
        {"kind": "activate_ability", "source_id": src, "ability_index": 0}
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()

    assert "MV0 victim" not in _names_on_bf(rs, 0)
    assert "MV0 victim" in _names_in_gy(rs, 0)
    assert "Blast Zone Source" in _names_in_gy(rs, 0)  # sacrificed
    assert "MV1 survivor" in _names_on_bf(rs, 1)


def test_blast_zone_destroy_aa_unaffordable_raises(synthetic_state):
    """Affordability gate: with no pool mana AND no auto-tappable lands,
    activating the ``{3}`` cost raises and mutates nothing — the source
    stays on the bf, the stack stays put."""
    rs = synthetic_state
    src = rs.register_and_inject_object(
        _blast_zone_source_dict(), 0, ZONE_BATTLEFIELD
    )
    rs.set_charge_counters(src, 2)
    # Tap out the default p0 Forests so apply-side auto-tap can't cover
    # {3}, then empty the pool — only then is the cost genuinely
    # unaffordable.
    for obj in rs.battlefield_snapshot():
        if obj.get("controller_id") != 0 or obj.get("tapped"):
            continue
        if obj.get("printing_name") in ("Forest", "Llanowar Elves"):
            rs.tap_object(obj["id"])
    rs.empty_mana_pool(0)

    stack_before = rs.stack_size()
    with pytest.raises(ValueError, match=r"unaffordable from controller's mana pool"):
        rs.apply_action(
            {"kind": "activate_ability", "source_id": src, "ability_index": 0}
        )
    # No mutation — source still on bf, stack unchanged.
    assert "Blast Zone Source" in _names_on_bf(rs, 0)
    assert rs.stack_size() == stack_before
