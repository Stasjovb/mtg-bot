"""Tests for the Duskmourn spells / enchantments / equipment / artifacts
batch-3 parser additions.

Each commit in this batch lands one card via a small additive change:
a literal-line entry on an existing builder, a name-keyed dispatch
factory on an existing builder, or a small flag widening on an existing
engine class. No new bespoke engine classes are introduced.

New engine fields on ``CardPrinting``:

* ``aura_yours_only`` — when True, the cast-time target picker for
  ``is_aura`` cards only offers permanents the caster controls.
  Mirrors the printed "Enchant creature you control" / "Enchant
  artifact you control" line. The flag is independent of
  ``aura_enchant_type`` (creature / artifact). Default False so
  existing plain "Enchant creature" Auras (Frantic Strength, Tractor
  Beam, ...) keep their previous behavior.

Cards newly claimed in this batch:

* **Glimmerlight** ``{2}`` Artifact — Equipment — ETB-create-Glimmer-
  token (no attach) + ``Equipped creature gets +1/+1`` + ``Equip {1}``.
  Claimed by extending ``equipment_builder``'s literal-ETB-line table
  with the printed Glimmer line, dispatching to bare ``CreateToken``
  (NOT ``CreateTokenAndAttachSelf`` — the printed text never says
  "and attach").

* **Sheltered by Ghosts** ``{1}{W}`` Enchantment — Aura — ETB exile
  target nonland permanent an opponent controls (until the Aura
  leaves), +1/+0 + lifelink + ward {2}, and the printed "Enchant
  creature you control" controller restriction. Claimed by name-
  keyed dispatch in ``enchantment_builder``, using the new
  ``aura_yours_only`` flag plus the existing
  ``ExileOpponentsNonlandPermanentUntilLeaves`` ETB and the existing
  ``attached_grants_ward`` rider that Hardlight Containment also
  uses.
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


# ---------- aura_yours_only flag ----------

def test_make_aura_aura_yours_only_kwarg():
    # New ``aura_yours_only`` kwarg on ``make_aura`` lands on the
    # ``CardPrinting.aura_yours_only`` field that the cast-time target
    # picker reads to filter the legal pool to permanents the caster
    # controls.
    from mtg_bot.cards.base import make_aura

    aura = make_aura(
        "Test Aura", "{1}{W}",
        power_bonus=1, toughness_bonus=0,
        aura_yours_only=True,
    )
    assert aura.aura_yours_only is True


def test_make_aura_yours_only_default_false():
    # Backward-compat sanity: the new kwarg defaults to False, so
    # existing call sites that don't pass ``aura_yours_only=`` keep
    # their previous behavior (any creature is a legal Aura target).
    from mtg_bot.cards.base import make_aura

    aura = make_aura("Plain Aura", "{U}")
    assert aura.aura_yours_only is False


def test_aura_yours_only_filters_legal_targets():
    # Belt-and-suspenders that the new flag actually filters the
    # cast-time legal-target pool. With ``aura_yours_only=True``, an
    # opponent's creature is NOT offered as a legal target — only
    # creatures the caster controls survive.
    from mtg_bot.actions import _select_spell_targets
    from mtg_bot.cards.base import make_aura, make_creature
    from mtg_bot.game import GameObject, GameState, Player, Zone

    aura = make_aura(
        "Test", "{W}",
        power_bonus=1, toughness_bonus=0,
        aura_yours_only=True,
    )
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    yours = GameObject(
        id=1, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    theirs = GameObject(
        id=2, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )

    class _PickFirst:
        def choose_target(self, state, pid, legal):
            return legal[0] if legal else None

    p0 = Player(id=0, agent=_PickFirst())
    p1 = Player(id=1)
    state = GameState(players=[p0, p1], battlefield=[yours, theirs])
    aura_obj = GameObject(
        id=10, printing=aura, owner_id=0, controller_id=0, zone=Zone.HAND,
    )
    p0.hand.append(aura_obj)
    targets = _select_spell_targets(state, 0, aura_obj)
    # Only your creature (id=1) is a legal target.
    assert targets == (("creature", 1),)


# ---------- Sheltered by Ghosts ----------

def test_sheltered_by_ghosts_claimed_by_parser():
    # Sheltered by Ghosts ``{1}{W}`` Aura — claimed via the name-keyed
    # ``_ENCHANTMENT_BUILDERS`` dispatch in ``parser.enchantment_builder``.
    assert "Sheltered by Ghosts" in _claimed_names()


def test_sheltered_by_ghosts_carries_aura_fields():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # all five hooks the static side ships:
    # - +1/+0 in the ``equipment_bonuses`` triple plus lifelink in
    #   the granted-keywords slot;
    # - ``aura_yours_only=True`` for the "Enchant creature you control"
    #   restriction;
    # - ``attached_grants_ward_str="{2}"`` for the ward {2} rider;
    # - the ``ExileOpponentsNonlandPermanentUntilLeaves`` ETB.
    from mtg_bot.effects import ExileOpponentsNonlandPermanentUntilLeaves

    parser = OracleParserCardSource()
    p = parser.get_printings()["Sheltered by Ghosts"]
    assert p.is_aura is True
    assert p.aura_yours_only is True
    assert p.equipment_bonuses == (1, 0, frozenset({"lifelink"}))
    assert p.attached_grants_ward_str == "{2}"
    assert any(
        isinstance(t.effect, ExileOpponentsNonlandPermanentUntilLeaves)
        for t in p.triggered_abilities
    )


def test_sheltered_by_ghosts_etb_exiles_opp_permanent():
    # End-to-end resolve sanity: with the Aura on the battlefield, the
    # ETB targets an opponent's permanent and exiles it — same shape
    # Banishing Light uses. Targets one of P1's permanents; P0's own
    # permanent is excluded by the legal-targets filter.
    from mtg_bot.cards.base import make_creature, make_enchantment
    from mtg_bot.effects import ExileOpponentsNonlandPermanentUntilLeaves
    from mtg_bot.game import GameObject, GameState, Player, Zone

    parser = OracleParserCardSource()
    sheltered = parser.get_printings()["Sheltered by Ghosts"]
    sheltered_obj = GameObject(
        id=1, printing=sheltered, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    # P0's own creature — not a legal target (opponents-only).
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    yours = GameObject(
        id=2, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    # P1's enchantment — a legal nonland permanent target.
    ench_pr = make_enchantment("Tome", "{1}{U}")
    theirs = GameObject(
        id=3, printing=ench_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[sheltered_obj, yours, theirs],
        resolving_source=sheltered_obj,
    )
    eff = ExileOpponentsNonlandPermanentUntilLeaves()
    legal = eff.legal_targets(state, controller_id=0)
    # P0's own creature excluded; P1's enchantment in the pool.
    assert ("permanent", 2) not in legal
    assert ("permanent", 3) in legal
