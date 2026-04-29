"""Tests for the Duskmourn spells / enchantments / equipment / artifacts
batch-4 parser additions.

Each commit in this batch lands one card via a small additive change:
a literal-line entry on an existing builder, a name-keyed dispatch
factory on an existing builder, or a small flag widening on an existing
engine class. No new bespoke engine classes are introduced.

New ``make_enchantment`` kwarg:

* ``ward`` (e.g. ``"{2}"``) — wires the printed Ward keyword on a non-
  Aura Enchantment ITSELF. Mirrors the same-named kwarg on
  ``make_creature`` and routes through the same
  ``CardPrinting.ward_cost`` / ``ward_cost_str`` fields the engine's
  ward-check helpers already read. Auras keep their own
  ``attached_grants_ward`` kwarg for the "Enchanted permanent has
  ward" rider — the two kwargs stay distinct because the Aura form
  targets the enchanted permanent, not the Aura itself.

Cards newly claimed in this batch:

* **Trapped in the Screen** ``{2}{W}`` Enchantment — Ward {2} + ETB
  exile target artifact/creature/enchantment an opponent controls
  until this enchantment leaves the battlefield. Claimed by name-
  keyed dispatch in ``enchantment_builder``, using the new ``ward``
  kwarg on ``make_enchantment`` plus the existing
  ``ExileOpponentsNonlandPermanentUntilLeaves`` ETB. The
  ``artifact, creature, or enchantment`` target widening is
  functionally equivalent to ``nonland permanent`` for the EoE/DSK
  pool — same simplification Banishing Light's ETB already uses.
"""

from __future__ import annotations

from mtg_bot.cards.parser.source import OracleParserCardSource


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- ward kwarg on make_enchantment ----------

def test_make_enchantment_ward_kwarg():
    # New ``ward`` kwarg on ``make_enchantment`` lands on the
    # ``CardPrinting.ward_cost`` / ``ward_cost_str`` fields the
    # engine's ward-check helpers (``effective_ward_cost``,
    # ``_apply_ward_check``) already read. Mirrors the same-named
    # kwarg on ``make_creature``.
    from mtg_bot.cards.base import make_enchantment

    ench = make_enchantment("Test Ench", "{1}{W}", ward="{2}")
    assert ench.ward_cost_str == "{2}"
    assert ench.ward_cost is not None
    assert ench.ward_cost.total == 2


def test_make_enchantment_ward_default_none():
    # Backward-compat sanity: the new kwarg defaults to None, so
    # existing call sites that don't pass ``ward=`` keep their
    # previous behavior (no ward on the enchantment itself).
    from mtg_bot.cards.base import make_enchantment

    ench = make_enchantment("Plain Ench", "{W}")
    assert ench.ward_cost_str == ""
    assert ench.ward_cost is None


# ---------- Trapped in the Screen ----------

def test_trapped_in_the_screen_claimed_by_parser():
    # Trapped in the Screen ``{2}{W}`` Enchantment — claimed via the
    # name-keyed ``_ENCHANTMENT_BUILDERS`` dispatch in
    # ``parser.enchantment_builder``.
    assert "Trapped in the Screen" in _claimed_names()


def test_trapped_in_the_screen_carries_ward_and_etb():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # both halves of the printed text:
    # - Ward {2} on the enchantment itself (``ward_cost_str == "{2}"``);
    # - the ``ExileOpponentsNonlandPermanentUntilLeaves`` ETB —
    #   functionally equivalent to the printed ``artifact, creature,
    #   or enchantment`` an opponent controls scope, since the
    #   nonland-permanent legal-targets filter excludes the same
    #   things lands and (unmodeled) planeswalkers would.
    from mtg_bot.effects import ExileOpponentsNonlandPermanentUntilLeaves

    parser = OracleParserCardSource()
    p = parser.get_printings()["Trapped in the Screen"]
    assert p.ward_cost_str == "{2}"
    assert any(
        isinstance(t.effect, ExileOpponentsNonlandPermanentUntilLeaves)
        for t in p.triggered_abilities
    )


def test_trapped_in_the_screen_etb_targets_opp_permanents():
    # End-to-end resolve sanity: the ETB targets an opponent's
    # permanent and exiles it. P0's own creature is excluded from
    # the legal-targets pool (opponents-only).
    from mtg_bot.cards.base import make_creature
    from mtg_bot.effects import ExileOpponentsNonlandPermanentUntilLeaves
    from mtg_bot.game import GameObject, GameState, Player, Zone

    parser = OracleParserCardSource()
    trapped = parser.get_printings()["Trapped in the Screen"]
    trapped_obj = GameObject(
        id=1, printing=trapped, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    yours = GameObject(
        id=2, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    theirs = GameObject(
        id=3, printing=bear_pr, owner_id=1, controller_id=1,
        zone=Zone.BATTLEFIELD,
    )
    state = GameState(
        players=[Player(id=0), Player(id=1)],
        battlefield=[trapped_obj, yours, theirs],
        resolving_source=trapped_obj,
    )
    eff = ExileOpponentsNonlandPermanentUntilLeaves()
    legal = eff.legal_targets(state, controller_id=0)
    assert ("permanent", 2) not in legal
    assert ("permanent", 3) in legal
