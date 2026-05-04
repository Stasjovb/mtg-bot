"""Engine-resolve tests for parser-shape primitives in
``mtg_bot/effects/generic/misc.py``. The existing
``test_cytoshape.py`` and ``test_scuttlemutt.py`` exercise the
``resolve()`` happy paths, but the targeting-protocol surface
(``requires_target``, ``target_count_range``, ``target_slot_kinds``,
``legal_targets``, ``describe``) and a handful of resolve early-
returns weren't covered.

Round I of the coverage chip-away series. Targets:

* ``CytoshapeBecomeCopyUEOT`` — the four targeting-protocol
  methods, ``describe()``, plus the under-2-targets and
  target-not-on-battlefield resolve early returns.
* ``ScuttlemuttColorChangeUEOT`` — the targeting-protocol surface,
  ``describe()``, and the no-targets / target-not-on-battlefield /
  invalid-color-choice resolve early returns.
"""

from __future__ import annotations


# ---------- CytoshapeBecomeCopyUEOT targeting-protocol surface ----------


def test_cytoshape_requires_target():
    from mtg_bot.effects.generic.misc import CytoshapeBecomeCopyUEOT

    assert CytoshapeBecomeCopyUEOT().requires_target() is True


def test_cytoshape_target_count_range_is_two_two():
    """Two creature targets: the changed creature + the source whose
    printing is copied."""
    from mtg_bot.effects.generic.misc import CytoshapeBecomeCopyUEOT

    assert CytoshapeBecomeCopyUEOT().target_count_range() == (2, 2)


def test_cytoshape_target_slot_kinds_creature_creature():
    from mtg_bot.effects.generic.misc import CytoshapeBecomeCopyUEOT

    assert CytoshapeBecomeCopyUEOT().target_slot_kinds() == (
        "creature", "creature",
    )


def test_cytoshape_legal_targets_only_creatures():
    """Legal-target pool is every creature on the battlefield, both
    sides. Non-creature permanents are filtered out."""
    from mtg_bot.cards.base import make_artifact, make_creature
    from mtg_bot.effects.generic.misc import CytoshapeBecomeCopyUEOT
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    bear = GameObject(id=1, printing=bear_pr, owner_id=0, controller_id=0,
                      zone=Zone.BATTLEFIELD)
    arti_pr = make_artifact("Bauble", "{1}")
    arti = GameObject(id=2, printing=arti_pr, owner_id=0, controller_id=0,
                      zone=Zone.BATTLEFIELD)
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[bear, arti],
    )
    legal = CytoshapeBecomeCopyUEOT().legal_targets(state, 0)
    ids = {tid for kind, tid in legal if kind == "creature"}
    assert bear.id in ids
    assert arti.id not in ids


def test_cytoshape_describe():
    from mtg_bot.effects.generic.misc import CytoshapeBecomeCopyUEOT

    desc = CytoshapeBecomeCopyUEOT().describe()
    assert "becomes a copy" in desc
    assert "another target creature" in desc


# ---------- CytoshapeBecomeCopyUEOT resolve early-returns ----------


def test_cytoshape_resolve_under_two_targets_no_op():
    """``len(targets) < 2`` early-returns silently — the copy needs
    both slots filled."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.misc import CytoshapeBecomeCopyUEOT
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    bear = GameObject(id=1, printing=bear_pr, owner_id=0, controller_id=0,
                      zone=Zone.BATTLEFIELD)
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[bear],
    )
    CytoshapeBecomeCopyUEOT().resolve(
        state, 0, (("creature", bear.id),),  # only one target
    )
    # No printing change; no continuous effect.
    assert bear.printing.name == "Bear"
    assert bear.original_printing is None
    assert state.continuous_effects == []


def test_cytoshape_resolve_first_target_not_on_battlefield_no_op():
    """If the first target's id no longer matches a battlefield object
    — e.g. the chosen creature died between cast and resolve — the
    resolve early-returns."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.misc import CytoshapeBecomeCopyUEOT
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    bear = GameObject(id=1, printing=bear_pr, owner_id=0, controller_id=0,
                      zone=Zone.BATTLEFIELD)
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[bear],
    )
    CytoshapeBecomeCopyUEOT().resolve(
        state, 0,
        (("creature", 99), ("creature", bear.id)),  # 99 not on field
    )
    assert state.continuous_effects == []
    assert bear.original_printing is None


# ---------- ScuttlemuttColorChangeUEOT targeting-protocol surface ----------


def test_scuttlemutt_requires_target():
    from mtg_bot.effects.generic.misc import ScuttlemuttColorChangeUEOT

    assert ScuttlemuttColorChangeUEOT().requires_target() is True


def test_scuttlemutt_legal_targets_only_creatures():
    from mtg_bot.cards.base import make_artifact, make_creature
    from mtg_bot.effects.generic.misc import ScuttlemuttColorChangeUEOT
    from mtg_bot.game import GameObject, GameState, Player, Zone

    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    bear = GameObject(id=1, printing=bear_pr, owner_id=0, controller_id=0,
                      zone=Zone.BATTLEFIELD)
    arti_pr = make_artifact("Bauble", "{1}")
    arti = GameObject(id=2, printing=arti_pr, owner_id=0, controller_id=0,
                      zone=Zone.BATTLEFIELD)
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[bear, arti],
    )
    legal = ScuttlemuttColorChangeUEOT().legal_targets(state, 0)
    ids = {tid for kind, tid in legal if kind == "creature"}
    assert bear.id in ids
    assert arti.id not in ids


def test_scuttlemutt_describe():
    from mtg_bot.effects.generic.misc import ScuttlemuttColorChangeUEOT

    desc = ScuttlemuttColorChangeUEOT().describe()
    assert "color" in desc
    assert "until end of turn" in desc


# ---------- ScuttlemuttColorChangeUEOT resolve early-returns ----------


def test_scuttlemutt_resolve_no_targets_no_op():
    from mtg_bot.effects.generic.misc import ScuttlemuttColorChangeUEOT
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    ScuttlemuttColorChangeUEOT().resolve(state, 0, ())
    assert state.continuous_effects == []


def test_scuttlemutt_resolve_target_not_on_battlefield_no_op():
    from mtg_bot.effects.generic.misc import ScuttlemuttColorChangeUEOT
    from mtg_bot.game import GameState, Player

    state = GameState(players=[Player(id=0), Player(id=1)])
    ScuttlemuttColorChangeUEOT().resolve(
        state, 0, (("creature", 999),),  # no such id
    )
    assert state.continuous_effects == []


def test_scuttlemutt_resolve_invalid_color_choice_no_op():
    """Agent's ``choose_mana_color`` returned a string outside
    ``{W, U, B, R, G}`` — the resolve early-returns without writing
    a registry entry."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects.generic.misc import ScuttlemuttColorChangeUEOT
    from mtg_bot.game import GameObject, GameState, Player, Zone

    class _BadColorAgent:
        def choose_mana_color(self, state, controller_id, options):
            return "X"  # invalid — resolve drops the effect

    bear_pr = make_creature("Bear", "{1}{G}", 2, 2)
    bear = GameObject(id=1, printing=bear_pr, owner_id=0, controller_id=0,
                      zone=Zone.BATTLEFIELD)
    p0 = Player(id=0, agent=_BadColorAgent())
    state = GameState(
        players=[p0, Player(id=1)],
        battlefield=[bear],
    )
    ScuttlemuttColorChangeUEOT().resolve(
        state, 0, (("creature", bear.id),),
    )
    # Invalid color → no continuous effect written.
    assert state.continuous_effects == []
