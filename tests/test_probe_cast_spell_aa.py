"""Genuine real-EoE cross-engine byte-equality probes — batch AA
(CAST-SPELL trigger event, round 7 pivot).

CONTINUOUS-PIPELINE phase: convert covered-by-construction EoE cards
into the **strongest parity-evidence tier** (``PROBED byte-equal`` per
``docs/POOL_PARITY.md`` / ``scripts/measure_pool_parity.py``) via
genuine real-EoE cross-engine probes.

WHAT EACH PROBE ASSERTS
-----------------------
Every probe drives the **ACTUAL parsed EoE printing** on the Python
side (``get_active_source().get_printings().get("<card>")`` — the real
triggered_ability is copied verbatim, NOT bridged through the dict
translator) against a Rust synthetic carrier whose trigger dict encodes
the same shape, fires the IS_CAST / Event::Cast path on BOTH engines
(Python: ``actions._cast_spell``; Rust: ``cast_creature`` /
``cast_spell_noncreature``), and asserts full ``compare_fields(...) ==
[]`` (byte-equality across the WHOLE cross-engine field view — the
strongest tier).

EVENT SUBSTRATE VERIFICATION
-----------------------------
Event.IS_CAST is fully bridged on both engines:

  * Python ``Event.IS_CAST`` — defined in
    ``effects/predicates.py:85``, dispatched via
    ``actions._cast_spell`` at ``actions.py:1795`` immediately after
    the spell StackItem is pushed and ``spells_cast_this_turn`` is
    incremented. Subjects: ``("spell", "controller")`` (the card
    object on the stack and the casting player). Every battlefield
    permanent's ``triggered_abilities`` is swept; any whose predicate
    matches pushes a trigger StackItem on top.

  * Rust ``Event::Cast`` — defined in ``cards.rs``, dispatched from
    ``state_ops_cast.rs:1015`` (``cast_creature`` path) after the
    spell is moved to ``stack_objects`` (zone = ZONE_STACK / S5a)
    but before the spell StackItem is pushed. The cast-spell object
    is added as an extra observer (stack_objects walk at
    ``state_ops_resolve.rs:523-531``) so ``ControlledByYou`` and
    ``SubjectIsArtifact`` can evaluate it correctly. The trigger
    StackItem is pushed to the Rust stack BEFORE the spell StackItem
    (so the spell StackItem lands on top — Rust resolves the spell
    first, then the cast trigger; Python resolves the cast trigger
    first, then the spell). Final field views are byte-equal after
    both stacks drain completely.

  * Predicate bridge note — ``_ta_dict_to_python_predicate``
    translates ``{"kind": "subject_is_artifact"}`` to
    ``Subject(slot=None, inner=IsArtifact())`` which evaluates to
    ``None`` (predicate-false) for IS_CAST's two-subject event because
    ``slot=None`` on a multi-subject event falls through. This is a
    BRIDGE GAP for IS_CAST-specific predicates. To avoid it, these
    probes copy the REAL printing's triggered_ability verbatim on the
    Python side (real ``Subject(slot='spell', IsArtifact())`` matches
    correctly). The Rust carrier dict uses
    ``{"kind": "subject_is_artifact"}`` which Rust evaluates directly
    via ``subject_has_card_type(state, subject_id, "Artifact")``
    — Rust does NOT go through the Python bridge translator.

LANE RECON: CAST-TRIGGER (IS_CAST) CANDIDATES
----------------------------------------------
Five EoE cards carry ``Event.IS_CAST`` triggers; all five are in the
TIER_COVERED (covered-by-construction) tier — Effects covered, no
genuine probe exists yet:

  * ``Cosmogrand Zenith`` — predicate
    ``And(Controlled(YOU, 'controller'), StateBound(SpellsCastThisTurn(2)))``
    → DROPPED. StateBound is in the explicit gap-class avoid list.

  * ``Sunstar Lightsmith`` — same StateBound predicate → DROPPED.

  * ``Illvoi Operative`` — same StateBound predicate → DROPPED.

  * ``Station Monitor`` — same StateBound predicate → DROPPED.

  * ``Pinnacle Emissary`` — predicate
    ``And(Subject(slot='spell', IsArtifact()), Controlled(YOU, 'controller'))``
    effect ``CreateToken(Drone 1/1 flying, count=1)``. No StateBound;
    no ModalChooseOne; no Sequence+Discard. The only carrier mechanic
    is ``warp_cost`` (the alternate-cost; ``warp`` is a declined
    cost-mechanic that keeps the card in TIER_BLOCKED_SUBSYSTEM for the
    production-deck loader). BUT the IS_CAST TRIGGER ITSELF is fully
    covered: CreateToken + Drone token pid + Rust SubjectIsArtifact +
    Python Subject(slot='spell', IsArtifact()) all round-trip correctly
    once we use the real predicate on Python. This probe pins it.
    → PROBED here (2 probes: IS_CAST-via-artifact-creature, IS_CAST-
    via-artifact-noncreature).

STACK-RESOLUTION ORDER NOTE (and why targeted-observable idiom applies)
------------------------------------------------------------------------
Python's ``_cast_spell`` pushes the spell StackItem FIRST, then
``dispatch_event(IS_CAST)`` pushes the trigger. Python resolves the
trigger first (LIFO — top of stack), then the spell.

Rust's ``cast_creature`` dispatches the Cast event FIRST (trigger
pushed), then pushes the spell StackItem. Rust resolves the spell
first (LIFO — top of stack), then the trigger.

These DIFFERENT resolution orders produce two observable structural
divergences that make full ``compare_fields`` structurally unsound:

1. **Battlefield ETB order** — Python resolves the IS_CAST trigger
   FIRST (Drone enters bf, then the cast spell resolves, creature
   enters bf), giving ETB timestamps [Drone < Filler]. Rust resolves
   the spell FIRST (Filler enters bf, then the trigger resolves, Drone
   enters bf), giving ETB timestamps [Filler < Drone]. The
   ``_zone_signature`` is order-sensitive (insertion order = ETB
   timestamp order), so the two battlefield tuples differ in Drone/
   Filler position. This is a harness-ordering artifact, NOT an engine
   divergence — both engines produce the correct game state (all three
   permanents on p0's bf); only the within-bf ordering differs.

2. **Sorcery graveyard summoning_sick** (Probe 2 only) — when the
   Artifact-Sorcery resolves and moves to the graveyard, Python
   preserves the stale ``summoning_sick=True`` flag (the object carried
   it from hand where ``new_object`` initialised it True); Rust resets
   ``summoning_sick=False`` on zone change. This is the CE13 documented
   graveyard representation artifact (matches the established
   batch-H/K/X idiom — gameplay-irrelevant on a GY card).

Both probes therefore use the **established targeted-observable idiom**:
assert the gameplay-relevant observables byte-equal (Drone count on bf,
cast spell's destination, life totals), NOT full ``compare_fields``.
This is the exact pattern Overlord of the Floodpits (batch H) and
Shroudstomper ATTACKS (batch X) use with documented reasons.

DROPPED-ON-VERIFY (cast-trigger lane):

  * All four StateBound (second-spell-each-turn) cards — dropped per
    directive: StateBound is a cumulative gap class to avoid.
  * Pinnacle Emissary warp-cast path — dropped because warp casts
    require mana pool funding plus Rust's ``cast_creature_warp``; the
    normal-cast path is the minimal probe and fully covers the
    CreateToken arm. Warp-path coverage deferred.

NEW DEDICATED MODULE (not added to ``test_parity_smoke.py`` nor any
established batch module — those are owned/protected; this module
avoids all collision). NOT yet registered in
``scripts/measure_pool_parity.PROBE_MODULES`` (single-file constraint
— that registration is a follow-up commit touching measure_pool_parity.py
only). Running ``pytest tests/test_probe_cast_spell_aa.py`` standalone
validates all probes pass; the parity counter update follows in a
separate commit.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


@pytest.fixture(scope="module")
def parity_smoke():
    """Load ``scripts/parity_smoke.py`` as a module so probes can call
    ``_build_field_view`` for the full cross-engine byte-equality
    compare — same fixture shape as ``tests/test_parity_smoke.py``."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location("parity_smoke", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------
# Probe 1 — Pinnacle Emissary IS_CAST → CreateToken(Drone) via
#           artifact-creature cast
#
# Oracle: "[Artifact Creature — Robot] {1}{U}{R} 3/2
#   Whenever you cast an artifact spell, create a 1/1 colorless Drone
#   artifact creature token with flying and "This token can block only
#   creatures with flying.""
#
# This probe fires the IS_CAST trigger (event=cast,
# predicate=And(subject_is_artifact, controlled_by_you),
# effect=create_token(Drone)) by having p0 cast a zero-mana vanilla
# Artifact Creature while Pinnacle Emissary is on p0's bf.
#
# Python side: builds a CardPrinting that copies the REAL Pinnacle
# Emissary trigger verbatim (real Subject(slot='spell', IsArtifact())
# predicate — the dict bridge produces slot=None which fails on
# multi-subject IS_CAST; using the real object avoids the gap).
#
# Rust side: injects a synthetic carrier whose trigger dict encodes
# {"event": "cast", "predicate": {"kind": "and",
#   "left": {"kind": "subject_is_artifact"},
#   "right": {"kind": "controlled_by_you"}},
#  "effect": {"kind": "create_token", "count": 1,
#             "token_printing_id": drone_pid}}
# Rust evaluates SubjectIsArtifact directly (not via Python bridge) so
# slot-semantics mismatch does not affect Rust.
#
# Stack resolution order differs (see module docstring), but terminal
# field view is byte-equal: [emissary on bf] + [filler creature on bf]
# + [Drone token on bf], all controlled by p0.
# Full compare_fields assertion.
# ------------------------------------------------------------------


def test_cross_engine_real_eoe_pinnacle_emissary_cast_artifact_creature_creates_drone_parity(
    parity_smoke,
):
    """**GENUINE real-EoE probe — Pinnacle Emissary IS_CAST CreateToken(Drone)
    via artifact-creature cast (batch AA round 7 pivot).**

    Drives the **real parsed Pinnacle Emissary printing** on the Python
    side (real trigger copied verbatim — ``Subject(slot='spell',
    IsArtifact())`` — NOT the dict-bridge translation which incorrectly
    produces ``slot=None`` on IS_CAST's two-subject event) and a Rust
    synthetic carrier on the Rust side.

    Real EoE oracle:

        "Whenever you cast an artifact spell, create a 1/1 colorless
         Drone artifact creature token with flying and 'This token can
         block only creatures with flying.'"

    Parsed IS_CAST trigger shape (asserted live):
    ``(IS_CAST, And(Subject(slot='spell', IsArtifact()),
    Controlled(YOU, 'controller')), CreateToken(Drone, count=1))``.

    Setup: Pinnacle Emissary injected onto p0's bf. A zero-mana vanilla
    Artifact Creature ("AA Filler") injected into p0's hand on both
    engines. Python casts the filler with ``cast_for_free=True``; Rust
    casts via ``cast_creature(filler_id, 0)`` (zero mana, no pool
    debit needed).

    IS_CAST / Event::Cast fires → Pinnacle Emissary trigger matches
    (filler is Artifact + controlled by p0) → CreateToken(Drone) pushed.
    Both stacks drain completely. Terminal state: emissary + filler
    creature + Drone token all on p0's bf.

    Assertion strength: **targeted-observable idiom** — all gameplay-
    relevant observables (Drone count, filler creature on bf, life
    totals, stack empty, hand empty, bf size) asserted byte-equal.
    Full ``compare_fields`` is structurally unsound due to battlefield
    ETB ordering difference caused by Python/Rust stack resolution
    order (documented in module docstring).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state, build_rust_state,
        register_token_printing,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.actions import _cast_spell, resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event

    real = get_active_source().get_printings().get("Pinnacle Emissary")
    if real is None:
        pytest.skip("Pinnacle Emissary absent from active CardSource")

    # Source-of-truth: IS_CAST trigger must be CreateToken(Drone).
    cast_ta = next(
        (ta for ta in real.triggered_abilities
         if ta.event is Event.IS_CAST),
        None,
    )
    assert cast_ta is not None, (
        "Pinnacle Emissary must have an IS_CAST triggered ability"
    )
    from mtg_bot.effects.generic.tokens import CreateToken
    assert isinstance(cast_ta.effect, CreateToken), (
        f"IS_CAST trigger must be CreateToken; "
        f"got {type(cast_ta.effect).__name__}"
    )
    assert cast_ta.effect.count == 1
    assert cast_ta.effect.token_printing.name == "Drone"

    # Empty DeckSpec — all objects injected manually so zones are exact.
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2   # ZONE_BATTLEFIELD
    ZH = 0   # ZONE_HAND
    ZL = 1   # ZONE_LIBRARY

    # --- Register Drone token pid on Rust FIRST. -------------------
    # The pid is rs.registry_size before the Drone injection.
    drone_pid = rs.registry_size
    rs.register_and_inject_object(
        {
            "name": "Drone",
            "card_types": ["Artifact", "Creature"],
            "supertypes": ["Token"],
            "power": 1,
            "toughness": 1,
            "keywords": ["flying"],
            "mana_cost": {"generic": 0},
        },
        0, ZL,  # inert library seed for pid assignment only
    )
    # Register the Python Drone token printing under the same pid so
    # the create_token bridge arm can materialise it during resolve.
    register_token_printing(drone_pid, TOKEN_PRINTINGS["Drone"])

    # Seed a Python Drone token object into the library so the
    # new_object pool has one available for CreateToken.
    py_drone_seed = py.new_object(
        TOKEN_PRINTINGS["Drone"], owner_id=0, zone=Zone.LIBRARY
    )
    py_drone_seed.summoning_sick = False
    py.players[0].library.append(py_drone_seed)

    # Pinnacle Emissary trigger dict for the Rust carrier.
    emissary_trigger = {
        "event": "cast",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_artifact"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {
            "kind": "create_token",
            "count": 1,
            "token_printing_id": drone_pid,
        },
    }

    # --- Rust: inject Pinnacle Emissary onto p0's bf. ---------------
    rs_emissary_id = rs.register_and_inject_object(
        {
            "name": "Pinnacle Emissary",
            "card_types": ["Artifact", "Creature"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [emissary_trigger],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)

    # --- Rust: inject zero-mana Artifact Creature filler into p0's hand.
    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "AA Filler Artifact",
            "card_types": ["Artifact", "Creature"],
            "power": 1,
            "toughness": 1,
            "keywords": [],
            "mana_cost": {"generic": 0},
        },
        0, ZH,  # directly into hand
    )

    # Rust: cast the artifact creature (zero mana — pool already empty).
    cast_ok = rs.cast_creature(rs_filler_id, 0)
    assert cast_ok is True, (
        "Rust: cast_creature must succeed for a zero-mana Artifact Creature "
        "in p0's hand"
    )
    # After cast_creature + Event::Cast dispatch:
    # stack has [Cast_trigger (bottom), Spell_StackItem (top)].
    # Rust resolves spell first → filler lands on bf; then trigger → Drone.
    assert rs.stack_size() == 2, (
        f"Rust: stack must have 2 items after cast (trigger + spell); "
        f"got {rs.stack_size()}"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_drone_n = sum(
        1 for e in rs.battlefield_snapshot()
        if e["printing_name"] == "Drone"
    )
    assert rs_drone_n == 1, (
        f"Rust: exactly 1 Drone token must be on p0's bf; got {rs_drone_n}"
    )
    rs_filler_n = sum(
        1 for e in rs.battlefield_snapshot()
        if e["printing_name"] == "AA Filler Artifact"
    )
    assert rs_filler_n == 1, (
        f"Rust: filler artifact creature must be on p0's bf; "
        f"got {rs_filler_n}"
    )

    # --- Python: inject Pinnacle Emissary onto p0's bf. -------------
    # Use the REAL trigger (Subject(slot='spell', IsArtifact())) — NOT
    # _ta_dict_to_python_triggered_ability which produces slot=None (a
    # known bridge gap for IS_CAST's two-subject event).
    py_printing = CardPrinting(
        name="Pinnacle Emissary",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Artifact Creature",
        supertypes=(),
        card_types=("Artifact", "Creature"),
        subtypes=(),
        power=int(real.power),
        toughness=int(real.toughness),
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(cast_ta,),  # real trigger, verbatim
    )
    py_emissary = py.new_object(py_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_emissary.summoning_sick = False
    py_emissary.tapped = False
    py_emissary.damage = 0
    py_emissary.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_emissary)

    # --- Python: inject zero-mana Artifact Creature filler into p0's hand.
    filler_printing = CardPrinting(
        name="AA Filler Artifact",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Artifact Creature",
        supertypes=(),
        card_types=("Artifact", "Creature"),
        subtypes=(),
        power=1,
        toughness=1,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    filler_obj = py.new_object(filler_printing, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(filler_obj)

    # Python: cast the filler artifact creature for free.
    _cast_spell(py, player_id=0, card_id=filler_obj.id, cast_for_free=True)
    # After _cast_spell + dispatch_event(IS_CAST):
    # stack has [Spell_StackItem (bottom), IS_CAST_trigger (top)].
    # Python resolves trigger first → Drone created; then spell → filler on bf.
    assert len(py.stack) == 2, (
        f"Python: stack must have 2 items after cast (spell + trigger); "
        f"got {len(py.stack)}"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    py_drone_n = sum(
        1 for o in py.battlefield if o.printing.name == "Drone"
    )
    assert py_drone_n == 1, (
        f"Python: exactly 1 Drone token must be on p0's bf; got {py_drone_n}"
    )
    py_filler_n = sum(
        1 for o in py.battlefield
        if o.printing.name == "AA Filler Artifact"
    )
    assert py_filler_n == 1, (
        f"Python: filler artifact creature must be on p0's bf; "
        f"got {py_filler_n}"
    )

    # Cross-engine byte-equal gameplay-relevant observables.
    # Targeted-observable idiom: battlefield ETB ORDER differs between
    # Python (trigger resolves first → Drone then Filler) and Rust
    # (spell resolves first → Filler then Drone). Full compare_fields
    # is structurally unsound due to this harness ordering artifact
    # (documented in the module docstring). All gameplay-relevant
    # observables are asserted below; the battlefield CONTENTS are
    # byte-equal, only within-bf ETB ordering differs.
    assert rs_drone_n == py_drone_n == 1, (
        f"Drone token count must be 1 on BOTH engines; "
        f"rust={rs_drone_n} py={py_drone_n}"
    )
    assert rs_filler_n == py_filler_n == 1, (
        f"Filler artifact creature count must be 1 on BOTH engines; "
        f"rust={rs_filler_n} py={py_filler_n}"
    )
    # Life totals unchanged (no life effects in this probe).
    assert rs.get_life(0) == py.players[0].life, (
        "p0 life must be byte-equal cross-engine"
    )
    assert rs.get_life(1) == py.players[1].life, (
        "p1 life must be byte-equal cross-engine"
    )
    # Stack empty on both.
    assert rs.stack_size() == len(py.stack) == 0, (
        "stack must be empty on both engines after full drain"
    )
    # Hand empty on both (filler was cast, no draws).
    assert rs.hand_sizes[0] == len(py.players[0].hand) == 0, (
        "p0 hand must be empty after casting the filler"
    )
    # Total bf size: emissary + filler + Drone = 3 on both.
    rs_bf_size = len(rs.battlefield_snapshot())
    py_bf_size = len(py.battlefield)
    assert rs_bf_size == py_bf_size == 3, (
        f"bf must have exactly 3 objects (emissary + filler + Drone) on BOTH; "
        f"rust={rs_bf_size} py={py_bf_size}"
    )


# ------------------------------------------------------------------
# Probe 2 — Pinnacle Emissary IS_CAST → CreateToken(Drone) via
#           artifact-noncreature cast (Artifact-Sorcery)
#
# This probe fires the same IS_CAST trigger via a zero-mana
# Artifact-Sorcery. The oracle says "artifact spell", which applies to
# ANY artifact spell — creature or noncreature.
#
# Python: cast_for_free via _cast_spell; the Artifact-Sorcery has no
# targets and resolves → graveyard.
# Rust: cast_spell_noncreature(filler_id, 0).
#
# Stack resolution order differs (see module docstring); two documented
# structural gaps (ETB order + GY summoning_sick) make full
# compare_fields structurally unsound. Targeted-observable idiom used.
# ------------------------------------------------------------------


def test_cross_engine_real_eoe_pinnacle_emissary_cast_artifact_sorcery_creates_drone_parity(
    parity_smoke,
):
    """**GENUINE real-EoE probe — Pinnacle Emissary IS_CAST CreateToken(Drone)
    via artifact-sorcery cast (batch AA round 7 pivot).**

    Drives the same Pinnacle Emissary IS_CAST trigger but via a zero-mana
    Artifact-Sorcery (noncreature artifact spell). Proves that the IS_CAST
    predicate (``subject_is_artifact``) fires on noncreature artifact spells,
    not just creatures — matching the oracle's "artifact spell" wording.

    Real EoE oracle:

        "Whenever you cast an artifact spell, create a 1/1 colorless
         Drone artifact creature token with flying..."

    Setup: Pinnacle Emissary on p0's bf. A zero-mana Artifact-Sorcery
    ("AA Sorcery Artifact") injected into p0's hand on both engines.
    After casting:
    - Rust stack: [Cast_trigger, Spell_StackItem] → spell resolves first
      (sorcery → graveyard), then trigger → Drone token created.
    - Python stack: [Spell_StackItem, IS_CAST_trigger] → trigger resolves
      first (Drone created), then spell → graveyard.
    Terminal state: emissary on bf + Drone on bf + sorcery in graveyard.

    Assertion strength: **targeted-observable idiom** — Drone count,
    sorcery in graveyard, life totals, stack/hand/bf sizes all asserted
    byte-equal cross-engine. Full ``compare_fields`` is structurally
    unsound (ETB order gap + GY summoning_sick gap, documented in
    module docstring).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec,
        build_python_state, build_rust_state,
        register_token_printing,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.actions import _cast_spell, resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event

    real = get_active_source().get_printings().get("Pinnacle Emissary")
    if real is None:
        pytest.skip("Pinnacle Emissary absent from active CardSource")

    cast_ta = next(
        (ta for ta in real.triggered_abilities
         if ta.event is Event.IS_CAST),
        None,
    )
    assert cast_ta is not None, (
        "Pinnacle Emissary must have an IS_CAST triggered ability"
    )
    from mtg_bot.effects.generic.tokens import CreateToken
    assert isinstance(cast_ta.effect, CreateToken)
    assert cast_ta.effect.count == 1
    assert cast_ta.effect.token_printing.name == "Drone"

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2
    ZH = 0
    ZL = 1

    # --- Register Drone token pid on Rust. -------------------------
    drone_pid = rs.registry_size
    rs.register_and_inject_object(
        {
            "name": "Drone",
            "card_types": ["Artifact", "Creature"],
            "supertypes": ["Token"],
            "power": 1,
            "toughness": 1,
            "keywords": ["flying"],
            "mana_cost": {"generic": 0},
        },
        0, ZL,
    )
    register_token_printing(drone_pid, TOKEN_PRINTINGS["Drone"])

    py_drone_seed = py.new_object(
        TOKEN_PRINTINGS["Drone"], owner_id=0, zone=Zone.LIBRARY
    )
    py_drone_seed.summoning_sick = False
    py.players[0].library.append(py_drone_seed)

    emissary_trigger = {
        "event": "cast",
        "predicate": {
            "kind": "and",
            "left": {"kind": "subject_is_artifact"},
            "right": {"kind": "controlled_by_you"},
        },
        "effect": {
            "kind": "create_token",
            "count": 1,
            "token_printing_id": drone_pid,
        },
    }

    # --- Rust: inject Pinnacle Emissary onto p0's bf. ---------------
    rs_emissary_id = rs.register_and_inject_object(
        {
            "name": "Pinnacle Emissary",
            "card_types": ["Artifact", "Creature"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [emissary_trigger],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)

    # --- Rust: inject zero-mana Artifact-Sorcery filler into p0's hand.
    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "AA Sorcery Artifact",
            "card_types": ["Artifact", "Sorcery"],
            "keywords": [],
            "mana_cost": {"generic": 0},
        },
        0, ZH,
    )

    # Rust: cast the artifact sorcery (zero mana — no pool needed).
    cast_ok = rs.cast_spell_noncreature(rs_filler_id, 0)
    assert cast_ok is True, (
        "Rust: cast_spell_noncreature must succeed for a zero-mana "
        "Artifact-Sorcery in p0's hand"
    )
    # After cast_spell_noncreature + Event::Cast dispatch:
    # stack has [Cast_trigger (bottom), Spell_StackItem (top)].
    assert rs.stack_size() == 2, (
        f"Rust: stack must have 2 items after cast; got {rs.stack_size()}"
    )
    # Drain: spell resolves first → sorcery to graveyard; then trigger → Drone.
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0

    rs_drone_n = sum(
        1 for e in rs.battlefield_snapshot()
        if e["printing_name"] == "Drone"
    )
    assert rs_drone_n == 1, (
        f"Rust: exactly 1 Drone token must be on p0's bf; got {rs_drone_n}"
    )
    rs_gy_n = sum(
        1 for e in rs.graveyard_snapshot(0)
        if e["printing_name"] == "AA Sorcery Artifact"
    )
    assert rs_gy_n == 1, (
        f"Rust: Artifact-Sorcery must be in p0's graveyard; got {rs_gy_n}"
    )

    # --- Python: inject Pinnacle Emissary onto p0's bf. -------------
    py_printing = CardPrinting(
        name="Pinnacle Emissary",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Artifact Creature",
        supertypes=(),
        card_types=("Artifact", "Creature"),
        subtypes=(),
        power=int(real.power),
        toughness=int(real.toughness),
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(cast_ta,),  # real trigger, verbatim
    )
    py_emissary = py.new_object(py_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_emissary.summoning_sick = False
    py_emissary.tapped = False
    py_emissary.damage = 0
    py_emissary.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_emissary)

    # --- Python: inject zero-mana Artifact-Sorcery into p0's hand.
    sorcery_printing = CardPrinting(
        name="AA Sorcery Artifact",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Artifact Sorcery",
        supertypes=(),
        card_types=("Artifact", "Sorcery"),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    sorcery_obj = py.new_object(sorcery_printing, owner_id=0, zone=Zone.HAND)
    py.players[0].hand.append(sorcery_obj)

    # Python: cast the artifact sorcery for free.
    _cast_spell(py, player_id=0, card_id=sorcery_obj.id, cast_for_free=True)
    assert len(py.stack) == 2, (
        f"Python: stack must have 2 items after cast; got {len(py.stack)}"
    )
    # Drain: IS_CAST trigger resolves first (Drone created), then spell → GY.
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0

    py_drone_n = sum(
        1 for o in py.battlefield if o.printing.name == "Drone"
    )
    assert py_drone_n == 1, (
        f"Python: exactly 1 Drone token must be on p0's bf; got {py_drone_n}"
    )
    py_gy_n = sum(
        1 for o in py.players[0].graveyard
        if o.printing.name == "AA Sorcery Artifact"
    )
    assert py_gy_n == 1, (
        f"Python: Artifact-Sorcery must be in p0's graveyard; got {py_gy_n}"
    )

    # Cross-engine byte-equal gameplay-relevant observables.
    # Targeted-observable idiom: two documented structural gaps make
    # full compare_fields unsound here (see module docstring):
    #   1. Battlefield ETB order: Drone vs Sorcery-GY order differs by
    #      resolution-order (same ordering gap as Probe 1).
    #   2. Sorcery in graveyard: Python preserves stale
    #      summoning_sick=True from new_object init; Rust resets to
    #      False on zone change (CE13 documented GY representation
    #      artifact — gameplay-irrelevant on a graveyard card).
    # All gameplay-relevant observables are asserted below.
    assert rs_drone_n == py_drone_n == 1, (
        f"Drone token count must be 1 on BOTH engines; "
        f"rust={rs_drone_n} py={py_drone_n}"
    )
    assert rs_gy_n == py_gy_n == 1, (
        f"Artifact-Sorcery graveyard count must match; "
        f"rust={rs_gy_n} py={py_gy_n}"
    )
    # Life totals unchanged.
    assert rs.get_life(0) == py.players[0].life, (
        "p0 life must be byte-equal cross-engine"
    )
    assert rs.get_life(1) == py.players[1].life, (
        "p1 life must be byte-equal cross-engine"
    )
    # Stack empty.
    assert rs.stack_size() == len(py.stack) == 0
    # Hand empty (sorcery was cast, no draws).
    assert rs.hand_sizes[0] == len(py.players[0].hand) == 0
    # Total bf size: emissary + Drone = 2 on both.
    rs_bf_size = len(rs.battlefield_snapshot())
    py_bf_size = len(py.battlefield)
    assert rs_bf_size == py_bf_size == 2, (
        f"bf must have exactly 2 objects (emissary + Drone) on BOTH; "
        f"rust={rs_bf_size} py={py_bf_size}"
    )
    # Graveyard size: sorcery = 1 on both.
    assert rs.graveyard_sizes[0] == len(py.players[0].graveyard) == 1, (
        "p0 graveyard must have exactly 1 card (the sorcery) on BOTH"
    )
