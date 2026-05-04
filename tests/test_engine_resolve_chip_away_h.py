"""Engine-resolve tests for parser-shape primitives in
``mtg_bot/effects/generic/destroy.py`` and
``mtg_bot/effects/generic/bounce.py`` whose unit tests covered parsing
but whose describe / no-host / no-source resolve branches still had
coverage gaps.

Round H of the coverage chip-away series. Targets:

* ``DestroyTargetCreature.describe()`` — the ``or_spacecraft``,
  ``or_enchantment``, and ``draw_if_undamaged_amount > 0`` rider
  branches.
* ``DestroyEnchantedPermanent`` — describe plus the
  host-left-battlefield (``host is None``) early return.
* ``DestroyUpToOneTargetNonlandPermanent.describe()`` — the
  optional-target Syr-Vondam shape.
* ``DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters``
  — describe plus the resolving-source-is-None defensive return.
* ``ReturnCreatureFromYourGraveyardToHand.describe()`` — the
  ``or_artifact`` and ``or_spacecraft`` widening describe paths
  plus the ``max_mv > 0`` cap variant; previously only the bare
  "creature card" shape was exercised.
"""

from __future__ import annotations


# ---------- DestroyTargetCreature.describe() ----------


def test_destroy_target_creature_describe_or_spacecraft():
    from mtg_bot.effects.generic.destroy import DestroyTargetCreature

    desc = DestroyTargetCreature(or_spacecraft=True).describe()
    assert "destroy target creature" in desc
    assert "Spacecraft" in desc


def test_destroy_target_creature_describe_or_enchantment():
    from mtg_bot.effects.generic.destroy import DestroyTargetCreature

    desc = DestroyTargetCreature(or_enchantment=True).describe()
    assert "destroy target creature" in desc
    assert "enchantment" in desc


def test_destroy_target_creature_describe_with_draw_rider():
    """Faller's-Faithful-shape rider — describe surfaces the
    "if it wasn't dealt damage this turn" follow-up."""
    from mtg_bot.effects.generic.destroy import DestroyTargetCreature

    desc = DestroyTargetCreature(draw_if_undamaged_amount=2).describe()
    assert "destroy target creature" in desc
    assert "wasn't dealt damage this turn" in desc
    assert "draws 2" in desc


def test_destroy_target_creature_describe_or_spacecraft_with_draw():
    """Compound: widening + rider — both surfaces fire."""
    from mtg_bot.effects.generic.destroy import DestroyTargetCreature

    desc = DestroyTargetCreature(
        or_spacecraft=True, draw_if_undamaged_amount=1,
    ).describe()
    assert "Spacecraft" in desc
    assert "wasn't dealt damage this turn" in desc


# ---------- DestroyEnchantedPermanent ----------


def test_destroy_enchanted_permanent_describe():
    from mtg_bot.effects.generic.destroy import DestroyEnchantedPermanent

    assert DestroyEnchantedPermanent().describe() == "destroy enchanted permanent"


def test_destroy_enchanted_permanent_host_left_battlefield_no_op():
    """``aura.attached_to`` is set to a non-existent id (host has
    left between trigger and resolve). Resolve early-returns at
    ``host is None`` without raising."""
    from mtg_bot.cards.base import make_aura
    from mtg_bot.effects.generic.destroy import DestroyEnchantedPermanent
    from mtg_bot.game import GameObject, GameState, Player, Zone

    aura_pr = make_aura("Test Aura", "{1}{B}")
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
    DestroyEnchantedPermanent().resolve(state, controller_id=0)
    # Aura stayed; no log line emitted; no graveyard arrival.
    assert aura in state.battlefield
    assert len(state.log) == pre_log_len


def test_destroy_enchanted_permanent_no_aura_no_op():
    """``state.resolving_source`` is None — early return via the
    ``aura is None`` branch (the existing parser test only hits
    the ``aura.attached_to is None`` sibling branch)."""
    from mtg_bot.effects.generic.destroy import DestroyEnchantedPermanent
    from mtg_bot.game import GameState, Player

    state = GameState(
        players=[Player(id=0), Player(id=1)], resolving_source=None,
    )
    pre_log_len = len(state.log)
    DestroyEnchantedPermanent().resolve(state, controller_id=0)
    assert len(state.log) == pre_log_len


# ---------- DestroyUpToOneTargetNonlandPermanent ----------


def test_destroy_up_to_one_nonland_permanent_describe():
    from mtg_bot.effects.generic.destroy import (
        DestroyUpToOneTargetNonlandPermanent,
    )

    desc = DestroyUpToOneTargetNonlandPermanent().describe()
    assert "destroy up to one target nonland permanent" == desc


# ---------- DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters ----------


def test_destroy_each_nonland_with_mv_equal_to_charge_counters_describe():
    from mtg_bot.effects.generic.destroy import (
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    )

    desc = DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters().describe()
    assert "nonland permanent" in desc
    assert "charge counters" in desc


def test_destroy_each_nonland_with_mv_equal_to_charge_counters_no_source():
    """``state.resolving_source`` is None — defensive early return."""
    from mtg_bot.effects.generic.destroy import (
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    )
    from mtg_bot.game import GameState, Player

    state = GameState(
        players=[Player(id=0), Player(id=1)], resolving_source=None,
    )
    pre_log_len = len(state.log)
    DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters().resolve(
        state, controller_id=0,
    )
    assert len(state.log) == pre_log_len


def test_destroy_each_nonland_with_mv_equal_to_charge_counters_resolve():
    """End-to-end: a Blast-Zone-shape source with 2 charge counters
    destroys every non-land, non-indestructible permanent on the
    battlefield whose printed mana value is exactly 2; lands and
    indestructible victims are skipped."""
    from mtg_bot.cards.base import make_basic_land, make_creature
    from mtg_bot.effects.generic.destroy import (
        DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters,
    )
    from mtg_bot.game import GameObject, GameState, Player, Zone

    src_pr = make_basic_land("Blast Zone-ish", "C")
    src = GameObject(
        id=1, printing=src_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    src.charge_counters = 2
    # A creature with MV 2 — should be destroyed.
    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    bear = GameObject(
        id=2, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    # A creature with MV 3 — should be skipped (mana value mismatch).
    big_pr = make_creature("Big", "{1}{1}{R}", 3, 3)
    big = GameObject(
        id=3, printing=big_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    # An indestructible creature with MV 2 — should be skipped.
    indes_pr = make_creature(
        "Wall", "{1}{W}", 0, 4, keywords=("indestructible",),
    )
    indes = GameObject(
        id=4, printing=indes_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    # A land with MV 0 — should be skipped (is_land filter).
    land_pr = make_basic_land("Some Land", "G")
    land = GameObject(
        id=5, printing=land_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[src, bear, big, indes, land],
        resolving_source=src,
    )
    DestroyEachNonlandPermanentWithMVEqualToSourceChargeCounters().resolve(
        state, controller_id=0,
    )
    # Only the matching, mortal, non-land creature went away.
    assert bear not in state.battlefield
    assert big in state.battlefield
    assert indes in state.battlefield
    assert land in state.battlefield
    assert src in state.battlefield


# ---------- ReturnCreatureFromYourGraveyardToHand describe widenings ----------


def test_return_creature_to_hand_describe_or_artifact():
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )

    eff = ReturnCreatureFromYourGraveyardToHand(or_artifact=True)
    desc = eff.describe()
    assert "artifact or creature" in desc
    assert "graveyard" in desc
    assert "your hand" in desc


def test_return_creature_to_hand_describe_or_spacecraft():
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )

    eff = ReturnCreatureFromYourGraveyardToHand(or_spacecraft=True)
    desc = eff.describe()
    assert "creature or Spacecraft" in desc


def test_return_creature_to_hand_describe_max_mv_cap():
    """Savior of the Small shape — per-card MV cap surfaces in the
    describe phrase."""
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )

    eff = ReturnCreatureFromYourGraveyardToHand(max_mv=3)
    desc = eff.describe()
    assert "mana value 3 or less" in desc


def test_return_creature_to_hand_describe_or_artifact_with_max_mv():
    """Compound: widening + per-card cap. The describe path takes
    the ``max_mv > 0`` branch, type_phrase comes from the widening."""
    from mtg_bot.effects.generic.bounce import (
        ReturnCreatureFromYourGraveyardToHand,
    )

    eff = ReturnCreatureFromYourGraveyardToHand(
        or_artifact=True, max_mv=2,
    )
    desc = eff.describe()
    assert "artifact or creature" in desc
    assert "mana value 2 or less" in desc
