"""Engine-resolve tests for parser-shape primitives in
``mtg_bot/effects/generic/`` whose unit tests cover parsing but whose
resolve / legal_targets / describe paths still have uncovered branches.

Round G of the coverage chip-away series. Targets:

* ``ReturnFromGraveyard`` — describe-method branches for the unified
  base across filter axes (artifact / land / nonland_permanent), the
  per-card mv-cap describe variant, the multi-target dedupe + sum-MV
  budget resolve path; ``legal_targets`` early-return when
  ``untargeted_all=True``; ``_gy_card_matches`` else branch when no
  primary type axis is set.
* ``ReturnCreatureFromYourGraveyardToBattlefield`` — legacy
  ``max_mv=None`` constructor compat (``__post_init__`` translates
  to 0).
* ``ReanimateTargetCreatureCardFromDefendersGraveyard`` — wrong
  target-kind early return in ``resolve``.
* ``TapEnchantedPermanent`` — host-not-found-on-battlefield early
  return (the ``aura.attached_to`` is set but the host has left
  play).
* ``PutChargeCountersOnSelf`` — ``amount_from_x=True`` describe form.
"""

from __future__ import annotations


# ---------- ReturnFromGraveyard.describe() branch sweep ----------


def test_return_from_graveyard_describe_artifact_card():
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard

    eff = ReturnFromGraveyard(artifact=True, destination="hand")
    desc = eff.describe()
    assert "artifact card" in desc
    assert "graveyard" in desc
    assert "hand" in desc


def test_return_from_graveyard_describe_land_card_to_battlefield():
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard

    eff = ReturnFromGraveyard(land=True, destination="battlefield")
    desc = eff.describe()
    assert "land card" in desc
    assert "battlefield" in desc


def test_return_from_graveyard_describe_nonland_permanent_multi():
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard

    eff = ReturnFromGraveyard(
        nonland_permanent=True, destination="hand", max_n=2,
    )
    desc = eff.describe()
    assert "nonland permanent" in desc
    assert "up to 2 target" in desc
    assert "graveyard" in desc


def test_return_from_graveyard_describe_max_mv_per_card():
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard

    eff = ReturnFromGraveyard(
        creature=True, destination="hand", max_mv=2,
    )
    desc = eff.describe()
    assert "mana value 2 or less" in desc
    assert "creature card" in desc


def test_return_from_graveyard_describe_creature_or_artifact():
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard

    eff = ReturnFromGraveyard(
        creature=True, or_artifact=True, destination="hand",
    )
    desc = eff.describe()
    assert "artifact or creature card" in desc


def test_return_from_graveyard_describe_creature_or_spacecraft():
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard

    eff = ReturnFromGraveyard(
        creature=True, or_spacecraft=True, destination="hand",
    )
    desc = eff.describe()
    assert "creature or Spacecraft card" in desc


def test_return_from_graveyard_describe_total_mv_budget_with_counter():
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard

    # The ``up to N with total mana value M or less`` + +1/+1 counter
    # form (Scout for Survivors describe shape).
    eff = ReturnFromGraveyard(
        creature=True, destination="battlefield", max_n=3,
        max_total_mv=3, plus_one_counter=True,
    )
    desc = eff.describe()
    assert "up to 3 target" in desc
    assert "total mana value 3 or less" in desc
    assert "+1/+1 counter on each" in desc


def test_return_from_graveyard_describe_total_mv_budget_no_counter():
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard

    eff = ReturnFromGraveyard(
        creature=True, destination="hand", max_n=3,
        max_total_mv=3, plus_one_counter=False,
    )
    desc = eff.describe()
    assert "total mana value 3 or less" in desc
    assert "+1/+1 counter" not in desc


# ---------- ReturnFromGraveyard.legal_targets() ----------


def test_return_from_graveyard_legal_targets_untargeted_all_returns_empty():
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    a_pr = make_creature("A", "{1}", 1, 1)
    a = GameObject(id=1, printing=a_pr, owner_id=0, controller_id=0,
                   zone=Zone.GRAVEYARD)
    p0 = Player(id=0)
    p0.graveyard.append(a)
    state = GameState(players=[p0, Player(id=1)])
    eff = ReturnFromGraveyard(
        creature=True, destination="battlefield", untargeted_all=True,
    )
    assert eff.legal_targets(state, 0) == []
    # And ``requires_target`` flips to False on untargeted_all.
    assert eff.requires_target() is False


# ---------- ReturnFromGraveyard._gy_card_matches() else branch ----------


def test_gy_card_matches_no_primary_type_returns_false():
    """When all four primary-type axes are False the predicate
    rejects every card. Defensive base behavior — no parser site
    builds this shape but ``_resolve_all`` still walks the filter."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.graveyard import _gy_card_matches
    from mtg_bot.game import GameObject, Zone

    a_pr = make_creature("A", "{1}", 1, 1)
    a = GameObject(id=1, printing=a_pr, owner_id=0, controller_id=0,
                   zone=Zone.GRAVEYARD)
    assert _gy_card_matches(
        a,
        creature=False,
        artifact=False,
        land=False,
        nonland_permanent=False,
        or_enchantment=False,
        or_spacecraft=False,
        or_artifact=False,
        max_mv=0,
    ) is False


# ---------- ReturnFromGraveyard multi-target resolve ----------


def test_return_from_graveyard_multi_target_dedupe_and_budget():
    """Multi-target resolve path (``max_n > 1``): targets are walked
    in pick order, deduped by id, and skipped past the sum-MV budget.
    The four-target list has one duplicate id and one card whose MV
    would exceed the remaining budget; both are skipped with log
    lines, the rest move to the battlefield with a +1/+1 counter."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    a_pr = make_creature("A", "{1}", 1, 1)  # MV 1
    b_pr = make_creature("B", "{1}", 1, 1)  # MV 1
    big_pr = make_creature("Big", "{2}", 2, 2)  # MV 2 — fits as last pick? remaining budget after A+B = 0
    a = GameObject(id=1, printing=a_pr, owner_id=0, controller_id=0,
                   zone=Zone.GRAVEYARD)
    b = GameObject(id=2, printing=b_pr, owner_id=0, controller_id=0,
                   zone=Zone.GRAVEYARD)
    big = GameObject(id=3, printing=big_pr, owner_id=0, controller_id=0,
                     zone=Zone.GRAVEYARD)
    p0 = Player(id=0)
    p0.graveyard.extend([a, b, big])
    state = GameState(players=[p0, Player(id=1)])
    eff = ReturnFromGraveyard(
        creature=True, destination="battlefield",
        min_n=1, max_n=3, max_total_mv=2, plus_one_counter=True,
    )
    # Pick a, then a again (dedupe), then big (skipped — MV 2 exceeds
    # budget remaining after a's MV 1 leaves 1), then b (MV 1 fits).
    targets = (
        ("graveyard_creature", a.id),
        ("graveyard_creature", a.id),  # duplicate — skipped
        ("graveyard_creature", big.id),  # over budget — skipped
        ("graveyard_creature", b.id),
    )
    eff.resolve(state, 0, targets)
    # a + b moved with counter; big stayed in graveyard.
    moved = [o for o in state.battlefield if o.id in (a.id, b.id)]
    assert len(moved) == 2
    for o in moved:
        assert o.plus_one_counters == 1
    assert big in p0.graveyard
    # The over-budget log line was emitted for big.
    assert any("budget" in line and "Big" in line for line in state.log)


def test_return_from_graveyard_multi_target_skips_wrong_kind():
    """Wrong target-kind tuples are silently skipped in the multi-
    target walk (single-target walk has its own coverage)."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    a_pr = make_creature("A", "{1}", 1, 1)
    a = GameObject(id=1, printing=a_pr, owner_id=0, controller_id=0,
                   zone=Zone.GRAVEYARD)
    p0 = Player(id=0)
    p0.graveyard.append(a)
    state = GameState(players=[p0, Player(id=1)])
    eff = ReturnFromGraveyard(
        creature=True, destination="hand", max_n=2,
    )
    targets = (
        ("not_a_real_kind", a.id),
        ("graveyard_creature", a.id),
    )
    eff.resolve(state, 0, targets)
    # The legitimate target was returned despite the spurious first
    # tuple.
    assert a in p0.hand
    assert a not in p0.graveyard


def test_return_from_graveyard_single_target_wrong_kind_returns():
    """Single-target walk's wrong-kind early-return."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    a_pr = make_creature("A", "{1}", 1, 1)
    a = GameObject(id=1, printing=a_pr, owner_id=0, controller_id=0,
                   zone=Zone.GRAVEYARD)
    p0 = Player(id=0)
    p0.graveyard.append(a)
    state = GameState(players=[p0, Player(id=1)])
    eff = ReturnFromGraveyard(creature=True, destination="hand")
    eff.resolve(state, 0, (("not_a_real_kind", a.id),))
    # The wrong-kind tuple was rejected; the card stayed in graveyard.
    assert a in p0.graveyard
    assert a not in p0.hand


def test_return_from_graveyard_log_suffix_appears_in_log():
    """``log_suffix`` (Petrified Field's ``(Petrified Field)`` tag)
    is appended to the move log line on the hand-destination path."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    a_pr = make_creature("A", "{1}", 1, 1)
    a = GameObject(id=1, printing=a_pr, owner_id=0, controller_id=0,
                   zone=Zone.GRAVEYARD)
    p0 = Player(id=0)
    p0.graveyard.append(a)
    state = GameState(players=[p0, Player(id=1)])
    eff = ReturnFromGraveyard(
        land=True, destination="hand",
        target_kind="graveyard_land", log_suffix="(MyTag)",
    )
    # land=True excludes A (a creature). Reset the filter via creature
    # (re-tagged for this test).
    eff = ReturnFromGraveyard(
        creature=True, destination="hand",
        target_kind="graveyard_creature", log_suffix="(MyTag)",
    )
    eff.resolve(state, 0, (("graveyard_creature", a.id),))
    assert any("(MyTag)" in line for line in state.log)


# ---------- ReturnCreatureFromYourGraveyardToBattlefield legacy compat ----------


def test_return_creature_to_battlefield_legacy_max_mv_none():
    """Legacy callers may still pass ``max_mv=None``; the
    ``__post_init__`` translates None -> 0 (unbounded)."""
    from mtg_bot.effects.generic.graveyard import (
        ReturnCreatureFromYourGraveyardToBattlefield,
    )

    eff = ReturnCreatureFromYourGraveyardToBattlefield(max_mv=None)
    assert eff.max_mv == 0
    assert eff.creature is True
    assert eff.destination == "battlefield"


# ---------- ReanimateTargetCreatureCardFromDefendersGraveyard wrong-kind ----------


def test_reanimate_defenders_graveyard_wrong_kind_no_op():
    """``("permanent", id)`` instead of ``("graveyard_creature", id)``
    — the resolve early-returns without touching state."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import ReanimateTargetCreatureCardFromDefendersGraveyard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    bear = GameObject(id=1, printing=bear_pr, owner_id=1, controller_id=1,
                      zone=Zone.GRAVEYARD)
    p1 = Player(id=1)
    p1.graveyard.append(bear)
    state = GameState(players=[Player(id=0), p1])
    eff = ReanimateTargetCreatureCardFromDefendersGraveyard()
    eff.resolve(state, 0, (("permanent", bear.id),))
    # The wrong-kind tuple short-circuits — bear stays in P1's
    # graveyard, doesn't enter the battlefield.
    assert bear in p1.graveyard
    assert bear not in state.battlefield


def test_reanimate_defenders_graveyard_no_targets_no_op():
    """No targets passed — the resolve early-returns."""
    from mtg_bot.effects import ReanimateTargetCreatureCardFromDefendersGraveyard
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    ReanimateTargetCreatureCardFromDefendersGraveyard().resolve(
        state, 0, (),
    )
    # No state change — no battlefield arrivals, no log entries.
    assert state.battlefield == []


# ---------- TapEnchantedPermanent host-not-on-battlefield ----------


def test_tap_enchanted_permanent_host_left_battlefield_no_op():
    """``aura.attached_to`` is set to a non-existent id (the host has
    left the battlefield between trigger and resolve). The resolve
    early-returns at ``host is None``."""
    from mtg_bot.cards.base import make_aura
    from mtg_bot.effects import TapEnchantedPermanent
    from mtg_bot.game import GameObject, GameState, Player, Zone

    aura_pr = make_aura("Test Aura", "{U}")
    aura = GameObject(
        id=1, printing=aura_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD, attached_to=999,  # non-existent host
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[aura],
        resolving_source=aura,
    )
    pre_log_len = len(state.log)
    TapEnchantedPermanent().resolve(state, 0)
    # No log line emitted; nothing to tap.
    assert len(state.log) == pre_log_len


# ---------- PutChargeCountersOnSelf describe(amount_from_x) ----------


def test_put_charge_counters_on_self_describe_x_form():
    from mtg_bot.effects.generic.counters import PutChargeCountersOnSelf

    desc = PutChargeCountersOnSelf(amount_from_x=True).describe()
    assert "X charge counters" in desc
    assert "this permanent" in desc


def test_put_charge_counters_on_self_describe_singular():
    from mtg_bot.effects.generic.counters import PutChargeCountersOnSelf

    desc = PutChargeCountersOnSelf(amount=1).describe()
    assert "1 charge counter" in desc
    # Singular form — no trailing 's' on counter.
    assert "1 charge counters" not in desc
