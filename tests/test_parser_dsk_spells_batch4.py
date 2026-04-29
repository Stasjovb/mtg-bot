"""Tests for the Duskmourn spells / enchantments / equipment / artifacts
batch-4 parser additions.

Each commit in this batch lands one card via a small additive change:
a literal-line entry on an existing builder, a name-keyed dispatch
factory on an existing builder, or a small flag widening on an existing
engine class. No new bespoke engine classes are introduced beyond the
manifest-dread-then-attach combinator described below.

New ``make_enchantment`` kwarg:

* ``ward`` (e.g. ``"{2}"``) — wires the printed Ward keyword on a non-
  Aura Enchantment ITSELF. Mirrors the same-named kwarg on
  ``make_creature`` and routes through the same
  ``CardPrinting.ward_cost`` / ``ward_cost_str`` fields the engine's
  ward-check helpers already read. Auras keep their own
  ``attached_grants_ward`` kwarg for the "Enchanted permanent has
  ward" rider — the two kwargs stay distinct because the Aura form
  targets the enchanted permanent, not the Aura itself.

New literal ETB line on the equipment_builder:

* ``"When this Equipment enters, manifest dread, then attach this
  Equipment to that creature."`` (Conductive Machete / Killer's Mask
  / Cursed Windbreaker DSK Equipment family) — wires the new
  ``ManifestDreadThenAttachSelf`` engine class which manifests the
  top-of-library card face-down (CR 701.55 / 701.34) and immediately
  attaches the Equipment to the just-manifested 2/2. Distinct from
  ``CreateTokenAndAttachSelf`` because the manifested permanent is a
  face-down card from library, not a freshly minted token. Parallels
  ``ManifestDreadThenPutPlusOneCountersOnIt`` (Slimy Aquarium /
  Weight Room door triggers) — same back-reference shape on "that
  creature" pointing at the just-manifested face-down.

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

* **Conductive Machete** ``{4}`` Artifact — Equipment — ETB-manifest-
  dread-then-attach + ``Equipped creature gets +2/+1`` + ``Equip
  {4}``. Claimed by extending the equipment_builder's literal-ETB-
  line table with the printed manifest-dread line, dispatched to
  the new ``ManifestDreadThenAttachSelf`` engine class.

* **Killer's Mask** ``{2}{B}`` Artifact — Equipment — same ETB shape
  as Conductive Machete + ``Equipped creature has menace`` + ``Equip
  {2}``. Reuses the same literal ETB line dispatch.

* **Cursed Windbreaker** ``{2}{U}`` Artifact — Equipment — same ETB
  shape as Conductive Machete + ``Equipped creature has flying`` +
  ``Equip {3}``. Reuses the same literal ETB line dispatch.
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


# ---------- ManifestDreadThenAttachSelf engine class ----------

def test_manifest_dread_then_attach_self_engine_class_exists():
    # The new engine class lives in ``mtg_bot.effects.generic`` next
    # to ``ManifestDread`` and ``ManifestDreadThenPutPlusOneCountersOnIt``.
    # Imports cleanly and is exposed via ``mtg_bot.effects``.
    from mtg_bot.effects import ManifestDreadThenAttachSelf

    eff = ManifestDreadThenAttachSelf()
    # No printed targets — the manifested face-down is the attach
    # target, not a printed-target choice.
    assert eff.requires_target() is False


def test_manifest_dread_then_attach_self_describe():
    # Belt-and-suspenders that the describe helper reflects the
    # combined behavior — manifest dread, then attach to that
    # creature.
    from mtg_bot.effects import ManifestDreadThenAttachSelf

    eff = ManifestDreadThenAttachSelf()
    desc = eff.describe()
    assert "manifest dread" in desc
    assert "attach" in desc


def test_manifest_dread_then_attach_self_attaches_to_manifested():
    # End-to-end resolve sanity: manifests a face-down card from the
    # top of library and attaches the source Equipment to it. The
    # face-down 2/2 enters first, then the Equipment's
    # ``attached_to`` is set to that face-down's id.
    from mtg_bot.cards.base import make_creature, make_equipment
    from mtg_bot.effects import ManifestDreadThenAttachSelf
    from mtg_bot.game import GameObject, GameState, Player, Zone

    eq_pr = make_equipment(
        "Test Equipment", "{2}",
        power_bonus=1, toughness_bonus=0,
        equip_cost="{1}",
    )
    eq_obj = GameObject(
        id=1, printing=eq_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    bear_pr = make_creature("Bear", "{1}{G}", power=2, toughness=2)
    # Two cards in library so manifest dread has the full 2-card
    # examination shape.
    card_a = GameObject(
        id=10, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.LIBRARY,
    )
    card_b = GameObject(
        id=11, printing=bear_pr, owner_id=0, controller_id=0,
        zone=Zone.LIBRARY,
    )
    p0 = Player(id=0, library=[card_a, card_b])
    p1 = Player(id=1)
    state = GameState(
        players=[p0, p1],
        battlefield=[eq_obj],
        resolving_source=eq_obj,
    )
    ManifestDreadThenAttachSelf().resolve(state, controller_id=0, targets=())
    # A face-down 2/2 is now on the battlefield, and the Equipment
    # is attached to it.
    face_downs = [o for o in state.battlefield if o.face_down]
    assert len(face_downs) == 1
    assert eq_obj.attached_to == face_downs[0].id


def test_manifest_dread_then_attach_self_no_op_on_empty_library():
    # Defensive sanity: with an empty library, ``ManifestDread`` doesn't
    # manifest anything; the attach step then no-ops (Equipment stays
    # unattached) rather than raising. Mirrors the same fallback
    # ``ManifestDreadThenPutPlusOneCountersOnIt`` uses.
    from mtg_bot.cards.base import make_equipment
    from mtg_bot.effects import ManifestDreadThenAttachSelf
    from mtg_bot.game import GameObject, GameState, Player, Zone

    eq_pr = make_equipment(
        "Test Equipment", "{2}",
        power_bonus=1, toughness_bonus=0,
        equip_cost="{1}",
    )
    eq_obj = GameObject(
        id=1, printing=eq_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    p0 = Player(id=0, library=[])
    p1 = Player(id=1)
    state = GameState(
        players=[p0, p1],
        battlefield=[eq_obj],
        resolving_source=eq_obj,
    )
    ManifestDreadThenAttachSelf().resolve(state, controller_id=0, targets=())
    # Nothing manifested → Equipment stays unattached.
    assert eq_obj.attached_to is None


def test_manifest_dread_then_attach_self_no_op_on_non_equipment_source():
    # Defensive sanity: if the source isn't an Equipment (e.g. the
    # engine class is wired by mistake on a non-Equipment artifact),
    # the attach step no-ops rather than half-resolving. Same
    # ``"Equipment" in subtypes`` guard ``AttachToTargetCreatureYouControl``
    # uses.
    from mtg_bot.cards.base import make_artifact
    from mtg_bot.effects import ManifestDreadThenAttachSelf
    from mtg_bot.game import GameObject, GameState, Player, Zone

    art_pr = make_artifact("Plain Artifact", "{2}")
    art_obj = GameObject(
        id=1, printing=art_pr, owner_id=0, controller_id=0,
        zone=Zone.BATTLEFIELD,
    )
    p0 = Player(id=0)
    p1 = Player(id=1)
    state = GameState(
        players=[p0, p1],
        battlefield=[art_obj],
        resolving_source=art_obj,
    )
    # Resolve must complete without raising.
    ManifestDreadThenAttachSelf().resolve(state, controller_id=0, targets=())
    # No manifest happened (the source-Equipment guard short-circuited
    # before reaching the manifest step), so the library count is
    # unchanged and the artifact is unattached.
    assert art_obj.attached_to is None


def test_manifest_dread_then_attach_self_no_op_on_missing_source():
    # Defensive sanity: with no ``resolving_source`` on the state
    # (defensive caller error), the effect no-ops rather than crashes.
    from mtg_bot.effects import ManifestDreadThenAttachSelf
    from mtg_bot.game import GameState, Player

    state = GameState(
        players=[Player(id=0), Player(id=1)],
    )
    # Resolve must complete without raising.
    ManifestDreadThenAttachSelf().resolve(state, controller_id=0, targets=())


# ---------- Equipment ETB line: literal manifest-dread-then-attach ----------

def test_conductive_machete_claimed_by_parser():
    # Conductive Machete ``{4}`` Equipment — claimed via the new
    # literal ETB line in ``equipment_builder``.
    assert "Conductive Machete" in _claimed_names()


def test_conductive_machete_carries_etb_and_pump_and_equip_cost():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # all three lines of the printed text:
    # - the ``ManifestDreadThenAttachSelf`` ETB trigger;
    # - +2/+1 in the ``equipment_bonuses`` triple;
    # - the ``Equip {4}`` synthesized activated ability.
    from mtg_bot.effects import ManifestDreadThenAttachSelf

    parser = OracleParserCardSource()
    p = parser.get_printings()["Conductive Machete"]
    assert any(
        isinstance(t.effect, ManifestDreadThenAttachSelf)
        for t in p.triggered_abilities
    )
    assert p.equipment_bonuses == (2, 1, frozenset())
    equip_costs = [
        a.cost.mana_str for a in p.activated_abilities
        if a.cost.mana_str
    ]
    assert "{4}" in equip_costs


def test_killers_mask_claimed_by_parser():
    # Killer's Mask ``{2}{B}`` Equipment — same literal ETB line as
    # Conductive Machete; the granted-keyword line is "menace".
    assert "Killer's Mask" in _claimed_names()


def test_killers_mask_carries_etb_and_menace_and_equip_cost():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries:
    # - the ``ManifestDreadThenAttachSelf`` ETB trigger;
    # - menace in the granted-keywords slot (the third member of
    #   ``equipment_bonuses``);
    # - the ``Equip {2}`` synthesized activated ability.
    from mtg_bot.effects import ManifestDreadThenAttachSelf

    parser = OracleParserCardSource()
    p = parser.get_printings()["Killer's Mask"]
    assert any(
        isinstance(t.effect, ManifestDreadThenAttachSelf)
        for t in p.triggered_abilities
    )
    assert p.equipment_bonuses == (0, 0, frozenset({"menace"}))
    equip_costs = [
        a.cost.mana_str for a in p.activated_abilities
        if a.cost.mana_str
    ]
    assert "{2}" in equip_costs


def test_cursed_windbreaker_claimed_by_parser():
    # Cursed Windbreaker ``{2}{U}`` Equipment — same literal ETB line
    # as Conductive Machete; the granted-keyword line is "flying".
    assert "Cursed Windbreaker" in _claimed_names()


def test_cursed_windbreaker_carries_etb_and_flying_and_equip_cost():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries:
    # - the ``ManifestDreadThenAttachSelf`` ETB trigger;
    # - flying in the granted-keywords slot;
    # - the ``Equip {3}`` synthesized activated ability.
    from mtg_bot.effects import ManifestDreadThenAttachSelf

    parser = OracleParserCardSource()
    p = parser.get_printings()["Cursed Windbreaker"]
    assert any(
        isinstance(t.effect, ManifestDreadThenAttachSelf)
        for t in p.triggered_abilities
    )
    assert p.equipment_bonuses == (0, 0, frozenset({"flying"}))
    equip_costs = [
        a.cost.mana_str for a in p.activated_abilities
        if a.cost.mana_str
    ]
    assert "{3}" in equip_costs
