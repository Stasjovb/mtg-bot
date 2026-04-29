"""Tests for the Duskmourn artifacts / Equipment batch-3 parser
additions.

Each commit in this batch lands one Toy artifact creature via name-keyed
bespoke dispatch on ``creature_builder``. Each card claims a single
bespoke effect class in ``mtg_bot.effects.bespoke``; no parser grammar
is extended (the DSK Toy family's printed shapes are too card-specific
to share a primitive).
"""

from __future__ import annotations

from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects.predicates import Event


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- Splitskin Doll ----------

def test_splitskin_doll_claimed_by_parser():
    # Splitskin Doll lands via name-keyed bespoke dispatch in
    # ``_BESPOKE_ARTIFACT_CREATURES``.
    assert "Splitskin Doll" in _claimed_names()


def test_splitskin_doll_carries_etb_with_bespoke_effect():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries a
    # single ENTERS trigger via the bespoke ``SplitskinDollETBEffect``
    # engine class. The effect handles both halves of the printed
    # body — the unconditional draw and the conditional discard — in
    # one resolve step.
    from mtg_bot.effects.bespoke import SplitskinDollETBEffect

    p = OracleParserCardSource().get_printings()["Splitskin Doll"]
    assert p.power == 2 and p.toughness == 1
    assert p.is_artifact is True
    assert "Toy" in p.subtypes
    etb = [t for t in p.triggered_abilities if t.event == Event.ENTERS]
    assert len(etb) == 1
    assert isinstance(etb[0].effect, SplitskinDollETBEffect)


# ---------- SplitskinDollETBEffect engine class ----------

def test_splitskin_effect_describe():
    from mtg_bot.effects.bespoke import SplitskinDollETBEffect

    desc = SplitskinDollETBEffect().describe()
    assert "draw a card" in desc
    assert "discard" in desc
    assert "power 2 or less" in desc


def test_splitskin_effect_dodges_discard_when_another_creature_with_power_2_present():
    # When the controller controls another creature whose effective
    # power is 2 or less, the discard is dodged — only the draw fires.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.bespoke import SplitskinDollETBEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    class _Agent:
        def choose_discard(self, state, pid, hand_ids):
            return hand_ids[0]

    doll_pr = make_creature(
        "Splitskin Doll", "{1}{W}", 2, 1, artifact=True,
        subtypes=("Toy",),
    )
    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    doll = GameObject(
        id=1, printing=doll_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    other = GameObject(
        id=2, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    deck = GameObject(
        id=10, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.LIBRARY,
    )
    hand_card = GameObject(
        id=11, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    p0 = Player(id=0, agent=_Agent(), library=[deck], hand=[hand_card])
    p1 = Player(id=1)
    state = GameState(
        players=[p0, p1],
        battlefield=[doll, other],
        resolving_source=doll,
    )
    SplitskinDollETBEffect().resolve(state, controller_id=0, targets=())
    # Drew the deck card; discard was dodged so hand_card stays.
    assert deck in p0.hand
    assert hand_card in p0.hand
    assert hand_card not in p0.graveyard


def test_splitskin_effect_discards_when_no_other_small_creature():
    # Without another creature of power 2 or less, the discard fires
    # — the controller's agent picks via ``choose_discard``.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.bespoke import SplitskinDollETBEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    class _Agent:
        def choose_discard(self, state, pid, hand_ids):
            return hand_ids[0]

    doll_pr = make_creature(
        "Splitskin Doll", "{1}{W}", 2, 1, artifact=True,
        subtypes=("Toy",),
    )
    big_pr = make_creature("Big", "{4}{G}", 5, 5)
    doll = GameObject(
        id=1, printing=doll_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    big = GameObject(
        id=2, printing=big_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    deck = GameObject(
        id=10, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.LIBRARY,
    )
    hand_card = GameObject(
        id=11, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    p0 = Player(id=0, agent=_Agent(), library=[deck], hand=[hand_card])
    p1 = Player(id=1)
    state = GameState(
        players=[p0, p1],
        battlefield=[doll, big],
        resolving_source=doll,
    )
    SplitskinDollETBEffect().resolve(state, controller_id=0, targets=())
    # Drew the deck card; discarded the hand card (no dodger present —
    # the doll itself is excluded by the "another creature" clause and
    # ``big`` has power 5).
    assert deck in p0.hand
    assert hand_card not in p0.hand
    assert hand_card in p0.graveyard


def test_splitskin_effect_doll_does_not_count_as_its_own_dodger():
    # The doll itself has printed power 2, but the printed clause says
    # "another creature" — so the source must be excluded from the
    # dodger pool. With the doll as the only creature, the discard
    # fires.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.bespoke import SplitskinDollETBEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    class _Agent:
        def choose_discard(self, state, pid, hand_ids):
            return hand_ids[0]

    doll_pr = make_creature(
        "Splitskin Doll", "{1}{W}", 2, 1, artifact=True,
        subtypes=("Toy",),
    )
    doll = GameObject(
        id=1, printing=doll_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    deck = GameObject(
        id=10, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.LIBRARY,
    )
    hand_card = GameObject(
        id=11, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    p0 = Player(id=0, agent=_Agent(), library=[deck], hand=[hand_card])
    p1 = Player(id=1)
    state = GameState(
        players=[p0, p1],
        battlefield=[doll],
        resolving_source=doll,
    )
    SplitskinDollETBEffect().resolve(state, controller_id=0, targets=())
    assert hand_card in p0.graveyard


def test_splitskin_effect_no_op_on_empty_hand_after_no_dodger_path():
    # No dodger and an empty hand → the discard branch silently no-ops
    # (no exception, nothing to discard). ``p.agent`` is None so the
    # discard branch's guard short-circuits anyway.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.bespoke import SplitskinDollETBEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    doll_pr = make_creature(
        "Splitskin Doll", "{1}{W}", 2, 1, artifact=True,
        subtypes=("Toy",),
    )
    doll = GameObject(
        id=1, printing=doll_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    p0 = Player(id=0, library=[], hand=[])
    p1 = Player(id=1)
    state = GameState(
        players=[p0, p1],
        battlefield=[doll],
        resolving_source=doll,
    )
    SplitskinDollETBEffect().resolve(state, controller_id=0, targets=())


# ---------- Arabella, Abandoned Doll ----------

def test_arabella_claimed_by_parser():
    # Arabella lands via name-keyed bespoke dispatch in
    # ``_BESPOKE_LEGENDARY_CREATURES``.
    assert "Arabella, Abandoned Doll" in _claimed_names()


def test_arabella_carries_attacks_trigger_with_bespoke_effect():
    # Belt-and-suspenders that the produced ``CardPrinting`` is the
    # legendary artifact creature carrying the bespoke
    # ``ArabellaAttackEffect`` engine class on a single ATTACKS trigger.
    from mtg_bot.effects.bespoke import ArabellaAttackEffect

    p = OracleParserCardSource().get_printings()["Arabella, Abandoned Doll"]
    assert p.power == 1 and p.toughness == 3
    assert p.is_artifact is True
    assert "Legendary" in p.supertypes
    assert "Toy" in p.subtypes
    attacks = [
        t for t in p.triggered_abilities if t.event == Event.ATTACKS
    ]
    assert len(attacks) == 1
    assert isinstance(attacks[0].effect, ArabellaAttackEffect)


def test_arabella_effect_describe():
    from mtg_bot.effects.bespoke import ArabellaAttackEffect

    desc = ArabellaAttackEffect().describe()
    assert "X damage" in desc
    assert "power 2 or less" in desc


def test_arabella_effect_deals_damage_and_gains_life():
    # End-to-end: with two creatures of power 2 or less (Arabella herself
    # at 1 and a 2/2 bear), X = 2 — Arabella deals 2 to each opponent
    # and the controller gains 2 life.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.bespoke import ArabellaAttackEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    arabella_pr = make_creature(
        "Arabella, Abandoned Doll", "{R}{W}", 1, 3,
        artifact=True, legendary=True, subtypes=("Toy",),
    )
    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    arabella = GameObject(
        id=1, printing=arabella_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    bear = GameObject(
        id=2, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    p0 = Player(id=0, life=10)
    p1 = Player(id=1, life=20)
    state = GameState(
        players=[p0, p1],
        battlefield=[arabella, bear],
        resolving_source=arabella,
    )
    ArabellaAttackEffect().resolve(state, controller_id=0, targets=())
    # X = 2 (Arabella @ power 1, Bear @ power 2). Both creatures are
    # in the controller's count.
    assert p1.life == 18
    assert p0.life == 12


def test_arabella_effect_excludes_high_power_creatures():
    # A 5/5 doesn't satisfy the "power 2 or less" filter — only Arabella
    # counts, so X = 1.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.bespoke import ArabellaAttackEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    arabella_pr = make_creature(
        "Arabella, Abandoned Doll", "{R}{W}", 1, 3,
        artifact=True, legendary=True, subtypes=("Toy",),
    )
    big_pr = make_creature("Big", "{4}{G}", 5, 5)
    arabella = GameObject(
        id=1, printing=arabella_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    big = GameObject(
        id=2, printing=big_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    p0 = Player(id=0, life=10)
    p1 = Player(id=1, life=20)
    state = GameState(
        players=[p0, p1],
        battlefield=[arabella, big],
        resolving_source=arabella,
    )
    ArabellaAttackEffect().resolve(state, controller_id=0, targets=())
    assert p1.life == 19
    assert p0.life == 11


def test_arabella_effect_no_op_when_x_is_zero():
    # Without any creature of power 2 or less, X = 0 — the effect is
    # a silent no-op (no damage, no life gain).
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.bespoke import ArabellaAttackEffect
    from mtg_bot.game import GameObject, GameState, Player, Zone

    big_pr = make_creature("Big", "{4}{G}", 5, 5)
    big = GameObject(
        id=1, printing=big_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    p0 = Player(id=0, life=10)
    p1 = Player(id=1, life=20)
    state = GameState(
        players=[p0, p1], battlefield=[big],
        resolving_source=big,
    )
    ArabellaAttackEffect().resolve(state, controller_id=0, targets=())
    assert p1.life == 20
    assert p0.life == 10
