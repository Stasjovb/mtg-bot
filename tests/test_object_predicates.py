"""Tests for the object-tier predicate atoms.

``ObjectPredicate`` is the slot-agnostic bottom layer: each atom takes
``(obj, state)`` and answers whether the object satisfies the property.
The trigger layer composes these via ``Subject(slot, inner)`` /
``Source(inner)``; those are tested separately with the trigger
combinator stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mtg_bot.effects.object_predicates import (
    HasCounter,
    HasKeyword,
    HasPowerAtMost,
    HasSubtype,
    IsArtifact,
    IsAttacking,
    IsBattle,
    IsBlocking,
    IsCreature,
    IsEnchantment,
    IsLand,
    IsNontoken,
    IsPlaneswalker,
    IsPlayer,
    IsTapped,
    ObjectAnd,
    ObjectNot,
    ObjectOr,
    ObjectPredicate,
)


@dataclass
class FakePrinting:
    card_types: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()
    is_token: bool = False
    # Fields read by ``mtg_bot.game.effective_subtypes`` to walk
    # CR-613 layered-subtype effects. Defaulted so a bare
    # ``FakePrinting()`` short-circuits the layered walk to just the
    # printed subtypes.
    is_artifact: bool = False
    is_land: bool = False
    is_basic_land: bool = False
    nonbasic_lands_are_mountains: bool = False
    grants_food_to_your_artifacts: bool = False
    grants_all_basic_land_types_to_lands_you_control: bool = False
    grants_basic_land_type_to_all_lands: str | None = None
    # Read by ``mtg_bot.game.is_creature_now`` and ``is_stationed``.
    # ``is_creature`` mirrors ``"Creature" in card_types`` on real
    # printings; computed from card_types in __post_init__ so test
    # fixtures don't have to set both.
    is_creature: bool = False
    station_threshold: int | None = None

    def __post_init__(self) -> None:
        if "Creature" in self.card_types and not self.is_creature:
            self.is_creature = True


@dataclass
class FakeObject:
    id: int = 0
    controller_id: int = 0
    printing: FakePrinting = field(default_factory=FakePrinting)
    plus_one_counters: int = 0
    charge_counters: int = 0
    stun_counters: int = 0
    loyalty_counters: int = 0
    tapped: bool = False
    blocking: int | None = None
    attacking: bool = False
    # Read by ``effective_subtypes`` (face-down permanents have no
    # subtypes per CR 701.34) and by the Magus / Dryad timestamp walks.
    face_down: bool = False
    etb_timestamp: int = 0
    # Read by ``is_creature_now`` — runtime type-line overrides.
    impending_active: bool = False
    enduring_returned_as_enchantment: bool = False
    permanent_is_creature: bool = False


@dataclass
class FakePlayer:
    id: int = 0


@dataclass
class FakeState:
    # ``effective_subtypes`` walks ``state.battlefield`` and
    # ``state.continuous_effects``; both default to empty so the
    # layered walk is a no-op and printed subtypes flow through.
    battlefield: list = field(default_factory=list)
    continuous_effects: list = field(default_factory=list)


# ---------- type predicates ----------


def test_is_land_true_for_land():
    obj = FakeObject(printing=FakePrinting(card_types=("Land",)))
    assert IsLand().test(obj, FakeState()) is True


def test_is_land_false_for_creature():
    obj = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    assert IsLand().test(obj, FakeState()) is False


def test_is_land_false_for_player():
    """A Player (no ``printing``) doesn't satisfy IsLand."""
    assert IsLand().test(FakePlayer(id=1), FakeState()) is False


def test_is_creature_true_for_creature():
    obj = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    assert IsCreature().test(obj, FakeState()) is True


def test_is_creature_false_for_land():
    obj = FakeObject(printing=FakePrinting(card_types=("Land",)))
    assert IsCreature().test(obj, FakeState()) is False


def test_is_artifact_true_for_artifact_creature():
    """A creature with the Artifact card type matches."""
    obj = FakeObject(
        printing=FakePrinting(card_types=("Artifact", "Creature"))
    )
    assert IsArtifact().test(obj, FakeState()) is True


def test_is_artifact_false_for_pure_creature():
    obj = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    assert IsArtifact().test(obj, FakeState()) is False


def test_is_enchantment_true_for_enchantment():
    obj = FakeObject(printing=FakePrinting(card_types=("Enchantment",)))
    assert IsEnchantment().test(obj, FakeState()) is True


def test_is_enchantment_true_for_room():
    """Rooms print as ``Enchantment — Room`` so they match IsEnchantment."""
    obj = FakeObject(
        printing=FakePrinting(card_types=("Enchantment",), subtypes=("Room",))
    )
    assert IsEnchantment().test(obj, FakeState()) is True


def test_is_enchantment_false_for_player():
    assert IsEnchantment().test(FakePlayer(id=1), FakeState()) is False


def test_is_player_true_for_player():
    """A Player (no ``printing``) matches."""
    assert IsPlayer().test(FakePlayer(id=1), FakeState()) is True


def test_is_player_false_for_permanent():
    obj = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    assert IsPlayer().test(obj, FakeState()) is False


def test_is_player_false_for_none():
    """Defensive: a missing object reads as not-a-player."""
    assert IsPlayer().test(None, FakeState()) is False


def test_is_planeswalker_true_for_planeswalker():
    obj = FakeObject(printing=FakePrinting(card_types=("Planeswalker",)))
    assert IsPlaneswalker().test(obj, FakeState()) is True


def test_is_planeswalker_false_for_creature():
    obj = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    assert IsPlaneswalker().test(obj, FakeState()) is False


def test_is_planeswalker_false_for_player():
    assert IsPlaneswalker().test(FakePlayer(id=1), FakeState()) is False


def test_is_battle_true_for_battle():
    obj = FakeObject(printing=FakePrinting(card_types=("Battle",)))
    assert IsBattle().test(obj, FakeState()) is True


def test_is_battle_false_for_creature():
    obj = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    assert IsBattle().test(obj, FakeState()) is False


def test_is_battle_false_for_player():
    assert IsBattle().test(FakePlayer(id=1), FakeState()) is False


def test_is_attacking_true_when_attacking():
    obj = FakeObject(attacking=True)
    assert IsAttacking().test(obj, FakeState()) is True


def test_is_attacking_false_when_not_attacking():
    obj = FakeObject(attacking=False)
    assert IsAttacking().test(obj, FakeState()) is False


def test_is_attacking_false_for_player():
    """Players don't attack — the ``attacking`` attribute is missing
    so the predicate evaluates false."""
    assert IsAttacking().test(FakePlayer(id=1), FakeState()) is False


# ---------- nontoken / subtype ----------


def test_is_nontoken_true_for_real_card():
    obj = FakeObject(printing=FakePrinting(is_token=False))
    assert IsNontoken().test(obj, FakeState()) is True


def test_is_nontoken_false_for_token():
    obj = FakeObject(printing=FakePrinting(is_token=True))
    assert IsNontoken().test(obj, FakeState()) is False


def test_is_nontoken_false_for_player():
    """A Player doesn't have a printing — returns false."""
    assert IsNontoken().test(FakePlayer(id=1), FakeState()) is False


def test_has_subtype_matches_named_subtype():
    obj = FakeObject(printing=FakePrinting(subtypes=("Kavu",)))
    assert HasSubtype("Kavu").test(obj, FakeState()) is True


def test_has_subtype_rejects_other_subtype():
    obj = FakeObject(printing=FakePrinting(subtypes=("Goblin",)))
    assert HasSubtype("Kavu").test(obj, FakeState()) is False


def test_has_subtype_matches_within_multi_subtype_printing():
    obj = FakeObject(printing=FakePrinting(subtypes=("Human", "Wizard")))
    assert HasSubtype("Wizard").test(obj, FakeState()) is True
    assert HasSubtype("Human").test(obj, FakeState()) is True
    assert HasSubtype("Soldier").test(obj, FakeState()) is False


def test_has_subtype_false_for_player():
    assert HasSubtype("Kavu").test(FakePlayer(id=1), FakeState()) is False


def test_has_subtype_face_down_returns_false():
    """A face-down permanent has no subtypes per CR 701.34, even if
    its printing prints with the subtype."""
    obj = FakeObject(
        printing=FakePrinting(subtypes=("Sliver",)),
        face_down=True,
    )
    assert HasSubtype("Sliver").test(obj, FakeState()) is False


def test_has_subtype_includes_layer4_add_subtype_grant():
    """A creature granted ``Sliver`` by a continuous-effect-registry
    layer-4 ``add_subtype`` entry counts toward ``HasSubtype("Sliver")``
    even if the printed subtype list omits it. This is the path
    Hivepool's Affinity-for-Slivers needs to be rules-correct: a token
    or creature granted Sliver by a Conspiracy-style continuous effect
    is a Sliver for layer-7-independent subtype checks."""
    from mtg_bot.game import ContinuousEffect

    obj = FakeObject(
        id=42,
        printing=FakePrinting(card_types=("Creature",), subtypes=("Bear",)),
    )
    state = FakeState()
    state.continuous_effects.append(
        ContinuousEffect(
            source_id=99,
            layer=4,
            timestamp=0,
            kind="add_subtype",
            target_id=42,
            params=("Sliver",),
            description="Conspiracy: creatures are Slivers",
        )
    )
    assert HasSubtype("Sliver").test(obj, state) is True
    # Printed Bear subtype still recognized.
    assert HasSubtype("Bear").test(obj, state) is True
    # An unrelated subtype isn't introduced.
    assert HasSubtype("Goblin").test(obj, state) is False


# ---------- IsTapped ----------


def test_is_tapped_true_when_tapped():
    obj = FakeObject(tapped=True)
    assert IsTapped().test(obj, FakeState()) is True


def test_is_tapped_false_when_untapped():
    obj = FakeObject(tapped=False)
    assert IsTapped().test(obj, FakeState()) is False


def test_is_tapped_false_for_player():
    """Players have no ``tapped`` attribute → predicate returns false
    (distinct from the legacy slot-aware predicate's source-fallback,
    which now lives at the trigger layer via ``Source(IsTapped())``)."""
    assert IsTapped().test(FakePlayer(id=1), FakeState()) is False


# ---------- IsBlocking ----------


def test_is_blocking_true_when_assigned_to_attacker():
    """``obj.blocking`` carries the attacker id when blocking — any
    non-None value is truthy."""
    obj = FakeObject(blocking=42)
    assert IsBlocking().test(obj, FakeState()) is True


def test_is_blocking_false_when_not_blocking():
    obj = FakeObject(blocking=None)
    assert IsBlocking().test(obj, FakeState()) is False


def test_is_blocking_false_for_player():
    """Players have no ``blocking`` attribute and evaluate false."""
    assert IsBlocking().test(FakePlayer(id=1), FakeState()) is False


# ---------- HasKeyword (uses real GameState/effective_keywords) ----------


def test_has_keyword_matches_printed_keyword():
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards.base import make_creature
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    flier = state.new_object(
        make_creature("Flier", "{1}{U}", 1, 1, keywords={"flying"}),
        0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(flier)
    assert HasKeyword("flying").test(flier, state) is True


def test_has_keyword_rejects_creature_without_keyword():
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards.base import make_creature
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    grounded = state.new_object(
        make_creature("Grounded", "{1}{G}", 2, 2), 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(grounded)
    assert HasKeyword("flying").test(grounded, state) is False


def test_has_keyword_false_for_player():
    """Players have no keywords."""
    assert HasKeyword("flying").test(FakePlayer(id=1), FakeState()) is False


# ---------- HasCounter ----------


def test_has_counter_plus_one_matches_creature_with_counter():
    obj = FakeObject(plus_one_counters=1)
    assert HasCounter("+1/+1").test(obj, FakeState()) is True


def test_has_counter_plus_one_rejects_creature_without_counter():
    obj = FakeObject(plus_one_counters=0)
    assert HasCounter("+1/+1").test(obj, FakeState()) is False


def test_has_counter_supports_other_kinds():
    charged = FakeObject(charge_counters=2)
    stunned = FakeObject(stun_counters=1)
    walker = FakeObject(loyalty_counters=4)
    assert HasCounter("charge").test(charged, FakeState()) is True
    assert HasCounter("stun").test(stunned, FakeState()) is True
    assert HasCounter("loyalty").test(walker, FakeState()) is True


def test_has_counter_kinds_are_independent():
    obj = FakeObject(plus_one_counters=0, charge_counters=3)
    assert HasCounter("+1/+1").test(obj, FakeState()) is False


def test_has_counter_unknown_kind_raises():
    obj = FakeObject(plus_one_counters=5)
    with pytest.raises(KeyError):
        HasCounter("+2/+2").test(obj, FakeState())


# ---------- HasPowerAtMost (uses real GameState/effective_power) ----------


def test_has_power_at_most_true_for_small_creature():
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards.base import make_creature
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    small = state.new_object(
        make_creature("Small", "{G}", 1, 1), 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(small)
    assert HasPowerAtMost(2).test(small, state) is True


def test_has_power_at_most_false_for_big_creature():
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards.base import make_creature
    from mtg_bot.game import GameState, Player, Zone

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    big = state.new_object(
        make_creature("Big", "{4}{G}", 5, 5), 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(big)
    assert HasPowerAtMost(2).test(big, state) is False


def test_has_power_at_most_false_for_player():
    """Players don't have a power."""
    assert HasPowerAtMost(2).test(FakePlayer(id=1), FakeState()) is False


# ---------- combinators ----------


def test_object_and_short_circuits_on_false():
    obj = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    pred = IsCreature() & IsLand()
    assert isinstance(pred, ObjectAnd)
    assert pred.test(obj, FakeState()) is False


def test_object_and_returns_true_when_both_match():
    obj = FakeObject(
        printing=FakePrinting(card_types=("Artifact", "Creature"))
    )
    pred = IsCreature() & IsArtifact()
    assert pred.test(obj, FakeState()) is True


def test_object_or_returns_true_if_any_matches():
    obj = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    pred = IsLand() | IsCreature()
    assert isinstance(pred, ObjectOr)
    assert pred.test(obj, FakeState()) is True


def test_object_not_inverts():
    obj = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    pred = ~IsLand()
    assert isinstance(pred, ObjectNot)
    assert pred.test(obj, FakeState()) is True


# ---------- ABC ----------


def test_object_predicate_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        ObjectPredicate()  # type: ignore[abstract]
