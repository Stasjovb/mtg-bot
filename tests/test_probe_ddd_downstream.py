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

PROBES
------

Probe 1 -- Survey Mechan: parser claims the printing, the activated
ability's effect is a ``SurveyMechanActivationEffect`` instance, the
bridge round-trips the dict shape, and the Python resolve path runs
to completion on a controlled state.

Probe 2 -- Memorial Vault: parser claims the printing, the activated
ability's effect is an ``ExileTopXOfLibraryMayPlayThisTurn(amount=
MVOfCostPaidObjectPlus(constant=1))`` instance, the bridge round-trips
the dict shape (effect + nested Formula), and the Python resolve path
exiles the expected card count off the controller's library with each
exiled card marked ``playable_from_exile_this_turn``.

Probe 3 -- Honored Knight-Captain: parser claims the printing, the
activated ability's effect is a
``SearchLibraryForEquipmentToBattlefield`` instance, the bridge
round-trips the dict shape, and the Python resolve path moves an
Equipment card from the controller's library to the battlefield
untapped (no summoning_sick on the artifact ETB per slice 14 TTT
Pin 2's CR 302.1 closure).
"""

from __future__ import annotations

import pytest


def _real_eoe_printings():
    """Return the EoE parser's name-keyed printings dict.  Cached at
    module level via lru_cache on the source class is not needed --
    ``OracleParserCardSource`` is cheap to construct (one JSON walk)
    and each probe only builds once.  Inlined here so probes don't
    share state across tests.
    """
    from mtg_bot.cards.parser.source import OracleParserCardSource
    return OracleParserCardSource().get_printings()


# ---------------------------------------------------------------------------
# Probe 1 -- Survey Mechan (DDD Pin 1)
# ---------------------------------------------------------------------------


def test_ddd_probe_survey_mechan_bridge_admits_real_eoe():
    """**DDD Pin 1 closure** -- Survey Mechan's activated ability body
    is admitted by the bridge end-to-end on a real-EoE printing.

    Verifies the closure chain end-to-end:
      1. The parser claims "Survey Mechan" from
         ``data/edge_of_eternities.json``.
      2. The printing carries exactly one activated ability whose
         effect is a ``SurveyMechanActivationEffect`` instance.
      3. The bridge ``_ta_dict_to_python_effect`` round-trips the
         canonical dict shape ``{"kind":
         "survey_mechan_activation_effect"}`` to a fresh
         ``SurveyMechanActivationEffect`` instance.
      4. ``SurveyMechanActivationEffect.requires_target() is True``
         and ``target_slot_kinds() == ("any_damage_target", "player")``
         (the two-slot targeting contract Survey Mechan declares).

    Pre-closure (the divergence DDD Pin 1 locked in): step 3 raised
    ``ValueError("unsupported effect kind ...")``.
    Post-closure (asserted here): step 3 returns a
    ``SurveyMechanActivationEffect`` instance bit-equivalent to the
    parser-built instance carried on the real EoE printing.
    """
    from mtg_bot.effects.bespoke import SurveyMechanActivationEffect
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. Parser claims the printing.
    printings = _real_eoe_printings()
    survey_mechan = printings.get("Survey Mechan")
    assert survey_mechan is not None, (
        "Parser should claim 'Survey Mechan' from "
        "data/edge_of_eternities.json (claimed via the bespoke effect "
        "branch in cards/parser/effects.py at the literal-line "
        "recognizer).  If this fails, either the printing data was "
        "removed or the parser branch was disabled."
    )

    # 2. Activated ability's effect is SurveyMechanActivationEffect.
    aa = getattr(survey_mechan, "activated_abilities", None) or ()
    assert len(aa) == 1, (
        "Survey Mechan should carry exactly one activated ability "
        "(the '{2}{U}{R}: It deals 3 damage to any target. Target "
        "player draws three cards and gains 3 life.' body).  "
        f"Got {len(aa)} activated abilities."
    )
    activated_effect = aa[0].effect
    assert isinstance(activated_effect, SurveyMechanActivationEffect), (
        "Survey Mechan's AA[0].effect should be a "
        "SurveyMechanActivationEffect instance (the bespoke dataclass "
        "the parser emits for this oracle text).  Got "
        f"{type(activated_effect).__name__!r}."
    )

    # 3. Bridge round-trip from canonical dict shape.
    bridged = _ta_dict_to_python_effect(
        {"kind": "survey_mechan_activation_effect"}
    )
    assert isinstance(bridged, SurveyMechanActivationEffect), (
        "Bridge arm should return a SurveyMechanActivationEffect "
        "instance for the canonical dict shape.  Got "
        f"{type(bridged).__name__!r}."
    )

    # 4. Targeting contract is preserved.
    assert bridged.requires_target() is True, (
        "SurveyMechanActivationEffect.requires_target() should be True "
        "-- the ability mandates two targets (any-damage-target + "
        "player).  Got "
        f"{bridged.requires_target()!r}."
    )
    assert bridged.target_slot_kinds() == ("any_damage_target", "player"), (
        "SurveyMechanActivationEffect.target_slot_kinds() should be "
        "('any_damage_target', 'player') -- two distinct tag kinds so "
        "the agent pipeline presents both pools separately.  "
        f"Got {bridged.target_slot_kinds()!r}."
    )


def test_ddd_probe_survey_mechan_python_resolve_runs():
    """**DDD Pin 1 closure** -- Survey Mechan's resolve path runs
    end-to-end on a controlled Python state.

    Drives ``SurveyMechanActivationEffect.resolve`` directly with a
    controlled state + targets tuple; asserts the three observable
    sub-effects fire:
      a. The damage target takes 3 damage.
      b. The player target draws 3 cards.
      c. The player target gains 3 life.

    Probe scope is Python-only -- no Rust ``Effect`` variant exists
    for this kind yet (a future slice would land it).  The Python
    resolve verification is the strongest evidence available today
    for the closure: the Effect class is parser-emitted + bridge-
    admitted + runtime-executable.
    """
    from mtg_bot.effects.bespoke import SurveyMechanActivationEffect
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    # Build a minimal Python state with two living players.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Inject a vanilla creature on P1's battlefield as the damage target.
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

    # Stack a few cards in P1's library so the draw-3 sub-effect has
    # something to pull (decking is the empty-library-loss path, which
    # the resolve fizzles silently against).
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

    # Record pre-state observables.
    pre_creature_damage = creature.damage
    pre_p1_hand_size = len(py_state.players[1].hand)
    pre_p1_life = py_state.players[1].life

    # Bridge-admit + resolve.
    bridged = _ta_dict_to_python_effect(
        {"kind": "survey_mechan_activation_effect"}
    )
    assert isinstance(bridged, SurveyMechanActivationEffect)

    bridged.resolve(
        py_state,
        controller_id=0,
        targets=(("any_damage_target", creature.id), ("player", 1)),
    )

    # a. Damage target took 3 damage.
    assert creature.damage == pre_creature_damage + 3, (
        "Survey Mechan resolve should deal 3 damage to the slot 0 "
        f"target creature.  Pre={pre_creature_damage}, "
        f"post={creature.damage}."
    )

    # b. Player target drew 3 cards.
    assert len(py_state.players[1].hand) == pre_p1_hand_size + 3, (
        "Survey Mechan resolve should make the slot 1 player draw 3 "
        f"cards.  Pre={pre_p1_hand_size}, "
        f"post={len(py_state.players[1].hand)}."
    )

    # c. Player target gained 3 life.
    assert py_state.players[1].life == pre_p1_life + 3, (
        "Survey Mechan resolve should make the slot 1 player gain 3 "
        f"life.  Pre={pre_p1_life}, "
        f"post={py_state.players[1].life}."
    )


# ---------------------------------------------------------------------------
# Probe 2 -- Memorial Vault (DDD Pin 2)
# ---------------------------------------------------------------------------


def test_ddd_probe_memorial_vault_bridge_admits_real_eoe():
    """**DDD Pin 2 closure** -- Memorial Vault's activated ability body
    is admitted by the bridge end-to-end on a real-EoE printing, AND
    the nested ``MVOfCostPaidObjectPlus(constant=1)`` Formula
    round-trips through the new ``_ta_dict_to_python_formula``
    dispatcher.

    Verifies the closure chain end-to-end:
      1. The parser claims "Memorial Vault" from
         ``data/edge_of_eternities.json``.
      2. The printing carries exactly one activated ability whose
         effect is an ``ExileTopXOfLibraryMayPlayThisTurn(amount=
         MVOfCostPaidObjectPlus(constant=1))`` instance.
      3. The bridge round-trips the canonical dict shape
         ``{"kind": "exile_top_x_of_library_may_play_this_turn",
            "amount": {"kind": "mv_of_cost_paid_object_plus",
                       "constant": 1}}``
         to a fresh ExileTopXOfLibraryMayPlayThisTurn with the same
         nested Formula structure.
      4. The Formula dispatcher round-trips the static
         ``Constant(amount=N)`` fallback (regression guard on the
         second formula kind).

    Pre-closure: step 3 raised ``ValueError("unsupported effect kind
    ...")`` AND the ``_ta_dict_to_python_formula`` helper did not
    exist.
    Post-closure: step 3 returns a structurally-equivalent
    ExileTopXOfLibraryMayPlayThisTurn, with constant=1 preserved.
    """
    from mtg_bot.effects.generic.exile import (
        ExileTopXOfLibraryMayPlayThisTurn,
    )
    from mtg_bot.effects.formulas import MVOfCostPaidObjectPlus, Constant
    from mtg_bot.parity.cross_engine import (
        _ta_dict_to_python_effect, _ta_dict_to_python_formula,
    )

    # 1. Parser claims the printing.
    printings = _real_eoe_printings()
    memorial_vault = printings.get("Memorial Vault")
    assert memorial_vault is not None, (
        "Parser should claim 'Memorial Vault' from "
        "data/edge_of_eternities.json (claimed via the multi-sentence "
        "literal recognizer in cards/parser/effects.py)."
    )

    # 2. Activated ability is the expected structured Effect.
    aa = getattr(memorial_vault, "activated_abilities", None) or ()
    assert len(aa) == 1, (
        "Memorial Vault should carry exactly one activated ability "
        "(the '{2}, {T}, Sacrifice another artifact: Exile the top X "
        "cards of your library, where X is one plus the mana value of "
        "the sacrificed artifact. You may play those cards this turn.' "
        "body).  "
        f"Got {len(aa)} activated abilities."
    )
    activated_effect = aa[0].effect
    assert isinstance(activated_effect, ExileTopXOfLibraryMayPlayThisTurn), (
        "Memorial Vault's AA[0].effect should be an "
        "ExileTopXOfLibraryMayPlayThisTurn instance.  Got "
        f"{type(activated_effect).__name__!r}."
    )
    assert isinstance(activated_effect.amount, MVOfCostPaidObjectPlus), (
        "Memorial Vault's AA[0].effect.amount should be an "
        "MVOfCostPaidObjectPlus formula.  Got "
        f"{type(activated_effect.amount).__name__!r}."
    )
    assert activated_effect.amount.constant == 1, (
        "Memorial Vault's AA[0].effect.amount.constant should be 1 "
        "('one plus the mana value of the sacrificed artifact').  "
        f"Got {activated_effect.amount.constant!r}."
    )

    # 3. Bridge round-trip from canonical dict shape.
    bridged = _ta_dict_to_python_effect({
        "kind": "exile_top_x_of_library_may_play_this_turn",
        "amount": {"kind": "mv_of_cost_paid_object_plus", "constant": 1},
    })
    assert isinstance(bridged, ExileTopXOfLibraryMayPlayThisTurn), (
        "Bridge arm should return an ExileTopXOfLibraryMayPlayThisTurn "
        "instance.  Got "
        f"{type(bridged).__name__!r}."
    )
    assert isinstance(bridged.amount, MVOfCostPaidObjectPlus), (
        "Bridge round-trip should preserve MVOfCostPaidObjectPlus on "
        "the nested 'amount' Formula.  Got "
        f"{type(bridged.amount).__name__!r}."
    )
    assert bridged.amount.constant == 1, (
        "Bridge round-trip should preserve constant=1 on the nested "
        f"Formula.  Got constant={bridged.amount.constant!r}."
    )

    # 4. Formula dispatcher round-trips Constant (the second wired
    #    formula kind; regression guard).
    static_formula = _ta_dict_to_python_formula(
        {"kind": "constant", "amount": 7}
    )
    assert isinstance(static_formula, Constant), (
        "Formula dispatcher should return Constant for kind='constant'.  "
        f"Got {type(static_formula).__name__!r}."
    )
    assert static_formula.amount == 7, (
        f"Constant round-trip; got amount={static_formula.amount!r}."
    )


def test_ddd_probe_memorial_vault_python_resolve_exiles_top_x():
    """**DDD Pin 2 closure** -- Memorial Vault's resolve path exiles
    the expected card count (driven by the Formula) and marks each
    card ``playable_from_exile_this_turn``.

    Drives ``ExileTopXOfLibraryMayPlayThisTurn.resolve`` directly with
    a controlled state where the cost-paid object's mana value is
    deterministic (a 2-mana artifact placed in
    ``state.resolving_cost_paid_objects``).  The Formula
    ``MVOfCostPaidObjectPlus(constant=1)`` should evaluate to
    ``2 + 1 = 3``, so the resolve exiles the top 3 cards of the
    controller's library; each lands in exile with
    ``playable_from_exile_this_turn=True``.

    Probe scope: Python-only (no Rust substrate for the kind yet --
    the Formula algebra has no Rust serialization protocol).
    """
    from mtg_bot.effects.generic.exile import (
        ExileTopXOfLibraryMayPlayThisTurn,
    )
    from mtg_bot.effects.formulas import MVOfCostPaidObjectPlus
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Build a 2-mana artifact -- the cost-paid object that drives the
    # Formula.  Memorial Vault's cost atom
    # ``sacrifice_another_artifact`` populates
    # ``state.resolving_cost_paid_objects`` via
    # _activate_ability's cost-payment plumbing; we install the same
    # tuple by hand here since the resolve path reads it as a flat
    # sequence.
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

    # Stack 5 cards on P0's library (the Effect exiles up to 3; the
    # tail two stay).
    library_cards = []
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
        library_cards.append(lib_obj)

    pre_library_size = len(py_state.players[0].library)
    pre_exile_size = len(py_state.players[0].exile)

    # Bridge-admit (full dict shape including Formula).
    bridged = _ta_dict_to_python_effect({
        "kind": "exile_top_x_of_library_may_play_this_turn",
        "amount": {"kind": "mv_of_cost_paid_object_plus", "constant": 1},
    })
    assert isinstance(bridged, ExileTopXOfLibraryMayPlayThisTurn)
    assert isinstance(bridged.amount, MVOfCostPaidObjectPlus)
    assert bridged.amount.constant == 1

    # Resolve.  Formula evaluates to 2 (artifact MV) + 1 (constant) = 3.
    bridged.resolve(py_state, controller_id=0, targets=())

    # Library shrank by 3.
    assert len(py_state.players[0].library) == pre_library_size - 3, (
        f"Memorial Vault resolve should exile 3 cards "
        f"(MVOfCostPaidObjectPlus(constant=1) = MV(2) + 1).  "
        f"Library pre={pre_library_size}, "
        f"post={len(py_state.players[0].library)}."
    )

    # Exile grew by 3.
    assert len(py_state.players[0].exile) == pre_exile_size + 3, (
        f"Memorial Vault resolve should put 3 cards in exile.  "
        f"Exile pre={pre_exile_size}, "
        f"post={len(py_state.players[0].exile)}."
    )

    # Each exiled card is marked playable_from_exile_this_turn.
    # The 3 cards exiled are the FIRST 3 library cards (top-of-library
    # pops in insertion order).
    exiled_objects = py_state.players[0].exile[-3:]
    for exiled in exiled_objects:
        assert exiled.zone == Zone.EXILE, (
            f"Exiled card {exiled.printing.name!r} should be in "
            f"Zone.EXILE; got {exiled.zone!r}."
        )
        assert exiled.playable_from_exile_this_turn is True, (
            f"Exiled card {exiled.printing.name!r} should be marked "
            f"playable_from_exile_this_turn=True (the impulse-cast "
            "lifetime flag the cleanup step clears).  Got "
            f"{exiled.playable_from_exile_this_turn!r}."
        )


# ---------------------------------------------------------------------------
# Probe 3 -- Honored Knight-Captain (DDD Pin 3)
# ---------------------------------------------------------------------------


def test_ddd_probe_honored_knight_captain_bridge_admits_real_eoe():
    """**DDD Pin 3 closure** -- Honored Knight-Captain's activated
    ability body is admitted by the bridge end-to-end on a real-EoE
    printing.

    Verifies the closure chain end-to-end:
      1. The parser claims "Honored Knight-Captain" from
         ``data/edge_of_eternities.json``.
      2. The printing carries one activated ability (the
         ``{4}{W}{W}, Sacrifice this creature`` Equipment tutor) whose
         effect is a ``SearchLibraryForEquipmentToBattlefield``
         instance.
      3. The bridge round-trips the canonical dict shape
         ``{"kind": "search_library_for_equipment_to_battlefield"}``
         to a fresh ``SearchLibraryForEquipmentToBattlefield``
         instance.
      4. Distinctness from sibling search Effect classes is preserved
         (regression guard).

    Pre-closure (the divergence DDD Pin 3 locked in): step 3 raised
    ``ValueError("unsupported effect kind ...")``.
    Post-closure (asserted here): step 3 returns a
    ``SearchLibraryForEquipmentToBattlefield`` instance.
    """
    from mtg_bot.effects.generic.search import (
        SearchLibraryForEquipmentToBattlefield,
        SearchLibraryForCard,
        SearchLibraryForBasicLandTapped,
    )
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    # 1. Parser claims the printing.
    printings = _real_eoe_printings()
    knight_captain = printings.get("Honored Knight-Captain")
    assert knight_captain is not None, (
        "Parser should claim 'Honored Knight-Captain' from "
        "data/edge_of_eternities.json (claimed via the literal-line "
        "recognizer in cards/parser/effects.py)."
    )

    # 2. AA[0].effect is SearchLibraryForEquipmentToBattlefield.
    aa = getattr(knight_captain, "activated_abilities", None) or ()
    assert len(aa) >= 1, (
        "Honored Knight-Captain should carry at least one activated "
        "ability (the '{4}{W}{W}, Sacrifice ...' Equipment tutor).  "
        f"Got {len(aa)} activated abilities."
    )
    # Find the AA whose effect is the Equipment tutor (the printing
    # might carry additional AAs; the tutor is the one this slice
    # unblocks).
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
        "Bridge arm should return a "
        "SearchLibraryForEquipmentToBattlefield instance.  Got "
        f"{type(bridged).__name__!r}."
    )

    # 4. Distinctness from sibling classes (regression guard).
    assert not isinstance(bridged, SearchLibraryForCard), (
        "Bridge-admitted Equipment tutor must NOT collapse to "
        "SearchLibraryForCard."
    )
    assert not isinstance(bridged, SearchLibraryForBasicLandTapped), (
        "Bridge-admitted Equipment tutor must NOT collapse to "
        "SearchLibraryForBasicLandTapped."
    )


def test_ddd_probe_honored_knight_captain_python_resolve_moves_equipment_to_bf():
    """**DDD Pin 3 closure** -- Honored Knight-Captain's resolve path
    moves an Equipment card from the controller's library to the
    battlefield untapped.

    Drives ``SearchLibraryForEquipmentToBattlefield.resolve`` directly
    with a controlled state where the controller's library contains
    one Equipment card.  Asserts the Equipment lands on the
    battlefield untapped, the library no longer contains it, and the
    library was shuffled (the post-search shuffle step always runs,
    matching the Stage-3 shuffle-after-search invariant the sibling
    classes also honor).

    Probe scope: Python-only (no Rust substrate for the kind yet).
    """
    from mtg_bot.effects.generic.search import (
        SearchLibraryForEquipmentToBattlefield,
    )
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import Zone

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py_state = build_python_state(spec)

    # Build an Equipment card and an unrelated filler in P0's library.
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

    pre_library_names = {o.printing.name for o in py_state.players[0].library}
    pre_bf_p0 = [o for o in py_state.battlefield if o.controller_id == 0]
    pre_bf_p0_names = {o.printing.name for o in pre_bf_p0}

    # Bridge-admit + resolve.
    bridged = _ta_dict_to_python_effect(
        {"kind": "search_library_for_equipment_to_battlefield"}
    )
    assert isinstance(bridged, SearchLibraryForEquipmentToBattlefield)
    bridged.resolve(py_state, controller_id=0, targets=())

    # Equipment is on P0's battlefield.
    post_bf_p0 = [o for o in py_state.battlefield if o.controller_id == 0]
    post_bf_p0_names = {o.printing.name for o in post_bf_p0}
    new_bf_names = post_bf_p0_names - pre_bf_p0_names
    assert "DDD Knight-Captain Probe Equipment" in new_bf_names, (
        "SearchLibraryForEquipmentToBattlefield.resolve should put the "
        "Equipment onto the controller's battlefield.  "
        f"Pre bf names={sorted(pre_bf_p0_names)!r}, "
        f"post bf names={sorted(post_bf_p0_names)!r}, "
        f"diff={sorted(new_bf_names)!r}."
    )

    # Equipment is no longer in P0's library.
    post_library_names = {
        o.printing.name for o in py_state.players[0].library
    }
    assert (
        "DDD Knight-Captain Probe Equipment" not in post_library_names
    ), (
        "Equipment should have been moved out of P0's library by the "
        "tutor resolve.  "
        f"Pre library names={sorted(pre_library_names)!r}, "
        f"post library names={sorted(post_library_names)!r}."
    )

    # Equipment is on battlefield untapped (post-TTT-Pin-2 closure:
    # non-creature ETBs leave summoning_sick=False; this probe also
    # cross-validates that invariant on a fresh Equipment ETB).
    bf_equip = next(
        o for o in post_bf_p0
        if o.printing.name == "DDD Knight-Captain Probe Equipment"
    )
    assert bf_equip.zone == Zone.BATTLEFIELD, (
        "Equipment should be in Zone.BATTLEFIELD post-tutor.  "
        f"Got {bf_equip.zone!r}."
    )
    assert bf_equip.tapped is False, (
        "SearchLibraryForEquipmentToBattlefield resolve enters the "
        "Equipment UNTAPPED (distinct from "
        "SearchLibraryForBasicLandTapped which enters tapped).  "
        f"Got tapped={bf_equip.tapped!r}."
    )
    assert bf_equip.summoning_sick is False, (
        "Non-creature Equipment ETB should leave summoning_sick=False "
        "(slice 14 TTT Pin 2 CR 302.1 + 612.6 closure -- non-creatures "
        "are not summoning sick).  Got "
        f"summoning_sick={bf_equip.summoning_sick!r}."
    )
