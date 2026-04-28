"""Tests for the Duskmourn spells / enchantments / equipment batch-2
parser additions.

This batch claims more unclaimed Duskmourn cards by composing existing
engine classes (with one targeted widening of ``DestroyTargetCreature``
for the ``or_enchantment`` flag) and minor grammar additions. Each new
primitive is reusable across cards and across sets, so the regex
additions in ``parser.effects`` aren't DSK-specific even though every
card claimed by this batch ships in Duskmourn.

New engine-class field:

* ``DestroyTargetCreature.or_enchantment`` — when True, widens the
  legal-target pool to also include any enchantment (Aura subtype or
  not), mirroring the existing ``or_spacecraft`` flag's shape. The
  enchantment branch emits ``("enchantment", id)`` target tuples; the
  resolve accepts either kind and finds the object by id.

New effect-grammar primitives (``parser.effects``):

* ``destroy target creature or enchantment`` →
  ``DestroyTargetCreature(or_enchantment=True)``. Mirrors the existing
  ``destroy target creature or Spacecraft`` shape but for the
  enchantment widening.

Cards newly claimed:

* **Withering Torment** ``{2}{B}`` Instant — ``Destroy target creature
  or enchantment. You lose 2 life.`` Two-sentence body parses through
  the existing Sequence combinator path (sentence-split) once the new
  destroy-target-creature-or-enchantment primitive lands.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    DestroyTargetCreature,
    DrawCards,
    ExileTargetCreature,
    LoseLife,
    Sequence,
)
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.generic import CreateToken


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- destroy-target-creature-or-enchantment primitive ----------

def test_parse_destroy_target_creature_or_enchantment():
    # New primitive: widens DestroyTargetCreature's target pool to
    # also include any enchantment (Aura or not). Engine flag
    # parallels the existing ``or_spacecraft``.
    eff = _parse_effect("destroy target creature or enchantment")
    assert eff == DestroyTargetCreature(or_enchantment=True)


def test_destroy_target_creature_or_enchantment_legal_targets_widening():
    # Belt-and-suspenders that the engine flag actually widens the
    # legal-target pool. With ``or_enchantment=True``, an enchantment
    # on the battlefield should be a legal target alongside any
    # creature.
    from mtg_bot.cards.base import (
        make_creature,
        make_enchantment,
    )
    from mtg_bot.game import GameObject, GameState, Player, Zone

    creature_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    ench_pr = make_enchantment("Tome", "{1}{U}")
    creature_obj = GameObject(
        id=1, printing=creature_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    ench_obj = GameObject(
        id=2, printing=ench_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[creature_obj, ench_obj],
    )
    eff = DestroyTargetCreature(or_enchantment=True)
    legal = eff.legal_targets(state, controller_id=0)
    # Both should be legal: creature kind for the creature, enchantment
    # kind for the enchantment.
    assert ("creature", 1) in legal
    assert ("enchantment", 2) in legal


def test_destroy_target_creature_default_excludes_enchantment():
    # Without ``or_enchantment``, the bare ``destroy target creature``
    # primitive must NOT pick up enchantments — the widening only
    # applies when the flag is set.
    from mtg_bot.cards.base import make_enchantment
    from mtg_bot.game import GameObject, GameState, Player, Zone

    ench_pr = make_enchantment("Tome", "{1}{U}")
    ench_obj = GameObject(
        id=2, printing=ench_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[ench_obj],
    )
    eff = DestroyTargetCreature()
    assert eff.legal_targets(state, controller_id=0) == []


def test_destroy_target_creature_describe_includes_enchantment_suffix():
    # The ``describe`` helper should reflect the new flag in its
    # English-ish output, mirroring the ``or_spacecraft`` suffix.
    eff = DestroyTargetCreature(or_enchantment=True)
    assert "enchantment" in eff.describe()


# ---------- Withering Torment claim ----------

def test_withering_torment_claimed_by_parser():
    # Withering Torment ``{2}{B}`` Instant — two-sentence body that
    # combines the new destroy-target-creature-or-enchantment
    # primitive with the existing ``you lose 2 life`` primitive,
    # composed via Sequence by the spell-effect parser's sentence-
    # split path.
    assert "Withering Torment" in _claimed_names()


def test_withering_torment_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the right Sequence shape (destroy with or_enchantment, then
    # lose 2 life).
    parser = OracleParserCardSource()
    p = parser.get_printings()["Withering Torment"]
    assert p.spell_effect == Sequence(effects=(
        DestroyTargetCreature(or_enchantment=True),
        LoseLife(amount=2),
    ))


# ---------- draw N cards (spelled-out cardinal) ----------

def test_parse_draw_two_cards():
    # Extension of ``_DRAW_N_CARDS`` to accept spelled-out small
    # cardinals — Glimmerburst's printed ``Draw two cards.`` prefix
    # needed this. Existing digit form must still work.
    assert _parse_effect("draw two cards") == DrawCards(amount=2)


def test_parse_draw_three_cards_spelled():
    # Forward-looking grammar coverage — no DSK card prints
    # ``draw three cards`` today, but the regex shape allows it
    # without further grammar work.
    assert _parse_effect("draw three cards") == DrawCards(amount=3)


def test_parse_draw_n_cards_digit_form_still_works():
    # The pre-existing digit form must continue to parse to the same
    # engine class.
    assert _parse_effect("draw 2 cards") == DrawCards(amount=2)


def test_parse_draw_unknown_word_returns_none():
    # An unrecognized word in the cardinal slot must not parse as a
    # draw effect (the regex's whitelist of small cardinals enforces
    # this — anything outside the table fails the alternation).
    assert _parse_effect("draw eleventy cards") is None


# ---------- Glimmerburst claim ----------

def test_glimmerburst_claimed_by_parser():
    # Glimmerburst ``{2}{W}{U}`` Instant — two-sentence body with
    # ``Draw two cards.`` + ``Create a 1/1 white Glimmer enchantment
    # creature token.`` Both pieces parse via existing primitives
    # (with the new draw-N-cards-spelled-out cardinal extension);
    # composed via Sequence by the spell-effect parser.
    assert "Glimmerburst" in _claimed_names()


def test_glimmerburst_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the right Sequence shape (draw 2, then mint Glimmer token).
    parser = OracleParserCardSource()
    p = parser.get_printings()["Glimmerburst"]
    assert p.spell_effect == Sequence(effects=(
        DrawCards(amount=2),
        CreateToken(token_printing=TOKEN_PRINTINGS["Glimmer"], count=1),
    ))


# ---------- Final Vengeance: additional-cost preamble flag ----------

def test_final_vengeance_claimed_by_parser():
    # Final Vengeance ``{1}{B}{B}`` Sorcery — additional-cost-sacrifice
    # preamble (creature-or-enchantment variant) + ``Exile target
    # creature.`` Claimed via the new printing flag on the additional-
    # cost preamble dispatcher; base effect is the existing
    # ``ExileTargetCreature``.
    assert "Final Vengeance" in _claimed_names()


def test_final_vengeance_carries_additional_cost_flag():
    # The additional-cost-sacrifice-creature-or-enchantment flag must
    # be threaded onto the ``CardPrinting`` so the engine's cast-time
    # cost-paying path knows to demand the sacrifice. The base spell
    # effect is the bare ``ExileTargetCreature`` — the additional-cost
    # preamble itself doesn't contribute an effect.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Final Vengeance"]
    assert p.additional_cost_sacrifice_creature_or_enchantment is True
    assert p.spell_effect == ExileTargetCreature()


def test_final_vengeance_additional_cost_gates_legal_actions():
    # Belt-and-suspenders that the new printing flag actually gates
    # casting at legal-actions time — without a creature OR enchantment
    # to sacrifice, the spell is not castable.
    from mtg_bot.cards.base import make_creature
    from mtg_bot.game import GameObject, GameState, Player, Zone
    from mtg_bot.legal import _additional_costs_payable

    parser = OracleParserCardSource()
    final_vengeance = parser.get_printings()["Final Vengeance"]
    # Build a minimal hand-card and battlefield. The card itself is
    # in P0's hand; the battlefield is empty so the cost is unpayable.
    card_obj = GameObject(
        id=10, printing=final_vengeance, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[],
    )
    assert _additional_costs_payable(state, 0, card_obj) is False
    # Now put a creature on P0's battlefield — the cost becomes payable.
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    state.battlefield.append(GameObject(
        id=11, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    ))
    assert _additional_costs_payable(state, 0, card_obj) is True


def test_final_vengeance_additional_cost_accepts_enchantment_sacrifice():
    # An Enchantment on P0's battlefield is also a valid sac target —
    # Final Vengeance's printed cost says "creature OR enchantment".
    from mtg_bot.cards.base import make_enchantment
    from mtg_bot.game import GameObject, GameState, Player, Zone
    from mtg_bot.legal import _additional_costs_payable

    parser = OracleParserCardSource()
    final_vengeance = parser.get_printings()["Final Vengeance"]
    card_obj = GameObject(
        id=10, printing=final_vengeance, owner_id=0, controller_id=0,
        zone=Zone.HAND,
    )
    ench_pr = make_enchantment("Tome", "{1}{U}")
    ench_obj = GameObject(
        id=12, printing=ench_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[ench_obj],
    )
    assert _additional_costs_payable(state, 0, card_obj) is True
