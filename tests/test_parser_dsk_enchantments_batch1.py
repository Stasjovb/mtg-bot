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

* **Sporogenic Infection** ``{1}{B}`` Enchantment — Aura. ETB target-
  opp-sacs-creature-other-than-enchanted + DEALT_DAMAGE-destroys-
  enchanted. The new
  ``TargetOpponentSacrificesCreatureOtherThanEnchanted`` engine
  class identifies the host via ``state.resolving_source.attached_to``
  and excludes it from the target's sac options. ``target player``
  narrows to ``target opponent`` per the same simplification Cracked
  Skull rides.
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


# ---------- Sporogenic Infection ----------


def test_sporogenic_infection_claimed_by_parser():
    # Sporogenic Infection ``{1}{B}`` Enchantment — Aura — claimed via
    # the name-keyed ``_ENCHANTMENT_BUILDERS`` dispatch.
    assert "Sporogenic Infection" in _claimed_names()


def test_sporogenic_infection_carries_etb_and_dealt_damage_triggers():
    # The produced ``CardPrinting`` carries two triggers, in printed
    # order:
    # 1. ETB target-opp-sacs-creature-other-than-enchanted via the
    #    new ``TargetOpponentSacrificesCreatureOtherThanEnchanted``
    #    engine class.
    # 2. DEALT_DAMAGE-destroys-host via ``DestroyEnchantedPermanent``.
    from mtg_bot.effects import (
        DestroyEnchantedPermanent,
        TargetOpponentSacrificesCreatureOtherThanEnchanted,
    )

    parser = OracleParserCardSource()
    p = parser.get_printings()["Sporogenic Infection"]
    assert len(p.triggered_abilities) == 2
    etb, dealt = p.triggered_abilities
    assert isinstance(
        etb.effect,
        TargetOpponentSacrificesCreatureOtherThanEnchanted,
    )
    assert isinstance(dealt.effect, DestroyEnchantedPermanent)


def test_sporogenic_infection_is_aura_with_correct_cost():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Sporogenic Infection"]
    assert p.mana_cost_str == "{1}{B}"
    assert p.is_aura is True
    assert p.aura_enchant_type == "creature"
    # Printed ``Enchant creature`` (any creature), not the yours-only
    # restriction. Self-targeting at cast-time pays for the printed
    # text; the ETB's target narrowing is a separate axis.
    assert p.aura_yours_only is False


# ---------- TargetOpponentSacrificesCreatureOtherThanEnchanted ----------


def test_sac_other_than_enchanted_legal_targets_is_opps_only():
    from mtg_bot.effects import (
        TargetOpponentSacrificesCreatureOtherThanEnchanted,
    )
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    eff = TargetOpponentSacrificesCreatureOtherThanEnchanted()
    legal = eff.legal_targets(state, controller_id=0)
    assert ("player", 1) in legal
    assert ("player", 0) not in legal
    assert eff.requires_target() is True


def test_sac_other_than_enchanted_excludes_host_from_options():
    # End-to-end resolve sanity: the target opp controls the enchanted
    # creature (host) plus a second creature. The host must not appear
    # in the sac options; the target must sacrifice the OTHER creature.
    from mtg_bot.cards.base import make_aura, make_creature
    from mtg_bot.effects import (
        TargetOpponentSacrificesCreatureOtherThanEnchanted,
    )
    from mtg_bot.game import GameObject, GameState, Player, Zone

    aura_pr = make_aura("TestSac", "{1}{B}")
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)

    host = GameObject(
        id=10, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    other = GameObject(
        id=11, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    aura = GameObject(
        id=20, printing=aura_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    aura.attached_to = host.id

    seen_options: list[list[int]] = []

    class _Agent:
        def choose_sacrifice(self, state, player_id, options):
            seen_options.append(list(options))
            return options[0]

    p0 = Player(id=0)
    p1 = Player(id=1)
    p1.agent = _Agent()
    state = GameState(
        players=[p0, p1],
        battlefield=[host, other, aura],
        resolving_source=aura,
    )
    eff = TargetOpponentSacrificesCreatureOtherThanEnchanted()
    eff.resolve(state, controller_id=0, targets=(("player", 1),))
    # The agent saw ONLY the non-host id.
    assert seen_options == [[11]]
    # The non-host creature is now in the graveyard; the host is still
    # on the battlefield.
    assert other not in state.battlefield
    assert host in state.battlefield


def test_sac_other_than_enchanted_no_legal_silently_no_ops():
    # When the target opp's only creature is the enchanted creature,
    # there are no legal sac options — the trigger silently no-ops.
    from mtg_bot.cards.base import make_aura, make_creature
    from mtg_bot.effects import (
        TargetOpponentSacrificesCreatureOtherThanEnchanted,
    )
    from mtg_bot.game import GameObject, GameState, Player, Zone

    aura_pr = make_aura("TestSac", "{1}{B}")
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    host = GameObject(
        id=10, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    aura = GameObject(
        id=20, printing=aura_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    aura.attached_to = host.id

    class _AssertAgent:
        def choose_sacrifice(self, state, player_id, options):
            raise AssertionError("should not be prompted with no options")

    p0 = Player(id=0)
    p1 = Player(id=1)
    p1.agent = _AssertAgent()
    state = GameState(
        players=[p0, p1],
        battlefield=[host, aura],
        resolving_source=aura,
    )
    eff = TargetOpponentSacrificesCreatureOtherThanEnchanted()
    eff.resolve(state, controller_id=0, targets=(("player", 1),))
    # Host survives.
    assert host in state.battlefield


def test_sac_other_than_enchanted_describe():
    from mtg_bot.effects import (
        TargetOpponentSacrificesCreatureOtherThanEnchanted,
    )

    desc = TargetOpponentSacrificesCreatureOtherThanEnchanted().describe()
    assert "sacrif" in desc
    assert "other than enchanted" in desc
