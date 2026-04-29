"""Tests for the Duskmourn enchantments batch-1 parser additions.

Each commit in this batch lands one DSK enchantment via name-keyed
dispatch on the existing ``enchantment_builder`` table.

Cards newly claimed in this batch:

* **Shardmage's Rescue** ``{W}`` Enchantment — Aura. Flash +
  Enchant-creature-you-control + ``Enchanted creature gets +1/+1``.
  The conditional ``As long as this Aura entered this turn, enchanted
  creature has hexproof`` line is dropped as an honest no-op:
  hexproof is engine-unenforced metadata in this codebase (the
  rooms-batch6 Lecture Hall precedent), so a conditional grant is
  identically a no-op.

* **Cracked Skull** ``{2}{B}`` Enchantment — Aura. ETB look-at-target-
  opp-hand may-discard + DEALT_DAMAGE-destroys-enchanted. The new
  ``TargetOpponentLookHandMayDiscard`` engine class honours the
  printed ``You may`` gate via ``Agent.choose_yes_no`` rather than
  forcing the discard the way ``TargetOpponentDiscardsCasterChoice``
  does. ``target player`` is narrowed to ``target opponent`` per the
  standard EoE / DSK simplification — self-targeting is never
  strategically correct for the controller. The destroys-host
  trigger rides the same shape Cryoshatter's bottom trigger uses.
"""

from __future__ import annotations

from mtg_bot.cards.parser_source import OracleParserCardSource


def _claimed_names() -> tuple[str, ...]:
    return OracleParserCardSource().claimed_names


# ---------- Shardmage's Rescue ----------


def test_shardmages_rescue_claimed_by_parser():
    # Shardmage's Rescue ``{W}`` Enchantment — Aura — claimed via the
    # name-keyed ``_ENCHANTMENT_BUILDERS`` dispatch in
    # ``parser.enchantment_builder``.
    assert "Shardmage's Rescue" in _claimed_names()


def test_shardmages_rescue_carries_flash_and_yours_only():
    # The produced ``CardPrinting`` carries:
    # - Flash on the Aura itself (``keywords`` contains "flash"),
    #   gating instant-speed casting via the same ``legal.py`` check
    #   Frantic Strength rides;
    # - ``aura_yours_only=True`` for the printed
    #   ``Enchant creature you control`` line — same flag Sheltered by
    #   Ghosts already ships.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Shardmage's Rescue"]
    assert "flash" in p.keywords
    assert p.aura_yours_only is True


def test_shardmages_rescue_grants_plus_one_plus_one():
    # ``Enchanted creature gets +1/+1`` rides the shared
    # ``equipment_bonuses`` machinery (the (power, toughness, keywords)
    # tuple ``make_aura`` materializes from its kwargs). The granted
    # keyword set is empty — the printed conditional hexproof line is
    # dropped as an honest no-op since hexproof is engine-unenforced
    # metadata in this codebase.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Shardmage's Rescue"]
    power_bonus, toughness_bonus, granted = p.equipment_bonuses
    assert power_bonus == 1
    assert toughness_bonus == 1
    assert granted == frozenset()


def test_shardmages_rescue_has_no_etb_trigger():
    # No ETB trigger is wired — the printed text only carries the
    # static rider and the conditional (dropped) hexproof grant. A
    # spurious trigger would be a regression; assert empty.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Shardmage's Rescue"]
    assert p.triggered_abilities == ()


def test_shardmages_rescue_is_aura_with_correct_cost_and_type():
    # Cost is ``{W}`` (single white). Type line ``Enchantment — Aura``;
    # ``aura_enchant_type`` defaults to ``"creature"`` (the printed
    # ``Enchant creature you control`` restriction is the
    # ``aura_yours_only`` flag, not a type change).
    parser = OracleParserCardSource()
    p = parser.get_printings()["Shardmage's Rescue"]
    assert p.mana_cost_str == "{W}"
    assert p.is_aura is True
    assert p.aura_enchant_type == "creature"


# ---------- Cracked Skull ----------


def test_cracked_skull_claimed_by_parser():
    # Cracked Skull ``{2}{B}`` Enchantment — Aura — claimed via the
    # name-keyed ``_ENCHANTMENT_BUILDERS`` dispatch.
    assert "Cracked Skull" in _claimed_names()


def test_cracked_skull_carries_etb_and_dealt_damage_triggers():
    # The produced ``CardPrinting`` carries two triggers, in printed
    # order:
    # 1. ETB-look-may-discard via ``TargetOpponentLookHandMayDiscard``
    # 2. DEALT_DAMAGE-destroys-host via ``DestroyEnchantedPermanent``
    from mtg_bot.effects import (
        DestroyEnchantedPermanent, TargetOpponentLookHandMayDiscard,
    )

    parser = OracleParserCardSource()
    p = parser.get_printings()["Cracked Skull"]
    assert len(p.triggered_abilities) == 2
    etb, dealt = p.triggered_abilities
    assert isinstance(etb.effect, TargetOpponentLookHandMayDiscard)
    assert isinstance(dealt.effect, DestroyEnchantedPermanent)


def test_cracked_skull_is_aura_with_correct_cost():
    # Cost is ``{2}{B}``. ``aura_enchant_type`` defaults to
    # ``"creature"`` (printed ``Enchant creature``, not the yours-only
    # variant).
    parser = OracleParserCardSource()
    p = parser.get_printings()["Cracked Skull"]
    assert p.mana_cost_str == "{2}{B}"
    assert p.is_aura is True
    assert p.aura_enchant_type == "creature"
    assert p.aura_yours_only is False


# ---------- TargetOpponentLookHandMayDiscard engine class ----------


def test_may_discard_legal_targets_is_opponents_only():
    # The simplified ``target player`` -> ``target opponent`` legality
    # narrowing means the caster is never offered themselves as a
    # target. Two-player smoke test: P0 controls; only P1 should be
    # listed.
    from mtg_bot.effects import TargetOpponentLookHandMayDiscard
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    eff = TargetOpponentLookHandMayDiscard()
    legal = eff.legal_targets(state, controller_id=0)
    assert ("player", 1) in legal
    assert ("player", 0) not in legal
    assert eff.requires_target() is True


def test_may_discard_yes_no_yes_path_discards_chosen_card():
    # End-to-end resolve sanity: target opp has a nonland and a land in
    # hand; caster says yes, picks the nonland, opp discards it.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.cards.lands import BASIC_LANDS
    from mtg_bot.effects import TargetOpponentLookHandMayDiscard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    bear_card = GameObject(
        id=10, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.HAND,
    )
    forest_pr = BASIC_LANDS["Forest"]
    forest_card = GameObject(
        id=11, printing=forest_pr, owner_id=1, controller_id=1,
        zone=Zone.HAND,
    )
    p0 = Player(id=0)
    p1 = Player(id=1, hand=[bear_card, forest_card])

    class _YesAgent:
        def choose_yes_no(self, state, player_id, prompt):
            return True

        def choose_card_from_opponent_hand(
            self, state, player_id, opponent_hand_ids,
        ):
            # Pick the bear (10) — the nonland.
            return 10

    p0.agent = _YesAgent()
    state = GameState(players=[p0, p1])
    eff = TargetOpponentLookHandMayDiscard()
    eff.resolve(state, controller_id=0, targets=(("player", 1),))
    assert bear_card not in p1.hand
    assert bear_card in p1.graveyard
    # The land stays in hand.
    assert forest_card in p1.hand


def test_may_discard_yes_no_no_path_keeps_hand_intact():
    # The caster declines via ``choose_yes_no`` returning False; no
    # discard happens. Honors the printed ``You may`` gate.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import TargetOpponentLookHandMayDiscard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    bear_card = GameObject(
        id=10, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.HAND,
    )
    p0 = Player(id=0)
    p1 = Player(id=1, hand=[bear_card])

    class _NoAgent:
        def choose_yes_no(self, state, player_id, prompt):
            return False

        def choose_card_from_opponent_hand(
            self, state, player_id, opponent_hand_ids,
        ):
            # Should never be reached when the may-gate is declined.
            raise AssertionError(
                "choose_card_from_opponent_hand called after decline"
            )

    p0.agent = _NoAgent()
    state = GameState(players=[p0, p1])
    eff = TargetOpponentLookHandMayDiscard()
    eff.resolve(state, controller_id=0, targets=(("player", 1),))
    # Hand unchanged.
    assert bear_card in p1.hand
    assert p1.graveyard == []


def test_may_discard_no_nonland_options_silently_no_ops():
    # If the target's hand has no nonland card, the directed discard
    # silently no-ops — the may-gate is never even prompted.
    from mtg_bot.cards.lands import BASIC_LANDS
    from mtg_bot.effects import TargetOpponentLookHandMayDiscard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    forest_pr = BASIC_LANDS["Forest"]
    forest_card = GameObject(
        id=11, printing=forest_pr, owner_id=1, controller_id=1,
        zone=Zone.HAND,
    )
    p0 = Player(id=0)
    p1 = Player(id=1, hand=[forest_card])

    class _AssertAgent:
        def choose_yes_no(self, state, player_id, prompt):
            raise AssertionError("may-gate prompted with no options")

        def choose_card_from_opponent_hand(
            self, state, player_id, opponent_hand_ids,
        ):
            raise AssertionError("never called")

    p0.agent = _AssertAgent()
    state = GameState(players=[p0, p1])
    eff = TargetOpponentLookHandMayDiscard()
    eff.resolve(state, controller_id=0, targets=(("player", 1),))
    assert forest_card in p1.hand
    assert p1.graveyard == []


def test_may_discard_no_agent_silently_declines():
    # When the caster has no agent, the directed discard silently
    # declines — the engine never auto-discards on the caster's
    # behalf.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import TargetOpponentLookHandMayDiscard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    bear_card = GameObject(
        id=10, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.HAND,
    )
    p0 = Player(id=0)  # no agent
    p1 = Player(id=1, hand=[bear_card])
    state = GameState(players=[p0, p1])
    eff = TargetOpponentLookHandMayDiscard()
    eff.resolve(state, controller_id=0, targets=(("player", 1),))
    assert bear_card in p1.hand
    assert p1.graveyard == []


def test_may_discard_describe_mentions_may_and_nonland():
    from mtg_bot.effects import TargetOpponentLookHandMayDiscard

    desc = TargetOpponentLookHandMayDiscard().describe()
    assert "may" in desc
    assert "nonland" in desc
