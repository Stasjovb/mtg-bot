"""Tests for the Duskmourn spells / enchantments / equipment / artifacts
batch-3 parser additions.

This batch claims more unclaimed Duskmourn cards by extending the
existing builders with one new literal-line entry per shape and one
small primitive widening. Each new primitive remains reusable: the
literal-Equipment-ETB pattern is the same one Auxiliary Boosters
already rides, and the spell-side Sequence path keeps working with
existing primitives once the new ``OwnerPutsTargetNonlandPermanent
OnTopOrBottomOfLibrary`` engine class lands.

Cards newly claimed in this batch:

* **Glimmerlight** ``{2}`` Artifact — Equipment — ETB-create-Glimmer-
  token (no attach) + ``Equipped creature gets +1/+1`` + ``Equip {1}``.
  Claimed by extending ``equipment_builder``'s literal-ETB-line table
  with the printed Glimmer line, dispatching to bare ``CreateToken``
  (NOT ``CreateTokenAndAttachSelf`` — the printed text never says
  "and attach").
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    TriggeredAbility,
)
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.generic import CreateToken
from mtg_bot.effects.predicates import Event, IsSelf


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- Glimmerlight: ETB-create-Glimmer-token Equipment ----------

def test_glimmerlight_claimed_by_parser():
    # Glimmerlight ``{2}`` Artifact — Equipment — claimed via the new
    # literal ETB line in ``equipment_builder``. Distinct from the
    # Auxiliary Boosters shape because the printed text never says
    # "and attach"; the Equipment stays unattached on the battlefield.
    assert "Glimmerlight" in _claimed_names()


def test_glimmerlight_carries_etb_create_glimmer_trigger():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the ETB trigger via bare ``CreateToken`` (not
    # ``CreateTokenAndAttachSelf``) against the canonical Glimmer
    # token printing.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Glimmerlight"]
    expected = TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf(),
        effect=CreateToken(
            token_printing=TOKEN_PRINTINGS["Glimmer"],
            count=1,
        ),
    )
    assert expected in p.triggered_abilities


def test_glimmerlight_carries_equipment_pump_and_equip_cost():
    # The remaining lines (``Equipped creature gets +1/+1.``,
    # ``Equip {1}``) ride the existing equipment_builder grammar — the
    # +1/+1 lands on ``equipment_bonuses`` and the equip cost lands as
    # an activated ability synthesized by ``make_equipment``.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Glimmerlight"]
    assert p.equipment_bonuses == (1, 1, frozenset())
    # ``make_equipment`` synthesizes an activated ability for the
    # equip cost. The cost mana-string is what we threaded onto the
    # printing.
    equip_costs = [
        a.cost.mana_str for a in p.activated_abilities
        if a.cost.mana_str
    ]
    assert "{1}" in equip_costs


def test_glimmerlight_resolves_etb_glimmer_token_creation():
    # End-to-end resolve sanity: when Glimmerlight's ETB trigger
    # resolves, a Glimmer token enters the battlefield under the
    # Equipment's controller. No attach happens — the Equipment stays
    # unattached.
    from mtg_bot.game import GameObject, GameState, Player, Zone

    parser = OracleParserCardSource()
    glimmerlight = parser.get_printings()["Glimmerlight"]
    eq_obj = GameObject(
        id=1, printing=glimmerlight, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[eq_obj],
    )
    # Resolve the ETB trigger directly — find the CreateToken trigger.
    create_trigger = next(
        t for t in glimmerlight.triggered_abilities
        if isinstance(t.effect, CreateToken)
    )
    create_trigger.effect.resolve(state, controller_id=0, targets=())
    # A Glimmer token now exists on the battlefield, controlled by P0.
    glimmer_tokens = [
        o for o in state.battlefield
        if o.printing.name == "Glimmer"
    ]
    assert len(glimmer_tokens) == 1
    assert glimmer_tokens[0].controller_id == 0
    # Glimmerlight itself stays unattached — no attach effect fired.
    assert eq_obj.attached_to is None
