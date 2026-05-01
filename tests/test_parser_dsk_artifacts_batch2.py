"""Tests for the Duskmourn artifacts / Equipment batch-2 parser
additions.

Round 1 deferred a handful of DSK pure-artifact and Equipment cards as
needing engine-level work; this batch claims the additive subset.

This commit lands **Ghost Vacuum** ``{1}`` Artifact — two activations.
The first ``{T}: Exile target card from a graveyard.`` lands as the
new ``ExileTargetCardFromGraveyard`` generic effect, parsed via the
unified activated grammar (new primitive in ``effects.py``). The
second ``{6}, {T}, Sacrifice this artifact: …`` recall body now
decomposes into the parameterized
``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl``
primitive (with ``grant_flying_counter=True`` and
``grant_subtype_and_pt=("Spirit", 1, 1)``) — the bespoke
``GhostVacuumActivatedEffect`` was deleted when the
"exiled-with-this" infrastructure landed. The Round-1 "flying
counter" custom counter type is realized as a new
``GameObject.flying_counters`` integer field; ``effective_keywords``
adds ``"flying"`` to a bearer's keyword set whenever that field is
positive (CR 122 named-counter grant).
"""

from __future__ import annotations

from mtg_bot.cards.parser.source import OracleParserCardSource


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- Ghost Vacuum ----------

def test_ghost_vacuum_claimed_by_parser():
    # Ghost Vacuum ``{1}`` Artifact — two activations claimed via the
    # new ``ExileTargetCardFromGraveyard`` primitive (first ability)
    # plus the new literal-line dispatch for the ``{6}, {T}, Sacrifice
    # this artifact`` recall (second ability).
    assert "Ghost Vacuum" in _claimed_names()


def test_ghost_vacuum_carries_two_activations():
    # First ability: ``{T}: Exile target card from a graveyard.``
    # parses through the unified activated grammar via the
    # ``ExileTargetCardFromGraveyard`` primitive — bare ``{T}`` cost
    # (NOT a mana ability since the body doesn't add mana).
    # Second ability: ``{6}, {T}, Sacrifice this artifact:`` cost +
    # parameterized
    # ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYour
    # Control`` body via the multi-sentence literal-effect recognizer.
    # The trailing ``Activate only as a sorcery.`` rider lifts to
    # ``sorcery_speed=True`` on the ability.
    from mtg_bot.effects import (
        ExileTargetCardFromGraveyard,
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )

    parser = OracleParserCardSource()
    p = parser.get_printings()["Ghost Vacuum"]
    assert len(p.activated_abilities) == 2
    exile_ability = next(
        a for a in p.activated_abilities
        if isinstance(a.effect, ExileTargetCardFromGraveyard)
    )
    assert exile_ability.cost.mana_str == ""
    assert exile_ability.cost.tap_self is True
    assert exile_ability.cost.sacrifice_self is False
    assert exile_ability.sorcery_speed is False
    # Not flagged as a mana ability — the unified detector only
    # auto-flags ``AddManaToPool`` bodies.
    assert exile_ability.is_mana_ability is False

    recall = next(
        a for a in p.activated_abilities
        if isinstance(
            a.effect,
            PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
        )
    )
    assert recall.cost.mana_str == "{6}"
    assert recall.cost.tap_self is True
    assert recall.cost.sacrifice_self is True
    assert recall.sorcery_speed is True
    # Rider parameters carry through — flying counter grant + 1/1
    # Spirit subtype/PT grant.
    assert recall.effect.grant_flying_counter is True
    assert recall.effect.grant_subtype_and_pt == ("Spirit", 1, 1)


def test_ghost_vacuum_has_no_triggered_abilities_or_statics():
    # Belt-and-suspenders sanity: the printing has zero triggers and
    # zero statics — both abilities are activated.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Ghost Vacuum"]
    assert p.triggered_abilities == ()
    assert p.static_abilities == ()


# ---------- ExileTargetCardFromGraveyard engine class ----------

def test_exile_target_card_from_graveyard_describe():
    from mtg_bot.effects import ExileTargetCardFromGraveyard

    assert (
        ExileTargetCardFromGraveyard().describe()
        == "exile target card from a graveyard"
    )


def test_exile_target_card_from_graveyard_target_kind_pool():
    # Both players' graveyards contribute to the legal-target pool —
    # the printed body has no controller restriction.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import ExileTargetCardFromGraveyard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    yours = GameObject(
        id=1, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.GRAVEYARD,
    )
    theirs = GameObject(
        id=2, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.GRAVEYARD,
    )
    p0 = Player(id=0, graveyard=[yours])
    p1 = Player(id=1, graveyard=[theirs])
    state = GameState(players=[p0, p1])
    legal = ExileTargetCardFromGraveyard().legal_targets(
        state, controller_id=0,
    )
    assert ("card_in_graveyard", 1) in legal
    assert ("card_in_graveyard", 2) in legal


def test_exile_target_card_from_graveyard_moves_chosen_to_exile():
    # End-to-end resolve: the chosen graveyard card moves to its
    # owner's exile zone and gets ``exiled_by_source`` stamped to the
    # source's id.
    from mtg_bot.cards.base import make_artifact, make_creature
    from mtg_bot.effects import ExileTargetCardFromGraveyard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    target = GameObject(
        id=2, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.GRAVEYARD,
    )
    art_pr = make_artifact("Source", "{1}")
    source_obj = GameObject(
        id=10, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    p0 = Player(id=0)
    p1 = Player(id=1, graveyard=[target])
    state = GameState(
        players=[p0, p1],
        battlefield=[source_obj],
        resolving_source=source_obj,
    )
    ExileTargetCardFromGraveyard().resolve(
        state, controller_id=0,
        targets=(("card_in_graveyard", 2),),
    )
    assert target not in p1.graveyard
    assert target in p1.exile
    assert target.zone == Zone.EXILE
    assert target.exiled_by_source == source_obj.id


def test_exile_target_card_from_graveyard_no_target_is_noop():
    # Empty targets: silent no-op (same shape every other targeted
    # primitive in this grammar uses).
    from mtg_bot.effects import ExileTargetCardFromGraveyard
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    ExileTargetCardFromGraveyard().resolve(
        state, controller_id=0, targets=(),
    )
    # Nothing to assert beyond "didn't raise".


def test_exile_target_card_from_graveyard_invalid_kind_is_noop():
    # Wrong target kind: silent no-op rather than raising.
    from mtg_bot.effects import ExileTargetCardFromGraveyard
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    ExileTargetCardFromGraveyard().resolve(
        state, controller_id=0,
        targets=(("creature", 999),),
    )
    # Nothing to assert beyond "didn't raise".


def test_exile_target_card_from_graveyard_missing_card_is_noop():
    # Target id doesn't exist in any graveyard: silent no-op.
    from mtg_bot.effects import ExileTargetCardFromGraveyard
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    ExileTargetCardFromGraveyard().resolve(
        state, controller_id=0,
        targets=(("card_in_graveyard", 999),),
    )
    # Nothing to assert beyond "didn't raise".


def test_exile_target_card_from_graveyard_no_source_skips_link():
    # When ``resolving_source`` is None (engine misuse), the exile
    # still happens but ``exiled_by_source`` stays None — defensive
    # branch covers the case where the source has been cleared by an
    # earlier mid-resolution side effect.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import ExileTargetCardFromGraveyard
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    target = GameObject(
        id=2, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.GRAVEYARD,
    )
    p0 = Player(id=0)
    p1 = Player(id=1, graveyard=[target])
    state = GameState(players=[p0, p1])  # no resolving_source
    ExileTargetCardFromGraveyard().resolve(
        state, controller_id=0,
        targets=(("card_in_graveyard", 2),),
    )
    assert target in p1.exile
    assert target.exiled_by_source is None


# ---------- PutEachCreatureCardExiledWithSourceOnto... engine class ----------
# Ghost Vacuum's recall body now decomposes into the parameterized
# ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl``
# primitive (with the flying-counter and 1/1-Spirit-subtype/PT rider
# parameters set). The behavioral expectations mirror what the bespoke
# ``GhostVacuumActivatedEffect`` enforced — the rider parameters
# preserve the same per-card grants — so the tests below validate the
# integrated decomposition end-to-end.

def test_ghost_vacuum_decomposed_describe():
    from mtg_bot.effects import (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )

    desc = PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
        grant_flying_counter=True,
        grant_subtype_and_pt=("Spirit", 1, 1),
    ).describe()
    assert "exiled with this permanent" in desc
    assert "flying counter" in desc
    assert "1/1 Spirit" in desc


def test_ghost_vacuum_decomposed_recalls_creatures_with_flying_counter():
    # End-to-end: a creature card tagged ``exiled_by_source == source.id``
    # returns to the activator's battlefield with a flying counter and
    # the layer-4/7 grants for "1/1 Spirit". A non-creature card with
    # the same tag stays in exile (the body's filter is "each creature
    # card").
    from mtg_bot.cards.base import (
        make_artifact, make_creature,
    )
    from mtg_bot.effects import (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.game import (
        GameObject, GameState, Player, Zone, effective_keywords,
        effective_subtypes,
    )

    art_pr = make_artifact("Ghost Vacuum", "{1}")
    source_obj = GameObject(
        id=10, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.GRAVEYARD,  # already sacrificed at cost time
    )
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    exiled_creature = GameObject(
        id=20, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.EXILE, exiled_by_source=source_obj.id,
    )
    other_art = make_artifact("Junk", "{1}")
    exiled_artifact = GameObject(
        id=21, printing=other_art, owner_id=1, controller_id=1,
        zone=Zone.EXILE, exiled_by_source=source_obj.id,
    )
    p0 = Player(id=0)
    p1 = Player(id=1, exile=[exiled_creature, exiled_artifact])
    state = GameState(
        players=[p0, p1],
        resolving_source=source_obj,
    )
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
        grant_flying_counter=True,
        grant_subtype_and_pt=("Spirit", 1, 1),
    ).resolve(state, controller_id=0, targets=())
    # Creature returned, controlled by activator, with flying counter.
    assert exiled_creature in state.battlefield
    assert exiled_creature.controller_id == 0
    assert exiled_creature.flying_counters == 1
    assert "flying" in effective_keywords(state, exiled_creature)
    # Spirit subtype added; printed Bear stays.
    subs = effective_subtypes(state, exiled_creature)
    assert "Spirit" in subs
    # Non-creature artifact stays in exile.
    assert exiled_artifact in p1.exile


def test_ghost_vacuum_decomposed_no_op_when_no_exiled_creatures():
    # No tagged exile cards: silent log, no battlefield change.
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.game import GameObject, GameState, Player, Zone

    art_pr = make_artifact("Ghost Vacuum", "{1}")
    source_obj = GameObject(
        id=10, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.GRAVEYARD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        resolving_source=source_obj,
    )
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
        grant_flying_counter=True,
        grant_subtype_and_pt=("Spirit", 1, 1),
    ).resolve(state, controller_id=0, targets=())
    assert state.battlefield == []


def test_ghost_vacuum_decomposed_no_source_is_noop():
    # Defensive: ``resolving_source`` is None (engine misuse) → silent
    # no-op rather than raising.
    from mtg_bot.effects import (
        PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl,
    )
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYourControl(
        grant_flying_counter=True,
        grant_subtype_and_pt=("Spirit", 1, 1),
    ).resolve(state, controller_id=0, targets=())
    # Nothing to assert beyond "didn't raise".


# ---------- GameObject.flying_counters granted-keyword wiring ----------

def test_flying_counter_grants_flying_keyword():
    # Round 1's "flying counter" custom counter type is realized as
    # ``GameObject.flying_counters``; ``effective_keywords`` adds
    # ``"flying"`` whenever that field is positive.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.game import (
        GameObject, GameState, Player, Zone, effective_keywords,
    )

    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    obj = GameObject(
        id=1, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[obj],
    )
    # Without a flying counter: no flying.
    assert "flying" not in effective_keywords(state, obj)
    # With a flying counter: flying granted.
    obj.flying_counters = 1
    assert "flying" in effective_keywords(state, obj)


def test_flying_counter_does_not_grant_other_keywords():
    # The flying-counter grant is keyword-specific — having a flying
    # counter shouldn't synthesize, e.g., haste or trample. Sanity
    # belt-and-suspenders that future named-counter types each need
    # their own field-and-grant pair.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.game import (
        GameObject, GameState, Player, Zone, effective_keywords,
    )

    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    obj = GameObject(
        id=1, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD, flying_counters=1,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[obj],
    )
    kws = effective_keywords(state, obj)
    assert "flying" in kws
    assert "haste" not in kws
    assert "trample" not in kws
