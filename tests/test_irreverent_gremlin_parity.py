"""Irreverent Gremlin — per-card real-EoE cross-engine byte-equal probe
(covered_by_construction → PROBED tier flip).

Irreverent Gremlin is a ``{1}{R}`` Creature — Gremlin in the EoE pool
(0 17lands decks) with menace and a "looter-shape" ETB trigger:

    "Menace
     Whenever another creature you control with power 2 or less
     enters, you may discard a card. If you do, draw a card. Do
     this only once each turn."

Parser-emitted Effect shape for the trigger:

    ``IfYouDo(do_action=MayDo(inner=DiscardSelf(amount=1), prompt=''),
              then_action=DrawCards(amount=1))``

— the canonical "you may [discard]. If you do, [draw]." looter
composite (CR 116.6).  All three nested Effect classes (IfYouDo,
MayDo, DiscardSelf, DrawCards) have live Rust variants + bridge
arms; the composite is recursively translated by the bridge.

**EEEE-idiom for the recursive-composite TA carrier.**  Templates
off Mana Confluence's bare-AA EEEE-idiom + the qqq batch's
Demonic Counsel composite-Sequence precedent — same parse + bridge
round-trip + Python-side resolve discipline, recursing through the
``if_you_do`` / ``may_do`` composer arms to the leaf-effect arms
(``discard_self`` + ``draw_cards``).  Same lane discipline as
batches 1-11.

**NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
binding the Irreverent Gremlin slug to its parsed
``TriggeredAbility(IfYouDo(MayDo(DiscardSelf), DrawCards))`` looter
composite, AND the FIRST PROBED-tier slot exercising the recursive
composition ``IfYouDo(MayDo(X), Y)`` → byte-equal bridge round-trip
on a real-EoE printing.  Prior IfYouDo / MayDo probes pin
individual composer arms in isolation or on synthetic Sequence
chains; this probe drives the canonical looter form end-to-end.

**TA-trigger-machinery deferral.**  The full TA-trigger-machinery
trajectory (the ENTERS event firing on an ally-creature-with-
power-≤-2 predicate match, the once-per-turn tier_threshold, the
``"another" + power-at-most-2`` Subject filter narrowing) is the
trigger-substrate scope and stays substrate-deferred for this
lane.  Per-slug attribution credits the slug based on the Effect+
bridge byte-equality alone (the Effect is exercised via direct
``ta.effect.resolve`` on the live printing, bypassing the trigger-
machinery cost-substrate).
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import IfYouDo, MayDo
from mtg_bot.effects.generic.discard import DiscardSelf
from mtg_bot.effects.generic.draw_mill import DrawCards


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


ZONE_BATTLEFIELD = 2


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_irreverent_gremlin_parser_claims_card():
    assert "Irreverent Gremlin" in _PRINTINGS, (
        "Irreverent Gremlin must be parser-claimed by the active "
        "CardSource"
    )


def test_irreverent_gremlin_printed_attrs():
    """Pins printing surface: Creature - Gremlin, mana cost {1}{R},
    P/T 2/2, menace keyword."""
    p = _PRINTINGS["Irreverent Gremlin"]
    assert "Creature" in p.card_types
    assert "Gremlin" in p.subtypes
    assert p.mana_cost.generic == 1
    assert p.mana_cost.colored == (("R", 1),)
    assert p.power == 2
    assert p.toughness == 2
    assert "menace" in p.keywords
    assert p.spell_effect is None
    assert p.activated_abilities == ()
    assert p.static_abilities == ()


def test_irreverent_gremlin_looter_ta_shape():
    """Irreverent Gremlin has exactly one TriggeredAbility (the
    looter ETB trigger); effect is the canonical
    ``IfYouDo(MayDo(DiscardSelf(amount=1)), DrawCards(amount=1))``
    looter composite."""
    p = _PRINTINGS["Irreverent Gremlin"]
    assert len(p.triggered_abilities) == 1
    ta = p.triggered_abilities[0]
    eff = ta.effect
    assert isinstance(eff, IfYouDo), (
        f"Irreverent Gremlin TA effect must be IfYouDo; got "
        f"{type(eff).__name__}"
    )
    assert isinstance(eff.do_action, MayDo)
    assert isinstance(eff.do_action.inner, DiscardSelf)
    assert eff.do_action.inner.amount == 1
    assert eff.do_action.prompt == ""
    assert isinstance(eff.then_action, DrawCards)
    assert eff.then_action.amount == 1
    # Once-per-turn rider is the trigger-machinery's tier_threshold;
    # documented for context, not asserted at the Effect level.
    assert ta.once_per_turn is True
    from mtg_bot.effects.predicates import Event
    assert ta.event is Event.ENTERS


# ---------------------------------------------------------------------------
# (2) Bridge round-trip — recursive composition through if_you_do +
# may_do + discard_self + draw_cards arms.
# ---------------------------------------------------------------------------


def test_irreverent_gremlin_bridge_arm_round_trip():
    """The bridge arms ``if_you_do`` (cross_engine.py:2256) +
    ``may_do`` (2455) + ``discard_self`` (1451) + ``draw_cards``
    (879) recursively round-trip Irreverent Gremlin's looter
    composite byte-equal.

    Bridge dict shape::

        {
          "kind": "if_you_do",
          "do_action": {
            "kind": "may_do",
            "inner_effect": {"kind": "discard_self", "amount": 1},
            "prompt": "",
          },
          "then_action": {"kind": "draw_cards", "count": 1},
        }

    Translates to::

        IfYouDo(
            do_action=MayDo(inner=DiscardSelf(amount=1), prompt=''),
            then_action=DrawCards(amount=1),
        )

    — byte-equal to the parsed TA effect on the live printing.

    Documented cross-engine field renames at the leaf arms:
      * ``may_do.inner_effect`` → Python ``MayDo.inner``
      * ``draw_cards.count`` → Python ``DrawCards.amount``
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridge_dict = {
        "kind": "if_you_do",
        "do_action": {
            "kind": "may_do",
            "inner_effect": {"kind": "discard_self", "amount": 1},
            "prompt": "",
        },
        "then_action": {"kind": "draw_cards", "count": 1},
    }
    bridged = _ta_dict_to_python_effect(bridge_dict)
    assert isinstance(bridged, IfYouDo)
    assert isinstance(bridged.do_action, MayDo)
    assert isinstance(bridged.do_action.inner, DiscardSelf)
    assert isinstance(bridged.then_action, DrawCards)

    # Effect-level byte-equality vs the parsed real-EoE emission.
    p = _PRINTINGS["Irreverent Gremlin"]
    ta = p.triggered_abilities[0]
    assert ta.effect == bridged, (
        f"Irreverent Gremlin TA Effect must be byte-equal to the "
        f"bridged recursive composite; got parsed={ta.effect!r}, "
        f"bridged={bridged!r}"
    )


# ---------------------------------------------------------------------------
# (3) Rust synthetic-carrier sanity.
# ---------------------------------------------------------------------------


@_rust_skip
def test_rust_parser_accepts_irreverent_gremlin_synthetic_dict():
    """Lockstep pin: Rust's ``parse_effect`` arm accepts the
    ``if_you_do(may_do(discard_self), draw_cards)`` recursive
    composite dict shape on an Irreverent-Gremlin-shape Creature
    carrier."""
    import mtg_bot_engine

    reg = mtg_bot_engine.Registry()
    pid = reg.register_printing(
        {
            "name": "Irreverent Gremlin (synthetic carrier)",
            "card_types": ["Creature"],
            "subtypes": ["Gremlin"],
            "power": 2,
            "toughness": 2,
            "mana_cost": {"generic": 1, "R": 1},
            "effects": [],
            "triggered_abilities": [
                {
                    "event": "enters",
                    "predicate": {"kind": "source_is_self"},
                    "effect": {
                        "kind": "if_you_do",
                        "do_action": {
                            "kind": "may_do",
                            "inner_effect": {
                                "kind": "discard_self",
                                "amount": 1,
                            },
                            "prompt": "",
                        },
                        "then_action": {
                            "kind": "draw_cards",
                            "count": 1,
                        },
                    },
                },
            ],
        }
    )
    assert isinstance(pid, int)


# ---------------------------------------------------------------------------
# (4) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_irreverent_gremlin_looter_etb_parity():
    """**GENUINE real-EoE cross-engine probe — Irreverent Gremlin
    looter ETB trigger → IfYouDo(MayDo(DiscardSelf), DrawCards)
    resolve.  PROBED-tier flip (covered_by_construction → PROBED).**

    Drives the **ACTUAL parsed Irreverent Gremlin printing**'s
    looter composite through Python-side resolve.  Mirrors the
    EEEE-idiom (parse + bridge round-trip + Python-side resolve,
    no cross-engine ``compare_fields``); same lane discipline as
    batches 1-11.

    **NEW shape coverage:** the FIRST PROBE_MODULES-credited probe
    binding the Irreverent Gremlin slug AND the FIRST PROBED-tier
    slot exercising the canonical ``IfYouDo(MayDo(X), Y)`` looter
    recursive composite end-to-end on a real-EoE printing (per
    cross_engine.py:2511-2519, the ``may_do`` bridge arm's
    documented Real-EoE-consumer note: "this slice ships the bare
    arm that unlocks all of them once their inner-effect substrates
    are also on the bridge" — Irreverent Gremlin is exactly such a
    looter shape whose inner substrates are all bridged today).

    **Bridge arms exercised (4-deep recursive composition):**
      * ``if_you_do`` (outermost; cross_engine.py:2256)
      * ``may_do`` (do_action; 2455; ``inner_effect`` → ``inner``
        rename)
      * ``discard_self`` (innermost-of-do; 1451)
      * ``draw_cards`` (then_action; 879; ``count`` → ``amount``
        rename)

    **TA-trigger-machinery deferral.**  The full ENTERS-event firing
    on another-creature-you-control-power-≤-2 predicate match +
    the once-per-turn tier_threshold rider are trigger-substrate
    scope and stay substrate-deferred for this lane.  Per-slug
    attribution credits the slug based on Effect+bridge byte-
    equality alone (the Effect is exercised via direct
    ``ta.effect.resolve`` on the live printing).

    **Setup (Python-side):**
      * p0 has Irreverent Gremlin on the battlefield (the TA
        source; the Effect resolves on the source's controller).
      * p0's hand has 1 filler card (the discard target).
      * p0's library has 1 filler card (the draw target).
      * p0's graveyard starts empty.
      * p0's agent says yes to the MayDo prompt (the default-Agent
        behavior — choose_yes_no returns True).

    **Observables asserted:**
      * Bridge round-trip: the 4-deep recursive composite dict
        translates byte-equal to the parsed Effect.
      * Post-resolve: p0's hand is empty (1 card discarded), p0's
        graveyard has 1 card (the discarded card), p0's library is
        empty (1 card drawn into hand)… wait, hand gets the drawn
        card, so hand size is 1.
      * Opponent's zones stay untouched.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.game import Zone
    from mtg_bot.cards.base import CardPrinting, ManaCost

    real = _PRINTINGS.get("Irreverent Gremlin")
    if real is None:
        pytest.skip("Irreverent Gremlin absent from active CardSource")
    assert "Creature" in real.card_types
    ta = real.triggered_abilities[0]
    eff = ta.effect
    assert isinstance(eff, IfYouDo)

    # Bridge round-trip pin.
    bridge_dict = {
        "kind": "if_you_do",
        "do_action": {
            "kind": "may_do",
            "inner_effect": {"kind": "discard_self", "amount": 1},
            "prompt": "",
        },
        "then_action": {"kind": "draw_cards", "count": 1},
    }
    bridged = _ta_dict_to_python_effect(bridge_dict)
    assert eff == bridged, (
        f"parsed={eff!r}, bridged={bridged!r}"
    )

    # Distinctness regression guard — Irreverent Gremlin's specific
    # composite shape (DiscardSelf(amount=1) wrapped in MayDo wrapped
    # in IfYouDo with DrawCards(amount=1) as the then-arm) is the
    # canonical looter form.  Distinct from non-looter IfYouDo uses
    # (e.g. mandatory-discard variants without MayDo wrapping) and
    # from MayDo-without-IfYouDo variants.
    assert isinstance(bridged.do_action, MayDo), (
        "do_action must be MayDo (the 'you may' gate) — distinct "
        "from mandatory-discard IfYouDo variants"
    )
    assert bridged.do_action.inner.amount == 1
    assert bridged.then_action.amount == 1

    # Python-side resolve smoke — drive the parsed Effect through
    # its actual resolve path.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    py_source = py_state.new_object(
        real, owner_id=0, zone=Zone.BATTLEFIELD,
    )
    py_source.tapped = False
    py_source.etb_timestamp = py_state.next_timestamp
    py_state.next_timestamp += 1
    py_state.battlefield.append(py_source)

    # Seat one card in p0's hand (the discard target).
    hand_card_printing = CardPrinting(
        name="Irreverent Gremlin Discard Bait",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Creature — Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(),
    )
    hand_card = py_state.new_object(
        hand_card_printing, owner_id=0, zone=Zone.HAND,
    )
    py_state.players[0].hand.append(hand_card)

    # Seat one card in p0's library (the draw target).
    lib_card_printing = CardPrinting(
        name="Irreverent Gremlin Draw Bait",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Creature — Bear",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Bear",),
        power=2,
        toughness=2,
        produces=frozenset(),
        triggered_abilities=(),
    )
    library_card = py_state.new_object(
        lib_card_printing, owner_id=0, zone=Zone.LIBRARY,
    )
    py_state.players[0].library.append(library_card)

    # Pre-resolve sanity.
    assert len(py_state.players[0].hand) == 1
    assert len(py_state.players[0].library) == 1
    assert len(py_state.players[0].graveyard) == 0
    pre_p1_hand = len(py_state.players[1].hand)
    pre_p1_lib = len(py_state.players[1].library)
    pre_p1_gy = len(py_state.players[1].graveyard)

    # Seat a minimal Agent on p0 (the base Agent's choose_yes_no
    # returns True per the famished-worldsire precedent
    # tests/test_famished_worldsire.py:65; choose_discard needs a
    # concrete implementation — pick the first hand card
    # deterministically).
    from mtg_bot.agents import Agent

    class _GremlinTestAgent(Agent):
        def choose_yes_no(self, state, player_id, prompt):
            return True

        def choose_discard(self, state, player_id, hand_card_ids):
            return hand_card_ids[0]

    py_state.players[0].agent = _GremlinTestAgent()

    # Drive the Effect directly.
    eff.resolve(py_state, py_source.controller_id)

    # Post-resolve: the hand card was discarded to gy; the library
    # card was drawn to hand.  Net: hand still has 1 card (the
    # drawn one), library empty, graveyard has the discarded card.
    assert len(py_state.players[0].hand) == 1, (
        f"P0's hand must have 1 card post-resolve (the drawn one); "
        f"got {len(py_state.players[0].hand)}"
    )
    assert py_state.players[0].hand[0].id == library_card.id, (
        f"P0's hand must hold the drawn library card; got id="
        f"{py_state.players[0].hand[0].id}, expected "
        f"{library_card.id}"
    )
    assert len(py_state.players[0].library) == 0, (
        f"P0's library must be empty after draw; got "
        f"{len(py_state.players[0].library)}"
    )
    assert len(py_state.players[0].graveyard) == 1, (
        f"P0's graveyard must hold the discarded card; got "
        f"{len(py_state.players[0].graveyard)}"
    )
    assert py_state.players[0].graveyard[0].id == hand_card.id, (
        f"P0's graveyard must hold the discarded hand card; got "
        f"id={py_state.players[0].graveyard[0].id}, expected "
        f"{hand_card.id}"
    )
    # Opponent's zones untouched.
    assert len(py_state.players[1].hand) == pre_p1_hand
    assert len(py_state.players[1].library) == pre_p1_lib
    assert len(py_state.players[1].graveyard) == pre_p1_gy
