"""Genuine real-EoE cross-engine byte-equality probes -- batch BBBB
(round 28; **first 4-letter probe batch -- alphabetic 3-letter naming
exhausted by ZZZ**).

One card from the ``covered_by_construction`` tier is upgraded to the
``PROBED`` tier by this module via the QQQ-established
``register_and_inject_object`` cross-engine spell-effect idiom
(``tests/test_probe_remaining_qqq.py``:404 Dark Endurance / :645 Enter
the Enigma):

  * **Withering Torment** -- Instant ``spell_effect = Sequence(
    DestroyTargetCreature(targets=(TargetSpec(filter=OneOf(IsCreature,
    IsEnchantment)),)), LoseLife(amount=2))``.  Bridge spell-effect:
    ``{"kind": "sequence", "effects": [{"kind": "destroy_target",
    "target": {"kind": "any_creature"}}, {"kind": "lose_life",
    "amount": 2}]}``.

    **NEW shape coverage:** the FIRST probe to drive a ``Sequence``
    composition of ``destroy_target`` + ``lose_life`` as a spell
    effect.  Prior coverage:
      * ``destroy_target`` bridge arm: pinned by Murder (PROBED,
        ``DestroyTargetCreature`` standalone spell-effect).
      * ``lose_life`` bridge arm: pinned at the synthetic-ETB-trigger
        level (round 24 ``test_cross_engine_synthetic_etb_lose_life_
        cross_controller_routes_to_source_controller_parity`` at
        ``test_parity_smoke.py``:51159) but **NOT as a SPELL EFFECT
        INSIDE A SEQUENCE**.  Withering Torment is the FIRST probe to
        drive ``lose_life`` in the spell-resolution code path as an
        ordered second effect after a target-bearing destroy.

    The bridge construction is bridge-narrowed per the QQQ Dark
    Endurance precedent: the genuine printing's
    ``DestroyTargetCreature`` carries a ``OneOf(IsCreature,
    IsEnchantment)`` filter (Withering Torment's printed broader scope
    "target creature or enchantment"); Rust's ``parse_target_filter``
    accepts only ``any_creature`` / ``any_player`` (cards.rs:2790-2799).
    Constructing the Python carrier from the bridge dict narrows the
    filter to ``IsCreature()`` only.  The synthetic defender bf seats
    only creature fillers, collapsing the asymmetry: both engines
    pick the same creature filler, destroy it, then apply -2 life to
    the spell's controller.

DROPPED ON VERIFY (honest discipline + divergence-pin handoff)
--------------------------------------------------------------

  * **Vanish from Sight** (Instant Sequence(OwnerPutsTargetArtifact
    OrCreatureOnTopOrBottomOfLibrary(nonland_permanent=True),
    Surveil(1))): **probe attempt surfaced a SUMMONING-SICK
    DIVERGENCE on the bounce-to-library path**.  Rust sets
    ``summoning_sick=True`` on the bounced object as it transitions
    battlefield -> top-of-library; Python's bounce path
    (``effects/generic/zone_moves.py``) does NOT stamp
    ``summoning_sick`` -- the bounced object retains its pre-bounce
    ``summoning_sick=False``.  The post-resolve field view differs on
    ``library_p1`` only in the ``summoning_sick`` slot (Python:
    ``('VFS Bounce Target', 0, 0, 0, 0, None, 1, 1)``; Rust:
    ``('VFS Bounce Target', 0, 1, 0, 0, None, 1, 1)`` -- 3rd slot is
    ``summoning_sick``).  This is the SAME class of asymmetry the ZZZ
    docstring (``tests/test_probe_remaining_zzz.py``:59-86) flagged
    for the exile-bf-leave path (Trapped in the Screen drop), now
    surfaced on a sibling battlefield-leave-via-library path.  Per
    the lane discipline ("If a candidate card fails byte-equality,
    do NOT fix the probe to pass -- that's masking a real divergence.
    Instead, characterize the divergence and treat it as a
    divergence pin candidate for a sibling lane."), Vanish from
    Sight is DROPPED.  A sibling-lane divergence pin should pin
    this bounce-to-library-summoning-sick asymmetry (parallel to the
    ZZZ-flagged exile divergence; the canonical CR ruling is that
    an object's status leaving the battlefield does not reset
    summoning_sick -- the next time it enters bf, it does -- so the
    cleanup is on the Rust side rather than Python).

  * **Violent Urge** (Instant PumpTargetCreatureUntilEOT(+1/+0, first
    strike)): bit-identical SHAPE to the already-PROBED Dark Endurance
    (QQQ, ``tests/test_probe_remaining_qqq.py``:404) -- both are
    ``PumpTargetCreatureUntilEOT`` spell-effects driven through the
    same ``pump_target_creature_until_eot`` bridge arm.  The only
    delta is the numeric ``power_bonus`` value (1 vs. 2) which is a
    bridge dict field, NOT a structural shape change.  Honest
    exhaustion -- the SHAPE is pinned by Dark Endurance.

  * **Horrid Vigor** / **Dual-Sun Technique** / **Rig for War** /
    **Give In to Violence** (Instant PumpTargetCreatureUntilEOT,
    various power/toughness/keyword combos): same honest-exhaustion
    drop as Violent Urge above -- all are ``PumpTargetCreatureUntilEOT``
    spell-effects, the SHAPE is pinned by Dark Endurance (QQQ).  The
    bridge arm is identical; only the field values + Python-side
    keyword-grant riders differ (and the keyword grants are bridge-
    invisible per the QQQ Dark Endurance docstring "the OOO bridge-
    narrowing discipline").

  * **Unwanted Remake** (Instant DestroyTargetCreature(targets=
    (TargetSpec(IsCreature),))): bit-identical SHAPE to the already-
    PROBED Murder (``test_parity_smoke.py`` Murder probe) -- both are
    ``DestroyTargetCreature`` spell-effects with the same target
    filter and same default rider values.  Honest exhaustion.

  * **Break Down the Door** / **Under the Skin** (Instant/Sorcery
    ManifestDread spell): bit-identical SHAPE to the already-PROBED
    SSS ``test_cross_engine_real_eoe_manifest_dread_spell_empty_lib_
    parity`` (round 23, ``tests/test_probe_remaining_sss.py``:266) --
    all drive the bare ``ManifestDread(count=1)`` spell-effect through
    the same bridge arm.  Honest exhaustion.

  * **Split Up** / **Let's Play a Game** (Sorcery ModalChooseOne):
    ``ModalChooseOne(DestroyAllCreatures(tapped_only=True),
    DestroyAllCreatures(untapped_only=True))`` -- the
    ``destroy_all_creatures`` bridge arm has no
    ``tapped_only`` / ``untapped_only`` mirror (cross_engine.py:4710-
    4722 "Field shape" note; Rust's variant is the unrestricted Wrath
    only).  A bridge-narrowed probe would diverge from the real card's
    semantics (Rust would destroy ALL creatures, Python would destroy
    only the narrowed subset).  Deferred -- needs a parameterized
    Rust Effect variant first.

  * **Unnerving Grasp** (Sorcery Sequence(ReturnTargetCreatureToOwners
    Hand(allow_nonland_permanent=True, optional=True), ManifestDread
    (1))): the genuine printing's ``ReturnTargetCreatureToOwnersHand``
    is OPTIONAL (the caster may decline to bounce) and the printed
    scope is broader than creature-only ("target nonland permanent").
    Bridge ``return_to_hand`` arm produces ``Bounce(targets=
    (TargetSpec(IsCreature()),))`` with ``optional=False`` (default);
    the bridge-narrowed Python construction would force the bounce
    (not optional) and narrow to creatures only.  Hypothetically
    probable via bridge-narrowing, but the OPTIONAL flag's agent-
    confirm semantics add Python-side decision-callback surface
    that's load-bearing for full bridge-narrowing correctness, AND
    the bounce path may surface the same summoning-sick divergence
    Vanish from Sight hit.  Deferred -- a sibling-lane divergence pin
    on the bounce path is the prerequisite cleanup.

  * **Lithobraking** (Instant Sequence(CreateToken(Lander),
    OptionalSacArtifactForEffect(DealNDamageToEachCreature(2)))):
    the ``OptionalSacArtifactForEffect`` Python class wraps an inner
    effect behind an opt-in sacrifice gate.  Rust has no
    ``Effect::OptionalSacArtifactForEffect`` variant (it would need
    a new Rust Effect with composable inner-effect storage).  No
    bridge arm.  Deferred -- needs a new Rust Effect substrate first.

  * **Temporal Intervention** (Sorcery TargetOpponentDiscardsCaster
    Choice): bridge ``discard_card`` arm produces ``TargetOpponent
    Discards(count=1)`` (cross_engine.py:2486-2530) -- the
    OPPONENT-PICKS variant.  The genuine printing's
    ``TargetOpponentDiscardsCasterChoice`` is the CASTER-PICKS variant
    (Temporal Intervention's printed text: "You choose").  Bridge-
    narrowing to opponent-picks would invert the choice agency on
    Python; the synthetic carrier construction would pin
    ``TargetOpponentDiscards`` (opponent-picks), NOT the genuine
    ``TargetOpponentDiscardsCasterChoice`` (caster-picks).  This
    breaks the "drives the actual parsed printing on Python"
    principle.  Deferred -- needs a new Rust ``Effect::TargetOpponent
    DiscardsCasterChoice`` variant + parse + bridge first (sister-arm
    convention).

  * **Sami, Ship's Engineer** (Creature BEGINNING_OF_END_STEP
    Controlled(YOU) ConditionalOnTappedCreatures(CreateToken(2/2
    Robot))): the outer ConditionalOnTappedCreatures shape is pinned
    by Dawnstrike Vanguard (PROBED).  The inner ``CreateToken`` arm
    is bridged but requires probe-time
    ``register_token_printing(pid, py_printing)`` setup
    (cross_engine.py:2143-2173) for the Robot token's Python-side
    CardPrinting registration.  Hypothetically probable but adds
    multi-axis composer-plus-token-registration scaffolding beyond
    the simple Withering Torment shape that already lands a NEW
    primitive coverage axis.  Deferred to a follow-up batch focused
    on token-registration probes (see Dockworker Drone's ENTERS
    PutPlusOneCounterOnSelf probe, ``test_probe_covered_unprobed_a.
    py``:272, as the template).

  * **Broodguard Elite** (Creature LEAVES_BATTLEFIELD IsSelf
    MoveSelfCountersToTargetCreatureYouControl): the
    ``move_self_counters_to_target_creature_you_control`` bridge arm
    is pinned at the bridge-translator unit level only; the DIES
    sibling shape is PROBED via Dockworker Drone (``test_probe_
    covered_unprobed_a.py``).  Broodguard's LEAVES_BATTLEFIELD is a
    SUPERSET event (fires on exile/bounce + DIES); driving the probe
    via DIES would replicate Dockworker, and driving via
    non-DIES-leave (bounce-to-hand, exile) hits the bounce / exile
    side of the same summoning-sick asymmetry Vanish from Sight
    surfaced (or the parallel exile-summoning-sick gap the ZZZ
    docstring flagged via Trapped in the Screen).  Deferred until
    the divergence-pin cleanup lands.

  * **Funeral Room // Awakening Hall** (Enchantment ENTERS IsSelf
    ReturnAllCreaturesFromYourGraveyardToBattlefield): Room subsystem
    + cascade ETB-fan-out makes the probe shape multi-axis; the bare
    bridge arm is unit-variant and ships per round-27 round-trip-
    surface-coverage rule but no EoE-pool probe lands cleanly without
    plumbing Room's two-half mechanic.  Deferred per round-17/18/19
    synthetic-only-when-riders-cascade precedent.

  * **All ZZZ + YYY drop-list entries (re-confirmed)** -- the ZZZ +
    YYY docstrings enumerate honest-exhaustion drops for rounds 26-27
    that apply equally here (Innocuous Rat, DDD pin cards, TTT pin
    cards, Cult Healer / Clammy Prowler / Irreverent Gremlin / Mirror
    Room // Fractured Realm / Optimistic Scavenger / Balemurk Leech /
    Cosmogrand Zenith / Station Monitor / Sunstar Lightsmith / Illvoi
    Operative / DEALS_COMBAT_DAMAGE family / Skystinger / Hand That
    Feeds / Flesh Burrower / Meltstrider Eulogist / pure-vanilla
    creatures / basic lands / Magus of the Moon / activated-ability
    cards / Weapons Manufacturing).

COVERED-BY-CONSTRUCTION -> PROBED (this module)
-----------------------------------------------
One card moves from ``covered_by_construction`` to the ``PROBED`` tier
upon merge.  Prior PROBED count (with ZZZ wired in via PROBE_MODULES,
after the post-Sothera+Requiem state on main HEAD 5f56ac56): 219 ->
220 (+1).  Prior covered count: 105 -> 104 (-1).
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
    """Load ``scripts/parity_smoke.py`` as a module."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "parity_smoke.py"
    spec = importlib.util.spec_from_file_location("parity_smoke", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parity_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Probe 1 -- Withering Torment: Instant Sequence(
#   DestroyTargetCreature(targets=(TargetSpec(OneOf(IsCreature,
#     IsEnchantment)),)),
#   LoseLife(amount=2)
# )
#   Bridge spell-effect: sequence{effects:[
#     destroy_target{target:{kind: "any_creature"}},
#     lose_life{amount:2}
#   ]}
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_withering_torment_destroy_then_lose_life_parity(
    parity_smoke,
):
    """**GENUINE real-EoE cross-engine probe -- Withering Torment
    (round 28 BBBB, Instant Sequence(DestroyTargetCreature,
    LoseLife(2))).**

    Drives a synthetic Instant carrier (constructed from the bridge
    spell-effect dict) on BOTH engines.  The real Withering Torment
    printing is verified at probe entry for shape but NOT used to drive
    resolution -- per the QQQ Dark Endurance precedent, the genuine
    printing's ``OneOf(IsCreature, IsEnchantment)`` filter widens the
    legal-target pool beyond Rust's ``parse_target_filter`` allowlist
    (which accepts only ``any_creature`` / ``any_player``; cards.rs:
    2790-2799).  Constructing the Python carrier from the bridge dict
    narrows the filter to ``IsCreature()`` only -- the synthetic
    defender bf seats only creature fillers, collapsing the asymmetry.

    **NEW shape coverage:** the FIRST probe to drive a ``Sequence``
    composition of ``destroy_target`` + ``lose_life`` as a spell
    effect.  Prior coverage:
      * ``destroy_target`` bridge arm: pinned by Murder (PROBED,
        ``DestroyTargetCreature`` standalone spell-effect).
      * ``lose_life`` bridge arm: pinned at the synthetic-ETB-trigger
        level (round 24 ``test_cross_engine_synthetic_etb_lose_life_
        cross_controller_routes_to_source_controller_parity`` at
        ``test_parity_smoke.py``:51159) but **NOT as a SPELL EFFECT
        INSIDE A SEQUENCE**.  Withering Torment is the FIRST probe to
        drive ``lose_life`` in the spell-resolution code path as an
        ordered second effect after a target-bearing destroy.

    Bridge spell-effect dict::

        {
            "kind": "sequence",
            "effects": [
                {"kind": "destroy_target",
                 "target": {"kind": "any_creature"}},
                {"kind": "lose_life", "amount": 2},
            ],
        }

    Setup:
      * p0 has Withering Torment (synthetic) on its hand.
      * p1 has a filler 2/2 Creature on the battlefield (the only
        legal target on both engines -- any_creature filter; not
        indestructible so the destroy will succeed).
      * p0 has no permanents and starts at 20 life.
      * p1 starts at 20 life (unaffected -- lose_life applies to the
        SOURCE's controller, NOT the opponent).

    Resolution flow:
      1. Rust: ``resolve_top_of_stack`` walks the bridged Sequence;
         child[0] = destroy_target picks the p1 filler (the I75
         controller-of-effect routing: defender = 1 -
         source_controller = 1; scans p1's bf top-to-bottom for first
         creature).  The p1 filler is destroyed to p1's graveyard (CR
         702.12 gate passes -- not indestructible).  Child[1] =
         lose_life(2) applies -2 life to p0 (the source's controller).
      2. Python: ``resolve_top_of_stack`` walks the synthetic
         Sequence; child[0] = ``DestroyTargetCreature(targets=
         (TargetSpec(IsCreature()),))``; the targeting pipeline picks
         p1's filler via the ``_PickFirstOpponentTargetAgent`` shim
         on p0's agent slot.  ``Destroy.resolve`` re-verifies the
         IsCreature filter at fire time (CR 608.2b) before invoking
         ``turn.destroy(state, obj)``.  Child[1] = ``LoseLife(amount
         =2)``; applies -2 life to p0 (the spell's controller).

    Observables (byte-equal across the full field view):
      * p1's filler: bf -> p1's graveyard (destroyed).
      * p0 life: 20 -> 18 on BOTH engines (-2 from LoseLife).
      * p1 life: 20 (unchanged) on BOTH engines.
      * p0 graveyard: 0 -> 1 card on BOTH engines (the Withering
        Torment spell itself).
      * p1 graveyard: 0 -> 1 card on BOTH engines (the destroyed
        filler creature).
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, build_rust_state,
        build_python_field_view, compare_fields,
        parity_smoke as ce_parity_smoke,
        _ta_dict_to_python_effect,
    )
    from mtg_bot.cards.source import get_active_source
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards.base import CardPrinting, ManaCost
    from mtg_bot.game import StackItem, Zone
    from mtg_bot.turn import state_based_actions as py_sba
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.destroy import (
        Destroy,
        DestroyTargetCreature,
    )
    from mtg_bot.effects.generic.life import LoseLife
    from tests.parity._picker_shims import _PickFirstOpponentTargetAgent

    # ------------------------------------------------------------------
    # 1. Verify the genuine parsed Withering Torment printing.
    # ------------------------------------------------------------------
    real = get_active_source().get_printings().get("Withering Torment")
    if real is None:
        pytest.skip("Withering Torment absent from active CardSource")
    assert "Instant" in real.card_types, (
        "Withering Torment must be an Instant"
    )
    se = real.spell_effect
    assert isinstance(se, Sequence), (
        f"genuine Withering Torment spell_effect must be Sequence; "
        f"got {type(se).__name__}"
    )
    assert len(se.effects) == 2, (
        f"Withering Torment Sequence must have 2 child effects; "
        f"got {len(se.effects)}"
    )
    assert isinstance(se.effects[0], DestroyTargetCreature), (
        f"Withering Torment Sequence[0] must be DestroyTargetCreature; "
        f"got {type(se.effects[0]).__name__}"
    )
    # The genuine printing has or_enchantment=True (its OneOf filter
    # spans creature OR enchantment); the bridge narrows to creature-
    # only (Rust's allowlist).
    assert se.effects[0].or_enchantment is True, (
        f"Withering Torment printing carries or_enchantment=True; "
        f"got {se.effects[0].or_enchantment}"
    )
    assert isinstance(se.effects[1], LoseLife), (
        f"Withering Torment Sequence[1] must be LoseLife; "
        f"got {type(se.effects[1]).__name__}"
    )
    assert se.effects[1].amount == 2, (
        f"Withering Torment LoseLife amount must be 2; "
        f"got {se.effects[1].amount}"
    )

    # ------------------------------------------------------------------
    # 2. Build the bridge spell-effect dict.
    # ------------------------------------------------------------------
    wt_effect_dict = {
        "kind": "sequence",
        "effects": [
            {
                "kind": "destroy_target",
                "target": {"kind": "any_creature"},
            },
            {"kind": "lose_life", "amount": 2},
        ],
    }
    bridge_effect = _ta_dict_to_python_effect(wt_effect_dict)
    assert isinstance(bridge_effect, Sequence), (
        f"Bridge effect must be Sequence; got {type(bridge_effect).__name__}"
    )
    # Bridge produces base ``Destroy`` (the destroy_target bridge arm
    # at cross_engine.py:2715-2745) rather than the
    # ``DestroyTargetCreature`` subclass; both share ``Destroy.resolve``
    # and the same ``IsCreature`` slot filter.
    assert isinstance(bridge_effect.effects[0], Destroy), (
        f"Bridge effects[0] must be Destroy (or subclass); got "
        f"{type(bridge_effect.effects[0]).__name__}"
    )
    assert isinstance(bridge_effect.effects[1], LoseLife), (
        f"Bridge effects[1] must be LoseLife; got "
        f"{type(bridge_effect.effects[1]).__name__}"
    )
    assert bridge_effect.effects[1].amount == 2, (
        f"Bridge LoseLife amount must be 2; got "
        f"{bridge_effect.effects[1].amount}"
    )

    # ------------------------------------------------------------------
    # 3. Build cross-engine states (empty decks).
    # ------------------------------------------------------------------
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    rs = build_rust_state(spec)
    ZB = 2  # ZONE_BATTLEFIELD
    ZH = 0  # ZONE_HAND

    py.players[0].agent = _PickFirstOpponentTargetAgent()

    # ------------------------------------------------------------------
    # 4. Rust: seat the destroy-target filler 2/2 on p1's bf, then push
    # synthetic Withering Torment with the bridge spell_effect onto the
    # stack.
    # ------------------------------------------------------------------
    rs_filler_id = rs.register_and_inject_object(
        {
            "name": "WT Destroy Target",
            "card_types": ["Creature"],
            "power": 2,
            "toughness": 2,
            "triggered_abilities": [],
        },
        1, ZB,
    )
    rs_p0_life_before = rs.get_life(0)
    rs_p1_life_before = rs.get_life(1)
    rs_p0_gy_before = len(rs.graveyard_snapshot(0))
    rs_p1_gy_before = len(rs.graveyard_snapshot(1))

    rs_spell_id = rs.register_and_inject_object(
        {
            "name": "Withering Torment",
            "card_types": ["Instant"],
            "effects": [wt_effect_dict],
        },
        0, ZH,
    )
    rs.push_to_stack(rs_spell_id, 0)
    assert rs.stack_size() == 1, (
        f"Rust: Withering Torment must be on the stack; "
        f"got {rs.stack_size()}"
    )
    rs.resolve_top_of_stack()
    rs.apply_sbas()
    assert rs.stack_size() == 0, (
        f"Rust: stack must be empty after the spell resolves; "
        f"got {rs.stack_size()}"
    )
    # p1's filler destroyed -> p1 graveyard +1.
    assert len(rs.graveyard_snapshot(1)) == rs_p1_gy_before + 1, (
        f"Rust: p1 graveyard must grow by 1 (destroyed filler); "
        f"before={rs_p1_gy_before} after={len(rs.graveyard_snapshot(1))}"
    )
    # p0 lost 2 life from LoseLife (source's controller = p0).
    assert rs.get_life(0) == rs_p0_life_before - 2, (
        f"Rust: p0 life must drop by 2 (LoseLife); "
        f"before={rs_p0_life_before} after={rs.get_life(0)}"
    )
    # p1 unchanged (lose_life applies to source's controller, not
    # opponent).
    assert rs.get_life(1) == rs_p1_life_before, (
        f"Rust: p1 life must remain unchanged; "
        f"before={rs_p1_life_before} after={rs.get_life(1)}"
    )
    # Spell moved to caster's graveyard.
    assert len(rs.graveyard_snapshot(0)) == rs_p0_gy_before + 1, (
        f"Rust: p0 graveyard must grow by 1 (Withering Torment); "
        f"before={rs_p0_gy_before} after={len(rs.graveyard_snapshot(0))}"
    )

    # ------------------------------------------------------------------
    # 5. Python: seat the destroy-target filler 2/2 on p1's bf, then
    # push synthetic Withering Torment with the bridge spell_effect onto
    # the stack (NOT the genuine printing -- per the bridge-narrowing
    # discipline; see docstring).
    # ------------------------------------------------------------------
    py_filler_printing = CardPrinting(
        name="WT Destroy Target",
        mana_cost_str="",
        mana_cost=ManaCost(generic=0),
        type_line="Creature",
        supertypes=(),
        card_types=("Creature",),
        subtypes=(),
        power=2,
        toughness=2,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
    )
    py_filler = py.new_object(
        py_filler_printing, owner_id=1, zone=Zone.BATTLEFIELD,
    )
    py_filler.summoning_sick = False
    py_filler.tapped = False
    py_filler.damage = 0
    py_filler.etb_timestamp = py.next_timestamp
    py.next_timestamp += 1
    py.battlefield.append(py_filler)

    py_p0_life_before = py.players[0].life
    py_p1_life_before = py.players[1].life
    py_p0_gy_before = len(py.players[0].graveyard)
    py_p1_gy_before = len(py.players[1].graveyard)

    # Construct a synthetic Withering Torment printing using the bridge
    # spell_effect (bare any_creature filter) -- the bridge-narrowing
    # idiom.
    py_wt_printing = CardPrinting(
        name="Withering Torment",
        mana_cost_str="{1}{B}",
        mana_cost=ManaCost(generic=1, colored=(("B", 1),)),
        type_line="Instant",
        supertypes=(),
        card_types=("Instant",),
        subtypes=(),
        power=None,
        toughness=None,
        produces=frozenset(),
        keywords=frozenset(),
        triggered_abilities=(),
        spell_effect=bridge_effect,
    )
    py_spell = py.new_object(
        py_wt_printing, owner_id=0, zone=Zone.STACK,
    )
    py_spell.summoning_sick = False
    py.stack.append(
        StackItem(source=py_spell, controller_id=0,
                  targets=(("creature", py_filler.id),))
    )

    resolve_top_of_stack(py)
    py_sba(py)
    assert len(py.stack) == 0, (
        f"Python: stack must be empty after the spell resolves; "
        f"got {len(py.stack)}"
    )
    # p1's filler destroyed -> p1 graveyard +1.
    assert len(py.players[1].graveyard) == py_p1_gy_before + 1, (
        f"Python: p1 graveyard must grow by 1 (destroyed filler); "
        f"before={py_p1_gy_before} "
        f"after={len(py.players[1].graveyard)}"
    )
    # p0 lost 2 life.
    assert py.players[0].life == py_p0_life_before - 2, (
        f"Python: p0 life must drop by 2 (LoseLife); "
        f"before={py_p0_life_before} after={py.players[0].life}"
    )
    # p1 unchanged.
    assert py.players[1].life == py_p1_life_before, (
        f"Python: p1 life must remain unchanged; "
        f"before={py_p1_life_before} after={py.players[1].life}"
    )
    # Spell moved to caster's graveyard.
    assert len(py.players[0].graveyard) == py_p0_gy_before + 1, (
        f"Python: p0 graveyard must grow by 1 (Withering Torment); "
        f"before={py_p0_gy_before} "
        f"after={len(py.players[0].graveyard)}"
    )

    # ------------------------------------------------------------------
    # 6. Cross-engine byte-equality across the WHOLE field view.
    # ------------------------------------------------------------------
    diffs = compare_fields(
        build_python_field_view(py),
        ce_parity_smoke()._build_field_view(rs),
    )
    assert diffs == [], (
        f"Withering Torment destroy-then-lose-life must be byte-equal "
        f"across the WHOLE field view on BOTH engines; diffs={diffs}"
    )
