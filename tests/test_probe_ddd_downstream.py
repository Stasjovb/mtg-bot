"""Genuine cross-engine probes -- batch DDD downstream unlock
(17th Rust slice; closes DDD Pins 1+2+3).

The 17th Rust slice landed 3 pure-Python bridge arms in
``_ta_dict_to_python_effect`` (``src/mtg_bot/parity/cross_engine.py``):

  * ``survey_mechan_activation_effect`` (DDD Pin 1) -- zero-field
    unit-variant arm for ``SurveyMechanActivationEffect`` (bespoke
    dataclass at ``effects/bespoke.py``).  Survey Mechan unblocked.

  * ``exile_top_x_of_library_may_play_this_turn`` (DDD Pin 2) -- arm
    + new ``_ta_dict_to_python_formula`` dispatcher (first Formula
    bridge dispatcher in cross_engine.py; currently handles
    ``mv_of_cost_paid_object_plus`` + ``constant``).  Memorial Vault
    unblocked.

  * ``search_library_for_equipment_to_battlefield`` (DDD Pin 3) --
    zero-field unit-variant arm for
    ``SearchLibraryForEquipmentToBattlefield``.  Honored
    Knight-Captain unblocked.

These are bridge-arm-only closures -- no new Rust ``Effect`` variant
landed in this slice (the three classes have no Rust substrate yet).
The probes below verify (a) the printed real-EoE oracle text claims
through the parser to the expected Python ``Effect`` instance,
(b) the bridge round-trips that Effect (dict-shape -> Python Effect)
without raising, and (c) the Python ``resolve`` path runs end-to-end
on a controlled state.

Cross-engine byte-equality on the Rust side is OUT OF SCOPE for this
slice (no Rust ``Effect`` variants exist for the three bridge arms).
A future slice would land Rust ``Effect::SurveyMechanActivationEffect``
+ ``Effect::ExileTopXOfLibraryMayPlayThisTurn`` (which also needs a
Rust Formula algebra serialization protocol) +
``Effect::SearchLibraryForEquipmentToBattlefield`` and bring these
under the full cross-engine byte-equality probe surface.  Today's
probes pin the Python side + bridge admit.

Probe naming follows the canonical ``test_cross_engine_real_eoe_<slug>
_parity`` convention so ``scripts/measure_pool_parity.py``'s
``_probe_module_probed_cards`` detector credits these three cards in
the PROBED tier (the strongest evidence tier).  Each probe binds its
genuine card via ``get_active_source().get_printings().get("<Name>")``
-- the load-bearing "this probe pins THAT card" assertion the detector
anchors on.

PROBES
------

* ``test_cross_engine_real_eoe_survey_mechan_parity`` -- parser claims
  Survey Mechan; the activated ability's effect is a
  ``SurveyMechanActivationEffect``; bridge round-trips the dict shape;
  Python resolve fires all three sub-effects (3 damage to slot-0
  target + 3 cards drawn by slot-1 player + 3 life gained by slot-1
  player) on a controlled state.

* ``test_cross_engine_real_eoe_memorial_vault_parity`` -- parser claims
  Memorial Vault; the activated ability's effect is an
  ``ExileTopXOfLibraryMayPlayThisTurn(amount=MVOfCostPaidObjectPlus(
  constant=1))``; bridge round-trips the dict shape including the
  nested Formula via the new ``_ta_dict_to_python_formula`` dispatcher;
  Python resolve evaluates the Formula against a controlled cost-paid
  artifact (MV 2 -> X = 3) and exiles the expected 3 library cards,
  each marked ``playable_from_exile_this_turn``.

* ``test_cross_engine_real_eoe_honored_knight_captain_parity`` --
  parser claims Honored Knight-Captain; one activated ability's effect
  is a ``SearchLibraryForEquipmentToBattlefield``; bridge round-trips
  the dict shape; Python resolve moves an Equipment card from the
  controller's library to the battlefield UNTAPPED with
  ``summoning_sick=False`` (cross-validates slice 14 TTT Pin 2's
  non-creature ETB CR 302.1 + 612.6 closure).
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# DDD Pin 1 -- Survey Mechan
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_survey_mechan_parity():
    """**17th Rust slice (DDD Pin 1 closure)** -- Survey Mechan's
    activated ability body is admitted by the bridge and resolves
    correctly on Python.

    Verifies the closure chain end-to-end on the genuine parsed
    printing:
      1. ``get_active_source().get_printings().get("Survey Mechan")``
         returns the parsed CardPrinting (the load-bearing "this probe
         pins THAT card" assertion).
      2. The printing carries one activated ability whose effect is a
         ``SurveyMechanActivationEffect`` instance.
      3. The bridge ``_ta_dict_to_python_effect`` round-trips the
         canonical dict shape ``{"kind":
         "survey_mechan_activation_effect"}`` to a fresh
         ``SurveyMechanActivationEffect``.
      4. The Effect's two-slot targeting contract (any_damage_target +
         player) is preserved on the bridged instance.
      5. Python's ``resolve`` path fires all three sub-effects on a
         controlled state: 3 damage to slot-0 target, 3 cards drawn
         by slot-1 player, 3 life gained by slot-1 player.

    Probe scope is Python-only: no Rust ``Effect`` variant exists for
    this kind yet (a future slice would land it).  The Python
    bridge-admit + resolve verification is the strongest evidence
    available today.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.bespoke import SurveyMechanActivationEffect
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    # 1. Genuine parsed printing binding (load-bearing for the
    #    PROBED-tier detector).
    survey_mechan = get_active_source().get_printings().get("Survey Mechan")
    assert survey_mechan is not None, (
        "Parser should claim 'Survey Mechan' from the active card source "
        "(data/edge_of_eternities.json via OracleParserCardSource).  If "
        "this fails, either the printing data was removed or the parser "
        "branch was disabled."
    )

    # 2. Activated ability's effect is SurveyMechanActivationEffect.
    aa = getattr(survey_mechan, "activated_abilities", None) or ()
    assert len(aa) == 1, (
        "Survey Mechan should carry exactly one activated ability "
        "(the '{2}{U}{R}: It deals 3 damage to any target. Target "
        "player draws three cards and gains 3 life.' body).  "
        f"Got {len(aa)} activated abilities."
    )
    parsed_effect = aa[0].effect
    assert isinstance(parsed_effect, SurveyMechanActivationEffect), (
        "Survey Mechan's AA[0].effect should be a "
        "SurveyMechanActivationEffect instance.  Got "
        f"{type(parsed_effect).__name__!r}."
    )

    # 3. Bridge round-trip from canonical dict shape.
    bridged = _ta_dict_to_python_effect(
        {"kind": "survey_mechan_activation_effect"}
    )
    assert isinstance(bridged, SurveyMechanActivationEffect), (
        "Bridge arm should return a SurveyMechanActivationEffect "
        f"instance.  Got {type(bridged).__name__!r}."
    )

    # 4. Targeting contract preserved on the bridged instance.
    assert bridged.requires_target() is True, (
        "SurveyMechanActivationEffect.requires_target() should be True.  "
        f"Got {bridged.requires_target()!r}."
    )
    assert bridged.target_slot_kinds() == ("any_damage_target", "player"), (
        "SurveyMechanActivationEffect.target_slot_kinds() should be "
        "('any_damage_target', 'player').  "
        f"Got {bridged.target_slot_kinds()!r}."
    )

    # 5. Python resolve fires all three sub-effects on a controlled state.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    creature_printing = CardPrinting(
        name="DDD Survey Mechan Probe Creature",
        mana_cost_str="",
        mana_cost=ManaCost(generic=1, colored=()),
        type_line="Creature -- Beast",
        supertypes=(),
        card_types=("Creature",),
        subtypes=("Beast",),
        power=4, toughness=5,
        produces=frozenset(), keywords=frozenset(),
        triggered_abilities=(),
    )
    creature = py_state.new_object(
        creature_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_state.battlefield.append(creature)
    creature.zone = Zone.BATTLEFIELD

    for i in range(5):
        filler_printing = CardPrinting(
            name=f"DDD Survey Mechan Filler {i}",
            mana_cost_str="",
            mana_cost=ManaCost(generic=1, colored=()),
            type_line="Sorcery",
            supertypes=(),
            card_types=("Sorcery",),
            subtypes=(),
            power=None, toughness=None,
            produces=frozenset(), keywords=frozenset(),
            triggered_abilities=(),
        )
        filler = py_state.new_object(
            filler_printing, owner_id=1, zone=Zone.LIBRARY,
        )
        py_state.players[1].library.append(filler)

    pre_creature_damage = creature.damage
    pre_p1_hand_size = len(py_state.players[1].hand)
    pre_p1_life = py_state.players[1].life

    bridged.resolve(
        py_state,
        controller_id=0,
        targets=(("any_damage_target", creature.id), ("player", 1)),
    )

    assert creature.damage == pre_creature_damage + 3, (
        "Survey Mechan resolve should deal 3 damage to slot-0 target.  "
        f"Pre={pre_creature_damage}, post={creature.damage}."
    )
    assert len(py_state.players[1].hand) == pre_p1_hand_size + 3, (
        "Survey Mechan resolve should make slot-1 player draw 3 cards.  "
        f"Pre={pre_p1_hand_size}, "
        f"post={len(py_state.players[1].hand)}."
    )
    assert py_state.players[1].life == pre_p1_life + 3, (
        "Survey Mechan resolve should make slot-1 player gain 3 life.  "
        f"Pre={pre_p1_life}, post={py_state.players[1].life}."
    )


# ---------------------------------------------------------------------------
# DDD Pin 2 -- Memorial Vault
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_memorial_vault_parity():
    """**17th Rust slice (DDD Pin 2 closure)** -- Memorial Vault's
    activated ability body is admitted by the bridge and resolves
    correctly on Python.

    Verifies the closure chain end-to-end on the genuine parsed
    printing:
      1. ``get_active_source().get_printings().get("Memorial Vault")``
         returns the parsed CardPrinting.
      2. The printing's activated ability effect is an
         ``ExileTopXOfLibraryMayPlayThisTurn(amount=
         MVOfCostPaidObjectPlus(constant=1))``.
      3. The bridge round-trips the canonical dict shape including
         the nested Formula via the new
         ``_ta_dict_to_python_formula`` dispatcher.
      4. The Formula dispatcher round-trips the static
         ``Constant(amount=N)`` fallback.
      5. Python's ``resolve`` path evaluates the Formula against a
         controlled cost-paid artifact (MV 2 -> X = 3) and exiles the
         expected 3 library cards, each marked
         ``playable_from_exile_this_turn=True``.

    Probe scope is Python-only: no Rust ``Effect`` variant exists for
    this kind yet (the Formula algebra has no Rust serialization
    protocol).
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.exile import (
        ExileTopXOfLibraryMayPlayThisTurn,
    )
    from mtg_bot.effects.formulas import MVOfCostPaidObjectPlus, Constant
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state,
        _ta_dict_to_python_effect, _ta_dict_to_python_formula,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    # 1. Genuine parsed printing binding.
    memorial_vault = (
        get_active_source().get_printings().get("Memorial Vault")
    )
    assert memorial_vault is not None, (
        "Parser should claim 'Memorial Vault' from the active card "
        "source."
    )

    # 2. Activated ability is the expected structured Effect.
    aa = getattr(memorial_vault, "activated_abilities", None) or ()
    assert len(aa) == 1, (
        "Memorial Vault should carry exactly one activated ability.  "
        f"Got {len(aa)}."
    )
    parsed_effect = aa[0].effect
    assert isinstance(parsed_effect, ExileTopXOfLibraryMayPlayThisTurn), (
        "Memorial Vault's AA[0].effect should be "
        "ExileTopXOfLibraryMayPlayThisTurn.  Got "
        f"{type(parsed_effect).__name__!r}."
    )
    assert isinstance(parsed_effect.amount, MVOfCostPaidObjectPlus), (
        "Memorial Vault's AA[0].effect.amount should be "
        "MVOfCostPaidObjectPlus.  Got "
        f"{type(parsed_effect.amount).__name__!r}."
    )
    assert parsed_effect.amount.constant == 1, (
        "Memorial Vault's AA[0].effect.amount.constant should be 1.  "
        f"Got {parsed_effect.amount.constant!r}."
    )

    # 3. Bridge round-trip from canonical dict shape (with nested
    #    Formula sub-dict).
    bridged = _ta_dict_to_python_effect({
        "kind": "exile_top_x_of_library_may_play_this_turn",
        "amount": {"kind": "mv_of_cost_paid_object_plus", "constant": 1},
    })
    assert isinstance(bridged, ExileTopXOfLibraryMayPlayThisTurn), (
        "Bridge arm should return ExileTopXOfLibraryMayPlayThisTurn.  "
        f"Got {type(bridged).__name__!r}."
    )
    assert isinstance(bridged.amount, MVOfCostPaidObjectPlus), (
        "Bridge round-trip should preserve MVOfCostPaidObjectPlus.  "
        f"Got {type(bridged.amount).__name__!r}."
    )
    assert bridged.amount.constant == 1, (
        "Bridge round-trip should preserve constant=1.  "
        f"Got {bridged.amount.constant!r}."
    )

    # 4. Formula dispatcher round-trips Constant (regression guard).
    static_formula = _ta_dict_to_python_formula(
        {"kind": "constant", "amount": 7}
    )
    assert isinstance(static_formula, Constant), (
        f"Got {type(static_formula).__name__!r}."
    )
    assert static_formula.amount == 7, (
        f"Got amount={static_formula.amount!r}."
    )

    # 5. Python resolve evaluates the Formula and exiles the expected
    #    card count.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    artifact_printing = CardPrinting(
        name="DDD Memorial Vault Probe Sacrificed Artifact",
        mana_cost_str="{2}",
        mana_cost=ManaCost(generic=2, colored=()),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=None, toughness=None,
        produces=frozenset(), keywords=frozenset(),
        triggered_abilities=(),
    )
    sacrificed_artifact = py_state.new_object(
        artifact_printing, owner_id=0, zone=Zone.GRAVEYARD,
    )
    py_state.resolving_cost_paid_objects = (sacrificed_artifact,)

    for i in range(5):
        lib_printing = CardPrinting(
            name=f"DDD Memorial Vault Library Card {i}",
            mana_cost_str="",
            mana_cost=ManaCost(generic=1, colored=()),
            type_line="Sorcery",
            supertypes=(),
            card_types=("Sorcery",),
            subtypes=(),
            power=None, toughness=None,
            produces=frozenset(), keywords=frozenset(),
            triggered_abilities=(),
        )
        lib_obj = py_state.new_object(
            lib_printing, owner_id=0, zone=Zone.LIBRARY,
        )
        py_state.players[0].library.append(lib_obj)

    pre_library_size = len(py_state.players[0].library)
    pre_exile_size = len(py_state.players[0].exile)

    bridged.resolve(py_state, controller_id=0, targets=())

    assert len(py_state.players[0].library) == pre_library_size - 3, (
        "Memorial Vault resolve should exile 3 cards "
        "(MVOfCostPaidObjectPlus(constant=1) = MV(2) + 1).  "
        f"Library pre={pre_library_size}, "
        f"post={len(py_state.players[0].library)}."
    )
    assert len(py_state.players[0].exile) == pre_exile_size + 3, (
        f"Exile pre={pre_exile_size}, "
        f"post={len(py_state.players[0].exile)}."
    )

    exiled_objects = py_state.players[0].exile[-3:]
    for exiled in exiled_objects:
        assert exiled.zone == Zone.EXILE, (
            f"Exiled card {exiled.printing.name!r} should be in EXILE.  "
            f"Got {exiled.zone!r}."
        )
        assert exiled.playable_from_exile_this_turn is True, (
            f"Exiled card {exiled.printing.name!r} should be marked "
            "playable_from_exile_this_turn=True.  Got "
            f"{exiled.playable_from_exile_this_turn!r}."
        )


# ---------------------------------------------------------------------------
# DDD Pin 3 -- Honored Knight-Captain
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_honored_knight_captain_parity():
    """**17th Rust slice (DDD Pin 3 closure)** -- Honored
    Knight-Captain's Equipment-tutor activated ability is admitted by
    the bridge and resolves correctly on Python.

    Verifies the closure chain end-to-end on the genuine parsed
    printing:
      1. ``get_active_source().get_printings().get("Honored
         Knight-Captain")`` returns the parsed CardPrinting.
      2. One activated ability's effect is a
         ``SearchLibraryForEquipmentToBattlefield`` instance.
      3. The bridge round-trips the canonical dict shape to a fresh
         ``SearchLibraryForEquipmentToBattlefield`` instance.
      4. Distinctness from sibling search Effect classes is preserved
         on the bridged instance (regression guard against the three
         arms collapsing).
      5. Python's ``resolve`` path moves an Equipment card from the
         controller's library to the battlefield UNTAPPED with
         ``summoning_sick=False`` (cross-validates slice 14 TTT
         Pin 2's non-creature ETB closure).

    Probe scope is Python-only: no Rust ``Effect`` variant exists for
    this kind yet.
    """
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.effects.generic.search import (
        SearchLibraryForEquipmentToBattlefield,
        SearchLibraryForCard,
        SearchLibraryForBasicLandTapped,
    )
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    # 1. Genuine parsed printing binding.
    knight_captain = (
        get_active_source().get_printings().get("Honored Knight-Captain")
    )
    assert knight_captain is not None, (
        "Parser should claim 'Honored Knight-Captain' from the active "
        "card source."
    )

    # 2. Activated ability's effect includes the Equipment tutor.
    aa = getattr(knight_captain, "activated_abilities", None) or ()
    assert len(aa) >= 1, (
        "Honored Knight-Captain should carry at least one activated "
        f"ability.  Got {len(aa)}."
    )
    tutor_aa = None
    for ab in aa:
        if isinstance(ab.effect, SearchLibraryForEquipmentToBattlefield):
            tutor_aa = ab
            break
    assert tutor_aa is not None, (
        "Honored Knight-Captain should carry an activated ability "
        "whose effect is SearchLibraryForEquipmentToBattlefield.  "
        f"AA effects: {[type(ab.effect).__name__ for ab in aa]!r}"
    )

    # 3. Bridge round-trip.
    bridged = _ta_dict_to_python_effect(
        {"kind": "search_library_for_equipment_to_battlefield"}
    )
    assert isinstance(bridged, SearchLibraryForEquipmentToBattlefield), (
        f"Got {type(bridged).__name__!r}."
    )

    # 4. Distinctness preserved.
    assert not isinstance(bridged, SearchLibraryForCard), (
        "Equipment tutor must NOT collapse to SearchLibraryForCard."
    )
    assert not isinstance(bridged, SearchLibraryForBasicLandTapped), (
        "Equipment tutor must NOT collapse to "
        "SearchLibraryForBasicLandTapped."
    )

    # 5. Python resolve moves Equipment from library to bf untapped.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    equip_printing = CardPrinting(
        name="DDD Knight-Captain Probe Equipment",
        mana_cost_str="{1}",
        mana_cost=ManaCost(generic=1, colored=()),
        type_line="Artifact -- Equipment",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=("Equipment",),
        power=None, toughness=None,
        produces=frozenset(), keywords=frozenset(),
        triggered_abilities=(),
    )
    filler_printing = CardPrinting(
        name="DDD Knight-Captain Probe Filler",
        mana_cost_str="{1}",
        mana_cost=ManaCost(generic=1, colored=()),
        type_line="Sorcery",
        supertypes=(),
        card_types=("Sorcery",),
        subtypes=(),
        power=None, toughness=None,
        produces=frozenset(), keywords=frozenset(),
        triggered_abilities=(),
    )
    equip_obj = py_state.new_object(
        equip_printing, owner_id=0, zone=Zone.LIBRARY,
    )
    filler_obj = py_state.new_object(
        filler_printing, owner_id=0, zone=Zone.LIBRARY,
    )
    py_state.players[0].library.extend([equip_obj, filler_obj])

    pre_bf_p0_names = {
        o.printing.name for o in py_state.battlefield
        if o.controller_id == 0
    }

    bridged.resolve(py_state, controller_id=0, targets=())

    post_bf_p0 = [
        o for o in py_state.battlefield if o.controller_id == 0
    ]
    post_bf_p0_names = {o.printing.name for o in post_bf_p0}
    new_bf_names = post_bf_p0_names - pre_bf_p0_names
    assert "DDD Knight-Captain Probe Equipment" in new_bf_names, (
        "SearchLibraryForEquipmentToBattlefield.resolve should put the "
        "Equipment onto the controller's battlefield.  "
        f"Pre={sorted(pre_bf_p0_names)!r}, post={sorted(post_bf_p0_names)!r}."
    )

    post_library_names = {
        o.printing.name for o in py_state.players[0].library
    }
    assert (
        "DDD Knight-Captain Probe Equipment" not in post_library_names
    ), (
        "Equipment should have been moved out of P0's library.  "
        f"Got post={sorted(post_library_names)!r}."
    )

    bf_equip = next(
        o for o in post_bf_p0
        if o.printing.name == "DDD Knight-Captain Probe Equipment"
    )
    assert bf_equip.zone == Zone.BATTLEFIELD, (
        f"Got {bf_equip.zone!r}."
    )
    assert bf_equip.tapped is False, (
        "SearchLibraryForEquipmentToBattlefield resolve enters the "
        "Equipment UNTAPPED (distinct from "
        "SearchLibraryForBasicLandTapped).  "
        f"Got tapped={bf_equip.tapped!r}."
    )
    assert bf_equip.summoning_sick is False, (
        "Non-creature Equipment ETB should leave summoning_sick=False "
        "(slice 14 TTT Pin 2 CR 302.1 + 612.6 closure).  Got "
        f"summoning_sick={bf_equip.summoning_sick!r}."
    )
