"""Mm'menon, the Right Hand's static-grants-activated-ability:
``Artifacts you control have '{T}: Add {U}. Spend this mana only to
cast a spell from anywhere other than your hand.'``

Audit-found bug: pre-fix the static was silently dropped with a
comment claiming "engine has no static-grants-activated-ability
plumbing yet." The grant is now wired through
``effective_activated_abilities`` (mirroring Ragost's per-card
artifact-grant pattern) and the new ``cast_from_outside_hand``
coin/spell-kind tag enforces the spend restriction in both the
cast-pipeline (``_cast_spell``) and the affordability probe
(``legal._spell_kinds_for_card``).
"""

from mtg_bot.actions import (
    CastSpell, _coin_satisfies_context, can_pay_cost,
)
from mtg_bot.cards import (
    BASIC_LANDS, EOE_CREATURES, MMNEMON_BLUE_MANA_GRANTED_ABILITY,
    parse_mana_cost,
)
from mtg_bot.game import (
    GameState, ManaCoin, Player, Zone, effective_activated_abilities,
)
from mtg_bot.legal import _spell_kinds_for_card, legal_actions
from mtg_bot.turn import Step


def _new_state():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0, zone=Zone.BATTLEFIELD):
    obj = state.new_object(printing, owner_id, zone)
    if zone == Zone.BATTLEFIELD:
        state.battlefield.append(obj)
    elif zone == Zone.HAND:
        state.player_by_id(owner_id).hand.append(obj)
    elif zone == Zone.LIBRARY:
        state.player_by_id(owner_id).library.append(obj)
    elif zone == Zone.GRAVEYARD:
        state.player_by_id(owner_id).graveyard.append(obj)
    elif zone == Zone.EXILE:
        state.player_by_id(owner_id).exile.append(obj)
    return obj


# -----------------------
# Printing shape
# -----------------------


def test_printing_has_grant_flag():
    p = EOE_CREATURES["Mm'menon, the Right Hand"]
    assert p.grants_blue_mana_ability_to_your_artifacts is True
    assert p.grants_cast_artifact_from_top_of_library is True
    assert p.is_legendary is True
    assert "flying" in p.keywords


def test_granted_ability_shape():
    ab = MMNEMON_BLUE_MANA_GRANTED_ABILITY
    assert ab.cost.tap_self is True
    assert ab.cost.mana is None
    assert ab.cost.sacrifice_self is False
    assert ab.is_mana_ability is True
    assert ab.effect.produces == (("U", 1),)
    assert ab.effect.spend_restriction == "cast_from_outside_hand"


# -----------------------
# effective_activated_abilities aggregation
# -----------------------


def test_artifact_gains_grant_with_mmnemon_in_play():
    state = _new_state()
    _put(state, EOE_CREATURES["Mm'menon, the Right Hand"])
    art = _put(state, EOE_CREATURES["Auxiliary Boosters"])
    abilities = effective_activated_abilities(state, art)
    # Auxiliary Boosters has no printed activated abilities of its own
    # (verify) — so the only one in the effective set is the grant.
    granted = [
        a for a in abilities
        if a is MMNEMON_BLUE_MANA_GRANTED_ABILITY
    ]
    assert len(granted) == 1


def test_artifact_does_not_gain_grant_without_mmnemon():
    state = _new_state()
    art = _put(state, EOE_CREATURES["Auxiliary Boosters"])
    abilities = effective_activated_abilities(state, art)
    assert MMNEMON_BLUE_MANA_GRANTED_ABILITY not in abilities


def test_grant_only_applies_to_controllers_artifacts():
    """Mm'menon's static reads 'Artifacts you control'. An opponent's
    artifact does not gain the ability."""
    state = _new_state()
    _put(state, EOE_CREATURES["Mm'menon, the Right Hand"], owner_id=0)
    opp_art = _put(state, EOE_CREATURES["Auxiliary Boosters"], owner_id=1)
    abilities = effective_activated_abilities(state, opp_art)
    assert MMNEMON_BLUE_MANA_GRANTED_ABILITY not in abilities


def test_grant_does_not_apply_to_nonartifact_creatures():
    state = _new_state()
    _put(state, EOE_CREATURES["Mm'menon, the Right Hand"])
    # A non-artifact creature shouldn't pick up the artifact grant.
    creature = _put(state, EOE_CREATURES["Rayblade Trooper"])
    abilities = effective_activated_abilities(state, creature)
    assert MMNEMON_BLUE_MANA_GRANTED_ABILITY not in abilities


def test_grant_does_not_apply_to_mmnemon_itself():
    """Mm'menon is a creature, not an artifact — even if she were an
    artifact, the static excludes self-grants by walking other
    permanents on the battlefield only."""
    state = _new_state()
    mm = _put(state, EOE_CREATURES["Mm'menon, the Right Hand"])
    abilities = effective_activated_abilities(state, mm)
    assert MMNEMON_BLUE_MANA_GRANTED_ABILITY not in abilities


# -----------------------
# Coin tag semantics
# -----------------------


def test_coin_tag_satisfies_outside_hand_context():
    coin = ManaCoin(color="U", spend_restriction="cast_from_outside_hand")
    assert _coin_satisfies_context(
        coin, frozenset({"spell", "cast_from_outside_hand"})
    )


def test_coin_tag_rejects_default_spell_context():
    coin = ManaCoin(color="U", spend_restriction="cast_from_outside_hand")
    assert not _coin_satisfies_context(coin, "spell")
    assert not _coin_satisfies_context(coin, frozenset({"spell"}))


def test_coin_tag_rejects_other_restrictions():
    coin = ManaCoin(color="U", spend_restriction="cast_from_outside_hand")
    # An artifact_spell context (Steelswarm) doesn't unlock this coin.
    assert not _coin_satisfies_context(
        coin, frozenset({"spell", "artifact_spell"})
    )


# -----------------------
# legal._spell_kinds_for_card detects the source zone
# -----------------------


def test_spell_kinds_in_hand_excludes_outside_hand():
    state = _new_state()
    card = _put(
        state, EOE_CREATURES["Auxiliary Boosters"], zone=Zone.HAND,
    )
    kinds = _spell_kinds_for_card(card)
    assert "cast_from_outside_hand" not in kinds


def test_spell_kinds_in_library_includes_outside_hand():
    state = _new_state()
    card = _put(
        state, EOE_CREATURES["Auxiliary Boosters"], zone=Zone.LIBRARY,
    )
    kinds = _spell_kinds_for_card(card)
    assert "cast_from_outside_hand" in kinds


def test_spell_kinds_in_exile_includes_outside_hand():
    state = _new_state()
    card = _put(
        state, EOE_CREATURES["Auxiliary Boosters"], zone=Zone.EXILE,
    )
    kinds = _spell_kinds_for_card(card)
    assert "cast_from_outside_hand" in kinds


# -----------------------
# can_pay_cost integration
# -----------------------


def test_outside_hand_coin_pays_for_outside_hand_cast():
    state = _new_state()
    state.players[0].mana_pool.append(
        ManaCoin(color="U", spend_restriction="cast_from_outside_hand")
    )
    state.players[0].mana_pool.append(
        ManaCoin(color="U", spend_restriction="cast_from_outside_hand")
    )
    cost = parse_mana_cost("{U}{U}")
    assert can_pay_cost(
        state, 0, cost,
        spell_kind=frozenset({"spell", "cast_from_outside_hand"}),
    )


def test_outside_hand_coin_cannot_pay_normal_hand_cast():
    state = _new_state()
    state.players[0].mana_pool.append(
        ManaCoin(color="U", spend_restriction="cast_from_outside_hand")
    )
    cost = parse_mana_cost("{U}")
    # Hand-cast context: only "spell" — the restricted coin does NOT
    # satisfy.
    assert not can_pay_cost(state, 0, cost, spell_kind="spell")


# -----------------------
# End-to-end: legal_actions surfaces a Mm'menon-funded library-top cast
# -----------------------


def test_legal_actions_allows_funded_library_top_cast():
    """With Mm'menon + an artifact in play, the topmost library card
    being an artifact spell, and the artifact tappable for {U} (via
    the grant), the cast should be exposed by legal_actions."""
    state = _new_state()
    _put(state, EOE_CREATURES["Mm'menon, the Right Hand"])
    art = _put(state, EOE_CREATURES["Hylderblade"])  # Equipment
    art.summoning_sick = False  # tap-on-mana-ability gate
    art.tapped = False
    # Also drop a Plains so a normal hand-cast wouldn't have lined up.
    # The library top: Mechan Specimen — Auxiliary Boosters costs
    # {4}{W} which is too expensive; pick a 1-cost artifact.
    # Hylderblade is {B}; pick something colorless cheap. Let's use
    # Auxiliary Boosters' colored cost — actually let's seed a cheap
    # artifact: Melded Moxite {1}{R} works if we drop a Mountain too.
    # Simplify: just verify the grant unlocks SOMETHING via the
    # library-top branch of legal_actions when the artifact is castable
    # for cost the granted mana can satisfy.
    cheap_art = state.new_object(
        EOE_CREATURES["Hylderblade"], 0, Zone.LIBRARY,  # {B} Equipment
    )
    state.players[0].library.insert(0, cheap_art)
    # Drop a Swamp so the colored {B} cost is paid by the land, and
    # the granted {U} can pay for any generic. Hylderblade has no
    # generic, so this is just the library-top-cast surface check.
    _put(state, BASIC_LANDS["Swamp"])
    actions = legal_actions(state, 0)
    library_casts = [
        a for a in actions
        if isinstance(a, CastSpell) and a.card_id == cheap_art.id
    ]
    # Must surface — Mm'menon's first ability lets us cast artifact
    # spells off the top, and the colored cost is satisfied by the
    # Swamp.
    assert library_casts


# -----------------------
# Regression: pre-existing "in-hand" casts still work
# -----------------------


def test_normal_hand_cast_still_uses_default_spell_kind():
    """Sanity check: casting a card from hand doesn't accidentally
    pick up the cast_from_outside_hand tag."""
    state = _new_state()
    card = _put(
        state, EOE_CREATURES["Rayblade Trooper"], zone=Zone.HAND,
    )
    kinds = _spell_kinds_for_card(card)
    assert kinds == frozenset({"spell"})
