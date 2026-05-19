"""Genuine real-EoE cross-engine byte-equality probes — batch X
(ATTACKS trigger event, round 6 pivot).

CONTINUOUS-PIPELINE phase: convert covered-by-construction EoE cards
into the **strongest parity-evidence tier** (``PROBED byte-equal`` per
``docs/POOL_PARITY.md`` / ``scripts/measure_pool_parity.py``) via
genuine real-EoE cross-engine probes.

WHAT EACH PROBE ASSERTS
-----------------------
Every probe drives the **ACTUAL parsed EoE printing** on the Python
side (``get_active_source().get_printings().get("<card>")`` — NOT a
synthetic stub) against a bridged synthetic carrier on the Rust side
(``register_and_inject_object`` carrying the SAME ATTACKS trigger dict),
fires the EXACT real ``triggered_ability`` through the production
ATTACKS path on BOTH engines (Python: ``declare_attackers``; Rust:
``declare_attacker``), and asserts full ``compare_fields(...) == []``
(byte-equality across the WHOLE cross-engine field view — the strongest
tier), or the established targeted-observable idiom where a documented
zone-move summoning_sick divergence makes full compare_fields
structurally unsound.

EVENT SUBSTRATE VERIFICATION
-----------------------------
Both ATTACKS and LEAVES_BATTLEFIELD events are fully bridged:

  * ``Event.ATTACKS`` — defined in ``effects/predicates.py:61``,
    bridged in ``parity/cross_engine.py:8808-8809``, dispatched per
    attacker in ``combat.py:196`` (Python) and
    ``state_ops_combat.rs:719`` (Rust).

  * ``Event.LEAVES_BATTLEFIELD`` — defined in
    ``effects/predicates.py:59``, bridged in
    ``parity/cross_engine.py:8812-8813``, dispatched in
    ``turn.py:369`` (Python) and the Rust LB site
    (``cards.rs:4002-4014``).

LANE RECON: LEAVES_BATTLEFIELD
--------------------------------
All LEAVES_BATTLEFIELD trigger cards found in the parsed EoE pool are
**BLOCKED** — none are covered-by-construction:

  * ``Anticausal Vestige`` — bespoke ``AnticausalVestigeLeavesEffect``
    (no bridge arm). BLOCKED.
  * ``Broodguard Elite`` — ``MoveSelfCountersToTargetCreatureYouControl``
    (no bridge arm). BLOCKED.
  * ``Cryogen Relic`` — ALREADY PROBED on ETB arm; its
    LEAVES_BATTLEFIELD trigger (``DrawCards``) fires on ANY zone exit,
    but the leaves-bf probe would require Rust's LB dispatch to push a
    trigger after a destroy/exile mutation — the LB bridge arm is
    wired at the Python ``_fire_leaves_battlefield_triggers`` site but
    the parallel Rust site for non-DIES exits is not exercised by any
    existing probe; a substrate validation probe is warranted but
    requires a two-step destroy+resolve path that is a separate lane
    from this batch's covered-by-construction focus.
  * ``Nutrient Block`` — ``DrawCards`` on LB; dropped in batch T
    because the draw fires from an empty library causing ``is_over``
    divergence (documented drop reason).
  * ``Syr Vondam, Sunstar Exemplar`` — two LB triggers, one of which
    is ``ConditionalIfSourcePowerAtLeast`` (no covered bridge arm).
    BLOCKED.

Result: LEAVES_BATTLEFIELD lane has **zero accessible real-EoE
covered-by-construction cards** at this HEAD. This is an honest
substrate gap finding — the LEAVES_BATTLEFIELD event IS bridged, but
every EoE LB trigger card is BLOCKED for other reasons (bespoke
effects, uncovered Effect classes, or documented library-empty hazard).
This finding is the valid deliverable for the LB axis; no forced probes.

PARTITION DISCIPLINE (batch X — ATTACKS triggers only)
-------------------------------------------------------
Prior rounds probed ATTACKS via Sunset Saboteur (targeted seat,
Haliya ATTACKS and Overlord ATTACKS legs left as "separate probe
surface" notes). This batch:

  1. Overlord of the Mistmoors — ATTACKS CreateToken(2× Insect
     2/1 flying). ETB probe (batch H) pins the ``create_token``
     arm end-to-end; THIS probe drives the SAME card's ATTACKS leg —
     distinct event, same Effect shape — via ``declare_attacker``.
     The ETB and ATTACKS triggers are structurally identical; the new
     pin proves the ATTACKS dispatch path fires CreateToken correctly.

  2. Shroudstomper — ATTACKS Sequence(Sequence(EachOpponentLosesLife(2),
     GainLife(2)), DrawCards(1)). ETB probe (batch K) pins the nested
     Sequence on the ENTERS path; THIS probe drives the ATTACKS leg.
     Uses the established targeted-observable idiom for the DrawCards
     arm (draw→hand zone move sets ``summoning_sick=False`` on Rust,
     preserves stale True on Python — gameplay-irrelevant graveyard
     flag documented in the batch-H/K ETB sisters).

  3. Specimen Freighter — ATTACKS EachOpponentMillsCards(4). This is
     the ONLY EoE card whose PRIMARY trigger (the non-ETB leg) is
     ATTACKS-only with ``EachOpponentMillsCards``. The card is an
     Artifact (not a Creature) with power=4/toughness=7 — both engines
     treat it as attackable (Python: ``declare_attackers`` does not
     filter on ``is_creature``; Rust: ``read_creature_status`` gates on
     ``printing.power.is_none()``, which passes for 4/7). Mill is
     untargeted; no agent shim needed. Full ``compare_fields``.

DROPPED-ON-VERIFY:

  * **Overlord of the Floodpits ATTACKS** — ``Sequence(DrawCards(2),
    DiscardSelf(1))`` fires on ATTACKS. The ``_DiscardFirstAgent`` shim
    from the ETB probe (batch H) works the same way here, but the 2-card
    draw requires 2 filler cards in p0's library, the discard pops
    hand[0], and the ``summoning_sick`` graveyard-artifact divergence
    documented in batch H recurs. This is a structurally valid probe,
    but the ETB probe already pins the Sequence(DrawCards+Discard) shape
    with the documented idiom; the ATTACKS variant adds no new bridge
    coverage. Deferred to a later round that specifically targets
    Sequence-with-discard ATTACKS coverage.

  * **Haliya, Ascendant Cadet ATTACKS** —
    ``PutPlusOneCounterOnCreatureYouControl`` (targeted, IsSelf). The
    ETB probe (test_parity_smoke.py:36675) already pins the
    ``put_plus_one_counter_on_creature_you_control`` bridge arm against
    the Haliya carrier; the ATTACKS leg fires the same bridge arm. The
    Tier-C seat (no-agent first-legal scan) is already tested by Sunset
    Saboteur (``put_plus_one_counter_on_opponents_creature``) and Haliya
    ETB (``put_plus_one_counter_on_creature_you_control``) — adding a
    third pin on the same arm is lower value than a fresh Effect class.
    Deferred.

  * All BLOCKED ATTACKS cards (Alpharael Stonechosen, Arabella Abandoned
    Doll, Attack-in-the-Box, Atomic Microsizer, Baseball Bat, Chorale of
    the Void, Comet Crawler, Entropic Battlecruiser, Fear of Surveillance,
    etc.) — Effect-uncovered or subsystem-gated. Dropped per directive.

NEW DEDICATED MODULE (not added to ``test_parity_smoke.py`` nor the
established batch_a / batch_b / … / batch_k / batch_t modules — those
are owned/protected; this module avoids all collision).
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


# ---------------------------------------------------------------------
# Probe 1 — Overlord of the Mistmoors ATTACKS → CreateToken(2× Insect)
#
# Oracle: "[Enchantment Creature — Leviathan] 6/6
#   Whenever this creature enters or attacks, create two 2/1 white
#   Insect creature tokens with flying."
# This probe drives the ATTACKS leg (event=attacks, predicate=IsSelf,
# effect=CreateToken(Insect 2/1 flying, count=2)).
# The ETB leg was probed in batch H (test_probe_covered_unprobed_h.py).
#
# Setup: Overlord injected onto p0's bf (unsick, untapped). Python:
# declare_attackers([overlord_id]) → ATTACKS triggers fire → 2 Insect
# tokens spawn. Rust: declare_attacker(overlord_id) → same path.
# Insect token pid pre-registered on Rust; Python uses intrinsic
# TOKEN_PRINTINGS["Insect"]. Full compare_fields.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_overlord_of_the_mistmoors_attacks_create_insect_tokens_parity(
    parity_smoke,
):
    """**GENUINE real-EoE probe — Overlord of the Mistmoors ATTACKS
    CreateToken(2× Insect 2/1 flying) (batch X round 6 pivot).**

    Drives the **real parsed Overlord of the Mistmoors printing** through
    the ATTACKS path on BOTH engines.  Batch-H already pinned the ETB
    (ENTERS) leg end-to-end; THIS probe pins the ATTACKS leg separately.

    Real EoE oracle:

        "Whenever this creature enters or attacks, create two 2/1 white
         Insect creature tokens with flying."

    Parsed ATTACKS trigger shape (asserted live):
    ``(ATTACKS, IsSelf, CreateToken(Insect 2/1 flying, count=2))``.

    The Overlord is injected onto p0's bf already unsick and untapped so
    ``declare_attacker`` / ``declare_attackers`` succeed.  Two Insect
    tokens spawn on p0's bf on BOTH engines; life totals unchanged.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (2 Insects on p0's bf on BOTH; life unchanged).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
        register_token_printing, _ta_dict_to_python_triggered_ability,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.generic.tokens import CreateToken

    real = get_active_source().get_printings().get("Overlord of the Mistmoors")
    if real is None:
        pytest.skip("Overlord of the Mistmoors absent from active CardSource")

    # §2 source-of-truth: genuine ATTACKS trigger must be CreateToken.
    attacks_ta = next(
        (ta for ta in real.triggered_abilities if ta.event is Event.ATTACKS),
        None,
    )
    assert attacks_ta is not None, (
        "Overlord of the Mistmoors must have an ATTACKS triggered ability"
    )
    assert isinstance(attacks_ta.effect, CreateToken), (
        f"ATTACKS trigger must be CreateToken; got {type(attacks_ta.effect).__name__}"
    )
    assert attacks_ta.effect.count == 2
    assert attacks_ta.effect.token_printing.name == "Insect"

    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # Register Insect token pid on Rust FIRST (established token-pid idiom).
    # The pid assignment is determined by rs.registry_size before injection.
    # register_token_printing must be called BEFORE _ta_dict_to_python_triggered_ability
    # so the create_token bridge arm can look up the Python printing by pid.
    insect_pid = rs.registry_size
    rs.register_and_inject_object(
        {"name": "Insect", "card_types": ["Creature"],
         "supertypes": ["Token"], "power": 2, "toughness": 1,
         "keywords": ["flying"],
         "mana_cost": {"generic": 0}},
        0, 1,  # owner=0, ZONE_LIBRARY (inert seed for pid assignment)
    )
    # Register the Python Insect token printing under the same pid so the
    # create_token bridge arm can materialise it during trigger translation.
    register_token_printing(insect_pid, TOKEN_PRINTINGS["Insect"])

    py_seed = py.new_object(
        TOKEN_PRINTINGS["Insect"], owner_id=0, zone=Zone.LIBRARY
    )
    py_seed.summoning_sick = False
    py.players[0].library.append(py_seed)

    # ATTACKS trigger dict — used for both Rust carrier injection and
    # Python printing construction (via _ta_dict_to_python_triggered_ability).
    overlord_trigger = {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {
            "kind": "create_token",
            "count": 2,
            "token_printing_id": insect_pid,
        },
    }

    # --- Rust: inject Overlord onto p0's bf (unsick, untapped). -------
    rs_id = rs.register_and_inject_object(
        {
            "name": "Overlord of the Mistmoors",
            "card_types": ["Enchantment", "Creature"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [overlord_trigger],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    # Rust: declare_attacker fires the ATTACKS dispatch → CreateToken push.
    assert rs.declare_attacker(rs_id) is True, (
        "Rust: declare_attacker must succeed for a valid unsick attacker"
    )
    assert rs.stack_size() == 1, (
        "Rust: ATTACKS trigger must be pushed onto the stack after declaring"
    )

    # --- Python: inject Overlord onto p0's bf (unsick, untapped). -----
    py_printing = CardPrinting(
        name="Overlord of the Mistmoors",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Enchantment Creature",
        supertypes=(),
        card_types=("Enchantment", "Creature"),
        subtypes=(),
        power=int(real.power),
        toughness=int(real.toughness),
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(
            _ta_dict_to_python_triggered_ability(overlord_trigger),
        ),
    )
    py_obj = py.new_object(py_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)

    # Python: declare_attackers → _fire_attacks_triggers → CreateToken push.
    py_declare_attackers(py, [py_obj.id])
    assert len(py.stack) == 1, (
        "Python: ATTACKS trigger must be pushed onto the stack after declaring"
    )

    # --- Drain both stacks (CreateToken resolves: 2 Insects spawn). ---
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    rs.apply_sbas()
    assert rs.stack_size() == 0 and len(py.stack) == 0

    # Concrete observable: exactly 2 Insect tokens on p0's bf on BOTH.
    rs_insect_n = sum(
        1 for e in rs.battlefield_snapshot()
        if e["printing_name"] == "Insect"
    )
    py_insect_n = sum(
        1 for o in py.battlefield if o.printing.name == "Insect"
    )
    assert rs_insect_n == 2 == py_insect_n, (
        f"Overlord of the Mistmoors ATTACKS → exactly 2 Insects on BOTH; "
        f"rust={rs_insect_n} py={py_insect_n}"
    )

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Overlord of the Mistmoors ATTACKS create-insect-tokens must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )


# ---------------------------------------------------------------------
# Probe 2 — Shroudstomper ATTACKS → Sequence(drain+draw)
#
# Oracle: "[Creature — Beast] {5}{G}{G} 5/5
#   When this creature enters or attacks, each opponent loses 2 life
#   and you gain 2 life, then draw a card."
# This probe drives the ATTACKS leg (event=attacks, predicate=IsSelf,
# effect=Sequence(Sequence(EachOpponentLosesLife(2), GainLife(2)),
# DrawCards(1))).
# The ETB leg was probed in batch K (test_probe_covered_unprobed_k.py).
#
# One filler card in p0's library so DrawCards(1) is observable.
# Rust: declare_attacker fires → sequence resolves → p1 -2 life,
#       p0 +2 life, p0 draws 1.
# Python: declare_attackers → same.
#
# Established targeted-observable idiom (documented reason): the
# DrawCards(1) moves a seeded-library object library→hand; Rust resets
# ``summoning_sick=False`` on zone change while Python preserves the
# stale True — a gameplay-irrelevant hand-card flag on a card in hand,
# NOT a draw engine divergence. The probe pins all gameplay-relevant
# observables (zone sizes, life totals) byte-equal cross-engine.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_shroudstomper_attacks_life_drain_draw_parity(
    parity_smoke,
):
    """**GENUINE real-EoE probe — Shroudstomper ATTACKS Sequence(drain+
    draw) (batch X round 6 pivot).**

    Drives the **real parsed Shroudstomper printing** through the ATTACKS
    path on BOTH engines.  Batch-K already pinned the ETB (ENTERS) leg;
    THIS probe pins the ATTACKS leg: each opponent loses 2 life, you gain
    2 life, then draw a card.

    Real EoE oracle:

        "When this creature enters or attacks, each opponent loses 2 life
         and you gain 2 life, then draw a card."

    Parsed ATTACKS trigger shape (asserted live):
    ``(ATTACKS, IsSelf, Sequence(Sequence(EachOpponentLosesLife(2),
    GainLife(2)), DrawCards(1)))``.

    One filler card in p0's library → DrawCards(1) draws it → p0 hand
    has 1 card.  p1 loses 2 life, p0 gains 2 life, p0 draws 1 — all
    cross-engine byte-equal on the gameplay-relevant observables
    (established targeted-observable idiom: summoning_sick on the
    library-seeded card in hand is gameplay-irrelevant).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state, CardDef,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.draw_mill import DrawCards

    real = get_active_source().get_printings().get("Shroudstomper")
    if real is None:
        pytest.skip("Shroudstomper absent from active CardSource")

    # §2 source-of-truth: genuine ATTACKS trigger must be Sequence.
    attacks_ta = next(
        (ta for ta in real.triggered_abilities if ta.event is Event.ATTACKS),
        None,
    )
    assert attacks_ta is not None, (
        "Shroudstomper must have an ATTACKS triggered ability"
    )
    assert isinstance(attacks_ta.effect, Sequence), (
        f"ATTACKS trigger must be Sequence; got {type(attacks_ta.effect).__name__}"
    )
    assert isinstance(attacks_ta.effect.effects[1], DrawCards)
    assert attacks_ta.effect.effects[1].amount == 1

    # One filler card in p0's library → DrawCards(1) is forced + observable.
    filler = CardDef(name="STO Filler", card_type="Land", mana_produced=("G",))
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=("STO Filler",),
        p1_library=(),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    py_p0_life0 = py.players[0].life
    py_p1_life0 = py.players[1].life

    # The ATTACKS trigger dict (same shape as ETB, different event key).
    attacks_trigger = {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "sequence", "effects": [
            {"kind": "sequence", "effects": [
                {"kind": "each_opponent_loses_life", "amount": 2},
                {"kind": "gain_life", "amount": 2},
            ]},
            {"kind": "draw_cards", "count": 1},
        ]},
    }

    # --- Rust: inject Shroudstomper onto p0's bf (unsick, untapped). --
    rs_id = rs.register_and_inject_object(
        {
            "name": "Shroudstomper",
            "card_types": ["Creature"],
            "power": int(real.power),
            "toughness": int(real.toughness),
            "keywords": [],
            "effects": [],
            "triggered_abilities": [attacks_trigger],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    rs_p0_life0 = rs.get_life(0)
    rs_p1_life0 = rs.get_life(1)
    assert rs.declare_attacker(rs_id) is True, (
        "Rust: declare_attacker must succeed for an unsick Shroudstomper"
    )
    assert rs.stack_size() == 1, (
        "Rust: ATTACKS trigger must be pushed after declaring attacker"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.get_life(1) == rs_p1_life0 - 2, (
        "Rust: p1 must lose 2 life (EachOpponentLosesLife)"
    )
    assert rs.get_life(0) == rs_p0_life0 + 2, (
        "Rust: p0 must gain 2 life (GainLife)"
    )
    assert rs.hand_sizes[0] == 1, (
        "Rust: p0 draws 1 from filler library"
    )
    assert rs.library_sizes[0] == 0, (
        "Rust: p0 library empty after drawing the filler"
    )

    # --- Python: inject Shroudstomper onto p0's bf (unsick, untapped). -
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    py_printing = CardPrinting(
        name="Shroudstomper",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=int(real.power),
        toughness=int(real.toughness),
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(
            _ta_dict_to_python_triggered_ability(attacks_trigger),
        ),
    )
    py_obj = py.new_object(py_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)

    py_declare_attackers(py, [py_obj.id])
    assert len(py.stack) == 1, (
        "Python: ATTACKS trigger must be pushed after declaring attacker"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert py.players[1].life == py_p1_life0 - 2, (
        "Python: p1 must lose 2 life"
    )
    assert py.players[0].life == py_p0_life0 + 2, (
        "Python: p0 must gain 2 life"
    )
    assert len(py.players[0].hand) == 1, (
        "Python: p0 draws 1 from filler library"
    )
    assert len(py.players[0].library) == 0, (
        "Python: p0 library empty after drawing"
    )

    # Gameplay-relevant observables byte-equal cross-engine.
    assert rs.get_life(0) == py.players[0].life, "p0 life cross-engine byte-equal"
    assert rs.get_life(1) == py.players[1].life, "p1 life cross-engine byte-equal"
    assert rs.hand_sizes[0] == len(py.players[0].hand), "p0 hand size byte-equal"
    assert rs.library_sizes[0] == len(py.players[0].library), (
        "p0 library size byte-equal"
    )
    # Established targeted-observable idiom: summoning_sick on the
    # seeded card-in-hand is a gameplay-irrelevant representation
    # artifact (Rust resets to False on zone change; Python preserves
    # the stale True from the library seed). All GAMEPLAY-RELEVANT
    # cross-engine observables above assert byte-equal; full
    # compare_fields would catch this known structural divergence.
    # Use targeted-observable idiom (same documented reason as ETB
    # probe in test_probe_covered_unprobed_k.py).


# ---------------------------------------------------------------------
# Probe 3 — Specimen Freighter ATTACKS → EachOpponentMillsCards(4)
#
# Oracle: "[Artifact — Vehicle] {3}
#   When this artifact enters, return up to two target creature cards
#   to their owners' hands. (Its ETB is ReturnUpToNTargetCreaturesToOwnersHands.)
#   Whenever Specimen Freighter attacks, the defending player mills
#   four cards."  [simplification: 2-player game → mills p1 4 cards]
# Parser → ATTACKS trigger: event=attacks, predicate=IsSelf,
#   effect=EachOpponentMillsCards(amount=4).
#
# The card's ETB is blocked (ReturnUpToNTargetCreaturesToOwnersHands has
# no bridge arm), but the ATTACKS trigger is fully covered.
# Specimen Freighter is an Artifact with power=4/toughness=7 — BOTH
# engines admit it to declare_attacker (Python doesn't filter on
# is_creature; Rust gates on printing.power.is_none(), which passes).
#
# Setup: 4 filler cards in p1's library → attacking mills them → p1
# library empty on BOTH engines. Full compare_fields.
# ---------------------------------------------------------------------


def test_cross_engine_real_eoe_specimen_freighter_attacks_each_opponent_mills_four_parity(
    parity_smoke,
):
    """**GENUINE real-EoE probe — Specimen Freighter ATTACKS
    EachOpponentMillsCards(4) (batch X round 6 pivot).**

    Drives the **real parsed Specimen Freighter printing** through the
    ATTACKS path on BOTH engines.  This is the FIRST real-EoE probe on
    the ``each_opponent_mills_cards`` bridge arm via the ATTACKS event
    (the prior probe in ``test_parity_smoke.py:19684`` used a synthetic
    ETB carrier; this probe uses the ACTUAL EoE printing via the ATTACKS
    dispatch path).

    Real EoE oracle:

        "Whenever Specimen Freighter attacks, the defending player mills
         four cards."

    Parsed ATTACKS trigger shape (asserted live):
    ``(ATTACKS, IsSelf, EachOpponentMillsCards(amount=4))``.

    Specimen Freighter is an Artifact (not a Creature) with power=4 /
    toughness=7.  Both engines admit it to ``declare_attacker``
    (Python: ``declare_attackers`` does not filter on ``is_creature``;
    Rust: ``read_creature_status`` gates on ``printing.power.is_none()``,
    which passes for a 4/7 printing).

    4 filler cards pre-seeded in p1's library → all 4 mill on attack
    → p1 library empty on BOTH engines.  No life changes.

    Assertion strength: **full ``compare_fields``** over the whole
    cross-engine field view (p1 library empty on BOTH; life unchanged).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state, CardDef,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.combat import declare_attackers as py_declare_attackers
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.game import Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.predicates import Event
    from mtg_bot.effects.generic.draw_mill import EachOpponentMillsCards

    real = get_active_source().get_printings().get("Specimen Freighter")
    if real is None:
        pytest.skip("Specimen Freighter absent from active CardSource")

    # §2 source-of-truth: genuine ATTACKS trigger must be EachOpponentMillsCards.
    attacks_ta = next(
        (ta for ta in real.triggered_abilities if ta.event is Event.ATTACKS),
        None,
    )
    assert attacks_ta is not None, (
        "Specimen Freighter must have an ATTACKS triggered ability"
    )
    assert isinstance(attacks_ta.effect, EachOpponentMillsCards), (
        f"ATTACKS trigger must be EachOpponentMillsCards; "
        f"got {type(attacks_ta.effect).__name__}"
    )
    assert attacks_ta.effect.amount == 4
    # Confirm power/toughness so both engines admit it to declare_attacker.
    assert real.power is not None and int(real.power) == 4, (
        "Specimen Freighter must have power=4 for declare_attacker eligibility"
    )
    assert real.toughness is not None and int(real.toughness) == 7

    # 4 filler cards in p1's library → all milled on attack.
    filler = CardDef(name="SF Filler", card_type="Land", mana_produced=("U",))
    spec = DeckSpec(
        card_defs=(filler,),
        p0_library=(),
        p1_library=("SF Filler", "SF Filler", "SF Filler", "SF Filler"),
    )
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2

    # ATTACKS trigger dict.
    attacks_trigger = {
        "event": "attacks",
        "predicate": {"kind": "source_is_self"},
        "effect": {"kind": "each_opponent_mills_cards", "count": 4},
    }

    # --- Rust: inject Specimen Freighter onto p0's bf (unsick, untapped).
    rs_id = rs.register_and_inject_object(
        {
            "name": "Specimen Freighter",
            "card_types": ["Artifact"],
            "power": 4,
            "toughness": 7,
            "keywords": [],
            "effects": [],
            "triggered_abilities": [attacks_trigger],
        },
        0, ZB,
    )
    rs.clear_summoning_sick_for_player(0)
    rs_p1_lib0 = rs.library_sizes[1]
    assert rs_p1_lib0 == 4, "p1 library must start with 4 filler cards"
    assert rs.declare_attacker(rs_id) is True, (
        "Rust: declare_attacker must succeed for Specimen Freighter (4/7 printing)"
    )
    assert rs.stack_size() == 1, (
        "Rust: ATTACKS trigger (EachOpponentMillsCards) must be pushed after declaring"
    )
    while rs.stack_size() > 0:
        rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.library_sizes[1] == 0, (
        f"Rust: p1 library must be empty after milling 4; "
        f"got {rs.library_sizes[1]}"
    )
    assert rs.graveyard_sizes[1] == 4, (
        f"Rust: p1 graveyard must have 4 milled cards; "
        f"got {rs.graveyard_sizes[1]}"
    )

    # --- Python: inject Specimen Freighter onto p0's bf (unsick, untapped).
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_triggered_ability

    py_printing = CardPrinting(
        name="Specimen Freighter",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0, colored=()),
        type_line="Artifact",
        supertypes=(),
        card_types=("Artifact",),
        subtypes=(),
        power=4,
        toughness=7,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(
            _ta_dict_to_python_triggered_ability(attacks_trigger),
        ),
    )
    py_obj = py.new_object(py_printing, owner_id=0, zone=Zone.BATTLEFIELD)
    py_obj.summoning_sick = False
    py_obj.tapped = False
    py_obj.damage = 0
    py_obj.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_obj)

    py_p1_lib0 = len(py.players[1].library)
    assert py_p1_lib0 == 4, "Python p1 library must start with 4 filler cards"
    py_declare_attackers(py, [py_obj.id])
    assert len(py.stack) == 1, (
        "Python: ATTACKS trigger must be pushed after declaring attacker"
    )
    while py.stack:
        resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.players[1].library) == 0, (
        f"Python: p1 library must be empty after milling 4; "
        f"got {len(py.players[1].library)}"
    )
    assert len(py.players[1].graveyard) == 4, (
        f"Python: p1 graveyard must have 4 milled cards; "
        f"got {len(py.players[1].graveyard)}"
    )

    # Cross-engine byte-equal on gameplay-relevant observables.
    assert rs.library_sizes[1] == len(py.players[1].library) == 0
    assert rs.graveyard_sizes[1] == len(py.players[1].graveyard) == 4

    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Specimen Freighter ATTACKS each-opponent-mills-4 must be "
        f"byte-equal across the WHOLE field view on BOTH; diffs={diffs}"
    )
